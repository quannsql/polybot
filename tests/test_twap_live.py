import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime,timezone
from decimal import Decimal as D
import json
from types import SimpleNamespace

import pytest

from polymarket_bot.twap_config import TwapSettings,STRATEGY,CONFIRMATION
from polymarket_bot.twap_signal import Observation,PriceBuffer,decide
from polymarket_bot.twap_store import TwapStore
from polymarket_bot.twap_feed import ChainlinkFeed
from polymarket_bot.twap_execution import reference_cap,check_book,check_signed
from polymarket_bot.twap_engine import TwapBot

START = 1794009600 // 900 * 900
DUE = (START+840)*1000


def settings(tmp_path, **changes):
    base = TwapSettings(mode='live',dry_run=False,live_confirmation=CONFIRMATION,
        account_eligibility_confirmed=True,signer_private_key='fake-test-key',
        wallet_address='0x'+'1'*40,relayer_api_key='fake-key',relayer_api_key_address='0x'+'2'*40,
        state_path=tmp_path/'state.sqlite3',decision_log_path=tmp_path/'events.jsonl',
        oracle_log_path=tmp_path/'oracle.jsonl',legacy_state_path=tmp_path/'legacy.json')
    return replace(base,**changes)


def buffers():
    a,b = PriceBuffer(),PriceBuffer()
    for buffer,value in [(a,D('100100')),(b,D('100110'))]:
        buffer.reset(DUE-120000)
        for second in range(779,840):
            observed = (START+second)*1000
            buffer.add(Observation(observed,observed+500,value))
    return a,b


def test_live_entrypoint_replaces_candle_engine():
    import run_bot
    assert run_bot.BotEngine is TwapBot


@pytest.mark.parametrize('change',[
    {'execution_strategy':'legacy_1230_ref85'}, {'decision_delay_seconds':750},
    {'minimum_lead_bps':D('10')}, {'live_fixed_stake_usd':D('21')},
    {'state_path':'bad.json'}, {'dry_run':True}, {'live_confirmation':'old'},
])
def test_new_profile_rejects_stale_or_drifting_live_config(tmp_path,change):
    if 'state_path' in change:
        change['state_path'] = tmp_path/change['state_path']
    with pytest.raises(ValueError):
        settings(tmp_path,**change).validate()


def test_env_does_not_silently_replace_invalid_numbers(monkeypatch):
    monkeypatch.setenv('POLYMARKET_LIVE_MAX_ORDERS','nan')
    with pytest.raises(ValueError,match='Invalid numeric'):
        TwapSettings.from_env()


def test_oracle_filter_uses_exact_source_and_receipt_cutoffs():
    twap,spot = buffers()
    opening = Observation(START*1000,START*1000+800,D('100000'))
    good,reason = decide(opening,twap,spot,DUE)
    assert reason == 'twap_spot_passed' and good['direction'] == 'up'
    spot.add(Observation(DUE-1000,DUE+100,D('100090')))
    # Conflicting same-timestamp revisions poison that timestamp, not overwrite history.
    assert decide(opening,twap,spot,DUE)[0] is not None
    spot.add(Observation(DUE,DUE+100,D('100090')))
    assert decide(opening,twap,spot,DUE+200)[1] == 'oracle_warmup_gap_or_conflict'


def test_down_filter_and_no_switch_of_frozen_side():
    twap,spot = buffers()
    twap.points = {t:replace(p,value=D('99900')) for t,p in twap.points.items()}
    spot.points = {t:replace(p,value=D('99890')) for t,p in spot.points.items()}
    opening = Observation(START*1000,START*1000+800,D('100000'))
    assert decide(opening,twap,spot,DUE)[0]['direction'] == 'down'
    assert decide(opening,twap,spot,DUE,fixed_side='up')[1] == 'direction_changed_before_submit'


def test_snapshot_cannot_instantly_create_a_healthy_minute():
    twap,spot = buffers()
    spot.reset(DUE-1000)
    assert not spot.valid_minute(DUE)
    opening = Observation(START*1000,START*1000+800,D('100000'))
    assert decide(opening,twap,spot,DUE)[0] is None


def test_opening_must_belong_to_this_market_and_arrive_within5s():
    twap,spot = buffers()
    for opening in [Observation((START-900)*1000,START*1000,D('100000')),
                    Observation(START*1000,START*1000+5001,D('100000'))]:
        assert decide(opening,twap,spot,DUE)[0] is None


