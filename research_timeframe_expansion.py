"""DCA timeframe search and independently labelled venue-price evaluation."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import httpx

from audit_poly_research import read_minutes, bars5
from polymarket_bot.signal_grid import features, raw_signals
from research_timeframes import aggregate, map_contracts, label_horizon, split_periods, stats
from polymarket_bot.actual_research import array, settlement, fee_schedule, history_asof, cash_cost
from polymarket_bot.robustness import bankroll_replay
from research_polymarket_actual import PublicArchive
from report_robust_paper import block_interval

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'logs/timeframe_expansion'


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,default=str,allow_nan=False),encoding='utf-8')


def dca_variant(minutes,main,aux,daily_route):
    if aux<main or aux%main:
        raise ValueError('Auxiliary timeframe must align with main')
    f=aggregate(minutes,main)
    a=aggregate(minutes,aux)
    # Exactly 60 minutes between completed auxiliary closes, not four bars
    # when auxiliary timeframe changes.
    a['run60']=(a.close/a.close.shift(60//aux)-1)*1e4
    a=a.set_index('signal_at',drop=False)
    aux_at=a.reindex(pd.DatetimeIndex(f.signal_at))
    route=f.signal_at.dt.floor('D').map(daily_route)
    up=route.eq('long')&f.close.le(f.lower)
    down=route.eq('short')&f.close.ge(f.upper)
    pump=pd.Series((aux_at.valid.fillna(False)&aux_at.close.ge(aux_at.upper)&aux_at.run60.ge(60)).to_numpy(),index=f.index)
    # Original raw_signals valid5 accepts flat volatility, so use count rather
    # than aggregate.valid (which imposes std>0 for other research families).
    valid=f.close.rolling(30).count().eq(30)
    mask=valid&(up|down|pump)
    selected=f.loc[mask,['signal_at']].copy()
    selected['side']=np.where(pump.loc[mask]|down.loc[mask],'down','up')
    selected['source']=np.where(pump.loc[mask],f'aux_short_{aux}m',f'main_{main}m')
    return selected.reset_index(drop=True)


def screen():
    p=json.loads((ROOT/'timeframe_expansion_protocol.json').read_text())
    old=json.loads((ROOT/'timeframe_research_20260913/summary.json').read_text())
    minutes,metadata=read_minutes([Path(s['path']) for s in old['metadata']['sources']])
    assert [s['sha256'] for s in metadata['sources']]==[s['sha256'] for s in old['metadata']['sources']]
    stop=minutes.index[-1]+pd.Timedelta(minutes=1)
    g=features(bars5(minutes))
    route=g.assign(day=g.decision_at.dt.floor('D')).drop_duplicates('day').set_index('day').route
    variants={};frames={};raw_bank={}
    for main in p['main_boll_minutes']:
        for aux in p['aux_short_boll_minutes']:
            if aux<main or aux%main:continue
            key=f'main{main}_aux{aux}'
            raw=dca_variant(minutes,main,aux,route)
            raw_bank[key]=raw
            if (main,aux)==(5,15):
                original=raw_signals(g,session_start=0,session_end=0)
                pd.testing.assert_frame_equal(raw[['signal_at','side']].reset_index(drop=True),
                    original[['signal_at','side']].reset_index(drop=True),check_dtype=False)
            for h in p['horizon_minutes']:
                ident=f'{key}__h{h}'
                labelled=label_horizon(map_contracts(raw,h,max_age=10),minutes,h)
                parts=split_periods(labelled,stop)
                frames[ident]=parts
                variants[ident]={'main_minutes':main,'aux_minutes':aux,'horizon_minutes':h,
                    'train':stats(parts['train']),'validation':stats(parts['validation'])}
    chosen={}
    for h in p['horizon_minutes']:
        eligible=[k for k,v in variants.items() if v['horizon_minutes']==h and v['train']['n']>=100 and v['validation']['n']>=100]
        chosen[str(h)]=sorted(eligible,key=lambda k:(-variants[k]['validation']['wilson_lower'],k))[:2]
    dump(OUT/'proxy_selected_before_confirmation.json',{'selected':chosen,'protocol':p})
    # Only now expose later-period scores.
    for k,v in variants.items():v['confirmation']=stats(frames[k]['confirmation'])
    selected=set(sum(chosen.values(),[]))|{f'main5_aux15__h{h}' for h in p['horizon_minutes']}
    predictions=[]
    for k in sorted(selected):
        h=variants[k]['horizon_minutes']
        for period in ('validation','confirmation'):
            for r in frames[k][period].itertuples():
                predictions.append({'id':k,'horizon':h,'period':period,'start':int(r.decision_at.timestamp()),
                    'side':r.side,'source':r.source,'proxy_correct':bool(r.correct)})
    dump(OUT/'selected_predictions.json',predictions)
    dump(OUT/'proxy_summary.json',{'protocol':p,'metadata':metadata,'stop':str(stop),
         'baseline_raw_parity':True,'variants':variants,'selected':chosen,
         'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    print(json.dumps({'variants':len(variants),'selected':chosen,'venue_markets':len({(r['horizon'],r['start']) for r in predictions if r['horizon'] in p['venue_horizons']})},indent=2),flush=True)


def market_slug(start,h):
    if h in (5,15):return f'btc-updown-{h}m-{start}'
    if h==240:return f'btc-updown-4h-{start}'
    if h==60:
        t=datetime.fromtimestamp(start,ZoneInfo('America/New_York'))
        months=['january','february','march','april','may','june','july','august','september','october','november','december']
        return f'bitcoin-up-or-down-{months[t.month-1]}-{t.day}-{t.year}-{t.hour%12 or 12}{"am" if t.hour<12 else "pm"}-et'
    raise ValueError('Unverified contract horizon')


def parse_contract(event,start,h):
    slug=market_slug(start,h)
    if event.get('slug')!=slug or len(event.get('markets',[]))!=1:raise ValueError('Market identity mismatch')
    m=event['markets'][0]
    stamp=lambda s:int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp())
    if m.get('slug')!=slug or not m.get('conditionId'):raise ValueError('Token market mismatch')
    if stamp(m['endDate'])!=start+h*60 or not m.get('eventStartTime') or stamp(m['eventStartTime'])!=start:raise ValueError('Contract time mismatch')
    names=[str(x).lower() for x in array(m['outcomes'])];tokens=list(map(str,array(m['clobTokenIds'])))
    if len(names)!=2 or set(names)!={'up','down'} or len(set(tokens))!=2:raise ValueError('Not binary Up Down')
    rule=(m.get('description','')+' '+m.get('resolutionSource','')).lower()
    if h==60:
        if 'binance' not in rule or '1 hour' not in rule or 'btc/usdt' not in rule:raise ValueError('Unknown hourly rule')
        kind='binance_1h'
    else:
        if 'chainlink' not in rule:raise ValueError('Unknown minute rule')
        kind='chainlink_twap' if 'twap' in rule else 'chainlink_spot'
    return {'slug':slug,'start':start,'end':start+h*60,'horizon':h,'condition_id':m['conditionId'],
        'tokens':dict(zip(names,tokens)),'rule_type':kind,'raw':m}


async def fetch():
    p=json.loads((ROOT/'timeframe_expansion_protocol.json').read_text())
    rows=json.loads((OUT/'selected_predictions.json').read_text())
    keys=sorted({(r['horizon'],r['start']) for r in rows if r['horizon'] in p['venue_horizons']})
    api=PublicArchive(OUT,concurrency=24)
    await api.client.aclose()
    api.client=httpx.AsyncClient(timeout=20,limits=httpx.Limits(max_connections=32,max_keepalive_connections=32))
    done=0;counts=Counter()
    async def one(h,t):
        nonlocal done
        path=OUT/'raw'/f'{h}_{t}.json'
        old=ROOT/'actual_market_research_20260913/raw'/f'{t}.json'
        if path.exists():record=json.loads(path.read_text())
        elif h==15 and old.exists():
            record=json.loads(old.read_text());dump(path,record)
        else:
            ev=await api.get('https://gamma-api.polymarket.com/events/slug/'+market_slug(t,h))
            record={'event':ev,'start':t,'horizon':h}
            if ev['status']==200:
                try:
                    m=parse_contract(ev['body'],t,h)
                    calls=[api.get(f"https://clob.polymarket.com/markets/{m['condition_id']}"),
                           api.get(f"https://clob.polymarket.com/clob-markets/{m['condition_id']}")]
                    for side in ('up','down'):
                        calls.append(api.get('https://clob.polymarket.com/prices-history',market=m['tokens'][side],
                                             startTs=t-120,endTs=t+h*60,fidelity=1))
                    record.update(dict(zip(('clob','fee_info','up_history','down_history'),await asyncio.gather(*calls))))
                    record['parsed']={k:v for k,v in m.items() if k!='raw'}
                    record['settlement']=settlement(m,record['clob'].get('body',{}))
                    record['fee']=fee_schedule(m,record['fee_info'].get('body',{}))
                except (KeyError,ValueError,TypeError) as exc:record['parse_error']=str(exc)
            dump(path,record)
        counts[record.get('settlement',{}).get('status',str(record.get('event',{}).get('status')))]+=1
        done+=1
        if done%100==0:print('markets',done,'/',len(keys),dict(counts),flush=True)
    try:
        for n in range(0,len(keys),64):await asyncio.gather(*(one(h,t) for h,t in keys[n:n+64]))
    finally:await api.client.aclose()
    dump(OUT/'fetch_coverage.json',{'requested':len(keys),'counts':dict(counts)})


def venue_metric(rows,requested,budget):
    n=len(rows);wins=sum(r['won'] for r in rows)
    labels={r['slug']:{'received_ms':r['end_ms'],'winner':r['winner']} for r in rows}
    return {'requested_signals':requested,'n':n,'wins':wins,'win_rate':wins/n if n else None,
        'pnl':sum(r['pnl'] for r in rows),'mean_pnl':sum(r['pnl'] for r in rows)/n if n else None,
        'fresh15s':sum(r['reference_age']<=15 for r in rows),
        'pnl_2c':sum(r['pnl_2c'] for r in rows),'pnl_3c':sum(r['pnl_3c'] for r in rows),
        'nonfills_2c':sum(r['nonfill_2c'] for r in rows),'nonfills_3c':sum(r['nonfill_3c'] for r in rows),
        'stress3c_nonfill_would_lose':sum(r['nonfill_3c'] and not r['won'] for r in rows),
        'mean_pnl_block95_diagnostic':block_interval(rows,min(r['opened_ms'] for r in rows)//86400000,max(r['opened_ms'] for r in rows)//86400000) if rows else None,
        'bankroll50_instant_settlement':bankroll_replay(rows,labels,50,budget),
        'by_rule_type':{kind:{'n':len(x:=[r for r in rows if r['rule_type']==kind]),'wins':sum(r['won'] for r in x),'pnl':sum(r['pnl'] for r in x)} for kind in sorted({r['rule_type'] for r in rows})},
        'monthly':{month:{'n':len(x:=[r for r in rows if r['month']==month]),'wins':sum(r['won'] for r in x),'pnl':sum(r['pnl'] for r in x)} for month in sorted({r['month'] for r in rows})}}


def select_venue(results):
    eligible=[k for k,v in results.items() if v['validation']['n']>=50 and v['validation']['pnl']>0 and v['validation']['pnl_3c']>0]
    return sorted(eligible,key=lambda k:(-results[k]['validation']['mean_pnl'],-results[k]['validation']['n'],k))


def analyze():
    p=json.loads((ROOT/'timeframe_expansion_protocol.json').read_text())
    pred=json.loads((OUT/'selected_predictions.json').read_text())
    pred=[r for r in pred if r['horizon'] in p['venue_horizons']]
    trades=[];counts=Counter();hashes={}
    for r in pred:
        h,t=r['horizon'],r['start'];path=OUT/'raw'/f'{h}_{t}.json'
        body=path.read_bytes();hashes[path.name]=hashlib.sha256(body).hexdigest();raw=json.loads(body)
        reason=None
        if raw.get('settlement',{}).get('status')!='confirmed':reason='missing_confirmed_label'
        elif raw.get('fee',{}).get('status')!='known':reason='missing_verified_fee'
        delay=h*60*p['entry_fraction'][0]//p['entry_fraction'][1]
        q=history_asof(raw.get(r['side']+'_history',{}).get('body',{}).get('history',[]),t+delay) if not reason else None
        if not reason:
            if q is None:reason='missing_recent_reference'
            elif q['price']<.85:reason='reference_below_085'
            elif q['price']+.01>=1:reason='reference_plus_1c_ge_one'
        if reason:
            counts[(r['id'],r['period'],reason)]+=1;continue
        won=r['side']==raw['settlement']['winner'];b=p['budget_usd']
        cost=cash_cost(q['price']+.01,raw['fee']);shares=b/cost
        row={**r,'slug':raw['parsed']['slug'],'end_ms':(t+h*60)*1000,'opened_ms':(t+delay)*1000,
             'winner':raw['settlement']['winner'],'won':won,'cost':b,'shares':shares,'pnl':won*shares-b,
             'reference':q['price'],'reference_age':q['age_seconds'],'rule_type':raw['parsed']['rule_type'],
             'month':datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m')}
        for pad,key in ((.02,'2c'),(.03,'3c')):
            ok=q['price']+pad<1
            row['pnl_'+key]=b*(won/cash_cost(q['price']+pad,raw['fee'])-1) if ok else 0.
            row['nonfill_'+key]=not ok
        trades.append(row)
    ids=sorted({r['id'] for r in pred});results={}
    for ident in ids:
        x=[r for r in trades if r['id']==ident and r['period']=='validation']
        results[ident]={'validation':venue_metric(x,sum(r['id']==ident and r['period']=='validation' for r in pred),p['budget_usd'])}
    chosen=select_venue(results)
    dump(OUT/'venue_selected_before_confirmation.json',{'ranked_ids':chosen,'selected':chosen[0] if chosen else None,'rule':p['venue_selection']})
    for ident in ids:
        for period in ('confirmation','all'):
            x=[r for r in trades if r['id']==ident and (period=='all' or r['period']==period)]
            results[ident][period]=venue_metric(x,sum(r['id']==ident and (period=='all' or r['period']==period) for r in pred),p['budget_usd'])
    base=results.get('main5_aux15__h15',{})
    if base:
        assert (base['validation']['n'],base['confirmation']['n'],base['confirmation']['wins'])==(288,125,124),'Original benchmark changed'
        assert abs(base['confirmation']['pnl']-165.164943988158)<1e-7
    dump(OUT/'venue_trades.json',trades)
    dump(OUT/'venue_summary.json',{'protocol':p,'selected':chosen[0] if chosen else None,'results':results,
        'exclusions':[{'id':k[0],'period':k[1],'reason':k[2],'n':v} for k,v in sorted(counts.items())],
        'raw_sha256':hashes,'warning':'Current cached fee curves, reference+padding assumed fill, not historical executable books. Full theoretical PnL requires available capital. All history previously explored. Shortlist does not prove global best.'})
    print(json.dumps({'selected':chosen[0] if chosen else None,'results':{k:{p:{c:v[p][c] for c in ('n','wins','win_rate','pnl','pnl_3c')} for p in ('validation','confirmation','all')} for k,v in results.items()}},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['screen','fetch','analyze'])
    phase=parser.parse_args().phase
    if phase=='screen':screen()
    elif phase=='fetch':asyncio.run(fetch())
    else:analyze()
