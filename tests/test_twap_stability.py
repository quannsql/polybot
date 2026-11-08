import numpy as np
import pandas as pd
import pytest

from research_twap_stability import TwapIndex,reference_trade,replay,FIT


def make_index():
    observed=np.arange(FIT*1000,(FIT+901)*1000,1000,dtype=np.int64)
    return TwapIndex(pd.DataFrame(dict(observed_ms=observed,received_ms=observed+1200,
        value=100+np.arange(len(observed))*.001)))


def test_index_only_uses_received_observations_and_blocks_late_open():
    index=make_index()
    assert index.at((FIT+750)*1000)['observed_ms']==(FIT+748)*1000
    index.received=index.received.copy()
    index.received[0]=(FIT+100)*1000
    assert index.decision(FIT,840)[1]=='opening_missing_or_late'


def test_index_future_changes_do_not_change_decision():
    index=make_index(); before=index.decision(FIT,840)
    index.values=index.values.copy()
    index.values[index.received>(FIT+840)*1000]*=10
    assert index.decision(FIT,840)==before


def test_index_gap_is_not_interpolated():
    index=make_index()
    keep=~((index.observed>=(FIT+800)*1000)&(index.observed<=(FIT+810)*1000))
    for attr in ('observed','received','values'):
        setattr(index,attr,getattr(index,attr)[keep])
    assert index.decision(FIT,840)[1]=='oracle_gap'


def row(start,won=True,cost=.95):
    return dict(start=start,decision_seconds=start+840,day='2026-08-15',
        won=won,unit_cost=cost,stressed_unit_cost=None)


def test_loss_stop_acts_after_known_loss_and_never_tops_up():
    rows=[row(FIT,False),row(FIT+900,True),row(FIT+1800,True)]
    a=replay(rows,stake=15,stop=True)
    assert a['taken']==1 and a['skipped']['daily_loss_stop']==2
    assert a['final_cash']==35
    b=replay(rows,stake=15,stop=False,initial=15)
    assert b['taken']==1 and b['skipped']['insufficient_cash']==2


def test_stress_nonfill_is_not_a_win_or_spend():
    result=replay([row(FIT)],stress=True)
    assert result['taken']==0 and result['pnl']==0
    assert result['skipped']['stressed_price_ge_one_nonfill']==1


def test_pending_principal_not_reused_and_overhead_charged():
    result=replay([row(FIT),row(FIT+900)],stake=15,initial=15,delay=1800,overhead=0)
    assert result['taken']==1 and result['skipped']['insufficient_cash']==1
    one=replay([row(FIT)],overhead=.05)
    assert one['pnl']==pytest.approx(15/.95-15-.05)


def test_drawdown_preserves_intermediate_settlement_peak():
    # Both payments are still pending at the final entry. First payout makes
    # equity 55; the following loss takes it to40 => drawdown15, not10.
    rows=[row(FIT,True,.75),row(FIT+900,False,.95)]
    result=replay(rows,stake=15,stop=False,delay=1800)
    assert result['final_cash']==40
    assert result['max_realized_drawdown']==15


def test_reference_is_not_future_and_high_price_stays_nonfill():
    f=dict(start=FIT,delay=840,side='up',lead_bps=10)
    r=dict(settlement=dict(status='confirmed',winner='up'),fee=dict(status='known',rate=.07),
        up_history=dict(status=200,body=dict(history=[dict(t=FIT+841,p=.9)])))
    assert reference_trade(f,r,10)[1]=='reference_missing_or_stale'
    r['up_history']['body']['history']=[dict(t=FIT+839,p=.995)]
    assert reference_trade(f,r,10)[1]=='base_price_ge_one_nonfill'
