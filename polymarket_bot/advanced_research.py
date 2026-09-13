"""Oracle/edge/microstructure research primitives. No signing or order APIs.

Probability is empirical and fail-closed on insufficient settled observations.
Maker fills are conservative queue scenarios, never exchange-confirmed fills.
"""
from collections import defaultdict, deque
from decimal import Decimal
import math
import numpy as np

from .actual_research import dec, buy_depth

SCHEMA = 'oracle_edge_v1'
TOPICS = {'crypto_prices_chainlink': 'spot', 'crypto_prices_twap_thirty': 'twap30',
          'crypto_prices_twap_sixty': 'twap60'}


def wilson_lower(wins, n):
    if not n:
        return 0.
    p = wins/n; z = 1.95996398454
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def oracle_kind(market):
    text = (market['raw'].get('description', '')+' '+market['resolution_source']).lower()
    if market['rule_type'] == 'chainlink_spot' and 'twap' not in text and 'time-weighted' not in text:
        return 'spot'
    if 'btc-usd-twap-60s' in text:
        return 'twap60'
    if 'btc-usd-twap-30s' in text:
        return 'twap30'
    raise ValueError('Unknown TWAP window: do not guess settlement feed')


class OracleBuffer:
    def __init__(self):
        self.points = defaultdict(lambda: deque(maxlen=7200))

    def add(self, event, received_ms):
        kind = TOPICS.get(event.get('topic'))
        p = event.get('payload', {})
        if not kind or p.get('symbol') != 'btc/usd' or 'timestamp' not in p:
            return False
        stamp = int(p['timestamp'])
        # CLOB /time is integer-second precision. Keep slightly future-stamped
        # arrivals, but describe() cannot use them until its as-of clock catches up.
        if stamp > received_ms+1000 or stamp < received_ms-30000:
            return False
        if 'full_accuracy_value' in p:
            value = Decimal(str(p['full_accuracy_value'])) / Decimal(10**18)
        else:
            value = dec(p.get('value'))
        if not value.is_finite() or value <= 0:
            return False
        # Conflicting duplicate observations invalidate the instant, not last-wins.
        existing = [x for x in self.points[kind] if x[0] == stamp]
        if existing and any(x[2] != value for x in existing):
            self.points[kind].append((stamp, received_ms, None))
            return False
        if existing:
            return False
        self.points[kind].append((stamp, received_ms, value))
        return True

    def describe(self, market, price_to_beat, beat_received_ms, now_ms, side):
        if side not in ('up', 'down') or not market['start']*1000 <= beat_received_ms <= now_ms:
            raise ValueError('Price-to-beat observation unavailable before decision')
        beat = dec(price_to_beat)
        if beat <= 0 or not market['start']*1000 < now_ms < market['end']*1000:
            raise ValueError('Outside active market or invalid price to beat')
        kind = oracle_kind(market)
        points = sorted([p for p in self.points[kind] if p[0] <= now_ms and p[1] <= now_ms], key=lambda p:p[0])
        if not points or now_ms-points[-1][0] > 5000 or points[-1][2] is None:
            raise ValueError('Missing, conflicting or stale oracle')
        recent = [p for p in points if p[0] >= now_ms-65000]
        if len(recent) < 30 or recent[-1][0]-recent[0][0] < 55000:
            raise ValueError('Oracle warmup: need >=55s and >=30 observations')
        if any(p[2] is None for p in recent) or max(np.diff([p[0] for p in recent])) > 5000:
            raise ValueError('Oracle gap/conflict: no interpolation across disconnect')
        elapsed = np.diff([p[0] for p in recent])/1000
        returns = np.diff(np.log([float(p[2]) for p in recent]))
        vol_per_s = float(np.sqrt(np.sum(returns**2)/np.sum(elapsed)))
        if vol_per_s <= 0 or not np.isfinite(vol_per_s):
            raise ValueError('Oracle volatility unavailable')
        distance = float(points[-1][2]/beat-1)
        remaining = (market['end']*1000-now_ms)/1000
        direction = 1 if side == 'up' else -1
        # TWAP observations overlap: z is only a feature, NOT a Gaussian win probability.
        z = direction*math.log(float(points[-1][2]/beat))/(vol_per_s*math.sqrt(remaining))
        return {'schema': SCHEMA, 'rule_hash': market['rule_sha256'], 'oracle_kind': kind,
                'oracle_observed_ms': points[-1][0], 'oracle_received_ms': points[-1][1],
                'price_to_beat': str(beat), 'price_to_beat_received_ms': beat_received_ms,
                'oracle_value': str(points[-1][2]), 'signed_distance_bps': direction*distance*1e4,
                'signed_z_feature': z, 'vol_per_second': vol_per_s, 'remaining_seconds': remaining,
                'warning': 'z is descriptive; empirical settlement calibration required, especially TWAP'}


