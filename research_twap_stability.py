"""BTC15m TWAP stability study: seven days calibration, seven days evaluation.

Actual Chainlink TWAP reports + official settlement; price-history PnL is a
reference scenario only. Absence of BTC15m L2 blocks executable-PnL claims.
Public GET only, no signer, wallet, approval or order imports.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from polymarket_bot.actual_research import parse_market,settlement,fee_schedule,history_asof,cash_cost
from research_fresh_data import Archive,dump,sha

ROOT=Path('data/twap_stability_20261108')
START=int(pd.Timestamp('2026-08-08',tz='UTC').timestamp())
FIT=int(pd.Timestamp('2026-08-15',tz='UTC').timestamp())
END=int(pd.Timestamp('2026-08-22',tz='UTC').timestamp())
DELAYS=(840,870)


class TwapIndex:
    def __init__(self,frame):
        f=frame.sort_values(['observed_ms','received_ms']).drop_duplicates('observed_ms',keep='first')
        self.observed=f.observed_ms.to_numpy(dtype=np.int64)
        self.received=f.received_ms.to_numpy(dtype=np.int64)
        self.values=f.value.to_numpy(dtype=float)

    def at(self,now_ms,exact_ms=None,max_age_ms=3000):
        if exact_ms is not None:
            i=np.searchsorted(self.observed,exact_ms)
            if i==len(self.observed) or self.observed[i]!=exact_ms or self.received[i]>now_ms:
                return None
        else:
            hi=np.searchsorted(self.observed,now_ms,side='right')
            lo=np.searchsorted(self.observed,now_ms-max_age_ms)
            known=np.flatnonzero(self.received[lo:hi]<=now_ms)
            if not len(known):
                return None
            i=lo+known[-1]
        return dict(value=float(self.values[i]),observed_ms=int(self.observed[i]),received_ms=int(self.received[i]))

    def decision(self,start,delay):
        now=(start+delay)*1000
        opening=self.at(now,exact_ms=start*1000)
        if not opening or opening['received_ms']>start*1000+5000:
            return None,'opening_missing_or_late'
        current=self.at(now)
        if not current:
            return None,'oracle_stale_or_missing'
        lo=np.searchsorted(self.observed,now-60000)
        hi=np.searchsorted(self.observed,now,side='right')
        stamps=self.observed[lo:hi][self.received[lo:hi]<=now]
        if len(stamps)<30 or np.diff(stamps).max()>5000:
            return None,'oracle_gap'
        lead=(current['value']/opening['value']-1)*10000
        return dict(start=start,delay=delay,side='up' if lead>=0 else 'down',
            lead_bps=abs(lead),opening=opening,current=current),'valid'


def load_reports():
    files=sorted((ROOT/'twap').glob('*.parquet'))
    if len(files)!=14:
        raise ValueError('Exactly 14 source days required; no filling missing days')
    frames=[]; manifests=[]
    for path in files:
        f=pd.read_parquet(path)
        observed=pd.to_datetime(f.observationsTimestamp,utc=True).dt.as_unit('ms').astype('int64')
        received=pd.to_datetime(f.receiveMicrosecondTimestamp,utc=True).dt.as_unit('ms').astype('int64')
        # Preserve raw exact integers for conflict detection before float features.
        exact=f.price.map(lambda x:str(Decimal(str(x))))
        value=f.price.map(lambda x:float(Decimal(str(x))/Decimal(10**18)))
        if not np.isfinite(value).all() or (value<=0).any() or ((received-observed)<-1000).any():
            raise ValueError('Invalid report values/time scaling')
        frames.append(pd.DataFrame(dict(observed_ms=observed,received_ms=received,value=value,exact=exact)))
        lag=received-observed
        manifests.append(dict(day=path.stem,rows=len(f),sha256=sha(path),median_receive_lag_ms=float(lag.median()),
            p99_receive_lag_ms=float(lag.quantile(.99)),first_observed_ms=int(observed.min()),last_observed_ms=int(observed.max())))
    merged=pd.concat(frames,ignore_index=True)
    conflicts=merged.groupby('observed_ms').exact.nunique().gt(1)
    bad=set(conflicts[conflicts].index)
    clean=merged.loc[~merged.observed_ms.isin(bad)].copy()
    duplicates=len(clean)-clean.observed_ms.nunique()
    clean=clean.sort_values(['observed_ms','received_ms']).drop_duplicates('observed_ms',keep='first')
    audit=dict(days=manifests,raw_rows=len(merged),usable_unique_reports=len(clean),
        conflicting_instants=len(bad),agreeing_duplicate_rows=int(duplicates))
    dump(ROOT/'report_quality.json',audit)
    return TwapIndex(clean),audit


def freeze():
    source=json.loads((ROOT/'download_manifest.json').read_text())
    protocol=dict(version=1,instrument='BTC Up/Down 15m',start=START,fit_at=FIT,end_exclusive=END,
        calibration='2026-08-08..14 UTC',evaluation='2026-08-15..21 UTC',
        primary='strict_1400_10bp, $15 all-in, one-loss-per-day stop, initial $50',
        policies=[dict(id='control_1400_5bp',delay=840,buffer=5),
            dict(id='strict_1400_10bp',delay=840,buffer=10),
            dict(id='strict_1430_10bp',delay=870,buffer=10),
            dict(id='tail_1400',delay=840,buffer='max(10, training99pct_abs_future_twap_move+2bp)')],
        stakes=[10,15,20],loss_stops=['none','one_losing_trade_per_day'],initial_cash=50,
        redemption_delays_seconds=[0,300,1800],minimum_reference=.85,padding=.01,
        quote_age_seconds=[75,15],stress_additional_cents=1,overhead_per_fill=[0,.01,.05],
        signal='Follow TWAP versus exact opening report received within5s; current age<=3s; no gap>5s',
        training_tail='Only final oracle reports RECEIVED before FIT; no test observations or official future labels used to fit',
        execution='Historical reference model only. No BTC15m L2 supplied; executable PnL=null.',
        target='Stability, coverage and downside; $10-15/day is NOT a fitted target or guaranteed income',
        selection='Primary fixed before scoring this period. Show all controls/sizing, never select max test PnL.',
        research_history='Threshold family informed by earlier September sample: this August split is retrospective temporal validation, not globally untouched/prospective OOS.',
        source_revision=source['revision'],source_days=[dict(day=x['date'],sha256=x['sha256']) for x in source['days']],
        code_sha256=sha(Path(__file__)))
    path=ROOT/'stability_protocol.json'
    if path.exists() and json.loads(path.read_text())!=protocol:
        raise ValueError('Inputs/code/protocol changed: preserve old run and use another output directory')
    dump(path,protocol)
    return protocol


def build_features(index):
    features=[]; reasons=Counter(); fit_moves=[]
    for start in range(START,END,900):
        for delay in DELAYS:
            feature,reason=index.decision(start,delay)
            reasons[reason]+=1
            if feature:
                features.append(feature)
                if start<FIT and delay==840:
                    final=index.at(FIT*1000,exact_ms=(start+900)*1000)
                    if final:
                        fit_moves.append(abs(final['value']/feature['current']['value']-1)*10000)
    if len(fit_moves)<100:
        raise ValueError('Insufficient causal calibration data')
    tail=max(10.,float(np.quantile(fit_moves,.99))+2.)
    fit=dict(fit_at_ms=FIT*1000,n=len(fit_moves),q99_absolute_move_bps=float(np.quantile(fit_moves,.99)),
        tail_buffer_bps=tail,minimum_buffer_bps=10,extra_buffer_bps=2,
        caution='Empirical quantile with finite sample, not 99.9% calibrated probability or loss guarantee')
    dump(ROOT/'features.json',features); dump(ROOT/'tail_calibration.json',fit)
    return features,fit


async def download_markets(api,features):
    needed={}
    for f in features:
        if f['lead_bps']>=5:
            needed.setdefault(f['start'],set()).add(f['side'])
    async def one(start):
        base=Path(f'raw/markets/{start}')
        event=await api.get(base/'event.json',f'https://gamma-api.polymarket.com/events/slug/btc-updown-15m-{start}')
        r=dict(start=start,event=event)
        try:
            if event.get('status')!=200:
                raise ValueError('Gamma unavailable')
            market=parse_market(event['body'],start)
            if 'btc-usd-twap-60s' not in (market['resolution_source']+' '+str(market['raw'].get('description',''))).lower():
                raise ValueError('Not verified BTC TWAP60s rule')
            if market['raw'].get('version','v1')!='v1':
                raise ValueError('Unsupported asset identifiers')
            r['parsed']={k:v for k,v in market.items() if k!='raw'}
            clob=await api.get(base/'clob.json',f'https://clob.polymarket.com/markets/{market["condition_id"]}')
            r['clob']=clob; r['settlement']=settlement(market,clob.get('body',{}))
            if start in needed:
                calls=[api.get(base/'fee_info.json',f'https://clob.polymarket.com/clob-markets/{market["condition_id"]}')]
                sides=sorted(needed[start])
                calls += [api.get(base/(s+'_history.json'),'https://clob.polymarket.com/prices-history',
                    market=market['tokens'][s],startTs=start,endTs=start+900,fidelity=1) for s in sides]
                values=await asyncio.gather(*calls)
                r['fee_info']=values[0]; r['fee']=fee_schedule(market,values[0].get('body',{}))
                r.update(dict(zip([s+'_history' for s in sides],values[1:])))
        except (ValueError,KeyError,TypeError) as exc:
            r['error']=str(exc)
        dump(api.out/base/'combined.json',r)
        return r
    records=[]; starts=list(range(START,END,900))
    for pos in range(0,len(starts),16):
        records.extend(await asyncio.gather(*(one(s) for s in starts[pos:pos+16])))
        if pos%64==0:
            print(f'BTC15m official archives: {len(records)}/{len(starts)}',flush=True)
    return records


def reference_trade(feature,record,buffer,age=75):
    if feature['lead_bps']<buffer:
        return None,'buffer'
    if record.get('settlement',{}).get('status')!='confirmed':
        return None,'settlement_unconfirmed'
    if record.get('fee',{}).get('status')!='known':
        return None,'fee_unknown'
    h=record.get(feature['side']+'_history',{})
    if h.get('status')!=200:
        return None,'history_unavailable'
    q=history_asof(h.get('body',{}).get('history',[]),feature['start']+feature['delay'],age)
    if q is None:
        return None,'reference_missing_or_stale'
    if q['price']<.85:
        return None,'reference_below_085'
    price=Decimal(str(q['price']))+Decimal('.01')
    if price>=1:
        return None,'base_price_ge_one_nonfill'
    won=feature['side']==record['settlement']['winner']
    cost=cash_cost(float(price),record['fee'])
    stress=price+Decimal('.01')
    return dict(start=feature['start'],decision_seconds=feature['start']+feature['delay'],
        day=pd.Timestamp(feature['start'],unit='s',tz='UTC').strftime('%Y-%m-%d'),side=feature['side'],
        won=won,reference=q,assumed_price=float(price),unit_cost=cost,
        stressed_unit_cost=cash_cost(float(stress),record['fee']) if stress<1 else None,
        lead_bps=feature['lead_bps']), 'eligible_reference'


def replay(rows,stake=15,stop=True,delay=0,initial=50,overhead=0,stress=False):
    cash=float(initial); pending=[]; skipped=Counter(); taken=[]; daily_loss=set()
    peak=cash; drawdown=0.
    def release(now):
        nonlocal cash,pending,peak,drawdown
        due=sorted(x for x in pending if x[0]<=now)
        remaining=list(pending)
        for item in due:
            _,payout,cost,overhead_cost,day,won=item
            remaining.remove(item)
            cash+=payout
            if not won:
                daily_loss.add(day)
            # Realize each chronological settlement separately: aggregating
            # several due payments can hide an intervening peak/drawdown.
            equity=cash+sum(x[2] for x in remaining)
            peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
        pending=remaining
        equity=cash+sum(x[2] for x in pending)
        peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    for r in sorted(rows,key=lambda r:r['decision_seconds']):
        release(r['decision_seconds'])
        if stop and r['day'] in daily_loss:
            skipped['daily_loss_stop']+=1; continue
        cost=r['stressed_unit_cost'] if stress else r['unit_cost']
        if cost is None:
            skipped['stressed_price_ge_one_nonfill']+=1; continue
        if cash+1e-8<stake+overhead:
            skipped['insufficient_cash']+=1; continue
        payout=stake/cost if r['won'] else 0.
        cash-=stake+overhead
        pending.append((r['start']+900+delay,payout,stake,overhead,r['day'],r['won']))
        equity=cash+sum(x[2] for x in pending)
        peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
        taken.append(dict(**r,pnl=payout-stake-overhead))
    release(float('inf'))
    return dict(initial_cash=initial,final_cash=cash,pnl=cash-initial,taken=len(taken),
        wins=sum(r['won'] for r in taken),losses=sum(not r['won'] for r in taken),
        max_realized_drawdown=drawdown,skipped=dict(skipped),stake=stake,
        stop_after_losing_trade_per_day=stop,redemption_delay_seconds=delay,overhead_per_fill=overhead,
        stress_plus_1c=stress,daily_pnl={d:sum(r['pnl'] for r in taken if r['day']==d)
            for d in pd.date_range('2026-08-15',periods=7,freq='D').strftime('%Y-%m-%d')},
        limitation='Cash-equivalent fees; redemption delay assumed. Loss stop acts only once outcome becomes available; open positions held at cost.')


def summarize(rows,days):
    n=len(rows); wins=sum(r['won'] for r in rows)
    daily={day:sum(20*(int(r['won'])/r['unit_cost']-1) for r in rows if r['day']==day) for day in days}
    values=np.array(list(daily.values()))
    rng=np.random.default_rng(1108)
    interval=np.quantile(values[rng.integers(0,len(values),size=(5000,len(values)))].sum(axis=1),[.025,.975]).tolist()
    return dict(n=n,wins=wins,losses=n-wins,win_rate=wins/n if n else None,
        unlimited_funding_pnl_20=sum(daily.values()) if n else None,daily_pnl_20=daily,
        mean_daily_pnl_20=float(values.mean()) if n else None,worst_day_20=float(values.min()) if n else None,
        positive_days=int((values>0).sum()),negative_days=int((values<0).sum()),
        bootstrap_day_total95_diagnostic=interval if n else None,
        note='Daily zeros can include unavailable inputs: read coverage counters. Seven days are too few for precise tail-risk inference.')


def analyze(index,features,fit,records,quality):
    by_start={r['start']:r for r in records}; results=[]; trades=[]
    policies=[('control_1400_5bp',840,5),('strict_1400_10bp',840,10),
        ('strict_1430_10bp',870,10),('tail_1400',840,fit['tail_buffer_bps'])]
    for name,delay,buffer in policies:
        for age in (75,15):
            matched=[f for f in features if f['delay']==delay]
            counts={}; scored={}
            for period,lo,hi in [('calibration',START,FIT),('evaluation',FIT,END)]:
                status=Counter(); rows=[]; oracle_wins=oracle_n=0
                for f in matched:
                    if not lo<=f['start']<hi:
                        continue
                    r=by_start[f['start']]
                    if f['lead_bps']>=buffer and r.get('settlement',{}).get('status')=='confirmed':
                        oracle_n+=1; oracle_wins+=f['side']==r['settlement']['winner']
                    row,reason=reference_trade(f,r,buffer,age)
                    status[reason]+=1
                    if row:
                        rows.append(row)
                days=pd.date_range(pd.Timestamp(lo,unit='s',tz='UTC'),periods=7,freq='D').strftime('%Y-%m-%d')
                scored[period]=summarize(rows,days)
                counts[period]=dict(requested_markets=(hi-lo)//900,valid_oracle_features=sum(lo<=f['start']<hi for f in matched),
                    statuses=dict(status),direction_n=oracle_n,direction_wins=int(oracle_wins),
                    direction_win_rate=oracle_wins/oracle_n if oracle_n else None)
                if period=='evaluation':
                    for row in rows:
                        trades.append(dict(policy=name,max_age=age,**row))
                    wallets=[replay(rows,stake,stop,redemption) for stake in (10,15,20)
                        for stop in (False,True) for redemption in (0,300,1800)]
                    sensitivity=[replay(rows,15,True,300,overhead=x,stress=s) for x in (0,.01,.05) for s in (False,True)]
            results.append(dict(policy=name,delay=delay,buffer_bps=buffer,max_reference_age=age,
                counts=counts,results=scored,wallets_evaluation=wallets,primary_wallet_sensitivity=sensitivity))
    checks=[]
    for r in records:
        metadata=r.get('event',{}).get('body',{}).get('eventMetadata',{})
        for field,t in [('priceToBeat',r['start']),('finalPrice',r['start']+900)]:
            p=index.at((END+10)*1000,exact_ms=t*1000)
            if p and metadata.get(field) is not None:
                checks.append(dict(start=r['start'],field=field,error=abs(p['value']-float(metadata[field]))))
    report=dict(schema=1,protocol_sha256=sha(ROOT/'stability_protocol.json'),
        primary_policy='strict_1400_10bp',requested_calendar_days=14,
        evaluation_days=7,official_markets=len(records),
        settlement_status=dict(Counter(r.get('settlement',{}).get('status','fetch_or_parse_failed') for r in records)),
        price_audit=dict(checked=len(checks),matching_within_1cent=sum(r['error']<=.01 for r in checks),
            max_error=max((r['error'] for r in checks),default=None)),
        quality=quality,tail_calibration=fit,policies=results,executable_pnl=None,
        limitations=['No BTC15m historical L2: all financial outputs use hypothetical reference fills.',
            'Current per-market fee metadata, not historical fee attestation. Gas/hosting/funding not measured.',
            'Seven evaluation days do not establish stable income, 99.9% accuracy or $10-15/day.',
            'Primary and grids frozen before this period scored; source not an independent third-party audit.',
            'Prior September-sample research informed the rule family; August time split is retrospective, not globally untouched/prospective OOS.',
            'Daily loss stop and redemption timing modeled, not exchange-confirmed portfolio operations.',
            'Do not substitute companion BTC5m L2 or average 1Hz spot into BTC15m TWAP/execution.'])
    dump(ROOT/'stability_summary.json',report); dump(ROOT/'evaluation_trades.json',trades)
    pd.json_normalize(trades).to_csv(ROOT/'evaluation_trades.csv',index=False)
    print(json.dumps(dict(price_audit=report['price_audit'],settlement_status=report['settlement_status'],
        tail=fit,policies=[dict(policy=r['policy'],age=r['max_reference_age'],
            evaluation=r['results']['evaluation'],counts=r['counts']['evaluation']) for r in results]),indent=2),flush=True)


async def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--offline',action='store_true')
    p.add_argument('--features-only',action='store_true'); args=p.parse_args()
    freeze(); index,quality=load_reports(); features,fit=build_features(index)
    print(f'{len(features)} causal features; tail buffer fitted from {fit["n"]} training outcomes',flush=True)
    if args.features_only:
        return
    api=Archive(ROOT,args.offline,concurrency=8)
    try:
        records=await download_markets(api,features)
    finally:
        await api.client.aclose()
    analyze(index,features,fit,records,quality)


if __name__=='__main__':
    asyncio.run(main())
