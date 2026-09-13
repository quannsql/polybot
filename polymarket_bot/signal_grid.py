"""Closed-candle observations shared by research and paper inference.

No exchange calls. Missing candles remain missing; indicators never bridge a gap.
The raw rules reproduce DCA direction triggers, not DCA position management.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def session_mask(times: pd.Series, start: int, end: int) -> pd.Series:
    start, end = start % 24, end % 24
    h = times.dt.hour
    if start == end:
        return pd.Series(True, index=times.index)
    return (h.ge(start) & h.lt(end)) if start < end else (h.ge(start) | h.lt(end))


def features(frame: pd.DataFrame, *, sma_days: int = 25,
             short_depth_pct: float = 1.5, daily_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    f = frame.copy()
    f['timestamp'] = pd.to_datetime(f.timestamp, utc=True)
    if f.timestamp.duplicated().any():
        raise ValueError('Duplicate 5m candles')
    f = f.sort_values('timestamp').set_index('timestamp')
    if f.empty:
        raise ValueError('Empty 5m history')
    if not f.index.equals(f.index.floor('5min')):
        raise ValueError('5m timestamps must be candle-open grid times')
    f = f.reindex(pd.date_range(f.index[0], f.index[-1], freq='5min'))
    f.index.name = 'timestamp'
    valid = (np.isfinite(f[['open', 'high', 'low', 'close', 'volume']]).all(axis=1)
             & f[['open', 'high', 'low', 'close']].gt(0).all(axis=1)
             & f.volume.ge(0) & f.high.ge(f[['open', 'close', 'low']].max(axis=1))
             & f.low.le(f[['open', 'close', 'high']].min(axis=1)))
    f.loc[~valid, ['open', 'high', 'low', 'close', 'volume']] = np.nan
    f['mid5'] = f.close.rolling(20).mean()
    std = f.close.rolling(20).std(ddof=0)
    f['lower5'], f['upper5'] = f.mid5 - 2 * std, f.mid5 + 2 * std
    f['valid5'] = f.close.rolling(30).count().eq(30)
    bars15 = f.resample('15min').agg(close=('close', 'last'), count=('close', 'count'))
    bars15.loc[bars15['count'].ne(3), 'close'] = np.nan
    bars15['close15'] = bars15.close
    bars15['mid15'] = bars15.close.rolling(20).mean()
    bars15['upper15'] = bars15.mid15 + 2 * bars15.close.rolling(20).std(ddof=0)
    bars15['slope15'] = bars15.mid15 - bars15.mid15.shift(4)
    bars15['run60'] = (bars15.close / bars15.close.shift(4) - 1) * 1e4
    bars15['valid15'] = bars15.close.rolling(30).count().eq(30)
    # Shift to availability time, then forward-fill only within the next 15m.
    bars15.index += pd.Timedelta(minutes=15)
    f['decision_at'] = f.index + pd.Timedelta(minutes=5)
    for col in ['close15', 'mid15', 'upper15', 'slope15', 'run60', 'valid15']:
        known = bars15[col].reindex(pd.DatetimeIndex(f.decision_at), method='ffill',
                                   tolerance=pd.Timedelta(minutes=10))
        f[col] = known.to_numpy()
    if daily_frame is None:
        daily = f.resample('1D').agg(close=('close', 'last'), count=('close', 'count'))
        daily.loc[daily['count'].ne(288), 'close'] = np.nan
    else:
        daily = daily_frame.copy()
        daily['timestamp'] = pd.to_datetime(daily.timestamp, utc=True)
        daily = daily.sort_values('timestamp').drop_duplicates('timestamp').set_index('timestamp')
        daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq='1D'))
        daily.loc[~np.isfinite(daily.close) | daily.close.le(0), 'close'] = np.nan
    sma = daily.close.rolling(sma_days).mean()
    route = pd.Series(np.where(daily.close < sma * (1 - short_depth_pct / 100),
                              'short', 'long'), index=daily.index)
    route.loc[sma.isna()] = None
    route.index += pd.Timedelta(days=1)
    f['route'] = f.decision_at.dt.floor('1D').map(route)
    return f.reset_index()


def raw_signals(grid: pd.DataFrame, *, router_enabled: bool = True,
                aux_enabled: bool = True, run_bps: float = 60,
                session_start: int = 8, session_end: int = 22) -> pd.DataFrame:
    f = grid.copy()
    route = f.route if router_enabled else pd.Series('long', index=f.index)
    up = route.eq('long') & f.close.le(f.lower5)
    down = route.eq('short') & f.close.ge(f.upper5)
    aux = (aux_enabled & f.valid15.eq(True) & f.decision_at.dt.minute.mod(15).eq(0)
           & f.close15.ge(f.upper15) & f.run60.ge(run_bps))
    f['source'] = np.where(aux, 'aux_short_15m', 'main_5m')
    f['side'] = np.where(aux | down, 'down', 'up')
    f['route'] = route
    mask = ((up | down | aux) & f.valid5
            & session_mask(f.decision_at, session_start, session_end))
    f = f.loc[mask].copy()
    f['signal_at'] = f.decision_at
    return f


def select_windows(raw: pd.DataFrame, *, policy: str = 'boundary') -> pd.DataFrame:
    """Map observations to known contract starts, never use intra-window future data.

    boundary: fresh observation exactly at T predicts [T,T+15).
    latest_5m: latest observation in (T-15,T] predicts [T,T+15).
    rolling_15m: each 5m observation predicts its next 15m (diagnostic only).
    """
    f = raw.copy()
    if policy == 'boundary':
        f = f.loc[f.signal_at.dt.minute.mod(15).eq(0)].copy()
        f['decision_at'] = f.signal_at
    elif policy == 'latest_5m':
        f['decision_at'] = f.signal_at.dt.ceil('15min')
        f = f.sort_values('signal_at').drop_duplicates('decision_at', keep='last')
    elif policy == 'rolling_15m':
        f['decision_at'] = f.signal_at
    else:
        raise ValueError(f'Unknown policy: {policy}')
    f['signal_age_minutes'] = (f.decision_at - f.signal_at).dt.total_seconds() / 60
    f['end_at'] = f.decision_at + pd.Timedelta(minutes=15)
    return f.sort_values('decision_at').reset_index(drop=True)