def calibration_key(feature, midpoint, delay):
    z = feature['signed_z_feature']
    if not math.isfinite(z) or not 0 < midpoint < 1:
        raise ValueError('Invalid feature or midpoint')
    zbin = int(np.searchsorted([0., .5, 1., 2.], z, side='right'))
    return '|'.join(map(str, [feature['rule_hash'], feature['oracle_kind'],
                             int(delay), min(9, int(midpoint*10)), zbin]))


def fit_calibration(observations, fit_at_ms, min_samples=50):
    """Only DCA-side rows whose confirmed labels were RECEIVED before fit time."""
    groups = defaultdict(dict)
    for r in observations:
        oracle = r.get('oracle', {})
        if (r.get('schema') != SCHEMA or r.get('settlement_status') != 'confirmed'
                or not r.get('dca_active') or r['settlement_received_ms'] >= fit_at_ms
                or r['decision_ms'] >= r['end_ms'] or r['end_ms'] > r['settlement_received_ms']
                or any(oracle.get(k, float('inf')) > r['decision_ms'] for k in
                       ['oracle_observed_ms', 'oracle_received_ms', 'price_to_beat_received_ms'])):
            continue
        k = calibration_key(r['oracle'], r['midpoint'], r['delay'])
        market = r['slug']
        if market in groups[k] and groups[k][market] != bool(r['correct']):
            raise ValueError('Conflicting labels')
        groups[k][market] = bool(r['correct'])  # repeated polling never inflates n
    cells = {}
    for k, values in groups.items():
        n = len(values); wins = sum(values.values())
        cells[k] = {'n': n, 'wins': wins, 'p_mean': (wins+1)/(n+2),
                    'p_lower': wilson_lower(wins, n), 'market_ids': sorted(values)}
    return {'schema': SCHEMA, 'mode': 'research_paper_only', 'fit_at_ms': fit_at_ms,
            'expires_ms': fit_at_ms+86400000, 'min_samples': max(50, min_samples), 'cells': cells,
            'warning': 'Within-cell Wilson bound is not a guarantee; forward calibration still required.'}


def empirical_probability(model, feature, midpoint, delay, now_ms, slug):
    if model.get('schema') != SCHEMA or model.get('mode') != 'research_paper_only':
        raise ValueError('Unsupported calibration artifact')
    if not model['fit_at_ms'] < now_ms < model['expires_ms']:
        raise ValueError('Future or expired calibration')
    cell = model['cells'].get(calibration_key(feature, midpoint, delay))
    if not cell or cell['n'] < max(50, model['min_samples']):
        raise ValueError('Insufficient independent settled calibration markets')
    if (len(set(cell['market_ids'])) != cell['n'] or not 0 <= cell['wins'] <= cell['n']
            or abs(cell['p_lower']-wilson_lower(cell['wins'], cell['n'])) > 1e-12):
        raise ValueError('Inconsistent calibration counts or probability bound')
    if slug in cell['market_ids']:
        raise ValueError('Current market present in training labels')
    return cell


