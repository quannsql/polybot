"""Offline fixed-protocol historical approximation; no executable-book claim."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import pandas as pd

from polymarket_bot.actual_research import history_asof, cash_cost
from polymarket_bot.robustness import bankroll_replay
from report_robust_paper import block_interval


ROOT=Path(__file__).resolve().parent


def main():
    protocol=json.loads((ROOT/'robustness_protocol.json').read_text())
    source=ROOT/'timeframe_research_20260913/predictions.csv'
    frame=pd.read_csv(source)
    frame=frame[frame.variant.eq('dca_5m_plus_15m__15m')].copy()
    original=len(frame)
    frame['decision_at']=pd.to_datetime(frame.decision_at,utc=True)
    # The archive mapped the latest signal to a boundary. Age zero retains only
    # actual boundary signals, removing the carried-forward 5/10 minute signals.
    frame=frame[frame.signal_age_minutes.eq(0)]
    boundary=len(frame)
    frame=frame[frame.decision_at.dt.hour.ge(protocol['session_start_utc']) &
                frame.decision_at.dt.hour.lt(protocol['session_end_utc'])]
    if frame.duplicated('decision_at').any():
        raise ValueError('Duplicate contract in fixed signal cohort')
    counts=Counter(original_24h_latest_signals=original,boundary_signals=boundary,
                   boundary_session_signals=len(frame))
    trades=[]; skipped=[]; hashes={}
    for row in frame.itertuples():
        start=int(row.decision_at.timestamp())
        path=ROOT/'actual_market_research_20260913/raw'/f'{start}.json'
        if not path.exists():
            counts['missing_cached_market']+=1
            continue
        data=path.read_bytes(); hashes[path.name]=hashlib.sha256(data).hexdigest()
        raw=json.loads(data)
        if raw.get('settlement',{}).get('status')!='confirmed':
            counts['unconfirmed_label']+=1;continue
        counts['confirmed_label']+=1
        if raw.get('fee',{}).get('status')!='known':
            counts['unknown_fee']+=1;continue
        q=history_asof(raw.get(row.side+'_history',{}).get('body',{}).get('history',[]),
                      start+protocol['entry_seconds'],max_age=75)
        if q is None:
            counts['missing_reference_within_75s']+=1;continue
        counts['reference_available']+=1
        counts['reference_age_le_1500ms']+=q['age_seconds']<=1.5
        counts['reference_age_le_15s']+=q['age_seconds']<=15
        # Reference is not a real ask; each padding is a separately labelled
        # assumed ask, used consistently for threshold and cap filtering.
        for pad in (.01,.02,.03):
            ask=q['price']+pad
            if not protocol['minimum_ask']<=ask<=protocol['maximum_price']:
                skipped.append({'slug':f'btc-updown-15m-{start}','pad':pad,'period':row.period,'reason':'assumed_ask_outside_filter'})
                continue
            cost_per_share=cash_cost(ask,raw['fee'])
            budget=protocol['budget_usd']
            shares=budget/cost_per_share
            won=row.side==raw['settlement']['winner']
            trades.append({'slug':f'btc-updown-15m-{start}', 'period':row.period,
                'opened_ms':(start+protocol['entry_seconds'])*1000,'end_ms':(start+900)*1000,
                'side':row.side,'source':row.source,'pad':pad,'assumed_ask':ask,
                'reference':q['price'],'reference_age_seconds':q['age_seconds'],
                'cost':budget,'shares':shares,'pnl':shares*won-budget,
                'winner':raw['settlement']['winner'],'won':won})
    results=[]
    for period in ('validation','confirmation','all'):
        cohort=frame if period=='all' else frame[frame.period.eq(period)]
        if cohort.empty:continue
        first=int(cohort.decision_at.min().timestamp())//86400
        last=int(cohort.decision_at.max().timestamp())//86400
        for pad in (.01,.02,.03):
            selected=[r for r in trades if r['pad']==pad and (period=='all' or r['period']==period)]
            n=len(selected)
            # Same-markets comparison removes differing cap eligibility.
            keys=[{r['slug'] for r in trades if r['pad']==p and (period=='all' or r['period']==period)} for p in (.01,.02,.03)]
            common=set.intersection(*keys)
            paired=[r for r in selected if r['slug'] in common]
            labels={r['slug']:{'received_ms':r['end_ms'],'winner':r['winner']} for r in selected}
            results.append({'period':period,'padding_cents':round(pad*100),
                'n':n,'wins':sum(r['won'] for r in selected),'win_rate':sum(r['won'] for r in selected)/n if n else None,
                'total_pnl_30usd_unlimited_capital':sum(r['pnl'] for r in selected),
                'mean_pnl':sum(r['pnl'] for r in selected)/n if n else None,
                'diagnostic_mean_pnl_block95':block_interval(selected,first,last),
                'fresh15s':sum(r['reference_age_seconds']<=15 for r in selected),
                'fresh1500ms':sum(r['reference_age_seconds']<=1.5 for r in selected),
                'common_markets_n':len(paired),'common_markets_pnl':sum(r['pnl'] for r in paired),
                'bankroll_50_optimistic_instant_resolution':bankroll_replay(selected,labels),
                'by_source':{s:{'n':len(v:=[r for r in selected if r['source']==s]),'pnl':sum(r['pnl'] for r in v)} for s in sorted({r['source'] for r in selected})}})
    output=ROOT/'logs/fixed_protocol_history'
    output.mkdir(parents=True,exist_ok=True)
    summary={'status':'historical_reference_approximation_not_executable_backtest',
        'protocol':protocol,'counts':dict(counts),'results':results,
        'limitations':['Source is cached Lighter predictions, not Binance: no exact live-source parity.',
            'Age-zero boundary/session filter applied to existing predictions; no newly optimized parameters.',
            'Assumed ask=historical reference+padding. No historical spread, depth, latency or FOK evidence.',
            'Cached fee schedules are not an as-of historical fee attestation.',
            '$30 PnL assumes unlimited liquidity; separate $50 replay credits proceeds at expiry optimistically.',
            'Previously examined history, not untouched out-of-sample validation. No live approval.'],
        'prediction_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'raw_hashes':hashes}
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (output/'trades.json').write_text(json.dumps(trades,indent=2),encoding='utf-8')
    print(json.dumps({'counts':dict(counts),'results':results},indent=2))


if __name__=='__main__':main()
