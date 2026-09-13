import numpy as np
import pandas as pd

from research_timeframes import (aggregate,map_contracts,label_horizon,split_periods,
                                 path_measurements,VALIDATION,CONFIRMATION)


def minute_frame(n=720):
    return pd.DataFrame({'open':100.,'high':100.,'low':100.,'close':100.,'volume':1.},
                         index=pd.date_range(VALIDATION,periods=n,freq='min',name='timestamp'))


def test_timeframe_aggregates_use_only_complete_closed_bars():
    f=minute_frame(400)
    f['close']=100+np.sin(np.arange(400))
    f['high']=f[['open','close']].max(axis=1)
    f['low']=f[['open','close']].min(axis=1)
    for tf in [1,3,5,15,30,60]:
        at=f.index[300]
        a=aggregate(f.iloc[:300],tf)
        b=aggregate(f,tf)
        a=a.loc[a.signal_at.le(at)]
        pd.testing.assert_frame_equal(a,b.loc[b.signal_at.le(at)])


def test_slow_horizon_does_not_carry_hour_old_signal():
    t=pd.to_datetime(['2026-04-19 00:05Z','2026-04-19 03:55Z','2026-04-19 04:00Z'])
    raw=pd.DataFrame({'signal_at':t,'side':['up','down','up']})
    x=map_contracts(raw,240)
    assert len(x)==1
    assert x.signal_at.iloc[0]==t[-1]
    assert x.end_at.iloc[0]==pd.Timestamp('2026-04-19 08:00Z')


def test_variable_horizon_labels_check_every_minute_and_tie_is_up():
    f=minute_frame()
    raw=pd.DataFrame({'signal_at':[f.index[0]],'side':['down']})
    for h in [5,15,30,60,240]:
        mapped=map_contracts(raw,h)
        x=label_horizon(mapped,f,h)
        assert len(x)==1 and not bool(x.correct.iloc[0])
        missing=f.copy();missing.loc[f.index[h//2],'close']=np.nan
        assert label_horizon(mapped,missing,h).empty


def test_long_labels_are_purged_at_split():
    times=pd.DatetimeIndex([VALIDATION-pd.Timedelta(hours=1),VALIDATION,
                            CONFIRMATION-pd.Timedelta(hours=1),CONFIRMATION])
    x=pd.DataFrame({'decision_at':times,'end_at':times+pd.Timedelta(hours=4)})
    parts=split_periods(x,CONFIRMATION+pd.Timedelta(days=1))
    assert parts['train'].empty
    assert parts['validation'].decision_at.tolist()==[VALIDATION]
    assert parts['confirmation'].decision_at.tolist()==[CONFIRMATION]


def test_profit_target_can_win_while_binary_expiry_loses():
    f=minute_frame()
    f.loc[f.index[2],'high']=100.4  # +40bp target touch
    f.loc[f.index[14],'close']=99.9 # -10bp at 15m expiry
    f.loc[f.index[14],'low']=99.9
    raw=pd.DataFrame({'signal_at':[f.index[0]],'side':['up'],'source':['test']})
    stats,_=path_measurements(raw,f)
    r=next(r for r in stats['rows'] if r['horizon_minutes']==15)
    assert r['tp30_before_sl200_rate']==1
    assert r['endpoint_win_rate']==0
    f.loc[f.index[2],'low']=97.9 # unknown intra-minute order: assume SL first
    stats,_=path_measurements(raw,f)
    r=next(r for r in stats['rows'] if r['horizon_minutes']==15)
    assert r['tp30_before_sl200_rate']==0
