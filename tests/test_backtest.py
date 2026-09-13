from datetime import timezone

import pandas as pd

from backtest_polymarket_btc15m import proxy_outcomes, simulate


def test_proxy_outcomes_treats_tie_as_up():
    timestamps = pd.date_range("2026-01-01", periods=15, freq="1min", tz=timezone.utc)
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0] * 15,
        "high": [101.0] * 15,
        "low": [99.0] * 15,
        "close": [100.0] * 15,
        "volume": [1.0] * 15,
    })
    result = proxy_outcomes(frame)
    assert len(result) == 1
    assert bool(result.iloc[0].up_won) is True


def test_simulation_uses_training_probability_and_fee():
    times = pd.date_range("2026-01-01", periods=40, freq="15min", tz=timezone.utc)
    # Twenty winning training observations and twelve winning OOS observations.
    correct = [True] * 20 + [True] * 12 + [False] * 8
    labelled = pd.DataFrame({
        "decision_at": times,
        "source": ["main_5m"] * 40,
        "side": ["up"] * 40,
        "correct": correct,
        "up_won": correct,
        "return_bps": [5.0 if value else -5.0 for value in correct],
    })
    trades, summary = simulate(
        labelled,
        ask=0.50,
        train_end=times[20],
        initial_bankroll=100.0,
        stake_usd=1.0,
        min_train_signals=10,
    )
    assert len(trades) == 20
    assert summary["metrics"]["wins"] == 12
    assert summary["metrics"]["pnl_usd"] > 0
    assert float(trades.iloc[0].fee_per_share) > 0
