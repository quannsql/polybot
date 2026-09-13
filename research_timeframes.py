"""Timeframe study: frozen validation selection, later confirmation, no orders.

All labels are venue-price proxies. Historical contract listings, Chainlink
settlements, quotes and fills are not inferred from OHLC candles.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_poly_research import read_minutes, bars5
from polymarket_bot.signal_grid import features, raw_signals, session_mask


SIGNAL_MINUTES = [1, 3, 5, 15, 30, 60]
HORIZONS = [5, 15, 30, 60, 240]
FAMILIES = ['two_sided_reversion', 'daily_routed_reversion', 'short_pump']
START = pd.Timestamp('2025-12-10', tz='UTC')
VALIDATION = pd.Timestamp('2026-04-19', tz='UTC')
CONFIRMATION = pd.Timestamp('2026-07-14', tz='UTC')
MAX_AGE = 10


def aggregate(minutes: pd.DataFrame, timeframe: int) -> pd.DataFrame:
    f = minutes.resample(f'{timeframe}min', origin='epoch').agg(
        open=('open','first'), high=('high','max'), low=('low','min'),
        close=('close','last'), volume=('volume','sum'), count=('close','count'))
    f.loc[f['count'].ne(timeframe), ['open','high','low','close','volume']] = np.nan
    f['mid'] = f.close.rolling(20).mean()
    sigma = f.close.rolling(20).std(ddof=0)
    f['lower'], f['upper'] = f.mid-2*sigma, f.mid+2*sigma
    f['valid'] = f.close.rolling(30).count().eq(30) & sigma.gt(0)
    f['signal_at'] = f.index + pd.Timedelta(minutes=timeframe)
    return f


def signal_bank(minutes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    grid = features(bars5(minutes))
    daily = grid.assign(day=grid.decision_at.dt.floor('D')).drop_duplicates('day').set_index('day').route
    bank = {}
    for timeframe in SIGNAL_MINUTES:
        f = aggregate(minutes,timeframe)
        route = f.signal_at.dt.floor('D').map(daily)
        now = pd.DatetimeIndex(f.signal_at)-pd.Timedelta(minutes=1)
        past = now-pd.Timedelta(minutes=60)
        run = pd.Series((minutes.close.reindex(now).to_numpy()/minutes.close.reindex(past).to_numpy()-1)*10000,
                        index=f.index)
        up, down = f.close.le(f.lower), f.close.ge(f.upper)
        for family in FAMILIES:
            if family == 'two_sided_reversion':
                mask = up | down
            elif family == 'daily_routed_reversion':
                mask = (up & route.eq('long')) | (down & route.eq('short'))
            else:
                mask = down & run.ge(60)
            x = f.loc[f.valid & mask,['signal_at']].copy()
            x['side'] = np.where(up.loc[x.index], 'up', 'down')
            x['source'] = f'{family}_{timeframe}m'
            bank[f'{family}_{timeframe}m'] = x.reset_index(drop=True)
    baseline = raw_signals(grid,session_start=0,session_end=0)
    bank['dca_5m_plus_15m'] = baseline[['signal_at','side','source']].reset_index(drop=True)
    return bank


def map_contracts(raw: pd.DataFrame, horizon: int, *, max_age: int=MAX_AGE) -> pd.DataFrame:
    """One prediction at the next epoch-aligned boundary, using past data only.

    For 4h this is a UTC research grid; actual market calendars must be matched
    before replaying orders. No carried signal older than max_age minutes.
    """
    if horizon <= 0 or max_age < 0:
        raise ValueError('Invalid mapping settings')
    x = raw.copy()
    x['decision_at'] = x.signal_at.dt.ceil(f'{horizon}min')
    x['signal_age_minutes'] = (x.decision_at-x.signal_at).dt.total_seconds()/60
    x = x.loc[x.signal_age_minutes.le(max_age)].sort_values('signal_at')
    x = x.drop_duplicates('decision_at',keep='last').sort_values('decision_at')
    x['end_at'] = x.decision_at+pd.Timedelta(minutes=horizon)
    return x.reset_index(drop=True)


def label_horizon(mapped: pd.DataFrame, minutes: pd.DataFrame, horizon: int) -> pd.DataFrame:
    x = mapped.copy()
    ends = pd.DatetimeIndex(x.end_at)-pd.Timedelta(minutes=1)
    x['start_price'] = minutes.open.reindex(pd.DatetimeIndex(x.decision_at)).to_numpy()
    x['end_price'] = minutes.close.reindex(ends).to_numpy()
    complete = minutes.close.rolling(horizon).count().reindex(ends).to_numpy() == horizon
    x = x.loc[complete & x.start_price.notna() & x.end_price.notna()].copy()
    x['up_won'] = x.end_price.ge(x.start_price)
    x['correct'] = x.side.eq(np.where(x.up_won,'up','down'))
    x['signed_return_bps'] = (x.end_price/x.start_price-1)*10000*np.where(x.side.eq('up'),1,-1)
    return x.reset_index(drop=True)


def split_periods(x: pd.DataFrame, stop: pd.Timestamp) -> dict[str,pd.DataFrame]:
    # Purge labels crossing either split, important for slow horizons.
    return {
        'train':x.loc[x.decision_at.ge(START)&x.end_at.le(VALIDATION)],
        'validation':x.loc[x.decision_at.ge(VALIDATION)&x.end_at.le(CONFIRMATION)],
        'confirmation':x.loc[x.decision_at.ge(CONFIRMATION)&x.end_at.le(stop)],
    }


def stats(x: pd.DataFrame) -> dict:
    n = len(x)
    if not n:
        return {'n':0, 'win_rate':None,'wilson_lower':None,'week_cluster_ci95':[None,None]}
    p = float(x.correct.mean())
    z = 1.959963984540054
    lower = (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
    day = x.decision_at.dt.floor('D')
    # Fixed non-overlapping seven-day clusters (labels within a cluster may overlap).
    block = ((day - pd.Timestamp('2025-01-01',tz='UTC')).dt.days//7)
    groups = x.groupby(block).correct.agg(['sum','count'])
    if len(groups) >= 4:
        rng = np.random.default_rng(913)
        ix = rng.integers(0,len(groups),size=(2000,len(groups)))
        samples = groups['sum'].to_numpy()[ix].sum(axis=1)/groups['count'].to_numpy()[ix].sum(axis=1)
        ci = np.quantile(samples,[.025,.975]).tolist()
    else:
        ci = [None,None]
    month = x.decision_at.dt.strftime('%Y-%m')
    return {'n':n,'wins':int(x.correct.sum()),'win_rate':p,'wilson_lower':float(lower),
        'week_clusters':len(groups),'week_cluster_ci95':ci,
        'always_up_accuracy':float(x.up_won.mean()),
        'always_down_accuracy':float((~x.up_won).mean()),
        'median_signed_return_bps':float(x.signed_return_bps.median()),
        'monthly':{str(k):{'n':len(g),'win_rate':float(g.correct.mean())} for k,g in x.groupby(month)}}


def economics(x: pd.DataFrame, train: pd.DataFrame) -> list[dict]:
    """Sensitivity per $1 budget, no bankroll/fill/settlement claims."""
    table = train.groupby(['source','side']).correct.agg(['sum','count'])
    p,n = [],[]
    for s,d in zip(x.source,x.side):
        if (s,d) in table.index:
            v = table.loc[(s,d)]
            p.append((v['sum']+1)/(v['count']+2)); n.append(v['count'])
        else:
            p.append(np.nan); n.append(0)
    p,n = np.array(p),np.array(n)
    rows=[]
    for ask in [.48,.50,.52,.55]:
        cost = ask+.07*ask*(1-ask)
        for mode in ['all_predictions','train_edge_ge_003']:
            ix = np.ones(len(x),dtype=bool) if mode=='all_predictions' else (n>=30)&((p-cost)>=.03)
            s = x.loc[ix]
            wr = float(s.correct.mean()) if len(s) else None
            rows.append({'ask':ask,'fee_rate_parameter':.07,'cost_per_share':cost,'mode':mode,
                'n':len(s),'win_rate':wr,'return_per_dollar_budget':wr/cost-1 if wr is not None else None})
    return rows


def path_measurements(raw: pd.DataFrame, minutes: pd.DataFrame) -> tuple[dict,pd.DataFrame]:
    """Same signal cohort at all horizons, no DCA; first-hit TP/SL ordering.

    Simultaneous TP/SL inside one minute is conservatively SL-first.
    A touched target is not a promise of an executable fill.
    """
    horizons = [5,15,30,60,240,720]
    x = raw.copy()
    x['decision_at'] = x.signal_at
    x['end_at'] = x.signal_at+pd.Timedelta(minutes=max(horizons))
    x = label_horizon(x,minutes,max(horizons))
    x = x.loc[x.decision_at.ge(VALIDATION)].reset_index(drop=True)
    indices = minutes.index.get_indexer(pd.DatetimeIndex(x.decision_at))
    ix = indices[:,None]+np.arange(max(horizons))[None,:]
    sign = np.where(x.side.eq('up'),1,-1)
    entry = x.start_price.to_numpy()[:,None]
    high, low = minutes.high.to_numpy()[ix],minutes.low.to_numpy()[ix]
    close = minutes.close.to_numpy()[ix]
    favorable = np.where(sign[:,None]>0,high/entry-1,1-low/entry)*10000
    adverse = np.where(sign[:,None]>0,1-low/entry,high/entry-1)*10000
    positive = favorable>0
    tp5, tp30, sl200 = favorable>=5, favorable>=30, adverse>=200
    def first_hit(a):
        return np.where(a.any(axis=1),a.argmax(axis=1)+1,max(horizons)+1)
    first_tp, first_sl = first_hit(tp30),first_hit(sl200)
    rows=[]
    examples=[]
    for h in horizons:
        correct = np.where(sign>0,close[:,h-1]>=entry[:,0],close[:,h-1]<entry[:,0])
        row={'horizon_minutes':h,'n':len(x),'endpoint_win_rate':float(correct.mean()),
            'ever_favorable_rate':float(positive[:,:h].any(axis=1).mean()),
            'ever_plus_5bp_rate':float(tp5[:,:h].any(axis=1).mean()),
            'ever_plus_30bp_rate':float(tp30[:,:h].any(axis=1).mean()),
            'tp30_before_sl200_rate':float(((first_tp<=h)&(first_tp<first_sl)).mean()),
            'both_in_same_first_minute_rate':float(((first_tp<=h)&(first_tp==first_sl)).mean()),
            'tp30_but_wrong_endpoint_rate':float(((first_tp<=h)&~correct).mean())}
        rows.append(row)
        if h==15:
            take = np.flatnonzero((first_tp<=h)&(first_tp<first_sl)&~correct)[:5]
            for j in take:
                examples.append({'signal_at':str(x.decision_at.iloc[j]),'side':x.side.iloc[j],
                    'entry':entry[j,0],'tp30_first_hit_minute':int(first_tp[j]),
                    'close_after_15m':close[j,h-1]})
    exported = x[['decision_at','side','source']].copy()
    exported['first_tp30_minute'] = first_tp
    exported['first_sl200_minute'] = first_sl
    return {'scope':'raw baseline signals; common complete 12h cohort; no DCA; OHLC touch diagnostic',
             'period_start':str(VALIDATION),'rows':rows,'examples_tp_then_wrong_15m':examples},exported


def plot_results(summary: dict, output: Path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names = summary['variants']
    fig,axes=plt.subplots(1,3,figsize=(15,5),constrained_layout=True)
    for ax,family in zip(axes,FAMILIES):
        matrix=np.full((len(SIGNAL_MINUTES),len(HORIZONS)),np.nan)
        for i,tf in enumerate(SIGNAL_MINUTES):
            for j,h in enumerate(HORIZONS):
                s=names[f'{family}_{tf}m__{h}m']['confirmation']
                if s['n']>=100: matrix[i,j]=s['win_rate']*100
                label='--' if s['win_rate'] is None else f"{100*s['win_rate']:.1f}%\nn={s['n']}"
                ax.text(j,i,label,ha='center',va='center',fontsize=8)
        mesh=ax.imshow(matrix,vmin=45,vmax=65,cmap='RdYlGn',aspect='auto')
        ax.set_xticks(range(len(HORIZONS)),['5m','15m','30m','1h','4h'])
        ax.set_yticks(range(len(SIGNAL_MINUTES)),[f'{x}m' for x in SIGNAL_MINUTES])
        ax.set_title(family.replace('_',' '),fontsize=10)
        ax.set_xlabel('Prediction horizon'); ax.set_ylabel('Signal timeframe')
    fig.suptitle('Later-period price-direction accuracy | 14 Jul - 3 Sep 2026\nLighter proxy; grey/blank cells have <100 observations; not Polymarket PnL',fontsize=12)
    fig.colorbar(mesh,ax=axes,label='Accuracy (%)',shrink=.8)
    fig.savefig(output/'timeframe_matrix.png',dpi=150)
    plt.close(fig)
    path=summary['path_diagnostic']['rows']
    fig,ax=plt.subplots(figsize=(9,4),constrained_layout=True)
    xs=np.arange(len(path))
    for col,title in [('endpoint_win_rate','Correct at expiry'),('ever_plus_30bp_rate','Ever touches +30bp'),
                       ('tp30_before_sl200_rate','+30bp before -200bp')]:
        ax.plot(xs,[r[col]*100 for r in path],marker='o',label=title)
    ax.set_xticks(xs,['5m','15m','30m','1h','4h','12h']);ax.set_ylim(0,100)
    ax.set_ylabel('Share of identical signal cohort (%)');ax.legend()
    ax.set_title('A price can reach a profit target, then finish in the opposite direction\nNo DCA; candle-touch diagnostic, not executable trade results',fontsize=10)
    ax.grid(alpha=.2)
    fig.savefig(output/'touch_vs_expiry.png',dpi=150)
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dirs',nargs='+',type=Path,default=[Path('D:/backtest')/d for d in
        ['data_lighter_240d','data_lighter_augall','data_lighter_0903']])
    parser.add_argument('--output-dir',type=Path,default=Path('timeframe_research_20260913'))
    parser.add_argument('--binance-data',type=Path,default=Path('D:/backtest/data_binance_aug/BTCUSDT_1m.csv'))
    args=parser.parse_args()
    if args.output_dir.resolve().is_relative_to(Path('D:/backtest').resolve()):
        raise ValueError('Research output must stay outside Bot1')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    plan={'signal_minutes':SIGNAL_MINUTES,'horizon_minutes':HORIZONS,'families':FAMILIES,
        'baseline':'DCA main 5m + auxiliary 15m; router on',
        'bollinger':[20,2],'session':'24h; 08-22 sensitivity on validation-selected candidates',
        'max_signal_age_minutes':MAX_AGE,'start':str(START),'validation_start':str(VALIDATION),
        'confirmation_start':str(CONFIRMATION),
        'selection':'top 3 per horizon by validation Wilson lower bound, train n>=100, validation n>=200; no confirmation labels',
        'statistical_status':'95 predeclared variants, no multiple-comparison significance claim; history previously examined, not pristine holdout',
        'labels':'fixed UTC grids, first minute open to last minute close; market source/listing/calendar not verified historically',
        'fees':'additive fee sensitivity only; no historical quotes or fills'}
    (args.output_dir/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    minutes,metadata=read_minutes([d/'BTCUSDT_1m.csv' for d in args.data_dirs])
    stop=minutes.index[-1]+pd.Timedelta(minutes=1)
    if stop<=CONFIRMATION:
        raise ValueError('This fixed protocol needs confirmation data after 2026-07-14')
    bank=signal_bank(minutes)
    variants, frames = {},{}
    for key,raw in bank.items():
        for h in HORIZONS:
            ident=f'{key}__{h}m'
            f=label_horizon(map_contracts(raw,h),minutes,h)
            parts=split_periods(f,stop)
            frames[ident]=parts
            variants[ident]={'signal':key,'horizon_minutes':h,'mapped':len(f),
                              'train':stats(parts['train']),'validation':stats(parts['validation'])}
    selected={}
    for h in HORIZONS:
        eligible=[k for k,v in variants.items() if v['horizon_minutes']==h and
            v['train']['n']>=100 and v['validation']['n']>=200]
        selected[str(h)]=sorted(eligible,key=lambda k:(-variants[k]['validation']['wilson_lower'],k))[:3]
    # Freeze these IDs before inspecting the later-period outcomes.
    (args.output_dir/'selected_on_validation.json').write_text(json.dumps(selected,indent=2),encoding='utf-8')
    picked=set(sum(selected.values(),[]))
    for ident,parts in frames.items():
        v=variants[ident]
        v['confirmation']=stats(parts['confirmation'])
        v['selected_on_validation']=ident in picked
        if ident in picked or v['signal']=='dca_5m_plus_15m':
            calibration=pd.concat([parts['train'],parts['validation']])
            v['price_sensitivity']=economics(parts['confirmation'],calibration)
            for phase in ['validation','confirmation']:
                x=parts[phase]
                # Candidate selection stays frozen; this is sensitivity, not a new optimisation.
                mask=session_mask(x.decision_at,8,22)&session_mask(x.signal_at,8,22)
                v[f'{phase}_08_22']=stats(x.loc[mask])
    # Paired predictions isolate quality differences from differing entry times.
    paired={}
    for ident in picked:
        h=variants[ident]['horizon_minutes']
        baseline=frames[f'dca_5m_plus_15m__{h}m']['confirmation']
        common=frames[ident]['confirmation'].merge(baseline,on='decision_at',suffixes=('_candidate','_baseline'))
        paired[ident]={'n':len(common),
            'candidate_win_rate':float(common.correct_candidate.mean()) if len(common) else None,
            'baseline_win_rate':float(common.correct_baseline.mean()) if len(common) else None,
            'different_direction_count':int(common.side_candidate.ne(common.side_baseline).sum())}
    cross={}
    if args.binance_data.exists():
        bm,bmeta=read_minutes([args.binance_data])
        for ident in sorted(picked | {f'dca_5m_plus_15m__{h}m' for h in HORIZONS}):
            h=variants[ident]['horizon_minutes']
            original=frames[ident]['confirmation']
            relabel=label_horizon(original.drop(columns=['start_price','end_price','correct','up_won','signed_return_bps']),bm,h)
            common=original.merge(relabel,on='decision_at',suffixes=('_lighter','_binance'))
            cross[ident]={'n':len(common),'lighter_win_rate':float(common.correct_lighter.mean()) if len(common) else None,
                'binance_win_rate':float(common.correct_binance.mean()) if len(common) else None,
                'label_disagreements':int(common.up_won_lighter.ne(common.up_won_binance).sum()),
                'note':'same Lighter signals, Binance outcome labels, common timestamps only'}
        cross['metadata']=bmeta
    path,pathrows=path_measurements(bank['dca_5m_plus_15m'],minutes)
    result={'protocol':plan,'metadata':metadata,'stop':str(stop),'selected':selected,'variants':variants,
            'paired_with_baseline':paired,'cross_venue_labels':cross,'path_diagnostic':path}
    (args.output_dir/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    pathrows.to_csv(args.output_dir/'path_cohort.csv',index=False)
    tables=[]
    for ident,parts in frames.items():
        for period in ['validation','confirmation']:
            tables.append(parts[period].assign(variant=ident,period=period,selected_on_validation=ident in picked))
    pd.concat(tables,ignore_index=True).to_csv(args.output_dir/'predictions.csv',index=False)
    plot_results(result,args.output_dir)
    print(json.dumps({'output':str(args.output_dir.resolve()),'variants':len(variants),'selected':selected,
                     'path':path,'selected_results':{k:variants[k]['confirmation'] for k in sorted(picked)}},indent=2))


if __name__=='__main__':
    main()
