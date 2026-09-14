"""Pure gate helpers vendored from Bot1; no venue operations.
Source: band_dca_lane.py and band_dca_market.py, 2026-09-14.
Historical missing-input diagnostics intentionally preserved.
"""
from __future__ import annotations
from types import SimpleNamespace
import numpy as np
import pandas as pd

def _normalize_5m_gate_frame(
    frame: pd.DataFrame | None,
    *,
    required: set[str],
    expected_closed_at: pd.Timestamp | None = None,
    history_bars: int | None = None,
) -> pd.DataFrame | None:
    """Return a causal, regular 5m frame for an entry gate.

    Venue adapters label candles by their *open* timestamp.  The bot supplies
    the closed timestamp of the signal candle, so a gate must use the row whose
    open is exactly five minutes before that stamp.  A newer row is discarded
    (it can be the candle that is still forming at a polling boundary); a
    missing/stale row fails open instead of making a decision on an old candle.
    A gap is also rejected because the research rules are row based and would
    otherwise mistake, for example, ten rows for fifty minutes.
    """
    if frame is None or not required.issubset(frame.columns):
        return None
    try:
        columns = sorted(required)
        f = frame[columns].copy()
        f["timestamp"] = pd.to_datetime(f["timestamp"], utc=True)
        for column in required - {"timestamp"}:
            f[column] = pd.to_numeric(f[column], errors="coerce")
        f = (f.dropna()
               .drop_duplicates("timestamp")
               .sort_values("timestamp")
               .reset_index(drop=True))
        if len(f) < 2:
            return None
        if expected_closed_at is not None:
            stamp = pd.Timestamp(expected_closed_at)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            else:
                stamp = stamp.tz_convert("UTC")
            expected_open = stamp - pd.Timedelta(minutes=5)
            f = f[f["timestamp"] <= expected_open].reset_index(drop=True)
            if f.empty or f["timestamp"].iloc[-1] != expected_open:
                return None
        # Sharing a venue snapshot must not extend one gate's data-validity
        # window to another gate's longer lookback. Validate only closed rows
        # in this gate's configured window.
        if history_bars is not None:
            f = f.tail(history_bars).reset_index(drop=True)
        gaps = f["timestamp"].diff().dropna()
        if (gaps != pd.Timedelta(minutes=5)).any():
            return None
        return f
    except (KeyError, TypeError, ValueError, IndexError):
        return None



def market_features(frame: pd.DataFrame | None, peer_frame: pd.DataFrame | None,
                    *, expected_closed_at: pd.Timestamp,
                    peer_bars: int = 13) -> pd.DataFrame | None:
    """DI/ADX/RSI14 from 720 closed 5m bars, indexed by knowledge time.

    Peer needs 13 closes for current 1h return, or 36 for every seed in
    (t-120m, t]. Incomplete 15m groups never contribute to an indicator.
    """
    own = _normalize_5m_gate_frame(
        frame, required={"timestamp", "open", "high", "low", "close"},
        history_bars=720, expected_closed_at=expected_closed_at)
    peer = _normalize_5m_gate_frame(
        peer_frame, required={"timestamp", "close"}, history_bars=peer_bars,
        expected_closed_at=expected_closed_at)
    if own is None or peer is None or len(own) < 720 or len(peer) < peer_bars:
        return None
    if not own.timestamp.tail(peer_bars).reset_index(drop=True).eq(peer.timestamp).all():
        return None
    prices = own[["open", "high", "low", "close"]]
    if (not np.isfinite(prices.to_numpy(float)).all()
            or not np.isfinite(peer.close.to_numpy(float)).all()
            or (prices <= 0).any().any() or (peer.close <= 0).any()
            or (own.high < prices.max(axis=1)).any()
            or (own.low > prices.min(axis=1)).any()):
        return None
    grouped = own.set_index("timestamp").resample("15min")
    bars = grouped.agg({"high": "max", "low": "min", "close": "last"})
    bars = bars.loc[grouped.close.count().eq(3)]
    high, low, close = bars.high, bars.low, bars.close
    tr = pd.concat([high-low, (high-close.shift()).abs(),
                    (low-close.shift()).abs()], axis=1).max(axis=1)
    up, down = high.diff(), -low.diff()
    def smooth(values: pd.Series) -> pd.Series:
        return values.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    plus = 100*smooth(up.where((up>down)&(up>0), 0.))/smooth(tr).replace(0, np.nan)
    minus = 100*smooth(down.where((down>up)&(down>0), 0.))/smooth(tr).replace(0, np.nan)
    adx = smooth(100*(plus-minus).abs()/(plus+minus).replace(0, np.nan))
    change = close.diff()
    gain, loss = smooth(change.clip(lower=0)), smooth((-change).clip(lower=0))
    rsi = 100*gain/(gain+loss).replace(0, np.nan)
    indicators = pd.DataFrame(dict(di=plus-minus, adx=adx, rsi=rsi))
    indicators.index += pd.Timedelta(minutes=15)
    known = pd.DatetimeIndex(own.timestamp) + pd.Timedelta(minutes=5)
    result = indicators.reindex(known, method="ffill")
    result["rsi_change30"] = result.rsi-result.rsi.shift(6)
    peer_close = peer.set_index("timestamp").close
    peer_return = (peer_close/peer_close.shift(12)-1)*1e4
    peer_return.index += pd.Timedelta(minutes=5)
    result["peer_return"] = peer_return.reindex(known)
    return result