def test_gap_and_conflicting_prices_block_entry():
    twap,spot = buffers()
    twap.points = {t:p for t,p in twap.points.items() if not DUE-20000<=t<=DUE-10000}
    assert not twap.valid_minute(DUE)


def test_live_reference_cap_matches_old_research_floor_padding_and_tick(tmp_path):
    config = settings(tmp_path)
    ref,cap = reference_cap([{'t':START+791,'p':.955}],START+840,D('.01'),config)
    assert cap == D('.96') and ref['age_seconds'] == 49
    with pytest.raises(ValueError,match='ge_one'):
        reference_cap([{'t':START+791,'p':.995}],START+840,D('.001'),config)


def test_restart_keeps_ambiguous_attempt_and_daily_stop(tmp_path):
    config = settings(tmp_path)
    store = TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    attempt = store.reserve('market1','up',DUE,20,{},5)
    store.update(attempt,'ambiguous',{})
    store.close()
    store = TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    assert store.budget_check(DUE+900000,5) == 'pending_or_unresolved_position'
    store.resolve(attempt,False,DUE+900000)
    assert store.budget_check(DUE+900000,5) == 'daily_loss_stop_utc'
    store.close()


def test_legacy_state_is_preserved_and_already_attempted_market_stays_blocked(tmp_path):
    config = settings(tmp_path)
    old = {'live_attempts':[{'market_slug':f'btc-updown-15m-{START}', 'status':'filled'}]}
    config.legacy_state_path.write_text(json.dumps(old))
    before = config.legacy_state_path.read_bytes()
    store = TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    store.import_legacy(config.legacy_state_path)
    assert store.budget_check(DUE,5) == 'legacy_attempt_needs_reconciliation'
    store.db.execute('UPDATE legacy SET reconciled=1')
    with pytest.raises(RuntimeError,match='legacy_market_already_attempted'):
        store.reserve(f'btc-updown-15m-{START}','up',DUE,20,{},5)
    assert before == config.legacy_state_path.read_bytes()
    store.close()


def test_wallet_binding_and_permanent_opening_conflict(tmp_path):
    config = settings(tmp_path)
    store = TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    store.bind_account('0x1111')
    with pytest.raises(RuntimeError,match='different wallet'):
        store.bind_account('0x2222')
    store.record_opening(Observation(START*1000,START*1000+800,D('100000')))
    store.record_opening(Observation(START*1000,START*1000+900,D('100001')))
    assert store.opening(START*1000) is None
    store.close()


def test_only_one_process_can_use_the_live_journal(tmp_path):
    config = settings(tmp_path)
    a = TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    b = TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    try:
        a.acquire_process_lock()
        with pytest.raises(RuntimeError,match='Another TWAP process'):
            b.acquire_process_lock()
        a.close()
        b.acquire_process_lock()
    finally:
        b.close()


def test_lifetime_limit_and_market_uniqueness_survive_restart(tmp_path):
    config=settings(tmp_path)
    store=TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    try:
        attempt=store.reserve('market1','up',DUE,20,{},1)
        store.update(attempt,'rejected',{})
        assert store.budget_check(DUE,1)=='lifetime_submission_limit'
        with pytest.raises(Exception): store.reserve('market1','up',DUE,20,{},5)
        assert len(store.orders())==1
    finally: store.close()


def test_late_conflict_invalidates_an_already_recorded_opening(tmp_path):
    config=settings(tmp_path)
    store=TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    try:
        store.record_opening(Observation(START*1000,START*1000+800,D('100000')))
        store.record_opening(Observation(START*1000,DUE,D('100001')))
        assert store.opening(START*1000) is None
    finally: store.close()


def test_sdk_snapshot_and_provider_fallback_cannot_create_a_trade_ready_feed(tmp_path):
    config=settings(tmp_path)
    store=TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    feed=ChainlinkFeed(store,now_ms=lambda:DUE)
    stamp=lambda value:datetime.fromtimestamp(value/1000,timezone.utc)
    try:
        history=[SimpleNamespace(timestamp=stamp(DUE-i*1000),value=D('100100')) for i in range(60)]
        event=SimpleNamespace(topic='prices.crypto.twap',type='subscribe',dropped=None,
            payload=SimpleNamespace(symbol='btcusd',source='chainlink',window_seconds=60,data=history))
        feed.consume(event)
        assert feed.twap.asof(DUE) is not None and not feed.twap.valid_minute(DUE)
        fallback=SimpleNamespace(topic='prices.crypto',type='update',dropped=None,
            payload=SimpleNamespace(symbol='btcusd',source='binance',value=D('100120'),timestamp=stamp(DUE)))
        feed.consume(fallback)
        assert feed.spot.asof(DUE) is None
    finally: store.close()


