"""Offline, hypothesis-limited DCA/Polymarket study. No orders or Bot1 writes.

Historical token references are not executable asks. Lighter-derived features
are not the Chainlink settlement feed. Existing later data is reused, not pristine.
"""
from __future__ import annotations

import hashlib
import json
from math import erf, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from audit_poly_research import read_minutes, bars5
from polymarket_bot.signal_grid import features
from polymarket_bot.actual_research import history_asof, cash_cost

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'actual_market_research_20260913'
OUT = ROOT / 'signal_extensions_20260913'
INPUTS = [Path('D:/backtest') / p / 'BTCUSDT_1m.csv' for p in
          ['data_lighter_240d', 'data_lighter_augall', 'data_lighter_0903']]
DELAYS = [330, 510, 630]
FILTERS = ['cap95', 'cap90', 'cap85', 'spot_lead', 'lead_z1',
           'momentum3', 'bb_reclaim', 'token_momentum2', 'quiet_vol',
           'normal_edge3', 'slope15_agrees']
POLICIES = [f'd{d}_{f}' for d in DELAYS for f in FILTERS]
BASELINES = ['baseline65', 'baseline85']
PROTOCOL = {
    'version': 1, 'policies': POLICIES, 'baseline_ids': BASELINES,
    'scope': 'Original DCA 5m+15m opportunity windows only; direction frozen at T.',
    'entry': 'Fixed T+330/510/630s, expiry T+900s. One entry per market per policy.',
    'price': 'All challengers use .65 <= reference <= .95; cap90/85 reduce upper cap.',
    'cost': 'Reference+1c or +3c, current cached per-market fees, $5 all-in cash equivalent.',
    'selection': 'Validation only: n>=100, win>=85%, +3c total PnL>0; max +3c total PnL then id.',
    'walk_forward': 'June through September; same selection using only markets ended by UTC month start.',
    'validation_end': '2026-07-14T00:00:00Z',
    'limitations': ['Later set already examined in previous research, NOT untouched holdout.',
                    '33 challenger hypotheses; exploratory unadjusted confidence intervals.',
                    'Lighter spot/volatility proxy, not historical Chainlink spot/TWAP.',
                    'History is not executable depth; fee metadata not historical as-of proof.',
                    'Missing minutes never filled. No live approval, no runtime changes.'],
}


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def feature_tables(minutes):
    # Input timestamps are minute OPEN; shift outputs to their availability time.
    close = minutes.close
    r = np.log(close / close.shift(1))
    m = pd.DataFrame({'close': close, 'ret3': r.rolling(3).sum(),
                      'vol30': r.rolling(30).std(ddof=0),
                      'vol_ratio': r.rolling(5).std(ddof=0) / r.rolling(60).std(ddof=0)})
    m.index = m.index + pd.Timedelta(minutes=1)
    b = features(bars5(minutes)).set_index('decision_at')
    return m, b


def observation(minutes, minute_features, bands, start, delay, side):
    entry = start + pd.Timedelta(seconds=delay)
    known = entry.floor('min')
    row = minute_features.reindex([known]).iloc[0]
    band = bands.reindex([entry.floor('5min')]).iloc[0]
    direction = 1 if side == 'up' else -1
    opening = minutes.open.get(start, np.nan)
    elapsed = minutes.loc[start:known-pd.Timedelta(minutes=1), 'close']
    complete = len(elapsed) == int((known-start).total_seconds()/60) and elapsed.notna().all()
    lead = direction * np.log(row.close / opening) if complete else np.nan
    # Forecast uncertainty starts at last observed CLOSE, not the delayed entry.
    remaining = (start + pd.Timedelta(minutes=15) - known).total_seconds() / 60
    denom = row.vol30 * sqrt(remaining)
    z = lead / denom if np.isfinite(denom) and denom > 0 else np.nan
    normal_p = .5 * (1 + erf(z / sqrt(2))) if np.isfinite(z) else np.nan
    reclaim = bool(band.valid5 == True and np.isfinite(row.close)
                   and band.lower5 < row.close < band.upper5)
    return {'feature_at': known, 'lead': lead, 'lead_z': z,
            'normal_p_uncalibrated': normal_p, 'momentum3': direction * row.ret3,
            'vol_ratio': row.vol_ratio, 'bb_reclaim': reclaim,
            'slope15_agrees': bool(band.valid15 == True and direction * band.slope15 > 0)}


