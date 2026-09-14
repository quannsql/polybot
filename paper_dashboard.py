"""Authenticated, read-only dashboard for paper experiments and live canary state."""
import base64
from collections import Counter
from datetime import datetime
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import parse_qs

DB = Path(os.environ.get('PAPER_DB', '/data/capture.sqlite3'))
ROBUST_REPORT = Path(os.environ.get('ROBUST_REPORT', '/robust/robustness_report.json'))
LIVE_DIR = Path(os.environ.get('LIVE_DATA_DIR', '/live'))

LOGIN = '''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Đăng nhập · Polybot Command Center</title>
<style>:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}*{box-sizing:border-box}body{min-height:100vh;margin:0;color:#eef2ff;background:#07090f;background-image:radial-gradient(circle at 15% 0,#17255488,transparent 34%),radial-gradient(circle at 90% 15%,#064e3b66,transparent 30%);display:grid;place-items:center;padding:22px}.shell{width:min(430px,100%)}.brand{display:flex;align-items:center;gap:13px;margin-bottom:28px}.mark{width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#34d399,#22d3ee);display:grid;place-items:center;color:#04110e;font-weight:900;box-shadow:0 12px 35px #10b98133}.brand b{font-size:19px}.brand span{display:block;color:#7d8ba6;font-size:12px;margin-top:2px}.panel{background:#0e121dcc;border:1px solid #20293a;border-radius:24px;padding:30px;box-shadow:0 28px 80px #0009;backdrop-filter:blur(18px)}h1{font-size:27px;letter-spacing:-.04em;margin:0 0 8px}p{color:#8f9bb2;line-height:1.55;margin:0 0 24px}.field{display:block;color:#aeb8ca;font-size:13px;font-weight:600;margin-top:16px}input{font:inherit;width:100%;margin-top:8px;padding:13px 14px;color:#eef2ff;background:#090d16;border:1px solid #273247;border-radius:12px;outline:none;transition:.2s}input:focus{border-color:#34d399;box-shadow:0 0 0 3px #34d39918}.password{position:relative}.password button{position:absolute;right:8px;bottom:7px;width:auto;padding:7px 9px;background:transparent;color:#8f9bb2;border:0}.submit{font:inherit;font-weight:750;width:100%;margin-top:24px;padding:13px;border:0;border-radius:12px;color:#032019;background:linear-gradient(135deg,#34d399,#22d3ee);cursor:pointer;box-shadow:0 12px 28px #10b98122}.meta{text-align:center;color:#657188;font-size:12px;margin-top:18px}.error{background:#3f1722;color:#fda4af;border:1px solid #7f1d35;padding:11px 13px;border-radius:11px;margin-bottom:14px;font-size:13px}</style>
<main class="shell"><div class="brand"><div class="mark">P</div><div><b>Polybot</b><span>Command Center</span></div></div><section class="panel"><h1>Chào mừng trở lại</h1><p>Đăng nhập để theo dõi chiến lược, paper execution và live canary.</p>ERROR_PLACEHOLDER<form method="post" action="/login"><label class="field">Tài khoản<input name="username" value="paper" autocomplete="username" autocapitalize="none" spellcheck="false" required></label><label class="field">Mật khẩu<div class="password"><input id="password" name="password" type="password" autocomplete="current-password" required><button type="button" onclick="const p=document.getElementById('password');p.type=p.type==='password'?'text':'password';this.textContent=p.type==='password'?'Hiện':'Ẩn'">Hiện</button></div></label><button class="submit">Mở dashboard</button></form><div class="meta">Read-only · Phiên bảo mật 24 giờ</div></section></main></html>'''


def session_token(password, expiry):
    stamp = str(expiry)
    signature = hmac.new(password.encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return stamp + '.' + signature


def _json(value, default=None):
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _read_tail_jsonl(path, maximum=300):
    try:
        with path.open('rb') as handle:
            handle.seek(0, 2); size = handle.tell()
            handle.seek(max(0, size-262144))
            if size > 262144: handle.readline()
            lines = handle.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-maximum:]:
        item = _json(line)
        if isinstance(item, dict): rows.append(item)
    return rows


