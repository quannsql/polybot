import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_recheck_1130 import observations, recheck


def minutes():
    index=pd.date_range('2026-06-01',periods=28*1440+60,freq='min',tz='UTC',name='timestamp')
    price=100+np.sin(np.arange(len(index))/70)
    return pd.DataFrame({'open':price,'high':price+1,'low':price-1,'close':price,'volume':1.},index=index)


def test_recheck_does_not_read_future_or_unfinished_minute():
    m=minutes(); start=m.index[-60]
    g,r,b=observations(m)
    before=recheck(g,r,b,m,start,'down','aux_short_15m')
    m.loc[m.index>=start+pd.Timedelta(minutes=11),['open','high','low','close']]*=10
    g,r,b=observations(m)
    after=recheck(g,r,b,m,start,'down','aux_short_15m')
    assert before==after
    assert pd.Timestamp(before['audit']['partial_close_available_at'])==start+pd.Timedelta(minutes=11)
    assert pd.Timestamp(before['audit']['closed_15m_available_at'])==start


def test_opposite_event_veto_and_no_new_signal_differ_from_reaffirmation():
    m=minutes();start=m.index[-60];g,_,b=observations(m)
    raw=pd.DataFrame({'signal_at':pd.Series([],dtype='datetime64[ns, UTC]'),'side':pd.Series([],dtype=str)})
    x=recheck(g,raw,b,m,start,'up','main_5m')
    assert x['veto_new_opposite'] and not x['require_new_same']
    raw=pd.DataFrame({'signal_at':[start+pd.Timedelta(minutes=5),start+pd.Timedelta(minutes=10)],'side':['down','up']})
    x=recheck(g,raw,b,m,start,'up','main_5m')
    assert not x['veto_new_opposite'] and x['require_new_same']
    # T+15 signal would only become available AFTER this market's entry/expiry.
    future=pd.DataFrame({'signal_at':[start+pd.Timedelta(minutes=15)],'side':['down']})
    assert recheck(g,pd.concat([raw,future]),b,m,start,'up','main_5m')==x


def test_rechecking_closed_15m_does_not_create_new_15m_information():
    m=minutes();start=m.index[-60];g,r,b=observations(m)
    for col,value in [('valid15',True),('close15',102.),('upper15',101.),('run60',70.)]:
        g.loc[start+pd.Timedelta(minutes=10),col]=value
    x=recheck(g,r.iloc[:0],b,m,start,'down','aux_short_15m')
    assert x['same_branch_closed']
    assert not x['require_new_same']


def test_data_gap_is_visible_not_confirmation():
    m=minutes();start=m.index[-60]
    m.loc[start+pd.Timedelta(minutes=3),:]=np.nan
    g,r,b=observations(m)
    x=recheck(g,r,b,m,start,'up','main_5m')
    assert not x['audit']['valid_closed_inputs']
    assert not x['veto_new_opposite'] and not x['require_new_same']


def test_recheck_counts_reconcile_saved_research_if_available():
    path=Path(__file__).parents[1]/'logs/recheck_1130/summary.json'
    if not path.exists():
        pytest.skip('Local study output absent')
    report=json.loads(path.read_text())
    assert report['original_signal_parity_markets']==413
    for row in report['results']:
        assert row['retained_candidates']+row['removed_winners']+row['removed_losers']==row['original_candidates']
        assert row['wins']+row['losses']==row['assumed_fills']
        assert row['assumed_fills']+row['retained_cost_nonfills']==row['retained_candidates']
