from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

from .config import Settings
from .market_data import BinanceFeed
from .models import jsonable
from .paper_store import StateStore
from .polymarket_api import MarketUnavailable, PolymarketLiveExecutor, PolymarketPublic
from .risk import RiskEngine
from .signal import snapshot

logger = logging.getLogger("polymarket_bot")


class BotEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.feed = BinanceFeed(settings.binance_url)
        self.api = PolymarketPublic(settings)
        self.store = StateStore(settings.state_path, settings.decision_log_path)
        self.risk = RiskEngine(settings, settings.load_calibration())
        self.executor = PolymarketLiveExecutor(settings) if settings.mode == "live" else None

    async def run_once(self, now: datetime | None = None) -> dict[str, Any] | None:
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = self.api.window_start(moment)
        if (moment - start).total_seconds() < self.settings.decision_delay_seconds:
            return None
        if (moment - start).total_seconds() > self.settings.max_entry_delay_seconds:
            return None
        market: Any
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
            # Paper mode may still be used for research from an environment
            # that cannot resolve polymarket.com.  Live mode must fail closed.
            geo = {"blocked": self.settings.mode == "live", "error": str(exc)}
            self.store.log("geoblock_unavailable", {"slug": market.slug, "geo": geo})
            if self.settings.mode == "live":
                self.store.mark_seen(market.slug)
                logger.error("cannot verify geoblock in live mode: %s", exc)
                return None
        blocked = bool(geo.get("blocked", True))
        if blocked and self.settings.mode == "live":
            self.store.log("live_blocked_geoblock", {"slug": market.slug, "geo": geo})
            self.store.mark_seen(market.slug)
            logger.error("live execution blocked by Polymarket geoblock: %s", geo)
            return None

        try:
            frame_5m = await self.feed.history_5m(
                self.settings.symbol, self.settings.history_5m_bars, now=moment
            )
            daily = await self.feed.history_1d(
                self.settings.symbol, self.settings.router_sma_days + 3, now=moment
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
            book = await self.api.book(market.token_for(signal.direction))
        except Exception as exc:
            self.store.log("book_unavailable", {"slug": market.slug, "error": str(exc)})
            logger.warning("book unavailable for %s: %s", market.slug, exc)
            return event
        decision = self.risk.decide(market, book, signal)
        self.store.log("decision", {"market": market, "signal": signal, "book": book, "decision": decision})
        self.store.mark_seen(market.slug)
        if decision is None:
            return event
        if decision.action == "buy" and self.settings.mode == "live":
            if (datetime.now(timezone.utc) - start).total_seconds() > self.settings.max_entry_delay_seconds:
                self.store.log('entry_expired', {'slug': market.slug})
                return event
            response = await self.executor.buy(market.token_for(signal.direction), decision.stake_usd)
            self.store.set_position(market.slug, {
                "token_id": market.token_for(signal.direction),
                "direction": signal.direction,
                "stake_usd": decision.stake_usd,
                "shares": decision.shares,
                "order_response": response,
            })
            self.store.log("live_order_submitted", {"market": market, "decision": decision, "response": response})
        elif decision.action == "buy":
            # Paper mode records the exact quote/risk calculation and never signs
            # or submits a CLOB order.
            self.store.set_position(market.slug, {
                "token_id": market.token_for(signal.direction),
                "direction": signal.direction,
                "stake_usd": decision.stake_usd,
                "shares": decision.shares,
                "paper": True,
            })
            self.store.log("paper_order", {"market": market, "decision": decision})
        return event

    async def run_forever(self) -> None:
        if self.executor is not None:
            await self.executor.connect()
        try:
            while True:
                try:
                    await self.run_once()
                except Exception:
                    logger.exception("bot tick failed; retrying")
                await asyncio.sleep(self.settings.poll_seconds)
        finally:
            if self.executor is not None:
                await self.executor.close()
