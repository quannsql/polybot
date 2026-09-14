"""Public BTC 1m capture, aggregated exactly as the legacy research input.

No exchange credentials, no Binance fallback, no forward-filled missing minutes.
Daily closes are accepted only after all 288 five-minute bars are complete.
"""
import asyncio
import math
from pathlib import Path
import sqlite3
import time

import httpx
import numpy as np
import pandas as pd

BASE = 'https://mainnet.zklighter.elliot.ai/api/v1'
COLS = ['open','high','low','close','volume']


def aggregate_minutes(frame, at):
    at = pd.Timestamp(at)
    f = frame.copy()
    f['timestamp'] = pd.to_datetime(f.timestamp,utc=True)
    if f.timestamp.duplicated().any() or not f.timestamp.equals(f.timestamp.dt.floor('min')):
        raise ValueError('Duplicate or off-grid Lighter minutes')
    f = f.loc[f.timestamp+pd.Timedelta(minutes=1)<=at].set_index('timestamp').sort_index()
    if f.empty:
        raise ValueError('Empty closed Lighter history')
    f = f.reindex(pd.date_range(f.index.min(), at-pd.Timedelta(minutes=1),freq='min'))
    f.index.name = 'timestamp'
    bars = f.resample('5min').agg(open=('open','first'),high=('high','max'),low=('low','min'),
        close=('close','last'),volume=('volume','sum'),count=('close','count'))
    bars.loc[bars['count'].ne(5),COLS] = np.nan
    bars = bars.loc[bars.index+pd.Timedelta(minutes=5)<=at]
    daily = bars.resample('1D').agg(close=('close','last'),count=('close','count'))
    daily.loc[daily['count'].ne(288),'close'] = np.nan
    daily = daily.loc[daily.index+pd.Timedelta(days=1)<=at]
    return bars.drop(columns='count').reset_index(), daily.reset_index()


class LighterPaperFeed:
    def __init__(self, api, ledger):
        self.api, self.ledger = api, ledger
        self.db = ledger.db
        self.db.execute('CREATE TABLE IF NOT EXISTS lighter_minutes '
                        '(ts INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL, received_ms INTEGER)')
        self.db.commit()
        self.verified = False

    async def refresh(self, at):
        stop = int(pd.Timestamp(at).timestamp())//60*60
        first = stop//86400*86400-28*86400
        if not self.verified:
            response = await self.api.get(BASE+'/orderBookDetails')
            matches = [r for r in response.get('body',{}).get('order_book_details',[])
                       if r.get('market_id')==1 and r.get('symbol')=='BTC']
            if response['status']!=200 or len(matches)!=1:
                raise ValueError('Lighter BTC market identity unverified')
            self.verified = True
            self.ledger.event('lighter_market_verified',None,{'market_id':1,'symbol':'BTC'})
        last = self.db.execute('SELECT MAX(ts) FROM lighter_minutes').fetchone()[0]
        # Re-request the last ten minutes; first captured closed candle wins.
        begin = max(first, last-600) if last is not None else first
        async def chunk(lo,hi):
            response = await self.api.get(BASE+'/candles',market_id=1,resolution='1m',
                start_timestamp=lo,end_timestamp=hi-1,count_back=(hi-lo)//60,set_timestamp_to_end='false')
            body = response.get('body',{})
            if response['status']!=200 or body.get('code')!=200 or body.get('r')!='1m':
                raise ValueError('Lighter minute history unavailable')
            values=[]
            seen=set()
            for row in body.get('c',[]):
                stamp=int(row['t'])
                if stamp%60000:
                    raise ValueError('Off-grid Lighter candle')
                ts=stamp//1000
                # count_back may return older rows outside start_timestamp.
                if not lo<=ts<hi:
                    continue
                if ts in seen:
                    raise ValueError('Duplicate Lighter minute')
                seen.add(ts)
                o,h,l,c = (float(row[k]) for k in ('o','h','l','c'))
                v = float(row.get('v',0))  # protobuf omits zero-volume field.
                if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):
                    raise ValueError('Invalid Lighter OHLCV')
                values.append((ts,o,h,l,c,v,self.ledger.ms()))
            self.db.executemany('INSERT OR IGNORE INTO lighter_minutes VALUES(?,?,?,?,?,?,?)',values)
            self.db.commit()
            return len(values)
        # Bounded fanout, independent of the number of warmup pages.
        chunks=[(lo,min(lo+500*60,stop)) for lo in range(begin,stop,500*60)]
        total=0
        for i in range(0,len(chunks),3):
            total+=sum(await asyncio.gather(*(chunk(lo,hi) for lo,hi in chunks[i:i+3])))
        self.ledger.event('lighter_refresh',None,{'from':begin,'to_exclusive':stop,'rows_received':total,
            'requests':len(chunks),'source':'Lighter BTC 1m; first captured closed candle wins'})
        records=self.db.execute('SELECT ts,open,high,low,close,volume FROM lighter_minutes '
                                'WHERE ts>=? AND ts<? ORDER BY ts',(first,stop)).fetchall()
        frame=pd.DataFrame(records,columns=['timestamp',*COLS])
        frame['timestamp']=pd.to_datetime(frame.timestamp,unit='s',utc=True)
        bars,daily=aggregate_minutes(frame,pd.Timestamp(stop,unit='s',tz='UTC'))
        return bars.tail(240).reset_index(drop=True), daily


