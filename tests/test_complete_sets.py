import pytest
from research_complete_sets import leg_cost


def test_paired_lower_than_one_before_fee_can_lose_after_fees():
    book=dict(asks=[dict(price='.49',size='100')])
    total=2*leg_cost(book,5,.07)
    assert total>5  # .49+.49 looks profitable before fees.


def test_walk_equal_quantity_and_fail_on_missing_depth():
    b=dict(asks=[dict(price='.9',size='2'),dict(price='.8',size='3')])
    assert leg_cost(b,5,0)==pytest.approx(4.2)
    with pytest.raises(ValueError,match='depth'):
        leg_cost(b,6,0)


def test_invalid_asks_fail_closed():
    with pytest.raises(ValueError):
        leg_cost(dict(asks=[dict(price='1.1',size=10)]),5,.07)
