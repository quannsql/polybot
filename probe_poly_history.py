"""Small read-only capability probe; no bypasses or order submission."""
import asyncio
import json
from pathlib import Path
import time

from research_polymarket_actual import PublicArchive,write_json


async def main():
    output=Path('D:/polybot/actual_market_research_20260913')
    api=PublicArchive(output)
    records=[]
    try:
        records.append({'kind':'geoblock','response':await api.get('https://polymarket.com/api/geoblock')})
        for start in [1776571200,1784030400,1789020900,int(time.time())//900*900]:
            event=await api.get(f'https://gamma-api.polymarket.com/events/slug/btc-updown-15m-{start}')
            if event['status']!=200:
                records.append({'kind':'metadata_failure','response':event})
                continue
            m=event['body']['markets'][0];token=json.loads(m['clobTokenIds'])[0]
            for name,url,params in [
                ('orderbook_history','https://clob.polymarket.com/orderbook-history',
                 {'asset_id':token,'startTs':start-120,'endTs':start+900,'limit':1000}),
                ('current_book','https://clob.polymarket.com/book',{'token_id':token})]:
                response=await api.get(url,**params)
                records.append({'kind':name,'start':start,'slug':m['slug'],'response':response})
                body=response.get('body',{})
                print(name,start,response['status'],str(body)[:220],flush=True)
    finally:
        await api.client.aclose()
    write_json(output/'capability_probes.json',records)


if __name__=='__main__':
    asyncio.run(main())
