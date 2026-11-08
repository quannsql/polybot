"""Public Chainlink spot reports matching the pinned TWAP research period.

Same publisher/revision as the existing TWAP cache; no API credentials or orders.
Spot is an additional warning signal, never substituted for settlement TWAP.
"""
import asyncio
import json
from pathlib import Path

import httpx
import pandas as pd

from download_twap_stability_data import REPO
from research_fresh_data import dump, sha

BASE = Path('data/twap_stability_20261108')
OUT = Path('data/twap_loss_audit_20261108')


async def main():
    revision = json.loads((BASE / 'hf_revision.json').read_text())['sha']
    entries = [r for r in json.loads((BASE / 'hf_pinned_tree.json').read_text())
               if r['type'] == 'file' and r['path'].startswith('chainlink_streams/')
               and r['path'].endswith('/BTCUSD.parquet')]
    if len(entries) != 14:
        raise ValueError('Expected exactly 14 matching public BTC spot days')
    sem = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        async def one(entry):
            day = entry['path'].split('date=')[1].split('/')[0]
            path = OUT / 'spot' / f'{day}.parquet'
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                async with sem:
                    response = await client.get(
                        f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/{entry["path"]}')
                    response.raise_for_status()
                    if len(response.content) != entry['size']:
                        raise ValueError('Unexpected downloaded size')
                    path.write_bytes(response.content)
            digest = sha(path)
            if digest != entry['lfs']['oid']:
                raise ValueError(f'Pinned LFS checksum mismatch: {day}')
            frame = pd.read_parquet(path)
            print(f'Spot {day}: {len(frame)} reports, checksum verified', flush=True)
            return dict(day=day, path=str(path), source_path=entry['path'],
                        bytes=path.stat().st_size, rows=len(frame), sha256=digest,
                        expected_lfs_sha256=entry['lfs']['oid'], columns=list(frame.columns))
        rows = await asyncio.gather(*(one(entry) for entry in entries))
    dump(OUT / 'spot_manifest.json', dict(repository=REPO, revision=revision,
        license='CC-BY-4.0', attribution='PMData / mileswangs',
        purpose='Causal spot warning signal; settlement remains official TWAP60s',
        days=sorted(rows, key=lambda r: r['day'])))


if __name__ == '__main__':
    asyncio.run(main())