def book_features(book, now_ms):
    # Same documented process-clock tolerance as buy_depth (integer /time).
    if not -1000 <= now_ms-int(book['timestamp']) <= 5000:
        raise ValueError('Stale/future orderbook')
    bids = sorted([(dec(x['price']), dec(x['size'])) for x in book['bids']], reverse=True)
    asks = sorted([(dec(x['price']), dec(x['size'])) for x in book['asks']])
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        raise ValueError('Empty/crossed orderbook')
    if any(not 0 < p < 1 or s <= 0 for p,s in bids+asks):
        raise ValueError('Invalid price or size')
    bid, ask = bids[0][0], asks[0][0]
    b = sum(s for p,s in bids if p >= bid-Decimal('.02'))
    a = sum(s for p,s in asks if p <= ask+Decimal('.02'))
    return {'bid': float(bid), 'ask': float(ask), 'midpoint': float((bid+ask)/2),
            'timestamp_skew_ms': now_ms-int(book['timestamp']),
            'spread': float(ask-bid), 'depth_imbalance_2c': float((b-a)/(b+a)),
            'bid_shares_2c': float(b), 'ask_shares_2c': float(a)}


def edge_fill(book, fee, probability, now_ms, *, budget=10., min_edge=.02):
    micro = book_features(book, now_ms)
    if micro['spread'] > .03:
        raise ValueError('Spread exceeds research guard')
    lower = float(probability['p_lower'])
    if not 0 < lower < 1:
        raise ValueError('Invalid probability bound')
    # Price itself cannot exceed conservative probability minus the edge budget.
    fill = buy_depth(book, fee, budget=budget, max_price=lower-min_edge, now_ms=now_ms)
    edge = lower-fill['break_even_probability']
    if edge < min_edge:
        raise ValueError('No conservative edge after displayed depth and fees')
    return {**fill, 'p_lower': lower, 'edge_per_share': edge,
            'conservative_expected_pnl': fill['shares']*lower-fill['total_cost']}


class MakerProbe:
    """FIFO scenario using reported SELL trades at exact limit price only.

    Never infer fills from cancelled/disappearing book size. No rebate income.
    Any stream gap invalidates the scenario; real queue priority is unknown.
    """
    def __init__(self, book, now_ms, end_ms, budget=10.):
        f = book_features(book, now_ms)
        self.token = str(book['asset_id']); self.market = book['market']
        self.price = dec(f['bid']); self.shares = dec(budget)/self.price
        if self.shares < dec(book.get('min_order_size', 5)) or dec(budget) < dec(book.get('min_order_size', 5)):
            raise ValueError('Maker probe below conservative minimum')
        self.queue_ahead = sum(dec(x['size']) for x in book['bids'] if dec(x['price']) == self.price)
        self.placed_ms = now_ms; self.active_ms = now_ms+250
        self.expires_ms = min(now_ms+30000, end_ms-10000)
        if self.expires_ms <= self.active_ms:
            raise ValueError('Too late for maker probe')
        self.filled = Decimal(0); self.seen = set(); self.invalid = False

    def trade(self, event, received_ms):
        if (self.invalid or event.get('event_type') != 'last_trade_price'
                or str(event.get('asset_id')) != self.token or event.get('market') != self.market
                or event.get('side') != 'SELL'):
            return
        at = int(event['timestamp'])
        if not self.active_ms <= at <= received_ms <= self.expires_ms:
            return
        if dec(event['price']) != self.price:
            return
        size = dec(event['size'])
        if size <= 0:
            return
        key = (event.get('transaction_hash'), at, str(size), str(self.price))
        if key in self.seen:
            return
        self.seen.add(key)
        consumed = min(size, self.queue_ahead)
        self.queue_ahead -= consumed
        self.filled += min(size-consumed, self.shares-self.filled)

    def summary(self):
        return {'token': self.token, 'market': self.market, 'price': str(self.price),
                'placed_ms': self.placed_ms, 'expires_ms': self.expires_ms,
                'shares_requested': str(self.shares), 'shares_scenario_filled': str(self.filled),
                'queue_ahead_remaining': str(self.queue_ahead), 'invalidated_by_gap': self.invalid,
                'kind': 'maker_queue_scenario_NOT_actual_fill', 'fee_assumption': 'maker zero; no rebates'}
