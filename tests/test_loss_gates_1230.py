import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from audit_poly_research import bars5
from research_loss_gates_1230 import (
    BOT1, entry_features, exact_gates, load_bot1, metric, poly_gates, safe,
)
from research_signal_extensions import feature_tables


def candles():
    index = pd.date_range('2026-06-01', periods=28*1440+60, freq='min', tz='UTC', name='timestamp')
    p = 100 + np.sin(np.arange(len(index))/23)*.5 + np.sin(np.arange(len(index))/97)
    return pd.DataFrame(dict(open=p,high=p+.1,low=p-.1,close=p,volume=1.),index=index)


def test_entry_gates_cannot_see_unfinished_minute_or_future_quote():
    m = candles(); start=m.index[-60]; t=int(start.timestamp())
    history=[{'t':t+600,'p':.90},{'t':t+730,'p':.95}]
    mf,bands=feature_tables(m)
    before=entry_features(m,mf,bands,start,'up',history)
    m.loc[m.index>=start+pd.Timedelta(minutes=12),['open','high','low','close']] *= 10
    mf,bands=feature_tables(m)
    after=entry_features(m,mf,bands,start,'up',history+[{'t':t+751,'p':.01}])
    assert safe(before)==safe(after)
    assert poly_gates(before,.95)==poly_gates(after,.95)


@pytest.mark.skipif(not (BOT1/'band_dca_lane.py').exists(),reason='Read-only Bot1 source not available')
@pytest.mark.parametrize('source',['main_5m','aux_short_15m'])
def test_exact_dca_helpers_ignore_forming_5m_and_future(source):
    m=candles(); start=m.index[-60]; at=start+pd.Timedelta(minutes=10)
    own=bars5(m); peer=own.copy(); lane,market=load_bot1()
    original=exact_gates(own,peer,at,'down',source,lane,market)
    own.loc[own.timestamp.ge(at),['open','high','low','close']] *= 10
    peer.loc[peer.timestamp.ge(at),['open','high','low','close']] *= .1
    assert exact_gates(own,peer,at,'down',source,lane,market)==original


def test_saved_cohort_matches_old_result_and_never_hides_rejected_winners():
    root=Path(__file__).parents[1]/'logs/loss_gates_1230'
    if not (root/'candidates.json').exists():pytest.skip('Local archive not available')
    rows=json.loads((root/'candidates.json').read_text(encoding='utf-8'))
    summary=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    assert len(rows)==410 and sum(r['won'] for r in rows)==398
    assert len({r['slug'] for r in rows})==410
    assert sum(r['pnl1'] for r in rows)==pytest.approx(132.149707693452)
    for gate,periods in summary['results'].items():
        m=periods['all']
        assert m['wins']+m['losses']==m['n']
        assert m['n']+m['removed_winners']+m['avoided_losses']==410
        assert m['delta1']==pytest.approx(20*m['avoided_losses']-m['removed_winner_profit1'])
    for r in rows:
        for c in (1,2,3):
            if not r['won']:assert r[f'pnl{c}']==-r[f'cost{c}']
            if r[f'cost{c}']==0:assert r[f'pnl{c}']==0


def test_missing_feature_does_not_grant_price_lead_confirmation():
    x=dict(lead=np.nan,lead_z=np.nan,momentum3=np.nan,token_momentum2=np.nan,
           vol_ratio=np.nan,bb_reclaim=False)
    gates=poly_gates(x,.90)
    for g in ('spot_lead_positive','lead_z1','lead_z1_5','momentum3_positive',
              'token_momentum_nonnegative','quiet_vol1_5','lead_z1_and_momentum3'):
        assert not gates[g]
