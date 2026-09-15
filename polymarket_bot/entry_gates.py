"""Frozen strong gate: causal inputs only, no outcome/settlement access."""
from types import SimpleNamespace
import math
import numpy as np
import pandas as pd
from .dca_gate_helpers import market_features, memory_rsi_blocks, auxiliary_short_shock_blocks
from .lighter_paper_feed import aggregate_minutes
from .signal_grid import features as signal_features

PROFILE = 'q1.5_z1.25_memory_old_signal_aux_shock'
PROFILE_B = PROFILE + '_slope15_z0.75'
SUPPORTED_PROFILES = frozenset((PROFILE, PROFILE_B))


def decide(inputs, *, profile=PROFILE):
    if profile not in SUPPORTED_PROFILES:
        raise ValueError('Unknown entry gate profile')
    vol, z = inputs['vol'], inputs['z']
    if vol is None or not math.isfinite(vol) or vol > 1.5:
        return False, 'volatility_ratio'
    if inputs['aux_shock']:
        return False, 'aux_shock'
    if inputs['memory'] or inputs['old_signal']:
        if z is None or not math.isfinite(z) or z < 1.25:
            return False, 'memory_or_old_signal_weak_lead'
    if profile == PROFILE_B and not inputs['slope15_agrees']:
        if z is None or not math.isfinite(z) or z < .75:
            return False, 'against_slope15_weak_lead'
    return True, 'variant_b_passed' if profile == PROFILE_B else 'strong_gate_passed'


def evaluate(own_minutes, peer_minutes, *, start, signal_at, side, source, profile=PROFILE):
    if profile not in SUPPORTED_PROFILES:
        raise ValueError('Unknown entry gate profile')
    start, signal_at = pd.Timestamp(start), pd.Timestamp(signal_at)
    age = (start-signal_at).total_seconds()/60
    if age not in (0, 5, 10) or side not in ('up', 'down') or source not in ('main_5m', 'aux_short_15m'):
        raise ValueError('Invalid original DCA signal identity')
    known = start+pd.Timedelta(minutes=12)
    def closed(frame):
        frame = frame.copy()
        frame['timestamp'] = pd.to_datetime(frame.timestamp, utc=True)
        frame = frame.loc[frame.timestamp < known].sort_values('timestamp')
        if frame.timestamp.duplicated().any():
            raise ValueError('Duplicate gate minutes')
        return frame
    own, peer = closed(own_minutes), closed(peer_minutes)
    own5, _ = aggregate_minutes(own, known)
    peer5, _ = aggregate_minutes(peer, known)
    minute = own.set_index('timestamp').reindex(pd.date_range(known-pd.Timedelta(minutes=61), known-pd.Timedelta(minutes=1), freq='min'))
    r = np.log(minute.close/minute.close.shift())
    vol = r.tail(5).std(ddof=0)/r.tail(60).std(ddof=0) if r.tail(60).notna().all() else np.nan
    sigma = r.tail(30).std(ddof=0) if r.tail(30).notna().all() else np.nan
    opening = minute.open.get(start, np.nan)
    lead = (1 if side == 'up' else -1)*np.log(minute.close.iloc[-1]/opening)
    z = lead/(sigma*math.sqrt(3)) if sigma > 0 and minute.loc[start:, 'close'].notna().all() else np.nan
    memory, memory_reason = (False, 'not_applicable')
    shock, shock_reason = (False, 'not_applicable')
    if source == 'main_5m':
        memory, memory_reason = memory_rsi_blocks(market_features(
            own5, peer5, expected_closed_at=signal_at, peer_bars=36),
            side='long' if side == 'up' else 'short')
    else:
        shock, shock_reason = auxiliary_short_shock_blocks(own5, peer5,
            SimpleNamespace(aux_shock_enabled=True, aux_shock_minutes=120),
            coin='BTC', expected_closed_at=start+pd.Timedelta(minutes=10))
    number = lambda v: float(v) if np.isfinite(v) else None
    inputs = dict(vol=number(vol), z=number(z), memory=bool(memory),
                  old_signal=age>=10, aux_shock=bool(shock))
    if profile == PROFILE_B:
        # Same availability grid as research: completed 5m at T+10, and
        # completed 15m only. Never include the forming 15m candle.
        band = signal_features(own5).set_index('decision_at').reindex(
            [start + pd.Timedelta(minutes=10)]).iloc[0]
        inputs['slope15_agrees'] = bool(
            band.valid15 == True and (1 if side == 'up' else -1) * band.slope15 > 0)
        inputs['slope15'] = number(band.slope15)
        inputs['slope15_valid'] = bool(band.valid15 == True)
    keep, reason = decide(inputs, profile=profile)
    return dict(profile=profile, keep=keep, reason=reason, inputs=inputs,
                feature_at=known.isoformat(), signal_at=signal_at.isoformat(), signal_age_minutes=age,
                memory_diagnostic=memory_reason, aux_shock_diagnostic=shock_reason,
                missing_history_policy='Bot1 helper diagnostics preserved; transport errors block runtime entry')
