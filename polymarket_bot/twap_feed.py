"""Authenticated SDK PolyBolt feeds; reject provider fallback and stale snapshots."""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal
import logging
import time

from .twap_signal import PriceBuffer, Observation

logger = logging.getLogger('polymarket_bot.twap')


def timestamp_ms(value):
    if not isinstance(value,datetime) or value.tzinfo is None:
        raise ValueError('Expected SDK timezone-aware datetime')
    delta = value.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
    return delta.days*86400000+delta.seconds*1000+delta.microseconds//1000


class ChainlinkFeed:
    def __init__(self, store, now_ms=None):
        self.store = store
        self.now_ms = now_ms or (lambda:time.time_ns()//1000000)
        self.twap, self.spot = PriceBuffer(), PriceBuffer()
        self.task = None
        self.connected = False

    def consume(self, event):
        received = self.now_ms()
        kind = 'twap' if event.topic == 'prices.crypto.twap' else 'spot' if event.topic == 'prices.crypto' else None
        if kind is None:
            return
        buffer = self.twap if kind == 'twap' else self.spot
        payload = event.payload
        source = str(payload.source).lower()
        if source != 'chainlink' or payload.symbol != 'btcusd' or (kind == 'twap' and payload.window_seconds != 60):
            buffer.reset(received)
            self.store.log('oracle_wrong_source_or_window',dict(kind=kind,source=source))
            return
        if event.type == 'subscribe' or getattr(event,'dropped',0):
            buffer.reset(received)
            self.store.log('oracle_snapshot_or_recovery',dict(kind=kind,dropped=getattr(event,'dropped',None)))
        points = payload.data if event.type == 'subscribe' else [payload]
        for item in points:
            point = Observation(timestamp_ms(item.timestamp),received,Decimal(item.value))
            buffer.add(point)
            self.store.record_price(kind,point,event.type)
            if kind == 'twap':
                self.store.record_opening(point)

    def invalidate(self):
        now = self.now_ms()
        self.twap.reset(now); self.spot.reset(now)
        self.connected = False

    async def _run(self, client):
        from polymarket.streams import CryptoPriceSpec,CryptoTwapPriceSpec
        while True:
            self.invalidate()
            try:
                specs = [CryptoPriceSpec(symbols=['btcusd'],provider='chainlink'),
                         CryptoTwapPriceSpec(symbols=['btcusd'],provider='chainlink')]
                async with await client.subscribe(specs) as stream:
                    self.connected = True
                    dropped = 0
                    async for event in stream:
                        current = getattr(stream,'dropped',0)
                        if current > dropped:
                            self.invalidate(); dropped = current
                            self.store.log('oracle_client_queue_drop',dict(dropped=current))
                        self.consume(event)
                        self.connected = True
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.invalidate()
                self.store.log('oracle_stream_disconnected',dict(error_type=type(error).__name__))
                logger.warning('Chainlink stream reconnecting: %s',type(error).__name__)
                await asyncio.sleep(2)

    def start(self, client):
        if self.task is None:
            self.task = asyncio.create_task(self._run(client))

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
