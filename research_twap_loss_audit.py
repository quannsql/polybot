"""Post-hoc BTC15m TWAP loss diagnosis, causal entry filters and exit alerts.

The 119-entry reference model is preserved. Spot and TWAP are used only as-of
each decision; outcome labels score results, never generate warnings. Captured
bids are price benchmarks with incomplete depth/clock attestations, not fills.
"""
from collections import Counter
from decimal import Decimal
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_fresh_data import dump, sha
from research_twap_stability import START, FIT, END, TwapIndex, reference_trade, replay

BASE = Path('data/twap_stability_20261108')
OUT = Path('data/twap_loss_audit_20261108')
ENTRY_RULES = ('baseline', 'buffer10', 'momentum10', 'momentum30',
               'projection30', 'spot_on_side', 'spot_not_behind_twap',
               'spot_on_side_and_momentum30')
EXIT_RULES = ('spot_cross', 'twap_half_entry_lead', 'twap_projection30_cross', 'twap_cross')


def freeze():
    protocol = dict(version=1, parent_summary_sha256=sha(BASE / 'stability_summary.json'),
        source_revision=json.loads((BASE / 'hf_revision.json').read_text())['sha'],
        universe='Original control_1400_5bp, reference age75s, ref>=.85, ref+1c<1; stake20',
        split='08..14 August calibration; 15..21 August evaluation, all previously inspected',
        research_status='Post-hoc hypothesis generation after identifying the three evaluation losses; NO new untouched holdout',
        entry_rules=list(ENTRY_RULES), primary_entry='spot_on_side_and_momentum30',
        entry_semantics='Momentum signed toward purchased side; zero threshold; projection continues trailing30s TWAP slope to expiry',
        exit_rules=list(EXIT_RULES), primary_exit='spot_cross',
        confirmation='3 distinct source observations, source gaps<=5s; missing/false resets; monitor every1s at T+841..899',
        exit_semantics='Spot/zero crosses <=0; half-lead <=half frozen entry lead; projection30 <=0',
        oracle_max_age_ms=3000, opening_max_receive_delay_ms=5000,
        entry_model='Identical original reference fills; not new captured-ask buys',
        exit_latency_ms=[500, 1000], exit_capture_max_age_ms=1500,
        exit_quote='Latest captured bid as-of arrival; require a NEW snapshot since signal; never use next/future snapshot',
        primary_clock_shift_ms=0, clock_sensitivity_ms=[-1000, 1000],
        bid_stop='Separate 10% decline of net bid value from per-share entry cost, evaluated only where quotes observed',
        hypothetical_exit_bids=[.25, .5, .75, .9], additional_exit_overhead=.01,
        costs='Venue buy fee in initial unit cost; sell fee on proceeds, metadata curve; full-size capacity is UNKNOWN for GitHub bids',
        selection='Report every frozen rule and false alarms on winners; never optimize only the three losers',
        no_live_changes=True)
    path = OUT / 'protocol.json'
    if path.exists() and json.loads(path.read_text()) != protocol:
        raise ValueError('Preserve old protocol; use a new output directory for changed rules')
    dump(path, protocol)
    return protocol


def load_stream(paths):
    frames = []
    for path in paths:
        f = pd.read_parquet(path)
        frames.append(pd.DataFrame(dict(
            observed_ms=pd.to_datetime(f.observationsTimestamp, utc=True).dt.as_unit('ms').astype('int64'),
            received_ms=pd.to_datetime(f.receiveMicrosecondTimestamp, utc=True).dt.as_unit('ms').astype('int64'),
            exact=f.price.map(str),
            value=f.price.map(lambda p: float(Decimal(str(p)) / Decimal(10 ** 18))))))
    f = pd.concat(frames, ignore_index=True)
    if not np.isfinite(f.value).all() or not f.value.gt(0).all():
        raise ValueError('Invalid stream price')
    conflicts = f.groupby('observed_ms').exact.nunique()
    bad = set(conflicts[conflicts.gt(1)].index)
    clean = f.loc[~f.observed_ms.isin(bad)].sort_values(['observed_ms', 'received_ms'])
    usable = clean.drop_duplicates('observed_ms', keep='first')
    quality = dict(raw_reports=len(f), usable_reports=len(usable), conflicting_instants=len(bad),
                   duplicate_rows=len(clean) - len(usable))
    return TwapIndex(usable), quality