def memory_rsi_blocks(features: pd.DataFrame | None, *, side: Side
                      ) -> tuple[bool, str | None]:
    """Keep the original seed; RSI only qualifies the additional memory veto."""
    if features is None:
        return False, "entry_memory_rsi_history_unavailable"
    window = features.tail(24)  # 115m ago through now; exactly t-120m excluded.
    if len(window) < 24 or not np.isfinite(window[["adx", "di", "peer_return"]]).all().all():
        return False, "entry_memory_rsi_indicator_unavailable"
    sign = 1 if side == "long" else -1
    seed = (window.adx<25)&(-sign*window.di>=5)&(-sign*window.peer_return>=30)
    current = window.iloc[-1]
    # Do not let an RSI recovery bypass the original EARLY_DIRECTION seed.
    if seed.iloc[-1]:
        return True, "entry_memory_rsi_original_seed"
    if not np.isfinite(current.rsi):
        return False, "entry_memory_rsi_indicator_unavailable"
    adverse_di = -sign*current.di
    adverse_rsi = -sign*(current.rsi-50)
    if seed.any() and adverse_di >= (5 if side == "long" else 0) and adverse_rsi >= 0:
        return True, "entry_memory_rsi[%s;120m;DI=%.2f;RSI=%.2f]" % (
            side, adverse_di, current.rsi)
    return False, None



def auxiliary_short_shock_blocks(
    frame: pd.DataFrame | None,
    peer_frame: pd.DataFrame | None,
    config: BandDcaConfig,
    *,
    coin: str,
    expected_closed_at: pd.Timestamp,
) -> tuple[bool, str | None]:
    """Own rising shock, plus BTC's shock for ETH; closed 5m inputs only.

    Reconstruct state from 720 closed candles on each decision, including after
    restart. Like the existing optional entry gates, unavailable data fails
    open with a diagnostic; it never interferes with open-position management.
    The research threshold is fixed at 3 ATR, with midpoint reclaim.
    """
    if not config.aux_shock_enabled:
        return False, None
    if coin not in ("BTC", "ETH"):
        return False, "aux_shock_unsupported_coin"
    required = {"timestamp", "open", "high", "low", "close"}
    frames = [_normalize_5m_gate_frame(
        x, required=required, expected_closed_at=expected_closed_at,
        history_bars=720) for x in (frame, peer_frame)]
    if any(x is None or len(x) < 720 for x in frames):
        return False, "aux_shock_history_unavailable"
    own, peer = [x.set_index("timestamp") for x in frames]
    if not own.index.equals(peer.index):
        return False, "aux_shock_history_unaligned"
    for f in (own, peer):
        if (not np.isfinite(f.to_numpy(float)).all()
                or (f <= 0).any().any()
                or (f.high < f[["open", "close", "low"]].max(axis=1)).any()
                or (f.low > f[["open", "close", "high"]].min(axis=1)).any()):
            return False, "aux_shock_history_invalid"

    def active(f: pd.DataFrame, other: pd.DataFrame) -> bool:
        c = f.close
        tr = pd.concat([f.high - f.low, (f.high - c.shift()).abs(),
                        (f.low - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        trigger = (((c - f.open) / atr.shift() >= 3.0)
                   & (c > f.high.shift().rolling(12).max())
                   & (other.close > other.close.shift(12))).to_numpy(bool)
        level = np.nan
        expires = -1
        # Open stamps differ from close stamps by a constant 5 minutes;
        # elapsed time and exact expiry comparisons are therefore identical.
        for stamp, price, open_, shock in zip(
                f.index.as_unit("ns").asi8, c.to_numpy(),
                f.open.to_numpy(), trigger):
            if expires >= 0 and (stamp >= expires or price <= level):
                expires = -1
                level = np.nan
            if shock:
                midpoint = (price + open_) / 2.0
                level = midpoint if expires < 0 else min(level, midpoint)
                expires = stamp + config.aux_shock_minutes * 60_000_000_000
        return bool(expires >= 0)

    reasons = []
    if active(own, peer):
        reasons.append(coin)
    if coin == "ETH" and active(peer, own):
        reasons.append("BTC")
    if reasons:
        return True, "aux_shock[%s;%dm]" % ("+".join(reasons), config.aux_shock_minutes)
    return False, None



