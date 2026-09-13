"""Read archived Bot1 cycles; compare realized winners with fixed-time labels.

This does not replay DCA or claim to reproduce the current live configuration.
Labels begin at each original entry, not at Polymarket contract boundaries.
"""
from pathlib import Path
import hashlib
import json

import pandas as pd

from audit_poly_research import read_minutes
from research_timeframes import label_horizon


def main():
    source = Path('D:/backtest/research_20260908/sl_campaign/all_trades_entry_features.csv')
    minutes, metadata = read_minutes([Path('D:/backtest')/d/'BTCUSDT_1m.csv' for d in
        ['data_lighter_240d', 'data_lighter_augall', 'data_lighter_0903']])
    all_cycles = pd.read_csv(source)
    cycles = all_cycles.loc[all_cycles.symbol.eq('BTC')].copy()
    cycles['decision_at'] = pd.to_datetime(cycles.opened_at, utc=True)
    if cycles.duplicated(['decision_at','side']).any():
        raise ValueError('Duplicate BTC cycles')
    if not cycles.decision_at.eq(cycles.decision_at.dt.floor('min')).all():
        raise ValueError('Off-grid entry timestamps: do not silently round')
    if not cycles.side.isin(['long', 'short']).all():
        raise ValueError('Unknown cycle side')
    cycles['side'] = cycles.side.map({'long':'up', 'short':'down'})
    cycles['cycle_won'] = cycles.realized_pnl.gt(0)
    result = {'scope':'Archived research cycles, not verified live configuration. Rolling entry-time labels, not contract replay.',
        'source':str(source), 'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'archived_btc_cycles':len(cycles), 'cycle_win_rate':float(cycles.cycle_won.mean()),
        'median_hold_minutes':float(cycles.minutes_held.median()),
        'held_over_15m_rate':float(cycles.minutes_held.gt(15).mean()),
        'multi_leg_rate':float(cycles.legs.gt(1).mean()), 'price_metadata':metadata}
    # Use the same cohort with complete 12h candles for all horizon comparisons.
    cohort = label_horizon(cycles.assign(end_at=cycles.decision_at+pd.Timedelta(hours=12)),minutes,720)
    rows = []
    exports = []
    for h in [5,15,30,60,240,720]:
        f = label_horizon(cohort.assign(end_at=cohort.decision_at+pd.Timedelta(minutes=h)),minutes,h)
        assert len(f) == len(cohort)
        rows.append({'horizon_minutes':h, 'n':len(f),
            'archived_cycle_win_rate':float(f.cycle_won.mean()),
            'endpoint_win_rate':float(f.correct.mean()),
            'cycle_won_but_endpoint_wrong_count':int((f.cycle_won & ~f.correct).sum()),
            'cycle_won_but_endpoint_wrong_fraction_of_cycle_winners':
                float((f.cycle_won & ~f.correct).sum()/f.cycle_won.sum())})
        exports.append(f[['decision_at','end_at','side','cycle_won','correct','start_price','end_price',
                           'minutes_held','legs','realized_pnl']].assign(horizon_minutes=h))
    result['common_complete_12h_cohort'] = rows
    output = Path('D:/polybot/timeframe_research_20260913')
    output.mkdir(exist_ok=True)
    (output/'dca_cycles.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    pd.concat(exports).to_csv(output/'dca_cycles_comparison.csv',index=False)
    print(json.dumps({k:v for k,v in result.items() if k!='price_metadata'},indent=2))


if __name__ == '__main__':
    main()