def build_rows(predictions, minutes):
    mf, bands = feature_tables(minutes)
    rows, hashes = [], {}
    for p in predictions.itertuples():
        start = int(p.decision_at.timestamp())
        path = ARCHIVE / 'raw' / f'{start}.json'
        blob = path.read_bytes()
        hashes[path.name] = hashlib.sha256(blob).hexdigest()
        record = json.loads(blob)
        if record.get('settlement', {}).get('status') != 'confirmed' or record.get('fee', {}).get('status') != 'known':
            continue
        if record['settlement']['winner'] != p.winner:
            raise ValueError('Settlement cache changed')
        history = record.get(p.side + '_history', {}).get('body', {}).get('history', [])
        for delay in DELAYS:
            quote = history_asof(history, start + delay)
            if quote is None:
                continue
            old = history_asof(history, start + delay - 120)
            row = {'decision_at': p.decision_at, 'end_at': p.decision_at + pd.Timedelta(minutes=15),
                   'period': p.period, 'side': p.side, 'rule_type': p.rule_type,
                   'delay': delay, 'reference': quote['price'], 'quote_age': quote['age_seconds'],
                   'token_momentum2': quote['price'] - old['price'] if old else np.nan,
                   'correct': p.side == record['settlement']['winner']}
            row.update(observation(minutes, mf, bands, p.decision_at, delay, p.side))
            for pad, suffix in [(.01, '1c'), (.03, '3c')]:
                cost = cash_cost(quote['price'] + pad, record['fee']) if quote['price'] + pad < 1 else np.nan
                row['cost_' + suffix] = cost
                row['pnl_' + suffix] = 5 * (float(row['correct']) / cost - 1)
            rows.append(row)
    return pd.DataFrame(rows).sort_values(['decision_at', 'delay']), hashes


def policy_mask(rows, policy):
    if policy in BASELINES:
        return rows.delay.eq(630) & rows.reference.ge(.65 if policy == 'baseline65' else .85) & rows.cost_1c.notna()
    d, filt = policy.split('_', 1)
    mask = rows.delay.eq(int(d[1:])) & rows.reference.between(.65, .95) & rows.cost_1c.notna()
    conditions = {
        'cap95': pd.Series(True, index=rows.index), 'cap90': rows.reference.le(.90),
        'cap85': rows.reference.le(.85), 'spot_lead': rows.lead.gt(0),
        'lead_z1': rows.lead_z.ge(1), 'momentum3': rows.momentum3.gt(0),
        'bb_reclaim': rows.bb_reclaim.eq(True), 'token_momentum2': rows.token_momentum2.gt(0),
        'quiet_vol': rows.vol_ratio.le(1.5),
        'normal_edge3': rows.normal_p_uncalibrated.sub(rows.cost_1c).ge(.03),
        'slope15_agrees': rows.slope15_agrees.eq(True),
    }
    return mask & conditions[filt]


