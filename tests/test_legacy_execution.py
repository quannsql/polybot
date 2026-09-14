import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backtest_legacy_execution import cohort, scenario
from collect_robust_paper import Experiment
from polymarket_bot.legacy import legacy_reference, legacy_intent
from polymarket_bot.lighter_paper_feed import aggregate_minutes
from polymarket_bot.robustness import replay_fill
from polymarket_bot.signal import snapshot
from audit_poly_research import bars5
from report_robust_paper import report

ROOT=Path(__file__).parents[1]
P=json.loads((ROOT/'legacy_protocol.json').read_text())
FEE={'status':'known','rate':.07}


def book(now,ask='.91',bid='.90',size='100'):
    return {'timestamp':str(now),'asks':[{'price':ask,'size':size}],
            'bids':[{'price':bid,'size':'100'}],'tick_size':'.01','min_order_size':'5'}


def test_original_protocol_and_reference_are_not_replaced_by_ask():
    assert P['signal_policy']=='latest_5m'
    assert P['session_start_utc']==P['session_end_utc']==0
    assert P['entry_seconds']==690
    assert 'minimum_ask' not in P and 'maximum_price' not in P
    with pytest.raises(ValueError,match='below_085'):
        legacy_reference([{'t':990,'p':.84}],1000,P)
    with pytest.raises(ValueError,match='missing_or_stale'):
        legacy_reference([{'t':1001,'p':.95},{'t':924,'p':.95}],1000,P)
    with pytest.raises(ValueError,match='not_below_one'):
        legacy_reference([{'t':990,'p':.99}],1000,P)
    # Above old price but below 0.97 is an execution issue, NOT new eligibility.
    ref=legacy_reference([{'t':990,'p':.85},{'t':1001,'p':.99}],1000,P)
    intent=legacy_intent('up',{'up':book(1000000)},ref,1000000,P)
    assert intent['cap']=='0.86' and ref['price']==.85
    with pytest.raises(ValueError,match='Insufficient displayed depth'):
        replay_fill(intent,book(1000500),FEE,1000500,P)
    # The old strategy accepts a .98 reference, and fills can exceed .97.
    high=legacy_reference([{'t':990,'p':.98}],1000,P)
    intent=legacy_intent('up',{'up':book(1000000,'.99','.98')},high,1000000,P)
    assert intent['cap']=='0.99'
    assert replay_fill(intent,book(1000500,'.99','.98'),FEE,1000500,P)['total_cost']<=30
    # Ask below .85 does not reject an eligible OLD reference.
    low=legacy_intent('up',{'up':book(1000000,'.84','.82')},ref,1000000,P)
    assert replay_fill(low,book(1000500,'.84','.82'),FEE,1000500,P)['vwap']==pytest.approx(.84)


def test_minute_resampling_and_daily_route_match_legacy_offline():
    dates=pd.date_range('2026-07-01',periods=28*1440+15,freq='min',tz='UTC')
    close=100+np.sin(np.arange(len(dates))/57)
    frame=pd.DataFrame({'timestamp':dates,'open':close,'high':close+1,'low':close-1,'close':close,'volume':1.})
    at=dates[-1]+pd.Timedelta(minutes=1)
    bars,daily=aggregate_minutes(frame,at)
    pd.testing.assert_frame_equal(bars,bars5(frame.set_index('timestamp')))
    a=snapshot(bars,decision_at=at,policy='latest_5m')
    b=snapshot(bars.tail(240),decision_at=at,daily_frame=daily,policy='latest_5m')
    assert a.direction==b.direction and a.route==b.route and a.reason==b.reason
    gapped=frame.drop(index=100)
    gb,gd=aggregate_minutes(gapped,at)
    assert gb.loc[gb.timestamp.eq(dates[100]),'close'].isna().all()
    assert pd.isna(gd.iloc[0]['close'])
    # Unknown next minute cannot change a previously frozen signal.
    future=frame.tail(1).copy();future['timestamp']=at;future['close']=1e6
    fb,fd=aggregate_minutes(pd.concat([frame,future]),at)
    pd.testing.assert_frame_equal(fb,bars)
    pd.testing.assert_frame_equal(fd,daily)


def test_real_original_cohort_reproduced_and_stress_cannot_delete_losses():
    if not (ROOT/'late_entries_20260913/summary.json').exists():
        pytest.skip('Local historical archive not distributed in Docker/Git')
    rows,_,counts,_=cohort()
    assert counts['original_eligible']==413
    base=scenario(rows,.01,5)
    later=[r for r in base if r['period']=='confirmation']
    earlier=[r for r in base if r['period']=='validation']
    assert (len(later),sum(r['won'] for r in later))==(125,124)
    assert (len(earlier),sum(r['won'] for r in earlier))==(288,273)
    assert sum(r['pnl'] for r in later)==pytest.approx(27.52749066469299)
    assert sum(r['pnl'] for r in earlier)==pytest.approx(-5.240400982160377)
    stress=scenario(rows,.03,30)
    assert {r['slug'] for r in stress}=={r['slug'] for r in base}
    assert sum(r['won'] for r in stress)==397
    lost=[r for r in stress if r['period']=='confirmation' and not r['won']]
    assert len(lost)==1 and lost[0]['status']=='nonfill_price_at_or_above_one'
    assert lost[0]['pnl']==0 and lost[0]['cost']==0


def test_forward_old_candidate_is_retained_when_unfillable(tmp_path):
    async def exercise():
        exp=Experiment(tmp_path,P)
        stamp=exp.ledger.ms()
        market={'slug':'btc-updown-15m-test','tokens':{'up':'token','down':'other'}}
        signal=SimpleNamespace(direction='up',source='main_5m')
        start=int(exp.ledger.now())-690
        async def fake_books(_):
            now=exp.ledger.ms()
            return {'up':book(now),'down':book(now,'.11','.10')},{'up':{},'down':{}}
        async def fake_get(url,**params):
            assert url.endswith('/prices-history')
            assert params['endTs']==start+690 and params['fidelity']==1
            return {'status':200,'body':{'history':[{'t':start+680,'p':.85}]}}
        exp.books=fake_books;exp.api.get=fake_get
        try:
            await exp.evaluate(market,FEE,signal,start)
            db=exp.ledger.db
            assert db.execute('SELECT eligible FROM legacy_candidates').fetchone()[0]==1
            assert db.execute("SELECT COUNT(*) FROM paper WHERE status='skipped'").fetchone()[0]==6
            db.execute('INSERT INTO experiment VALUES(?,?,?)',(exp.digest,json.dumps(P),stamp))
            db.execute('INSERT INTO windows VALUES(?,?,?,?)',(market['slug'],stamp,json.dumps({'direction':'up'}),'ok'))
            db.execute('INSERT INTO labels VALUES(?,?,?)',(market['slug'],stamp+2000,'down'));db.commit()
            exp.ledger.resolve(market['slug'],{'status':'confirmed','winner':'down'})
            result=report(tmp_path/'capture.sqlite3')
            assert result['replay_verified']==6 and not result['replay_mismatches']
            c=result['legacy_fixed_cohort']
            assert c['labelled_candidates']==1 and c['direction_wins']==0
            assert c['primary_shadow_fills_settled']==0 and c['primary_zero_fill_or_capture_missing']==1
            assert c['legacy_assumed_ref_plus_1c_pnl_same_candidates']==-30
            assert c['primary_shadow_pnl']==0
        finally:
            await exp.api.client.aclose();exp.ledger.db.close()
    asyncio.run(exercise())
