"""Original late-entry eligibility, separate from execution feasibility."""
from decimal import ROUND_DOWN

from .actual_research import dec, history_asof
from .robustness import quote


def legacy_reference(history, due_seconds, protocol):
    reference = history_asof(history, due_seconds, protocol['reference_max_age_seconds'])
    if reference is None:
        raise ValueError('legacy_reference_missing_or_stale')
    if dec(reference['price']) < dec(protocol['minimum_reference']):
        raise ValueError('legacy_reference_below_085')
    if dec(reference['price']) + dec(protocol['price_padding']) >= 1:
        raise ValueError('legacy_reference_plus_1c_not_below_one')
    return reference


def legacy_intent(side, books, reference, now_ms, protocol):
    """Do NOT filter on ask or replace the frozen reference with a midpoint."""
    if side not in books:
        raise ValueError('no_signal_or_book')
    book = books[side]
    ask, _ = quote(book, now_ms, protocol)
    tick = dec(book['tick_size'])  # Missing live tick is not guessed.
    if not 0 < tick < 1:
        raise ValueError('invalid_tick')
    assumed_price = dec(reference['price']) + dec(protocol['price_padding'])
    if not 0 < assumed_price < 1:
        raise ValueError('invalid_reference_limit')
    cap = (assumed_price/tick).to_integral_value(rounding=ROUND_DOWN)*tick
    return {'side': side, 'ask': str(ask), 'cap': str(cap),
            'reference': reference, 'decision_ms': now_ms,
            'execution_assumption': 'FOK-like shadow, limit <= old assumed reference+1c'}
