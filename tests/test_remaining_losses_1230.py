import copy
import json
import numpy as np
import pytest
from research_remaining_losses_1230 import SOURCE, OUT, RULES, matrix, entry_inputs, keep, choose
from polymarket_bot.entry_gates import decide
from research_gate_combinations_1230 import inputs


@pytest.fixture
def cohort():
    if not SOURCE.exists():pytest.skip('Local research archive absent')
    return [r for r in json.loads(SOURCE.read_text()) if decide(inputs(r))[0]]


def test_additional_gate_cannot_read_outcome_or_future(cohort):
    expected=matrix(cohort); changed=copy.deepcopy(cohort)
    for r in changed:
        r['won']=not r['won'];r['winner']='unknown';r['slug']='different'
        r['outcome_diagnostic_only']={'future':1e12}
        for c in (1,2,3):r[f'pnl{c}']=1e9
    assert np.array_equal(matrix(changed),expected)


def test_conditional_gate_does_not_require_positive_momentum_alone(cohort):
    x=entry_inputs(cohort[0]);rule=next(r for r in RULES if r['id']=='adverse_momentum_z0.5')
    assert keep(x|dict(momentum=-.001,z=.5),rule)
    assert not keep(x|dict(momentum=-.001,z=.4999),rule)
    assert keep(x|dict(momentum=.001,z=.4),rule)
    assert not keep(x|dict(momentum=-.001,z=None),rule)


def test_later_outcomes_do_not_change_training_selection(cohort):
    train=[r for r in cohort if r['period']=='validation']
    expected=choose(train,matrix(train))
    changed=copy.deepcopy(cohort)
    for r in changed:
        if r['period']=='confirmation':
            r['won']=False
            for c in (1,2,3):r[f'pnl{c}']=-1e9
    train=[r for r in changed if r['period']=='validation']
    assert choose(train,matrix(train))==expected


def test_scores_reconcile_removed_wins_and_losses():
    path=OUT/'summary.json'
    if not path.exists():pytest.skip('Run research first')
    report=json.loads(path.read_text(encoding='utf-8'))
    for result in report['results'].values():
        s=result['all']
        assert s['wins']+s['losses']==s['n']
        assert s['n']+s['removed_winners']+s['avoided_losses']==300
        assert s['delta1']==pytest.approx(20*s['avoided_losses']-s['sacrificed_winner_profit1'])
        for c in (1,2,3):assert s[f'fills{c}']+s[f'nonfills{c}']==s['n']
