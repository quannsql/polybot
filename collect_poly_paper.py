"""Bounded, public-data-only Bot2 recorder and experimental shadow ledger.

No settings/env loading, private keys, authenticated clients or order endpoints.
Default stops after 120 seconds. Re-running safely resumes unresolved shadow rows.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

import pandas as pd
import websockets

from polymarket_bot.actual_research import parse_market, settlement, fee_schedule, buy_depth, dec
from polymarket_bot.market_data import BinanceFeed
from polymarket_bot.signal import snapshot
from polymarket_bot.signal_grid import features
from research_polymarket_actual import PublicArchive


POLICIES=[
    {'id':'dca_open','source':'dca','delay':30,'minimum_mid':0.,'cap':.58},
    {'id':'bb15_open','source':'bb15','delay':30,'minimum_mid':0.,'cap':.58},
    {'id':'dca_late5_mid75','source':'dca','delay':330,'minimum_mid':.75,'cap':.99,'max_above_mid':.01},
    {'id':'dca_late10_mid85','source':'dca','delay':630,'minimum_mid':.85,'cap':.99,'max_above_mid':.01},
    {'id':'dca_late1130_mid85','source':'dca','delay':690,'minimum_mid':.85,'cap':.99,'max_above_mid':.01},
    {'id':'dca_late10_mid75','source':'dca','delay':630,'minimum_mid':.75,'cap':.99,'max_above_mid':.01},
    {'id':'dca_late10_mid65','source':'dca','delay':630,'minimum_mid':.65,'cap':.99,'max_above_mid':.01},
]


class Ledger:
    def __init__(self,path):
        self.clock_offset=0.
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, received_ms INTEGER, kind TEXT, slug TEXT, payload TEXT)')
        self.db.execute('''CREATE TABLE IF NOT EXISTS paper (
            slug TEXT, policy TEXT, side TEXT, opened_ms INTEGER, shares REAL,
            cost REAL, status TEXT, winner TEXT, pnl REAL, payload TEXT,
            PRIMARY KEY(slug,policy))''')
        self.db.commit()
    def now(self):
        return time.time()+self.clock_offset
    def ms(self):
        return int(self.now()*1000)
    def event(self,kind,slug,payload):
        self.db.execute('INSERT INTO events(received_ms,kind,slug,payload) VALUES(?,?,?,?)',
                        (self.ms(),kind,slug,json.dumps(payload,default=str)))
        self.db.commit()
    def seen(self,slug,policy):
        return self.db.execute('SELECT 1 FROM paper WHERE slug=? AND policy=?',(slug,policy)).fetchone() is not None
    def attempt(self,slug,policy,side,fill=None,reason=None):
        self.db.execute('INSERT OR IGNORE INTO paper VALUES(?,?,?,?,?,?,?,?,?,?)',
            (slug,policy,side,self.ms(),fill['shares'] if fill else 0,
             fill['total_cost'] if fill else 0,'pending' if fill else 'skipped',None,None,
             json.dumps({'fill':fill,'reason':reason},default=str)))
        self.db.commit()
    def pending(self):
        return [r[0] for r in self.db.execute("SELECT DISTINCT slug FROM paper WHERE status='pending'")]
    def resolve(self,slug,label):
        if label.get('status')!='confirmed':
            return 0
        winner=label['winner']
        if winner not in {'up','down'}:
            raise ValueError('Invalid final binary winner')
        rows=self.db.execute("SELECT policy,side,shares,cost FROM paper WHERE slug=? AND status='pending'",(slug,)).fetchall()
        for policy,side,shares,cost in rows:
            self.db.execute("UPDATE paper SET status='settled',winner=?,pnl=? WHERE slug=? AND policy=? AND status='pending'",
                (winner,(shares if side==winner else 0)-cost,slug,policy))
        self.db.commit()
        return len(rows)
    def summary(self):
        counts=dict(self.db.execute('SELECT kind,count(*) FROM events GROUP BY kind'))
        policies=[]
        for policy,status,n,pnl in self.db.execute('SELECT policy,status,count(*),sum(pnl) FROM paper GROUP BY policy,status'):
            policies.append({'policy':policy,'status':status,'n':n,'shadow_pnl':pnl})
        return {'event_counts':counts,'paper':policies,'warning':'Displayed-depth hypothetical fills, no exchange execution; independent experiments, budgets recorded per run, not a portfolio backtest.'}


async def record_chainlink(ledger,seconds):
    deadline=time.monotonic()+seconds
    frame={'action':'subscribe','subscriptions':[{'topic':'crypto_prices_twap_sixty','type':'update',
                                                  'filters':'{"symbol":"btc/usd"}'}]}
    while time.monotonic()<deadline:
        try:
            async with websockets.connect('wss://ws-live-data.polymarket.com',ping_interval=None,
                                          open_timeout=10,close_timeout=3) as socket:
                await socket.send(json.dumps(frame))
                ledger.event('chainlink_connected',None,{'topic':'crypto_prices_twap_sixty'})
                async def heartbeat():
                    while True:
                        await socket.send('PING')
                        await asyncio.sleep(5)
                beat=asyncio.create_task(heartbeat())
                try:
                    while time.monotonic()<deadline:
                        raw=await asyncio.wait_for(socket.recv(),timeout=min(15,max(.1,deadline-time.monotonic())))
                        if raw in ('PONG','PING'):
                            continue
                        try:
                            event=json.loads(raw)
                        except (ValueError,TypeError):
                            continue
                        payload=event.get('payload',{}) if isinstance(event,dict) else {}
                        if payload.get('symbol')=='btc/usd':
                            # Preserve full_accuracy_value (E18) and observation timestamp.
                            ledger.event('chainlink_twap',None,event)
                finally:
                    beat.cancel()
                    with suppress(asyncio.CancelledError):
                        await beat
        except (OSError,TimeoutError,websockets.exceptions.WebSocketException) as e:
            ledger.event('chainlink_gap',None,{'error':str(e),'no_history_replay':True})
            await asyncio.sleep(min(3,max(0,deadline-time.monotonic())))


async def freeze_signals(api,ledger,start):
    """Compute only at opening with closed data; never backfill missed decisions."""
    slug=f'btc-updown-15m-{start}'
    at=datetime.fromtimestamp(start,timezone.utc)
    feed=BinanceFeed()
    f,daily=await asyncio.gather(feed.history_5m('BTCUSDT',200,now=at),feed.history_1d('BTCUSDT',30,now=at))
    base=snapshot(f,decision_at=at,daily_frame=daily,policy='latest_5m',
                  session_start_utc=0,session_end_utc=0,router_enabled=True,aux_enabled=True)
    g=features(f,daily_frame=daily)
    r=g.iloc[-1]
    direction=None
    if bool(r.valid15) and r.upper15>r.mid15 and pd.Timestamp(r.decision_at)==pd.Timestamp(at):
        lower=2*r.mid15-r.upper15
        if r.route=='long' and r.close15<=lower:
            direction='up'
        elif r.route=='short' and r.close15>=r.upper15:
            direction='down'
    result={'dca':base.direction,'bb15':direction,'generated_ms':ledger.ms(),
            'signal_source':'Binance BTCUSDT; not the historical Lighter calibration'}
    ledger.event('signals_frozen',slug,{'signals':result,'baseline':asdict(base),
        'candles_5m':f.to_dict('records'),'daily':daily.to_dict('records')})
    if ledger.now()-start>50:
        raise ValueError('Signal computation missed opening deadline')
    return result


async def snapshot_books(api,ledger,start,*,budget=10.):
    slug=f'btc-updown-15m-{start}'
    event=await api.get(f'https://gamma-api.polymarket.com/events/slug/{slug}')
    ledger.event('market_metadata',slug,event)
    if event.get('status')!=200:
        raise ValueError('Gamma unavailable')
    market=parse_market(event['body'],start)
    m=market['raw']
    if m.get('closed') is True or m.get('acceptingOrders') is not True:
        raise ValueError('Market not accepting orders')
    info,*books=await asyncio.gather(api.get(f"https://clob.polymarket.com/clob-markets/{market['condition_id']}"),
        *(api.get('https://clob.polymarket.com/book',token_id=market['tokens'][side]) for side in ['up','down']))
    ledger.event('fee_info',slug,info)
    fee=fee_schedule(market,info.get('body',{}))
    out={}
    for side,response in zip(['up','down'],books):
        ledger.event('orderbook',slug,{'side':side,'response':response,'fee':fee})
        if response.get('status')!=200:
            continue
        book=response['body']
        if str(book.get('asset_id'))!=market['tokens'][side] or book.get('market')!=market['condition_id']:
            ledger.event('book_identity_mismatch',slug,{'side':side})
            continue
        out[side]=book
        try:
            # Cost-only probes on BOTH outcomes, not selected orders or win-rate samples.
            fill=buy_depth(book,fee,budget=budget,max_price=.99,now_ms=ledger.ms())
            ledger.event('depth_cost_probe',slug,{'side':side,**fill})
        except (ValueError,KeyError,TypeError) as e:
            ledger.event('depth_cost_unavailable',slug,{'side':side,'reason':str(e)})
    return market,fee,out


async def settle_pending(api,ledger):
    for slug in ledger.pending():
        start=int(slug.rsplit('-',1)[1])
        if ledger.now()<start+900:
            continue
        event=await api.get(f'https://gamma-api.polymarket.com/events/slug/{slug}')
        try:
            market=parse_market(event['body'],start)
            clob=await api.get(f"https://clob.polymarket.com/markets/{market['condition_id']}")
            label=settlement(market,clob.get('body',{}))
            ledger.event('settlement_check',slug,{'event':event,'clob':clob,'label':label})
            ledger.resolve(slug,label)
        except (ValueError,KeyError,TypeError) as e:
            ledger.event('settlement_error',slug,{'error':str(e)})


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-seconds',type=int,default=120)
    parser.add_argument('--poll-seconds',type=float,default=10)
    parser.add_argument('--budget-usd',type=float,default=10)
    parser.add_argument('--output-dir',type=Path,default=Path('paper_market_capture'))
    parser.add_argument('--settle-only',action='store_true')
    args=parser.parse_args()
    if args.duration_seconds<=0 or args.poll_seconds<5:
        raise ValueError('Require a positive finite duration and poll >=5s')
    if not 0 < args.budget_usd <= 30:
        raise ValueError('Paper budget must be greater than zero and at most $30')
    if not args.output_dir.resolve().is_relative_to(Path(__file__).resolve().parent):
        raise ValueError('Recorder must stay in Bot2')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    ledger=Ledger(args.output_dir/'capture.sqlite3')
    api=PublicArchive(args.output_dir)
    ledger.event('run_plan',None,{'policies':POLICIES,'budget_each':args.budget_usd,'duration_seconds':args.duration_seconds,
        'execution':'shadow only; no calibrated probability or live approval',
        'quote_freshness_ms':5000,'entry_tolerance_seconds':20})
    stream=None
    try:
        geo=await api.get('https://polymarket.com/api/geoblock')
        ledger.event('geoblock',None,geo)
        # Public observation is independent of trading eligibility. No fallback proxy.
        offsets=[]
        for _ in range(3):
            before=time.time()
            server=await api.get('https://clob.polymarket.com/time')
            after=time.time();body=server.get('body')
            if server.get('status')!=200 or not isinstance(body,(int,float)) or after-before>3:
                raise ValueError('Clock synchronization could not be verified')
            offsets.append(body-(before+after)/2)
        if max(offsets)-min(offsets)>2 or abs(sorted(offsets)[1])>300:
            raise ValueError('Unstable/excessive server clock offset')
        ledger.clock_offset=sorted(offsets)[1]
        ledger.event('clock_verified',None,{'offsets_seconds':offsets,'selected_offset_seconds':ledger.clock_offset,
                                           'scope':'process clock only; operating system clock unchanged'})
        await settle_pending(api,ledger)
        if not args.settle_only:
            deadline=time.monotonic()+args.duration_seconds
            stream=asyncio.create_task(record_chainlink(ledger,args.duration_seconds))
            current=None; signals=None; last_settle=0
            while time.monotonic()<deadline:
                tick=time.monotonic();start=int(ledger.now())//900*900;slug=f'btc-updown-15m-{start}'
                elapsed=ledger.now()-start
                if start!=current:
                    current=start;signals=None
                try:
                    if signals is None and 20<=elapsed<=45:
                        signals=await freeze_signals(api,ledger,start)
                    market,fee,books=await snapshot_books(api,ledger,start,budget=args.budget_usd)
                    elapsed=ledger.now()-start
                    for policy in POLICIES:
                        if not policy['delay']<=elapsed<=policy['delay']+20 or ledger.seen(slug,policy['id']):
                            continue
                        side=signals.get(policy['source']) if signals else None
                        if side not in books:
                            ledger.attempt(slug,policy['id'],side,reason='no_frozen_signal_or_book')
                            continue
                        try:
                            book=books[side]
                            ask=min(dec(x['price']) for x in book['asks']);bid=max(dec(x['price']) for x in book['bids'])
                            if (ask+bid)/2<dec(policy['minimum_mid']) or ask-bid>dec(.03):
                                raise ValueError('Agreement or spread filter')
                            cap=min(dec(policy['cap']),(ask+bid)/2+dec(policy.get('max_above_mid',1)))
                            fill=buy_depth(book,fee,budget=args.budget_usd,max_price=float(cap),now_ms=ledger.ms())
                            ledger.attempt(slug,policy['id'],side,fill=fill)
                        except (ValueError,KeyError,TypeError) as e:
                            ledger.attempt(slug,policy['id'],side,reason=str(e))
                    if tick-last_settle>=60:
                        await settle_pending(api,ledger);last_settle=tick
                except Exception as e:
                    ledger.event('tick_error',slug,{'error':str(e)})
                await asyncio.sleep(min(max(0,args.poll_seconds-(time.monotonic()-tick)),max(0,deadline-time.monotonic())))
    finally:
        if stream is not None:
            stream.cancel()
            with suppress(asyncio.CancelledError):
                await stream
        await api.client.aclose()
        result=ledger.summary()
        (args.output_dir/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        ledger.db.close()
        print(json.dumps(result,indent=2))


if __name__=='__main__':
    asyncio.run(main())
