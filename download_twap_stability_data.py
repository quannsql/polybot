"""Download only public, CC-BY-4.0 TWAP reports from a pinned HF dataset.

The dataset's L2 is BTC5m and is deliberately NOT substituted for BTC15m L2.
No credentials, wallets, orders or payments.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pandas as pd

from research_fresh_data import dump,sha

ROOT=Path('data/twap_stability_20261108')
REPO='mileswangs/polymarket-btc-updown-5m-orderbook-tick-data'


async def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(timeout=90,follow_redirects=True) as client:
        pin=ROOT/'hf_revision.json'
        if not pin.exists():
            r=await client.get(f'https://huggingface.co/api/datasets/{REPO}')
            r.raise_for_status(); dump(pin,r.json())
        revision=json.loads(pin.read_text())['sha']
        tree=ROOT/'hf_pinned_tree.json'
        if not tree.exists():
            r=await client.get(f'https://huggingface.co/api/datasets/{REPO}/tree/{revision}',params=dict(recursive='true',limit=1000))
            r.raise_for_status(); dump(tree,r.json())
        entries=[x for x in json.loads(tree.read_text()) if x['type']=='file' and x['path'].startswith('chainlink_streams_twap60s/')]
        if len(entries)!=14:
            raise ValueError('Unexpected source coverage; inspect pinned manifest')
        sem=asyncio.Semaphore(3)
        async def one(entry):
            path=entry['path']; date=path.split('date=')[1].split('/')[0]
            local=ROOT/'twap'/f'{date}.parquet'; local.parent.mkdir(parents=True,exist_ok=True)
            expected=(entry.get('lfs') or {}).get('oid')
            if not local.exists():
                async with sem:
                    r=await client.get(f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/{path}')
                    r.raise_for_status()
                    if len(r.content)!=entry['size']:
                        raise ValueError(f'Size mismatch: {date}')
                    local.write_bytes(r.content)
            digest=sha(local)
            if expected and digest!=expected:
                raise ValueError(f'LFS checksum mismatch: {date}')
            f=pd.read_parquet(local)
            print(f'TWAP {date}: {len(f)} reports',flush=True)
            return dict(date=date,path=str(local),bytes=local.stat().st_size,rows=len(f),sha256=digest,
                expected_lfs_sha256=expected,columns=list(f.columns),source_path=path)
        records=await asyncio.gather(*(one(e) for e in entries))
        dump(ROOT/'download_manifest.json',dict(repository=REPO,revision=revision,license='CC-BY-4.0',
            attribution='PMData / mileswangs dataset publisher',days=sorted(records,key=lambda r:r['date']),
            scope='Chainlink TWAP60s only; BTC5m L2 excluded from BTC15m execution research'))


if __name__=='__main__':
    asyncio.run(main())
