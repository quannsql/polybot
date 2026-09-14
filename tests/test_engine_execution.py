import asyncio
from decimal import Decimal
from types import SimpleNamespace
import time

from polymarket_bot.config import Settings
from polymarket_bot.engine import BotEngine
from polymarket_bot.models import Book


def test_transient_quote_skip_does_not_mark_market_seen():
    class Store:
        def __init__(self):
            self.marked = []
        def log(self, *_):
            pass
        def mark_seen(self, slug):
            self.marked.append(slug)

    engine = object.__new__(BotEngine)
    engine.settings = Settings()
    engine.store = Store()
    engine.api = SimpleNamespace(
        server_clock_offset_ms=0,
        book=lambda token: None,
    )
    book = Book(
        "token", Decimal(".84"), Decimal(".85"), Decimal("30"), Decimal("30"),
        Decimal(".01"), Decimal(".01"), Decimal("5"), False,
        int(time.time() * 1000),
    )

    async def get_book(_):
        return book

    engine.api.book = get_book
    engine.risk = SimpleNamespace(decide=lambda *_: SimpleNamespace(
        action="skip", reason="price_below_entry_filter"
    ))
    market = SimpleNamespace(slug="btc-window")
    signal = SimpleNamespace(direction="up")

    assert asyncio.run(engine._evaluate_quote(market, signal, "token")) is False
    assert engine.store.marked == []


def test_unapproved_calibration_is_terminal_for_current_market():
    class Store:
        def __init__(self):
            self.marked = []
        def log(self, *_):
            pass
        def mark_seen(self, slug):
            self.marked.append(slug)

    engine = object.__new__(BotEngine)
    engine.settings = Settings()
    engine.store = Store()
    book = Book(
        "token", Decimal(".84"), Decimal(".85"), Decimal("30"), Decimal("30"),
        Decimal(".01"), Decimal(".01"), Decimal("5"), False,
        int(time.time() * 1000),
    )

    async def get_book(_):
        return book

    engine.api = SimpleNamespace(server_clock_offset_ms=0, book=get_book)
    engine.risk = SimpleNamespace(decide=lambda *_: SimpleNamespace(
        action="paper_signal_only", reason="calibration_missing_or_not_approved"
    ))
    market = SimpleNamespace(slug="btc-window")
    signal = SimpleNamespace(direction="up")

    assert asyncio.run(engine._evaluate_quote(market, signal, "token")) is True
    assert engine.store.marked == ["btc-window"]
