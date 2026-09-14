"""Bounded public-only oracle/edge/order-flow recorder. No real order endpoints."""
import argparse
import asyncio
from collections import deque
from contextlib import suppress
import json
import math
import os
from pathlib import Path
import time

import websockets

from collect_poly_paper import Ledger, freeze_signals, snapshot_books
from research_polymarket_actual import PublicArchive
from polymarket_bot.actual_research import parse_market, settlement, buy_depth
from polymarket_bot.advanced_research import (SCHEMA, OracleBuffer, MakerProbe, TOPICS,
    book_features, fit_calibration, empirical_probability, edge_fill)

DELAYS = [630, 690, 750, 810, 840, 870]


class CaptureLedger(Ledger):
    """Batch high-rate public stream events; flush at least every second."""
    def __init__(self, path):
        super().__init__(path)
        self.last_flush = time.monotonic()

    def event(self, kind, slug, payload):
        self.db.execute('INSERT INTO events(received_ms,kind,slug,payload) VALUES(?,?,?,?)',
                        (self.ms(), kind, slug, json.dumps(payload, default=str)))
        if time.monotonic()-self.last_flush >= 1:
            self.db.commit(); self.last_flush = time.monotonic()


async def heartbeat(ws, seconds):
    while True:
        await ws.send('PING')
        await asyncio.sleep(seconds)


async def oracle_stream(ledger, buffer):
    frame = {'action': 'subscribe', 'subscriptions': [
        {'topic': t, 'type': '*' if t == 'crypto_prices_chainlink' else 'update',
         'filters': '{"symbol":"btc/usd"}'} for t in TOPICS]}
    while True:
        try:
            async with websockets.connect('wss://ws-live-data.polymarket.com', ping_interval=None,
                                           open_timeout=10, close_timeout=2) as ws:
                await ws.send(json.dumps(frame))
                ledger.event('advanced_oracle_connected', None, frame)
                beat = asyncio.create_task(heartbeat(ws, 5))
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), 15)
                        if raw in ('PONG', 'PING'):
                            continue
                        try:
                            event = json.loads(raw)
                        except (ValueError, TypeError):
                            # Blank/ack frames are not a connection failure.
                            if str(raw).strip():
                                ledger.event('advanced_oracle_non_json', None, {'text': str(raw)[:160]})
                            continue
                        if not isinstance(event, dict):
                            continue
                        accepted = buffer.add(event, ledger.ms())
                        ledger.event('advanced_oracle_raw', None, {'accepted': accepted, 'event': event})
                finally:
                    beat.cancel()
                    with suppress(asyncio.CancelledError):
                        await beat
        except (OSError, ValueError, KeyError, TypeError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
            buffer.points.clear()  # reconnect needs a new warmup; no silent gap bridging
            ledger.event('advanced_oracle_gap', None, {'error': str(exc)})
            await asyncio.sleep(3)


async def market_stream(ledger, market, flow, probes):
    slug = market['slug']
    try:
        async with websockets.connect('wss://ws-subscriptions-clob.polymarket.com/ws/market',
                                       ping_interval=None, open_timeout=10, close_timeout=2) as ws:
            await ws.send(json.dumps({'assets_ids': list(market['tokens'].values()), 'type': 'market'}))
            ledger.event('advanced_market_connected', slug, {'tokens': market['tokens']})
            beat = asyncio.create_task(heartbeat(ws, 10))
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), 20)
                    if raw in ('PONG', 'PING'):
                        continue
                    try:
                        data = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    for event in data if isinstance(data, list) else [data]:
                        if not isinstance(event, dict) or event.get('market') != market['condition_id']:
                            continue
                        now = ledger.ms()
                        ledger.event('advanced_market_raw', slug, event)
                        if event.get('event_type') == 'last_trade_price':
                            if int(event['timestamp']) <= now and str(event.get('asset_id')) in market['tokens'].values():
                                flow.append((now, event))
                            for probe in list(probes.values()):
                                probe.trade(event, now)
            finally:
                beat.cancel()
                with suppress(asyncio.CancelledError):
                    await beat
    finally:
        for probe in probes.values():
            probe.invalid = True
        ledger.event('advanced_market_gap', slug, {'maker_probes_invalidated': True})


def flow_features(flow, token, now_ms):
    trades = []; seen = set()
    for received, e in flow:
        if str(e.get('asset_id')) != token or not now_ms-30000 <= int(e['timestamp']) <= received <= now_ms:
            continue
        key = (e.get('transaction_hash'), e['timestamp'], e.get('size'), e.get('price'), e.get('side'))
        if key not in seen:
            trades.append(e); seen.add(key)
    buys = sum(float(e['size']) for e in trades if e.get('side') == 'BUY')
    sells = sum(float(e['size']) for e in trades if e.get('side') == 'SELL')
    return {'reported_buy_shares_30s': buys, 'reported_sell_shares_30s': sells,
            'reported_trade_imbalance_30s': (buys-sells)/(buys+sells) if buys+sells else None,
            'trade_count_30s': len(trades), 'scope': 'reported public trade side; not independent order-flow proof'}


