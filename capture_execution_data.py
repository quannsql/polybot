"""Bounded public REST/WSS acquisition probe; never imports the order executor.

Records BOTH outcomes, irrespective of strategy. Depth probes are independent
liquidity scenarios, NOT Variant B trades. Run before a forward replay is possible.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
import json
import statistics
import time

import httpx
import websockets

from polymarket_bot.actual_research import parse_market, fee_schedule, history_asof, buy_depth
from research_fresh_data import dump, sha


async def capture(out, duration, interval):
    out.mkdir(parents=True,exist_ok=True)
    started = time.monotonic()
    deadline = started+duration
    rawfile = out/'events.jsonl'
    counters = Counter(); rtts=[]; ages=[]; clock_offsets=[]; markets={}; ws_errors=[]
    stream = rawfile.open('x',encoding='utf-8')
    def log(kind,payload,**fields):
        stream.write(json.dumps(dict(received_ms=int(time.time()*1000),kind=kind,
            payload=payload,**fields),separators=(',',':'))+'\n')
        stream.flush(); counters[kind]+=1
    async with httpx.AsyncClient(timeout=10) as client:
        async def get(url,**params):
            before=time.time(); begin=time.monotonic()
            try:
                r=await client.get(url,params=params or None)
                rtt=(time.monotonic()-begin)*1000
                try:
                    body=r.json()  # /time can be JSON numeric with text/plain content type.
                except ValueError:
                    body={'text':r.text[:300]}
                result=dict(url=str(r.url),status=r.status_code,body=body,rtt_ms=rtt,
                    requested_ms=int(before*1000),received_ms=int(time.time()*1000))
            except (httpx.HTTPError,ValueError) as exc:
                result=dict(url=url,status=None,error=str(exc))
            return result
        for i in range(3):
            r=await get('https://clob.polymarket.com/time'); log('clock',r)
            if r['status']==200 and type(r['body']) in (int,float) and r['rtt_ms']<3000:
                clock_offsets.append(r['body']*1000-(r['requested_ms']+r['received_ms'])/2)
        offset=statistics.median(clock_offsets) if clock_offsets else None
        ws_task=None; current=None
        async def websocket(tokens,slug):
            try:
                async with websockets.connect('wss://ws-subscriptions-clob.polymarket.com/ws/market',
                        open_timeout=10,close_timeout=2) as ws:
                    await ws.send(json.dumps(dict(type='market',assets_ids=list(tokens.values()))))
                    while time.monotonic()<deadline:
                        try:
                            raw=await asyncio.wait_for(ws.recv(),timeout=min(10,max(.01,deadline-time.monotonic())))
                            log('websocket_raw',raw,slug=slug)
                        except asyncio.TimeoutError:
                            await ws.send('PING')
            except Exception as exc:
                ws_errors.append(type(exc).__name__+': '+str(exc)); log('websocket_error',ws_errors[-1],slug=slug)
        try:
            while time.monotonic()<deadline:
                begin=time.monotonic()
                now=time.time()+(offset or 0)/1000
                start=int(now)//900*900
                if current != start:
                    if ws_task:
                        ws_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await ws_task
                    slug=f'btc-updown-15m-{start}'
                    response=await get('https://gamma-api.polymarket.com/events/slug/'+slug)
                    log('metadata',response,slug=slug)
                    if response['status'] != 200:
                        break
                    m=parse_market(response['body'],start)
                    info=await get('https://clob.polymarket.com/clob-markets/'+m['condition_id'])
                    log('fee_info',info,slug=slug)
                    fee=fee_schedule(m,info.get('body',{}))
                    markets[slug]=dict(rule_type=m['rule_type'],rule_sha256=m['rule_sha256'],
                        tokens=m['tokens'],fee=fee,window_start=start)
                    refs={}
                    for side,token in m['tokens'].items():
                        response=await get('https://clob.polymarket.com/prices-history',
                            market=token,startTs=start-120,endTs=int(now),fidelity=1)
                        log('reference_history',response,slug=slug,side=side)
                        refs[side]=history_asof(response.get('body',{}).get('history',[]),int(now),75)
                    ws_task=asyncio.create_task(websocket(m['tokens'],slug))
                    current=start
                for side,token in m['tokens'].items():
                    response=await get('https://clob.polymarket.com/book',token_id=token)
                    log('rest_book',response,slug=slug,side=side)
                    if response['status'] != 200:
                        continue
                    rtts.append(response['rtt_ms'])
                    book=response['body']; now_ms=response['received_ms']+(offset or 0)
                    age=now_ms-int(book.get('timestamp',0)); ages.append(age)
                    ref=refs[side]
                    for scale in (1.,.5):
                        result=dict(depth_fraction=scale,reference=ref,eligible_strategy_signal=False,
                            interpretation='Independent acquisition probe; reference frozen at probe start, not B entry')
                        try:
                            if offset is None:
                                raise ValueError('server_clock_unverified')
                            if not ref or time.time()+(offset or 0)/1000-ref['timestamp']>75 or ref['price']<.85 or ref['price']+.01>=1:
                                raise ValueError('reference_missing_stale_or_below_threshold')
                            tick=float(book['tick_size'])
                            from decimal import Decimal,ROUND_DOWN
                            cap=float(((Decimal(str(ref['price']))+Decimal('.01'))/Decimal(str(tick))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(tick)))
                            scaled=dict(book,asks=[dict(p,size=str(float(p['size'])*scale)) for p in book['asks']])
                            fill=buy_depth(scaled,fee,budget=20,max_price=cap,now_ms=int(now_ms),max_age_ms=1500)
                            result.update(status='shadow_depth_available',fill=fill,cap=cap)
                        except (ValueError,KeyError,TypeError) as exc:
                            result.update(status='skip',reason=str(exc))
                        log('depth_probe',result,slug=slug,side=side)
                await asyncio.sleep(max(0,min(interval-(time.monotonic()-begin),deadline-time.monotonic())))
        finally:
            if ws_task:
                ws_task.cancel()
                with suppress(asyncio.CancelledError):
                    await ws_task
            stream.close()
    def quantiles(xs):
        if not xs:
            return None
        return dict(min=min(xs),median=statistics.median(xs),max=max(xs))
    result=dict(started_at=datetime.fromtimestamp(time.time()-(time.monotonic()-started),timezone.utc).isoformat(),
        duration_seconds=time.monotonic()-started,counts=dict(counters),markets=markets,
        rest_book_rtt_ms=quantiles(rtts),book_age_ms=quantiles(ages),
        clock_offsets_ms=clock_offsets,websocket_errors=ws_errors,
        file_sha256=sha(rawfile),observed_trade_pnl=None,
        limitations=['No orders submitted. Depth is displayed liquidity, not a guaranteed fill.',
            'Probe observes both sides without DCA/B signals; do not count snapshots as distinct trades.',
            'No assumed 250/500/1000ms latency: measured request/response timestamps are saved.',
            'This records current books only. It does not reconstruct historical books.',
            'Chainlink stream is not captured here; settlement remains a separate later join.'])
    dump(out/'summary.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--duration-seconds',type=int,default=120)
    p.add_argument('--interval-seconds',type=float,default=1.)
    p.add_argument('--output-dir',type=Path,default=Path('data/execution_probe_20261108'))
    args=p.parse_args()
    if not 1<=args.duration_seconds<=86400 or args.interval_seconds<.25:
        raise ValueError('Capture must be bounded (1..86400s), interval >=.25s')
    asyncio.run(capture(args.output_dir,args.duration_seconds,args.interval_seconds))
