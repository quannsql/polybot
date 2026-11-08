"""Offline exploratory late-entry/abstention study. No promise of zero losses.

Uses the previously downloaded 289 DCA windows; DOES NOT evaluate Variant B
without ETH or use settled finalPrice as an entry feature. No network or orders.
"""
from collections import Counter
from decimal import Decimal
import math
from pathlib import Path
import json

import numpy as np
import pandas as pd

from polymarket_bot.actual_research import history_asof, cash_cost
from research_fresh_data import dump, sha

SOURCE=Path('data/research_20261108')
OUT=Path('data/high_confidence_20261108')
DELAYS=(750,780,810,840,870,885,895)
THRESHOLDS=(.85,.90,.95,.97,.99)
PADS=(.01,.001)
AGES=(75,15)
FILTERS=('none','z2','z3','quiet_z3')
SPLIT=int(pd.Timestamp('2026-10-15',tz='UTC').timestamp())


def inputs(minutes,start,delay,side):
    """Only completed minutes; remaining uncertainty starts at the last close."""
    known=pd.Timestamp(start+delay,unit='s',tz='UTC').floor('min')
    start_at=pd.Timestamp(start,unit='s',tz='UTC')
    f=minutes.reindex(pd.date_range(known-pd.Timedelta(minutes=61),known-pd.Timedelta(minutes=1),freq='min'))
    changes=np.log(f.close/f.close.shift())
    sigma=changes.tail(30).std(ddof=0) if changes.tail(30).notna().all() else np.nan
    vol=changes.tail(5).std(ddof=0)/changes.tail(60).std(ddof=0) if changes.tail(60).notna().all() else np.nan
    opening=f.open.get(start_at,np.nan)
    complete=f.loc[start_at:,'close'].notna().all()
    lead=(1 if side=='up' else -1)*np.log(f.close.iloc[-1]/opening) if complete else np.nan
    remaining=(start+900-known.timestamp())/60
    z=lead/(sigma*math.sqrt(remaining)) if sigma>0 and remaining>0 else np.nan
    number=lambda x:float(x) if np.isfinite(x) else None
    return dict(feature_at=int(known.timestamp()),last_closed_price=number(f.close.iloc[-1]),
        lead_z=number(z),vol_ratio=number(vol),uncertainty_minutes_from_last_known_close=remaining)


def keep(features,policy):
    if policy=='none':
        return True
    z=features['lead_z']; vol=features['vol_ratio']
    if z is None:
        return False
    if policy=='z2':
        return z>=2
    if policy=='z3':
        return z>=3
    if policy=='quiet_z3':
        return z>=3 and vol is not None and vol<=1.5
    raise ValueError('Unknown filter')


def trade(row,record,features,delay,threshold,padding,max_age,policy):
    if record.get('settlement',{}).get('status')!='confirmed':
        return None,'settlement_unconfirmed'
    if record.get('fee',{}).get('status')!='known':
        return None,'fee_unknown'
    if not keep(features,policy):
        return None,'feature_filter'
    history=record.get(row['side']+'_history',{})
    if history.get('status')!=200:
        return None,'history_unavailable'
    q=history_asof(history.get('body',{}).get('history',[]),row['start']+delay,max_age)
    if q is None:
        return None,'missing_or_stale_reference'
    if q['price']<threshold:
        return None,'reference_below_threshold'
    price=Decimal(str(q['price']))+Decimal(str(padding))
    won=row['side']==record['settlement']['winner']
    # Record infeasible price separately, do not call it a winning trade.
    fillable=price<1
    shares=20/cash_cost(float(price),record['fee']) if fillable else 0.
    return dict(start=row['start'],slug=row['slug'],side=row['side'],won=won,
        reference=q['price'],reference_age=q['age_seconds'],assumed_price=float(price),
        modeled_fill=fillable,shares=shares,pnl=shares*won-20 if fillable else 0.,
        **features),'eligible' if fillable else 'price_ge_one_nonfill'


def summarize(rows):
    f=[r for r in rows if r['modeled_fill']]
    n=len(f); wins=sum(r['won'] for r in f)
    pnl=sum(r['pnl'] for r in f)
    winprofits=[r['pnl'] for r in f if r['won']]
    meanwin=float(np.mean(winprofits)) if winprofits else None
    return dict(qualified_references=len(rows),n=n,nonfills=len(rows)-n,wins=wins,losses=n-wins,
        win_rate=wins/n if n else None,pnl=pnl if n else None,
        mean_winning_pnl=meanwin,
        break_even_from_mean_win=20/(20+meanwin) if meanwin is not None else None,
        one_winner_flipped_to_loss_pnl=pnl-max((r['shares'] for r in f if r['won']),default=0) if n else None,
        zero_losses_lower95_iid_diagnostic=.05**(1/n) if n and n==wins else None)


