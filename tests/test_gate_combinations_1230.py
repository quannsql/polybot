import copy
import json
from pathlib import Path

import numpy as np
import pytest

from research_gate_combinations_1230 import (
    SOURCE, OUT, RULES, bootstrap, decide, inputs, masks, walkforward,
)


def condition(**changes):
    x=dict(vol=1.2,z=1.1,memory=False,early=False,weak=False,aux_shock=False,old_signal=False)
    return x|changes


def test_conditional_memory_is_not_unconditional_veto():
    rule=next(r for r in RULES if r['id']=='q1.5_z1_memory')
    assert decide(condition(memory=True,z=1.),rule)
    assert not decide(condition(memory=True,z=.99),rule)
    assert decide(condition(memory=False,z=.5),rule)
    assert not decide(condition(vol=1.51),rule)
    assert not decide(condition(vol=None),rule)
    assert not decide(condition(memory=True,z=None),rule)


def test_combined_veto_preserves_branch_flags_and_aux_shock():
    rule=next(r for r in RULES if r['id']=='q1.5_z1.25_memory_old_signal_aux_shock')
    assert not decide(condition(old_signal=True,z=1.2),rule)
    assert decide(condition(old_signal=True,z=1.3),rule)
    assert not decide(condition(aux_shock=True,z=2.),rule)
    assert decide(condition(z=.4),rule)


@pytest.fixture
def rows():
    if not SOURCE.exists():pytest.skip('Local historical audit unavailable')
    return json.loads(SOURCE.read_text(encoding='utf-8'))


def test_labels_pnl_slug_and_future_diagnostics_never_enter_decision(rows):
    a=masks(rows)
    changed=copy.deepcopy(rows)
    for r in changed:
        r['won']=not r['won'];r['winner']='opposite';r['pnl1']=1e9
        r['slug']='unrelated';r['outcome_diagnostic_only']={'future_price':1e30}
    assert np.array_equal(a,masks(changed))
    assert set(inputs(rows[0]))=={'vol','z','memory','early','weak','aux_shock','old_signal'}


def test_walkforward_june_choice_and_score_ignore_july_august_outcomes(rows):
    matrix=masks(rows)
    before=walkforward(rows,matrix)['folds'][0]
    changed=copy.deepcopy(rows)
    for r in changed:
        if r['start']>=1782864000:  # 2026-07-01 UTC
            r['won']=not r['won']
            for c in (1,2,3):r[f'pnl{c}']=1000 if r['won'] else -1000
    after=walkforward(changed,matrix)['folds'][0]
    assert before==after


def test_bootstrap_handles_all_identical_no_change_rules(rows):
    result=bootstrap(rows,np.ones((len(RULES),len(rows)),bool),repetitions=10)
    assert all(r['paired_gain_per_original_candidate_ci95']==[0.,0.] for r in result.values())


def test_saved_metrics_reconcile_every_candidate_and_nonfill():
    path=OUT/'summary.json'
    if not path.exists():pytest.skip('Research artifact unavailable')
    s=json.loads(path.read_text(encoding='utf-8'))
    assert len(s['results'])==58
    for r in s['results'].values():
        m=r['all']
        assert m['n']+m['avoided_losses']+m['removed_winners']==410
        assert m['wins']+m['losses']==m['n']
        assert m['delta1']==pytest.approx(20*m['avoided_losses']-m['sacrificed_winner_profit1'])
        for c in (1,2,3):
            assert m[f'fills{c}']+m[f'nonfills{c}']==m['n']
            assert m[f'filled_losses{c}']+m[f'nonfill_would_lose{c}']==m['losses']
