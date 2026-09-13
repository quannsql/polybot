"""Causal sanity check for mapping Band-DCA signals to BTC 15-minute outcomes.

This is intentionally a direction study, not a Polymarket PnL backtest.  It
uses Lighter one-minute prices as a proxy for the market's Chainlink 60-second
TWAP resolution feed and does not have historical Polymarket order books,
spreads, fills, or fees.

The decision is made exactly on a 15-minute boundary.  All indicator inputs
end at that boundary and the proxy outcome is measured over the next 15
minutes, preventing the common look-ahead error of using the candle being
predicted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def load_bars(path: Path, frequency: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    expected = pd.date_range(frame.timestamp.iloc[0], frame.timestamp.iloc[-1], freq=frequency)
    if len(expected) != len(frame) or not frame.timestamp.reset_index(drop=True).equals(
        pd.Series(expected, name="timestamp")
    ):
        raise ValueError(f"{path} is not a continuous {frequency} series")
    return frame.reset_index(drop=True)


def add_bollinger(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    middle = result.close.rolling(20, min_periods=20).mean()
    sigma = result.close.rolling(20, min_periods=20).std(ddof=0)
    result["bb_lower"] = middle - 2.0 * sigma
    result["bb_upper"] = middle + 2.0 * sigma
    result["closed_at"] = result.timestamp + pd.Timedelta(minutes=5)
    return result


def add_daily_route(frame: pd.DataFrame) -> pd.DataFrame:
    # Matches band_dca_lane.daily_route(): day D sees only fully closed D-1,
    # and chooses SHORT only when D-1 close is more than 1.5% below SMA25.
    daily = frame.set_index("timestamp").close.resample("1D").last().dropna()
    route = pd.DataFrame({"previous_close": daily})
    route["sma25"] = route.previous_close.rolling(25, min_periods=25).mean()
    route["route"] = np.where(
        route.previous_close < route.sma25 * (1.0 - 0.015), "short", "long"
    )
    route.loc[route.sma25.isna(), 'route'] = None
    route.index = route.index + pd.Timedelta(days=1)
    result = frame.copy()
    result["trading_day"] = result.closed_at.dt.floor("1D")
    return result.merge(route[["route"]], left_on="trading_day", right_index=True, how="left")


def build_main_signals(frame_5m: pd.DataFrame) -> pd.DataFrame:
    frame = add_daily_route(add_bollinger(frame_5m))
    at_boundary = frame.closed_at.dt.minute.mod(15).eq(0)
    in_session = frame.closed_at.dt.hour.ge(8) & frame.closed_at.dt.hour.lt(22)
    long_signal = frame.route.eq("long") & frame.close.le(frame.bb_lower)
    short_signal = frame.route.eq("short") & frame.close.ge(frame.bb_upper)
    signals = frame.loc[at_boundary & in_session & (long_signal | short_signal)].copy()
    signals["source"] = "main_5m"
    signals["side"] = np.where(long_signal.loc[signals.index], "up", "down")
    signals["decision_at"] = signals.closed_at
    return signals[["decision_at", "source", "side", "close", "bb_lower", "bb_upper"]]


def build_aux_signals(frame_5m: pd.DataFrame) -> pd.DataFrame:
    indexed = frame_5m.set_index("timestamp")
    grouped = indexed.resample("15min", label="left", closed="left")
    bars = grouped.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), count=("close", "count"),
    )
    bars = bars.loc[bars["count"].eq(3)].drop(columns="count")
    middle = bars.close.rolling(20, min_periods=20).mean()
    sigma = bars.close.rolling(20, min_periods=20).std(ddof=0)
    bars["bb_upper"] = middle + 2.0 * sigma
    bars["bb_lower"] = middle - 2.0 * sigma
    bars["closed_at"] = bars.index + pd.Timedelta(minutes=15)
    bars["run_bps"] = (bars.close / bars.close.shift(4) - 1.0) * 1e4
    in_session = bars.closed_at.dt.hour.ge(8) & bars.closed_at.dt.hour.lt(22)
    signal = bars.close.ge(bars.bb_upper) & bars.run_bps.ge(60.0)
    result = bars.loc[in_session & signal].copy()
    result["source"] = "aux_short_15m"
    result["side"] = "down"
    result["decision_at"] = result.closed_at
    return result[["decision_at", "source", "side", "close", "bb_lower", "bb_upper", "run_bps"]]


def proxy_outcomes(frame_1m: pd.DataFrame) -> pd.DataFrame:
    bars = frame_1m.copy().set_index("timestamp")
    grouped = bars.resample("15min", label="left", closed="left")
    outcomes = grouped.agg(
        price_to_beat=("open", "first"), end_price=("close", "last"),
        minute_count=("close", "count"),
    )
    outcomes = outcomes.loc[outcomes.minute_count.eq(15)].copy()
    outcomes["up_won"] = outcomes.end_price.ge(outcomes.price_to_beat)
    outcomes.index.name = "decision_at"
    return outcomes


def score(signals: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    joined = signals.merge(outcomes, left_on="decision_at", right_index=True, how="inner")
    joined["correct"] = joined.side.eq(np.where(joined.up_won, "up", "down"))

    def metrics(group: pd.DataFrame) -> dict:
        count = len(group)
        wins = int(group.correct.sum())
        accuracy = wins / count if count else None
        # Wilson 95% interval, avoiding scipy as a runtime dependency.
        if not count:
            low = high = None
        else:
            z = 1.959963984540054
            center = (accuracy + z * z / (2 * count)) / (1 + z * z / count)
            radius = z * np.sqrt(
                accuracy * (1 - accuracy) / count + z * z / (4 * count * count)
            ) / (1 + z * z / count)
            low, high = center - radius, center + radius
        return {
            "signals": count,
            "wins": wins,
            "accuracy": accuracy,
            "wilson95_low": low,
            "wilson95_high": high,
        }

    summary = {"all": metrics(joined)}
    for source, group in joined.groupby("source"):
        summary[source] = metrics(group)
    for side, group in joined.groupby("side"):
        summary[f"side_{side}"] = metrics(group)
    return joined, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    data_dir = args.data_dir
    if data_dir is None:
        candidate = Path("D:/backtest/data_lighter_240d")
        data_dir = candidate if candidate.exists() else Path("data_lighter_240d")
    frame_5m = load_bars(data_dir / "BTCUSDT_5m.csv", "5min")
    frame_1m = load_bars(data_dir / "BTCUSDT_1m.csv", "1min")
    main_signals = build_main_signals(frame_5m)
    aux_signals = build_aux_signals(frame_5m)
    # Runtime precedence: the auxiliary lane is evaluated first on a boundary.
    signals = pd.concat([aux_signals, main_signals], ignore_index=True, sort=False)
    signals = signals.sort_values(["decision_at", "source"])
    signals = signals.drop_duplicates("decision_at", keep="first")
    joined, summary = score(signals, proxy_outcomes(frame_1m))

    result = {
        "data_start": str(frame_1m.timestamp.iloc[0]),
        "data_end": str(frame_1m.timestamp.iloc[-1]),
        "label": "Lighter first-open to last-close proxy; not Chainlink TWAP",
        "signal_scope": "raw Band-DCA boundary signals; no position occupancy or optional gates",
        "summary": summary,
    }
    print(json.dumps(result, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        joined.to_csv(args.output, index=False)


if __name__ == "__main__":
    main()