def live_snapshot(directory=LIVE_DIR, now_ms=None):
    now_ms = now_ms or int(time.time()*1000)
    state_path = directory/'live_state.json'
    state = _json(state_path.read_text(encoding='utf-8'), {}) if state_path.exists() else {}
    events = _read_tail_jsonl(directory/'live_decisions.jsonl')
    heartbeat = next((e for e in reversed(events)
                      if e.get('event') in {'bot_heartbeat','bot_started'}), None)
    heartbeat_ms = None
    if heartbeat:
        try:
            heartbeat_ms = int(datetime.fromisoformat(
                heartbeat['timestamp'].replace('Z','+00:00')).timestamp()*1000)
        except (KeyError, TypeError, ValueError):
            pass
    age = (now_ms-heartbeat_ms)/1000 if heartbeat_ms else None
    health = ('online' if age is not None and age < 100 else
              'stale' if age is not None and age < 240 else 'starting')
    attempts = []
    for item in state.get('live_attempts', []) if isinstance(state, dict) else []:
        payload = item.get('payload') if isinstance(item.get('payload'), dict) else {}
        result = item.get('result') if isinstance(item.get('result'), dict) else {}
        attempts.append({k:item.get(k) for k in
                         ('attempt_id','market_slug','status','created_at','finished_at')} | {
            'direction':payload.get('direction'), 'stake_usd':payload.get('stake_usd'),
            'max_price':payload.get('max_price'), 'filled':result.get('filled'),
            'settlement_confirmed':result.get('settlement_confirmed'),
            'error':result.get('error'),
        })
    positions = []
    for slug, item in (state.get('positions', {}) if isinstance(state, dict) else {}).items():
        if isinstance(item, dict):
            positions.append({'market_slug':slug, **{k:item.get(k) for k in
                ('direction','stake_usd','shares','making_amount')}})
    error_events = [e for e in events if any(word in str(e.get('event',''))
                    for word in ('error','failed','unavailable','blocked'))][-8:]
    return {
        'enabled':os.environ.get('LIVE_MODE_ENABLED','0') == '1',
        'health':health, 'heartbeat_ms':heartbeat_ms, 'heartbeat_age_seconds':age,
        'latest_event':events[-1] if events else None,
        'event_counts':dict(Counter(e.get('event','unknown') for e in events)),
        'attempts':list(reversed(attempts)), 'positions':positions,
        'errors':list(reversed(error_events)),
        'config':{
            'strategy':os.environ.get('LIVE_STRATEGY','DCA legacy · 12:30'),
            'stake_usd':float(os.environ.get('LIVE_STAKE_USD','20')),
            'bankroll_usd':float(os.environ.get('LIVE_BANKROLL_USD','50')),
            'entry_seconds':int(os.environ.get('LIVE_ENTRY_SECONDS','750')),
            'max_attempts':int(os.environ.get('LIVE_MAX_ATTEMPTS','1')),
        },
    }


