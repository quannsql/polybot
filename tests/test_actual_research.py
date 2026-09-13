import copy
import json

import pytest

from polymarket_bot.actual_research import (parse_market,settlement,fee_schedule,
    history_asof,cash_cost,buy_depth)
from collect_poly_paper import Ledger


START=1789020900


def fixture():
    slug=f'btc-updown-15m-{START}'
    m={'slug':slug,'conditionId':'abc','eventStartTime':'2026-09-10T06:15:00Z',
       'endDate':'2026-09-10T06:30:00Z','outcomes':'["Down","Up"]','clobTokenIds':'["22","11"]',
       'description':'Chainlink TWAP BTC/USD','resolutionSource':'https://data.chain.link/',
       'closed':True,'umaResolutionStatus':'resolved','outcomePrices':'["0","1"]',
       'feesEnabled':True,'feeSchedule':{'rate':.07,'exponent':1}}
    event={'slug':slug,'markets':[m]}
    c={'condition_id':'abc','closed':True,'tokens':[{'token_id':'22','winner':False},
                                                       {'token_id':'11','winner':True}]}
    info={'c':'abc','fd':{'r':.07,'e':1},'tbf':1000}
    return event,c,info


def test_map_outcome_names_not_array_position():
    e,c,i=fixture(); m=parse_market(e,START)
    assert m['tokens']=={'down':'22','up':'11'}
    assert settlement(m,c)['winner']=='up'


@pytest.mark.parametrize('field,value',[('slug','wrong'),('eventStartTime','2026-09-10T06:00:00Z'),
    ('endDate','2026-09-10T06:45:00Z'),('clobTokenIds','["11","11"]'),('description','BTC Binance')])
def test_market_rule_and_identity_fail_closed(field,value):
    e,_,_=fixture();e['markets'][0][field]=value
    if field=='description':e['markets'][0]['resolutionSource']='binance'
    with pytest.raises(ValueError):parse_market(e,START)


@pytest.mark.parametrize('change',['open','proposed','near_one','conflict','void','token_mismatch'])
def test_never_infer_settlement_from_price_alone(change):
    e,c,_=fixture();m=e['markets'][0]
    if change=='open':m['closed']=False
    if change=='proposed':m['umaResolutionStatus']='proposed'
    if change=='near_one':m['outcomePrices']='["0.001","0.999"]'
    if change=='conflict':c['tokens'][0]['winner']=True
    if change=='void':c['is_50_50_outcome']=True
    if change=='token_mismatch':c['tokens'][0]['token_id']='different'
    assert settlement(parse_market(e,START),c)['winner'] is None


def test_fee_curve_not_legacy_base_fee():
    e,_,i=fixture();m=parse_market(e,START)
    f=fee_schedule(m,i)
    assert f['rate']==.07 # NOT 1000/10000 = .10
    assert cash_cost(.5,f)==pytest.approx(.5175)
    i['fd']['r']=.1
    assert fee_schedule(m,i)['status']=='fee_disagreement'


def test_missing_or_unsupported_fees_do_not_assume_default():
    e,_,_=fixture();e['markets'][0]['feeSchedule']['exponent']=2
    assert fee_schedule(parse_market(e,START))['status']=='unsupported'
    e['markets'][0].pop('feeSchedule')
    assert fee_schedule(parse_market(e,START))['status']=='unknown'


def test_history_asof_never_uses_nearest_future_or_conflicting_duplicate():
    points=[{'t':100,'p':.4},{'t':130,'p':.8}]
    assert history_asof(points,129)['price']==.4
    assert history_asof(points,99) is None
    assert history_asof(points,300) is None
    assert history_asof(points+[{'t':130,'p':.7}],131) is None
    assert history_asof(points+[{'t':130,'p':.8}],131)['price']==.8


def book():
    return {'timestamp':'100000','bids':[{'price':'.49','size':'50'}],
            'asks':[{'price':'.60','size':'100'},{'price':'.50','size':'10'}],
            'min_order_size':'5'}


def test_depth_walk_fees_and_budget():
    b=book();fee={'status':'known','rate':.07}
    fill=buy_depth(b,fee,budget=10,max_price=.65,now_ms=100000)
    assert len(fill['fills'])==2
    assert fill['vwap']>.5
    assert fill['total_cost']<=10.0000001
    assert fill['break_even_probability']>fill['vwap']


@pytest.mark.parametrize('case',['stale','future','depth','crossed','empty','negative','minimum','unknown_fee'])
def test_paper_fill_fail_closed(case):
    b=book();f={'status':'known','rate':.07};now=100000;cap=.65
    if case=='stale':now=110000
    if case=='future':now=90000
    if case=='depth':cap=.51
    if case=='crossed':b['bids'][0]['price']='.60'
    if case=='empty':b['asks']=[]
    if case=='negative':b['asks'][0]['size']='-1'
    if case=='minimum':b['min_order_size']='30'
    if case=='unknown_fee':f={'status':'unknown'}
    with pytest.raises(ValueError):buy_depth(b,f,budget=10,max_price=cap,now_ms=now)


def test_ledger_idempotent_and_waits_for_confirmed_settlement(tmp_path):
    l=Ledger(tmp_path/'paper.db')
    fill={'shares':18.,'total_cost':10.}
    l.attempt('slug','a','up',fill=fill)
    l.attempt('slug','a','up',fill={'shares':999,'total_cost':1})
    l.attempt('slug','b','down',fill=fill)
    assert l.resolve('slug',{'status':'not_final','winner':None})==0
    assert l.pending()==['slug']
    assert l.resolve('slug',{'status':'confirmed','winner':'up'})==2
    assert l.resolve('slug',{'status':'confirmed','winner':'up'})==0
    assert l.db.execute('SELECT policy,pnl FROM paper ORDER BY policy').fetchall()==[('a',8.),('b',-10.)]
    l.db.close()


def test_validation_selection_unchanged_when_future_settlements_flip(tmp_path):
    import pandas as pd
    from research_polymarket_actual import analyze
    rows=[]; records={}
    for phase,date,n in [('validation','2026-04-20',100),('confirmation','2026-08-01',20)]:
        for t in pd.date_range(date,periods=n,freq='15min',tz='UTC'):
            start=int(t.timestamp())
            rows.append({'variant':'dca_5m_plus_15m__15m','period':phase,'decision_at':t,'side':'up','correct':True})
            records[start]={'settlement':{'status':'confirmed','winner':'up'},'parsed':{'rule_type':'chainlink_spot'},
                'fee':{'status':'known','rate':.07},
                'up_history':{'body':{'history':[{'t':start+d,'p':.8} for d in [20,320,620]]}},
                'down_history':{'body':{'history':[{'t':start+d,'p':.2} for d in [20,320,620]]}}}
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    f=pd.DataFrame(rows)
    first=analyze(f,records,a)
    for start,r in records.items():
        if start>=int(pd.Timestamp('2026-08-01',tz='UTC').timestamp()):
            r['settlement']['winner']='down'
    second=analyze(f,records,b)
    assert len(first['selected'])==3
    assert first['selected']==second['selected']
    k=first['selected'][0]
    assert first['grid'][k]['confirmation_eligible_1c']['win_rate']==1
    assert second['grid'][k]['confirmation_eligible_1c']['win_rate']==0
