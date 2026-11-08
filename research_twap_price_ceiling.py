"""Posthoc price-ceiling sensitivity, accepting smaller winning profit.

Partial captured-quote sample only; not independent validation or actual fills.
"""
from decimal import Decimal
import json
from pathlib import Path

from research_fresh_data import dump,sha
from research_twap_stability import FIT,END,replay
from research_twap_depth import load_quotes,top_fill

ROOT=Path('data/twap_stability_20261108')
OUT=ROOT/'high_price_study'


def acquire(f,r,quotes,buffer,max_ask,min_profit,latency=500):
    if f['lead_bps']<buffer:
        return None,'buffer'
    if r.get('settlement',{}).get('status')!='confirmed' or r.get('fee',{}).get('status')!='known':
        return None,'unknown_label_or_fee'
    now=(f['start']+f['delay'])*1000
    initial,reason=quotes.at(f['start'],f['side'],now,1500)
    if not initial:
        return None,reason
    if not .85<=initial['ask']<=max_ask:
        return None,'price_outside_range'
    cap=min(max_ask,float(Decimal(str(initial['ask']))+Decimal('.001')))
    after,reason=quotes.at(f['start'],f['side'],now+latency,1500)
    if not after:
        return None,'arrival_'+reason
    if after['available_ms']<now:
        return None,'arrival_refresh_unobserved'
    if after['ask']>cap:
        return None,'arrival_price_exceeds_cap'
    try:
        fill=top_fill(after,r['fee'],15,.5)
    except ValueError as exc:
        return None,str(exc)
    if fill['winning_pnl_reserved']<min_profit:
        return None,'insufficient_winning_margin'
    return dict(start=f['start'],decision_seconds=f['start']+f['delay'],
        day=__import__('datetime').datetime.fromtimestamp(f['start'],__import__('datetime').timezone.utc).strftime('%Y-%m-%d'),
        won=f['side']==r['settlement']['winner'],unit_cost=15/fill['shares'],stressed_unit_cost=None,
        initial_quote=initial,arrival_quote=after,**fill), 'captured_quote_scenario'


def main():
    from collections import Counter
    OUT.mkdir(parents=True,exist_ok=True)
    protocol=dict(code_sha256=sha(Path(__file__)),note='Posthoc sensitivity after primary study; no choosing best test result',
        ceilings=[.99,.995,.999],min_winning_margins=[.05,.01],latencies_ms=[500,1000],budget=15,
        quote_max_age_ms=1500,depth_fraction=.5,overhead_per_fill=.01,
        validity='Incomplete quote days and unknown source-clock alignment; all acquisition remains conditional')
    p=OUT/'protocol.json'
    if p.exists() and json.loads(p.read_text())!=protocol:
        raise ValueError('Preserve protocol before modifying run')
    dump(p,protocol)
    features=[f for f in json.loads((ROOT/'features.json').read_text()) if FIT<=f['start']<END]
    records={int(p.parent.name):json.loads(p.read_text()) for p in (ROOT/'raw/markets').glob('*/combined.json')}
    quotes,coverage=load_quotes(records)
    tail=json.loads((ROOT/'tail_calibration.json').read_text())['tail_buffer_bps']
    policies=[('control_1400_5bp',840,5),('strict_1400_10bp',840,10),('strict_1430_10bp',870,10),('tail_1400',840,tail)]
    results=[]
    for name,delay,buffer in policies:
        for cap in (.99,.995,.999):
            for minimum in (.05,.01):
                for latency in (500,1000):
                    rows=[]; reasons=Counter()
                    for f in features:
                        if f['delay']!=delay:
                            continue
                        row,reason=acquire(f,records[f['start']],quotes,buffer,cap,minimum,latency)
                        reasons[reason]+=1
                        if row:
                            rows.append(row)
                    results.append(dict(policy=name,max_ask=cap,min_winning_profit=minimum,latency_ms=latency,
                        n=len(rows),wins=sum(r['won'] for r in rows),losses=sum(not r['won'] for r in rows),
                        reasons=dict(reasons),covered_subset_wallet=replay(rows,15,True,300,overhead=.01)))
    theoretical=[]
    for price in (.98,.99,.995,.999):
        fee=.07*price*(1-price)
        win=15/(price+fee)-15
        theoretical.append(dict(price=price,stake=15,win_pnl=win,
            maximum_daily_wins=96,upper_income_all_96_win=win*96,
            upper_income_after_001_overhead=96*(win-.01),
            note='Arithmetic upper bound at the same purchase price, not forecast or available liquidity.'))
    dump(OUT/'summary.json',dict(coverage=coverage,scenarios=results,theoretical_income_ceiling=theoretical,
        weekly_execution_pnl=None,warning='Never extrapolate covered subset PnL to all seven days.'))
    print(json.dumps(dict(scenarios=[dict(policy=r['policy'],cap=r['max_ask'],min_profit=r['min_winning_profit'],
        latency=r['latency_ms'],n=r['n'],wins=r['wins'],covered_pnl=r['covered_subset_wallet']['pnl']) for r in results],
        theoretical=theoretical),indent=2))


if __name__=='__main__':
    main()
