"""Durable multi-market journal; never retry an ambiguous order automatically."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sqlite3

from .models import jsonable
from .twap_signal import Observation


def encoded(value):
    return json.dumps(jsonable(value), separators=(',',':'), allow_nan=False)


class TwapStore:
    def __init__(self, path, log_path, oracle_path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS openings(start_ms INTEGER PRIMARY KEY,value TEXT NOT NULL,received_ms INTEGER NOT NULL,valid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS signals(slug TEXT PRIMARY KEY,payload TEXT,reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,slug TEXT UNIQUE NOT NULL,created_ms INTEGER NOT NULL,day TEXT NOT NULL,side TEXT NOT NULL,budget TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,response TEXT NOT NULL DEFAULT '{}',won INTEGER,settled_ms INTEGER,redeem_status TEXT NOT NULL DEFAULT 'not_requested');
            CREATE TABLE IF NOT EXISTS legacy(slug TEXT PRIMARY KEY,payload TEXT NOT NULL,reconciled INTEGER NOT NULL DEFAULT 0);
        ''')
        self.handlers = []
        self.event_logger = self._logger(log_path,10_000_000,5)
        self.oracle_logger = self._logger(oracle_path,50_000_000,20)
        self.process_lock = None

    def _logger(self, path, size, backups):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path,maxBytes=size,backupCount=backups,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger = logging.Logger(str(path.resolve()),logging.INFO)
        logger.addHandler(handler); self.handlers.append(handler)
        return logger

    def log(self, event, payload):
        self.event_logger.info(encoded(dict(timestamp=datetime.now(timezone.utc),event=event,payload=payload)))

    def record_price(self, kind, point, origin):
        self.oracle_logger.info(encoded(dict(kind=kind,origin=origin,observed_ms=point.observed_ms,
            received_ms=point.received_ms,value=point.value,source='chainlink',window_seconds=60 if kind=='twap' else None)))

    def acquire_process_lock(self):
        path = self.path.with_suffix('.process.lock')
        handle = path.open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b'0'); handle.flush()
                handle.seek(0); msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,IOError):
            handle.close()
            raise RuntimeError('Another TWAP process already owns this journal') from None
        self.process_lock = handle

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def record_opening(self, point):
        if point.observed_ms % 900000:
            return
        previous = self.db.execute('SELECT * FROM openings WHERE start_ms=?',(point.observed_ms,)).fetchone()
        if previous and Decimal(previous['value']) != point.value:
            self.db.execute('UPDATE openings SET valid=0 WHERE start_ms=?',(point.observed_ms,))
            self.log('opening_conflict',dict(start_ms=point.observed_ms))
        elif previous is None and point.received_ms <= point.observed_ms+5000:
            self.db.execute('INSERT INTO openings VALUES(?,?,?,1)',(point.observed_ms,str(point.value),point.received_ms))
            self.log('opening_recorded',dict(start_ms=point.observed_ms,value=point.value,received_ms=point.received_ms))

    def opening(self, start_ms):
        row = self.db.execute('SELECT * FROM openings WHERE start_ms=? AND valid=1',(start_ms,)).fetchone()
        return Observation(start_ms,row['received_ms'],Decimal(row['value'])) if row else None

    def frozen(self, slug):
        row = self.db.execute('SELECT * FROM signals WHERE slug=?',(slug,)).fetchone()
        return dict(payload=json.loads(row['payload']) if row['payload'] else None,reason=row['reason']) if row else None

    def freeze(self, slug, payload, reason):
        self.db.execute('INSERT OR IGNORE INTO signals VALUES(?,?,?)',(slug,encoded(payload) if payload is not None else None,reason))
        return self.frozen(slug)

    def order(self, slug):
        row = self.db.execute('SELECT * FROM orders WHERE slug=?',(slug,)).fetchone()
        return dict(row) if row else None

    def orders(self, statuses=None):
        rows = [dict(r) for r in self.db.execute('SELECT * FROM orders ORDER BY id')]
        return [r for r in rows if statuses is None or r['status'] in statuses]

    def budget_check(self, now_ms, maximum, daily_stop=True):
        if len(self.orders()) >= maximum:
            return 'lifetime_submission_limit'
        if self.orders({'reserved','submitted','ambiguous','open'}):
            return 'pending_or_unresolved_position'
        if self.db.execute('SELECT 1 FROM legacy WHERE reconciled=0 LIMIT 1').fetchone():
            return 'legacy_attempt_needs_reconciliation'
        day = datetime.fromtimestamp(now_ms/1000,timezone.utc).strftime('%Y-%m-%d')
        if daily_stop and self.db.execute('SELECT 1 FROM orders WHERE day=? AND won=0 LIMIT 1',(day,)).fetchone():
            return 'daily_loss_stop_utc'
        return None

    def bind_account(self, wallet):
        wallet = wallet.lower()
        previous = self.db.execute("SELECT value FROM meta WHERE key='wallet'").fetchone()
        if previous and previous['value'] != wallet:
            raise RuntimeError('This TWAP journal belongs to a different wallet')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('wallet',?)",(wallet,))

    def reserve(self, slug, side, now_ms, budget, payload, maximum, daily_stop=True):
        with self.transaction():
            if self.db.execute('SELECT 1 FROM legacy WHERE slug=?',(slug,)).fetchone():
                raise RuntimeError('legacy_market_already_attempted')
            why = self.budget_check(now_ms,maximum,daily_stop)
            if why:
                raise RuntimeError(why)
            day = datetime.fromtimestamp(now_ms/1000,timezone.utc).strftime('%Y-%m-%d')
            cursor = self.db.execute('INSERT INTO orders(slug,created_ms,day,side,budget,payload,status) VALUES(?,?,?,?,?,?,?)',
                (slug,now_ms,day,side,str(budget),encoded(payload),'reserved'))
            return cursor.lastrowid

    def update(self, attempt_id, status, response=None):
        if response is None:
            self.db.execute('UPDATE orders SET status=? WHERE id=?',(status,attempt_id))
        else:
            self.db.execute('UPDATE orders SET status=?,response=? WHERE id=?',(status,encoded(response),attempt_id))

    def resolve(self, attempt_id, won, now_ms):
        self.db.execute('UPDATE orders SET status=?,won=?,settled_ms=? WHERE id=?',('resolved',int(won),now_ms,attempt_id))

    def redeem_status(self, attempt_id, status):
        self.db.execute('UPDATE orders SET redeem_status=? WHERE id=?',(status,attempt_id))

    def import_legacy(self, path):
        if self.db.execute("SELECT 1 FROM meta WHERE key='legacy_imported'").fetchone():
            return
        path = Path(path)
        lock = path.with_suffix(path.suffix+'.live-submit.lock')
        if not path.exists():
            if lock.exists():
                raise RuntimeError('Legacy submission lock exists without its state; restore/reconcile the old state first')
            return
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(state,dict) or not isinstance(state.get('live_attempts',[]),list)
                    or not all(isinstance(a,dict) for a in state.get('live_attempts',[]))
                    or not isinstance(state.get('positions',{}),dict)):
                raise ValueError()
        except (ValueError,OSError):
            raise RuntimeError('Unreadable legacy state; refusing to discard the previous live attempt') from None
        if lock.exists() and not state.get('live_attempts') and not state.get('positions'):
            raise RuntimeError('Legacy lock has no matching attempt; reconcile before switching journals')
        with self.transaction():
            attempts = list(state.get('live_attempts',[]))
            known = {a.get('market_slug') for a in attempts}
            for slug,position in state.get('positions',{}).items():
                if slug not in known:
                    attempts.append(dict(market_slug=slug,status='legacy_position',position=position))
            for attempt in attempts:
                slug = attempt.get('market_slug')
                if not isinstance(slug,str) or not slug.startswith('btc-updown-15m-'):
                    raise ValueError('Unrecognized legacy market identity')
                resolved = int(attempt.get('status') == 'rejected_or_unfilled')
                self.db.execute('INSERT OR IGNORE INTO legacy VALUES(?,?,?)',(slug,encoded(attempt),resolved))
            self.db.execute("INSERT INTO meta VALUES('legacy_imported',?)",(str(path),))
        self.log('legacy_imported',dict(attempts=len(state.get('live_attempts',[])),path=str(path)))

    def close(self):
        if self.process_lock:
            if os.name == 'nt':
                import msvcrt
                self.process_lock.seek(0); msvcrt.locking(self.process_lock.fileno(),msvcrt.LK_UNLCK,1)
            self.process_lock.close(); self.process_lock = None
        for handler in self.handlers:
            handler.close()
        self.db.close()
