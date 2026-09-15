import math
from polymarket_bot.entry_gates import decide
import numpy as np
import pandas as pd
import pytest
from polymarket_bot.entry_gates import PROFILE_B, evaluate


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


def test_b_is_additive_and_conditional_including_boundary_and_missing_data():
    base = dict(vol=1., z=.75, memory=False, old_signal=False, aux_shock=False,
                slope15_agrees=False)
    assert decide(base, profile=PROFILE_B)[0]
    for z in (.749999, None, math.nan):
        assert not decide(base | {'z': z}, profile=PROFILE_B)[0]
    assert decide(base | {'z': -.1, 'slope15_agrees': True}, profile=PROFILE_B)[0]
    for overrides in ({'vol': 1.6}, {'aux_shock': True}, {'memory': True}, {'old_signal': True}):
        assert not decide(base | overrides, profile=PROFILE_B)[0]
    with pytest.raises(ValueError):
        decide(base, profile='unknown')


def test_production_b_ignores_forming_minutes_and_unclosed_15m():
    times = pd.date_range('2026-06-01', periods=4*1440+30, freq='min', tz='UTC')
    p = 100 + np.sin(np.arange(len(times))/97)
    frame = pd.DataFrame(dict(timestamp=times, open=p, high=p+.1, low=p-.1, close=p, volume=1.))
    start = times[4*1440]
    kwargs = dict(start=start, signal_at=start, side='down', source='aux_short_15m', profile=PROFILE_B)
    before = evaluate(frame, frame, **kwargs)
    changed = frame.copy()
    changed.loc[changed.timestamp >= start+pd.Timedelta(minutes=12), ['open','high','low','close']] *= 10
    assert evaluate(changed, changed, **kwargs) == before
    changed = frame.copy()
    changed.loc[changed.timestamp >= start, ['open','high','low','close']] *= 2
    after = evaluate(changed, changed, **kwargs)
    assert after['inputs']['slope15'] == before['inputs']['slope15']
    assert after['inputs']['slope15_agrees'] == before['inputs']['slope15_agrees']