async def resolve_observed(api, ledger):
    rows = ledger.db.execute('''SELECT DISTINCT o.slug FROM advanced_observations o
        LEFT JOIN advanced_labels l ON o.slug=l.slug WHERE l.slug IS NULL''').fetchall()
    probes = ledger.db.execute("SELECT DISTINCT slug FROM events WHERE kind='maker_probe_intent' AND slug IS NOT NULL").fetchall()
    labeled = {r[0] for r in ledger.db.execute('SELECT slug FROM advanced_labels')}
    due = sorted({s for (s,) in rows+probes if s not in labeled and int(s.rsplit('-', 1)[1])+900 < ledger.now()})[:10]
    for slug in due:
        event = await api.get(f'https://gamma-api.polymarket.com/events/slug/{slug}')
        try:
            market = parse_market(event['body'], int(slug.rsplit('-', 1)[1]))
            response = await api.get(f"https://clob.polymarket.com/markets/{market['condition_id']}")
            label = settlement(market, response.get('body', {}))
            ledger.event('advanced_settlement_check', slug, {'label': label, 'event': event, 'clob': response})
            if label.get('status') == 'confirmed':
                ledger.db.execute('INSERT OR IGNORE INTO advanced_labels VALUES(?,?,?)',
                                   (slug, ledger.ms(), json.dumps(label)))
                ledger.db.commit(); ledger.resolve(slug, label)
        except (ValueError, KeyError, TypeError) as exc:
            ledger.event('advanced_settlement_error', slug, {'error': str(exc)})


