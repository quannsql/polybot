"""Read-only paper ledger dashboard. No wallet or order capabilities."""
import base64
import hmac
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

DB = Path(os.environ.get('PAPER_DB', '/data/capture.sqlite3'))

LOGIN = '''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Đăng nhập Polybot</title>
<style>body{background:#0c1420;color:#e8edf4;font:16px system-ui;margin:0;padding:24px}main{max-width:380px;margin:8vh auto}input,button{font:inherit;box-sizing:border-box;width:100%;padding:14px;margin:8px 0 20px;border-radius:8px;border:1px solid #416184;background:#152235;color:white}button{background:#24587b;cursor:pointer}small{color:#a4b6cd}.error{color:#ffa598}input[type=checkbox]{width:auto;margin-right:8px}</style>
<main><h1>Polybot / Paper</h1><p>Theo dõi mô phỏng giao dịch</p>ERROR_PLACEHOLDER
<form method="post" action="/login"><label>Tài khoản<input name="username" value="paper" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>
<label>Mật khẩu<input id="password" name="password" type="password" autocomplete="current-password" autocapitalize="none" spellcheck="false" required></label>
<label><input type="checkbox" onclick="document.getElementById('password').type=this.checked?'text':'password'">Hiện mật khẩu</label><button>Đăng nhập</button></form><small>Chỉ xem dữ liệu paper. Phiên đăng nhập có hiệu lực 24 giờ.</small></main></html>'''


def session_token(password, expiry):
    stamp = str(expiry)
    signature = hmac.new(password.encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return stamp + '.' + signature


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
                      'reason': raw.get('baseline', {}).get('reason'),
                      'source': raw.get('baseline', {}).get('source')}
        errors = [dict(r) for r in db.execute("SELECT received_ms,kind,slug,payload FROM events WHERE kind IN ('tick_error','settlement_error') ORDER BY id DESC LIMIT 5")]
        plan = db.execute("SELECT received_ms,payload FROM events WHERE kind='run_plan' ORDER BY id DESC LIMIT 1").fetchone()
        end_ms = None
        protocol = {}
        if plan:
            run = json.loads(plan['payload'])
            end_ms = plan['received_ms'] + run.get('duration_seconds', 0)*1000
            protocol = run.get('protocol', {})
        robustness = None
        report_path=Path(os.environ.get('ROBUST_REPORT','/robust/robustness_report.json'))
        try:
            robustness=json.loads(report_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            pass
        return {'now_ms': int(time.time()*1000), 'latest': dict(recent) if recent else None,
                'policies': policies, 'trades': trades, 'signal': signal,
                'errors': errors, 'planned_end_ms': end_ms, 'robustness':robustness,
                'session': {k: protocol.get(k) for k in ('session_start_utc','session_end_utc','entry_seconds',
                                                       'signal_policy','signal_source','reference_source','minimum_reference')}}


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        expected = 'Basic ' + base64.b64encode(('paper:' + self.server.password).encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            return True
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookies['paper_session'].value
            expiry = int(token.split('.')[0])
            return time.time() < expiry <= time.time()+86401 and hmac.compare_digest(
                token, session_token(self.server.password, expiry))
        except (ValueError, KeyError):
            return False

    def login_page(self, error=False):
        message = '<p class="error">Tài khoản hoặc mật khẩu chưa đúng. Vui lòng thử lại.</p>' if error else ''
        body = LOGIN.replace('ERROR_PLACEHOLDER', message).encode()
        self.send_response(401 if error else 200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != '/login':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError()
            form = parse_qs(self.rfile.read(length).decode())
            username = form.get('username', [''])[0].strip()
            password = form.get('password', [''])[0].strip()
        except (ValueError, UnicodeError):
            self.send_error(400)
            return
        if username != 'paper' or not hmac.compare_digest(password, self.server.password):
            time.sleep(0.5)
            self.login_page(error=True)
            return
        token = session_token(self.server.password, int(time.time())+86400)
        self.send_response(303)
        self.send_header('Location', '/')
        self.send_header('Set-Cookie', 'paper_session='+token+'; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def do_GET(self):
        if self.path == '/login':
            self.login_page()
            return
        if not self.authorized():
            if self.path == '/api/status':
                self.send_error(401)
            else:
                self.send_response(303)
                self.send_header('Location', '/login')
                self.send_header('Cache-Control', 'no-store')
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
