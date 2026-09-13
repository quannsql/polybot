"""Paper inference from the same closed-candle grid as the audited backtest."""
from __future__ import annotations

from datetime import datetime
import math
import pandas as pd
from .models import SignalSnapshot
from .signal_grid import features, raw_signals, select_windows
from .signal_grid import session_mask


def snapshot(frame_5m: pd.DataFrame, *, decision_at: datetime | pd.Timestamp,
             sma_days: int = 25, short_depth_pct: float = 1.5,
             short_lane_run_bps: float = 60.0,
             session_start_utc: int = 0, session_end_utc: int = 0,
             daily_frame: pd.DataFrame | None = None,
             policy: str = "boundary", router_enabled: bool = True,
             aux_enabled: bool = True) -> SignalSnapshot:
    at = pd.Timestamp(decision_at)
    at = at.tz_localize("UTC") if at.tzinfo is None else at.tz_convert("UTC")
    if at != at.floor("15min"):
        raise ValueError("Prediction time must be a 15m market boundary")
    if policy not in {"boundary", "latest_5m"}:
        raise ValueError("Paper inference requires fixed Polymarket windows")
    f = frame_5m.copy()
    f["timestamp"] = pd.to_datetime(f["timestamp"], utc=True)
    f = f.loc[f.timestamp + pd.Timedelta(minutes=5) <= at]
    def empty(reason):
        return SignalSnapshot(at.to_pydatetime(), None, None, None, 0.,
                              None, None, None, None, None, None, reason)
    if not bool(session_mask(pd.Series([at]),session_start_utc,session_end_utc).iloc[0]):
        return empty('outside_session')
    if f.empty or f.timestamp.max() + pd.Timedelta(minutes=5) != at:
        return empty("latest_closed_5m_not_at_boundary")
    grid = features(f, sma_days=sma_days, short_depth_pct=short_depth_pct,
                    daily_frame=daily_frame)
    current = grid.iloc[-1]
    if not bool(current.valid5):
        return empty("5m_history_missing_or_irregular")
    candidates = select_windows(raw_signals(grid, router_enabled=router_enabled,
        aux_enabled=aux_enabled, run_bps=short_lane_run_bps,
        session_start=session_start_utc, session_end=session_end_utc), policy=policy)
    selected = candidates.loc[candidates.decision_at.eq(at)]
    row = selected.iloc[-1] if len(selected) else current
    def num(key):
        value = row[key]
        return float(value) if pd.notna(value) and math.isfinite(float(value)) else None
    route = row.route if pd.notna(row.route) else None
    if selected.empty:
        direction, source, strength, reason = None, None, 0., "no_signal"
    else:
        direction, source = row.side, row.source
        strength = 1. if source == "aux_short_15m" else .75
        reason = ("15m_upper_band_and_60m_pump" if source == "aux_short_15m"
                  else "route_long_5m_lower_band" if direction == "up"
                  else "route_short_5m_upper_band")
        if policy == 'latest_5m':
            reason += f";signal_at={row.signal_at.isoformat()};age_min={row.signal_age_minutes:g}"
    return SignalSnapshot(at.to_pydatetime(), route, direction, source, strength,
                          num("close"), num("lower5"), num("upper5"), num("close15"),
                          num("upper15"), num("run60"), reason)
