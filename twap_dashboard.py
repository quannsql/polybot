"""Read-only TWAP dashboard for the bot's SQLite journal and JSONL telemetry."""
import argparse
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time


ASSETS = Path(__file__).with_name('twap_web')
MARKET = re.compile(r'btc-updown-15m-[0-9]{1,12}')
ORDER_STATES = {'reserved', 'submitted', 'ambiguous', 'open', 'resolved',
                'rejected', 'aborted_before_submit'}
REDEEM_STATES = {'not_requested', 'started', 'confirmed', 'ambiguous_check_wallet',
                 'zero_token_balance_or_already_redeemed'}
EVENTS = {
    'twap_started', 'polygon_rpc_ready', 'opening_recorded', 'opening_conflict',
    'oracle_snapshot_or_recovery', 'oracle_wrong_source_or_window',
    'oracle_client_queue_drop', 'oracle_stream_disconnected', 'legacy_imported',
    'twap_frozen_signal', 'twap_signal_skip', 'twap_budget_skip', 'twap_entry_skip',
    'twap_recheck_skip', 'twap_final_signal_or_deadline_skip', 'twap_market_unavailable',
    'twap_live_intent', 'twap_ambiguous_post', 'twap_order_result',
    'twap_fill_awaiting_reconciliation', 'twap_resolved', 'twap_redeemed',
    'twap_redeem_needs_review', 'twap_tick_error', 'twap_paper_candidate',
}
REASONS = {
    'opening_missing_late_or_invalid', 'oracle_warmup_gap_or_conflict', 'oracle_stale_or_missing',
    'direction_changed_before_submit', 'twap_lead_below_5bp', 'spot_not_supporting_twap',
    'legacy_market_already_attempted', 'official_opening_disagrees_with_recorded_twap',
    'reference_missing_stale_or_below_085', 'reference_plus_1c_ge_one', 'invalid_tick_rounded_cap',
    'missing_book_side', 'invalid_book_level', 'wrong_book_asset', 'missing_book_timestamp',
    'stale_book_or_slow_request', 'one_sided_or_crossed_book', 'ask_above_frozen_reference_cap',
    'shares_below_venue_minimum', 'insufficient_haircut_depth_inside_cap', 'winning_margin_too_small',
    'signed_order_identity_or_type_mismatch', 'signed_order_uses_wrong_wallet',
    'invalid_signed_amounts', 'signed_price_exceeds_cap', 'unexpected_builder_fee_not_supported',
    'signed_cash_plus_metadata_fee_exceeds_20', 'network_geoblock_rejected',
    'market_tick_tokens_or_fee_changed_before_post', 'market_not_accepting_orders',
    'lifetime_submission_limit', 'pending_or_unresolved_position',
    'legacy_attempt_needs_reconciliation', 'daily_loss_stop_utc',
    'unknown_or_disagreeing_fee_schedule', 'unsupported_tick_size',
    'unsupported_settlement_stream_or_market_version', 'market_is_not_verified_btc15m_twap60',
}


def object_json(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return int(parsed.timestamp() * 1000) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def market_slug(value):
    return value if isinstance(value, str) and MARKET.fullmatch(value) else None


def tail_bytes(path, limit):
    try:
        with path.open('rb') as stream:
            length = stream.seek(0, 2)
            stream.seek(max(0, length - limit))
            if length > limit:
                stream.readline(limit)
            return stream.read(limit)
    except OSError:
        return b''


def records(path, limit):
    current = tail_bytes(path, limit)
    previous = tail_bytes(path.with_name(path.name + '.1'), limit - len(current)) if len(current) < limit else b''
    for chunk in (previous, current):
        for line in chunk.splitlines(keepends=True):
            if line.endswith(b'\n'):
                row = object_json(line)
                if row:
                    yield row


def read_journal(path, start_ms):
    journal = {'state': 'missing', 'orders': [], 'totals': None, 'opening': None}
    if not path.is_file():
        return journal
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.5)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            totals = dict(db.execute('''SELECT COUNT(*) AS attempts,
                COUNT(CASE WHEN status='open' THEN 1 END) AS open_positions,
                COUNT(CASE WHEN status IN ('reserved','submitted','ambiguous') THEN 1 END) AS pending,
                COUNT(CASE WHEN status='resolved' AND won=1 THEN 1 END) AS wins,
                COUNT(CASE WHEN status='resolved' AND won=0 THEN 1 END) AS losses FROM orders''').fetchone())
            totals['legacy_pending'] = db.execute('SELECT COUNT(*) FROM legacy WHERE reconciled=0').fetchone()[0]
            opening = db.execute('SELECT value FROM openings WHERE start_ms=? AND valid=1', (start_ms,)).fetchone()
            orders = []
            for row in db.execute('''SELECT id,slug,created_ms,side,budget,status,won,settled_ms,
                    redeem_status,payload FROM orders ORDER BY id DESC LIMIT 200'''):
                order = dict(row)
                order['cap'] = number(object_json(order.pop('payload')).get('cap'))
                order['slug'] = market_slug(order['slug'])
                order['budget'] = number(order['budget'])
                order['side'] = order['side'] if order['side'] in {'up', 'down'} else None
                order['status'] = order['status'] if order['status'] in ORDER_STATES else 'unknown'
                order['redeem_status'] = order['redeem_status'] if order['redeem_status'] in REDEEM_STATES else 'unknown'
                orders.append(order)
            return {'state': 'ready', 'orders': orders, 'totals': totals,
                    'opening': number(opening['value']) if opening else None}
    except (sqlite3.Error, OSError):
        journal['state'] = 'unavailable'
        return journal


