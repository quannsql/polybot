from copy import deepcopy
import numpy as np
import pandas as pd
import pytest

from research_high_confidence import inputs,trade,summarize,economics,keep


def frame():
    ts=pd.date_range('2026-10-01',periods=120,freq='min',tz='UTC')
    p=100+np.sin(np.arange(120)/5)+np.arange(120)*.01
    return pd.DataFrame(dict(open=p,close=p),index=ts)


def test_closed_minutes_no_future_and_no_false_5_second_uncertainty():
    f=frame(); start=int(f.index[90].timestamp())
    before=inputs(f,start,895,'up')
    changed=f.copy(); changed.loc[changed.index>=pd.Timestamp(start+840,unit='s',tz='UTC'),'close']*=10
    assert inputs(changed,start,895,'up')==before
    assert before['uncertainty_minutes_from_last_known_close']==1


def test_zero_trades_never_perfect_and_nonfill_not_win():
    assert summarize([])['win_rate'] is None
    assert summarize([dict(modeled_fill=False,won=True,pnl=0)])['n']==0


def test_final_price_and_settlement_only_change_scoring_not_entry():
    row=dict(start=100000,slug='s',side='up')
    record=dict(fee=dict(status='known',rate=.07),settlement=dict(status='confirmed',winner='up'),
        up_history=dict(status=200,body=dict(history=[dict(t=100840,p=.99)])))
    f=dict(lead_z=3.,vol_ratio=1.)
    a,_=trade(row,record,f,870,.99,.001,75,'z3')
    other=deepcopy(record); other['eventMetadata']=dict(finalPrice=0,priceToBeat=999999)
    other['settlement']['winner']='down'
    b,_=trade(row,other,f,870,.99,.001,75,'z3')
    assert a['shares']==b['shares'] and a['assumed_price']==b['assumed_price']
    assert b['pnl']==-20


def test_fee_economics_and_one_loss_stress():
    e=economics(.99)
    assert e['win_pnl']==pytest.approx(.18788867994424)
    assert e['break_even_win_probability']==pytest.approx(.990693)
    assert e['wins_to_recover_one_loss']==107
    assert summarize([dict(modeled_fill=True,won=True,pnl=.2,shares=20.2)])['one_winner_flipped_to_loss_pnl']==-20


def test_missing_z_cannot_pass_and_quiet_is_conditional():
    assert not keep(dict(lead_z=None,vol_ratio=1),'z3')
    assert keep(dict(lead_z=3,vol_ratio=None),'z3')
    assert not keep(dict(lead_z=3,vol_ratio=None),'quiet_z3')
