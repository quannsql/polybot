import copy
import pytest

from polymarket_bot.advanced_research import (SCHEMA, OracleBuffer, oracle_kind,
    fit_calibration, empirical_probability, edge_fill, MakerProbe)
from collect_advanced_paper import flow_features

START = 1789020900
NOW = (START+630)*1000


def market():
    return {'start': START, 'end': START+900, 'rule_type': 'chainlink_twap',
            'rule_sha256': 'rule1', 'resolution_source': 'Chainlink',
            'raw': {'description': 'Chainlink BTC/USD https://data.chain.link/streams/btc-usd-twap-60s-streams'}}


def oracle():
    b = OracleBuffer()
    for i in range(66):
        t = NOW-(65-i)*1000
        b.add({'topic': 'crypto_prices_twap_sixty', 'payload': {'symbol': 'btc/usd',
               'timestamp': t, 'full_accuracy_value': str((60000+i)*10**18), 'value': 1}}, t)
    return b


def feature():
    return oracle().describe(market(), '60000', START*1000+1000, NOW, 'up')


def test_oracle_correct_feed_and_exact_value():
    f = feature()
    assert f['oracle_kind'] == 'twap60'
    assert f['oracle_value'] == '60065'
    assert f['signed_distance_bps'] > 0
    assert 'p_mean' not in f  # no uncalibrated Gaussian probability


def test_oracle_rejects_unknown_rule_stale_and_future_beat():
    m = market(); m['raw']['description'] = 'Unknown Chainlink TWAP'
    with pytest.raises(ValueError):
        oracle_kind(m)
    with pytest.raises(ValueError):
        oracle().describe(market(), 60000, NOW+1, NOW, 'up')
    with pytest.raises(ValueError):
        oracle().describe(market(), 60000, START*1000, NOW+6000, 'up')


def test_oracle_does_not_substitute_spot_for_twap():
    b = oracle(); b.points['spot'] = b.points.pop('twap60')
    with pytest.raises(ValueError):
        b.describe(market(), 60000, START*1000, NOW, 'up')


def test_oracle_future_observation_and_conflicting_duplicate():
    b = oracle()
    e = {'topic': 'crypto_prices_twap_sixty', 'payload': {'symbol': 'btc/usd', 'timestamp': NOW+1001, 'value': 1}}
    assert b.add(e, NOW) is False
    e['payload']['timestamp'] = NOW
    b.add(e, NOW)
    with pytest.raises(ValueError):
        b.describe(market(), 60000, START*1000, NOW, 'up')


def test_near_future_received_point_is_deferred_not_used():
    b = oracle()
    assert b.add({'topic': 'crypto_prices_twap_sixty', 'payload': {'symbol': 'btc/usd',
                  'timestamp': NOW+500, 'value': 90000}}, NOW)
    f = b.describe(market(), 60000, START*1000, NOW, 'up')
    assert f['oracle_value'] == '60065'


def training():
    f = feature()
    for k in ['oracle_observed_ms', 'oracle_received_ms', 'price_to_beat_received_ms']:
        f[k] = NOW-1000001
    return [{'schema': SCHEMA, 'settlement_status': 'confirmed', 'settlement_received_ms': NOW-1,
             'decision_ms': NOW-1000000, 'end_ms': NOW-10000, 'dca_active': True,
             'oracle': f, 'midpoint': .85, 'delay': 630, 'slug': f'old{i}', 'correct': True}
            for i in range(60)]


def test_calibration_deduplicates_markets_and_ignores_future_labels():
    rows = training()
    future = copy.deepcopy(rows)
    for r in future:
        r.update(slug='future'+r['slug'], settlement_received_ms=NOW+10000, correct=False)
    m = fit_calibration(rows+rows+future, NOW)
    cell = empirical_probability(m, feature(), .85, 630, NOW+1000, 'current')
    assert cell['n'] == 60
    assert cell['wins'] == 60
    with pytest.raises(ValueError):
        empirical_probability(m, feature(), .85, 630, NOW+1000, 'old1')
    with pytest.raises(ValueError):
        empirical_probability(m, feature(), .85, 630, NOW-1, 'current')


def test_empty_calibration_never_manufactures_probability():
    m = fit_calibration([], NOW)
    with pytest.raises(ValueError):
        empirical_probability(m, feature(), .85, 630, NOW+1000, 'current')


def test_training_rejects_features_received_after_decision():
    rows = training()
    for r in rows:
        r['oracle']['oracle_received_ms'] = r['decision_ms']+1
    assert fit_calibration(rows, NOW)['cells'] == {}


def book():
    return {'timestamp': str(NOW), 'asset_id': 'token', 'market': 'condition', 'min_order_size': '5',
            'bids': [{'price': '.84', 'size': '5'}], 'asks': [{'price': '.85', 'size': '100'}]}


def test_edge_gate_accounts_for_fee_and_depth():
    fee = {'status': 'known', 'rate': .07}
    fill = edge_fill(book(), fee, {'p_lower': .93}, NOW)
    assert fill['edge_per_share'] > .02
    assert fill['total_cost'] <= 10
    with pytest.raises(ValueError):
        edge_fill(book(), fee, {'p_lower': .87}, NOW)
    with pytest.raises(ValueError):
        edge_fill(book(), {'status': 'unknown'}, {'p_lower': .99}, NOW)


def trade(size=7, stamp=NOW+1000):
    return {'event_type': 'last_trade_price', 'asset_id': 'token', 'market': 'condition',
            'side': 'SELL', 'price': '.84', 'size': str(size), 'timestamp': str(stamp),
            'transaction_hash': str(stamp)}


def test_maker_queue_partial_dedup_latency_expiry_and_gap():
    p = MakerProbe(book(), NOW, NOW+300000)
    p.trade(trade(stamp=NOW+100), NOW+100)
    assert p.filled == 0
    p.trade(trade(), NOW+1000)
    assert p.filled == 2  # first five shares consumed public queue ahead
    p.trade(trade(), NOW+1000)
    assert p.filled == 2
    p.trade(trade(100, NOW+31000), NOW+31000)
    assert p.filled == 2
    p.invalid = True
    p.trade(trade(100, NOW+2000), NOW+2000)
    assert p.filled == 2


def test_maker_book_disappearance_is_not_fill():
    p = MakerProbe(book(), NOW, NOW+300000)
    e = trade(); e['event_type'] = 'price_change'
    p.trade(e, NOW+1000)
    assert p.filled == 0


def test_trade_flow_dedup_and_future_exclusion():
    e = trade(); future = trade(1000, NOW+90000)
    x = flow_features([(NOW+1000, e), (NOW+1000, e), (NOW+90000, future)], 'token', NOW+2000)
    assert x['reported_sell_shares_30s'] == 7
    assert x['trade_count_30s'] == 1
