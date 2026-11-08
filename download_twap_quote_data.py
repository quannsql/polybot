"""Download publicly shared BTC15m quote archives; never substitute BTC5m books.

SQLite is opened read-only and only BTC15m top-of-book rows are exported.
Source receipt/exchange timestamp limitations remain explicit in the manifest.
"""
import asyncio
import json
from pathlib import Path
import sqlite3

import httpx
import pandas as pd
import pyarrow as pa

from research_fresh_data import dump,sha

ROOT=Path('data/twap_stability_20261108')
BOOK=ROOT/'quotes'


async def main():
    BOOK.mkdir(parents=True,exist_ok=True)
    tree=json.loads((ROOT/'book_github_tree.json').read_text()); revision=tree['sha']
    entries=[x for x in tree['tree'] if x['path'].endswith('.db.zst')]
    manifests=[]; frames=[]
    async with httpx.AsyncClient(timeout=120,follow_redirects=True) as client:
        for entry in entries:
            filename=Path(entry['path']).name
            compressed=BOOK/filename; database=compressed.with_suffix('')
            if not compressed.exists():
                response=await client.get(f'https://raw.githubusercontent.com/gensx-x1/polymarket-btc-eth-updown-data/{revision}/{entry["path"]}')
                response.raise_for_status()
                if len(response.content)!=entry['size']:
                    raise ValueError('Compressed database size mismatch')
                compressed.write_bytes(response.content)
            if not database.exists():
                with pa.input_stream(str(compressed),compression='zstd') as source,database.open('wb') as target:
                    while chunk:=source.read(1024*1024):
                        target.write(chunk)
            connection=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
            try:
                connection.execute('PRAGMA query_only=ON')
                columns=[r[1] for r in connection.execute('PRAGMA table_info(ticks)')]
                required=['ts_ms','asset','slug','window_s','window_start','window_end','ok',
                    'up_bid','up_ask','up_ask_sz','down_bid','down_ask','down_ask_sz']
                if not set(required)<=set(columns):
                    raise ValueError('Unrecognized source schema')
                f=pd.read_sql_query('SELECT '+','.join(required)+" FROM ticks WHERE asset='BTC' AND window_s=900",connection)
            finally:
                connection.close()
            frames.append(f)
            manifests.append(dict(file=filename,compressed_sha256=sha(compressed),database_sha256=sha(database),
                source_git_blob=entry['sha'],btc15_rows=len(f),first_ms=int(f.ts_ms.min()),last_ms=int(f.ts_ms.max())))
            print(f'{filename}: {len(f)} BTC15m quotes',flush=True)
        merged=pd.concat(frames,ignore_index=True).sort_values(['slug','ts_ms'])
        if merged.duplicated(['slug','ts_ms']).any():
            dup=merged.loc[merged.duplicated(['slug','ts_ms'],keep=False)]
            if dup.groupby(['slug','ts_ms']).nunique().gt(1).any().any():
                raise ValueError('Conflicting quote duplicates')
            merged=merged.drop_duplicates(['slug','ts_ms'])
        merged.to_parquet(BOOK/'github_btc15m_quotes.parquet',index=False)
        repo='polyorderbooks/polymarket-crypto-updown-orderbooks-l2'
        pin=BOOK/'hf_revision.json'
        if not pin.exists():
            r=await client.get(f'https://huggingface.co/api/datasets/{repo}'); r.raise_for_status(); dump(pin,r.json())
        rev=json.loads(pin.read_text())['sha']
        local=BOOK/'hf_15m_l2.parquet'
        if not local.exists():
            r=await client.get(f'https://huggingface.co/datasets/{repo}/resolve/{rev}/updown_15m.parquet')
            r.raise_for_status(); local.write_bytes(r.content)
        f=pd.read_parquet(local)
        subset=f.loc[f.coin.str.lower().eq('btc') & f.contract_length.eq('15m')].copy()
        subset.to_parquet(BOOK/'hf_btc15m_l2.parquet',index=False)
    dump(BOOK/'manifest.json',dict(github_repository='gensx-x1/polymarket-btc-eth-updown-data',github_revision=revision,
        github_files=manifests,github_export_sha256=sha(BOOK/'github_btc15m_quotes.parquet'),github_rows=len(merged),
        hf_repository=repo,hf_revision=rev,hf_license='CC-BY-4.0; attribution PolyOrderbooks',
        hf_raw_sha256=sha(local),hf_btc15_rows=len(subset),hf_btc15_export_sha256=sha(BOOK/'hf_btc15m_l2.parquet'),
        limitations=['GitHub source top-of-book only, timestamp convention not independently attested; no request/response or exchange-age proof.',
            'HF full ladders sampled in time; no historical queue or order acknowledgments.',
            'Coverage is partial; no extrapolation to uncovered days or BTC5m substitution.']))
    print('Quote datasets downloaded and BTC15m exported.',flush=True)


if __name__=='__main__':
    asyncio.run(main())