def test_corrupt_legacy_state_is_not_silently_reset(tmp_path):
    config=settings(tmp_path); config.legacy_state_path.write_text('{bad')
    store=TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    try:
        with pytest.raises(RuntimeError,match='Unreadable legacy state'):
            store.import_legacy(config.legacy_state_path)
    finally: store.close()


def raw_book(clock, token='up-token'):
    return dict(asset_id=token,timestamp=str(clock[0]),min_order_size='5',
        asks=[{'price':'.95','size':'1000'}],bids=[{'price':'.94','size':'1000'}])


def test_quote_depth_and_source_timestamp_are_real_execution_constraints(tmp_path):
    config = settings(tmp_path); clock=[DUE]
    book = raw_book(clock)
    assert check_book(book,'up-token',D('.96'),D('.07'),config,DUE)['best_ask'] == D('.95')
    book['timestamp'] = str(DUE-1501)
    with pytest.raises(ValueError,match='stale'):
        check_book(book,'up-token',D('.96'),D('.07'),config,DUE)
    book = raw_book(clock); book['asks'][0]['size']='10'
    with pytest.raises(ValueError,match='depth'):
        check_book(book,'up-token',D('.96'),D('.07'),config,DUE)


@dataclass
class Signed:
    maker: str = '0x'+'1'*40
    token_id: str = 'up-token'
    side: str = 'BUY'
    order_type: str = 'FOK'
    post_only: bool = False
    maker_amount: int = 19000000
    taker_amount: int = 20000000
    builder: str = '0x'+'0'*64
    salt: int = 123


class Response:
    ok=True; status='matched'; order_id='order-1'; trade_ids=['trade-1']
    def model_dump(self,mode):
        return dict(ok=True,status=self.status,order_id=self.order_id,
                    trade_ids=self.trade_ids,making_amount='19',taking_amount='20')


async def engine_fixture(tmp_path,mode='live'):
    config = settings(tmp_path,mode=mode,dry_run=mode!='live')
    clock = [DUE+200]
    engine = TwapBot(config,now_ms=lambda:clock[0])
    await engine.api.close()
    engine.clock_ok = True
    engine.feed.twap,engine.feed.spot = buffers()
    engine.store.record_opening(Observation(START*1000,START*1000+800,D('100000')))
    record = dict(parsed=dict(slug=f'btc-updown-15m-{START}',condition_id='condition',
        tokens={'up':'up-token','down':'down-token'},raw=dict(active=True,closed=False,acceptingOrders=True)),
        event=dict(closed=False),fee=dict(status='known',rate=.07),tick=D('.001'))
    class Api:
        server_clock_offset_ms=0
        calls=0
        async def market_record(self,start): return deepcopy(record)
        async def price_history(self,*args): return [{'t':START+791,'p':.95}]
        async def raw_book(self,token):
            self.calls += 1
            return raw_book(clock,token)
        async def geoblock(self): return dict(blocked=False,country='VN',region='')
        async def close(self): pass
    class Client:
        creates=[]; posts=[]
        async def create_market_order(self,**kwargs):
            self.creates.append(kwargs); return Signed()
        async def post_order(self,signed):
            self.posts.append(signed); return Response()
        async def wait_for_order_fill_settlement(self,response,**kwargs): return ['tx']
    class Executor:
        client=Client()
        async def ensure_balance(self,*args,**kwargs): pass
        async def close(self): pass
    engine.api=Api(); engine.executor=Executor()
    return engine,clock,record