def snapshot(path=DB, robust_path=ROBUST_REPORT, live_dir=LIVE_DIR):
    now_ms = int(time.time()*1000)
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        recent = db.execute('SELECT received_ms,kind,slug FROM events ORDER BY id DESC LIMIT 1').fetchone()
        event_counts = dict(db.execute('SELECT kind,count(*) FROM events GROUP BY kind'))
        policies = [dict(r) for r in db.execute('''SELECT policy,
            SUM(status='pending') pending, SUM(status='skipped') skipped,
            SUM(status='settled') settled,
            SUM(status='settled' AND side=winner) wins,
            SUM(CASE WHEN status='settled' THEN pnl ELSE 0 END) pnl
            FROM paper GROUP BY policy ORDER BY policy''')]
        trades = []; reasons = Counter()
        for row in db.execute('SELECT * FROM paper ORDER BY opened_ms DESC LIMIT 250'):
            item = dict(row); payload = _json(item.pop('payload'), {}) or {}
            fill = payload.get('fill') or {}
            item['reason'] = payload.get('reason'); item['vwap'] = fill.get('vwap')
            item['fee'] = fill.get('fee_cash_equivalent')
            if item['status'] == 'skipped': reasons[item['reason'] or 'Không rõ lý do'] += 1
            trades.append(item)
        sig = db.execute("SELECT slug,received_ms,payload FROM events WHERE kind='signals_frozen' ORDER BY id DESC LIMIT 1").fetchone()
        signal = None
        if sig:
            raw = _json(sig['payload'], {}) or {}
            signal = {'slug':sig['slug'], 'at':sig['received_ms'],
                'direction':raw.get('signals',{}).get('dca'),
                'reason':raw.get('baseline',{}).get('reason'),
                'source':raw.get('baseline',{}).get('source')}
        errors = [dict(r) for r in db.execute("SELECT received_ms,kind,slug,payload FROM events WHERE kind IN ('tick_error','settlement_error') ORDER BY id DESC LIMIT 8")]
        plan = db.execute("SELECT received_ms,payload FROM events WHERE kind='run_plan' ORDER BY id DESC LIMIT 1").fetchone()
        end_ms = None; protocol = {}
        if plan:
            run = _json(plan['payload'], {}) or {}; protocol = run.get('protocol', {})
            end_ms = plan['received_ms'] + run.get('duration_seconds',0)*1000
        primary_id = os.environ.get('PAPER_PRIMARY_POLICY','dca_500ms_depth100')
        primary = next((p for p in policies if p['policy']==primary_id), policies[0] if policies else None)
        curve = []
        if primary:
            running = 0.
            for row in db.execute("SELECT opened_ms,pnl FROM paper WHERE policy=? AND status='settled' ORDER BY opened_ms LIMIT 1000", (primary['policy'],)):
                running += float(row['pnl'] or 0); curve.append({'at':row['opened_ms'],'pnl':running})
        robustness = None
        try: robustness = json.loads(robust_path.read_text(encoding='utf-8'))
        except (OSError, ValueError): pass
        return {'now_ms':now_ms, 'latest':dict(recent) if recent else None,
            'event_counts':event_counts, 'policies':policies, 'trades':trades,
            'primary':primary, 'equity_curve':curve, 'skip_reasons':reasons.most_common(8),
            'signal':signal, 'errors':errors, 'planned_end_ms':end_ms,
            'robustness':robustness, 'live':live_snapshot(live_dir,now_ms),
            'session':{k:protocol.get(k) for k in ('session_start_utc','session_end_utc','entry_seconds',
                'signal_policy','signal_source','reference_source','minimum_reference','budget_usd','initial_bankroll_usd')}}


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        expected = 'Basic '+base64.b64encode(('paper:'+self.server.password).encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization',''),expected): return True
        try:
            cookies = SimpleCookie(self.headers.get('Cookie','')); token = cookies['paper_session'].value
            expiry = int(token.split('.')[0])
            return time.time()<expiry<=time.time()+86401 and hmac.compare_digest(
                token,session_token(self.server.password,expiry))
        except (ValueError,KeyError): return False

    def _headers(self, content_type, length=0):
        self.send_header('Content-Type',content_type); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        if length: self.send_header('Content-Length',str(length))

    def login_page(self,error=False):
        message = '<div class="error">Tài khoản hoặc mật khẩu chưa đúng.</div>' if error else ''
        body = LOGIN.replace('ERROR_PLACEHOLDER',message).encode()
        self.send_response(401 if error else 200); self._headers('text/html; charset=utf-8',len(body))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if self.path!='/login': self.send_error(404); return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096: raise ValueError()
            form=parse_qs(self.rfile.read(length).decode()); username=form.get('username',[''])[0].strip(); password=form.get('password',[''])[0].strip()
        except (ValueError,UnicodeError): self.send_error(400); return
        if username!='paper' or not hmac.compare_digest(password,self.server.password):
            time.sleep(.5); self.login_page(error=True); return
        token=session_token(self.server.password,int(time.time())+86400)
        self.send_response(303); self.send_header('Location','/'); self.send_header('Set-Cookie','paper_session='+token+'; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax')
        self._headers('text/plain; charset=utf-8'); self.end_headers()

    def do_GET(self):
        if self.path=='/login': self.login_page(); return
        if self.path=='/logout':
            self.send_response(303); self.send_header('Location','/login'); self.send_header('Set-Cookie','paper_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax'); self._headers('text/plain; charset=utf-8'); self.end_headers(); return
        if not self.authorized():
            if self.path=='/api/status': self.send_error(401)
            else: self.send_response(303); self.send_header('Location','/login'); self._headers('text/plain; charset=utf-8'); self.end_headers()
            return
        if self.path not in ('/','/api/status'): self.send_error(404); return
        try:
            body=(json.dumps(snapshot(),ensure_ascii=False).encode() if self.path=='/api/status' else Path(__file__).with_name('paper_dashboard.html').read_bytes())
        except (sqlite3.Error,OSError,ValueError): self.send_error(503,'Dashboard data temporarily unavailable'); return
        self.send_response(200); self._headers('application/json; charset=utf-8' if self.path=='/api/status' else 'text/html; charset=utf-8',len(body)); self.end_headers(); self.wfile.write(body)

    def log_message(self,fmt,*args): pass


if __name__=='__main__':
    password=Path(os.environ.get('PAPER_PASSWORD_FILE','/run/secrets/paper_password')).read_text().strip()
    if len(password)<16: raise SystemExit('Dashboard password must contain at least 16 characters')
    server=ThreadingHTTPServer(('0.0.0.0',8080),Handler); server.password=password
    print('Polybot read-only command center listening on port 8080',flush=True); server.serve_forever()
