from datetime import datetime, timezone
from decimal import Decimal
import json

from polymarket_bot.twap_signal import Observation
from polymarket_bot.twap_store import TwapStore
from twap_dashboard import snapshot


def test_dashboard_reads_live_wal_and_projects_safe_fields(tmp_path):
    db = tmp_path / 'state.sqlite3'
    decisions = tmp_path / 'decisions.jsonl'
    oracle = tmp_path / 'oracle.jsonl'
    start = 1794182400000
    now = start + 840000
    slug = f'btc-updown-15m-{start // 1000}'
    store = TwapStore(db, decisions, oracle)
    try:
        store.record_opening(Observation(start, start + 100, Decimal('90000')))
        attempt = store.reserve(slug, 'up', now, Decimal('20'), {'cap': '.96', 'signer': 'private-fixture'}, 5)
        store.update(attempt, 'open', {'signature': 'private-fixture'})
        store.log('twap_entry_skip', {'slug': slug, 'reason': 'unexpected external error private-fixture'})
        store.record_price('twap', Observation(now - 1000, now, Decimal('90031')), 'update')
        store.record_price('spot', Observation(now - 1000, now, Decimal('90036')), 'subscribe')
        report = snapshot(db, decisions, oracle, 5, 845, now)
        assert report['journal']['state'] == 'ready'
        assert report['journal']['totals']['open_positions'] == 1
        assert report['journal']['orders'][0]['cap'] == .96
        assert report['journal']['opening'] == 90000
        assert report['prices'] == {'twap': [[now - 1000, 90031]], 'spot': []}
        assert report['events'][0]['event'] == 'twap_entry_skip'
        assert 'private-fixture' not in json.dumps(report)

        store.resolve(attempt, True, now + 60000)
        report = snapshot(db, decisions, oracle, 5, 845, now + 60000)
        assert report['journal']['totals']['wins'] == 1
        assert report['journal']['totals']['open_positions'] == 0
    finally:
        store.close()


def test_dashboard_keeps_rotated_heartbeat_and_ignores_incomplete_log_line(tmp_path):
    decisions = tmp_path / 'decisions.jsonl'
    now = 1794182400000
    previous = decisions.with_name(decisions.name + '.1')
    previous.write_text(json.dumps({
        'timestamp': datetime.fromtimestamp(now / 1000 - 15, timezone.utc).isoformat(),
        'event': 'twap_heartbeat', 'payload': {'clock_ok': True, 'twap_fresh': True},
    }) + '\n', encoding='utf-8')
    decisions.write_text('{"event":"twap_started","payload":', encoding='utf-8')
    report = snapshot(tmp_path / 'missing.sqlite3', decisions, tmp_path / 'oracle.jsonl', 5, 845, now)
    assert report['heartbeat']['age_seconds'] == 15
    assert report['events'] == []
    assert report['journal']['state'] == 'missing'
    assert report['journal']['totals'] is None