async def sync_clock(api, ledger):
    offsets = []
    for _ in range(3):
        a = time.time(); response = await api.get('https://clob.polymarket.com/time'); b = time.time()
        if response.get('status') != 200 or not isinstance(response.get('body'), (int, float)) or b-a > 3:
            raise ValueError('Unverified server time')
        offsets.append(response['body']-(a+b)/2)
    if max(offsets)-min(offsets) > 2 or abs(sorted(offsets)[1]) > 300:
        raise ValueError('Unstable server clock')
    ledger.clock_offset = sorted(offsets)[1]
    ledger.event('advanced_clock', None, {'offsets': offsets, 'scope': 'process only',
                 'book_future_tolerance_ms': 1000, 'reason': 'CLOB integer-second clock precision; oracle features still as-of'})


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-seconds', type=int, default=120)
    parser.add_argument('--budget-usd', type=float, default=10., help='All-in cash-equivalent budget per independent shadow scenario, max $30')
    parser.add_argument('--output-dir', type=Path, default=Path('advanced_paper_capture'))
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--verified-reference-file', type=Path,
                        help='Optional operator-verified {slug,price_to_beat,observed_ms,source_url}; no guessed defaults')
    parser.add_argument('--settle-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 86400:
        raise ValueError('Choose a bounded duration of 1..86400 seconds')
    if not math.isfinite(args.budget_usd) or not 0 < args.budget_usd <= 30:
        raise ValueError('Paper trial budget must be finite and in (0,30] USD')
    allowed_root = Path(os.getenv('POLYBOT_ALLOWED_DATA_ROOT', str(Path.cwd()))).resolve()
    if not args.output_dir.resolve().is_relative_to(allowed_root):
        raise ValueError(f'Output must stay inside {allowed_root}')
    args.output_dir.mkdir(exist_ok=True, parents=True)
    ledger = CaptureLedger(args.output_dir/'capture.sqlite3'); api = PublicArchive(args.output_dir)
    ledger.db.execute('CREATE TABLE IF NOT EXISTS advanced_observations(slug TEXT, delay INTEGER, side TEXT, payload TEXT, PRIMARY KEY(slug,delay,side))')
    ledger.db.execute('CREATE TABLE IF NOT EXISTS advanced_labels(slug TEXT PRIMARY KEY, received_ms INTEGER, payload TEXT)')
    ledger.db.commit()
    oracle = OracleBuffer(); streams = []; ws_market = None
    probes = {}; flow = deque(maxlen=50000); current = None; signals = None; last_settle = 0
    try:
        ledger.event('advanced_plan', None, {'schema': SCHEMA, 'delays': DELAYS, 'budget': args.budget_usd,
                     'mode': 'public-only paper, maker probes are not strategy entries', 'duration': args.duration_seconds})
        geo = await api.get('https://polymarket.com/api/geoblock')
        ledger.event('geoblock', None, geo)  # No bypass; public observation is not trading eligibility.
        await sync_clock(api, ledger)
        model = json.loads(args.calibration.read_text(encoding='utf-8')) if args.calibration else fit_calibration([], ledger.ms()-1)
        await resolve_observed(api, ledger)
        if args.settle_only:
            return
        streams.append(asyncio.create_task(oracle_stream(ledger, oracle)))
        deadline = time.monotonic()+args.duration_seconds
        while time.monotonic() < deadline:
            tick = time.monotonic(); start = int(ledger.now())//900*900; slug = f'btc-updown-15m-{start}'
            try:
                if current != start:
                    if ws_market:
                        ws_market.cancel()
                        with suppress(asyncio.CancelledError, Exception):
                            await ws_market
                    for probe in probes.values():
                        ledger.event('maker_probe_result', None, probe.summary())
                    probes.clear(); flow.clear(); current = start; signals = None; ws_market = None
                if signals is None and 20 <= ledger.now()-start <= 45:
                    signals = await freeze_signals(api, ledger, start)
                market, fee, books = await snapshot_books(api, ledger, start, budget=args.budget_usd)
                if ws_market is None or ws_market.done():
                    if ws_market is not None:
                        with suppress(asyncio.CancelledError, Exception):
                            ws_market.result()
                        for p in probes.values():
                            ledger.event('maker_probe_result', slug, p.summary())
                        probes.clear(); flow.clear()
                    ws_market = asyncio.create_task(market_stream(ledger, market, flow, probes))
                meta_ms, meta_json = ledger.db.execute("SELECT received_ms,payload FROM events WHERE kind='market_metadata' AND slug=? ORDER BY id DESC LIMIT 1", (slug,)).fetchone()
                meta = json.loads(meta_json)['body'].get('eventMetadata') or {}
                price_to_beat = meta.get('priceToBeat')  # never read finalPrice
                if price_to_beat is None and args.verified_reference_file:
                    ref = json.loads(args.verified_reference_file.read_text(encoding='utf-8'))
                    if (ref.get('slug') == slug and ref.get('source_url')
                            and start*1000 <= int(ref['observed_ms']) <= ledger.ms()):
                        price_to_beat = ref['price_to_beat']; meta_ms = int(ref['observed_ms'])
                        ledger.event('operator_verified_reference', slug, ref)
                for side, book in books.items():
                    now = ledger.ms()
                    try:
                        micro = book_features(book, now)
                        micro.update(flow_features(flow, market['tokens'][side], now))
                        ledger.event('advanced_microstructure', slug, {'side': side, **micro})
                        old = probes.get(side)
                        if old and now >= old.expires_ms:
                            ledger.event('maker_probe_result', slug, old.summary()); del probes[side]
                        if side not in probes:
                            probes[side] = MakerProbe(book, now, market['end']*1000, budget=args.budget_usd)
                            ledger.event('maker_probe_intent', slug, {'side': side, **probes[side].summary()})
                    except (ValueError, KeyError, TypeError) as exc:
                        ledger.event('advanced_book_skip', slug, {'side': side, 'reason': str(exc)})
                        continue
                    try:
                        if price_to_beat is None:
                            raise ValueError('Verified priceToBeat unavailable on live Gamma; no retrospective or guessed substitute')
                        of = oracle.describe(market, price_to_beat, meta_ms, now, side)
                        ledger.event('advanced_oracle_features', slug, {'side': side, **of})
                    except (ValueError, KeyError, TypeError) as exc:
                        ledger.event('advanced_oracle_skip', slug, {'side': side, 'reason': str(exc)})
                        continue
                    for delay in DELAYS:
                        if not delay*1000 <= now-start*1000 < delay*1000+10000:
                            continue
                        dca_active = bool(signals and signals.get('dca') == side)
                        obs = {'schema': SCHEMA, 'slug': slug, 'side': side, 'delay': delay,
                               'decision_ms': now, 'end_ms': market['end']*1000, 'dca_active': dca_active,
                               'oracle': of, 'midpoint': micro['midpoint'], 'microstructure': micro}
                        ledger.db.execute('INSERT OR IGNORE INTO advanced_observations VALUES(?,?,?,?)',
                                          (slug, delay, side, json.dumps(obs)))
                        ledger.db.commit()
                        policy = f'oracle_edge_d{delay}'
                        if not dca_active or ledger.seen(slug, policy):
                            continue
                        try:
                            probability = empirical_probability(model, of, micro['midpoint'], delay, now, slug)
                            fill = edge_fill(book, fee, probability, now, budget=args.budget_usd)
                            ledger.attempt(slug, policy, side, fill=fill)
                        except (ValueError, KeyError, TypeError) as exc:
                            ledger.attempt(slug, policy, side, reason=str(exc))
                if tick-last_settle > 60:
                    await resolve_observed(api, ledger); last_settle = tick
            except Exception as exc:
                ledger.event('advanced_tick_error', slug, {'error': str(exc)})
            await asyncio.sleep(min(max(0, 5-(time.monotonic()-tick)), max(0, deadline-time.monotonic())))
    finally:
        # Persist probes before cancellation invalidates active stream state.
        for probe in probes.values():
            if ledger.ms() < probe.expires_ms:
                probe.invalid = True
            ledger.event('maker_probe_result', None, probe.summary())
        if ws_market:
            streams.append(ws_market)
        for task in streams:
            task.cancel()
        for task in streams:
            with suppress(asyncio.CancelledError, Exception):
                await task
        await api.client.aclose()
        ledger.db.commit()
        result = ledger.summary()
        result['advanced_observations'] = ledger.db.execute('SELECT count(*) FROM advanced_observations').fetchone()[0]
        result['confirmed_labels'] = ledger.db.execute('SELECT count(*) FROM advanced_labels').fetchone()[0]
        (args.output_dir/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        ledger.db.close(); print(json.dumps(result, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
