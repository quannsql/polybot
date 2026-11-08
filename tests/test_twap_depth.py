from copy import deepcopy
import pandas as pd
import pytest

from research_twap_depth import QuoteIndex,candidate,top_fill
from research_twap_stability import FIT


def fixture(after_price=.95,after_size=100,refresh=True):
    now=(FIT+840)*1000
    rows=[dict(start=FIT,side='up',captured_ms=now-1000,bid=.94,ask=.95,ask_size=100,source='test',priority=0)]
    if refresh:
        rows.append(dict(start=FIT,side='up',captured_ms=now+200,bid=.94,ask=after_price,ask_size=after_size,source='test',priority=0))
    return QuoteIndex(pd.DataFrame(rows)),dict(start=FIT,delay=840,side='up',lead_bps=12),dict(
        settlement=dict(status='confirmed',winner='up'),fee=dict(status='known',rate=.07))


def test_quote_index_never_uses_a_future_snapshot():
    q,_,_=fixture(); now=(FIT+840)*1000
    before,_=q.at(FIT,'up',now)
    assert before['captured_ms']==now-1000
    assert q.at(FIT,'up',now+5000)[1]=='capture_too_old'


def test_capacity_needs_arrival_refresh_not_old_book_assumed_still_there():
    q,f,r=fixture(refresh=False)
    assert candidate(f,r,q,10)[1]=='no_arrival_refresh_observation'


def test_price_cap_frozen_before_arrival_and_never_chased():
    q,f,r=fixture(after_price=.96)
    assert candidate(f,r,q,10)[1]=='arrival_ask_above_frozen_cap'


def test_haircut_depth_must_cover_all_requested_shares():
    q,f,r=fixture(after_size=20)
    assert candidate(f,r,q,10,haircut=.5)[1]=='insufficient_top_depth'
    assert candidate(f,r,q,10,haircut=1)[1]=='captured_depth_scenario'


def test_cash_cap_and_shares_rounding():
    fill=top_fill(dict(ask=.95,ask_size=100),dict(rate=.07),15,.5)
    assert 0<fill['charged_cost']<=15
    assert fill['shares']==pytest.approx(round(fill['shares'],4))
    assert fill['shares']>15  # winning payout, not a calibrated probability.


def test_winner_only_changes_scoring_not_entry_or_depth():
    q,f,r=fixture(); before,_=candidate(f,r,q,10)
    other=deepcopy(r); other['settlement']['winner']='down'
    after,_=candidate(f,other,q,10)
    assert after['shares']==before['shares'] and after['cap']==before['cap']
    assert not after['won']


def test_clock_shift_remains_causal_under_its_explicit_assumption():
    q,_,_=fixture(); now=(FIT+840)*1000
    quote,_=q.at(FIT,'up',now,clock_shift=-1000)
    assert quote['available_ms']<=now
    assert quote['captured_ms']==now+200  # clock sensitivity, not baseline UTC claim.


@pytest.mark.parametrize('price',[.995,.999])
def test_accepting_tiny_profit_changes_price_capacity_not_certainty(price):
    from research_twap_price_ceiling import acquire
    now=(FIT+840)*1000
    frame=pd.DataFrame([dict(start=FIT,side='up',captured_ms=now+t,bid=price-.001,
        ask=price,ask_size=100,source='test',priority=0) for t in (-1000,200)])
    quotes=QuoteIndex(frame)
    f=dict(start=FIT,delay=840,side='up',lead_bps=12)
    r=dict(settlement=dict(status='confirmed',winner='down'),fee=dict(status='known',rate=.07))
    assert acquire(f,r,quotes,10,.99,.01)[1]=='price_outside_range'
    row,reason=acquire(f,r,quotes,10,price,.01)
    assert reason=='captured_quote_scenario' and not row['won']
    assert row['winning_pnl_reserved']>=.01  # Potential win profit does not prevent the loss.
