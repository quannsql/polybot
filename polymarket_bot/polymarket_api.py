from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import importlib.metadata
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
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
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
    """Production V2, one-order canary executor with price/spend protection."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Any = None

    async def connect(self) -> None:
        if self.client is not None:
            return
        async with httpx.AsyncClient(timeout=10, trust_env=False) as public_client:
            clock_response = await public_client.get(f"{self.settings.clob_url}/time")
            clock_response.raise_for_status()
            server_time = clock_response.json()
        if not isinstance(server_time, (int, float)):
            raise RuntimeError("Invalid CLOB server clock response")
        offset = float(server_time) - datetime.now(timezone.utc).timestamp()
        if abs(offset) > 30:
            raise RuntimeError(f"Server clock offset too large ({offset:.1f}s)")
        try:
            version = importlib.metadata.version("polymarket-client")
            from polymarket import AsyncSecureClient, RelayerApiKey
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            raise RuntimeError("Install requirements-live-sdk.txt (CLOB V2)") from exc
        if version != "0.10.0":
            raise RuntimeError(f"Unsupported polymarket-client version {version}")
        relayer = RelayerApiKey(
            key=self.settings.relayer_api_key,
            address=self.settings.relayer_api_key_address,
        )
        client = await AsyncSecureClient.create(
            private_key=self.settings.signer_private_key,
            wallet=self.settings.wallet_address,
            api_key=relayer,
        )
        if str(client.wallet).lower() != str(self.settings.wallet_address).lower():
            await client.close()
            raise RuntimeError("SDK resolved a different Polymarket wallet")
        if (self.settings.expected_wallet_type
                and client.wallet_type != self.settings.expected_wallet_type):
            actual = client.wallet_type
            await client.close()
            raise RuntimeError(f"Wallet type mismatch: SDK resolved {actual}")
        balance = await client.get_balance_allowance(asset_type="COLLATERAL")
        required = int(Decimal(str(self.settings.live_fixed_stake_usd)) * 1_000_000)
        if balance.balance < required:
            await client.close()
            available = Decimal(balance.balance) / Decimal(1_000_000)
            raise RuntimeError(f"Insufficient pUSD balance for canary: {available} available")
        self.client = client

    async def buy(self, token_id: str, stake_usd: Decimal, max_price: Decimal) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("Live executor is not connected")
        if not Decimal("0") < stake_usd <= Decimal("30"):
            raise RuntimeError("Live order must be greater than $0 and no more than $30")
        if not Decimal("0") < max_price <= Decimal(str(self.settings.live_max_price)):
            raise RuntimeError("Live order price exceeds configured cap")
        balance = await self.client.get_balance_allowance(asset_type="COLLATERAL")
        if balance.balance < int(stake_usd * 1_000_000):
            raise RuntimeError("Insufficient pUSD balance immediately before order")

        # FOK leaves no resting remainder. max_spend lets the V2 SDK reduce the
        # notional for its current fee schedule so the all-in target is capped.
        response = await self.client.place_market_order(
            token_id=token_id,
            side="BUY",
            amount=str(stake_usd),
            max_spend=str(stake_usd),
            max_price=str(max_price),
            order_type="FOK",
        )
        result = response.model_dump(mode="json")
        if not response.ok:
            result["reconciled"] = True
            result["filled"] = False
            return result
        if response.status == "live":
            await self.client.cancel_order(order_id=str(response.order_id))
            raise RuntimeError("Unexpected resting FOK order was cancelled")
        result["filled"] = bool(response.trade_ids)
        result["reconciled"] = bool(response.trade_ids)
        if response.status == "delayed" and not response.trade_ids:
            # A delayed response can execute after the HTTP response. Query the
            # accepted order; never assume it was unfilled and never resubmit.
            for _ in range(10):
                await asyncio.sleep(1)
                try:
                    order = await self.client.get_order(order_id=str(response.order_id))
                except Exception:
                    continue
                result["order_snapshot"] = order.model_dump(mode="json")
                if order.size_matched > 0:
                    result["filled"] = True
                    result["reconciled"] = True
                    break
                if order.status.lower() in {"cancelled", "canceled", "expired", "unmatched"}:
                    result["filled"] = False
                    result["reconciled"] = True
                    break
        if response.trade_ids:
            try:
                hashes = await self.client.wait_for_order_fill_settlement(response, timeout_s=60)
                result["settlement_hashes"] = [str(item) for item in hashes]
                result["settlement_confirmed"] = True
            except Exception as exc:
                # Submission succeeded. Never retry: the journal requires manual
                # reconciliation when settlement confirmation is ambiguous.
                result["settlement_confirmed"] = False
                result["settlement_error"] = type(exc).__name__
        return result

    async def close(self) -> None:
        if self.client is not None:
            close = getattr(self.client, "close", None)
            if close:
                result = close()
                if hasattr(result, "__await__"):
                    await result