def test_end_to_end_posts_one_capped_fok_after_final_checks(tmp_path):
    async def run():
        engine,clock,_=await engine_fixture(tmp_path)
        try:
            await engine.run_once(); await engine.run_once()
            assert len(engine.executor.client.posts)==1
            assert engine.executor.client.creates[0] == dict(asset_id='up-token',side='BUY',amount='20',max_spend='19.99',max_price='0.96',order_type='FOK')
            row=engine.store.orders()[0]
            assert row['status']=='open' and row['budget']=='20'
            assert json.loads(row['payload'])['oracle']['decision_ms']==DUE
            assert engine.api.calls==2  # Preliminary book plus one AFTER SDK preparation.
        finally: await engine.close()
    asyncio.run(run())


def test_paper_reads_book_without_signing_or_posting(tmp_path):
    async def run():
        engine,_,_=await engine_fixture(tmp_path,mode='paper')
        try:
            await engine.run_once()
            assert not engine.executor.client.posts and not engine.executor.client.creates
            assert not engine.store.orders()
        finally: await engine.close()
    asyncio.run(run())


def test_future_received_spot_cannot_change_frozen_signal_but_can_block_actual_submission(tmp_path):
    async def run():
        engine,_,_=await engine_fixture(tmp_path)
        engine.feed.spot.add(Observation(DUE,DUE+100,D('100090')))
        try:
            await engine.run_once()
            frozen=engine.store.frozen(f'btc-updown-15m-{START}')
            assert frozen['reason']=='twap_spot_passed'
            assert not engine.executor.client.posts and not engine.store.orders()
        finally: await engine.close()
    asyncio.run(run())


@pytest.mark.parametrize('failure',['late_signing','stale_final_book','fee_changed','signed_cap','signed_cash','signed_wallet','geoblock'])
def test_pre_post_failure_never_submits(tmp_path,failure):
    async def run():
        engine,clock,record=await engine_fixture(tmp_path)
        original_create=engine.executor.client.create_market_order
        original_book=engine.api.raw_book
        async def create(**kwargs):
            signed=await original_create(**kwargs)
            if failure=='late_signing': clock[0]+=6000
            if failure=='signed_cap': signed.maker_amount=19900000
            if failure=='signed_cash': signed.maker_amount=20000000; signed.taker_amount=21000000
            if failure=='signed_wallet': signed.maker='0x'+'3'*40
            if failure=='fee_changed': record['fee']['rate']=.08
            return signed
        async def book(token):
            value=await original_book(token)
            if failure=='stale_final_book' and engine.api.calls==2: value['timestamp']=str(clock[0]-2000)
            return value
        async def geo(): return dict(blocked=False,country='US',region='')
        engine.executor.client.create_market_order=create
        engine.api.raw_book=book
        if failure=='geoblock': engine.api.geoblock=geo
        try:
            await engine.run_once()
            assert not engine.executor.client.posts and not engine.store.orders()
        finally: await engine.close()
    asyncio.run(run())


def test_ambiguous_post_never_creates_a_second_order(tmp_path):
    async def run():
        engine,_,_=await engine_fixture(tmp_path)
        async def uncertain(signed): raise TimeoutError('response lost')
        engine.executor.client.post_order=uncertain
        try:
            with pytest.raises(TimeoutError): await engine.run_once()
            assert engine.store.orders()[0]['status']=='ambiguous'
        finally: await engine.close()
        restarted,_,_=await engine_fixture(tmp_path)
        try:
            await restarted.run_once()
            assert not restarted.executor.client.posts
            assert restarted.store.budget_check(DUE+900000,5)=='pending_or_unresolved_position'
        finally: await restarted.close()
    asyncio.run(run())


def test_slow_journal_logging_cannot_push_a_post_beyond_entry_deadline(tmp_path):
    async def run():
        engine,clock,_=await engine_fixture(tmp_path)
        original=engine.store.log
        def slow(event,payload):
            original(event,payload)
            if event=='twap_live_intent': clock[0]+=6000
        engine.store.log=slow
        try:
            await engine.run_once()
            assert not engine.executor.client.posts
            assert engine.store.orders()[0]['status']=='aborted_before_submit'
        finally: await engine.close()
    asyncio.run(run())


def test_sdk_017_contract_supports_authenticated_feed_and_separate_sign_post():
    sdk=pytest.importorskip('polymarket')
    from polymarket.streams import CryptoPriceSpec,CryptoTwapPriceSpec
    import inspect,importlib.metadata
    assert importlib.metadata.version('polymarket-client')=='0.17.0'
    assert CryptoPriceSpec(symbols=['btcusd'],provider='chainlink').provider=='chainlink'
    assert CryptoTwapPriceSpec(symbols=['btcusd'],provider='chainlink').topic=='prices.crypto.twap'
    assert 'max_spend' in inspect.signature(sdk.AsyncSecureClient.create_market_order).parameters
    assert hasattr(sdk.AsyncSecureClient,'post_order')


