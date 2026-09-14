from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import time
from typing import Any

import websockets


class MarketStreamError(RuntimeError):
    pass


def event_mentions_market(
    event: dict[str, Any], condition_id: str, token_ids: set[str]
) -> bool:
    """Return whether a supported market event belongs to this contract."""
    event_type = event.get("event_type")
    # The CLOB's initial full-book snapshot currently omits event_type.
    if event_type is None and isinstance(event.get("bids"), list) and isinstance(event.get("asks"), list):
        event_type = "book"
    if event_type not in {
        "book", "price_change", "best_bid_ask", "tick_size_change"
    }:
        return False
    market = event.get("market")
    if market and str(market).lower() != condition_id.lower():
        return False
    asset_id = event.get("asset_id")
    if asset_id is not None and str(asset_id) in token_ids:
        return True
    changes = event.get("price_changes")
    if isinstance(changes, list):
        return any(
            isinstance(change, dict) and str(change.get("asset_id")) in token_ids
            for change in changes
        )
    return False


class MarketChangeStream:
    """Use CLOB WSS only to wake the bot; REST remains quote authority."""

    def __init__(
        self,
        url: str,
        condition_id: str,
        token_ids: tuple[str, ...],
        max_event_age_ms: int = 1500,
        server_clock_offset_ms: int = 0,
    ):
        self.url = url
        self.condition_id = condition_id
        self.token_ids = tuple(str(item) for item in token_ids)
        self.max_event_age_ms = max_event_age_ms
        self.server_clock_offset_ms = server_clock_offset_ms
        self.websocket: Any = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "MarketChangeStream":
        try:
            self.websocket = await websockets.connect(
                self.url,
                ping_interval=None,
                open_timeout=8,
                close_timeout=3,
                max_queue=1024,
            )
            await self.websocket.send(json.dumps({
                "assets_ids": list(self.token_ids),
                "type": "market",
            }))
        except Exception as exc:
            await self.close()
            raise MarketStreamError(f"cannot subscribe to market stream: {exc}") from exc
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(10)
                await self.websocket.send("PING")
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self.websocket is not None:
            with suppress(Exception):
                await self.websocket.close()
            self.websocket = None

    async def wait_for_change(self, timeout: float) -> dict[str, Any] | None:
        if self.websocket is None:
            raise MarketStreamError("market stream is not connected")
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                message = await asyncio.wait_for(self.websocket.recv(), remaining)
            except asyncio.TimeoutError:
                return None
            except Exception as exc:
                raise MarketStreamError(f"market stream disconnected: {exc}") from exc
            if message == "PONG":
                continue
            try:
                payload = json.loads(message)
            except (json.JSONDecodeError, TypeError):
                continue
            events = payload if isinstance(payload, list) else [payload]
            for event in events:
                if not isinstance(event, dict):
                    continue
                if not event_mentions_market(event, self.condition_id, set(self.token_ids)):
                    continue
                try:
                    source_ms = int(event["timestamp"])
                except (KeyError, TypeError, ValueError):
                    continue
                received_ms = int(time.time() * 1000)
                age_ms = received_ms + self.server_clock_offset_ms - source_ms
                if -1000 <= age_ms <= self.max_event_age_ms:
                    event_type = event.get("event_type") or "book"
                    return {
                        "event_type": event_type,
                        "source_timestamp_ms": source_ms,
                        "received_timestamp_ms": received_ms,
                        "age_ms": age_ms,
                    }
