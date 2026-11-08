"""Partial-coverage BTC15m captured-ask replay for the frozen TWAP policies.

This is a quote-capacity scenario, NOT exchange-confirmed fills. Unknown clock
alignment and uncovered days are reported, never extrapolated to a week return.
"""
from collections import Counter,defaultdict
from decimal import Decimal,ROUND_DOWN,ROUND_UP
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_fresh_data import dump,sha
from research_twap_stability import FIT,END,replay

ROOT=Path('data/twap_stability_20261108')
OUT=ROOT/'depth_study'


class QuoteIndex:
    def __init__(self,frame):
        self.groups={}
        f=frame.sort_values(['captured_ms','priority']).drop_duplicates(['start','side','captured_ms'],keep='last')
        for key,g in f.groupby(['start','side'],sort=False):
            self.groups[key]=dict(times=g.captured_ms.to_numpy(dtype=np.int64),
                bid=g.bid.to_numpy(float),ask=g.ask.to_numpy(float),size=g.ask_size.to_numpy(float),
                source=g.source.to_numpy())

    def at(self,start,side,now,max_age=1500,clock_shift=0):
        group=self.groups.get((start,side))
        if group is None:
            return None,'no_book_coverage'
        i=np.searchsorted(group['times'],now-clock_shift,side='right')-1
        if i<0:
            return None,'no_prior_book'
        available=int(group['times'][i])+clock_shift
        if now-available>max_age:
            return None,'capture_too_old'
        bid,ask,size=group['bid'][i],group['ask'][i],group['size'][i]
        if not np.isfinite([bid,ask,size]).all() or not 0<bid<ask<1 or size<=0:
            return None,'invalid_one_sided_or_crossed_quote'
        return dict(captured_ms=int(group['times'][i]),available_ms=available,bid=float(bid),
            ask=float(ask),ask_size=float(size),source=str(group['source'][i])), 'valid'


def load_quotes(records):
    g=pd.read_parquet(ROOT/'quotes/github_btc15m_quotes.parquet')
    g=g.loc[g.window_start.ge(FIT)&g.window_start.lt(END)&g.ok.eq(1)].copy()
    if not g.slug.eq('btc-updown-15m-'+g.window_start.astype(str)).all() or not (g.window_end-g.window_start).eq(900).all():
        raise ValueError('Quote identity/window mismatch')
    frames=[]
    for side in ('up','down'):
        frames.append(pd.DataFrame(dict(start=g.window_start,side=side,captured_ms=g.ts_ms,
            bid=g[side+'_bid'],ask=g[side+'_ask'],ask_size=g[side+'_ask_sz'],
            source='github_top',priority=0)))
    h=pd.read_parquet(ROOT/'quotes/hf_btc15m_l2.parquet')
    h['start']=h.market_slug.str.rsplit('-',n=1).str[-1].astype('int64')
    h=h.loc[h.start.ge(FIT)&h.start.lt(END)].copy()
    rows=[]; statuses=Counter()
    for r in h.itertuples():
        tokens=records.get(r.start,{}).get('parsed',{}).get('tokens',{})
        matches=[side for side,t in tokens.items() if str(t)==str(r.token_id)]
        if len(matches)!=1:
            statuses['token_identity_unknown']+=1; continue
        asks=list(zip(r.ask_prices,r.ask_sizes)); bids=list(zip(r.bid_prices,r.bid_sizes))
        if not asks or not bids:
            statuses['empty_side']+=1; continue
        ask=min(float(p) for p,s in asks)
        size=sum(float(s) for p,s in asks if float(p)==ask)
        rows.append(dict(start=int(r.start),side=matches[0],captured_ms=int(pd.Timestamp(r.captured_at).timestamp()*1000),
            bid=max(float(p) for p,s in bids),ask=ask,ask_size=size,source='hf_full_ladder_top_only',priority=1))
    frames.append(pd.DataFrame(rows))
    frame=pd.concat(frames,ignore_index=True)
    frame.start=frame.start.astype('int64'); frame.captured_ms=frame.captured_ms.astype('int64')
    coverage={}
    for source,f in frame.groupby('source'):
        coverage[source]=dict(rows=len(f),markets=f.start.nunique(),first_capture_ms=int(f.captured_ms.min()),
            last_capture_ms=int(f.captured_ms.max()),days=sorted(pd.to_datetime(f.start,unit='s',utc=True).dt.strftime('%Y-%m-%d').unique()))
    return QuoteIndex(frame),dict(sources=coverage,hf_rejections=dict(statuses))


def top_fill(quote,fee,budget=15,haircut=.5):
    """Reserve whole budget conservatively; shares/fee rounded within cash cap."""
    p=Decimal(str(quote['ask'])); rate=Decimal(str(fee['rate'])); b=Decimal(str(budget))
    per=rate*p*(1-p)
    shares=(b/(p+per)).quantize(Decimal('.0001'),rounding=ROUND_DOWN)
    charged=(shares*per).quantize(Decimal('.00001'),rounding=ROUND_UP)
    cost=shares*p+charged
    if cost>b:
        shares-=Decimal('.0001'); charged=(shares*per).quantize(Decimal('.00001'),rounding=ROUND_UP); cost=shares*p+charged
    if shares<5 or shares*p<5:
        raise ValueError('below_conservative_minimum')
    if shares>Decimal(str(quote['ask_size']))*Decimal(str(haircut)):
        raise ValueError('insufficient_top_depth')
    return dict(shares=float(shares),charged_cost=float(cost),reserved_budget=budget,
        winning_pnl_reserved=float(shares)-budget)