def context(twap, spot, start, delay, side):
    """Only reports both observed and received by this clock tick are usable."""
    feature, reason = twap.decision(start, delay)
    if feature is None:
        return None, reason
    now = (start + delay) * 1000
    opening = feature['opening']['value']
    current = feature['current']
    sign = 1 if side == 'up' else -1
    lead = sign * (current['value'] / opening - 1) * 10000
    result = dict(start=start, delay=delay, clock_ms=now, lead_bps=lead,
                  twap_value=current['value'], opening_value=opening,
                  twap_observed_ms=current['observed_ms'], twap_received_ms=current['received_ms'])
    for seconds in (10, 30, 60):
        past = twap.at(now - seconds * 1000)
        momentum = None if past is None else sign * (current['value'] - past['value']) / opening * 10000
        result[f'momentum{seconds}_bps'] = momentum
        if seconds == 30:
            span = None if past is None else (current['observed_ms'] - past['observed_ms']) / 1000
            remaining = (start + 900) - current['observed_ms'] / 1000
            result['projection30_bps'] = (lead + momentum * remaining / span
                                           if span is not None and span > 0 else None)
    raw = spot.at(now)
    result['spot_lead_bps'] = None if raw is None else sign * (raw['value'] / opening - 1) * 10000
    result['spot_minus_twap_bps'] = None if raw is None else sign * (raw['value'] - current['value']) / opening * 10000
    result['spot_value'] = None if raw is None else raw['value']
    result['spot_observed_ms'] = None if raw is None else raw['observed_ms']
    result['spot_received_ms'] = None if raw is None else raw['received_ms']
    return result, 'valid'


def entry_keep(rule, values):
    if rule == 'baseline':
        return True
    if values is None:
        return None
    if rule == 'buffer10':
        return values['lead_bps'] >= 10
    keys = dict(momentum10='momentum10_bps', momentum30='momentum30_bps',
                projection30='projection30_bps', spot_on_side='spot_lead_bps',
                spot_not_behind_twap='spot_minus_twap_bps')
    if rule == 'spot_on_side_and_momentum30':
        a, b = values['spot_lead_bps'], values['momentum30_bps']
        return None if a is None or b is None else a > 0 and b >= 0
    value = values[keys[rule]]
    return None if value is None else (value >= 0 if rule.startswith('momentum') or rule == 'spot_not_behind_twap' else value > 0)


class Confirmation:
    """Repeated polling of a single report never counts as confirmation."""
    def __init__(self):
        self.observations = []

    def update(self, condition, observed_ms):
        if condition is None or observed_ms is None or not condition:
            self.observations = []
            return False
        if self.observations and observed_ms == self.observations[-1]:
            return len(self.observations) >= 3
        if self.observations and not 0 < observed_ms - self.observations[-1] <= 5000:
            self.observations = []
        self.observations.append(observed_ms)
        return len(self.observations) >= 3


def exit_alert(rule, initial, points):
    confirm = Confirmation()
    for point in points:
        if point is None:
            confirm.update(None, None)
            continue
        key = 'spot_lead_bps' if rule == 'spot_cross' else 'projection30_bps' if rule == 'twap_projection30_cross' else 'lead_bps'
        value = point[key]
        threshold = initial['lead_bps'] / 2 if rule == 'twap_half_entry_lead' else 0
        observed = point['spot_observed_ms'] if rule == 'spot_cross' else point['twap_observed_ms']
        if confirm.update(None if value is None else value <= threshold, observed):
            return dict(rule=rule, signal_ms=point['clock_ms'], delay=point['delay'],
                        seconds_remaining=900 - point['delay'], values=point)
    return None


class BidIndex:
    def __init__(self, frame):
        self.groups = {}
        f = frame.sort_values(['captured_ms', 'priority']).drop_duplicates(['start', 'side', 'captured_ms'], keep='last')
        for key, group in f.groupby(['start', 'side'], sort=False):
            self.groups[key] = group.to_dict('records')
        self.times = {key: np.array([q['captured_ms'] for q in group], dtype=np.int64)
                      for key, group in self.groups.items()}

    def at(self, start, side, now_ms, max_age=1500, shift=0):
        key = start, side
        if key not in self.groups:
            return None, 'no_market_book'
        i = np.searchsorted(self.times[key], now_ms - shift, side='right') - 1
        if i < 0:
            return None, 'no_prior_book'
        quote = dict(self.groups[key][i])
        quote['available_ms'] = quote['captured_ms'] + shift
        if now_ms - quote['available_ms'] > max_age:
            return None, 'stale_capture'
        if not np.isfinite(quote['bid']) or not 0 < quote['bid'] < 1:
            return None, 'no_positive_bid'
        if np.isfinite(quote['ask']) and quote['bid'] >= quote['ask']:
            return None, 'crossed_book'
        return quote, 'valid'


