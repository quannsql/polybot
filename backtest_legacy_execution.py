"""Reproduce OLD candidates exactly; stress execution costs without retuning signals.

Offline, no orders or API calls. Keeps every original eligible market in every
scenario. A hypothetical price >=1 is an explicit non-fill, NOT a deleted row.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pandas as pd

from polymarket_bot.actual_research import cash_cost
from polymarket_bot.legacy import legacy_reference
from polymarket_bot.robustness import bankroll_replay
from report_robust_paper import block_interval, wilson

ROOT = Path(__file__).resolve().parent


def cohort(root=ROOT):
    protocol = json.loads((root/'legacy_protocol.json').read_text())
    source = root/'actual_market_research_20260913/settlement_predictions.csv'
    predictions = pd.read_csv(source, parse_dates=['decision_at'])
    predictions = predictions[predictions.variant.eq('dca_5m_plus_15m__15m')]
    if predictions.decision_at.duplicated().any():
        raise ValueError('Duplicate market in original predictions')
    counts = Counter(original_signals=len(predictions))
    rows, hashes = [], {}
    for p in predictions.itertuples():
        start = int(p.decision_at.timestamp())
        path = root/'actual_market_research_20260913/raw'/f'{start}.json'
        data = path.read_bytes()
        hashes[path.name] = hashlib.sha256(data).hexdigest()
        raw = json.loads(data)
        if raw.get('settlement', {}).get('status') != 'confirmed' or raw.get('fee', {}).get('status') != 'known':
            counts['unverified_label_or_fee'] += 1
            continue
        try:
            ref = legacy_reference(raw.get(p.side+'_history', {}).get('body', {}).get('history', []),
                                   start+protocol['entry_seconds'], protocol)
        except ValueError as exc:
            counts[str(exc)] += 1
            continue
        winner = raw['settlement']['winner']
        rows.append({'slug':p.slug, 'period':p.period, 'side':p.side, 'winner':winner,
                     'won':p.side==winner, 'opened_ms':(start+690)*1000,
                     'end_ms':(start+900)*1000, 'rule_type':p.rule_type,
                     'reference':ref, 'fee':raw['fee']})
    counts['original_eligible'] = len(rows)
    return rows, protocol, dict(counts), {'predictions_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                                         'cached_market_sha256':hashes}


def scenario(rows, padding, budget):
    result = []
    for r in rows:
        # Deliberately do NOT re-apply signal or minimum-price eligibility here.
        price = r['reference']['price'] + padding
        fillable = 0 < price < 1
        shares = budget/cash_cost(price, r['fee']) if fillable else 0.
        cost = budget if fillable else 0.
        result.append({**r, 'padding':padding, 'assumed_price':price, 'cost':cost,
                       'shares':shares, 'pnl':shares*r['won']-cost,
                       'status':'assumed_fill_not_observed' if fillable else 'nonfill_price_at_or_above_one'})
    return result


def summarize(rows, period, padding, budget):
    selected = [r for r in rows if period == 'all' or r['period'] == period]
    filled = [r for r in selected if r['cost'] > 0]
    unfilled = [r for r in selected if r['cost'] == 0]
    wins = sum(r['won'] for r in selected)
    start_date = '2026-07-14' if period == 'confirmation' else '2026-04-19'
    end_exclusive = '2026-07-14' if period == 'validation' else '2026-09-04'
    first = int(pd.Timestamp(start_date,tz='UTC').timestamp())//86400
    last = int(pd.Timestamp(end_exclusive,tz='UTC').timestamp())//86400-1
    pnl = sum(r['pnl'] for r in filled)
    labels = {r['slug']:{'received_ms':r['end_ms'], 'winner':r['winner']} for r in filled}
    portfolios = {}
    for delay in (0, 300, 1800):
        delayed = {k:{**v,'received_ms':v['received_ms']+delay*1000} for k,v in labels.items()}
        portfolios[str(delay)] = bankroll_replay(filled, delayed, 50, budget)
    winning_pnl = [r['pnl'] for r in filled if r['won']]
    monthly = {}
    for row in selected:
        month = pd.Timestamp(row['opened_ms'],unit='ms',tz='UTC').strftime('%Y-%m')
        m = monthly.setdefault(month, {'candidates':0,'assumed_fills':0,'wins_filled':0,'pnl':0.})
        m['candidates'] += 1; m['assumed_fills'] += row['cost']>0
        m['wins_filled'] += row['cost']>0 and row['won']; m['pnl'] += row['pnl']
    return {'period':period, 'padding_cents':padding*100, 'budget':budget,
        'fixed_candidates':len(selected), 'fixed_direction_wins':wins,
        'fixed_direction_win_rate':wins/len(selected) if selected else None,
        'assumed_fills':len(filled), 'nonfills':len(unfilled),
        'nonfill_would_win':sum(r['won'] for r in unfilled),
        'nonfill_would_lose':sum(not r['won'] for r in unfilled),
        'filled_win_rate':sum(r['won'] for r in filled)/len(filled) if filled else None,
        'total_pnl_unlimited_funding':pnl,
        'mean_pnl_per_original_candidate':pnl/len(selected) if selected else None,
        'mean_winning_pnl':sum(winning_pnl)/len(winning_pnl) if winning_pnl else None,
        'loss_per_filled_loser':-budget,
        'reference_age_le_15s':sum(r['reference']['age_seconds']<=15 for r in selected),
        'reference_age_le_1500ms':sum(r['reference']['age_seconds']<=1.5 for r in selected),
        'wilson_lower95_iid_direction_only':wilson(wins,len(selected)),
        'diagnostic_mean_pnl_per_candidate_block95':block_interval(selected,first,last),
        'bankroll50_hypothetical_redemption_delay_seconds':portfolios, 'monthly':monthly}


def run(root=ROOT):
    rows, protocol, counts, manifest = cohort(root)
    baseline = scenario(rows,.01,5)
    # This is the acceptance criterion: fail loudly if original parity is lost.
    old = json.loads((root/'late_entries_20260913/summary.json').read_text())['grid']['d690_min0.85']
    for period in ('validation','confirmation'):
        part = [r for r in baseline if r['period']==period]
        if (len(part)!=old[period]['n'] or sum(r['won'] for r in part)!=old[period]['wins']
            or abs(sum(r['pnl'] for r in part)-old[period]['pnl_1c'])>1e-8):
            raise ValueError('OLD BACKTEST PARITY FAILED: do not publish substituted results')
    results = []
    for budget in (5,30):
        for pad in (.01,.02,.03):
            simulated=scenario(rows,pad,budget)
            results.extend(summarize(simulated,period,pad,budget)
                           for period in ('validation','confirmation','all'))
    manifest['code_sha256'] = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root/'backtest_legacy_execution.py',root/'legacy_protocol.json',
                  root/'polymarket_bot/legacy.py',root/'polymarket_bot/actual_research.py',
                  root/'polymarket_bot/robustness.py',root/'report_robust_paper.py')}
    return {'status':'old_configuration_reproduced_execution_readiness_unproven',
        'old_backtest_parity':True, 'protocol':protocol, 'counts':counts, 'results':results,
        'limitations':[
            'Fixed old strategy and candidate cohort; NO boundary-only, session or 0.97 filters.',
            'Historical reference is prices-history, NOT an ask; prices+1/2/3c are assumptions, not observed slippage.',
            'No historical book/depth, quote receipt timestamps, queue or order acknowledgments in the archive.',
            'Fees use cached known curves and cash-equivalent accounting, not historical fee attestation or wallet reconciliation.',
            'Original 5 USD reproduced before 30 USD sensitivity; neither establishes executable 30 USD depth.',
            'All scenarios reuse the original eligible set. Infeasible stressed prices are explicit zero-cost nonfills.',
            'Redemption delays 0/300/1800 seconds are stress assumptions, NOT measured settlement times; pending funds unavailable.',
            'Hosting, funding/withdrawal, gas/relayer and discretionary early sale costs excluded; no rebates assumed.',
            'Previously explored 138-day history, not a new holdout. Bootstrap is diagnostic, especially with only one later loss.',
            'No live approval or real orders; future shadow books still cannot prove actual exchange fills.'
        ], 'manifest':manifest}, baseline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'logs/legacy_execution')
    args=parser.parse_args()
    summary, rows=run()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    (args.output_dir/'original_candidates.json').write_text(json.dumps(rows,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':summary['status'],'counts':summary['counts'],
        'results':[{k:v for k,v in r.items() if k not in ('monthly','bankroll50_hypothetical_redemption_delay_seconds')}
                   for r in summary['results']]},indent=2))


if __name__=='__main__':
    main()