def economics(price,rate=.07,budget=20):
    cost=price+rate*price*(1-price)
    gain=budget/cost-budget
    return dict(price=price,win_pnl=gain,loss_pnl=-budget,break_even_win_probability=cost,
        wins_to_recover_one_loss=math.ceil(budget/gain) if gain>0 else None)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    files=[SOURCE/'candidates.json',SOURCE/'BTCUSDT_1m.csv']
    files+=sorted((SOURCE/'raw/polymarket').glob('*/combined.json'))
    protocol=dict(delays=DELAYS,thresholds=THRESHOLDS,paddings=PADS,max_reference_ages=AGES,filters=FILTERS,
        split_utc='2026-10-15',budget=20,total_policies=len(DELAYS)*len(THRESHOLDS)*len(PADS)*len(AGES)*len(FILTERS),
        source_sha256={str(p):sha(p) for p in files},code_sha256=sha(Path(__file__)),
        cohort='All 289 cached DCA direction windows, not just the 61 baseline trades',
        preregistration='Fixed grid recorded before scoring this study; old outcomes already seen, exploratory reused-data study',
        direction='Original DCA direction frozen at T; no favourite-direction substitution',
        forbidden_inputs='Gamma eventMetadata finalPrice/priceToBeat, outcome prices and settlement never entry features',
        features='Lighter proxy from completed 1m only; no ETH/Variant B; no probability inferred from Z',
        execution='Reference+padding hypothetical; 0.001 padding is a separate execution change, not current +0.01 cap evidence',
        time_split='Descriptive discovery/confirmation on already inspected October data, NOT an untouched holdout',
        selector='On discovery only: n>=20, no losses, positive pnl. Largest n, then smaller padding, then id. Otherwise no selection.')
    path=OUT/'protocol.json'
    encoded=json.loads(json.dumps(protocol))
    if path.exists() and json.loads(path.read_text())!=encoded:
        raise ValueError('Changed inputs/code/protocol: preserve run and choose another output directory')
    dump(path,protocol)
    minutes=pd.read_csv(SOURCE/'BTCUSDT_1m.csv')
    minutes.timestamp=pd.to_datetime(minutes.timestamp,utc=True)
    minutes=minutes.set_index('timestamp').sort_index()
    rows=json.loads((SOURCE/'candidates.json').read_text())
    records={r['start']:json.loads((SOURCE/f'raw/polymarket/{r["start"]}/combined.json').read_text()) for r in rows}
    feature_cache={(r['start'],d):inputs(minutes,r['start'],d,r['side']) for r in rows for d in DELAYS}
    results=[]; alltrades=[]
    for delay in DELAYS:
        for threshold in THRESHOLDS:
            for padding in PADS:
                for max_age in AGES:
                    for policy in FILTERS:
                        ident=f'd{delay}_ref{threshold}_pad{padding}_age{max_age}_{policy}'
                        trades=[]; reasons=Counter()
                        for row in rows:
                            t,reason=trade(row,records[row['start']],feature_cache[row['start'],delay],
                                delay,threshold,padding,max_age,policy)
                            reasons[reason]+=1
                            if t is not None:
                                trades.append(t)
                        parts=dict(all=summarize(trades),discovery=summarize([t for t in trades if t['start']<SPLIT]),
                            confirmation=summarize([t for t in trades if t['start']>=SPLIT]))
                        result=dict(id=ident,delay=delay,threshold=threshold,padding=padding,max_age=max_age,
                            filter=policy,statuses=dict(reasons),**parts)
                        results.append(result)
                        alltrades.extend(dict(policy_id=ident,**t) for t in trades)
    eligible=[r for r in results if r['discovery']['n']>=20 and r['discovery']['losses']==0 and r['discovery']['pnl']>0]
    selected=sorted(eligible,key=lambda r:(-r['discovery']['n'],r['padding'],r['id']))[:1]
    perfect=[r for r in results if r['all']['n'] and r['all']['losses']==0]
    perfect=sorted(perfect,key=lambda r:(-r['all']['n'],r['padding'],r['id']))
    summary=dict(protocol_sha256=sha(path),candidates=len(rows),policies=len(results),
        perfect_in_sample_count=len(perfect),perfect_in_sample_largest=perfect[:10],
        selected_on_discovery=selected,
        economics=[economics(p) for p in (.96,.98,.99,.995,.999)],
        zero_loss_sample_size_iid95={str(p):math.ceil(math.log(.05)/math.log(p)) for p in (.99,.999,.9999)},
        zero_loss_281_lower95_iid=.05**(1/281),
        limitations=['No zero-loss guarantee from finite history; 560 correlated policies reuse inspected data.',
            'Late entries at 14:45/14:55 cannot be validated with minute history and last closed minute alone.',
            'No observed executable asks/depth or oracle TWAP before entry; all PnL modeled.',
            'Max age15 is a data quality subset, not a demonstrated market alpha.',
            'Price>=1 nonfills stay counted separately. Zero trades is never labeled 100% win.',
            'Posthoc best zero-loss row is discovery only; selector output is separate.'])
    dump(OUT/'summary.json',summary); dump(OUT/'results.json',results)
    pd.json_normalize(results).to_csv(OUT/'results.csv',index=False)
    pd.DataFrame(alltrades).to_csv(OUT/'trades.csv',index=False)
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    main()
