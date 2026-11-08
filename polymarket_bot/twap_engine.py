"""Replacement live engine: frozen14:00 TWAP/spot signal, FOK and durable state."""
import asyncio
from contextlib import suppress
from decimal import Decimal
import hashlib
import json
import logging
import signal
import time

from .geography import geographic_check
from .polymarket_api import PolymarketLiveExecutor
from .polygon_rpc import check_polygon_approvals
from .twap_config import STRATEGY
from .twap_execution import TwapPublic,reference_cap,check_book,check_signed
from .twap_feed import ChainlinkFeed
from .twap_signal import decide
from .twap_store import TwapStore,encoded

logger = logging.getLogger('polymarket_bot.twap')
D = Decimal


class TwapBot:
    def __init__(self, settings, *, now_ms=None):
        self.settings = settings
        self.now_ms = now_ms or (lambda:time.time_ns()//1000000)
        self.store = TwapStore(settings.state_path,settings.decision_log_path,settings.oracle_log_path)
        self.feed = ChainlinkFeed(self.store,self.now_ms)
        self.api = TwapPublic(settings)
        self.executor = PolymarketLiveExecutor(settings)
        self.stop = asyncio.Event()
        self.market_cache = {}
        self.done = set()
        self.metadata_retry_at = 0
        self.reconcile_at = 0
        self.heartbeat_at = 0
        self.clock_ok = False

    async def start(self, *, check_trading_ready=True, collect_prices=True):
        self.settings.require_account()
        self.store.acquire_process_lock()
        if self.settings.mode == 'live':
            self.store.bind_account(self.settings.wallet_address)
            self.store.import_legacy(self.settings.legacy_state_path)
        await self.api.sync_clock()
        self.clock_ok = abs(self.api.server_clock_offset_ms) <= 1500
        if not self.clock_ok:
            raise RuntimeError('Clock differs from CLOB by more than1.5s; enable system time synchronization')
        if self.settings.mode == 'live' and check_trading_ready:
            geo = geographic_check(await self.api.geoblock())
            if not geo.get('new_order_network_check'):
                raise RuntimeError('Polymarket did not allow new orders from this server network')
        await self.executor.connect(check_balance=self.settings.mode=='live' and check_trading_ready)
        if self.settings.mode == 'live' and check_trading_ready:
            # Perform allowance work before the entry window, never by retrying
            # a post after the signal/quote guards have expired.
            approvals = await check_polygon_approvals(self.executor.client)
            if approvals['missing_erc20'] or approvals['missing_erc1155']:
                await self.executor.client.setup_trading_approvals()
            self.store.log('polygon_rpc_ready', approvals)
            logger.info('Polygon RPC %s: approvals checked on chain %s',
                        approvals['host'], approvals['chain_id'])
        if collect_prices:
            self.feed.start(self.executor.client)
        self.store.log('twap_started',dict(mode=self.settings.mode,strategy=STRATEGY,
            entry_seconds=840,max_submit_seconds=self.settings.max_entry_delay_seconds,
            stake_target=20,max_submissions=self.settings.live_max_orders,
            reference_floor='.85',cap_padding='.01',minimum_lead_bps=5,
            spot_filter='up:spot>=twap; down:spot<=twap',exit='hold_to_resolution',
            daily_loss_stop=self.settings.daily_loss_stop,auto_redeem=self.settings.auto_redeem))
        logger.info('TWAP runtime started: %s, $20 target, at most%s lifetime submissions',
                    self.settings.mode,self.settings.live_max_orders)

    def current_signal(self, start, when, fixed_side=None):
        return decide(self.store.opening(start*1000),self.feed.twap,self.feed.spot,when,
                      self.settings.minimum_lead_bps,fixed_side)

    async def freeze(self, start, record):
        slug = record['parsed']['slug']
        previous = self.store.frozen(slug)
        if previous is not None:
            return previous
        due = start+840
        oracle,why = self.current_signal(start,due*1000)
        if oracle is None:
            return self.store.freeze(slug,None,why)
        if self.store.db.execute('SELECT 1 FROM legacy WHERE slug=?',(slug,)).fetchone():
            return self.store.freeze(slug,None,'legacy_market_already_attempted')
        metadata = record['event'].get('eventMetadata') or {}
        if metadata.get('priceToBeat') is not None and abs(D(str(metadata['priceToBeat']))-D(str(oracle['opening']['value']))) > D('.01'):
            return self.store.freeze(slug,None,'official_opening_disagrees_with_recorded_twap')
        token = record['parsed']['tokens'][oracle['direction']]
        history = await self.api.price_history(token,start,due)
        try:
            reference,cap = reference_cap(history,due,record['tick'],self.settings)
        except ValueError as error:
            return self.store.freeze(slug,None,str(error))
        payload = dict(oracle=oracle,reference=reference,cap=cap,token=token,
            direction=oracle['direction'],start=start,condition_id=record['parsed']['condition_id'])
        self.store.log('twap_frozen_signal',dict(slug=slug,**payload))
        return self.store.freeze(slug,payload,'twap_spot_passed')

    def _deadline_ok(self, start):
        return (start+840)*1000 <= self.now_ms() <= (start+self.settings.max_entry_delay_seconds)*1000

    async def _book(self, token, cap, rate, signed_shares=None):
        before = time.monotonic()
        raw = await self.api.raw_book(token)
        received = time.monotonic()
        self.store.log('twap_execution_book',dict(token=token,captured_ms=self.now_ms(),
            request_rtt_ms=round((received-before)*1000,3),raw_book=raw))
        quote = check_book(raw,token,cap,rate,self.settings,
            self.now_ms()+self.api.server_clock_offset_ms,(received-before)*1000,signed_shares)
        return quote,received

    async def submit(self, start, record, frozen):
        settings = self.settings
        payload = frozen['payload']; token = payload['token']; cap = D(payload['cap'])
        side = payload['direction']; slug = record['parsed']['slug']
        rate = D(str(record['fee']['rate']))
        if not self.clock_ok or not self._deadline_ok(start):
            return False
        current,why = self.current_signal(start,self.now_ms(),side)
        if current is None:
            self.store.log('twap_recheck_skip',dict(slug=slug,reason=why))
            return False
        quote,_ = await self._book(token,cap,rate)
        if settings.mode == 'paper':
            self.store.log('twap_paper_candidate',dict(slug=slug,frozen=payload,current=current,book=quote,
                note='Displayed capacity only; no order signed or posted'))
            self.done.add(slug)
            logger.info('Paper TWAP candidate %s %s ask=%s cap=%s',slug,side,quote['best_ask'],cap)
            return True
        # Signing performs metadata/network work but does NOT place an order.
        # Leave1cent within the $20 target for fee rounding.
        signed = await self.executor.client.create_market_order(asset_id=token,side='BUY',
            amount='20',max_spend='19.99',max_price=str(cap),order_type='FOK')
        amounts = check_signed(signed,token,cap,rate,settings)
        geo,_,fresh = await asyncio.gather(self.api.geoblock(),
            self.executor.ensure_balance(D('20'),max_age=0),self.api.market_record(start))
        if not geographic_check(geo).get('new_order_network_check'):
            raise ValueError('network_geoblock_rejected')
        self._active(fresh)
        if fresh['parsed']['tokens'] != record['parsed']['tokens'] or fresh['tick'] != record['tick'] or fresh['fee'] != record['fee']:
            raise ValueError('market_tick_tokens_or_fee_changed_before_post')
        # The last REST book comes AFTER signing, balance/geo/metadata reads.
        quote,received = await self._book(token,cap,rate,amounts['shares'])
        current,why = self.current_signal(start,self.now_ms(),side)
        if current is None or not self._deadline_ok(start):
            self.store.log('twap_final_signal_or_deadline_skip',dict(slug=slug,reason=why))
            return False
        digest = hashlib.sha256(encoded(signed).encode()).hexdigest()
        attempt = self.store.reserve(slug,side,self.now_ms(),D('20'),
            dict(**payload,signed_digest=digest,signed_salt=str(signed.salt),signed_amounts=amounts,
                 final_oracle=current,final_book=quote),settings.live_max_orders,settings.daily_loss_stop)
        self.store.log('twap_live_intent',dict(attempt_id=attempt,slug=slug,side=side,cap=cap,signed_amounts=amounts))
        logger.info('Prepared TWAP FOK #%s %s %s cap=%s',attempt,slug,side,cap)
        # Fsync/SQLite commit may take time: final local guards after reservation.
        current,why = self.current_signal(start,self.now_ms(),side)
        if current is None or not self._deadline_ok(start) or (time.monotonic()-received)*1000 > settings.live_quote_max_age_ms:
            self.store.update(attempt,'aborted_before_submit',dict(reason=why or 'deadline_or_quote_expired'))
            self.done.add(slug)
            return False
        try:
            response = await self.executor.client.post_order(signed)
        except Exception as error:
            self.store.update(attempt,'ambiguous',dict(error_type=type(error).__name__))
            self.store.log('twap_ambiguous_post',dict(attempt_id=attempt,error_type=type(error).__name__))
            self.done.add(slug)
            raise
        result = response.model_dump(mode='json')
        if not response.ok:
            self.store.update(attempt,'rejected',result)
        else:
            self.store.update(attempt,'submitted',result)
            if response.status in {'live','unmatched'}:
                await self.executor.client.cancel_order(order_id=str(response.order_id))
            if response.trade_ids:
                try:
                    hashes = await self.executor.client.wait_for_order_fill_settlement(response,timeout_s=60)
                    result['settlement_hashes'] = list(map(str,hashes))
                    result['settlement_confirmed'] = True
                    self.store.update(attempt,'open',result)
                except Exception as error:
                    self.store.log('twap_fill_awaiting_reconciliation',dict(attempt_id=attempt,error_type=type(error).__name__))
        self.store.log('twap_order_result',dict(attempt_id=attempt,response=result))
        logger.info('TWAP order #%s status=%s',attempt,self.store.order(slug)['status'])
        self.done.add(slug)
        return True

    @staticmethod
    def _active(record):
        event,raw = record['event'],record['parsed']['raw']
        if event.get('closed') or raw.get('closed') or not raw.get('active') or not raw.get('acceptingOrders'):
            raise ValueError('market_not_accepting_orders')

    async def _reconcile_order(self, row):
        result = json.loads(row['response'])
        order_id = result.get('order_id')
        if not order_id:
            return  # Unknown POST without an ID remains blocked, across restarts.
        order = await self.executor.client.get_order(order_id=order_id)
        if order.size_matched == 0:
            if order.status.lower() in {'cancelled','canceled','expired'}:
                self.store.update(row['id'],'rejected',result)
            elif order.status.lower() in {'live','unmatched'}:
                await self.executor.client.cancel_order(order_id=order_id)
            return
        trades = []
        for trade_id in order.associate_trades:
            async for trade in self.executor.client.list_account_trades(id=str(trade_id)):
                if str(trade.id) == str(trade_id):
                    trades.append(trade)
        if trades and len({str(t.id) for t in trades}) == len(order.associate_trades) and all(str(t.status).upper()=='CONFIRMED' for t in trades):
            result['settlement_confirmed'] = True
            result['reconciled_order'] = order.model_dump(mode='json')
            self.store.update(row['id'],'open',result)
        elif trades and len({str(t.id) for t in trades}) == len(order.associate_trades) and all(str(t.status).upper()=='FAILED' for t in trades):
            self.store.update(row['id'],'rejected',result)

    async def _redeem(self, row):
        if not self.settings.auto_redeem or not row['won'] or row['redeem_status'] != 'not_requested':
            return
        payload = json.loads(row['payload'])
        balance = await self.executor.client.get_balance_allowance(asset_type='CONDITIONAL',asset_id=payload['token'])
        if balance.balance == 0:
            self.store.redeem_status(row['id'],'zero_token_balance_or_already_redeemed')
            return
        self.store.redeem_status(row['id'],'started')
        try:
            handle = await self.executor.client.redeem_positions(condition_id=payload['condition_id'])
            self.store.log('twap_redeem_submitted',dict(attempt_id=row['id'],
                transaction_id=getattr(handle,'transaction_id',None),transaction_hash=getattr(handle,'transaction_hash',None)))
            await handle.wait()
        except Exception as error:
            self.store.redeem_status(row['id'],'ambiguous_check_wallet')
            self.store.log('twap_redeem_needs_review',dict(attempt_id=row['id'],error_type=type(error).__name__))
            return
        self.store.redeem_status(row['id'],'confirmed')
        self.store.log('twap_redeemed',dict(attempt_id=row['id'],slug=row['slug']))

    async def reconcile(self):
        if self.settings.mode != 'live':
            return
        for row in self.store.orders({'submitted','ambiguous'}):
            await self._reconcile_order(row)
        for row in self.store.orders({'open'}):
            payload = json.loads(row['payload'])
            if self.now_ms() < (payload['start']+900)*1000:
                continue
            result,_ = await self.api.resolved(payload['start'])
            if result.get('status') == 'confirmed':
                won = result['winner'] == row['side']
                self.store.resolve(row['id'],won,self.now_ms())
                self.store.log('twap_resolved',dict(attempt_id=row['id'],slug=row['slug'],won=won,
                    source='Gamma+CLOB explicit winner; cash PnL requires trade/fee receipts'))
                logger.info('TWAP #%s resolved %s',row['id'],'WIN' if won else 'LOSS')
        for row in self.store.orders({'resolved'}):
            await self._redeem(row)
        for row in self.store.db.execute('SELECT * FROM legacy WHERE reconciled=0').fetchall():
            start = int(row['slug'].rsplit('-',1)[1])
            result,_ = await self.api.resolved(start)
            if result.get('status') == 'confirmed':
                self.store.db.execute('UPDATE legacy SET reconciled=1 WHERE slug=?',(row['slug'],))
                self.store.log('legacy_market_resolved',dict(slug=row['slug'],note='Legacy files preserved; actual wallet balance checked before new orders'))

    async def run_once(self):
        now = self.now_ms(); start = now//900000*900; elapsed = now-start*1000
        slug = f'btc-updown-15m-{start}'
        if slug in self.done or self.store.order(slug):
            return
        if start not in self.market_cache and now >= self.metadata_retry_at:
            try:
                self.market_cache = {start:await self.api.market_record(start)}
            except Exception as error:
                self.metadata_retry_at = now+10000
                self.store.log('twap_market_unavailable',dict(slug=slug,error_type=type(error).__name__))
                return
        record = self.market_cache.get(start)
        if record is None or not 840000 <= elapsed <= self.settings.max_entry_delay_seconds*1000:
            return
        try:
            if self.store.frozen(slug) is None:
                # Tick size/fees can change during the market. Do not freeze a
                # cap using metadata fetched fourteen minutes earlier.
                record = await self.api.market_record(start)
                self.market_cache[start] = record
            self._active(record)
            if self.settings.mode == 'live':
                why = self.store.budget_check(self.now_ms(),self.settings.live_max_orders,self.settings.daily_loss_stop)
                if why:
                    self.done.add(slug)
                    self.store.log('twap_budget_skip',dict(slug=slug,reason=why))
                    logger.info('TWAP skip %s: %s',slug,why)
                    return
            frozen = await self.freeze(start,record)
            if frozen['payload'] is None:
                self.done.add(slug)
                self.store.log('twap_signal_skip',dict(slug=slug,reason=frozen['reason']))
                logger.info('TWAP skip %s: %s',slug,frozen['reason'])
                return
            await self.submit(start,record,frozen)
        except (ValueError,RuntimeError) as error:
            self.store.log('twap_entry_skip',dict(slug=slug,reason=str(error)))
            logger.info('TWAP entry skipped %s: %s',slug,error)

    async def run_forever(self):
        try:
            await self.start()
            loop = asyncio.get_running_loop()
            with suppress(NotImplementedError):
                loop.add_signal_handler(signal.SIGTERM,self.stop.set)
            while not self.stop.is_set():
                try:
                    if self.now_ms() >= self.reconcile_at:
                        self.reconcile_at = self.now_ms()+20000
                        await self.reconcile()
                    if self.now_ms() >= self.heartbeat_at:
                        self.clock_ok = False
                        self.heartbeat_at = self.now_ms()+60000
                        await self.api.sync_clock()
                        self.clock_ok = abs(self.api.server_clock_offset_ms)<=1500
                        now = self.now_ms()
                        self.store.log('twap_heartbeat',dict(strategy=STRATEGY,mode=self.settings.mode,
                            clock_ok=self.clock_ok,feed_connected=self.feed.connected,
                            twap_fresh=self.feed.twap.asof(now) is not None,
                            spot_fresh=self.feed.spot.asof(now) is not None,
                            opening_known=self.store.opening(now//900000*900000) is not None,
                            total_submissions=len(self.store.orders())))
                        logger.info('TWAP heartbeat: clock=%s twap=%s spot=%s opening=%s submissions=%s',
                            self.clock_ok,self.feed.twap.asof(now) is not None,self.feed.spot.asof(now) is not None,
                            self.store.opening(now//900000*900000) is not None,len(self.store.orders()))
                        self.heartbeat_at = now+60000
                    await self.run_once()
                except Exception as error:
                    self.store.log('twap_tick_error',dict(error_type=type(error).__name__))
                    logger.warning('TWAP tick failed: %s',type(error).__name__)
                try:
                    await asyncio.wait_for(self.stop.wait(),timeout=.25)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.close()

    async def close(self):
        await self.feed.close()
        await self.executor.close()
        await self.api.close()
        self.store.close()
