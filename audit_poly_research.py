"""Reproducible DCA -> next fixed 15m research, read-only inputs.

Outputs are price-direction proxies and synthetic payout scenarios. No orders.
Explicit variants are specified before scoring; no best-parameter selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from polymarket_bot.signal_grid import features, raw_signals, select_windows, session_mask


def read_minutes(paths: list[Path]) -> tuple[pd.DataFrame, dict]:
    frames, sources = [], []
    for path in paths:
        f = pd.read_csv(path)
        f['timestamp'] = pd.to_datetime(f.timestamp, utc=True)
        if not f.timestamp.equals(f.timestamp.dt.floor('min')):
            raise ValueError(f'Off-grid minute timestamps: {path}')
        if f.timestamp.duplicated().any():
            raise ValueError(f'Duplicate rows inside {path}')
        cols = ['open', 'high', 'low', 'close', 'volume']
        f[cols] = f[cols].apply(pd.to_numeric, errors='raise')
        if (not np.isfinite(f[cols]).all().all() or f[cols[:4]].le(0).any().any()
                or f.volume.lt(0).any() or f.high.lt(f[['open','close','low']].max(axis=1)).any()
                or f.low.gt(f[['open','close','high']].min(axis=1)).any()):
            raise ValueError(f'Invalid OHLCV rows: {path}')
        sources.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'rows': len(f), 'first': str(f.timestamp.min()), 'last': str(f.timestamp.max())})
        frames.append(f)
    all_rows = pd.concat(frames, ignore_index=True)
    duplicates = all_rows[all_rows.timestamp.duplicated(False)]
    conflicts = int(duplicates.groupby('timestamp')[['open','high','low','close']].nunique().gt(1).any(axis=1).sum())
    # Explicit deterministic priority: first input wins overlapping timestamps.
    merged = all_rows.drop_duplicates('timestamp', keep='first').sort_values('timestamp').set_index('timestamp')
    index = pd.date_range(merged.index.min(), merged.index.max(), freq='1min')
    missing = len(index) - len(merged)
    merged = merged.reindex(index)
    merged.index.name = 'timestamp'
    return merged, {'sources': sources, 'overlap_rows': len(all_rows)-len(merged.dropna()),
                    'ohlc_conflicting_timestamps': conflicts, 'overlap_policy': 'first input wins',
                    'missing_minutes': missing, 'grid_minutes': len(merged)}


def bars5(minutes: pd.DataFrame) -> pd.DataFrame:
    result = minutes.resample('5min').agg(open=('open','first'), high=('high','max'),
        low=('low','min'), close=('close','last'), volume=('volume','sum'), count=('close','count'))
    result.loc[result['count'].ne(5), ['open','high','low','close','volume']] = np.nan
    return result.drop(columns='count').reset_index()


def label(signals: pd.DataFrame, minutes: pd.DataFrame) -> pd.DataFrame:
    f = signals.copy()
    if f.empty:
        return f.assign(correct=pd.Series(dtype=bool), up_won=pd.Series(dtype=bool),
                        start_price=pd.Series(dtype=float), end_price=pd.Series(dtype=float))
    f['start_price'] = minutes.open.reindex(pd.DatetimeIndex(f.decision_at)).to_numpy()
    end_minutes = pd.DatetimeIndex(f.end_at - pd.Timedelta(minutes=1))
    f['end_price'] = minutes.close.reindex(end_minutes).to_numpy()
    # Check all 15 observations; last close alone cannot establish a valid window.
    counts = minutes.close.rolling(15).count().reindex(end_minutes).to_numpy()
    valid = f.start_price.notna() & f.end_price.notna() & (counts == 15)
    f = f.loc[valid].copy()
    f['up_won'] = f.end_price.ge(f.start_price)
    f['correct'] = f.side.eq(np.where(f.up_won, 'up', 'down'))
    f['return_bps'] = (f.end_price / f.start_price - 1) * 10000
    return f.reset_index(drop=True)


def scores(f: pd.DataFrame) -> dict:
    n = len(f)
    if n == 0:
        return {'n': 0, 'win_rate': None}
    wins = int(f.correct.sum())
    p = wins/n
    # Cluster resampling by UTC day accounts for multiple correlated signals.
    daily = f.assign(day=f.decision_at.dt.floor('D')).groupby('day').correct.agg(['sum','count'])
    rng = np.random.default_rng(20260913)
    if len(daily) > 1:
        ix = rng.integers(0, len(daily), size=(1000,len(daily)))
        rates = daily['sum'].to_numpy()[ix].sum(axis=1) / daily['count'].to_numpy()[ix].sum(axis=1)
        ci = np.quantile(rates,[.025,.975]).tolist()
    else:
        ci = [None, None]
    return {'n':n, 'wins':wins, 'win_rate':p, 'daily_cluster_ci95':ci,
            'always_up_accuracy':float(f.up_won.mean()),
            'always_down_accuracy':float((~f.up_won).mean()),
            'by_source': {str(k):{'n':len(g),'win_rate':float(g.correct.mean())}
                          for k,g in f.groupby('source')},
            'by_side': {str(k):{'n':len(g),'win_rate':float(g.correct.mean())}
                        for k,g in f.groupby('side')}}


def walk_forward(f: pd.DataFrame, start: pd.Timestamp, stop: pd.Timestamp) -> pd.DataFrame:
    """Refit monthly with only settled observations before that month."""
    f = f.copy()
    f['p_train'] = np.nan
    f['n_train'] = 0
    f['fit_at'] = pd.NaT
    f['fit_at'] = pd.to_datetime(f.fit_at, utc=True)
    evaluation = f.loc[(f.decision_at >= start) & (f.decision_at < stop)]
    for month in sorted(evaluation.decision_at.dt.strftime('%Y-%m').unique()):
        cut = pd.Timestamp(month+'-01', tz='UTC')
        train = f.loc[f.end_at <= cut]
        table = train.groupby(['source','side']).correct.agg(['sum','count'])
        target = f.decision_at.dt.strftime('%Y-%m').eq(month) & f.index.isin(evaluation.index)
        for (source,side), stats in table.iterrows():
            ix = target & f.source.eq(source) & f.side.eq(side)
            f.loc[ix,'p_train'] = (stats['sum']+1)/(stats['count']+2)
            f.loc[ix,'n_train'] = int(stats['count'])
            f.loc[ix,'fit_at'] = cut
    return f.loc[f.index.isin(evaluation.index)].copy()


def scenario(f: pd.DataFrame, ask: float, *, fee_rate: float=.07,
             min_edge: float=.03, require_edge: bool=True) -> dict:
    """One-share payout with additive fee assumption; $5 all-in budget/trade.

    Ask already includes crossing the spread: do not charge spread twice.
    Immediate payout at end is an idealisation (no resolution cash-lock model).
    """
    cost = ask + fee_rate*ask*(1-ask)
    eligible = (f.n_train.ge(30) & f.p_train.sub(cost).ge(min_edge)) if require_edge else pd.Series(True,index=f.index)
    x = f.loc[eligible].copy()
    budget, bankroll = 5., 1000.
    if budget/cost < 5:  # synthetic minimum order size: five shares
        x = x.iloc[:0]
    pnl = x.correct.astype(float)*(budget/cost) - budget
    # Stop once insufficient cash; no fractional dust trades to prolong a run.
    equity = bankroll + pnl.cumsum()
    insufficient = np.flatnonzero(np.r_[bankroll, equity.to_numpy()[:-1]] < budget) if len(x) else []
    if len(insufficient):
        pnl = pnl.iloc[:insufficient[0]]
        x = x.iloc[:insufficient[0]]
        equity = bankroll + pnl.cumsum()
    curve = pd.Series(np.r_[bankroll,equity.to_numpy()])
    return {'ask':ask, 'fee_rate_parameter':fee_rate, 'cost_per_share':cost,
        'break_even_win_rate':cost, 'trades':len(x),
        'win_rate':float(x.correct.mean()) if len(x) else None,
        'pnl_usd':float(pnl.sum()), 'stake_including_fee_usd':budget,
        'initial_bankroll_usd':bankroll, 'max_drawdown_usd':float((curve.cummax()-curve).max()),
        'roi_on_stakes':float(pnl.sum()/(len(x)*budget)) if len(x) else None}


def trend_control(grid: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """New hypothesis, not a DCA entry rule: both frames above/below mid + slope."""
    f = grid.copy()
    up = f.close.gt(f.mid5) & f.close15.gt(f.mid15) & f.slope15.gt(0)
    down = f.close.lt(f.mid5) & f.close15.lt(f.mid15) & f.slope15.lt(0)
    f['side'] = np.where(up, 'up', 'down')
    f['source'] = 'trend_control'
    f['signal_at'] = f.decision_at
    f = f.loc[(up|down) & f.valid5 & f.valid15.eq(True) & session_mask(f.decision_at,start,end)]
    return select_windows(f,policy='boundary')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dirs', nargs='+', type=Path, default=[Path('D:/backtest/data_lighter_240d')])
    parser.add_argument('--output-dir', type=Path, default=Path('research_audit_20260913'))
    parser.add_argument('--warmup-days',type=int,default=25)
    args = parser.parse_args()
    if args.output_dir.resolve().is_relative_to(Path('D:/backtest').resolve()):
        raise ValueError('Output must not be inside Bot 1 directory')
    if args.warmup_days < 25:
        raise ValueError('At least 25 complete days required for fair route comparison')
    minutes, metadata = read_minutes([d/'BTCUSDT_1m.csv' for d in args.data_dirs])
    grid = features(bars5(minutes))
    metadata['feature_coverage'] = {
        'grid_5m_rows': len(grid), 'valid_5m_history_rows': int(grid.valid5.sum()),
        'valid_15m_history_rows': int(grid.valid15.eq(True).sum()),
        'complete_25day_route_rows': int(grid.route.notna().sum()),
        'note': 'Missing minute breaks its 5m bar; incomplete day invalidates rolling daily SMA25.'}
    start = minutes.index[0].ceil('D') + pd.Timedelta(days=args.warmup_days)
    stop = minutes.index[-1] + pd.Timedelta(minutes=1)
    # Calendar-time split independent of signal counts and outcomes.
    split = (start+(stop-start)*.6).ceil('D')
    variants, records = {}, []
    for session, hours in [('08_22',(8,22)),('24h',(0,0))]:
        for route_name, router, aux in [('router_on',True,True),('router_off',False,True),
                                         ('main_long_only',False,False)]:
            raw = raw_signals(grid, router_enabled=router, aux_enabled=aux,
                              session_start=hours[0],session_end=hours[1])
            raw = raw.loc[(raw.decision_at >= start)&(raw.decision_at < stop)]
            for policy in ['boundary','latest_5m','rolling_15m']:
                name = f'{route_name}__{session}__{policy}'
                mapped = select_windows(raw,policy=policy)
                mapped = mapped.loc[session_mask(mapped.decision_at,*hours)]
                f = label(mapped,minutes)
                wf = walk_forward(f,split,stop)
                is_contract = policy != 'rolling_15m'
                variants[name] = {'raw_5m_and_aux_observations':len(raw),
                    'mapped_predictions':len(mapped),'incomplete_outcomes_dropped':len(mapped)-len(f),
                    'contract_windows':is_contract, 'all':scores(f),'evaluation':scores(wf),
                    'signal_age_counts':f.signal_age_minutes.value_counts().sort_index().to_dict(),
                    'monthly': {str(k):{'n':len(g),'win_rate':float(g.correct.mean())}
                                for k,g in wf.groupby(wf.decision_at.dt.strftime('%Y-%m'))}}
                if is_contract:
                    variants[name]['ask_scenarios_edge_filtered'] = [scenario(wf,a) for a in [.45,.50,.55]]
                    variants[name]['ask_scenarios_all_signals'] = [scenario(wf,a,require_edge=False) for a in [.45,.50,.55]]
                wf['variant'] = name
                records.append(wf[['variant','decision_at','end_at','signal_at','signal_age_minutes',
                                   'source','side','correct','up_won','p_train','n_train','fit_at']])
        f = label(trend_control(grid,*hours),minutes)
        f = f.loc[(f.decision_at >= start)&(f.decision_at < stop)]
        wf = walk_forward(f,split,stop)
        variants[f'trend_control__{session}'] = {'new_hypothesis_not_dca':True,
                                                'all':scores(f),'evaluation':scores(wf)}
    # Explain prior 1024 -> 614/410 -> 301 count on its original observation scope.
    raw_old = raw_signals(grid,session_start=8,session_end=22)
    old = label(select_windows(raw_old),minutes)
    i = int(len(old)*.6)
    cut = old.decision_at.iloc[i]
    train,test = old.loc[old.decision_at<cut],old.loc[old.decision_at>=cut].copy()
    table = train.groupby(['source','side']).correct.agg(['sum','count'])
    test['p_train'] = [(table.loc[(s,d),'sum']+1)/(table.loc[(s,d),'count']+2)
                       if (s,d) in table.index else np.nan for s,d in zip(test.source,test.side)]
    test['n_train'] = [int(table.loc[(s,d),'count']) if (s,d) in table.index else 0 for s,d in zip(test.source,test.side)]
    legacy = {'all_raw_observations':len(raw_old),'boundary_labelled':len(old),
              'train':len(train),'test':len(test),
              'ask_050_edge03_count':int((test.n_train.ge(20)&test.p_train.ge(.5+.07*.5*.5+.03)).sum())}
    result = {'metadata':metadata,'start_after_warmup':str(start),'end':str(stop),
        'evaluation_start':str(split),'fit_schedule':'expanding monthly; train end_at <= month start',
        'label':'Lighter 1m open(T) to close(T+14m); Up on tie; not official resolution',
        'scope':'raw fresh-direction observations; no DCA inventory/adds/optional deployment gates',
        'inference_limit':'descriptive OOS; same history used by Bot1 research, not pristine external holdout',
        'pnl_limit':'synthetic ask, additive fee, immediate settlement, full assumed fill; no historical market eligibility/books',
        'legacy_funnel':legacy,'variants':variants}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    pd.concat(records,ignore_index=True).to_csv(args.output_dir/'predictions.csv',index=False)
    print(json.dumps({'output':str(args.output_dir.resolve()),'metadata':metadata,
        'legacy_funnel':legacy,'evaluation_start':str(split),
        'counts':{k:{'all':v['all']['n'],'evaluation':v['evaluation']['n'],
                     'win_rate':v['evaluation']['win_rate']} for k,v in variants.items()}},indent=2))


if __name__ == '__main__':
    main()
