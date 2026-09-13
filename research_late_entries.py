"""Later entries on fixed DCA opportunities; historical references, NOT fills."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from polymarket_bot.actual_research import history_asof, cash_cost
from research_signal_extensions import metric

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'actual_market_research_20260913'
OUT = ROOT / 'late_entries_20260913'
DELAYS = [630, 690, 750, 810, 840, 870]


def dump(path, x):
    path.write_text(json.dumps(x, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def build():
    pred = pd.read_csv(ARCHIVE/'settlement_predictions.csv', parse_dates=['decision_at'])
    pred = pred.loc[pred.variant.eq('dca_5m_plus_15m__15m')]
    rows = []
    for p in pred.itertuples():
        start = int(p.decision_at.timestamp())
        r = json.loads((ARCHIVE/'raw'/f'{start}.json').read_text(encoding='utf-8'))
        if r.get('settlement', {}).get('status') != 'confirmed' or r.get('fee', {}).get('status') != 'known':
            continue
        for delay in DELAYS:
            quote = history_asof(r.get(p.side+'_history', {}).get('body', {}).get('history', []), start+delay)
            if quote is None:
                continue
            row = {'decision_at': p.decision_at, 'end_at': p.decision_at+pd.Timedelta(minutes=15),
                   'period': p.period, 'side': p.side, 'rule_type': p.rule_type,
                   'delay': delay, 'reference': quote['price'], 'quote_age': quote['age_seconds'],
                   'correct': p.side == r['settlement']['winner']}
            for pad, suffix in [(.01, '1c'), (.03, '3c')]:
                cost = cash_cost(quote['price']+pad, r['fee']) if quote['price']+pad < 1 else np.nan
                row['cost_'+suffix] = cost
                row['pnl_'+suffix] = 5*(float(row['correct'])/cost-1)
            rows.append(row)
    return pd.DataFrame(rows), pred


def main():
    OUT.mkdir(exist_ok=True)
    dump(OUT/'protocol.json', {'delays': DELAYS, 'thresholds': [.65, .85],
         'prices': 'reference+1c/+3c, current cached fees, $5 cash equivalent',
         'freshness': '75s primary for old-study parity; <=15s diagnostic',
         'selection': 'No best-delay selection; report all. History already reused.',
         'causality': 'Fixed market+side has identical settlement correctness at every delay.'})
    rows, pred = build()
    results = {}
    for threshold in [.65, .85]:
        for delay in DELAYS:
            x = rows.loc[rows.delay.eq(delay) & rows.reference.ge(threshold) & rows.cost_1c.notna()]
            results[f'd{delay}_min{threshold}'] = {}
            for period in ['validation', 'confirmation']:
                part = x.loc[x.period.eq(period)]
                results[f'd{delay}_min{threshold}'][period] = metric(part)
                results[f'd{delay}_min{threshold}'][period]['fresh15s'] = metric(part.loc[part.quote_age.le(15)])
    # Same market and direction at EVERY delay. Do not re-filter by future price.
    initial = rows.loc[rows.delay.eq(630) & rows.reference.ge(.65), 'decision_at']
    eligible = rows.loc[rows.decision_at.isin(initial) & rows.cost_1c.notna()]
    common = eligible.groupby('decision_at').delay.nunique()
    same = eligible.loc[eligible.decision_at.isin(common[common.eq(len(DELAYS))].index)]
    paired = {str(d): {p: metric(same.loc[same.delay.eq(d) & same.period.eq(p)])
                       for p in ['validation', 'confirmation']} for d in DELAYS}
    for period in ['validation', 'confirmation']:
        assert len({paired[str(d)][period]['win_rate'] for d in DELAYS}) == 1
    # Exploratory price-only calibration: each month uses only older months,
    # independently per delay/rule/price bucket. No oracle calibration claim.
    rows['bucket'] = np.floor(rows.reference*10).astype(int)
    calibrated = []
    for cut in pd.date_range('2026-06-01', '2026-09-01', freq='MS', tz='UTC'):
        # One-day embargo because exact historical resolution availability unknown.
        train = rows.loc[rows.end_at.lt(cut-pd.Timedelta(days=1))]
        table = train.groupby(['delay','rule_type','bucket']).correct.agg(['sum','count'])
        test = rows.loc[rows.decision_at.ge(cut) & rows.decision_at.lt(cut+pd.offsets.MonthBegin(1))]
        for row in test.to_dict('records'):
            key = (row['delay'], row['rule_type'], row['bucket'])
            if key not in table.index or not np.isfinite(row['cost_1c']):
                continue
            stats = table.loc[key]; n = int(stats['count']); p = float(stats['sum']/n); z = 1.95996398454
            lower = (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
            if n >= 50 and lower-row['cost_1c'] >= .02:
                calibrated.append({**row, 'n_train': n, 'p_lower': lower, 'fit_at': cut})
    cal = pd.DataFrame(calibrated, columns=list(rows.columns)+['n_train','p_lower','fit_at'])
    cal.to_csv(OUT/'price_only_edge_trades.csv', index=False)
    summary = {'requested_markets': len(pred), 'quote_markets': int(rows.decision_at.nunique()),
               'grid': results, 'same_cohort_diagnostic_not_a_tradable_selection': paired,
               'price_only_edge_per_delay': {str(d): metric(cal.loc[cal.delay.eq(d)]) for d in DELAYS},
               'warning': 'No real fills. Late quote staleness matters. Same-cohort requires future availability and is diagnostic ONLY.'}
    rows.to_csv(OUT/'observations.csv', index=False)
    dump(OUT/'summary.json', summary)
    dump(OUT/'manifest.json', {'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                               'source_labels_sha256': hashlib.sha256((ARCHIVE/'settlement_predictions.csv').read_bytes()).hexdigest()})
    for k, v in results.items():
        a=v['validation']; b=v['confirmation']
        print(k, 'before', a['n'], round(a['win_rate']*100,2), round(a['pnl_1c'],2),
              'later', b['n'], round(b['win_rate']*100,2), round(b['pnl_1c'],2),
              'fresh15_n', b['fresh15s']['n'])
    print('price_only_edge', summary['price_only_edge_per_delay'])


if __name__ == '__main__':
    main()
