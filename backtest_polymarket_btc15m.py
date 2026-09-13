"""Scenario backtest for the Bot 2 BTC Up/Down 15-minute strategy.

This is deliberately a *simulation*, not a historical Polymarket PnL replay.
The repository has historical Lighter candles but not historical Polymarket
order books.  Therefore the script:

* re-builds the causal Bot 1 observations from closed 5m and 15m candles;
* labels each 15m window with a 1m Lighter first-open/last-close proxy;
* calibrates a probability from the training portion only;
* applies a synthetic Polymarket ask, spread, fee and depth model; and
* reports accuracy and binary-contract PnL for an out-of-sample period.

The resolution label is not Chainlink's historical TWAP and the synthetic ask
is not a historical Polymarket quote.  The output is useful for sensitivity
analysis, but it must not be described as realised Polymarket performance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REQUIRED = {"timestamp", "open", "high", "low", "close", "volume"}


def load_bars(path: Path, frequency: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = REQUIRED.difference(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    if frame.empty:
        raise ValueError(f"{path} is empty")
    expected = pd.date_range(frame.timestamp.iloc[0], frame.timestamp.iloc[-1], freq=frequency)
    actual = frame.timestamp.reset_index(drop=True)
    if len(expected) != len(actual) or not actual.equals(pd.Series(expected, name="timestamp")):
        raise ValueError(f"{path} is not a continuous {frequency} series")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    return frame.reset_index(drop=True)


def _in_session(stamps: pd.Series, start: int, end: int) -> pd.Series:
    hours = stamps.dt.hour
    start %= 24
    end %= 24
    if start == end:
        return pd.Series(True, index=stamps.index)
    if start < end:
        return hours.ge(start) & hours.lt(end)
    return hours.ge(start) | hours.lt(end)


def build_signals(frame_5m: pd.DataFrame, *, sma_days: int = 25,
                  short_depth_pct: float = 1.5, short_lane_run_bps: float = 60.,
                  session_start_utc: int = 8, session_end_utc: int = 22,
                  policy: str = 'boundary', router_enabled: bool = True) -> pd.DataFrame:
    """Compatibility entrypoint using the shared research/paper rules."""
    from polymarket_bot.signal_grid import features, raw_signals, select_windows
    grid = features(frame_5m, sma_days=sma_days, short_depth_pct=short_depth_pct)
    signals = select_windows(raw_signals(grid, router_enabled=router_enabled,
        run_bps=short_lane_run_bps, session_start=session_start_utc,
        session_end=session_end_utc), policy=policy)
    return signals.rename(columns={'lower5':'bb_lower','upper5':'bb_upper','run60':'run_bps'})


def proxy_outcomes(frame_1m: pd.DataFrame) -> pd.DataFrame:
    """Create the conservative 15m proxy label from complete 1m candles."""
    indexed = frame_1m.copy().set_index("timestamp").sort_index()
    outcomes = indexed.resample("15min", label="left", closed="left").agg(
        start_price=("open", "first"),
        end_price=("close", "last"),
        minute_count=("close", "count"),
    )
    outcomes = outcomes.loc[outcomes["minute_count"].eq(15)].copy()
    outcomes["up_won"] = outcomes["end_price"].ge(outcomes["start_price"])
    outcomes["return_bps"] = (outcomes["end_price"] / outcomes["start_price"] - 1.0) * 1e4
    outcomes.index.name = "decision_at"
    return outcomes.reset_index()


def join_labels(signals: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    joined = signals.merge(outcomes, on="decision_at", how="inner")
    joined["correct"] = joined["side"].eq(np.where(joined["up_won"], "up", "down"))
    return joined.sort_values("decision_at").reset_index(drop=True)


def _probability_table(train: pd.DataFrame, prior_strength: float = 2.0) -> dict[tuple[str, str], float]:
    table: dict[tuple[str, str], float] = {}
    for (source, side), group in train.groupby(["source", "side"], sort=False):
        count = len(group)
        wins = int(group["correct"].sum())
        # Beta(1,1) smoothing prevents a small training sample from producing
        # a false probability of exactly 0 or 1.
        table[(str(source), str(side))] = (wins + prior_strength / 2.0) / (count + prior_strength)
    return table


def _wilson(wins: int, count: int) -> tuple[float | None, float | None]:
    if count <= 0:
        return None, None
    z = 1.959963984540054
    p = wins / count
    center = (p + z * z / (2 * count)) / (1 + z * z / count)
    radius = z * np.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / (1 + z * z / count)
    return float(center - radius), float(center + radius)


def _metrics(trades: pd.DataFrame, initial_bankroll: float, candidates: int) -> dict:
    if trades.empty:
        return {
            "candidates": int(candidates), "trades": 0, "wins": 0, "losses": 0,
            "accuracy": None, "wilson95": [None, None], "pnl_usd": 0.0,
            "staked_usd": 0.0, "roi_on_stake": None, "profit_factor": None,
            "max_drawdown_usd": 0.0, "final_bankroll_usd": initial_bankroll,
        }
    wins = int(trades["correct"].sum())
    count = len(trades)
    gross_profit = float(trades.loc[trades["pnl_usd"] > 0, "pnl_usd"].sum())
    gross_loss = float(-trades.loc[trades["pnl_usd"] < 0, "pnl_usd"].sum())
    equity = pd.Series([initial_bankroll, *trades["bankroll_after_usd"].astype(float).tolist()])
    drawdown = equity.cummax() - equity
    low, high = _wilson(wins, count)
    staked = float(trades["cost_usd"].sum())
    pnl = float(trades["pnl_usd"].sum())
    return {
        "candidates": int(candidates), "trades": count, "wins": wins,
        "losses": count - wins, "accuracy": wins / count,
        "wilson95": [low, high], "pnl_usd": pnl, "staked_usd": staked,
        "roi_on_stake": pnl / staked if staked else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown_usd": float(drawdown.max()),
        "final_bankroll_usd": float(trades["bankroll_after_usd"].iloc[-1]),
    }


def simulate(
    labelled: pd.DataFrame,
    *,
    ask: float,
    train_end: pd.Timestamp,
    initial_bankroll: float = 100.0,
    stake_usd: float = 1.0,
    size_mode: str = "fixed",
    max_stake_usd: float = 10.0,
    kelly_fraction: float = 0.10,
    fee_rate: float = 0.07,
    spread: float = 0.02,
    max_spread: float = 0.04,
    min_edge: float = 0.03,
    depth_shares: float = 1_000_000.0,
    fill_rate: float = 1.0,
    min_train_signals: int = 20,
) -> tuple[pd.DataFrame, dict]:
    train = labelled.loc[labelled["decision_at"] < train_end]
    test = labelled.loc[labelled["decision_at"] >= train_end].copy()
    probabilities = _probability_table(train)
    test["model_probability"] = [probabilities.get((s, d), np.nan) for s, d in zip(test.source, test.side)]
    test["fee_per_share"] = fee_rate * ask * (1.0 - ask)
    test["edge_per_share"] = test["model_probability"] - ask - test["fee_per_share"]
    counts = train.groupby(["source", "side"]).size().to_dict()
    test["train_count"] = [counts.get((s, d), 0) for s, d in zip(test.source, test.side)]
    eligible = (
        test["model_probability"].notna()
        & test["train_count"].ge(min_train_signals)
        & test["edge_per_share"].ge(min_edge)
        & (spread <= max_spread)
        & (fill_rate > 0)
    )
    candidates = int(eligible.sum())
    rows: list[dict] = []
    bankroll = float(initial_bankroll)
    for row in test.loc[eligible].itertuples(index=False):
        p = float(row.model_probability)
        fee = float(row.fee_per_share)
        unit_cost = ask + fee
        win_net = 1.0 - unit_cost
        loss_net = unit_cost
        if unit_cost <= 0 or win_net <= 0:
            continue
        if size_mode == "kelly":
            # Fraction of bankroll spent, not number of shares per dollar.
            kelly = (p - unit_cost) / (1.0 - unit_cost)
            target_stake = min(max_stake_usd, bankroll * kelly_fraction * max(0.0, kelly))
        else:
            target_stake = stake_usd
        target_stake = min(target_stake, bankroll)
        shares = min(target_stake / unit_cost if unit_cost else 0.0, depth_shares) * fill_rate
        cost = shares * unit_cost
        if shares <= 0 or cost <= 0:
            continue
        correct = bool(row.correct)
        payout = shares if correct else 0.0
        pnl = payout - cost
        bankroll += pnl
        rows.append({
            "decision_at": row.decision_at,
            "source": row.source,
            "side": row.side,
            "model_probability": p,
            "train_count": int(row.train_count),
            "ask": ask,
            "spread": spread,
            "fee_per_share": fee,
            "edge_per_share": float(row.edge_per_share),
            "shares": shares,
            "cost_usd": cost,
            "payout_usd": payout,
            "pnl_usd": pnl,
            "correct": correct,
            "proxy_up_won": bool(row.up_won),
            "proxy_return_bps": float(row.return_bps),
            "bankroll_after_usd": bankroll,
        })
    trades = pd.DataFrame(rows)
    summary = {
        "ask": ask,
        "spread": spread,
        "fee_rate": fee_rate,
        "min_edge": min_edge,
        "train_end": train_end.isoformat(),
        "training_signals": len(train),
        "test_signals": len(test),
        "probability_by_source_side": {
            f"{source}:{side}": {"p": p, "n": int(counts.get((source, side), 0))}
            for (source, side), p in probabilities.items()
        },
        "metrics": _metrics(trades, initial_bankroll, candidates),
    }
    return trades, summary


def _parse_asks(raw: str) -> list[float]:
    values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not values or any(value <= 0 or value >= 1 for value in values):
        raise ValueError("--asks must contain prices strictly between 0 and 1")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("backtest_results_revised"))
    parser.add_argument("--asks", default="0.45,0.50,0.55", help="comma-separated synthetic ask prices")
    parser.add_argument("--train-ratio", type=float, default=0.60)
    parser.add_argument("--min-train-signals", type=int, default=20)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--spread", type=float, default=0.02)
    parser.add_argument("--max-spread", type=float, default=0.04)
    parser.add_argument("--min-edge", type=float, default=0.03)
    parser.add_argument("--stake", type=float, default=1.0)
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--size-mode", choices=("fixed", "kelly"), default="fixed")
    parser.add_argument("--max-stake", type=float, default=10.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.10)
    parser.add_argument("--depth-shares", type=float, default=1_000_000.0)
    parser.add_argument("--fill-rate", type=float, default=1.0)
    parser.add_argument("--session-start-utc", type=int, default=8)
    parser.add_argument("--session-end-utc", type=int, default=22)
    args = parser.parse_args()

    if not 0.1 <= args.train_ratio <= 0.9:
        raise ValueError("--train-ratio must be between 0.1 and 0.9")
    if args.fill_rate <= 0 or args.fill_rate > 1:
        raise ValueError("--fill-rate must be in (0, 1]")
    data_dir = args.data_dir
    if data_dir is None:
        candidate = Path("D:/backtest/data_lighter_240d")
        data_dir = candidate if candidate.exists() else Path("data_lighter_240d")
    frame_5m = load_bars(data_dir / "BTCUSDT_5m.csv", "5min")
    frame_1m = load_bars(data_dir / "BTCUSDT_1m.csv", "1min")
    signals = build_signals(
        frame_5m,
        session_start_utc=args.session_start_utc,
        session_end_utc=args.session_end_utc,
    )
    labelled = join_labels(signals, proxy_outcomes(frame_1m))
    if labelled.empty:
        raise RuntimeError("no labelled signals after joining 5m/15m signals to 1m outcomes")
    first_at, last_at = frame_1m.timestamp.iloc[0], frame_1m.timestamp.iloc[-1]
    train_end = (first_at + (last_at-first_at)*args.train_ratio).ceil('1D')
    train_end = train_end.tz_localize("UTC") if train_end.tzinfo is None else train_end.tz_convert("UTC")
    # If the split timestamp itself is included in train, there is no overlap
    # with the test side because simulate() uses a strict '< train_end'.
    output_dir = args.output_dir
    if output_dir.resolve().is_relative_to(Path('D:/backtest').resolve()):
        raise ValueError('Output must stay outside Bot1 directory')
    output_dir.mkdir(parents=True, exist_ok=True)
    all_summaries: list[dict] = []
    for ask in _parse_asks(args.asks):
        trades, summary = simulate(
            labelled,
            ask=ask,
            train_end=train_end,
            initial_bankroll=args.bankroll,
            stake_usd=args.stake,
            size_mode=args.size_mode,
            max_stake_usd=args.max_stake,
            kelly_fraction=args.kelly_fraction,
            fee_rate=args.fee_rate,
            spread=args.spread,
            max_spread=args.max_spread,
            min_edge=args.min_edge,
            depth_shares=args.depth_shares,
            fill_rate=args.fill_rate,
            min_train_signals=args.min_train_signals,
        )
        all_summaries.append(summary)
        trades.to_csv(output_dir / f"trades_ask_{ask:.3f}.csv", index=False)

    result = {
        "data_start": str(frame_1m["timestamp"].iloc[0]),
        "data_end": str(frame_1m["timestamp"].iloc[-1]),
        "signal_count": len(signals),
        "labelled_signal_count": len(labelled),
        "signal_scope": "Bot 1 causal main 5m lane + auxiliary 15m short lane; aux precedence",
        "resolution_label": "Lighter 1m first-open to last-close proxy; not Chainlink TWAP",
        "entry_model": "synthetic fixed ask/spread/depth/fill; not historical Polymarket orderbook",
        "session_utc": [args.session_start_utc % 24, args.session_end_utc % 24],
        "train_ratio": args.train_ratio,
        "split_type": "single chronological holdout, not walk-forward; see audit_poly_research.py",
        "results": all_summaries,
    }
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