def load_bids(records):
    g = pd.read_parquet(BASE / 'quotes/github_btc15m_quotes.parquet')
    g = g.loc[g.window_start.ge(FIT) & g.window_start.lt(END) & g.ok.eq(1)]
    frames = [pd.DataFrame(dict(start=g.window_start, side=side, captured_ms=g.ts_ms,
        bid=g[side + '_bid'], ask=g[side + '_ask'], bid_size=np.nan,
        source='github_top_bid_size_NOT_RECORDED', priority=0)) for side in ('up', 'down')]
    h = pd.read_parquet(BASE / 'quotes/hf_btc15m_l2.parquet')
    h['start'] = h.market_slug.str.rsplit('-', n=1).str[-1].astype('int64')
    rows = []
    for r in h.loc[h.start.ge(FIT) & h.start.lt(END)].itertuples():
        matches = [side for side, token in records.get(r.start, {}).get('parsed', {}).get('tokens', {}).items()
                   if str(token) == str(r.token_id)]
        if len(matches) != 1 or len(r.bid_prices) == 0:
            continue
        bid = max(float(p) for p in r.bid_prices)
        size = sum(float(s) for p, s in zip(r.bid_prices, r.bid_sizes) if float(p) == bid)
        rows.append(dict(start=int(r.start), side=matches[0],
            captured_ms=int(pd.Timestamp(r.captured_at).timestamp() * 1000), bid=bid,
            ask=min(map(float, r.ask_prices)) if len(r.ask_prices) else np.nan,
            bid_size=size, source='hf_top', priority=1))
    frames.append(pd.DataFrame(rows))
    return BidIndex(pd.concat(frames, ignore_index=True))


def sale_pnl(trade, bid, rate, overhead=.01):
    shares = 20 / trade['unit_cost']
    net = bid - rate * bid * (1 - bid)
    return shares * net - 20 - overhead


def observed_exit(trade, alert, bids, rate, latency=500, shift=0):
    if alert is None:
        return dict(status='hold_no_alert')
    arrival = alert['signal_ms'] + latency
    if arrival >= (trade['start'] + 900) * 1000:
        return dict(status='arrival_after_close')
    quote, why = bids.at(trade['start'], trade['side'], arrival, shift=shift)
    if quote is None:
        return dict(status=why)
    if quote['available_ms'] <= alert['signal_ms']:
        return dict(status='no_new_snapshot_during_latency')
    size = quote['bid_size']
    capacity = 'unknown_bid_size' if not np.isfinite(size) else ('top_half_depth_sufficient' if .5 * size >= 20 / trade['unit_cost'] else 'top_half_depth_insufficient')
    quote['bid_size'] = None if not np.isfinite(size) else float(size)
    return dict(status='indicative_bid_only', bid=quote['bid'], quote=quote,
                latency_ms=latency, clock_shift_ms=shift, capacity=capacity,
                hypothetical_full_sale_pnl=sale_pnl(trade, quote['bid'], rate),
                certified_fill=False)


def summarize(rows):
    pnl = sum(20 * (int(r['won']) / r['unit_cost'] - 1) for r in rows)
    daily = Counter()
    for r in rows:
        daily[r['day']] += 20 * (int(r['won']) / r['unit_cost'] - 1)
    return dict(n=len(rows), wins=sum(r['won'] for r in rows), losses=sum(not r['won'] for r in rows),
        pnl_20=pnl, daily_pnl_20=dict(daily))


