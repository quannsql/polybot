"""Offline entry reconfirmation on the exact old DCA cohort, with no future bars."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_poly_research import bars5, read_minutes
from backtest_legacy_execution import cohort, scenario
from polymarket_bot.signal_grid import features, raw_signals, select_windows
from polymarket_bot.robustness import bankroll_replay
from report_robust_paper import block_interval

ROOT=Path(__file__).resolve().parent


def observations(minutes):
    grid=features(bars5(minutes))
    raw=raw_signals(grid,session_start=0,session_end=0)
    b15=minutes.resample('15min').agg(close=('close','last'),count=('close','count'))
    b15.loc[b15['count'].ne(15),'close']=np.nan
    return grid.set_index('decision_at',drop=False), raw, b15


def recheck(grid, raw, b15, minutes, start, side, source):
    latest=start+pd.Timedelta(minutes=10)
    r=grid.loc[latest]
    fresh=raw.loc[raw.signal_at.gt(start)&raw.signal_at.le(latest)].sort_values('signal_at')
    valid=bool(grid.loc[start+pd.Timedelta(minutes=5),'valid5']) and bool(r.valid5)
    opposite=bool(fresh.side.ne(side).any())
    last_side=fresh.iloc[-1].side if len(fresh) else None
    if source=='aux_short_15m':
        closed=bool(r.valid15==True and r.close15>=r.upper15 and r.run60>=60)
    else:
        closed=bool(r.valid5 and ((side=='up' and r.route=='long' and r.close<=r.lower5)
                                  or (side=='down' and r.route=='short' and r.close>=r.upper5)))
    # No row at or after T+11 is used: that 1m candle is still incomplete at 11:30.
    known=minutes.loc[start:start+pd.Timedelta(minutes=10),'close']
    prev=b15.close.reindex(pd.date_range(start-pd.Timedelta(minutes=285),periods=19,freq='15min'))
    older=b15.close.get(start-pd.Timedelta(minutes=60),np.nan)
    partial_valid=len(known)==11 and known.notna().all() and prev.notna().all() and pd.notna(older) and older>0
    part_close=part_upper=part_run=None
    partial=False
    if partial_valid:
        part_close=float(known.iloc[-1])
        closes=np.r_[prev.to_numpy(),part_close]
        part_upper=float(closes.mean()+2*closes.std(ddof=0))
        part_run=float((part_close/older-1)*1e4)
        partial=part_close>=part_upper and part_run>=60
    return {'original':True,
        'veto_new_opposite':valid and not opposite,
        'require_new_same':valid and last_side==side,
        'same_branch_closed':valid and closed,
        'same_branch_partial15_proxy':valid and (partial if source=='aux_short_15m' else closed),
        'audit':{'source':source,'fresh_sides':fresh.side.tolist(),'fresh_times':[str(t) for t in fresh.signal_at],
            'closed_5m_available_at':str(latest),'closed_15m_available_at':str(start),
            'partial_close_available_at':str(start+pd.Timedelta(minutes=11)),
            'valid_closed_inputs':valid,'partial_valid':bool(partial_valid),'close5':float(r.close) if pd.notna(r.close) else None,
            'partial15_close':part_close,'partial15_upper':part_upper,'partial15_run_four_bars_bps':part_run}}


def metric(original, selected, budget):
    taken=[r for r in selected if r['cost']>0]
    keys={r['slug'] for r in selected}
    removed=[r for r in original if r['slug'] not in keys]
    n=len(taken); wins=sum(r['won'] for r in taken)
    labels={r['slug']:{'winner':r['winner'],'received_ms':r['end_ms']} for r in taken}
    base_pnl=sum(r['pnl'] for r in original)
    pnl=sum(r['pnl'] for r in taken)
    paired=[{**r,'pnl':(r['pnl'] if r['slug'] in keys else 0)-r['pnl']} for r in original]
    first=min(r['opened_ms'] for r in original)//86400000
    last=max(r['opened_ms'] for r in original)//86400000
    return {'original_candidates':len(original),'retained_candidates':len(selected),
        'assumed_fills':n,'wins':wins,'losses':n-wins,'win_rate':wins/n if n else None,
        'removed_winners':sum(r['won'] for r in removed),'removed_losers':sum(not r['won'] for r in removed),
        'retained_cost_nonfills':len(selected)-n,'pnl':pnl,'delta_pnl_vs_original':pnl-base_pnl,
        'mean_pnl_per_fill':pnl/n if n else None,
        'paired_delta_per_original_candidate_block95_diagnostic':block_interval(paired,first,last),
        'bankroll50_instant_settlement_assumption':bankroll_replay(taken,labels,50,budget)}


def main():
    protocol=json.loads((ROOT/'recheck_1130_protocol.json').read_text())
    oldmeta=json.loads((ROOT/'timeframe_research_20260913/summary.json').read_text())['metadata']
    inputs=[Path(s['path']) for s in oldmeta['sources']]
    minutes,metadata=read_minutes(inputs)
    assert [s['sha256'] for s in metadata['sources']]==[s['sha256'] for s in oldmeta['sources']], 'Historical source changed'
    grid,raw,b15=observations(minutes)
    mapped=select_windows(raw,policy='latest_5m').set_index('decision_at')
    candidates,_,_,archive_manifest=cohort()
    masks={}; audits=[]
    for row in candidates:
        start=pd.Timestamp(row['end_ms']-900000,unit='ms',tz='UTC')
        original=mapped.loc[start]
        assert original.side==row['side'], 'Rebuilt original signal differs from archive'
        check=recheck(grid,raw,b15,minutes,start,row['side'],original.source)
        masks[row['slug']]=check
        audits.append({**row,'checks':check})
    results=[]
    for budget in protocol['budgets']:
        for pad in protocol['cost_padding_cents']:
            original=scenario(candidates,pad/100,budget)
            for period in ('validation','confirmation','all'):
                base=[r for r in original if period=='all' or r['period']==period]
                for variant in protocol['variants']:
                    selected=[r for r in base if masks[r['slug']][variant]]
                    results.append({'period':period,'budget':budget,'pad_cents':pad,'variant':variant,
                                    **metric(base,selected,budget)})
    # Recheck baseline acceptance independently of the proposed masks.
    for period,n,wins in [('validation',288,273),('confirmation',125,124)]:
        r=next(r for r in results if r['period']==period and r['variant']=='original' and r['budget']==5 and r['pad_cents']==1)
        assert (r['assumed_fills'],r['wins'])==(n,wins)
    report={'protocol':protocol,'results':results,'metadata':metadata,
        'original_signal_parity_markets':len(audits),'archive_manifest':archive_manifest,
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'limitations':['Price/fee assumptions are unchanged, not real fills. New filter does not fix missing historical order books.',
            'Reconfirmation filters original candidates; no reversed positions or newly discovered trades.',
            'Historical candle publication/transport latency is unknown.',
            'Partial 15m is a separate hypothesis using T+11 information, not T+11:30 tick data or the eventual candle close.',
            'Both periods have been examined before. Improvements are exploratory, not new out-of-sample evidence.',
            'No paper or live deployment, configuration changes, or Bot1 writes.']}
    out=ROOT/'logs/recheck_1130';out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    (out/'candidate_audit.json').write_text(json.dumps(audits,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('period','variant','assumed_fills','wins','losses','win_rate','pnl','removed_winners','removed_losers')}
                     for r in results if r['budget']==30 and r['pad_cents']==1],indent=2))


if __name__=='__main__':
    main()
