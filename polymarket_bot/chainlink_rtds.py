"""Optional low-level Chainlink TWAP stream used for resolution-aligned research.

The engine does not use this stream as a substitute for market resolution. It
is a recorder/validation feed: the event's own Gamma rules remain authoritative.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import websockets


class ChainlinkRtds:
    def __init__(self, url: str = "wss://ws-live-data.polymarket.com"):
        self.url = url

    async def stream(self, symbol: str = "btc/usd", window_seconds: int = 60) -> AsyncIterator[dict]:
        topic = "crypto_prices_twap_sixty" if window_seconds == 60 else "crypto_prices_twap_thirty"
        frame = {
            "action": "subscribe",
            "subscriptions": [{
                "topic": topic, "type": "update",
                "filters": json.dumps({"symbol": symbol}, separators=(",", ":")),
            }],
        }
        async with websockets.connect(self.url, ping_interval=None) as socket:
            await socket.send(json.dumps(frame, separators=(",", ":")))
            while True:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    # RTDS uses an application-level text heartbeat, not the
                    # WebSocket protocol ping used by many feeds.
                    await socket.send("PING")
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                if raw == "PONG":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                payload = event.get("payload")
                if isinstance(payload, dict) and payload.get("symbol") == symbol:
                    yield event
