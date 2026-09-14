"""Read-only availability probe. An empty API response is never a filled book."""
import asyncio
import json
from pathlib import Path
import time

from backtest_legacy_execution import cohort
from research_polymarket_actual import PublicArchive


async def main():
    root=Path(__file__).resolve().parent
    output=root/'logs/legacy_execution'
    output.mkdir(parents=True,exist_ok=True)
    rows,_,_,_=cohort()
    later=[r for r in rows if r['period']=='confirmation']
    picks={r['slug']:r for r in later[:2]+later[-2:]+[r for r in later if not r['won']]}
    api=PublicArchive(output,concurrency=3)
    try:
        async def one(r):
            start=r['end_ms']//1000-900
            raw=json.loads((root/f'actual_market_research_20260913/raw/{start}.json').read_text())
            result=await api.get('https://clob.polymarket.com/orderbook-history',
                asset_id=raw['parsed']['tokens'][r['side']],startTs=start+685,endTs=start+695,limit=1000)
            return {'slug':r['slug'],'side':r['side'],'response':result}
        probes=await asyncio.gather(*(one(r) for r in picks.values()))
    finally:
        await api.client.aclose()
    report={'created_unix':time.time(),'samples':probes,
        'note':'Five preselected later-cohort markets including the sole loss. Probe is not proof of global absence or complete history coverage. Never substitute current books for these historical windows.'}
    (output/'book_history_probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps([{'slug':r['slug'],'status':r['response']['status'],
                       'body':r['response'].get('body')} for r in probes],indent=2))


if __name__=='__main__':
    asyncio.run(main())