def metric(rows):
    x = rows.sort_values('decision_at')
    if x.empty:
        return {'n': 0, 'win_rate': None, 'pnl_1c': 0., 'pnl_3c': 0.}
    n = len(x); wins = int(x.correct.sum()); rate = wins/n
    curve = np.r_[0., x.pnl_1c.cumsum()]
    streak = best = 0
    for won in x.correct:
        streak = 0 if won else streak + 1
        best = max(best, streak)
    z = 1.95996398454
    lower = (rate+z*z/(2*n)-z*sqrt(rate*(1-rate)/n+z*z/(4*n*n)))/(1+z*z/n)
    paired = x.loc[x.cost_3c.notna()]
    return {'n': n, 'wins': wins, 'win_rate': rate, 'wilson_lower': lower,
            'pnl_1c': float(x.pnl_1c.sum()), 'avg_pnl_1c': float(x.pnl_1c.mean()),
            'avg_win_1c': float(x.loc[x.correct, 'pnl_1c'].mean()) if wins else None,
            'max_drawdown_1c': float((np.maximum.accumulate(curve)-curve).max()),
            'max_loss_streak': best, 'paired_n': len(paired),
            'paired_pnl_1c': float(paired.pnl_1c.sum()), 'pnl_3c': float(paired.pnl_3c.sum()),
            'monthly': {str(month): {'n': len(g), 'pnl_1c': float(g.pnl_1c.sum()),
                                     'wins': int(g.correct.sum())}
                        for month, g in x.groupby(x.decision_at.dt.strftime('%Y-%m'))}}


def choose(rows):
    """Caller passes only ended training markets; stable deterministic rule."""
    candidates = []
    for policy in POLICIES:
        s = metric(rows.loc[policy_mask(rows, policy)])
        if s['n'] >= 100 and s['win_rate'] >= .85 and s['pnl_3c'] > 0:
            candidates.append((s['pnl_3c'], policy))
    return sorted(candidates, key=lambda v: (-v[0], v[1]))[0][1] if candidates else None


def select_on_validation(rows):
    return choose(rows.loc[rows.period.eq('validation')])


