from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from polymarket_bot.config import Settings
from polymarket_bot.models import Book, Market
from polymarket_bot.risk import RiskEngine
from polymarket_bot.signal import snapshot


def _frame() -> pd.DataFrame:
    times = pd.date_range("2025-12-31 21:30", periods=30, freq="5min", tz="UTC")
    closes = [100.0] * 29 + [95.0]
    return pd.DataFrame({
        "timestamp": times, "open": closes, "high": closes,
        "low": closes, "close": closes, "volume": [1.0] * len(closes),
    })


def _daily() -> pd.DataFrame:
    times = pd.date_range("2025-12-01", periods=31, freq="1D", tz="UTC")
    return pd.DataFrame({"timestamp": times, "close": [100.0] * len(times)})


def test_snapshot_uses_only_closed_5m_rows_and_maps_lower_band_to_up():
    result = snapshot(
        _frame(), decision_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        daily_frame=_daily(), session_start_utc=0, session_end_utc=0,
    )
    assert result.direction == "up"
    assert result.source == "main_5m"
    assert result.route == "long"
    assert result.reason == "route_long_5m_lower_band"


def test_risk_requires_explicit_approved_calibration():
    settings = Settings(mode="paper", max_stake_usd=10.0)
    engine = RiskEngine(settings, {})
    result = snapshot(_frame(), decision_at=datetime(2026, 1, 1, tzinfo=timezone.utc), daily_frame=_daily())
    assert engine.probability(result) is None


def test_risk_calculates_positive_edge_after_fee():
    settings = Settings(mode="paper", max_stake_usd=10.0, bankroll_usd=100.0)
    engine = RiskEngine(settings, {"approved": True, "probability_by_source": {"main_5m": {"up": 0.65}}})
    signal = snapshot(_frame(), decision_at=datetime(2026, 1, 1, tzinfo=timezone.utc), daily_frame=_daily())
    market = Market(
        slug="btc-updown-15m-1", title="Bitcoin Up or Down", condition_id="0x1",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc), end=datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc),
        resolution_source="Chainlink", description="Chainlink", outcomes=("Up", "Down"),
        token_ids=("up", "down"), active=True, closed=False, accepting_orders=True,
        tick_size=Decimal("0.01"), min_order_size=Decimal("5"), fees_enabled=True, neg_risk=False,
    )
    book = Book("up", Decimal("0.49"), Decimal("0.50"), Decimal("20"), Decimal("20"), Decimal("0.01"), Decimal("0.01"), Decimal("5"), False)
    decision = engine.decide(market, book, signal)
    assert decision is not None
    assert decision.action == "buy"
    assert decision.edge_per_share > Decimal("0.03")
