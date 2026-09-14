import asyncio
import json
import time

from polymarket_bot.market_stream import MarketChangeStream, event_mentions_market


def test_event_matcher_accepts_direct_and_nested_token_changes():
    tokens = {"up", "down"}
    assert event_mentions_market(
        {"event_type": "book", "market": "condition", "asset_id": "up"},
        "condition", tokens,
    )
    assert event_mentions_market(
        {"market": "condition", "asset_id": "up", "bids": [], "asks": []},
        "condition", tokens,
    )
    assert event_mentions_market(
        {
            "event_type": "price_change",
            "market": "condition",
            "price_changes": [{"asset_id": "down"}],
        },
        "condition", tokens,
    )
    assert not event_mentions_market(
        {"event_type": "book", "market": "other", "asset_id": "up"},
        "condition", tokens,
    )
    assert not event_mentions_market(
        {"event_type": "last_trade_price", "market": "condition", "asset_id": "up"},
        "condition", tokens,
    )


def test_stream_ignores_pong_stale_and_unrelated_events():
    now_ms = int(time.time() * 1000)

    class FakeWebSocket:
        def __init__(self):
            self.messages = iter([
                "PONG",
                json.dumps({
                    "event_type": "book", "market": "other",
                    "asset_id": "up", "timestamp": now_ms,
                }),
                json.dumps({
                    "event_type": "book", "market": "condition",
                    "asset_id": "up", "timestamp": now_ms - 10_000,
                }),
                json.dumps({
                    "event_type": "best_bid_ask", "market": "condition",
                    "asset_id": "down", "timestamp": now_ms,
                }),
            ])

        async def recv(self):
            return next(self.messages)

    stream = MarketChangeStream("wss://example", "condition", ("up", "down"), 1500)
    stream.websocket = FakeWebSocket()
    result = asyncio.run(stream.wait_for_change(1))
    assert result is not None
    assert result["event_type"] == "best_bid_ask"
    assert 0 <= result["age_ms"] <= 1500
