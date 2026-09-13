from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

import httpx

from .config import Settings
from .models import Book, Direction, Market


class MarketUnavailable(RuntimeError):
    pass


def _decimal(value: Any) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            result = json.loads(value)
        except json.JSONDecodeError:
            return []
        return result if isinstance(result, list) else []
    return []


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class PolymarketPublic:
    def __init__(self, settings: Settings, timeout: float = 10.0):
        self.settings = settings
        self.timeout = timeout

    async def _get(self, url: str, **params: Any) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params or None)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def window_start(now: datetime | None = None) -> datetime:
        stamp = now or datetime.now(timezone.utc)
        stamp = stamp.astimezone(timezone.utc)
        epoch = int(stamp.timestamp()) // 900 * 900
        return datetime.fromtimestamp(epoch, tz=timezone.utc)

    async def geoblock(self) -> dict[str, Any]:
        result = await self._get(self.settings.geoblock_url)
        return result if isinstance(result, dict) else {"blocked": True, "reason": "invalid_response"}

    async def market_for_window(self, window_start: datetime | None = None) -> Market:
        start = self.window_start(window_start)
        slug = f"btc-updown-15m-{int(start.timestamp())}"
        try:
            event = await self._get(f"{self.settings.gamma_url}/events/slug/{slug}")
        except httpx.HTTPStatusError as exc:
            raise MarketUnavailable(f"Gamma did not return {slug}: {exc.response.status_code}") from exc
        if not isinstance(event, dict):
            raise MarketUnavailable(f"Gamma response for {slug} is not an object")
        markets = event.get("markets")
        if not isinstance(markets, list) or len(markets) != 1 or not isinstance(markets[0], dict):
            raise MarketUnavailable(f"{slug} did not contain exactly one market")
        raw = markets[0]
        title = str(event.get("title") or raw.get("question") or "")
        description = str(event.get("description") or raw.get("description") or "")
        resolution_source = str(event.get("resolutionSource") or raw.get("resolutionSource") or "")
        if "bitcoin" not in title.lower() or "up or down" not in title.lower():
            raise MarketUnavailable(f"unexpected BTC market title: {title!r}")
        if "chainlink" not in (description + " " + resolution_source).lower():
            raise MarketUnavailable("market rules do not identify Chainlink; refusing to trade")

        outcomes = _list(raw.get("outcomes"))
        token_ids = _list(raw.get("clobTokenIds") or raw.get("clob_token_ids"))
        if len(outcomes) != 2 or len(token_ids) != 2:
            raise MarketUnavailable(f"{slug} has invalid outcome/token metadata")
        token_by_outcome = {str(outcome).strip().lower(): str(token) for outcome, token in zip(outcomes, token_ids)}
        if not {"up", "down"}.issubset(token_by_outcome):
            raise MarketUnavailable(f"{slug} outcomes are not Up/Down: {outcomes!r}")
        condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "")
        if not condition_id:
            raise MarketUnavailable(f"{slug} has no condition id")
        return Market(
            slug=slug, title=title, condition_id=condition_id,
            start=start, end=start + timedelta(minutes=15),
            resolution_source=resolution_source, description=description,
            outcomes=("Up", "Down"),
            token_ids=(token_by_outcome["up"], token_by_outcome["down"]),
            active=bool(event.get("active", raw.get("active", False))),
            closed=bool(event.get("closed", raw.get("closed", False))),
            accepting_orders=bool(raw.get("acceptingOrders", raw.get("accepting_orders", False))),
            tick_size=_decimal(raw.get("orderPriceMinTickSize", raw.get("tick_size"))),
            min_order_size=_decimal(raw.get("orderMinSize", raw.get("minimumOrderSize"))),
            fees_enabled=bool(raw.get("feesEnabled", raw.get("fees_enabled", True))),
            neg_risk=bool(raw.get("negRisk", raw.get("neg_risk", False))),
        )

    async def book(self, token_id: str) -> Book:
        try:
            raw = await self._get(f"{self.settings.clob_url}/book", token_id=token_id)
        except httpx.HTTPStatusError as exc:
            raise MarketUnavailable(f"CLOB book unavailable: {exc.response.status_code}") from exc
        bids = [(Decimal(str(x["price"])), Decimal(str(x["size"])))
                for x in (raw.get("bids") or []) if isinstance(x, dict) and _decimal(x.get("price")) is not None]
        asks = [(Decimal(str(x["price"])), Decimal(str(x["size"])))
                for x in (raw.get("asks") or []) if isinstance(x, dict) and _decimal(x.get("price")) is not None]
        bids.sort(key=lambda item: item[0], reverse=True)
        asks.sort(key=lambda item: item[0])
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
        return Book(
            token_id=token_id, best_bid=best_bid, best_ask=best_ask,
            bid_size=bids[0][1] if bids else Decimal("0"),
            ask_size=asks[0][1] if asks else Decimal("0"), spread=spread,
            tick_size=_decimal(raw.get("tick_size")),
            min_order_size=_decimal(raw.get("min_order_size")),
            neg_risk=bool(raw.get("neg_risk", False)),
        )


class PolymarketLiveExecutor:
    """Disabled legacy adapter; retained interface, no submission implementation.

    The old market-order path had no verified price cap or fill reconciliation.
    Adding credentials must not accidentally activate that prototype.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Any = None

    async def connect(self) -> None:
        raise RuntimeError('Legacy live executor disabled pending capped order execution and fill reconciliation')

    async def buy(self, token_id: str, stake_usd: Decimal) -> Any:
        raise RuntimeError('Legacy market-order submission disabled; no approved live trial executor')

    async def close(self) -> None:
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if close:
                result = close()
                if hasattr(result, "__await__"):
                    await result
