from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any

from .config import Settings
from .models import Book, Direction, Market, SignalSnapshot, TradeDecision


def _clamp_probability(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    return result if Decimal("0") < result < Decimal("1") else None


class RiskEngine:
    def __init__(self, settings: Settings, calibration: dict):
        self.settings = settings
        self.calibration = calibration

    def probability(self, signal: SignalSnapshot) -> Decimal | None:
        if not signal.direction or not signal.source:
            return None
        # Explicit approval prevents the 53-58% Lighter proxy study from being
        # mistaken for a calibrated Polymarket probability.
        if self.calibration.get("approved") is not True:
            return None
        # A calibration from fresh boundary signals does not estimate the
        # probability of a signal carried for another 5/10 minutes.
        if (self.settings.signal_policy != 'boundary'
                and self.calibration.get('signal_policy') != self.settings.signal_policy):
            return None
        table = self.calibration.get("probability_by_source")
        if not isinstance(table, dict):
            return None
        source = table.get(signal.source)
        if not isinstance(source, dict):
            return None
        return _clamp_probability(source.get(signal.direction))

    def legacy_approval(self, signal: SignalSnapshot) -> Decimal | None:
        """Return a descriptive historical rate only for the exact approved rule.

        This rate is logged for auditability.  It is not treated as a calibrated
        conditional probability and is not used for an edge threshold.
        """
        if self.settings.execution_strategy != "legacy_1230_ref85":
            return None
        expected = {
            "approved": True,
            "strategy_id": "dca_legacy_1230_ref85_v1",
            "signal_policy": "latest_5m",
            "signal_source": "lighter_1m_resampled",
            "entry_seconds": 750,
            "stake_usd": 20,
            "bankroll_usd": 50,
        }
        if any(self.calibration.get(key) != value for key, value in expected.items()):
            return None
        table = self.calibration.get("descriptive_win_rate_by_source")
        if not isinstance(table, dict):
            return None
        source = table.get(signal.source)
        return _clamp_probability(source.get(signal.direction)) if isinstance(source, dict) else None

    def decide(self, market: Market, book: Book, signal: SignalSnapshot) -> TradeDecision | None:
        if not signal.direction or not signal.source:
            return None
        ask = book.best_ask
        if ask is None or not (Decimal("0") < ask < Decimal("1")):
            return None
        spread = book.spread or Decimal("1")
        if spread > Decimal(str(self.settings.max_spread)):
            return TradeDecision(
                market.slug, signal.direction, signal.source, ask, spread,
                Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                Decimal("0"), Decimal("0"), "skip", "spread_above_limit",
            )
        if (self.settings.execution_strategy != "legacy_1230_ref85"
                and ask < Decimal(str(self.settings.min_entry_price))):
            return TradeDecision(
                market.slug, signal.direction, signal.source, ask, spread,
                Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                Decimal("0"), Decimal("0"), "skip", "price_below_entry_filter",
            )
        legacy_rate = self.legacy_approval(signal)
        if self.settings.execution_strategy == "legacy_1230_ref85":
            if legacy_rate is None:
                return TradeDecision(
                    market.slug, signal.direction, signal.source, ask, spread,
                    Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                    Decimal("0"), Decimal("0"), "paper_signal_only",
                    "legacy_strategy_missing_exact_approval",
                )
            fee_rate = Decimal(str(self.settings.taker_fee_rate)) if market.fees_enabled else Decimal("0")
            fee_per_share = fee_rate * ask * (Decimal("1") - ask)
            stake = min(Decimal(str(self.settings.live_fixed_stake_usd)),
                        Decimal(str(self.settings.max_stake_usd)))
            min_shares = market.min_order_size or book.min_order_size
            if min_shares and stake < min_shares * ask:
                stake = Decimal("0")
            stake = stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            shares = (stake / ask).quantize(Decimal("0.0001"), rounding=ROUND_DOWN) if stake else Decimal("0")
            if stake <= 0:
                return TradeDecision(
                    market.slug, signal.direction, signal.source, ask, spread,
                    legacy_rate, fee_per_share, Decimal("0"), Decimal("0"),
                    Decimal("0"), Decimal("0"), "skip", "stake_below_minimum",
                )
            # No fabricated model edge: execution follows the explicitly
            # approved historical threshold rule and frozen reference cap.
            return TradeDecision(
                market.slug, signal.direction, signal.source, ask, spread,
                legacy_rate, fee_per_share, Decimal("0"), stake, shares,
                Decimal("0"), "buy", "approved_legacy_threshold_rule",
            )

        p = self.probability(signal)
        if p is None:
            return TradeDecision(
                market.slug, signal.direction, signal.source, ask, spread,
                Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
                Decimal("0"), Decimal("0"), "paper_signal_only", "calibration_missing_or_not_approved",
            )

        fee_rate = Decimal(str(self.settings.taker_fee_rate)) if market.fees_enabled else Decimal("0")
        # Polymarket's documented fee is C * rate * p * (1-p), so this is the
        # per-share fee for a BUY at the current ask.
        fee_per_share = fee_rate * ask * (Decimal("1") - ask)
        edge = p - ask - fee_per_share
        if edge < Decimal(str(self.settings.min_edge)):
            return TradeDecision(
                market.slug, signal.direction, signal.source, ask, spread, p,
                fee_per_share, edge, Decimal("0"), Decimal("0"),
                Decimal("0"), "skip", "edge_below_limit",
            )

        win = Decimal("1") - ask - fee_per_share
        loss = ask + fee_per_share
        if win <= 0 or loss <= 0:
            return None
        kelly = (p * win - (Decimal("1") - p) * loss) / (win * loss)
        stake = min(
            Decimal(str(self.settings.max_stake_usd)),
            Decimal(str(self.settings.bankroll_usd))
            * Decimal(str(self.settings.kelly_fraction)) * max(Decimal("0"), kelly),
        )
        if self.settings.mode == "live" and self.settings.live_fixed_stake_usd:
            # A canary uses fixed sizing only after the positive-edge checks.
            stake = min(Decimal(str(self.settings.live_fixed_stake_usd)),
                        Decimal(str(self.settings.max_stake_usd)))
        # Respect both CLOB depth and minimum order size.  Do not round a
        # positive edge into an accidental over-spend.
        stake = min(stake, book.ask_size * ask)
        min_shares = market.min_order_size or book.min_order_size
        if min_shares:
            stake = max(stake, min_shares * ask) if stake >= min_shares * ask else Decimal("0")
        stake = stake.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if stake <= 0:
            return TradeDecision(
                market.slug, signal.direction, signal.source, ask, spread, p,
                fee_per_share, edge, Decimal("0"), Decimal("0"),
                Decimal("0"), "skip", "stake_below_depth_or_minimum",
            )
        shares = (stake / ask).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        expected = shares * edge
        return TradeDecision(
            market.slug, signal.direction, signal.source, ask, spread, p,
            fee_per_share, edge, stake, shares, expected, "buy", "positive_edge",
        )
