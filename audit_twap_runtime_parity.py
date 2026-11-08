"""Compare production exact-decimal TWAP/spot rule to all222 cached candidates.

Offline development audit only. It does not import an account or order executor.
"""
from collections import defaultdict,Counter
from decimal import Decimal
import json
from pathlib import Path

import pandas as pd

from polymarket_bot.twap_signal import Observation,PriceBuffer,decide
from research_fresh_data import dump,sha

BASE=Path('data/twap_stability_20261108')
LOSS=Path('data/twap_loss_audit_20261108')
OUT=Path('data/twap_live_validation_20261109')


def exact_points(paths, starts):
    grouped=defaultdict(list)
    wanted={start*1000 for start in starts}
    for path in paths:
        frame=pd.read_parquet(path,columns=['observationsTimestamp','receiveMicrosecondTimestamp','price'])
        observed=pd.to_datetime(frame.observationsTimestamp,utc=True).dt.as_unit('ms').astype('int64')
        received=pd.to_datetime(frame.receiveMicrosecondTimestamp,utc=True).dt.as_unit('ms').astype('int64')
        window=observed//900000*900000
        age=observed-window
        use=window.isin(wanted)&(age.eq(0)|age.between(775000,840000))&received.le(window+840000)
        for i in frame.index[use]:
            start=int(window[i]//1000)
            grouped[start].append(Observation(int(observed[i]),int(received[i]),Decimal(str(frame.price[i]))/Decimal(10**18)))
    return {start:sorted(points,key=lambda p:(p.observed_ms,p.received_ms)) for start,points in grouped.items()}


def main():
    rows=json.loads((LOSS/'entry_features.json').read_text())
    starts=[row['trade']['start'] for row in rows]
    twap=exact_points(sorted((BASE/'twap').glob('*.parquet')),starts)
    spot=exact_points(sorted((LOSS/'spot').glob('*.parquet')),starts)
    cases=[]; mismatches=[]
    for row in rows:
        trade=row['trade']; start=trade['start']; due=(start+840)*1000
        a,b=PriceBuffer(),PriceBuffer()
        a.reset(due-120000); b.reset(due-120000)
        opening=None
        for point in twap[start]:
            a.add(point)
            if point.observed_ms==start*1000 and opening is None:
                opening=point
        for point in spot[start]: b.add(point)
        result,reason=decide(opening,a,b,due)
        expected=row['features']['spot_minus_twap_bps']>=0
        actual=result is not None
        case=dict(start=start,period='calibration' if start<1786752000 else 'evaluation',
            expected_filter_pass=expected,production_pass=actual,reason=reason,won=trade['won'])
        cases.append(case)
        if expected!=actual: mismatches.append(case)
    report=dict(code_sha256=sha(Path('polymarket_bot/twap_signal.py')),candidates=len(cases),
        mismatches=mismatches,periods={period:dict(candidates=sum(r['period']==period for r in cases),
            kept=sum(r['production_pass'] and r['period']==period for r in cases),
            losses_kept=sum(r['production_pass'] and r['period']==period and not r['won'] for r in cases))
            for period in ('calibration','evaluation')},
        note='Signal/filter parity only. Additional live price/depth, SDK signing, latency and account guards may reject an entry. No fill/PnL claim.')
    dump(OUT/'signal_parity.json',report)
    if mismatches:
        raise AssertionError(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