def read_decisions(path, now_ms):
    heartbeat = None
    events = []
    for row in records(path, 524288):
        at = timestamp(row.get('timestamp'))
        payload = row.get('payload')
        event = row.get('event')
        if at is None or not isinstance(payload, dict) or not isinstance(event, str):
            continue
        if event == 'twap_heartbeat':
            heartbeat = {'at': at, 'age_seconds': max(0, (now_ms - at) // 1000),
                         **{field: payload.get(field) is True for field in (
                             'clock_ok', 'feed_connected', 'twap_fresh', 'spot_fresh', 'opening_known')}}
        elif event in EVENTS:
            reason = payload.get('reason')
            events.append({'at': at, 'event': event, 'slug': market_slug(payload.get('slug')),
                           'reason': reason if isinstance(reason, str) and reason in REASONS else None,
                           'attempt_id': payload.get('attempt_id') if type(payload.get('attempt_id')) is int else None,
                           'won': payload.get('won') if type(payload.get('won')) is bool else None})
    return heartbeat, list(reversed(events[-80:]))


def read_prices(path, now_ms):
    buckets = {'twap': {}, 'spot': {}}
    cutoff = now_ms - 30 * 60 * 1000
    for row in records(path, 1_048_576):
        kind, observed, received = (row.get(key) for key in ('kind', 'observed_ms', 'received_ms'))
        if (kind not in ('twap', 'spot') or row.get('source') != 'chainlink'
                or row.get('origin') != 'update' or (kind == 'twap' and row.get('window_seconds') != 60)
                or type(observed) is not int or type(received) is not int
                or not cutoff <= observed <= received + 1000 or received > now_ms):
            continue
        value = number(row.get('value'))
        if value is None or value <= 0:
            continue
        bucket = observed // 5000
        previous = buckets[kind].get(bucket)
        if previous is None or observed > previous[0]:
            buckets[kind][bucket] = [observed, value]
    return {kind: sorted(points.values()) for kind, points in buckets.items()}


def snapshot(db_path, decisions, oracle, max_orders, entry_end_seconds, now_ms=None):
    now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    start_ms = now_ms // 900000 * 900000
    heartbeat, events = read_decisions(decisions, now_ms)
    return {'now_ms': now_ms, 'heartbeat': heartbeat, 'events': events,
            'journal': read_journal(db_path, start_ms), 'prices': read_prices(oracle, now_ms),
            'limits': {'max_orders': max_orders},
            'market': {'start_ms': start_ms, 'entry_ms': start_ms + 840000,
                       'entry_end_ms': start_ms + entry_end_seconds * 1000, 'end_ms': start_ms + 900000}}


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get('Host', '').split(':', 1)[0] not in {'127.0.0.1', 'localhost'}:
            self.send_error(403)
            return
        if self.path == '/api/status':
            self.send_content(self.server.status_json(), 'application/json')
            return
        assets = {'/': ('index.html', 'text/html'), '/dashboard.css': ('dashboard.css', 'text/css'),
                  '/dashboard.js': ('dashboard.js', 'text/javascript'),
                  '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if self.path in assets:
            filename, content_type = assets[self.path]
            self.send_content((ASSETS / filename).read_bytes(), content_type)
        elif self.path == '/health':
            self.send_content(b'ok', 'text/plain')
        else:
            self.send_error(404)

    def send_content(self, data, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, port, options):
        super().__init__(('127.0.0.1', port), DashboardHandler)
        self.options = options
        self.cache_at = 0
        self.cache = b''
        self.cache_lock = threading.Lock()

    def status_json(self):
        with self.cache_lock:
            if time.monotonic() - self.cache_at >= 4 or not self.cache:
                self.cache = json.dumps(snapshot(**self.options), allow_nan=False).encode('utf-8')
                self.cache_at = time.monotonic()
            return self.cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('/data/twap_state.sqlite3'))
    parser.add_argument('--decisions', type=Path, default=Path('/data/twap_decisions.jsonl'))
    parser.add_argument('--oracle', type=Path, default=Path('/data/twap_oracle.jsonl'))
    parser.add_argument('--max-orders', type=int, default=5)
    parser.add_argument('--entry-end-seconds', type=int, default=845)
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    options = dict(db_path=args.db, decisions=args.decisions, oracle=args.oracle,
                   max_orders=args.max_orders, entry_end_seconds=args.entry_end_seconds)
    with DashboardServer(args.port, options) as server:
        print(f'TWAP dashboard listening on 127.0.0.1:{server.server_port}', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
