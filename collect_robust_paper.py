"""Fixed forward experiment; public GET/WSS only, no wallet or live executor."""
import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import time

import websockets

from collect_poly_paper import Ledger, record_chainlink
from research_polymarket_actual import PublicArchive
from polymarket_bot.actual_research import parse_market, fee_schedule, settlement
from polymarket_bot.market_data import BinanceFeed
from polymarket_bot.signal import snapshot
from polymarket_bot.robustness import select_intent, favourite, replay_fill


def encode(value):
    return json.dumps(value, sort_keys=True, default=str, separators=(',', ':'))


class Experiment:
    def __init__(self, output, protocol):
        output.mkdir(parents=True, exist_ok=True)
        self.output, self.protocol = output, protocol
        self.ledger = Ledger(output/'capture.sqlite3')
        root=Path(__file__).resolve().parent
        files=['collect_robust_paper.py','collect_poly_paper.py','research_polymarket_actual.py',
               'polymarket_bot/robustness.py','polymarket_bot/actual_research.py',
               'polymarket_bot/signal.py','polymarket_bot/signal_grid.py','polymarket_bot/market_data.py']
        self.manifest={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
        self.dependencies={name:importlib.metadata.version(name) for name in ('httpx','pandas','numpy','websockets')}
        self.digest = hashlib.sha256(encode({'protocol':protocol,'code':self.manifest,'dependencies':self.dependencies}).encode()).hexdigest()
        db = self.ledger.db
        db.execute('CREATE TABLE IF NOT EXISTS experiment (hash TEXT PRIMARY KEY, protocol TEXT, started_ms INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS labels (slug TEXT PRIMARY KEY, received_ms INTEGER, winner TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS windows (slug TEXT PRIMARY KEY, start_ms INTEGER, signal TEXT, reason TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS measurements (slug TEXT, policy TEXT, payload TEXT, PRIMARY KEY(slug,policy))')
        existing = db.execute('SELECT hash FROM experiment').fetchone()
        if existing and existing[0] != self.digest:
            db.close()
            raise ValueError('Protocol changed: use a separate output directory')
        db.commit()
        self.api = PublicArchive(output)
        self.feed = BinanceFeed()

    async def sync_clock(self):
        offsets = []
        for _ in range(3):
            before = time.time()
            response = await self.api.get('https://clob.polymarket.com/time')
            after = time.time()
            value = response.get('body')
            if response['status'] != 200 or type(value) not in (int, float) or after-before > 3:
                raise ValueError('Unverified server clock')
            offsets.append(value-(before+after)/2)
        if max(offsets)-min(offsets)>2 or abs(sorted(offsets)[1])>30:
            raise ValueError('Unstable server clock')
        self.ledger.clock_offset = sorted(offsets)[1]
        self.ledger.event('clock_verified', None, {'offsets_seconds': offsets})

    async def frozen_signal(self, start):
        at = datetime.fromtimestamp(start, tz=timezone.utc)
        frame, daily = await asyncio.gather(self.feed.history_5m('BTCUSDT', 240, now=at),
                                          self.feed.history_1d('BTCUSDT', 28, now=at))
        p = self.protocol
        signal = snapshot(frame, decision_at=at, daily_frame=daily, policy=p['signal_policy'],
                          session_start_utc=p['session_start_utc'], session_end_utc=p['session_end_utc'],
                          router_enabled=True, aux_enabled=True)
        if self.ledger.now() > start+45:
            raise ValueError('Signal missed opening deadline')
        self.ledger.event('signals_frozen', f'btc-updown-15m-{start}', {
            'signals': {'dca': signal.direction}, 'baseline': asdict(signal),
            'candles_5m': frame.to_dict('records'), 'daily': daily.to_dict('records')})
        return signal

    async def market(self, start):
        slug = f'btc-updown-15m-{start}'
        response = await self.api.get(f'https://gamma-api.polymarket.com/events/slug/{slug}')
        self.ledger.event('market_metadata', slug, response)
        if response.get('status') != 200:
            raise ValueError('Gamma unavailable')
        m = parse_market(response['body'], start)
        if m['raw'].get('closed') or m['raw'].get('acceptingOrders') is not True:
            raise ValueError('Market closed or not accepting')
        info = await self.api.get(f"https://clob.polymarket.com/clob-markets/{m['condition_id']}")
        self.ledger.event('fee_info', slug, info)
        fee = fee_schedule(m, info.get('body', {}))
        if info.get('status') != 200 or fee.get('status') != 'known':
            raise ValueError('Unverified market fees')
        return m, fee

    async def books(self, market):
        async def one(side):
            before = self.ledger.ms()
            response = await self.api.get('https://clob.polymarket.com/book', token_id=market['tokens'][side])
            after = self.ledger.ms()
            book = response.get('body')
            if (response.get('status') != 200 or not isinstance(book, dict)
                or str(book.get('asset_id')) != market['tokens'][side]
                or book.get('market') != market['condition_id']):
                raise ValueError('Book identity or network error')
            return side, book, {'requested_ms': before, 'received_ms': after, 'rtt_ms': after-before}
        rows = await asyncio.gather(one('up'), one('down'))
        return {s:b for s,b,_ in rows}, {s:t for s,_,t in rows}

    async def raw_stream(self, market, until):
        """Compressed, receipt-timestamped events around decision; gaps are explicit."""
        directory = self.output/'streams'
        directory.mkdir(exist_ok=True)
        with gzip.open(directory/(market['slug']+'.jsonl.gz'), 'at', encoding='utf-8') as out:
            while self.ledger.now() < until:
                try:
                    async with websockets.connect('wss://ws-subscriptions-clob.polymarket.com/ws/market',
                            ping_interval=None, open_timeout=5, close_timeout=2) as ws:
                        await ws.send(encode({'type':'market', 'assets_ids':list(market['tokens'].values())}))
                        self.ledger.event('robust_stream_connected', market['slug'], {})
                        last_ping = 0.
                        while self.ledger.now() < until:
                            if time.monotonic()-last_ping > 8:
                                await ws.send('PING'); last_ping=time.monotonic()
                            try:
                                message = await asyncio.wait_for(ws.recv(), min(2, max(.05, until-self.ledger.now())))
                            except asyncio.TimeoutError:
                                continue
                            record = {'received_ms': self.ledger.ms(), 'monotonic_ns': time.monotonic_ns(), 'raw': message}
                            out.write(encode(record)+'\n')
                except Exception as exc:
                    out.write(encode({'received_ms':self.ledger.ms(),'gap':str(exc)})+'\n')
                    self.ledger.event('robust_stream_gap', market['slug'], {'error':str(exc)})
                    await asyncio.sleep(1)

    async def evaluate(self, market, fee, signal, start):
        p, ledger = self.protocol, self.ledger
        due = start*1000+p['entry_seconds']*1000
        books, timings = await self.books(market)
        decision_ms, decision_mono = ledger.ms(), time.monotonic()
        ledger.event('robust_decision_books', market['slug'], {'books':books,'timings':timings,'decision_ms':decision_ms})
        if not 0 <= decision_ms-due <= p['entry_tolerance_ms']:
            raise ValueError('Missed fixed entry timestamp tolerance')
        choices = {'dca': signal.direction}
        try:
            choices['favourite'] = favourite(books, decision_ms, p)
        except ValueError:
            choices['favourite'] = None
        intents = {}
        for name, side in choices.items():
            try:
                intents[name] = select_intent(side, books, decision_ms, p)
            except (ValueError, KeyError) as exc:
                for delay in p['latency_ms']:
                    for depth in p['depth_fractions']:
                        ledger.attempt(market['slug'], f'{name}_{delay}ms_depth{int(depth*100)}', side, reason=str(exc))
        async def arrival(delay):
            await asyncio.sleep(max(0, decision_mono+delay/1000-time.monotonic()))
            try:
                observed, times = await self.books(market)
                now_ms = ledger.ms()
                for name, intent in intents.items():
                    for depth in p['depth_fractions']:
                        policy = f'{name}_{delay}ms_depth{int(depth*100)}'
                        measurement = {'protocol_hash':self.digest,'intent':intent,
                            'book':observed[intent['side']], 'fee':fee, 'observed_ms':now_ms,
                            'target_delay_ms':delay,'elapsed_ms':round((time.monotonic()-decision_mono)*1000,3),
                            'timings':times, 'depth_fraction':depth, 'dca_signal':signal.direction,
                            'source':signal.source}
                        ledger.db.execute('INSERT OR IGNORE INTO measurements VALUES(?,?,?)',
                                          (market['slug'],policy,encode(measurement)))
                        ledger.db.commit()
                        try:
                            fill = replay_fill(intent, observed[intent['side']], fee, now_ms, p, depth)
                            ledger.attempt(market['slug'],policy,intent['side'],fill=fill)
                        except (ValueError, KeyError) as exc:
                            ledger.attempt(market['slug'],policy,intent['side'],reason=str(exc))
            except Exception as exc:
                ledger.event('tick_error',market['slug'],{'phase':'arrival','delay':delay,'error':str(exc)})
                for name,intent in intents.items():
                    for depth in p['depth_fractions']:
                        ledger.attempt(market['slug'],f'{name}_{delay}ms_depth{int(depth*100)}',intent['side'],reason='arrival_data_unavailable')
        await asyncio.gather(*(arrival(delay) for delay in p['latency_ms']))

    async def window(self, start, overall_deadline):
        slug, ledger = f'btc-updown-15m-{start}', self.ledger
        if ledger.db.execute('SELECT 1 FROM windows WHERE slug=?',(slug,)).fetchone():
            return
        # Persist before fetching: restart never reconstructs an earlier decision.
        ledger.db.execute('INSERT INTO windows VALUES(?,?,?,?)',(slug,start*1000,None,'started'))
        ledger.db.commit()
        if ledger.now() > start+30:
            ledger.db.execute('UPDATE windows SET reason=? WHERE slug=?',('started_mid_window',slug)); ledger.db.commit()
            return
        await asyncio.sleep(max(0,start+5-ledger.now()))
        signal = await self.frozen_signal(start)
        ledger.db.execute('UPDATE windows SET signal=?,reason=? WHERE slug=?',(encode(asdict(signal)),signal.reason,slug)); ledger.db.commit()
        if signal.reason == 'outside_session':
            return
        due = start+self.protocol['entry_seconds']
        if overall_deadline < due+10:
            return
        await asyncio.sleep(max(0,due-25-ledger.now()))
        market, fee = await self.market(start)
        stream = asyncio.create_task(self.raw_stream(market,due+10))
        try:
            await asyncio.sleep(max(0,due-ledger.now()))
            await self.evaluate(market,fee,signal,start)
            await stream
        finally:
            stream.cancel()
            with suppress(asyncio.CancelledError):
                await stream

    async def settle(self):
        # Recover a crash between label persistence and updating paper rows.
        for slug,winner in self.ledger.db.execute("SELECT l.slug,l.winner FROM labels l WHERE EXISTS (SELECT 1 FROM paper p WHERE p.slug=l.slug AND p.status='pending')").fetchall():
            self.ledger.resolve(slug,{'status':'confirmed','winner':winner})
        # Also label unfilled/skipped windows for matched baseline comparisons.
        rows = self.ledger.db.execute('SELECT slug,start_ms FROM windows WHERE signal IS NOT NULL AND slug NOT IN (SELECT slug FROM labels)').fetchall()
        for slug,start_ms in rows:
            if self.ledger.ms() < start_ms+900_000:
                continue
            try:
                event = await self.api.get(f'https://gamma-api.polymarket.com/events/slug/{slug}')
                m = parse_market(event['body'], start_ms//1000)
                clob = await self.api.get(f"https://clob.polymarket.com/markets/{m['condition_id']}")
                label = settlement(m,clob.get('body',{}))
                self.ledger.event('settlement_check',slug,{'event':event,'clob':clob,'label':label})
                if label.get('status') == 'confirmed':
                    self.ledger.db.execute('INSERT OR IGNORE INTO labels VALUES(?,?,?)',(slug,self.ledger.ms(),label['winner']))
                    self.ledger.db.commit()
                    self.ledger.resolve(slug,label)
            except Exception as exc:
                self.ledger.event('settlement_error',slug,{'error':str(exc)})

    async def housekeeping(self, deadline):
        last_settle = 0
        last_report = 0
        last_clock = time.monotonic()
        while self.ledger.now() < deadline:
            if shutil.disk_usage(self.output).free < 2*1024**3:
                raise RuntimeError('Disk reserve reached: stop capture and retain existing data')
            self.ledger.event('collector_heartbeat',None,{'protocol_hash':self.digest})
            if time.monotonic()-last_settle > 60:
                await self.settle()
                last_settle = time.monotonic()
            if time.monotonic()-last_clock > 3600 and int(self.ledger.now())%900 < 600:
                await self.sync_clock()
                last_clock = time.monotonic()
            if time.monotonic()-last_report > 300:
                from report_robust_paper import report
                result = await asyncio.to_thread(report,self.output/'capture.sqlite3')
                temporary=self.output/'robustness_report.tmp'
                temporary.write_text(encode(result),encoding='utf-8')
                temporary.replace(self.output/'robustness_report.json')
                last_report=time.monotonic()
            await asyncio.sleep(5)

    async def run(self, duration):
        await self.sync_clock()
        ledger = self.ledger
        ledger.db.execute('INSERT OR IGNORE INTO experiment VALUES(?,?,?)',(self.digest,encode(self.protocol),ledger.ms()))
        ledger.db.commit()
        started=ledger.db.execute('SELECT started_ms FROM experiment').fetchone()[0]
        # Restart must never move the prespecified final review date forward.
        deadline = min(ledger.now()+duration,started/1000+self.protocol['validation_days']*86400)
        ledger.event('run_plan',None,{'protocol':self.protocol,'duration_seconds':max(0,deadline-ledger.now()),'budget_each':30,
            'protocol_hash':self.digest,'code_hashes':self.manifest,'dependencies':self.dependencies})
        chainlink = asyncio.create_task(record_chainlink(ledger,duration))
        housekeeping = asyncio.create_task(self.housekeeping(deadline))
        async def windows():
            while ledger.now()<deadline:
                start = int(ledger.now())//900*900
                try:
                    await self.window(start,deadline)
                except Exception as exc:
                    ledger.event('tick_error',f'btc-updown-15m-{start}',{'error':str(exc)})
                    ledger.db.execute('UPDATE windows SET reason=? WHERE slug=?',
                                      ('capture_error: '+str(exc),f'btc-updown-15m-{start}'))
                    ledger.db.commit()
                await asyncio.sleep(min(max(.1,start+900-ledger.now()),max(.1,deadline-ledger.now())))
        runner = asyncio.create_task(windows())
        try:
            done, _ = await asyncio.wait([runner,housekeeping],return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            await self.settle()
        finally:
            for task in (chainlink,housekeeping,runner):
                task.cancel()
            await asyncio.gather(chainlink,housekeeping,runner,return_exceptions=True)
            ledger.event('run_finished',None,ledger.summary())
            await self.api.client.aclose()
            ledger.db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('/app/robust_forward'))
    parser.add_argument('--duration-seconds',type=int,default=28*86400)
    parser.add_argument('--protocol',type=Path,default=Path(__file__).with_name('robustness_protocol.json'))
    args=parser.parse_args()
    if not 0 < args.duration_seconds <= 28*86400:
        raise ValueError('Duration must be positive and no more than 28 days')
    protocol=json.loads(args.protocol.read_text())
    if protocol['mode']!='research_paper_only' or protocol['budget_usd']>30:
        raise ValueError('Public paper only, maximum $30 simulated budget')
    asyncio.run(Experiment(args.output_dir,protocol).run(args.duration_seconds))


if __name__=='__main__':
    main()
