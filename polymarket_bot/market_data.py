from __future__ import annotations

from datetime import datetime, timezone
import asyncio
from typing import Any

import httpx
import pandas as pd


class BinanceFeed:
    """Public Binance OHLCV feed used only as a signal source.

    The resolution price is *not* read from Binance.  Polymarket's current
    crypto markets resolve from Chainlink data, so this adapter is deliberately
    separate from the resolution/market API adapter.
    """

    def __init__(self, base_url: str = "https://api.binance.com", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def history_5m(self, symbol: str, limit: int, now: datetime | None = None) -> pd.DataFrame:
        params = {"symbol": symbol.upper(), "interval": "5m", "limit": min(1000, max(30, limit + 5))}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v3/klines", params=params)
            response.raise_for_status()
            raw: Any = response.json()
        if not isinstance(raw, list):
            raise ValueError("Binance klines response is not a list")
        rows = []
        for item in raw:
            if not isinstance(item, list) or len(item) < 6:
                continue
            rows.append({
                "timestamp": pd.to_datetime(int(item[0]), unit="ms", utc=True),
                "open": float(item[1]), "high": float(item[2]),
                "low": float(item[3]), "close": float(item[4]),
                "volume": float(item[5]),
            })
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame = frame.drop_duplicates("timestamp").sort_values("timestamp")
        moment = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
        frame = frame.loc[frame.timestamp + pd.Timedelta(minutes=5) <= moment]
        return frame.tail(limit).reset_index(drop=True)

    async def history_1d(self, symbol: str, limit: int, now: datetime | None = None) -> pd.DataFrame:
        params = {"symbol": symbol.upper(), "interval": "1d", "limit": min(1000, max(30, limit + 3))}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v3/klines", params=params)
            response.raise_for_status()
            raw: Any = response.json()
        rows = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, list) or len(item) < 6:
                continue
            rows.append({
                "timestamp": pd.to_datetime(int(item[0]), unit="ms", utc=True),
                "open": float(item[1]), "high": float(item[2]),
                "low": float(item[3]), "close": float(item[4]),
                "volume": float(item[5]),
            })
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame = frame.drop_duplicates("timestamp").sort_values("timestamp")
        moment = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
        moment = moment.tz_localize("UTC") if moment.tzinfo is None else moment.tz_convert("UTC")
        frame = frame.loc[frame.timestamp + pd.Timedelta(days=1) <= moment]
        return frame.tail(limit).reset_index(drop=True)


async def close_feed(feed: Any) -> None:
    close = getattr(feed, "aclose", None) or getattr(feed, "close", None)
    if close is not None:
        result = close()
        if asyncio.iscoroutine(result):
            await result