def clustered_pnl_delta(a, b, first, last):
    """Paired weekly aggregate dollar difference, including inactive days/weeks."""
    days = pd.date_range(first.floor('D'), last.floor('D'), freq='D')
    def daily(x):
        return x.groupby(x.decision_at.dt.floor('D')).pnl_1c.sum().reindex(days, fill_value=0)
    delta = daily(a)-daily(b)
    groups = delta.groupby(np.arange(len(days))//7).sum().to_numpy()
    idx = np.random.default_rng(913).integers(0, len(groups), (5000, len(groups)))
    samples = groups[idx].sum(axis=1)
    return {'delta_usd': float(delta.sum()), 'weeks': len(groups),
            'exploratory_week_bootstrap_ci95_usd': np.quantile(samples, [.025, .975]).tolist(),
            'multiple_testing_adjusted': False}


def evaluate(rows):
    selected = select_on_validation(rows)
    dump(OUT / 'selected_before_later_scoring.json', {'policy': selected, 'rule': PROTOCOL['selection']})
    table = {p: {period: metric(rows.loc[policy_mask(rows, p) & rows.period.eq(period)])
                 for period in ['validation', 'confirmation']} for p in POLICIES + BASELINES}
    later = rows.loc[rows.period.eq('confirmation')]
    result = {'selected': selected, 'policies': table}
    baseline = later.loc[policy_mask(later, 'baseline65')]
    result['exploratory_later_deltas_not_used_for_selection'] = {
        p: clustered_pnl_delta(later.loc[policy_mask(later, p)], baseline,
                               later.decision_at.min(), later.decision_at.max())
        for p in POLICIES}
    if selected:
        selected_rows = later.loc[policy_mask(later, selected)]
        baseline = later.loc[policy_mask(later, 'baseline65')]
        result['selected_vs_baseline_later'] = clustered_pnl_delta(selected_rows, baseline,
                                                                  later.decision_at.min(), later.decision_at.max())
        result['selected_later_by_rule'] = {str(k): metric(g) for k, g in selected_rows.groupby('rule_type')}
        selected_rows.to_csv(OUT / 'selected_later_trades.csv', index=False)
    frozen_months, trades = [], []
    for cut in pd.date_range('2026-06-01', '2026-09-01', freq='MS', tz='UTC'):
        train = rows.loc[rows.end_at.le(cut)]
        policy = choose(train)
        next_cut = cut + pd.offsets.MonthBegin(1)
        test = rows.loc[rows.decision_at.ge(cut) & rows.decision_at.lt(next_cut)]
        picked = test.loc[policy_mask(test, policy)].copy() if policy else test.iloc[:0].copy()
        picked['policy'] = policy
        trades.append(picked)
        frozen_months.append({'month': cut.strftime('%Y-%m'), 'policy': policy,
                              'training_last_settlement_boundary': str(train.end_at.max()),
                              'performance': metric(picked)})
    walk = pd.concat(trades, ignore_index=True)
    if walk.duplicated('decision_at').any():
        raise ValueError('More than one walk-forward entry per market')
    walk.to_csv(OUT / 'walk_forward_trades.csv', index=False)
    result['walk_forward'] = {'months': frozen_months, 'combined': metric(walk)}
    same_dates = rows.loc[rows.decision_at.ge(pd.Timestamp('2026-06-01', tz='UTC'))]
    result['walk_forward']['baseline65_same_calendar_period'] = metric(
        same_dates.loc[policy_mask(same_dates, 'baseline65')])
    result['dataset'] = {'markets': int(rows.decision_at.nunique()), 'quote_rows': len(rows),
                         'first': str(rows.decision_at.min()), 'last': str(rows.decision_at.max())}
    dump(OUT / 'summary.json', result)
    return result


def verify_original_reference_math(rows):
    original = pd.read_csv(ARCHIVE / 'historical_reference_predictions.csv',
                           parse_dates=['decision_at'])
    original = original.loc[original.variant.eq('dca_5m_plus_15m__15m')
                            & original.delay_seconds.isin([330, 630])]
    joined = rows.loc[rows.delay.isin([330, 630])].merge(
        original, left_on=['decision_at', 'delay'], right_on=['decision_at', 'delay_seconds'],
        validate='one_to_one', suffixes=('', '_old'), how='outer', indicator=True)
    if not joined['_merge'].eq('both').all():
        raise AssertionError('Original quote coverage not reproduced')
    np.testing.assert_allclose(joined.reference, joined.reference_price, atol=1e-12)
    np.testing.assert_allclose(joined.pnl_1c, 5*joined.roi_pad_1c, atol=1e-12, equal_nan=True)
    return {'matched_rows': len(joined), 'quote_and_five_dollar_pnl_identical': True}


def main():
    OUT.mkdir(exist_ok=True)
    protocol_path = OUT / 'protocol.json'
    if protocol_path.exists() and json.loads(protocol_path.read_text(encoding='utf-8')) != PROTOCOL:
        raise ValueError('Protocol changed; use a new version/output directory')
    dump(protocol_path, PROTOCOL)  # before reading/scoring outcomes
    pred_path = ARCHIVE / 'settlement_predictions.csv'
    predictions = pd.read_csv(pred_path, parse_dates=['decision_at'])
    predictions = predictions.loc[predictions.variant.eq('dca_5m_plus_15m__15m')].copy()
    if predictions.duplicated('decision_at').any():
        raise ValueError('Duplicate opportunities')
    minutes, metadata = read_minutes(INPUTS)
    rows, hashes = build_rows(predictions, minutes)
    regression = verify_original_reference_math(rows)
    rows.to_csv(OUT / 'feature_observations.csv', index=False)
    result = evaluate(rows)
    dump(OUT / 'manifest.json', {'minute_sources': metadata, 'archive_sha256': hashes,
                                'baseline_regression': regression,
                                'predictions_sha256': hashlib.sha256(pred_path.read_bytes()).hexdigest(),
                                'code_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                                for name in ['research_signal_extensions.py', 'audit_poly_research.py',
                                                             'polymarket_bot/signal_grid.py',
                                                             'polymarket_bot/actual_research.py']}})
    print(json.dumps({'selected': result['selected'], 'dataset': result['dataset'],
                      'selected_performance': result['policies'].get(result['selected']),
                      'delta': result.get('selected_vs_baseline_later'),
                      'walk_forward': result['walk_forward']}, indent=2))


if __name__ == '__main__':
    main()