class LighterFeed:
    """Persistent public Lighter source for the audited legacy live signal."""

    def __init__(self, cache_path: Path, timeout: float = 10.0, *, symbol: str = 'BTC', history_days: int = 28):
        if symbol not in {'BTC', 'ETH'}:
            raise ValueError('Unsupported gate feed symbol')
        self.symbol, self.history_days = symbol, history_days
        self.market_id = None
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path)
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS minutes '
            '(ts INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL, received_ms INTEGER)'
        )
        self.db.commit()
        self.client = httpx.AsyncClient(timeout=timeout, trust_env=False)
        self.verified = False

    async def _get(self, path, **params):
        response = await self.client.get(BASE + path, params=params)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError('Invalid Lighter response')
        return body

    async def refresh(self, at):
        stop = int(pd.Timestamp(at).timestamp()) // 60 * 60
        first = stop // 86400 * 86400 - self.history_days * 86400
        if not self.verified:
            body = await self._get('/orderBookDetails')
            matches = [r for r in body.get('order_book_details', [])
                       if r.get('symbol') == self.symbol]
            if len(matches) != 1:
                raise ValueError('Lighter market identity unverified')
            self.market_id = int(matches[0]['market_id'])
            if self.symbol == 'BTC' and self.market_id != 1:
                raise ValueError('Unexpected BTC market identity')
            self.verified = True
        last = self.db.execute('SELECT MAX(ts) FROM minutes').fetchone()[0]
        begin = max(first, last - 600) if last is not None else first

        async def chunk(lo, hi):
            body = await self._get('/candles', market_id=self.market_id, resolution='1m',
                start_timestamp=lo, end_timestamp=hi-1, count_back=(hi-lo)//60,
                set_timestamp_to_end='false')
            if body.get('code') != 200 or body.get('r') != '1m':
                raise ValueError('Lighter minute history unavailable')
            values = []; seen = set()
            for row in body.get('c', []):
                stamp = int(row['t'])
                if stamp % 60000:
                    raise ValueError('Off-grid Lighter candle')
                ts = stamp // 1000
                if not lo <= ts < hi:
                    continue
                if ts in seen:
                    raise ValueError('Duplicate Lighter minute')
                seen.add(ts)
                o, h, l, c = (float(row[k]) for k in ('o', 'h', 'l', 'c'))
                v = float(row.get('v', 0))
                if (not all(math.isfinite(x) for x in (o, h, l, c, v))
                        or min(o, h, l, c) <= 0 or v < 0
                        or h < max(o, l, c) or l > min(o, h, c)):
                    raise ValueError('Invalid Lighter OHLCV')
                values.append((ts, o, h, l, c, v, int(time.time()*1000)))
            self.db.executemany('INSERT OR IGNORE INTO minutes VALUES(?,?,?,?,?,?,?)', values)
            self.db.commit()

        chunks = [(lo, min(lo+500*60, stop)) for lo in range(begin, stop, 500*60)]
        for index in range(0, len(chunks), 3):
            await asyncio.gather(*(chunk(lo, hi) for lo, hi in chunks[index:index+3]))
        records = self.db.execute(
            'SELECT ts,open,high,low,close,volume FROM minutes '
            'WHERE ts>=? AND ts<? ORDER BY ts', (first, stop)
        ).fetchall()
        frame = pd.DataFrame(records, columns=['timestamp', *COLS])
        frame['timestamp'] = pd.to_datetime(frame.timestamp, unit='s', utc=True)
        bars, daily = aggregate_minutes(frame, pd.Timestamp(stop, unit='s', tz='UTC'))
        return bars.tail(240).reset_index(drop=True), daily

    def gate_minutes(self, at):
        stop = int(pd.Timestamp(at).timestamp()) // 60 * 60
        rows = self.db.execute('SELECT ts,open,high,low,close,volume FROM minutes '
                              'WHERE ts>=? AND ts<? ORDER BY ts', (stop-4*86400, stop)).fetchall()
        frame = pd.DataFrame(rows, columns=['timestamp', *COLS])
        frame['timestamp'] = pd.to_datetime(frame.timestamp, unit='s', utc=True)
        return frame

    async def close(self):
        await self.client.aclose()
        self.db.close()
