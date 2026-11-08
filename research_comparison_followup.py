"""Data-quality sensitivity and conservative two-leg maker queue scenarios.

Follow-up on previously scored small samples, NOT independent validation.
"""
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

import pandas as pd

from polymarket_bot.actual_research import history_asof,cash_cost
from research_strategy_comparison import BookState,text,stats
from research_fresh_data import dump,sha

SOURCE=Path('data/strategy_comparison_20261108')
OUT=Path('data/strategy_followup_20261108')


def price_sensitivity(features,records):
    results=[]
    for delay in (840,870):
        for buffer in (0,5,10):
            for age in (75,15):
                for pad in (.01,.001):
                    rows=[]; status=Counter()
                    for feature in features:
                        if feature['delay']!=delay:
                            continue
                        r=records[feature['start']]
                        if feature['absolute_lead_bps']<buffer:
                            status['buffer']+=1; continue
                        if r.get('settlement',{}).get('status')!='confirmed' or r.get('fee',{}).get('status')!='known':
                            status['label_or_fee_unknown']+=1; continue
                        hist=r.get(feature['side']+'_history',{})
                        q=history_asof(hist.get('body',{}).get('history',[]),feature['start']+delay,age) if hist.get('status')==200 else None
                        if not q:
                            status['reference_missing_or_stale']+=1; continue
                        if q['price']<.85:
                            status['reference_below_085']+=1; continue
                        price=Decimal(str(q['price']))+Decimal(str(pad))
                        if price>=1:
                            status['price_ge_one_nonfill']+=1; continue
                        shares=20/cash_cost(float(price),r['fee'])
                        won=feature['side']==r['settlement']['winner']
                        status['modeled_fill']+=1
                        rows.append(dict(won=won,pnl=shares*won-20))
                    results.append(dict(delay=delay,buffer_bps=buffer,max_reference_age=age,padding=pad,
                        statuses=dict(status),**stats(rows)))
    return results


class QueueLeg:
    def __init__(self,token,price,queue,quantity):
        self.token,self.price=token,float(price)
        self.queue,self.target,self.filled=float(queue),float(quantity),0.

    def trade(self,token,side,price,size):
        if token!=self.token or side!='sell' or abs(float(price)-self.price)>1e-10:
            return
        size=float(size)
        consumed=min(self.queue,size); self.queue-=consumed
        self.filled+=min(self.target-self.filled,max(0.,size-consumed))


