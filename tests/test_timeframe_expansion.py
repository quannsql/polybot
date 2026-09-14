import copy
from datetime import datetime,timezone

import numpy as np
import pandas as pd
import pytest

from audit_poly_research import bars5
from polymarket_bot.signal_grid import features, raw_signals
from research_timeframes import map_contracts
from research_timeframe_expansion import dca_variant, market_slug, parse_contract, select_venue


def data():
    ix=pd.date_range('2026-04-01',periods=28*1440+240,freq='min',tz='UTC',name='timestamp')
    p=100+np.sin(np.arange(len(ix))/18)+np.arange(len(ix))*.0001
    return pd.DataFrame({'open':p,'high':p+.1,'low':p-.1,'close':p,'volume':1.},index=ix)


def routes(m):
    g=features(bars5(m))
    return g.assign(day=g.decision_at.dt.floor('D')).drop_duplicates('day').set_index('day').route


def test_changed_candle_frames_keep_closed_bar_causality_and_original_parity():
    m=data();route=routes(m)
    baseline=dca_variant(m,5,15,route)
    expected=raw_signals(features(bars5(m)),session_start=0,session_end=0)
    pd.testing.assert_frame_equal(baseline[['signal_at','side']].reset_index(drop=True),expected[['signal_at','side']].reset_index(drop=True),check_dtype=False)
    cutoff=m.index[-240]+pd.Timedelta(minutes=17)
    original=dca_variant(m,10,60,route)
    m.loc[m.index>=cutoff,['open','high','low','close']]*=4
    changed=dca_variant(m,10,60,routes(m))
    pd.testing.assert_frame_equal(original.loc[original.signal_at.le(cutoff)].reset_index(drop=True),changed.loc[changed.signal_at.le(cutoff)].reset_index(drop=True))


def test_market_window_mapping_10m_and_1h_respects_max_signal_age():
    raw=pd.DataFrame({'signal_at':pd.to_datetime(['2026-04-01T00:05Z','2026-04-01T00:48Z','2026-04-01T00:50Z'],utc=True),'side':['up','down','up']})
    mapped=map_contracts(raw,60,max_age=10)
    assert len(mapped)==1 and mapped.iloc[0].side=='up'
    assert mapped.iloc[0].signal_age_minutes==10
    ten=map_contracts(raw,10,max_age=10)
    assert ten.iloc[0].decision_at==pd.Timestamp('2026-04-01T00:10Z')
    assert (ten.end_at-ten.decision_at).eq(pd.Timedelta(minutes=10)).all()


def test_hourly_slug_and_source_match_real_contract_rules():
    start=int(datetime(2026,8,30,16,tzinfo=timezone.utc).timestamp())
    slug=market_slug(start,60)
    assert slug=='bitcoin-up-or-down-august-30-2026-12pm-et'
    winter=int(datetime(2026,1,2,5,tzinfo=timezone.utc).timestamp())
    assert market_slug(winter,60)=='bitcoin-up-or-down-january-2-2026-12am-et'
    m={'slug':slug,'conditionId':'cond','eventStartTime':'2026-08-30T16:00:00Z','endDate':'2026-08-30T17:00:00Z',
       'outcomes':['Up','Down'],'clobTokenIds':['1','2'],'description':'Binance BTC/USDT 1 hour candle','resolutionSource':'Binance'}
    ev={'slug':slug,'markets':[m]}
    assert parse_contract(ev,start,60)['rule_type']=='binance_1h'
    m['endDate']='2026-08-30T16:15:00Z'
    with pytest.raises(ValueError,match='time mismatch'):parse_contract(ev,start,60)
    with pytest.raises(ValueError,match='Unverified'):market_slug(start,10)


def test_parameter_selection_never_reads_confirmation_outcomes():
    results={'a':{'validation':{'n':60,'pnl':5,'pnl_3c':1,'mean_pnl':.1}},
             'b':{'validation':{'n':100,'pnl':30,'pnl_3c':-1,'mean_pnl':.3}},
             'c':{'validation':{'n':10,'pnl':100,'pnl_3c':50,'mean_pnl':10}}}
    assert select_venue(results)==['a']
    for r in results.values():r['confirmation']={'n':10000,'pnl':1e9}
    assert select_venue(results)==['a']
    results['a']['validation']['pnl_3c']=-1
    assert select_venue(results)==[]
