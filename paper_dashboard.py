"""Read-only paper ledger dashboard. No wallet or order capabilities."""
import base64
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB = Path(os.environ.get('PAPER_DB', '/data/capture.sqlite3'))


def snapshot(path=DB):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        recent = db.execute('SELECT received_ms,kind,slug FROM events ORDER BY id DESC LIMIT 1').fetchone()
        policies = [dict(r) for r in db.execute('''SELECT policy,
            SUM(status='pending') pending, SUM(status='skipped') skipped,
            SUM(status='settled') settled,
            SUM(status='settled' AND side=winner) wins,
            SUM(CASE WHEN status='settled' THEN pnl ELSE 0 END) pnl
            FROM paper GROUP BY policy ORDER BY policy''')]
        trades = []
        for row in db.execute('SELECT * FROM paper ORDER BY opened_ms DESC LIMIT 150'):
            item = dict(row)
            payload = json.loads(item.pop('payload'))
            fill = payload.get('fill') or {}
            item['reason'] = payload.get('reason')
            item['vwap'] = fill.get('vwap')
            item['fee'] = fill.get('fee_cash_equivalent')
            trades.append(item)
        sig = db.execute("SELECT slug,received_ms,payload FROM events WHERE kind='signals_frozen' ORDER BY id DESC LIMIT 1").fetchone()
        signal = None
        if sig:
            raw = json.loads(sig['payload'])
            signal = {'slug': sig['slug'], 'at': sig['received_ms'],
                      'direction': raw.get('signals', {}).get('dca'),
                      'source': raw.get('baseline', {}).get('source')}
        errors = [dict(r) for r in db.execute("SELECT received_ms,kind,slug,payload FROM events WHERE kind IN ('tick_error','settlement_error') ORDER BY id DESC LIMIT 5")]
        plan = db.execute("SELECT received_ms,payload FROM events WHERE kind='run_plan' ORDER BY id DESC LIMIT 1").fetchone()
        end_ms = None
        if plan:
            end_ms = plan['received_ms'] + json.loads(plan['payload']).get('duration_seconds', 0)*1000
        return {'now_ms': int(time.time()*1000), 'latest': dict(recent) if recent else None,
                'policies': policies, 'trades': trades, 'signal': signal,
                'errors': errors, 'planned_end_ms': end_ms}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected = 'Basic ' + base64.b64encode(('paper:' + self.server.password).encode()).decode()
        if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Polybot paper", charset="UTF-8"')
            self.end_headers()
            return
        if self.path not in ('/', '/api/status'):
            self.send_error(404)
            return
        try:
            body = (json.dumps(snapshot(), ensure_ascii=False).encode() if self.path == '/api/status'
                    else Path(__file__).with_name('paper_dashboard.html').read_bytes())
        except (sqlite3.Error, OSError, ValueError):
            self.send_error(503, 'Paper ledger temporarily unavailable')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8' if self.path == '/api/status' else 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == '__main__':
    password = Path(os.environ.get('PAPER_PASSWORD_FILE', '/run/secrets/paper_password')).read_text().strip()
    if len(password) < 16:
        raise SystemExit('Dashboard password must contain at least 16 characters')
    server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
    server.password = password
    print('Read-only paper dashboard listening on port 8080', flush=True)
    server.serve_forever()
