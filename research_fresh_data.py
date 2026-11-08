"""Download public inputs and audit the FROZEN Variant B on a new calendar period.

No wallet, execution engine, secrets or order submission. All network calls are GET.
Historical prices are references, never evidence of a fill. See RESEARCH_DATA_GUIDE.md.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
from pathlib import Path
import time

import httpx
import numpy as np
import pandas as pd

from polymarket_bot.actual_research import parse_market, settlement, fee_schedule, history_asof, cash_cost
from polymarket_bot.entry_gates import PROFILE_B, evaluate
from polymarket_bot.lighter_paper_feed import BASE, aggregate_minutes
from polymarket_bot.signal_grid import features, raw_signals, select_windows

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / 'data/research_20261108'


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(value):
    x = pd.Timestamp(value)
    return x.tz_localize('UTC') if x.tzinfo is None else x.tz_convert('UTC')


def freeze(out, start, end):
    """Persist the full decision/cost protocol before downloading/scoring results."""
    protocol = dict(schema=1, start=start.isoformat(), end_exclusive=end.isoformat(),
        warmup_days=30, source='Lighter BTC/ETH 1m', policy='latest_5m',
        profile=PROFILE_B, entry_seconds=750, reference_max_age_seconds=75,
        minimum_reference=.85, padding_cents=[1, 2, 3], budget_usd=20,
        initial_cash_usd=50, redemption_delay_seconds=[0, 300, 1800],
        fixed_cost_usd_per_fill=[0, .01, .05],
        session_utc='24h', router_sma_days=25, router_depth_pct=1.5,
        bb_period=20, bb_sigma=2, auxiliary_run60_bps=60,
        baseline_profile='same DCA direction/reference universe, no B gate',
        new_period_constraint='start after 2026-09-15; no threshold selection',
        historical_execution='reference+padding; UNKNOWN fill probability',
        universe='all frozen DCA candidates; missing metadata/reference/fee/label stays counted',
        costs='fetched market fee curve; not as-of historical attestation; no assumed rebate',
        missing_features='report production fail-open helper diagnostics; strict subset blocks unavailable helpers',
        code_sha256={p: sha(ROOT/p) for p in ['polymarket_bot/signal_grid.py',
            'polymarket_bot/entry_gates.py', 'polymarket_bot/dca_gate_helpers.py',
            'polymarket_bot/actual_research.py', 'research_fresh_data.py']})
    path = out / 'protocol.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != protocol:
            raise ValueError('Protocol/code changed: use another output directory; do not overwrite a frozen run')
    else:
        dump(path, protocol)
    return protocol


class Archive:
    def __init__(self, out, offline=False, concurrency=4):
        self.out, self.offline = out, offline
        self.blocked_hosts = set()
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.sem = asyncio.Semaphore(concurrency)

    async def get(self, path, url, **params):
        path = self.out/path
        if path.exists():
            cached = json.loads(path.read_text(encoding='utf-8'))
            if self.offline or cached.get('status') in (200, 403, 405):
                return cached
        if self.offline:
            return dict(status=None, error='offline_cache_missing', url=url, params=params)
        host = httpx.URL(url).host
        if host in self.blocked_hosts:
            return dict(status=None, error='host_challenge_stop', url=url, params=params)
        result = None
        for attempt in range(4):
            async with self.sem:
                if host in self.blocked_hosts:
                    return dict(status=None, error='host_challenge_stop', url=url, params=params)
                began = time.perf_counter()
                try:
                    r = await self.client.get(url, params=params or None)
                    result = dict(url=str(r.url), status=r.status_code,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        rtt_ms=round((time.perf_counter()-began)*1000, 3),
                        body=r.json() if 'json' in r.headers.get('content-type', '') else {'text':r.text[:1000]})
                    if r.status_code in (403,405) and 'human verification' in r.text.lower():
                        self.blocked_hosts.add(host)
                except (httpx.HTTPError, ValueError) as exc:
                    result = dict(url=url, params=params, status=None,
                        fetched_at=datetime.now(timezone.utc).isoformat(), error=str(exc))
            if result['status'] is not None and result['status'] not in (429, 500, 502, 503, 504):
                break
            await asyncio.sleep(min(8, 1+2*attempt))
        dump(path, result)
        return result


def candle_rows(body, lo, hi):
    if body.get('code') != 200 or body.get('r') != '1m':
        raise ValueError('Unverified Lighter minute response')
    rows = []
    for x in body.get('c', []):
        ts = int(x['t'])
        if ts % 60000:
            raise ValueError('Off-grid minute')
        if not lo <= ts//1000 < hi:
            continue  # API count_back may include older rows.
        row = [ts//1000] + [float(x[k]) for k in ('o','h','l','c')] + [float(x.get('v', 0))]
        _, o, h, l, c, v = row
        if not np.isfinite(row).all() or min(o,h,l,c) <= 0 or v < 0 or h < max(o,l,c) or l > min(o,h,c):
            raise ValueError('Invalid OHLCV')
        rows.append(row)
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError('Duplicate minutes')
    return rows


async def download_minutes(api, start, end):
    first, stop = int((start-pd.Timedelta(days=30)).timestamp()), int(end.timestamp())
    identity = await api.get(Path('raw/lighter_markets.json'), BASE+'/orderBookDetails')
    if identity.get('status') != 200:
        raise ValueError('Lighter market discovery unavailable')
    manifest = {}
    for symbol in ('BTC','ETH'):
        matches = [m for m in identity['body'].get('order_book_details', []) if m.get('symbol') == symbol]
        if len(matches) != 1 or (symbol == 'BTC' and matches[0]['market_id'] != 1):
            raise ValueError('Lighter market identity mismatch')
        market_id = matches[0]['market_id']
        chunks = [(lo, min(lo+500*60, stop)) for lo in range(first, stop, 500*60)]
        rows, failed = [], []
        async def chunk(lo, hi):
            r = await api.get(Path(f'raw/lighter/{symbol}/{lo}.json'), BASE+'/candles',
                market_id=market_id, resolution='1m', start_timestamp=lo, end_timestamp=hi-1,
                count_back=(hi-lo)//60, set_timestamp_to_end='false')
            if r.get('status') != 200:
                return [], dict(start=lo,end=hi,error=r.get('error',str(r.get('status'))))
            return candle_rows(r['body'], lo, hi), None
        for i in range(0, len(chunks), 8):
            for values, error in await asyncio.gather(*(chunk(*c) for c in chunks[i:i+8])):
                rows.extend(values)
                if error:
                    failed.append(error)
            if i % 40 == 0:
                print(f'{symbol}: {min(i+8,len(chunks))}/{len(chunks)} pages', flush=True)
        f = pd.DataFrame(rows, columns=['timestamp','open','high','low','close','volume'])
        if f.timestamp.duplicated().any():
            raise ValueError('Duplicate downloaded minutes')
        f = f.sort_values('timestamp')
        f.timestamp = pd.to_datetime(f.timestamp, unit='s', utc=True)
        path = api.out/f'{symbol}USDT_1m.csv'
        f.to_csv(path, index=False)
        manifest[symbol] = dict(market_id=market_id, rows=len(f), expected_rows=(stop-first)//60,
            missing_minutes=(stop-first)//60-len(f), failed_pages=failed, sha256=sha(path),
            first=str(f.timestamp.min()) if len(f) else None, last=str(f.timestamp.max()) if len(f) else None)
        print(f'{symbol}: {len(f)} minutes, {manifest[symbol]["missing_minutes"]} missing', flush=True)
    dump(api.out/'minute_manifest.json', manifest)


def candidates(out, start, end):
    frames = []
    for symbol in ('BTC','ETH'):
        f = pd.read_csv(out/f'{symbol}USDT_1m.csv')
        f.timestamp = pd.to_datetime(f.timestamp, utc=True)
        frames.append(f)
    own, peer = frames
    if own.empty:
        dump(out/'candidates.json', [])
        return []
    own5, _ = aggregate_minutes(own, end)
    grid = features(own5)
    raw = select_windows(raw_signals(grid, session_start=0, session_end=0), policy='latest_5m')
    selected = raw.loc[raw.decision_at.ge(start) & raw.end_at.le(end)]
    rows = []
    for index, r in enumerate(selected.itertuples()):
        at = r.decision_at + pd.Timedelta(minutes=12)
        # Same four-day production input horizon; evaluate itself cuts at T+12.
        sliced = [f.loc[f.timestamp.ge(at-pd.Timedelta(days=4)) & f.timestamp.lt(at)] for f in frames]
        if sliced[1].empty:
            gate = dict(keep=False,reason='peer_history_missing',profile=PROFILE_B,
                memory_diagnostic='peer_history_unavailable',aux_shock_diagnostic='peer_history_unavailable')
        else:
            gate = evaluate(*sliced, start=r.decision_at, signal_at=r.signal_at,
                side=r.side, source=r.source, profile=PROFILE_B)
        unavailable = [gate[k] for k in ('memory_diagnostic','aux_shock_diagnostic')
            if gate.get(k) and any(s in gate[k] for s in ('unavailable','unaligned','invalid'))]
        rows.append(dict(start=int(r.decision_at.timestamp()), slug=f'btc-updown-15m-{int(r.decision_at.timestamp())}',
            signal_at=r.signal_at.isoformat(), side=r.side, source=r.source,
            gate=gate, strict_features_ok=not unavailable, unavailable_helpers=unavailable))
        if index % 50 == 0:
            print(f'Frozen B features: {index+1}/{len(selected)}', flush=True)
    dump(out/'candidates.json', rows)
    return rows


async def download_markets(api, rows):
    async def market(row):
        base = Path(f'raw/polymarket/{row["start"]}')
        event = await api.get(base/'event.json', 'https://gamma-api.polymarket.com/events/slug/'+row['slug'])
        result = dict(start=row['start'], event=event)
        try:
            if event['status'] != 200:
                raise ValueError('Gamma metadata unavailable')
            m = parse_market(event['body'], row['start'])
            if m['raw'].get('version', 'v1') != 'v1':
                raise ValueError('Protocol V2 asset identifiers require separate adapter')
            specs = [('clob', 'https://clob.polymarket.com/markets/'+m['condition_id'], {}),
                ('fee_info', 'https://clob.polymarket.com/clob-markets/'+m['condition_id'], {})]
            for side in ('up','down'):
                specs.append((side+'_history', 'https://clob.polymarket.com/prices-history',
                    dict(market=m['tokens'][side], startTs=row['start']-120, endTs=row['start']+900, fidelity=1)))
            values = await asyncio.gather(*(api.get(base/(name+'.json'), url, **params) for name,url,params in specs))
            result.update(dict(zip([s[0] for s in specs], values)))
            result['parsed'] = {k:v for k,v in m.items() if k != 'raw'}
            result['settlement'] = settlement(m, result['clob'].get('body', {}))
            result['fee'] = fee_schedule(m, result['fee_info'].get('body', {}))
        except (ValueError, KeyError, TypeError) as exc:
            result['parse_error'] = str(exc)
        dump(api.out/base/'combined.json', result)
        return result
    records = []
    for i in range(0,len(rows),8):
        records.extend(await asyncio.gather(*(market(r) for r in rows[i:i+8])))
        print(f'Polymarket: {min(i+8,len(rows))}/{len(rows)} candidates archived', flush=True)
    return records


def scenario(row, record, padding=.01, overhead=0.):
    """Score only known labels/fees/references. Nonfill >=1 stays in the cohort."""
    label = record.get('settlement', {})
    if label.get('status') != 'confirmed':
        return None, 'settlement_'+label.get('status','missing')
    fee = record.get('fee', {})
    if fee.get('status') != 'known':
        return None, 'fee_'+fee.get('status','missing')
    if record.get(row['side']+'_history', {}).get('status') != 200:
        return None, 'history_unavailable'
    history = record.get(row['side']+'_history', {}).get('body', {}).get('history', [])
    q = history_asof(history, row['start']+750, 75)
    if q is None:
        return None, 'reference_missing_or_stale'
    if q['price'] < .85:
        return None, 'reference_below_085'
    if Decimal(str(q['price']))+Decimal('.01') >= 1:
        return None, 'base_reference_plus_1c_not_below_one'
    won = row['side'] == label['winner']
    price = Decimal(str(q['price'])) + Decimal(str(padding))
    # Cost stress keeps the ORIGINAL +1c eligible cohort and never reselects it.
    filled = price < 1
    tick = record.get('clob', {}).get('body', {}).get('minimum_tick_size')
    tick_cap = None
    if tick and Decimal(str(tick)) > 0:
        tick_cap = float(((Decimal(str(q['price']))+Decimal('.01'))/Decimal(str(tick))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(tick)))
    shares = 20 / cash_cost(float(price), fee) if filled else 0.
    pnl = shares*won-20-overhead if filled else 0.
    return dict(slug=row['slug'], side=row['side'], start=row['start'], won=won,
        reference=q, assumed_price=float(price), live_tick_rounded_cap=tick_cap,
        assumed_fill=filled, shares=shares, cost=20. if filled else 0., overhead=overhead if filled else 0.,
        pnl=pnl, rule_type=record['parsed']['rule_type'],
        price_basis='unrounded historical reference+padding, NOT observed ask'), 'eligible'


def wallet(rows, delay=0, initial=50.):
    cash = initial
    locked = []
    peak, dd, taken, skipped = initial, 0., 0, 0
    def release(now):
        nonlocal cash, locked, peak, dd
        keep = []
        for at, payout, cost in sorted(locked):
            if at <= now:
                cash += payout
                equity = cash + sum(x[2] for x in locked if x[0] > at)
                peak = max(peak, equity)
                dd = max(dd, peak-equity)
            else:
                keep.append((at,payout,cost))
        locked = keep
    for r in sorted(rows,key=lambda x:x['start']):
        release(r['start']+750)
        if not r['assumed_fill']:
            continue
        if cash+1e-8 < r['cost']+r['overhead']:
            skipped += 1
            continue
        cash -= r['cost']+r['overhead']
        locked.append((r['start']+900+delay,r['shares']*r['won'],r['cost']))
        taken += 1
    release(float('inf'))
    return dict(final_cash=cash,pnl=cash-initial,taken=taken,skipped_for_funds=skipped,
        max_realized_drawdown=dd,redemption_delay_seconds=delay,
        limitation='Redemption timing assumed, not observed; open positions valued at cost; no intramarket drawdown')


def metrics(rows):
    if not rows:
        return dict(n=0, wins=0, win_rate=None, pnl=None, wallets={})
    filled = [r for r in rows if r['assumed_fill']]
    n, w = len(rows), sum(r['won'] for r in rows)
    z = 1.95996398454
    p = w/n
    mid = (p+z*z/(2*n))/(1+z*z/n)
    margin = z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    monthly = {}
    for r in rows:
        month = datetime.fromtimestamp(r['start'],timezone.utc).strftime('%Y-%m')
        m = monthly.setdefault(month,dict(n=0,wins=0,pnl=0.))
        m['n'] += 1; m['wins'] += r['won']; m['pnl'] += r['pnl']
    # Three-day blocks include days WITHOUT trades; diagnostic for serial dependence.
    a = min(r['start'] for r in rows)//86400
    b = max(r['start'] for r in rows)//86400
    days = np.zeros(b-a+1)
    for r in rows:
        days[r['start']//86400-a] += r['pnl']
    interval = None
    if len(days) >= 6:
        rng = np.random.default_rng(1108)
        starts = rng.integers(0,len(days),size=(3000,int(np.ceil(len(days)/3))))
        idx = ((starts[:,:,None]+np.arange(3))%len(days)).reshape(3000,-1)[:,:len(days)]
        interval = np.quantile(days[idx].sum(axis=1),[.025,.975]).tolist()
    return dict(n=n,wins=w,losses=n-w,win_rate=p,wilson95_iid_diagnostic=[mid-margin,mid+margin],
        assumed_fills=len(filled),nonfills_price_ge_one=n-len(filled),
        filled_win_rate=sum(r['won'] for r in filled)/len(filled) if filled else None,
        pnl=sum(r['pnl'] for r in rows),mean_pnl_per_candidate=sum(r['pnl'] for r in rows)/n,
        mean_winning_pnl=float(np.mean([r['pnl'] for r in filled if r['won']])) if any(r['won'] for r in filled) else None,
        pnl_block3day_bootstrap95_diagnostic=interval,monthly=monthly,
        wallets={str(d):wallet(rows,d) for d in (0,300,1800)})


def analyze(out, rows, records):
    by_start = {r['start']:r for r in records}
    results, counters = {}, {}
    trades = []
    for profile in ('baseline','variant_b','variant_b_strict'):
        kept = [r for r in rows if profile == 'baseline' or
            (r['gate']['keep'] and (profile != 'variant_b_strict' or r['strict_features_ok']))]
        status = Counter()
        for r in kept:
            _, reason = scenario(r, by_start[r['start']])
            status[reason] += 1
        counters[profile] = dict(signal_candidates=len(rows),gate_kept=len(kept),statuses=dict(status))
        results[profile] = {}
        for cents in (1,2,3):
            scored = [s for r in kept for s,reason in [scenario(r,by_start[r['start']],cents/100)] if s is not None]
            results[profile][f'plus_{cents}c'] = metrics(scored)
            if cents == 1:
                for s in scored:
                    trades.append(dict(profile=profile,**s))
        results[profile]['overhead_sensitivity_plus_1c'] = {}
        for overhead in (.01,.05):
            scored = [s for r in kept for s,reason in [scenario(r,by_start[r['start']],.01,overhead)] if s is not None]
            results[profile]['overhead_sensitivity_plus_1c'][str(overhead)] = metrics(scored)
    summary = dict(created_at=datetime.now(timezone.utc).isoformat(), protocol_sha256=sha(out/'protocol.json'),
        minute_manifest=json.loads((out/'minute_manifest.json').read_text()),
        counts=counters, helper_unavailable_candidates=sum(not r['strict_features_ok'] for r in rows),
        gate_reasons=dict(Counter(r['gate']['reason'] for r in rows)),
        confirmed_rule_types=dict(Counter(r.get('parsed',{}).get('rule_type','unknown') for r in records)),
        results=results, observed_execution_pnl=None,
        limitations=['No historical ask/depth/latency: modeled fills only; executable PnL is UNKNOWN.',
            'Metadata/fees fetched now, not an as-of fee attestation. API settlement is not onchain proof.',
            'Missing/failed inputs are counted and excluded from scoring, not silently treated as losses or fills.',
            'Baseline and B compared on their own eligible sets; selection after price filter can change composition.',
            'Bootstrap/Wilson are diagnostics, not guarantees; no threshold optimization on this run.',
            'Historical unrounded padding preserves old research economics; current tick-rounded live cap is also exported.',
            'Unlimited-funding aggregate differs from continuous $50 wallet; redemption delays assumed.',
            'This is a repeat-entry research replay. Deployed canary permits ONE persistent submit, not all historical trades.'])
    dump(out/'summary.json', summary)
    dump(out/'trades.json', trades)
    pd.json_normalize(trades).to_csv(out/'trades.csv', index=False)
    files = [p for p in out.rglob('*') if p.is_file() and p.name not in ('file_manifest.json',)]
    dump(out/'file_manifest.json', {str(p.relative_to(out)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in files})
    print(json.dumps(dict(counts=counters,results={k:v['plus_1c'] for k,v in results.items()}),indent=2),flush=True)
    return summary


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2026-10-01')
    p.add_argument('--end', default='2026-11-08', help='Exclusive UTC endpoint')
    p.add_argument('--output-dir', type=Path, default=DEFAULT_OUT)
    p.add_argument('--offline', action='store_true')
    p.add_argument('--download-only', action='store_true')
    args = p.parse_args()
    start,end = stamp(args.start),stamp(args.end)
    if start <= stamp('2026-09-15') or end <= start or end > pd.Timestamp.now(tz='UTC').floor('min'):
        raise ValueError('Use a completed new calendar range after 2026-09-15')
    out = args.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
    freeze(out,start,end)
    api = Archive(out,args.offline)
    try:
        await download_minutes(api,start,end)
        if args.download_only:
            return
        rows = candidates(out,start,end)
        records = await download_markets(api,rows)
        analyze(out,rows,records)
    finally:
        await api.client.aclose()


if __name__ == '__main__':
    asyncio.run(main())
