import pytest
from research_late_entry_payoff import payoff


def test_cash_inclusive_profit_loss_and_nonfill():
    fee = {'status': 'known', 'rate': .07}
    win = payoff(.85, fee, True)
    loss = payoff(.85, fee, False)
    expected_cost = .86 + .07*.86*.14
    assert win['shares'] == pytest.approx(30/expected_cost)
    assert win['pnl'] == pytest.approx(30/expected_cost-30)
    assert loss['pnl'] == -30
    assert payoff(.99, fee, True) is None
    assert payoff(.98, fee, False, .03) is None
    assert payoff(.85, fee, True, .03)['pnl'] < win['pnl']
