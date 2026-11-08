"""Accounting/data-integrity checks for the independent fresh-period replay."""
from copy import deepcopy
import pytest

from research_fresh_data import candle_rows, metrics, scenario, wallet


def sample(price=.96, won=True):
    row = dict(start=100000,slug='test',side='up')
    record = dict(settlement=dict(status='confirmed',winner='up' if won else 'down'),
        fee=dict(status='known',rate=.07), parsed=dict(rule_type='chainlink_twap'),
        clob=dict(body=dict(minimum_tick_size=.01)),
        up_history=dict(status=200,body=dict(history=[dict(t=100740,p=price)])))
    return row,record


def test_budget_fee_and_settlement_accounting():
    row,record = sample(.96)
    s,reason = scenario(row,record)
    assert reason == 'eligible'
    assert s['shares'] == pytest.approx(20/(.97+.07*.97*.03))
    assert s['pnl'] == pytest.approx(s['shares']-20)
    record['settlement']['winner'] = 'down'
    s,_ = scenario(row,record)
    assert s['pnl'] == -20


def test_stress_retains_original_cohort_and_records_nonfill():
    row,record = sample(.98)
    base,_ = scenario(row,record,.01)
    stress,reason = scenario(row,record,.02)
    assert base['assumed_fill']
    assert reason == 'eligible' and stress['won']
    assert not stress['assumed_fill'] and stress['pnl'] == stress['cost'] == 0
    m = metrics([stress])
    assert m['n'] == m['wins'] == m['nonfills_price_ge_one'] == 1
    assert m['filled_win_rate'] is None


def test_future_reference_never_used_and_unknown_fee_not_scored():
    row,record = sample()
    record['up_history']['body']['history'] = [dict(t=100751,p=.9)]
    assert scenario(row,record)[1] == 'reference_missing_or_stale'
    record['fee']['status'] = 'unknown'
    assert scenario(row,record)[1] == 'fee_unknown'


def test_quote_age_boundary_and_duplicate_conflict():
    row,record = sample()
    record['up_history']['body']['history'] = [dict(t=100675,p=.96)]
    assert scenario(row,record)[1] == 'eligible'
    record['up_history']['body']['history'][0]['t'] -= 1
    assert scenario(row,record)[1] == 'reference_missing_or_stale'
    record['up_history']['body']['history'] = [dict(t=100740,p=.96),dict(t=100740,p=.97)]
    assert scenario(row,record)[1] == 'reference_missing_or_stale'


def test_tick_cap_is_exported_without_replacing_historical_scenario():
    row,record = sample(.955)
    s,_ = scenario(row,record)
    assert s['live_tick_rounded_cap'] == .96
    assert s['assumed_price'] == .965


def test_unconfirmed_label_not_inferred_from_near_one_price():
    row,record = sample(.98)
    record['settlement'] = dict(status='not_final')
    assert scenario(row,record) == (None,'settlement_not_final')


def test_wallet_locks_principal_and_does_not_top_up():
    row,record = sample(.96,False)
    first,_ = scenario(row,record)
    second = deepcopy(first); second['start'] += 900; second['slug'] = 'second'
    assert wallet([first,second],initial=30,delay=1800)['taken'] == 1
    assert wallet([first,second],initial=30,delay=1800)['skipped_for_funds'] == 1
    assert wallet([first],initial=50)['final_cash'] == 30
    assert wallet([first],initial=50)['max_realized_drawdown'] == 20


def test_missing_and_invalid_minutes_not_filled():
    b = dict(code=200,r='1m',c=[dict(t=60000,o=100,h=101,l=99,c=100)])
    assert candle_rows(b,0,180) == [[60,100,101,99,100,0]]
    with pytest.raises(ValueError,match='Duplicate'):
        candle_rows(dict(b,c=b['c']*2),0,180)
    with pytest.raises(ValueError,match='Invalid OHLCV'):
        candle_rows(dict(b,c=[dict(t=60000,o=100,h=98,l=99,c=100)]),0,180)


def test_empty_results_do_not_claim_zero_pnl_or_perfect_winrate():
    assert metrics([])['pnl'] is None
    assert metrics([])['win_rate'] is None
