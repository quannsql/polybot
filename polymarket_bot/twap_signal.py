"""Exact-decimal, as-received Chainlink TWAP/spot signal; no candle indicators."""
from dataclasses import dataclass, asdict
from decimal import Decimal


@dataclass(frozen=True)
class Observation:
    observed_ms: int
    received_ms: int
    value: Decimal


class PriceBuffer:
    def __init__(self):
        self.points = {}
        self.conflicts = {}
        self.healthy_since_ms = None

    def reset(self, now_ms):
        self.points.clear()
        self.conflicts.clear()
        self.healthy_since_ms = now_ms

    def add(self, point):
        if not point.value.is_finite() or point.value <= 0:
            raise ValueError('Invalid oracle value')
        if point.observed_ms > point.received_ms + 1000:
            raise ValueError('Future oracle observation')
        previous = self.points.get(point.observed_ms)
        if previous is not None and previous.value != point.value:
            discovered = max(previous.received_ms,point.received_ms)
            self.conflicts[point.observed_ms] = min(self.conflicts.get(point.observed_ms,discovered),discovered)
        if previous is None or point.received_ms < previous.received_ms:
            self.points[point.observed_ms] = point
        cutoff = point.received_ms - 180000
        self.points = {t:p for t,p in self.points.items() if t >= cutoff}
        self.conflicts = {t:when for t,when in self.conflicts.items() if t >= cutoff}

    def asof(self, now_ms, max_age_ms=3000):
        eligible = [p for t,p in self.points.items() if now_ms-max_age_ms <= t <= now_ms
                    and p.received_ms <= now_ms and self.conflicts.get(t,now_ms+1)>now_ms]
        return max(eligible, key=lambda p:p.observed_ms) if eligible else None

    def valid_minute(self, now_ms):
        if self.healthy_since_ms is None or now_ms-self.healthy_since_ms < 60000:
            return False
        if any(now_ms-60000 <= t <= now_ms and known<=now_ms for t,known in self.conflicts.items()):
            return False
        stamps = sorted(t for t,p in self.points.items() if now_ms-60000 <= t <= now_ms and p.received_ms <= now_ms)
        return len(stamps) >= 30 and max((b-a for a,b in zip(stamps,stamps[1:])), default=60001) <= 5000


def decide(opening, twap, spot, decision_ms, minimum_lead_bps=Decimal('5'), fixed_side=None):
    """Snapshot input contains no final labels or Polymarket outcome prices."""
    if opening is None or not opening.value.is_finite() or opening.value <= 0 or opening.observed_ms != decision_ms//900000*900000 or opening.received_ms > opening.observed_ms+5000 or opening.received_ms > decision_ms:
        return None, 'opening_missing_late_or_invalid'
    if not twap.valid_minute(decision_ms) or not spot.valid_minute(decision_ms):
        return None, 'oracle_warmup_gap_or_conflict'
    current, raw = twap.asof(decision_ms), spot.asof(decision_ms)
    if current is None or raw is None:
        return None, 'oracle_stale_or_missing'
    lead = (current.value/opening.value-1)*10000
    side = 'up' if lead >= 0 else 'down'
    if fixed_side is not None and side != fixed_side:
        return None, 'direction_changed_before_submit'
    if abs(lead) < minimum_lead_bps:
        return None, 'twap_lead_below_5bp'
    sign = 1 if side == 'up' else -1
    if sign*(raw.value-current.value) < 0:
        return None, 'spot_not_supporting_twap'
    return dict(direction=side, decision_ms=decision_ms, opening=asdict(opening),
                twap=asdict(current), spot=asdict(raw), lead_bps=abs(lead),
                spot_minus_twap_bps=sign*(raw.value-current.value)/opening.value*10000), 'twap_spot_passed'