def test_rejected_fok_does_not_retry_this_market(tmp_path):
    async def run():
        engine,_,_=await engine_fixture(tmp_path)
        class Rejected:
            ok=False
            def model_dump(self,mode): return dict(ok=False,code='fok_not_filled')
        async def reject(signed):
            engine.executor.client.posts.append(signed)
            return Rejected()
        engine.executor.client.post_order=reject
        try:
            await engine.run_once(); await engine.run_once()
            assert len(engine.executor.client.posts)==1
            assert engine.store.orders()[0]['status']=='rejected'
            assert engine.store.budget_check(DUE,5) is None
        finally: await engine.close()
    asyncio.run(run())


def test_confirmed_private_receipt_and_official_outcome_are_needed_for_loss_stop(tmp_path):
    async def run():
        engine,clock,_=await engine_fixture(tmp_path)
        async def pending(*args,**kwargs): raise TimeoutError('not yet confirmed')
        engine.executor.client.wait_for_order_fill_settlement=pending
        try:
            await engine.run_once()
            assert engine.store.orders()[0]['status']=='submitted'
            async def get_order(**kwargs):
                return SimpleNamespace(size_matched=D(20),associate_trades=['trade-1'],
                    status='matched',model_dump=lambda mode:dict(size_matched='20'))
            async def trades(**kwargs):
                yield SimpleNamespace(id='trade-1',status='CONFIRMED')
            engine.executor.client.get_order=get_order
            engine.executor.client.list_account_trades=trades
            await engine.reconcile()
            assert engine.store.orders()[0]['status']=='open'
            clock[0]=(START+901)*1000
            async def resolved(start): return dict(status='confirmed',winner='down'),{}
            engine.api.resolved=resolved
            await engine.reconcile()
            assert engine.store.orders()[0]['won']==0
            assert engine.store.budget_check(clock[0],5)=='daily_loss_stop_utc'
        finally: await engine.close()
    asyncio.run(run())


@pytest.mark.parametrize('failed',[False,True])
def test_redemption_is_recorded_and_not_blindly_repeated(tmp_path,failed):
    async def run():
        engine,clock,_=await engine_fixture(tmp_path)
        calls=[]
        try:
            await engine.run_once(); clock[0]=(START+901)*1000
            async def resolved(start): return dict(status='confirmed',winner='up'),{}
            async def balance(**kwargs): return SimpleNamespace(balance=20000000)
            async def redeem(**kwargs):
                calls.append(kwargs)
                async def wait():
                    if failed: raise TimeoutError('receipt not known')
                    return SimpleNamespace(transaction_hash='0xtx')
                return SimpleNamespace(wait=wait,transaction_id='redeem-1',transaction_hash=None)
            engine.api.resolved=resolved
            engine.executor.client.get_balance_allowance=balance
            engine.executor.client.redeem_positions=redeem
            await engine.reconcile(); await engine.reconcile()
            assert len(calls)==1
            assert calls[0]==dict(condition_id='condition')
            assert engine.store.orders()[0]['redeem_status']==('ambiguous_check_wallet' if failed else 'confirmed')
        finally: await engine.close()
    asyncio.run(run())


def test_real_sdk_model_prices_are_decimals_without_e18_division(tmp_path):
    pytest.importorskip('polymarket')
    from polymarket.models.price_events import CryptoTwapPriceUpdateEvent
    config=settings(tmp_path)
    store=TwapStore(config.state_path,config.decision_log_path,config.oracle_log_path)
    try:
        feed=ChainlinkFeed(store,now_ms=lambda:START*1000+800)
        stamp=datetime.fromtimestamp(START,timezone.utc)
        event=CryptoTwapPriceUpdateEvent(timestamp=stamp,payload=dict(symbol='btcusd',source='chainlink',
            timestamp=stamp,value='100000.123456789012345678',window_seconds=60))
        feed.consume(event)
        assert store.opening(START*1000).value==D('100000.123456789012345678')
    finally: store.close()
