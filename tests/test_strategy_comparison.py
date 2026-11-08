import numpy as np
import pandas as pd
import pytest

from research_strategy_comparison import oracle_at,oracle_decision,BookState,paired_cost


def reports():
    start=100000
    ts=np.arange(start*1000,(start+901)*1000,1000,dtype=np.int64)
    return start,pd.DataFrame(dict(observed_ms=ts,received_ms=ts+1200,value=100+np.arange(len(ts))*.001))


def test_oracle_defers_not_yet_received_points():
    start,f=reports()
    r=oracle_at(f,(start+750)*1000)
    assert r['observed_ms']==(start+748)*1000
    assert r['received_ms']<=(start+750)*1000


def test_opening_report_must_have_been_received_near_open():
    start,f=reports()
    f.loc[f.observed_ms.eq(start*1000),'received_ms']=(start+500)*1000
    assert oracle_decision(f,start,750)[1]=='opening_report_missing_or_late'


def test_future_changes_do_not_change_past_entry():
    start,f=reports(); before=oracle_decision(f,start,750)
    f.loc[f.received_ms>(start+750)*1000,'value']*=10
    assert oracle_decision(f,start,750)==before


def test_gap_and_stale_oracle_block_entry():
    start,f=reports()
    cut=f.loc[~f.observed_ms.between((start+710)*1000,(start+720)*1000)]
    assert oracle_decision(cut,start,750)[1]=='oracle_gap'
    assert oracle_at(f.iloc[:5],(start+750)*1000) is None


def test_book_reset_after_gap_requires_full_snapshot():
    b=BookState(); b.apply('book',[(.4,10)],[(.6,10)],1000,1010,seq=1)
    assert b.book(1010)['asks'][0]['price']==.6
    b.apply('status',[],[],1020,1020,status='gap_start')
    b.apply('price_change',[],[(.59,10)],1030,1040,seq=2)
    with pytest.raises(ValueError): b.book(1040)
    b.apply('book',[(.4,10)],[(.6,10)],1050,1060,seq=3)
    assert b.book(1060)


def test_book_delta_cancellation_sequence_loss_and_receive_time():
    b=BookState(); b.apply('book',[(.4,10)],[(.6,10),(.7,20)],1000,1010,seq=1)
    with pytest.raises(ValueError): b.book(1005)
    b.apply('price_change',[],[(.6,0)],1020,1030,seq=2)
    assert b.book(1030)['asks'][0]['price']==.7
    b.apply('price_change',[],[(.65,10)],1040,1050,seq=4)
    with pytest.raises(ValueError): b.book(1050)


def test_pair_fee_and_equal_share_accounting():
    a=dict(asks=[dict(price='.49',size=10)])
    assert paired_cost(a,a,5,0)['net_before_other_costs']==pytest.approx(.1)
    assert paired_cost(a,a,5,.07)['net_before_other_costs']<0
