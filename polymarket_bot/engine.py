from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
import logging
import time
from typing import Any

from .config import Settings
from .geography import geographic_check
from .market_data import BinanceFeed
from .lighter_paper_feed import LighterFeed
from .actual_research import history_asof
from .market_stream import MarketChangeStream, MarketStreamError
from .paper_store import StateStore
from .polymarket_api import MarketUnavailable, PolymarketLiveExecutor, PolymarketPublic
from .risk import RiskEngine
from .signal import snapshot

logger = logging.getLogger("polymarket_bot")


class BotEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.feed = (
            LighterFeed(settings.state_path.parent / "lighter_minutes.sqlite3")
            if settings.data_source == "lighter"
            else BinanceFeed(settings.binance_url)
        )
        self.api = PolymarketPublic(settings)
        self.store = StateStore(settings.state_path, settings.decision_log_path)
        self.risk = RiskEngine(settings, settings.load_calibration())
        self.executor = PolymarketLiveExecutor(settings) if settings.mode == "live" else None

    def _book_is_fresh(self, book: Any) -> bool:
        if book.timestamp_ms is None:
            return False
        age_ms = (
            int(time.time() * 1000)
            + self.api.server_clock_offset_ms
            - book.timestamp_ms
        )
        return -1000 <= age_ms <= self.settings.live_quote_max_age_ms

    async def run_once(self, now: datetime | None = None) -> dict[str, Any] | None:
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = self.api.window_start(moment)
        elapsed = (moment - start).total_seconds()
        if elapsed < self.settings.decision_delay_seconds:
            return None
        if elapsed > self.settings.max_entry_delay_seconds:
            return None
        try:
            market = await self.api.market_for_window(start)
        except MarketUnavailable as exc:
            logger.info("market unavailable at %s: %s", start.isoformat(), exc)
            return None
        if self.store.seen(market.slug):
            return None
        if not market.active or market.closed or not market.accepting_orders:
            self.store.log("market_skipped", {"slug": market.slug, "reason": "inactive_or_closed"})
            self.store.mark_seen(market.slug)
            return None

        try:
            geo = await self.api.geoblock()
        except Exception as exc:
            geo = {"blocked": self.settings.mode == "live", "error": str(exc)}
            self.store.log("geoblock_unavailable", {"slug": market.slug, "geo": geo})
            if self.settings.mode == "live":
                logger.error("cannot verify geoblock in live mode: %s", exc)
                return None
        if (self.settings.mode == "live"
                and not geographic_check(geo).get("new_order_network_check", False)):
            self.store.log("live_blocked_geoblock", {"slug": market.slug, "geo": geo})
            logger.error("live execution blocked by Polymarket geoblock: %s", geo)
            return None

        try:
            if isinstance(self.feed, LighterFeed):
                frame_5m, daily = await self.feed.refresh(moment)
            else:
                frame_5m, daily = await asyncio.gather(
                    self.feed.history_5m(
                        self.settings.symbol, self.settings.history_5m_bars, now=moment
                    ),
                    self.feed.history_1d(
                        self.settings.symbol, self.settings.router_sma_days + 3, now=moment
                    ),
                )
        except Exception as exc:
            self.store.log("signal_feed_unavailable", {"slug": market.slug, "error": str(exc)})
            logger.warning("signal feed unavailable for %s: %s", market.slug, exc)
            return None
        signal = snapshot(
            frame_5m, decision_at=start,
            sma_days=self.settings.router_sma_days,
            short_depth_pct=self.settings.router_short_depth_pct,
            short_lane_run_bps=self.settings.short_lane_run_bps,
            session_start_utc=self.settings.session_start_utc,
            session_end_utc=self.settings.session_end_utc,
            daily_frame=daily,
            policy=self.settings.signal_policy,
            router_enabled=self.settings.router_enabled,
            aux_enabled=self.settings.aux_enabled,
        )
        event = {"market": market, "signal": signal, "geo": geo}
        self.store.log("signal", event)
        if signal.direction is None:
            self.store.mark_seen(market.slug)
            return event

        try:
            await self.api.sync_clock()
        except Exception as exc:
            self.store.log("clob_clock_unavailable", {"slug": market.slug, "error": str(exc)})
            logger.warning("cannot synchronize CLOB clock for %s: %s", market.slug, exc)
            if self.settings.mode == "live":
                return event

        frozen_cap = None
        if self.settings.execution_strategy == "legacy_1230_ref85":
            while frozen_cap is None:
                try:
                    frozen_cap = await self._legacy_reference_cap(market, signal, start)
                except Exception as exc:
                    remaining = (
                        start + timedelta(seconds=self.settings.max_entry_delay_seconds)
                        - datetime.now(timezone.utc)
                    ).total_seconds()
                    self.store.log("legacy_reference_unavailable", {
                        "slug": market.slug, "error": str(exc),
                        "remaining_seconds": remaining,
                    })
                    if remaining <= 0:
                        self.store.mark_seen(market.slug)
                        return event
                    await asyncio.sleep(min(.25, remaining))
        await self._monitor_entry_window(market, signal, start, frozen_cap)
        return event

    async def _legacy_reference_cap(self, market: Any, signal: Any, start: datetime) -> Decimal:
        due = int(start.timestamp()) + self.settings.decision_delay_seconds
        history = await self.api.price_history(
            market.token_for(signal.direction), int(start.timestamp()) - 120, due
        )
        reference = history_asof(history, due, self.settings.reference_max_age_seconds)
        if reference is None:
            raise ValueError("legacy_reference_missing_or_stale")
        price = Decimal(str(reference["price"]))
        if price < Decimal(str(self.settings.min_entry_price)):
            raise ValueError("legacy_reference_below_085")
        assumed = price + Decimal(str(self.settings.reference_price_padding))
        if assumed >= Decimal("1"):
            raise ValueError("legacy_reference_plus_padding_not_below_one")
        tick = market.tick_size
        if tick is None or not Decimal("0") < tick < Decimal("1"):
            raise ValueError("legacy_market_tick_missing")
        cap = (assumed / tick).to_integral_value(rounding=ROUND_DOWN) * tick
        cap = min(cap, Decimal(str(self.settings.live_max_price)))
        self.store.log("legacy_reference_frozen", {
            "slug": market.slug, "reference": reference, "cap": cap,
            "due_seconds": due,
        })
        return cap

    async def _monitor_entry_window(
        self, market: Any, signal: Any, start: datetime,
        frozen_cap: Decimal | None = None,
    ) -> None:
        token_id = market.token_for(signal.direction)
        if frozen_cap is not None:
            # The legacy window is only five seconds wide. REST immediately;
            # a WebSocket handshake may consume the entire FOK opportunity.
            await self._monitor_with_rest_fallback(
                market, signal, token_id, start, frozen_cap
            )
            return
        try:
            async with MarketChangeStream(
                self.settings.market_ws_url,
                market.condition_id,
                market.token_ids,
                self.settings.live_quote_max_age_ms,
                self.api.server_clock_offset_ms,
            ) as stream:
                first = True
                while True:
                    remaining = (
                        start + timedelta(seconds=self.settings.max_entry_delay_seconds)
                        - datetime.now(timezone.utc)
                    ).total_seconds()
                    if remaining <= 0:
                        self.store.log("entry_window_expired", {"slug": market.slug})
                        self.store.mark_seen(market.slug)
                        return
                    if not first:
                        change = await stream.wait_for_change(min(remaining, 10.0))
                        if change is None:
                            continue
                        if self.settings.market_event_debounce_ms:
                            await asyncio.sleep(self.settings.market_event_debounce_ms / 1000)
                    first = False
                    if await self._evaluate_quote(market, signal, token_id, frozen_cap):
                        return
        except MarketStreamError as exc:
            self.store.log("market_stream_unavailable", {"slug": market.slug, "error": str(exc)})
            logger.warning("market stream unavailable for %s; using REST fallback: %s", market.slug, exc)
            await self._monitor_with_rest_fallback(market, signal, token_id, start, frozen_cap)

    async def _monitor_with_rest_fallback(
        self, market: Any, signal: Any, token_id: str, start: datetime,
        frozen_cap: Decimal | None = None,
    ) -> None:
        while True:
            remaining = (
                start + timedelta(seconds=self.settings.max_entry_delay_seconds)
                - datetime.now(timezone.utc)
            ).total_seconds()
            if remaining <= 0:
                self.store.log("entry_window_expired", {"slug": market.slug, "fallback": "rest"})
                self.store.mark_seen(market.slug)
                return
            if await self._evaluate_quote(market, signal, token_id, frozen_cap):
                return
            await asyncio.sleep(min(float(self.settings.poll_seconds), remaining))

    async def _evaluate_quote(
        self, market: Any, signal: Any, token_id: str,
        frozen_cap: Decimal | None = None,
    ) -> bool:
        try:
            book = await self.api.book(token_id)
        except Exception as exc:
            self.store.log("book_unavailable", {"slug": market.slug, "error": str(exc)})
            return False
        if not self._book_is_fresh(book):
            self.store.log("stale_book_ignored", {
                "slug": market.slug, "book_timestamp_ms": book.timestamp_ms
            })
            return False
        if frozen_cap is not None and (book.best_ask is None or book.best_ask > frozen_cap):
            self.store.log("legacy_ask_above_frozen_cap", {
                "slug": market.slug, "ask": book.best_ask, "cap": frozen_cap,
            })
            return False
        decision = self.risk.decide(market, book, signal)
        self.store.log("decision", {
            "market": market, "signal": signal, "book": book, "decision": decision
        })
        if decision is None:
            return False
        if decision.reason in {
            "calibration_missing_or_not_approved",
            "legacy_strategy_missing_exact_approval",
        }:
            self.store.mark_seen(market.slug)
            return True
        if decision.action != "buy":
            return False
        return await self._execute_fresh_decision(market, signal, decision, frozen_cap)

    async def _execute_fresh_decision(
        self, market: Any, signal: Any, decision: Any,
        frozen_cap: Decimal | None = None,
    ) -> bool:
        token_id = market.token_for(signal.direction)
        if self.settings.mode != "live":
            self.store.set_position(market.slug, {
                "token_id": token_id,
                "direction": signal.direction,
                "stake_usd": decision.stake_usd,
                "shares": decision.shares,
                "paper": True,
            })
            self.store.log("paper_order", {"market": market, "decision": decision})
            self.store.mark_seen(market.slug)
            return True
        if self.executor is None:
            raise RuntimeError("live executor missing")

        final_geo, _ = await asyncio.gather(
            self.api.geoblock(),
            self.executor.ensure_balance(decision.stake_usd, max_age=0),
        )
        if not geographic_check(final_geo).get("new_order_network_check", False):
            raise RuntimeError("Polymarket geoblock changed before submission")
        final_book = await self.api.book(token_id)
        quote_observed_at = time.monotonic()
        if not self._book_is_fresh(final_book):
            self.store.log("final_quote_stale", {
                "slug": market.slug, "book_timestamp_ms": final_book.timestamp_ms
            })
            return False
        final_decision = self.risk.decide(market, final_book, signal)
        self.store.log("final_decision", {
            "market": market, "book": final_book, "decision": final_decision
        })
        if final_decision is None or final_decision.action != "buy":
            return False
        if frozen_cap is not None and (
                final_book.best_ask is None or final_book.best_ask > frozen_cap):
            self.store.log("final_legacy_ask_above_frozen_cap", {
                "slug": market.slug, "ask": final_book.best_ask, "cap": frozen_cap,
            })
            return False

        tick = market.tick_size or final_book.tick_size or Decimal("0.01")
        cap = frozen_cap if frozen_cap is not None else min(
            Decimal(str(self.settings.live_max_price)),
            final_decision.ask + Decimal(str(self.settings.live_price_slippage)),
        )
        cap = (cap / tick).to_integral_value(rounding=ROUND_DOWN) * tick
        attempt_id = self.store.reserve_live_attempt(
            market.slug,
            {
                "token_id": token_id,
                "direction": signal.direction,
                "stake_usd": final_decision.stake_usd,
                "max_price": cap,
                "book_timestamp_ms": final_book.timestamp_ms,
            },
            self.settings.live_max_orders,
        )
        try:
            response = await self.executor.buy(
                token_id,
                final_decision.stake_usd,
                cap,
                quote_observed_at=quote_observed_at,
            )
        except Exception as exc:
            self.store.finish_live_attempt(attempt_id, "ambiguous_or_failed", {
                "error_type": type(exc).__name__, "error": str(exc)
            })
            self.store.mark_seen(market.slug)
            raise

        status = (
            "filled" if response.get("filled")
            else "rejected_or_unfilled" if response.get("reconciled")
            else "accepted_pending_manual_reconciliation"
        )
        self.store.finish_live_attempt(attempt_id, status, response)
        if response.get("filled") or not response.get("reconciled"):
            self.store.set_position(market.slug, {
                "token_id": token_id,
                "direction": signal.direction,
                "stake_usd": final_decision.stake_usd,
                "shares": response.get("taking_amount", "0"),
                "making_amount": response.get("making_amount", "0"),
                "order_response": response,
            })
        self.store.log("live_order_result", {
            "market": market, "decision": final_decision, "response": response
        })
        self.store.mark_seen(market.slug)
        return True

    async def run_forever(self) -> None:
        if self.executor is not None:
            await self.executor.connect()
        try:
            if isinstance(self.feed, LighterFeed):
                # Warm the persistent 28-day cache before an entry window begins.
                # A failed warmup is fatal in live mode; there is no Binance fallback.
                await self.feed.refresh(datetime.now(timezone.utc))
            while True:
                try:
                    await self.run_once()
                except Exception:
                    logger.exception("bot tick failed; retrying")
                await asyncio.sleep(self.settings.poll_seconds)
        finally:
            if self.executor is not None:
                await self.executor.close()
            await self.api.close()
            close = getattr(self.feed, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