def candidate(feature,record,quotes,buffer,latency=500,haircut=.5,age=1500,clock_shift=0):
    if feature['lead_bps']<buffer:
        return None,'buffer'
    if record.get('settlement',{}).get('status')!='confirmed' or record.get('fee',{}).get('status')!='known':
        return None,'label_or_fee_unknown'
    start=feature['start']; decision=(start+feature['delay'])*1000
    before,why=quotes.at(start,feature['side'],decision,age,clock_shift)
    if before is None:
        return None,why
    if not .85<=before['ask']<=.99:
        return None,'decision_ask_outside_085_099'
    cap=min(.99,float(Decimal(str(before['ask']))+Decimal('.001')))
    after,why=quotes.at(start,feature['side'],decision+latency,age,clock_shift)
    if after is None:
        return None,'arrival_'+why
    if after['available_ms']<decision:
        return None,'no_arrival_refresh_observation'
    if after['ask']>cap:
        return None,'arrival_ask_above_frozen_cap'
    try:
        fill=top_fill(after,record['fee'],15,haircut)
    except ValueError as exc:
        return None,str(exc)
    if fill['winning_pnl_reserved']<.05:
        return None,'winning_margin_below_005'
    won=feature['side']==record['settlement']['winner']
    return dict(start=start,side=feature['side'],decision_seconds=start+feature['delay'],
        day=pd.Timestamp(start,unit='s',tz='UTC').strftime('%Y-%m-%d'),won=won,
        unit_cost=15/fill['shares'],stressed_unit_cost=None,
        initial_quote=before,arrival_quote=after,cap=cap,**fill), 'captured_depth_scenario'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inputs=[ROOT/'quotes/github_btc15m_quotes.parquet',ROOT/'quotes/hf_btc15m_l2.parquet',ROOT/'features.json',ROOT/'tail_calibration.json']
    protocol=dict(code_sha256=sha(Path(__file__)),sources={str(p):sha(p) for p in inputs},
        evaluation='2026-08-15..21 UTC; partial BTC15m quote coverage only',budget=15,
        same_oracle_profiles_as='stability_protocol.json',min_ask=.85,max_ask=.99,
        frozen_cap='min(0.99, decision captured ask+0.001); new execution sub-study, NOT old ref+1c rule',
        latencies_ms=[250,500,1000],depth_fractions=[1,.5],max_capture_ages_ms=[1500,5000],
        primary=dict(latency_ms=500,depth_fraction=.5,max_capture_age_ms=1500,clock_shift_ms=0),
        clock_sensitivity_ms=[-1000,1000],arrival='Need a new quote captured between decision and hypothetical arrival; no future books',
        costs='Metadata fee curve; rounded shares/fees; whole $15 reserved, tiny unused cash conservatively not credited; no rebate',
        validity='Captured top depth capacity only. Quote timestamps unverified; no exchange acknowledgments or guaranteed FOK fills.',
        selection='Sub-study fixed before its quote results scored; no selection to hit desired daily PnL')
    p=OUT/'protocol.json'
    if p.exists() and json.loads(p.read_text())!=protocol:
        raise ValueError('Preserve existing protocol if changing run')
    dump(p,protocol)
    features=[f for f in json.loads((ROOT/'features.json').read_text()) if FIT<=f['start']<END]
    fit=json.loads((ROOT/'tail_calibration.json').read_text())
    records={int(p.parent.name):json.loads(p.read_text()) for p in (ROOT/'raw/markets').glob('*/combined.json')}
    quotes,coverage=load_quotes(records)
    results=[]; allrows=[]
    policies=[('control_1400_5bp',840,5),('strict_1400_10bp',840,10),('strict_1430_10bp',870,10),('tail_1400',840,fit['tail_buffer_bps'])]
    for name,delay,buffer in policies:
        scenarios=[(l,d,a,0) for l in (250,500,1000) for d in (1,.5) for a in (1500,5000)]
        scenarios += [(500,.5,1500,s) for s in (-1000,1000)]
        for latency,depth,age,shift in scenarios:
            status=Counter(); missing_losers=Counter(); rows=[]
            for feature in features:
                if feature['delay']!=delay:
                    continue
                record=records[feature['start']]
                row,reason=candidate(feature,record,quotes,buffer,latency,depth,age,shift)
                status[reason]+=1
                if feature['lead_bps']>=buffer and record.get('settlement',{}).get('winner')!=feature['side']:
                    missing_losers[reason]+=1
                if row:
                    rows.append(row)
            portfolio=replay(rows,15,True,300,overhead=.01)
            result=dict(policy=name,latency_ms=latency,depth_fraction=depth,max_capture_age_ms=age,clock_shift_ms=shift,
                n=len(rows),wins=sum(r['won'] for r in rows),losses=sum(not r['won'] for r in rows),
                counts=dict(status),known_oracle_losers_by_reason=dict(missing_losers),
                covered_subset_wallet=portfolio,
                warning='Partial quote coverage + clock assumptions. Subset PnL is NOT a full-week executable return.')
            results.append(result)
            if (latency,depth,age,shift)==(500,.5,1500,0):
                allrows.extend(dict(policy=name,**r) for r in rows)
    report=dict(coverage=coverage,scenarios=results,certified_week_execution_pnl=None,
        note='Missing quote dates and known losses cannot be assumed to be nonfills or zero-PnL days; do not extrapolate subset.')
    dump(OUT/'summary.json',report); dump(OUT/'primary_trades.json',allrows)
    print(json.dumps(dict(coverage=coverage,primary=[r for r in results if (r['latency_ms'],r['depth_fraction'],r['max_capture_age_ms'],r['clock_shift_ms'])==(500,.5,1500,0)]),indent=2))


if __name__=='__main__':
    main()
