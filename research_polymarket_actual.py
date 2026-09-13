"""Join frozen DCA candidates to official settlements and token price history.

Only public GET requests. Historical references are NEVER called executable asks.
No wallets, credentials, signing, orders, or runtime configuration changes.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from polymarket_bot.actual_research import parse_market, settlement, fee_schedule, history_asof, cash_cost

VARIANTS=['dca_5m_plus_15m__15m','daily_routed_reversion_15m__15m']
DELAYS=[30,330,630]
THRESHOLDS=[0,.55,.65,.75,.85,.90]


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')


class PublicArchive:
    def __init__(self, output: Path, concurrency: int=5):
        self.output=output
        self.sem=asyncio.Semaphore(concurrency)
        self.client=httpx.AsyncClient(timeout=20)
    async def get(self,url,**params):
        for attempt in range(3):
            async with self.sem:
                try:
                    r=await self.client.get(url,params=params or None)
                    if r.status_code in (429,500,502,503,504) and attempt<2:
                        await asyncio.sleep(min(5,1+attempt*2))
                        continue
                    try:
                        payload=r.json()
                    except ValueError:
                        payload={'text':r.text[:1000]}
                    return {'url':str(r.url),'fetched_at':utcnow(),'status':r.status_code,'body':payload}
                except (httpx.HTTPError,ValueError) as e:
                    if attempt==2:
                        return {'url':url,'fetched_at':utcnow(),'status':None,'error':str(e)}
            await asyncio.sleep(1)
    async def market(self,start:int):
        path=self.output/'raw'/f'{start}.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        event=await self.get(f'https://gamma-api.polymarket.com/events/slug/btc-updown-15m-{start}')
        result={'start':start,'event':event}
        try:
            if event['status']!=200:
                raise ValueError('Gamma request failed')
            market=parse_market(event['body'],start)
            cond=market['condition_id']
            calls=[self.get(f'https://clob.polymarket.com/markets/{cond}'),
                   self.get(f'https://clob.polymarket.com/clob-markets/{cond}')]
            for side in ['up','down']:
                calls.append(self.get('https://clob.polymarket.com/prices-history',market=market['tokens'][side],
                                      startTs=start-120,endTs=start+900,fidelity=1))
            result.update(dict(zip(['clob','fee_info','up_history','down_history'],await asyncio.gather(*calls))))
            result['parsed']={k:v for k,v in market.items() if k!='raw'}
            result['settlement']=settlement(market,result['clob'].get('body',{}))
            result['fee']=fee_schedule(market,result['fee_info'].get('body',{}))
        except (ValueError,KeyError,TypeError) as e:
            result['parse_error']=str(e)
        write_json(path,result)
        return result


def score(x:pd.DataFrame) -> dict:
    if len(x)==0:
        return {'n':0,'win_rate':None,'wilson_lower':None}
    n=len(x); p=float(x.correct.mean()); z=1.95996398454
    lo=(p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
    result={'n':n,'wins':int(x.correct.sum()),'win_rate':p,'wilson_lower':float(lo)}
    weeks=x.decision_at.dt.floor('D').map(lambda d:int(d.timestamp())//604800)
    groups=x.groupby(weeks).correct.agg(['sum','count'])
    result['week_clusters']=len(groups)
    if len(groups)>=4:
        ix=np.random.default_rng(913).integers(0,len(groups),size=(2000,len(groups)))
        rates=groups['sum'].to_numpy()[ix].sum(axis=1)/groups['count'].to_numpy()[ix].sum(axis=1)
        result['week_cluster_ci95']=np.quantile(rates,[.025,.975]).tolist()
    for col in ['reference_price','cost_pad_0','cost_pad_1c','cost_pad_3c','roi_pad_0','roi_pad_1c','roi_pad_3c']:
        if col in x:
            a=x[col].dropna()
            result[col+'_n']=len(a)
            result[col+'_mean']=float(a.mean()) if len(a) else None
    result['monthly']={str(k):{'n':len(g),'win_rate':float(g.correct.mean())}
                       for k,g in x.groupby(x.decision_at.dt.strftime('%Y-%m'))}
    return result


def analyze(predictions, records, output):
    labels=[]; refs=[]; statuses=Counter()
    for r in records.values():
        statuses[r.get('settlement',{}).get('status','fetch_or_parse_failed')]+=1
    for p in predictions.to_dict('records'):
        start=int(p['decision_at'].timestamp()); r=records[start]
        label=r.get('settlement',{})
        if label.get('status')!='confirmed':
            continue
        base={k:p[k] for k in ['variant','period','decision_at','side']}
        base.update({'winner':label['winner'],'correct':p['side']==label['winner'],
                     'proxy_correct':bool(p['correct']),'slug':f'btc-updown-15m-{start}',
                     'rule_type':r['parsed']['rule_type']})
        labels.append(base)
        for delay in DELAYS:
            quote=history_asof(r.get(p['side']+'_history',{}).get('body',{}).get('history',[]),start+delay)
            if quote is None:
                continue
            row={**base,'delay_seconds':delay,'reference_price':quote['price'],
                 'reference_timestamp':quote['timestamp'],'reference_age_seconds':quote['age_seconds'],
                 'fee_status':r.get('fee',{}).get('status','unknown')}
            for pad,suffix in [(0,'0'),(.01,'1c'),(.03,'3c')]:
                price=quote['price']+pad
                if r.get('fee',{}).get('status')=='known' and price<1:
                    cost=cash_cost(price,r['fee'])
                    row['cost_pad_'+suffix]=cost
                    row['roi_pad_'+suffix]=float(row['correct'])/cost-1
                else:
                    row['cost_pad_'+suffix]=None;row['roi_pad_'+suffix]=None
            refs.append(row)
    f=pd.DataFrame(labels); q=pd.DataFrame(refs)
    summary={'created_at':utcnow(),'requested_markets':len(records),'settlement_status':dict(statuses),
             'interpretation':'Actual API settlement labels; historical token references, not executable asks/fills. Fees are present metadata, not historical attestation.',
             'baseline':{},'grid':{}}
    if f.empty:
        write_json(output/'summary.json',summary)
        return summary
    for variant in VARIANTS:
        summary['baseline'][variant]={}
        for period in ['validation','confirmation']:
            x=f.loc[f.variant.eq(variant)&f.period.eq(period)]
            s=score(x)
            s['proxy_win_rate_same_rows']=float(x.proxy_correct.mean()) if len(x) else None
            s['label_disagreements']=int(x.correct.ne(x.proxy_correct).sum())
            s['requested']=int((predictions.variant.eq(variant)&predictions.period.eq(period)).sum())
            summary['baseline'][variant][period]=s
    # Selection is frozen on validation BEFORE computing confirmation grid scores.
    candidates=[]
    if not q.empty:
        for variant in VARIANTS:
            for delay in DELAYS:
                for threshold in THRESHOLDS:
                    key=f'{variant}__delay{delay}__ref{threshold}'
                    x=q.loc[q.variant.eq(variant)&q.delay_seconds.eq(delay)&q.reference_price.ge(threshold)]
                    v=score(x.loc[x.period.eq('validation')])
                    summary['grid'][key]={'validation':v,'variant':variant,'delay':delay,'threshold':threshold}
                    # Unknown fees or reference+padding >=1 are not hypothetical entries.
                    eligible=x.loc[x.period.eq('validation')&x.cost_pad_1c.notna()]
                    e=score(eligible)
                    summary['grid'][key]['validation_eligible_1c']=e
                    if e['n']>=100 and e.get('roi_pad_1c_mean',-1)>0:
                        candidates.append(key)
        selected=sorted(candidates,key=lambda k:(-summary['grid'][k]['validation_eligible_1c']['wilson_lower'],k))[:3]
        write_json(output/'selected_on_validation.json',{'ids':selected,
            'rule':'Top 3 validation Wilson lower on fee-known reference+1c<1 entries, n>=100 and positive scenario return; not live approval'})
        summary['selected']=selected
        for key,v in summary['grid'].items():
            x=q.loc[q.variant.eq(v['variant'])&q.delay_seconds.eq(v['delay'])&q.reference_price.ge(v['threshold'])]
            v['confirmation']=score(x.loc[x.period.eq('confirmation')])
            v['confirmation_eligible_1c']=score(x.loc[x.period.eq('confirmation')&x.cost_pad_1c.notna()])
            v['paired_price_sensitivity']={}
            for period in ['validation','confirmation']:
                paired=x.loc[x.period.eq(period)&x.cost_pad_1c.notna()&x.cost_pad_3c.notna()]
                v['paired_price_sensitivity'][period]={
                    'n':len(paired),'roi_1c':float(paired.roi_pad_1c.mean()) if len(paired) else None,
                    'roi_3c':float(paired.roi_pad_3c.mean()) if len(paired) else None}
            v['selected']=key in selected
        q.to_csv(output/'historical_reference_predictions.csv',index=False)
        # Diagnostic market-favourite control on the SAME union of DCA opportunity
        # windows, not all listed markets. Not used in candidate selection.
        controls=[]
        periods={int(p.decision_at.timestamp()):p.period for p in predictions.itertuples()}
        for start,r in records.items():
            winner=r.get('settlement',{}).get('winner')
            if r.get('settlement',{}).get('status')!='confirmed':
                continue
            for delay in DELAYS:
                quotes={s:history_asof(r.get(s+'_history',{}).get('body',{}).get('history',[]),start+delay)
                        for s in ['up','down']}
                if not all(quotes.values()) or quotes['up']['price']==quotes['down']['price']:
                    continue
                side=max(quotes,key=lambda s:quotes[s]['price'])
                reference=quotes[side]['price']
                cost=cash_cost(reference+.01,r['fee']) if reference+.01<1 and r.get('fee',{}).get('status')=='known' else None
                controls.append({'decision_at':pd.Timestamp(start,unit='s',tz='UTC'),'period':periods[start],
                    'delay_seconds':delay,'side':side,'reference_price':reference,'correct':side==winner,
                    'cost_pad_1c':cost,'roi_pad_1c':float(side==winner)/cost-1 if cost else None})
        control=pd.DataFrame(controls)
        summary['favorite_control']={}
        if not control.empty:
            control.to_csv(output/'favorite_control.csv',index=False)
            for delay in DELAYS:
                for threshold in THRESHOLDS:
                    x=control.loc[control.delay_seconds.eq(delay)&control.reference_price.ge(threshold)]
                    summary['favorite_control'][f'delay{delay}__ref{threshold}']={
                        period:score(x.loc[x.period.eq(period)&x.cost_pad_1c.notna()])
                        for period in ['validation','confirmation']}
            summary['favorite_control_scope']='Union of the two DCA opportunity sets only; later diagnostic, not a selected trading strategy.'
    f.to_csv(output/'settlement_predictions.csv',index=False)
    summary['rule_types']=f.groupby('rule_type').size().to_dict()
    summary['unresolved_or_failed_excluded']=len(predictions)-len(f)
    write_json(output/'summary.json',summary)
    return summary


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions',type=Path,default=Path('timeframe_research_20260913/predictions.csv'))
    parser.add_argument('--output-dir',type=Path,default=Path('actual_market_research_20260913'))
    parser.add_argument('--limit',type=int,default=0,help='Chronologically first N markets; zero = all')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    if not args.output_dir.resolve().is_relative_to(Path('D:/polybot').resolve()):
        raise ValueError('Outputs must stay in Bot2')
    (args.output_dir/'raw').mkdir(parents=True,exist_ok=True)
    plan={'created_at':utcnow(),'variants':VARIANTS,'delays_seconds':DELAYS,'thresholds':THRESHOLDS,
        'max_history_age_seconds':75,'reference_price_padding':[0,.01,.03],
        'selection':'validation only, min100 and positive +1c reference scenario, top3 Wilson lower',
        'scope':'delay30 near opening; delay330/630 enter 5/10min later but same original 15m expiry',
        'historical_price_warning':'Historical reference is neither executable ask nor a calibrated probability.',
        'fee_warning':'Use per-market Gamma and CLOB curves fetched now; historical as-of schedules not established.',
        'no_live_approval':True,'prediction_sha256':hashlib.sha256(args.predictions.read_bytes()).hexdigest()}
    if not (args.output_dir/'plan.json').exists():
        write_json(args.output_dir/'plan.json',plan)
    f=pd.read_csv(args.predictions)
    f=f.loc[f.variant.isin(VARIANTS)].copy()
    f['decision_at']=pd.to_datetime(f.decision_at,utc=True)
    if f.duplicated(['variant','decision_at']).any():
        raise ValueError('Duplicate prediction/contract')
    starts=sorted({int(x.timestamp()) for x in f.decision_at})
    if args.limit:
        starts=starts[:args.limit]
        f=f.loc[f.decision_at.map(lambda x:int(x.timestamp())).isin(starts)]
    archive=PublicArchive(args.output_dir)
    records={}
    try:
        # Bounded batches avoid thousands of live tasks and provide progress/checkpoints.
        for i in range(0,len(starts),25):
            batch=starts[i:i+25]
            if args.offline:
                rows=[json.loads((args.output_dir/'raw'/f'{x}.json').read_text(encoding='utf-8')) for x in batch]
            else:
                rows=await asyncio.gather(*(archive.market(x) for x in batch))
            records.update(zip(batch,rows))
            print(f'Cached {len(records)}/{len(starts)} markets',flush=True)
    finally:
        await archive.client.aclose()
    summary=analyze(f,records,args.output_dir)
    write_json(args.output_dir/'analysis_manifest.json',{
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'pure_logic_sha256':hashlib.sha256(Path('polymarket_bot/actual_research.py').read_bytes()).hexdigest(),
        'prediction_sha256':plan['prediction_sha256'],
        'selection_eligibility':'Fee known and reference+1c<1; no substitution for missing ask.',
        'raw_sha256':{str(start):hashlib.sha256((args.output_dir/'raw'/f'{start}.json').read_bytes()).hexdigest()
                      for start in records}})
    print(json.dumps({k:v for k,v in summary.items() if k in ['baseline','settlement_status','selected']},indent=2),flush=True)


if __name__=='__main__':
    asyncio.run(main())
