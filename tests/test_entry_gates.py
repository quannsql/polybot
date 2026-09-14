import math
from polymarket_bot.entry_gates import decide


def test_frozen_strong_gate_truth_table():
    base = dict(vol=1.0, z=0.0, memory=False, old_signal=False, aux_shock=False)
    assert decide(base)[0]
    assert not decide(base | {'vol': 1.50001})[0]
    assert not decide(base | {'vol': math.nan})[0]
    assert not decide(base | {'aux_shock': True, 'z': 10})[0]
    assert not decide(base | {'memory': True, 'z': 1.24999})[0]
    assert decide(base | {'memory': True, 'z': 1.25})[0]
    assert not decide(base | {'old_signal': True, 'z': None})[0]
    assert decide(base | {'old_signal': True, 'z': 1.25})[0]
