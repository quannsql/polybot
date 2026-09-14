from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal


Direction = Literal["up", "down"]


@dataclass(frozen=True)
class Market:
    slug: str
    title: str
    condition_id: str
    start: datetime
    end: datetime
    resolution_source: str
    description: str
    outcomes: tuple[str, str]
    token_ids: tuple[str, str]
    active: bool
    closed: bool
    accepting_orders: bool
    tick_size: Decimal | None
    min_order_size: Decimal | None
    fees_enabled: bool
    neg_risk: bool

    def token_for(self, direction: Direction) -> str:
        return self.token_ids[0 if direction == "up" else 1]


@dataclass(frozen=True)
class Book:
    token_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    bid_size: Decimal
    ask_size: Decimal
    spread: Decimal | None
    tick_size: Decimal | None
    min_order_size: Decimal | None
    neg_risk: bool
    timestamp_ms: int | None = None


@dataclass(frozen=True)
class SignalSnapshot:
    decision_at: datetime
    route: str | None
    direction: Direction | None
    source: str | None
    strength: float
    close_5m: float | None
    lower_5m: float | None
    upper_5m: float | None
    close_15m: float | None
    upper_15m: float | None
    run_60m_bps: float | None
    reason: str


@dataclass(frozen=True)
class TradeDecision:
    market_slug: str
    direction: Direction
    source: str
    ask: Decimal
    spread: Decimal
    model_probability: Decimal
    fee_per_share: Decimal
    edge_per_share: Decimal
    stake_usd: Decimal
    shares: Decimal
    expected_pnl_usd: Decimal
    action: str
    reason: str


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
