import asyncio
import copy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import time

import pytest

from collect_robust_paper import Experiment
from polymarket_bot.robustness import select_intent, replay_fill, bankroll_replay
from report_robust_paper import report


P=json.loads((Path(__file__).parents[1]/'robustness_protocol.json').read_text())


def book(now,ask='.90',size='100'):
    return {'timestamp':str(now),'asset_id':'token','market':'condition',
            'bids':[{'price':'.89','size':'100'}],
            'asks':[{'price':ask,'size':size}], 'min_order_size':'5','tick_size':'.01'}


def test_cap_frozen_and_no_future_arrival_or_missing_depth():
    b=book(10000)
    i=select_intent('up',{'up':b},10000,P)
    assert i['cap']=='0.91'
    fee={'status':'known','rate':.07}
    with pytest.raises(ValueError,match='Insufficient displayed depth'):
        replay_fill(i,book(10250,'.92'),fee,10250,P)
    with pytest.raises(ValueError,match='arrival_before_decision'):
        replay_fill(i,b,fee,9999,P)
    with pytest.raises(ValueError,match='Stale/future'):
        replay_fill(i,b,fee,13000,P)
    with pytest.raises(ValueError,match='Insufficient displayed depth'):
        replay_fill(i,book(10250,size='40'),fee,10250,P,.5)
    fill=replay_fill(i,book(10250,size='40'),fee,10250,P,1.)
    assert 29.99 <= fill['total_cost'] <= 30


def test_bankroll_holds_funds_and_cannot_trade_after_thirty_dollar_loss():
    rows=[{'slug':'a','opened_ms':100,'cost':30,'shares':33,'side':'up'},
          {'slug':'b','opened_ms':200,'cost':30,'shares':33,'side':'up'},
          {'slug':'c','opened_ms':400,'cost':30,'shares':33,'side':'up'}]
    labels={'a':{'received_ms':300,'winner':'down'},'c':{'received_ms':500,'winner':'up'}}
    r=bankroll_replay(rows,labels)
    assert r['taken']==1
    assert r['cash_after_known_settlements']==20
    assert r['skipped_for_funds']==2
    assert r['max_realized_drawdown']==30
    pending=bankroll_replay(rows[:1],{})
    assert pending['cash_after_known_settlements']==20
    assert pending['locked_cost']==30


def test_delayed_observations_replay_and_report_end_to_end(tmp_path):
    async def exercise():
        exp=Experiment(tmp_path,P)
        stamp=exp.ledger.ms()
        market={'slug':'btc-updown-15m-100','tokens':{'up':'token','down':'other'}}
        signal=SimpleNamespace(direction='up',source='main_5m')
        async def books(_):
            now=exp.ledger.ms()
            up=book(now)
            down=book(now,'.11'); down['bids'][0]['price']='.10'
            return {'up':up,'down':down},{'up':{'received_ms':now},'down':{'received_ms':now}}
        exp.books=books
        try:
            await exp.evaluate(market,{'status':'known','rate':.07},signal,int(exp.ledger.now())-690)
            db=exp.ledger.db
            db.execute('INSERT INTO experiment VALUES(?,?,?)',(exp.digest,json.dumps(P),stamp))
            db.execute('INSERT INTO windows VALUES(?,?,?,?)',(market['slug'],stamp,json.dumps({'direction':'up'}),'ok'))
            db.execute('INSERT INTO labels VALUES(?,?,?)',(market['slug'],stamp+2000,'up'));db.commit()
            exp.ledger.resolve(market['slug'],{'status':'confirmed','winner':'up'})
            result=report(tmp_path/'capture.sqlite3')
            assert result['replay_verified']==12
            assert not result['replay_mismatches']
            assert len(result['policies'])==12
            assert all(p['unique_markets']==1 for p in result['policies'])
            assert result['paired_dca_minus_favourite']['n']==1
            assert result['paired_dca_minus_favourite']['pnl_difference']==0
            assert all(p['mean_pnl_block_bootstrap_95'] is None for p in result['policies'])
            assert result['status']=='diagnostic_only_no_live_approval'
        finally:
            await exp.api.client.aclose()
            exp.ledger.db.close()
    asyncio.run(exercise())


def test_protocol_cannot_be_changed_in_existing_experiment(tmp_path):
    async def exercise():
        exp=Experiment(tmp_path,P)
        exp.ledger.db.execute('INSERT INTO experiment VALUES(?,?,?)',(exp.digest,json.dumps(P),100))
        exp.ledger.db.commit()
        await exp.api.client.aclose();exp.ledger.db.close()
        different={**P,'minimum_ask':.86}
        with pytest.raises(ValueError,match='Protocol changed'):
            Experiment(tmp_path,different)
    asyncio.run(exercise())
