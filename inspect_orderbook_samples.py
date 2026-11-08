"""Inspect downloaded provider samples locally; not a strategy backtest."""
from pathlib import Path
import json

import numpy as np
import pandas as pd

from research_fresh_data import dump, sha


def inspect(directory):
    directory=Path(directory)
    result={}
    for name in ('vike_book_events.parquet','pmdata_l2.parquet'):
        path=directory/name
        f=pd.read_parquet(path)
        if name.startswith('vike'):
            timestamps=pd.to_datetime(f.ts,unit='ms',utc=True)
            lag=f.local_ts-f.ts
            snapshots=f.loc[f.is_snapshot.eq(1)]
            ids=dict(token_ids=f.token_id.unique().tolist(),condition_ids=f.condition_id.unique().tolist())
            books=[(json.loads(r.bids or '[]'),json.loads(r.asks or '[]')) for r in snapshots.itertuples()]
            attribution='Vike; CC BY-NC 4.0; https://vike.io/data/polymarket/historical-data'
        else:
            timestamps=pd.to_datetime(f.timestamp,utc=True)
            lag=(f.local_timestamp-f.timestamp).dt.total_seconds()*1000
            snapshots=f.loc[f.event_type.eq('book')]
            ids=dict(slugs=f.market_slug.unique().tolist())
            books=[(list(zip(r.bid_prices,r.bid_sizes)),list(zip(r.ask_prices,r.ask_sizes)))
                for r in snapshots.itertuples()]
            attribution='PMData free evaluation sample; https://pmdata.dev/polymarket-historical-data'
        malformed=empty=crossed=0
        for bids,asks in books:
            levels=bids+asks
            if any(not np.isfinite([float(p),float(s)]).all() or not 0<float(p)<1 or float(s)<=0 for p,s in levels):
                malformed+=1
            if not bids or not asks:
                empty+=1
            elif max(float(p) for p,s in bids)>=min(float(p) for p,s in asks):
                crossed+=1
        result[name]=dict(rows=len(f),bytes=path.stat().st_size,sha256=sha(path),
            columns=list(f.columns),first=timestamps.min().isoformat(),last=timestamps.max().isoformat(),
            event_types=f.event_type.astype(str).value_counts().to_dict(),identifiers=ids,
            full_snapshots=len(snapshots),snapshot_malformed=malformed,snapshot_empty=empty,
            snapshot_crossed=crossed,receive_minus_exchange_ms=dict(
                min=float(lag.min()),median=float(lag.median()),p99=float(lag.quantile(.99)),max=float(lag.max())),
            attribution=attribution,
            limitations=['Sample market is BTC 5m, NOT this bot\'s BTC 15m contract.',
                'Provider receive timestamps measure provider-site delays, not our server latency.',
                'Full snapshot inspection only. Reconstruct deltas in received order and reset at gap/status markers before execution replay.',
                'Do not infer coverage of other markets, FOK success or strategy PnL from this sample.'])
    dump(directory/'inspection.json',result)
    print(json.dumps({k:{n:v[n] for n in ['rows','first','last','full_snapshots','snapshot_malformed','snapshot_crossed']}
        for k,v in result.items()},indent=2))


if __name__=='__main__':
    inspect(Path('data/orderbook_samples'))