def exit_summary(rows, alerts, bids, records, latency=500, shift=0):
    statuses = Counter(); details = []
    lower = upper = 0.
    triggered_wins = triggered_losses = 0
    for r in rows:
        alert = alerts[r['start']]
        result = observed_exit(r, alert, bids, records[r['start']]['fee']['rate'], latency, shift)
        statuses[result['status']] += 1
        hold = 20 * (int(r['won']) / r['unit_cost'] - 1)
        if alert is None or result['status'] == 'arrival_after_close':
            lower += hold; upper += hold
        if alert is not None:
            triggered_wins += int(r['won']); triggered_losses += int(not r['won'])
            if result['status'] == 'arrival_after_close':
                pass  # No permitted sale; retain the modeled settlement payoff.
            elif result['status'] == 'indicative_bid_only':
                lower += result['hypothetical_full_sale_pnl']; upper += result['hypothetical_full_sale_pnl']
            else:
                lower += -20.01; upper += 20 / r['unit_cost'] - 20.01
        details.append(dict(start=r['start'], won_if_held=r['won'], hold_pnl=hold, alert=alert, exit=result))
    triggered = [r for r in rows if alerts[r['start']] is not None]
    scenarios = {str(bid): sum(sale_pnl(r, bid, records[r['start']]['fee']['rate'])
        if alerts[r['start']] is not None and alerts[r['start']]['signal_ms'] + latency < (r['start'] + 900) * 1000
        else 20 * (int(r['won']) / r['unit_cost'] - 1) for r in rows)
        for bid in (.25, .5, .75, .9)}
    return dict(n=len(rows), alerts=len(triggered), alerts_on_losers=triggered_losses,
        alerts_on_would_be_winners=triggered_wins, exit_statuses=dict(statuses),
        latency_ms=latency, clock_shift_ms=shift,
        covered_quote_and_unobserved_sale_bounds=[lower, upper],
        bounds_warning='Conditional on original entries and full sales at captured bids; missing sale price spans0..1. NOT executable bounds.',
        hypothetical_constant_bid_week_pnl=scenarios, certified_week_exit_pnl=None,
        details=details)


def quote_stop(trade, bids, rate):
    for quote in bids.groups.get((trade['start'], trade['side']), []):
        time = quote['captured_ms']
        if not (trade['decision_seconds'] * 1000 < time < (trade['start'] + 900) * 1000):
            continue
        if bids.at(trade['start'], trade['side'], time)[0] is None:
            continue
        bid = quote['bid']
        if np.isfinite(bid) and 0 < bid < 1 and bid - rate * bid * (1 - bid) <= .9 * trade['unit_cost']:
            return dict(rule='bid_value_stop10pct', signal_ms=time,
                        delay=(time - trade['start'] * 1000) / 1000,
                        seconds_remaining=(trade['start'] + 900) - time / 1000)
    return None


def quote_coverage(trade, bids):
    """Missing monitoring data cannot be interpreted as absence of a price stop."""
    lo = trade['decision_seconds'] * 1000
    hi = (trade['start'] + 900) * 1000
    stamps = [q['captured_ms'] for q in bids.groups.get((trade['start'], trade['side']), [])
              if lo <= q['captured_ms'] < hi and bids.at(trade['start'], trade['side'], q['captured_ms'])[0] is not None]
    maximum_gap = max(np.diff([lo] + stamps + [hi])) if stamps else hi - lo
    return dict(valid_captures=len(stamps), max_monitor_gap_ms=int(maximum_gap),
                continuously_observed_under_1p5s_gap=bool(stamps and maximum_gap <= 1500))


