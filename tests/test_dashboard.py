import json
from pathlib import Path
import sqlite3
import time

from paper_dashboard import live_snapshot, session_token, snapshot


def database(path: Path):
    db = sqlite3.connect(path)
    db.executescript('''
      CREATE TABLE events (id INTEGER PRIMARY KEY, received_ms INTEGER, kind TEXT, slug TEXT, payload TEXT);
      CREATE TABLE paper (slug TEXT, policy TEXT, side TEXT, opened_ms INTEGER,
        shares REAL, cost REAL, status TEXT, winner TEXT, pnl REAL, payload TEXT);
    ''')
    now = int(time.time()*1000)
    db.execute('INSERT INTO events VALUES(1,?,?,?,?)', (now, 'run_plan', None,
        json.dumps({'duration_seconds':3600,'protocol':{'entry_seconds':690,'budget_usd':30}})))
    db.execute('INSERT INTO events VALUES(2,?,?,?,?)', (now, 'signals_frozen', 'btc-updown-15m-1',
        json.dumps({'signals':{'dca':'down'},'baseline':{'source':'main_5m','reason':'test'}})))
    fill = {'fill':{'vwap':.91,'fee_cash_equivalent':.1},'reason':None}
    db.execute('INSERT INTO paper VALUES(?,?,?,?,?,?,?,?,?,?)',
        ('btc-updown-15m-1','dca_500ms_depth100','down',now,22,20,'settled','down',2,json.dumps(fill)))
    db.execute('INSERT INTO paper VALUES(?,?,?,?,?,?,?,?,?,?)',
        ('btc-updown-15m-2','dca_500ms_depth100','up',now+1,0,0,'skipped',None,None,
         json.dumps({'fill':None,'reason':'Insufficient displayed depth'})))
    db.commit(); db.close()


def live_files(path: Path):
    path.mkdir()
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    (path/'live_decisions.jsonl').write_text(json.dumps({
        'timestamp':now,'event':'bot_heartbeat','payload':{'mode':'live'}})+'\n',encoding='utf-8')
    (path/'live_state.json').write_text(json.dumps({'seen_markets':[], 'positions':{},
        'live_attempts':[{'attempt_id':1,'market_slug':'btc-updown-15m-3','status':'filled',
          'created_at':now,'payload':{'direction':'up','stake_usd':'20','max_price':'.91'},
          'result':{'filled':True,'settlement_confirmed':True,'private_key':'must not leak'}}]}),encoding='utf-8')


def test_dashboard_combines_paper_robust_and_redacted_live(tmp_path, monkeypatch):
    db = tmp_path/'capture.sqlite3'; database(db)
    robust = tmp_path/'robust.json'; robust.write_text(json.dumps({'protocol_id':'x'}))
    live = tmp_path/'live'; live_files(live)
    monkeypatch.setenv('LIVE_MODE_ENABLED','1')
    result = snapshot(db, robust, live)
    assert result['primary']['settled'] == 1
    assert result['primary']['wins'] == 1
    assert result['equity_curve'][-1]['pnl'] == 2
    assert result['skip_reasons'] == [('Insufficient displayed depth',1)]
    assert result['signal']['direction'] == 'down'
    assert result['robustness']['protocol_id'] == 'x'
    assert result['live']['health'] == 'online'
    assert result['live']['attempts'][0]['stake_usd'] == '20'
    assert 'private_key' not in json.dumps(result)


def test_live_snapshot_handles_empty_directory_and_session_signature(tmp_path):
    result = live_snapshot(tmp_path)
    assert result['attempts'] == [] and result['heartbeat_ms'] is None
    assert session_token('a-secret-password',123).startswith('123.')
