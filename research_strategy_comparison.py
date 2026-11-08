"""Public-data comparison of oracle late entry and complete-set acquisition.

Downloads official market labels and references for one free TWAP sample day.
No wallet/secret/order APIs. Historical-reference PnL is never executable PnL.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

import numpy as np
import pandas as pd

from polymarket_bot.actual_research import parse_market,settlement,fee_schedule,history_asof,cash_cost
from research_complete_sets import leg_cost
from research_fresh_data import Archive,dump,sha

OUT=Path('data/strategy_comparison_20261108')
DAY=int(pd.Timestamp('2026-09-01',tz='UTC').timestamp())
DELAYS=(750,840,870,885)
BUFFERS=(0,5,10,20)


def text(value):
    return value.decode() if isinstance(value,bytes) else str(value)


def read_oracle(path):
    f=pd.read_parquet(path)
    f['observed_ms']=pd.to_datetime(f.observationsTimestamp,utc=True).astype('int64')//1000
    f['received_ms']=pd.to_datetime(f.receiveMicrosecondTimestamp,utc=True).astype('int64')//1000
    # Parquet source is microseconds; never guess ns from numeric magnitudes.
    f['value']=f.price.map(lambda p:float(Decimal(str(p))/Decimal(10**18)))
    if not np.isfinite(f.value).all() or (f.value<=0).any():
        raise ValueError('Invalid TWAP price/scaling')
    conflicts=f.groupby('observed_ms').value.nunique().gt(1)
    f=f.loc[~f.observed_ms.isin(conflicts[conflicts].index)].copy()
    return f.sort_values(['observed_ms','received_ms']).drop_duplicates('observed_ms',keep='first')


def oracle_at(f,now_ms,*,exact_ms=None,max_age_ms=3000):
    eligible=f.loc[f.observed_ms.le(now_ms)&f.received_ms.le(now_ms)]
    if exact_ms is not None:
        eligible=eligible.loc[eligible.observed_ms.eq(exact_ms)]
    elif len(eligible):
        eligible=eligible.loc[eligible.observed_ms.ge(now_ms-max_age_ms)]
    if eligible.empty:
        return None
    r=eligible.iloc[-1]
    return dict(value=float(r.value),observed_ms=int(r.observed_ms),received_ms=int(r.received_ms))


def oracle_decision(f,start,delay):
    now=(start+delay)*1000
    opening=oracle_at(f,now,exact_ms=start*1000)
    if opening is None or opening['received_ms']>start*1000+5000:
        return None,'opening_report_missing_or_late'
    current=oracle_at(f,now)
    if current is None:
        return None,'oracle_missing_or_stale'
    recent=f.loc[f.observed_ms.ge(now-60000)&f.observed_ms.le(now)&f.received_ms.le(now)].sort_values('observed_ms')
    if len(recent)<30 or recent.observed_ms.diff().max()>5000:
        return None,'oracle_gap'
    lead=(current['value']/opening['value']-1)*10000
    return dict(start=start,delay=delay,side='up' if lead>=0 else 'down',
        absolute_lead_bps=abs(lead),signed_lead_bps=lead,opening=opening,current=current), 'valid'


async def download_day(api):
    async def window(start):
        base=Path(f'raw/markets/{start}')
        ev=await api.get(base/'event.json',f'https://gamma-api.polymarket.com/events/slug/btc-updown-15m-{start}')
        record=dict(start=start,event=ev)
        try:
            if ev['status']!=200:
                raise ValueError('Gamma unavailable')
            m=parse_market(ev['body'],start)
            if m['raw'].get('version','v1')!='v1':
                raise ValueError('Unsupported asset version')
            specs=[('clob',f'https://clob.polymarket.com/markets/{m["condition_id"]}',{}),
                ('fee_info',f'https://clob.polymarket.com/clob-markets/{m["condition_id"]}',{})]
            specs += [(side+'_history','https://clob.polymarket.com/prices-history',
                dict(market=m['tokens'][side],startTs=start,endTs=start+900,fidelity=1)) for side in ('up','down')]
            values=await asyncio.gather(*(api.get(base/(name+'.json'),url,**params) for name,url,params in specs))
            record.update(dict(zip([x[0] for x in specs],values)))
            record['parsed']={k:v for k,v in m.items() if k!='raw'}
            record['settlement']=settlement(m,record['clob'].get('body',{}))
            record['fee']=fee_schedule(m,record['fee_info'].get('body',{}))
        except (ValueError,KeyError,TypeError) as exc:
            record['error']=str(exc)
        dump(api.out/base/'combined.json',record)
        return record
    records=[]
    for offset in range(0,96,8):
        records+=await asyncio.gather(*(window(DAY+i*900) for i in range(offset,min(offset+8,96))))
        print(f'Official TWAP-day market archives: {len(records)}/96',flush=True)
    return records


def reference_trade(feature,record,min_lead,padding=.01):
    if feature['absolute_lead_bps']<min_lead:
        return None,'buffer'
    if record.get('settlement',{}).get('status')!='confirmed':
        return None,'settlement_unknown'
    if record.get('fee',{}).get('status')!='known':
        return None,'fee_unknown'
    hist=record.get(feature['side']+'_history',{})
    q=history_asof(hist.get('body',{}).get('history',[]),feature['start']+feature['delay'],75) if hist.get('status')==200 else None
    if not q:
        return None,'reference_missing'
    if q['price']<.85:
        return None,'reference_below_085'
    price=Decimal(str(q['price']))+Decimal(str(padding))
    if price>=1:
        return None,'reference_plus_pad_ge_one'
    shares=20/cash_cost(float(price),record['fee'])
    won=feature['side']==record['settlement']['winner']
    return dict(start=feature['start'],side=feature['side'],won=won,reference=q,
        assumed_price=float(price),shares=shares,pnl=shares*won-20,
        absolute_lead_bps=feature['absolute_lead_bps']), 'modeled_fill'


def stats(rows):
    n=len(rows); w=sum(r['won'] for r in rows)
    return dict(n=n,wins=w,losses=n-w,win_rate=w/n if n else None,
        pnl=sum(r['pnl'] for r in rows) if n else None,
        mean_pnl=sum(r['pnl'] for r in rows)/n if n else None)


def analyze_oracle(f,records):
    features=[]; rejected=Counter(); checks=[]
    for record in records:
        start=record['start']
        # Official start/final metadata is ONLY an audit, not an entry feature.
        gamma=record.get('event',{}).get('body',{}).get('eventMetadata',{})
        for key,at in [('priceToBeat',start),('finalPrice',start+900)]:
            point=oracle_at(f,(start+910)*1000,exact_ms=at*1000)
            if point and gamma.get(key) is not None:
                error=abs(point['value']-float(gamma[key]))
                checks.append(dict(start=start,field=key,source_price=point['value'],gamma_price=float(gamma[key]),absolute_error=error))
        for delay in DELAYS:
            feature,reason=oracle_decision(f,start,delay)
            if feature is None:
                rejected[reason]+=1
            else:
                feature['label']=record.get('settlement',{})
                feature['day_half']='first' if start<DAY+43200 else 'second'
                features.append(feature)
    by_start={r['start']:r for r in records}
    policies=[]
    for delay in DELAYS:
        all_features=[x for x in features if x['delay']==delay]
        for buffer in BUFFERS:
            rows=[]; counts=Counter(); qualified=[]
            for feature in all_features:
                row,reason=reference_trade(feature,by_start[feature['start']],buffer)
                counts[reason]+=1
                if feature['absolute_lead_bps']>=buffer and feature['label'].get('status')=='confirmed':
                    qualified.append(dict(won=feature['side']==feature['label']['winner'],pnl=0.))
                if row:
                    rows.append(row)
            policies.append(dict(delay=delay,min_lead_bps=buffer,oracle_direction_only=stats(qualified),
                modeled_reference_pnl=stats(rows),statuses=dict(counts),
                first_half=stats([r for r in rows if r['start']<DAY+43200]),
                second_half=stats([r for r in rows if r['start']>=DAY+43200])))
    changes={}
    for delay in DELAYS:
        out=[]
        for feature in features:
            if feature['delay']!=delay:
                continue
            final=oracle_at(f,(feature['start']+910)*1000,exact_ms=(feature['start']+900)*1000)
            if final:
                out.append(dict(day_half=feature['day_half'],move_bps=abs(final['value']/feature['current']['value']-1)*10000))
        changes[str(delay)]={half:dict(n=len(vals),p95=float(np.quantile(vals,.95)) if vals else None,
            p99=float(np.quantile(vals,.99)) if vals else None,max=max(vals,default=None))
            for half in ('first','second') for vals in [[x['move_bps'] for x in out if x['day_half']==half]]}
    confirmed=sum(r.get('settlement',{}).get('status')=='confirmed' for r in records)
    audit=dict(checked=len(checks),matching_to_1cent=sum(x['absolute_error']<=.01 for x in checks),
        max_absolute_error=max((x['absolute_error'] for x in checks),default=None),rows=checks)
    return dict(reports=len(f),official_confirmed_markets=confirmed,valid_features=len(features),
        feature_rejections=dict(rejected),price_audit=audit,policies=policies,
        absolute_future_twap_move_bps=changes,observed_execution_pnl=None),features


class BookState:
    """Receive-order L2 reconstruction; gaps invalidate until a full snapshot."""
    def __init__(self):
        self.bids={}; self.asks={}; self.valid=False; self.received_ms=0; self.observed_ms=0; self.last_seq=None

    def apply(self,kind,bids,asks,observed_ms,received_ms,*,seq=None,status=''):
        if kind=='status':
            self.valid=False; self.last_seq=None
            return
        if kind=='book':
            self.bids={float(p):float(s) for p,s in bids if float(s)>0}
            self.asks={float(p):float(s) for p,s in asks if float(s)>0}
            self.valid=True
        elif kind=='price_change':
            if not self.valid:
                return
            if seq is not None and self.last_seq is not None and seq!=self.last_seq+1:
                self.valid=False; self.last_seq=None
                return
            for levels,target in ((bids,self.bids),(asks,self.asks)):
                for p,s in levels:
                    p,s=float(p),float(s)
                    if s>0:
                        target[p]=s
                    else:
                        target.pop(p,None)
        else:
            return
        self.observed_ms=int(observed_ms); self.received_ms=int(received_ms); self.last_seq=seq

    def book(self,at_ms,max_age=1500):
        if not self.valid or self.received_ms>at_ms or not -1000<=at_ms-self.observed_ms<=max_age:
            raise ValueError('Unverified or stale book')
        if not self.bids or not self.asks or max(self.bids)>=min(self.asks):
            raise ValueError('Empty/crossed book')
        return dict(bids=[dict(price=p,size=s) for p,s in self.bids.items()],
            asks=[dict(price=p,size=s) for p,s in self.asks.items()])


def paired_cost(up,down,q,rate):
    cost=leg_cost(up,q,rate)+leg_cost(down,q,rate)
    return dict(quantity=q,cost=cost,net_before_other_costs=q-cost,roi=(q-cost)/cost)


def replay_vike(path,rate=.07):
    f=pd.read_parquet(path).sort_values('local_ts',kind='stable')
    books={}; pairs=[]; reasons=Counter(); prev_check=-1
    for r in f.itertuples():
        token=str(r.token_id); book=books.setdefault(token,BookState())
        kind=text(r.event_type)
        if kind not in ('book','price_change','status'):
            continue
        book.apply(kind,json.loads(r.bids or '[]'),json.loads(r.asks or '[]'),r.ts,r.local_ts,
            seq=int(r.seq) if r.seq else None,status=str(r.status))
        if r.local_ts//1000==prev_check or len(books)!=2:
            continue
        prev_check=r.local_ts//1000
        try:
            legs=[b.book(r.local_ts) for b in books.values()]
            x=paired_cost(*legs,5,rate)
            pairs.append(dict(received_ms=int(r.local_ts),**x))
        except ValueError as exc:
            reasons[str(exc)]+=1
    return dict(raw_events=len(f),sample_seconds=len(pairs),rejected_seconds=dict(reasons),
        positive_seconds=sum(r['net_before_other_costs']>0 for r in pairs),
        best_net_5pairs=max((r['net_before_other_costs'] for r in pairs),default=None),
        median_net_5pairs=float(np.median([r['net_before_other_costs'] for r in pairs])) if pairs else None,
        rate_assumption=rate,observations=pairs,
        limitation='BTC5m sample, November 6; not the TWAP day or a daily strategy return. Fee rate sensitivity, not as-of attestation.')


async def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--offline',action='store_true')
    args=parser.parse_args(); OUT.mkdir(parents=True,exist_ok=True)
    protocol=dict(day='2026-09-01',oracle_source='PMData direct Chainlink TWAP60s free sample, E18',
        delays=DELAYS,buffers_bps=BUFFERS,oracle_max_age_ms=3000,oracle_max_gap_ms=5000,
        reference_min=.85,padding=.01,budget=20,price_model='historical reference, not actual fill',
        direction='Follow current TWAP vs opening exact report; independent oracle policy, NOT DCA/Variant B',
        selection='Report all 16 fixed policies; no best-policy choice',
        book_sample='Vike both-token BTC5m November6, sampled once per receive-time second, gaps invalidated',
        comparison='Different datasets and horizons: feasibility/economics study, no validated PnL ranking',
        sources={p:sha(p) for p in [str(OUT/'BTCUSD_twap60s.parquet'),'data/orderbook_samples/vike_book_events.parquet']},
        code_sha256=sha(Path(__file__)))
    p=OUT/'protocol.json'
    if p.exists() and json.loads(p.read_text())!=json.loads(json.dumps(protocol)):
        raise ValueError('Protocol changed: preserve run before rerunning')
    dump(p,protocol)
    api=Archive(OUT,args.offline)
    try:
        records=await download_day(api)
    finally:
        await api.client.aclose()
    oracle=read_oracle(OUT/'BTCUSD_twap60s.parquet')
    result,features=analyze_oracle(oracle,records)
    dump(OUT/'oracle_summary.json',result); dump(OUT/'oracle_features.json',features)
    arbitrage={str(r):replay_vike('data/orderbook_samples/vike_book_events.parquet',r) for r in (0,.07)}
    dump(OUT/'complete_set_replay.json',arbitrage)
    print(json.dumps(dict(oracle={k:v for k,v in result.items() if k not in ('price_audit','policies')},
        price_audit={k:v for k,v in result['price_audit'].items() if k!='rows'},
        complete_set={k:{a:b for a,b in v.items() if a!='observations'} for k,v in arbitrage.items()}),indent=2))


if __name__=='__main__':
    asyncio.run(main())