def entry_capacity(rows, records, gate_values):
    """Extra post-hoc diagnostic: capacity under the ORIGINAL frozen ref+1c cap."""
    from research_twap_depth import load_quotes, top_fill
    quotes, coverage = load_quotes(records)
    outcomes = {}
    for row in rows:
        now = row['decision_seconds'] * 1000
        quote, reason = quotes.at(row['start'], row['side'], now + 500)
        if quote is not None:
            if quote['available_ms'] <= now:
                reason = 'no_new_arrival_snapshot'
            elif quote['ask'] > row['assumed_price']:
                reason = 'ask_above_reference_cap'
            else:
                try:
                    top_fill(quote, records[row['start']]['fee'], budget=20, haircut=.5)
                    reason = 'captured_top_capacity_only'
                except ValueError as error:
                    reason = str(error)
        outcomes[row['start']] = reason
    rules = []
    for rule in ENTRY_RULES:
        kept = [row for row in rows if entry_keep(rule, gate_values[row['start']]) is True]
        rules.append(dict(rule=rule, n_reference_entries=len(kept),
                          statuses=dict(Counter(outcomes[row['start']] for row in kept))))
    return dict(scope='Post-hoc entry-capacity diagnostic on original119 hypothetical entries, NOT new trade selection',
        parameters=dict(budget=20, latency_ms=500, max_capture_age_ms=1500, depth_haircut=.5,
                        cap='original frozen reference+0.01', actual_ask_floor='none; original minimum applies to reference'),
        coverage=coverage, rules=rules,
        known_losses={str(row['start']): outcomes[row['start']] for row in rows if not row['won']},
        executable_pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    freeze()
    if args.prepare_only:
        print('Post-hoc policy family frozen before inspecting new spot/path results.')
        return
    print('Loading verified cached reports...', flush=True)
    twap, twap_quality = load_stream(sorted((BASE / 'twap').glob('*.parquet')))
    spot_paths = sorted((OUT / 'spot').glob('*.parquet'))
    if len(spot_paths) != 14:
        raise ValueError('Run download_twap_loss_data.py first')
    spot, spot_quality = load_stream(spot_paths)
    records = {int(p.parent.name): json.loads(p.read_text()) for p in (BASE / 'raw/markets').glob('*/combined.json')}
    features = [f for f in json.loads((BASE / 'features.json').read_text()) if f['delay'] == 840]
    pool = []
    for feature in features:
        row, _ = reference_trade(feature, records[feature['start']], 5, 75)
        if row:
            pool.append(row)
    evaluation = [r for r in pool if FIT <= r['start'] < END]
    expected = [r for r in json.loads((BASE / 'evaluation_trades.json').read_text())
                if r['policy'] == 'control_1400_5bp' and r['max_age'] == 75]
    assert len(evaluation) == 119 and sum(r['won'] for r in evaluation) == 116
    assert {r['start'] for r in expected} == {r['start'] for r in evaluation}
    assert abs(summarize(evaluation)['pnl_20'] - 22.55975741732056) < 1e-8
    entries = {r['start']: context(twap, spot, r['start'], 840, r['side'])[0] for r in pool}
    gate_results = []
    for rule in ENTRY_RULES:
        periods = {}
        for name, lo, hi in [('calibration', START, FIT), ('evaluation', FIT, END)]:
            rows = [r for r in pool if lo <= r['start'] < hi]
            kept = [r for r in rows if entry_keep(rule, entries[r['start']]) is True]
            rejected = [r for r in rows if entry_keep(rule, entries[r['start']]) is not True]
            periods[name] = dict(**summarize(kept), removed_winners=sum(r['won'] for r in rejected),
                removed_losers=sum(not r['won'] for r in rejected),
                unavailable_input=sum(entry_keep(rule, entries[r['start']]) is None for r in rows))
            if name == 'evaluation':
                periods[name]['wallet50_stake20_daily_stop'] = replay(kept, 20, True, 300)
        gate_results.append(dict(rule=rule, **periods))
    bids = load_bids(records)
    paths = {}
    for r in evaluation:
        paths[r['start']] = [context(twap, spot, r['start'], delay, r['side'])[0]
                             for delay in range(841, 900)]
    exit_results = []
    exit_details = {}
    for rule in EXIT_RULES:
        alerts = {r['start']: exit_alert(rule, entries[r['start']], paths[r['start']]) for r in evaluation}
        for latency, shift in ((500, 0), (1000, 0), (500, -1000), (500, 1000)):
            result = exit_summary(evaluation, alerts, bids, records, latency, shift)
            details = result.pop('details')
            exit_results.append(dict(rule=rule, **result))
            if (latency, shift) == (500, 0):
                exit_details[rule] = details
    stops = {r['start']: quote_stop(r, bids, records[r['start']]['fee']['rate']) for r in evaluation}
    stop_result = exit_summary(evaluation, stops, bids, records)
    stop_details = stop_result.pop('details')
    stop_later = exit_summary(evaluation, stops, bids, records, latency=1000)
    stop_later_details = stop_later.pop('details')
    monitoring = {r['start']: quote_coverage(r, bids) for r in evaluation}
    stop_summary = dict(observed_signals=stop_result['alerts'],
        observed_signals_on_losers=stop_result['alerts_on_losers'],
        observed_signals_on_winners=stop_result['alerts_on_would_be_winners'],
        continuously_observed_trade_count=sum(q['continuously_observed_under_1p5s_gap'] for q in monitoring.values()),
        unknown_or_interrupted_monitoring_count=sum(not q['continuously_observed_under_1p5s_gap'] for q in monitoring.values()),
        exit_statuses_500ms=stop_result['exit_statuses'], exit_statuses_1000ms=stop_later['exit_statuses'],
        full_week_stop_pnl=None, warning='No stop observed in a coverage gap is UNKNOWN; never impute hold-to-settlement as a price-stop outcome.',
        monitoring=monitoring)
    losses = []
    for r in evaluation:
        if r['won']:
            continue
        loss = dict(trade=r, utc=str(pd.Timestamp(r['start'], unit='s', tz='UTC')),
            vietnam=str(pd.Timestamp(r['start'], unit='s', tz='UTC').tz_convert('Asia/Ho_Chi_Minh')),
            entry_features=entries[r['start']],
            final_metadata=records[r['start']]['event']['body'].get('eventMetadata', {}),
            entry_filter_passes={rule: entry_keep(rule, entries[r['start']]) for rule in ENTRY_RULES},
            book_market_present=(r['start'], r['side']) in bids.groups,
            checkpoints=[context(twap, spot, r['start'], d, r['side'])[0] for d in (810, 840, 850, 860, 870, 880, 890, 899)],
            timeline=[context(twap, spot, r['start'], d, r['side'])[0] for d in range(750, 900)],
            exits={rule: next(x for x in exit_details[rule] if x['start'] == r['start']) for rule in EXIT_RULES},
            bid_stop=next(x for x in stop_details if x['start'] == r['start']))
        losses.append(loss)
    report = dict(protocol_sha256=sha(OUT / 'protocol.json'), code_sha256=sha(Path(__file__)),
        source_quality=dict(twap=twap_quality, spot=spot_quality),
        baseline=summarize(evaluation), baseline_wallet50_stake20_daily_stop=replay(evaluation, 20, True, 300),
        entry_filters=gate_results, exits=exit_results,
        quote_stop10pct=stop_summary, losses=losses,
        entry_capacity_original_cap=entry_capacity(evaluation, records, entries),
        monitor_missing_seconds=sum(p is None for points in paths.values() for p in points),
        certified_week_execution_pnl=None,
        limitations=['All rules are post-hoc hypotheses; no new independent holdout.',
            'Original price-history buys assumed; ask fills not validated.',
            'Spot is a warning feature, never the settlement substitute.',
            'GitHub has no bid sizes. Source clock alignment unverified. Captured bids do not guarantee sales.',
            'Unknown exit prices, missing books and missed alerts are never filled using future reference prices.',
            'Metadata fee curve is not an as-of historical fee attestation; exit overhead0.01 is assumed.'])
    dump(OUT / 'summary.json', report)
    dump(OUT / 'exit_details.json', dict(**exit_details, bid_value_stop10pct=stop_details,
                                        bid_value_stop10pct_1000ms=stop_later_details))
    dump(OUT / 'entry_features.json', [dict(trade=r, features=entries[r['start']]) for r in pool])
    pd.json_normalize([dict(period='calibration' if r['start'] < FIT else 'evaluation',
        trade=r, features=entries[r['start']],
        rules={rule:entry_keep(rule, entries[r['start']]) for rule in ENTRY_RULES})
        for r in pool]).to_csv(OUT / 'candidate_trades.csv', index=False)
    dump(OUT / 'paths.json', paths)
    pd.json_normalize(losses).to_csv(OUT / 'losses.csv', index=False)
    source_files = [BASE / 'features.json', BASE / 'evaluation_trades.json', BASE / 'stability_summary.json',
        BASE / 'quotes/github_btc15m_quotes.parquet', BASE / 'quotes/hf_btc15m_l2.parquet', OUT / 'spot_manifest.json']
    source_files += sorted((BASE / 'twap').glob('*.parquet')) + spot_paths
    source_files += sorted((BASE / 'raw/markets').glob('*/combined.json'))
    dump(OUT / 'run_manifest.json', dict(code_sha256=sha(Path(__file__)),
        protocol_sha256=sha(OUT / 'protocol.json'), sources={str(p):sha(p) for p in source_files}))
    print(json.dumps(dict(baseline=report['baseline'], entry_filters=gate_results,
        exits=exit_results, losses=[dict(start=l['trade']['start'], side=l['trade']['side'],
            entry=l['entry_features'], book=l['book_market_present'],
            exits={k:dict(alert=v['alert'], exit=v['exit']) for k,v in l['exits'].items()}) for l in losses]), indent=2), flush=True)


if __name__ == '__main__':
    main()