def maker_replay(path,start):
    f=pd.read_parquet(path).sort_values('local_ts',kind='stable')
    states={}; scenarios=[]
    for offset in (5,60,120,180):
        for latency in (250,1000):
            scenarios.append(dict(offset_seconds=offset,latency_ms=latency,
                placed_ms=(start+offset)*1000,activated_ms=(start+offset)*1000+latency,
                expires_ms=(start+offset+30)*1000,state='waiting',prices={},legs=[]))
    for r in f.itertuples():
        at=int(r.local_ts); token=str(r.token_id); kind=text(r.event_type)
        for s in scenarios:
            if s['state']=='waiting' and at>=s['placed_ms']:
                try:
                    if len(states)!=2: raise ValueError('Need two observed token books')
                    books={t:b.book(s['placed_ms']) for t,b in states.items()}
                    s['prices']={t:max(float(x['price']) for x in b['bids']) for t,b in books.items()}
                    if sum(s['prices'].values())>=1: raise ValueError('No maker complete-set discount')
                    s['state']='pending'
                except ValueError as exc:
                    s['state']='skipped'; s['reason']=str(exc)
            if s['state']=='pending' and at>=s['activated_ms']:
                try:
                    for t,b in states.items():
                        book=b.book(s['activated_ms'])
                        price=s['prices'][t]
                        if price>=min(float(x['price']) for x in book['asks']):
                            raise ValueError('Would cross after latency; post-only rejected')
                        # All depth currently ahead; cancellations never create our fills.
                        queue=sum(float(x['size']) for x in book['bids'] if abs(float(x['price'])-price)<1e-10)
                        s['legs'].append(QueueLeg(t,price,queue,5))
                    s['state']='active'
                except ValueError as exc:
                    s['state']='skipped'; s['reason']=str(exc)
            if s['state']=='active' and at>s['expires_ms']:
                s['state']='expired'
            if s['state']=='active':
                if kind=='status':
                    s['state']='invalid_gap'; s['reason']='Public feed gap/status invalidates queue'
                elif kind=='trade' and s['activated_ms']<=int(r.ts)<=at<=s['expires_ms']:
                    for leg in s['legs']:
                        leg.trade(token,text(r.side),r.price,r.size)
        if kind in ('book','price_change','status'):
            book=states.setdefault(token,BookState())
            book.apply(kind,json.loads(r.bids or '[]'),json.loads(r.asks or '[]'),r.ts,r.local_ts,
                seq=int(r.seq) if r.seq else None,status=str(r.status))
    output=[]
    for s in scenarios:
        legs=[dict(token=x.token,price=x.price,filled=x.filled,queue_remaining=x.queue,target=x.target) for x in s.pop('legs')]
        quantities=[x['filled'] for x in legs]
        paired=min(quantities) if len(quantities)==2 else 0.
        full=len(quantities)==2 and all(q>=5-1e-10 for q in quantities) and s['state']!='invalid_gap'
        output.append(dict(**s,legs=legs,full_pair_scenario=full,matched_shares=paired,
            unmatched_shares=max(quantities,default=0.)-paired,
            matched_margin_before_other_costs=paired*(1-sum(s['prices'].values())) if paired else 0.))
    return dict(scenarios=output,full_pair_scenarios=sum(x['full_pair_scenario'] for x in output),
        statuses=dict(Counter(x['state'] for x in output)),
        limitation='8 parallel queue hypotheses on ONE BTC5m market. Unknown real queue priority and arrival ordering; no claimed fills/PnL.')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    features=json.loads((SOURCE/'oracle_features.json').read_text())
    records={int(p.parent.name):json.loads(p.read_text()) for p in (SOURCE/'raw/markets').glob('*/combined.json')}
    source='data/orderbook_samples/vike_book_events.parquet'
    protocol=dict(code_sha256=sha(Path(__file__)),oracle_features_sha256=sha(SOURCE/'oracle_features.json'),
        book_sha256=sha(source),study='Posthoc data quality and execution sensitivity; no independent holdout',
        maker='5 shares per outcome, 30s expiry, FIFO queue; exact SELL prints only; invalidate at gaps; no rebate',
        taker='Freshness75/15s and padding1c/0.1c; reference price assumptions, not displayed asks')
    path=OUT/'protocol.json'
    if path.exists() and json.loads(path.read_text())!=protocol:
        raise ValueError('Preserve existing protocol before changing run')
    dump(path,protocol)
    result=dict(reference_sensitivity=price_sensitivity(features,records),
        maker=maker_replay(source,1793952300))
    raw=pd.read_parquet(SOURCE/'BTCUSD_twap60s.parquet')
    observed=pd.to_datetime(raw.observationsTimestamp).dt.as_unit('ms').astype('int64')
    received=pd.to_datetime(raw.receiveMicrosecondTimestamp).dt.as_unit('ms').astype('int64')
    lag=received-observed
    result['oracle_provider_latency_ms']=dict(rows=len(raw),median=float(lag.median()),p99=float(lag.quantile(.99)),
        max=int(lag.max()),negative_count=int((lag<0).sum()),source='PMData provider site, not user server')
    dump(OUT/'summary.json',result)
    print(json.dumps(dict(maker=result['maker'],oracle_latency=result['oracle_provider_latency_ms']),indent=2))


if __name__=='__main__':
    main()
