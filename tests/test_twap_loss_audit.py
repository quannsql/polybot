from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from research_twap_loss_audit import (
    BidIndex, Confirmation, context, entry_keep, exit_alert, exit_summary,
    observed_exit, quote_coverage, sale_pnl,
)
from research_twap_stability import FIT, TwapIndex


def streams():
    seconds = np.arange(902)
    frame = pd.DataFrame(dict(observed_ms=(FIT + seconds) * 1000,
        received_ms=(FIT + seconds + 1) * 1000, value=100000 + seconds * .1))
    raw = frame.copy()
    raw.received_ms += 1000
    raw.value += 10
    return frame, raw


def test_entry_context_ignores_future_and_not_yet_received_prices():
    frame, raw = streams()
    before, _ = context(TwapIndex(frame), TwapIndex(raw), FIT, 840, 'up')
    assert before['twap_observed_ms'] == (FIT + 839) * 1000
    assert before['spot_observed_ms'] == (FIT + 838) * 1000
    frame.loc[frame.observed_ms.ge((FIT + 840) * 1000), 'value'] = 1
    raw.loc[raw.observed_ms.ge((FIT + 839) * 1000), 'value'] = 1000000
    after, _ = context(TwapIndex(frame), TwapIndex(raw), FIT, 840, 'up')
    assert before == after


def test_direction_sign_changes_warning_without_changing_price_source():
    frame, raw = streams()
    up, _ = context(TwapIndex(frame), TwapIndex(raw), FIT, 840, 'up')
    down, _ = context(TwapIndex(frame), TwapIndex(raw), FIT, 840, 'down')
    assert up['lead_bps'] == pytest.approx(-down['lead_bps'])
    assert up['spot_lead_bps'] == pytest.approx(-down['spot_lead_bps'])
    assert up['momentum30_bps'] == pytest.approx(-down['momentum30_bps'])


def test_missing_feature_is_unavailable_not_a_pass():
    values = dict(spot_lead_bps=None, momentum30_bps=2)
    assert entry_keep('spot_on_side_and_momentum30', values) is None
    assert entry_keep('baseline', None) is True


def test_confirmation_needs_distinct_observations():
    confirm = Confirmation()
    assert not confirm.update(True, 1000)
    assert not confirm.update(True, 1000)
    assert not confirm.update(True, 2000)
    assert confirm.update(True, 3000)


def test_confirmation_resets_on_missing_false_or_large_gap():
    confirm = Confirmation()
    for condition, time in [(True, 1000), (True, 2000), (None, None),
                            (True, 3000), (False, 4000), (True, 5000), (True, 12000)]:
        assert not confirm.update(condition, time)
    assert not confirm.update(True, 13000)
    assert confirm.update(True, 14000)


def test_exit_alert_is_not_selected_by_eventual_outcome():
    points = [dict(lead_bps=value, twap_observed_ms=i * 1000,
                   clock_ms=(FIT + 840 + i) * 1000, delay=840 + i)
              for i, value in enumerate((9, 3, 2, 1), 1)]
    first = exit_alert('twap_half_entry_lead', dict(lead_bps=10), points)
    other = deepcopy(points)
    for point in other:
        point['eventual_winner'] = 'up'
    second = exit_alert('twap_half_entry_lead', dict(lead_bps=10), other)
    assert {k: v for k, v in second.items() if k != 'values'} == {k: v for k, v in first.items() if k != 'values'}
    assert first['delay'] == 844


def bid_fixture(after=200, size=np.nan):
    now = (FIT + 850) * 1000
    rows = [dict(start=FIT, side='up', captured_ms=now + offset, bid=bid,
                 ask=.98, bid_size=size, source='test', priority=0)
            for offset, bid in ((-1000, .9), (after, .8))]
    return BidIndex(pd.DataFrame(rows)), dict(start=FIT, side='up', unit_cost=.95), dict(signal_ms=now)


def test_exit_never_uses_next_future_quote_or_assumes_old_book_persisted():
    bids, trade, alert = bid_fixture(after=800)
    assert observed_exit(trade, alert, bids, .07, latency=500)['status'] == 'no_new_snapshot_during_latency'
    assert observed_exit(trade, alert, bids, .07, latency=1000)['bid'] == .8


def test_missing_bid_depth_remains_unknown_even_with_an_observed_price():
    bids, trade, alert = bid_fixture()
    result = observed_exit(trade, alert, bids, .07)
    assert result['status'] == 'indicative_bid_only'
    assert result['capacity'] == 'unknown_bid_size'
    assert result['quote']['bid_size'] is None
    assert result['certified_fill'] is False


def test_quote_that_triggers_price_stop_is_not_assumed_still_available_at_arrival():
    bids, trade, alert = bid_fixture(after=0)
    assert observed_exit(trade, alert, bids, .07)['status'] == 'no_new_snapshot_during_latency'


def test_no_book_does_not_mean_no_price_stop():
    bids, trade, _ = bid_fixture()
    trade.update(start=FIT + 900, decision_seconds=FIT + 900 + 840)
    coverage = quote_coverage(trade, bids)
    assert coverage['valid_captures'] == 0
    assert coverage['continuously_observed_under_1p5s_gap'] is False


def test_exit_does_not_fill_after_market_close():
    bids, trade, alert = bid_fixture()
    alert['signal_ms'] = (FIT + 900) * 1000 - 100
    assert observed_exit(trade, alert, bids, .07)['status'] == 'arrival_after_close'


def test_round_trip_includes_entry_cost_sell_fee_and_exit_overhead():
    cost = .95 + .07 * .95 * .05
    result = sale_pnl(dict(unit_cost=cost), .8, .07, .01)
    assert result == pytest.approx(20 / cost * (.8 - .07 * .8 * .2) - 20 - .01)


def test_missing_exit_book_is_unknown_not_a_successful_stop_at_trigger_price():
    bids, trade, alert = bid_fixture()
    trade.update(start=FIT + 900, won=False)
    report = exit_summary([trade], {trade['start']: alert}, bids,
                          {trade['start']: dict(fee=dict(rate=.07))})
    assert report['exit_statuses'] == {'no_market_book': 1}
    assert report['certified_week_exit_pnl'] is None
    assert report['covered_quote_and_unobserved_sale_bounds'][0] == pytest.approx(-20.01)


def test_sale_arriving_after_close_preserves_settlement_instead_of_inventing_a_fill():
    bids, trade, alert = bid_fixture()
    trade['won'] = True
    alert['signal_ms'] = (FIT + 900) * 1000 - 100
    report = exit_summary([trade], {FIT: alert}, bids, {FIT: dict(fee=dict(rate=.07))})
    hold = 20 / trade['unit_cost'] - 20
    assert report['covered_quote_and_unobserved_sale_bounds'] == pytest.approx([hold, hold])
    assert all(value == pytest.approx(hold) for value in report['hypothetical_constant_bid_week_pnl'].values())
