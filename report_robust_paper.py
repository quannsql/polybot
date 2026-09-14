"""Replay captured observations and report uncertainty; never approves live trading."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sqlite3
import statistics
import time

from polymarket_bot.robustness import replay_fill, bankroll_replay


def block_interval(rows, first_day, last_day, block=3, repetitions=2000):
    days = list(range(first_day,last_day+1))
    daily = {day:[0.,0] for day in days}
    for row in rows:
        d = row['opened_ms']//86_400_000
        if d in daily:
            daily[d][0] += row['pnl']; daily[d][1] += 1
    if len(days)<7 or not rows:
        return None
    rng = random.Random(20260914)
    estimates=[]
    for _ in range(repetitions):
        sample=[]
        while len(sample)<len(days):
            start=rng.randrange(len(days))
            sample.extend(days[(start+j)%len(days)] for j in range(block))
        sums=[daily[d] for d in sample[:len(days)]]
        n=sum(x[1] for x in sums)
        if n:
            estimates.append(sum(x[0] for x in sums)/n)
    if not estimates:
        return None
    estimates.sort()
    return [estimates[int(.025*(len(estimates)-1))], estimates[int(.975*(len(estimates)-1))]]


def wilson(wins,n):
    if not n:
        return None
    p=wins/n; z=1.959963984540054
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def report(path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        experiment=db.execute('SELECT * FROM experiment').fetchone()
        if not experiment:
            return {'status':'waiting_for_experiment'}
        protocol=json.loads(experiment['protocol'])
        rows=[dict(r) for r in db.execute('SELECT * FROM paper')]
        windows=[dict(r) for r in db.execute('SELECT * FROM windows ORDER BY start_ms')]
        labels={r['slug']:dict(r) for r in db.execute('SELECT * FROM labels')}
        measurements={(r['slug'],r['policy']):json.loads(r['payload']) for r in db.execute('SELECT * FROM measurements')}
        now_ms=int(time.time()*1000)
        first=experiment['started_ms']//86_400_000
        last=now_ms//86_400_000
        window_signals={r['slug']:json.loads(r['signal']) if r['signal'] else {} for r in windows}
        replay_mismatches=[]
        replay_verified=0
        for row in rows:
            m=measurements.get((row['slug'],row['policy']))
            if not m:
                continue
            try:
                fill=replay_fill(m['intent'],m['book'],m['fee'],m['observed_ms'],protocol,m['depth_fraction'])
            except (KeyError,ValueError):
                if row['status']!='skipped':
                    replay_mismatches.append([row['slug'],row['policy'],'unexpected_replay_rejection'])
                else:
                    replay_verified+=1
                continue
            if row['status']=='skipped' or abs(row['cost']-fill['total_cost'])>1e-7 or abs(row['shares']-fill['shares'])>1e-7:
                replay_mismatches.append([row['slug'],row['policy'],'cost_or_shares_mismatch'])
            else:
                replay_verified+=1
        output=[]
        for policy in sorted(set(r['policy'] for r in rows)):
            selected=[r for r in rows if r['policy']==policy]
            filled=[r for r in selected if r['status']!='skipped']
            settled=[r for r in filled if r['status']=='settled']
            n=len(settled); wins=sum(r['winner']==r['side'] for r in settled)
            delays=[measurements[(r['slug'],policy)]['elapsed_ms'] for r in selected if (r['slug'],policy) in measurements]
            pnl=sum(r['pnl'] for r in settled)
            costs=sum(r['cost'] for r in settled)
            output.append({'policy':policy,'attempts':len(selected),'filled_shadow':len(filled),
                'settled':n,'unique_markets':len({r['slug'] for r in settled}),
                'days_with_settled_entries':len({r['opened_ms']//86_400_000 for r in settled}),
                'wins':wins,'win_rate':wins/n if n else None,'wilson_lower_95_iid_only':wilson(wins,n),
                'pnl':pnl,'mean_pnl':pnl/n if n else None,'return_on_spend':pnl/costs if costs else None,
                'mean_pnl_block_bootstrap_95':block_interval(settled,first,last,protocol['bootstrap_block_days']),
                'observed_delay_median_ms':statistics.median(delays) if delays else None,
                'observed_delay_max_ms':max(delays) if delays else None,
                'skip_reasons':dict(Counter(json.loads(r['payload']).get('reason') for r in selected if r['status']=='skipped')),
                'bankroll_50':bankroll_replay(filled,labels,protocol['initial_bankroll_usd'],protocol['budget_usd'])})
        # Paired profits count abstention/unfilled as zero, but exclude unlabelled windows.
        indexed={(r['slug'],r['policy']):r for r in rows}
        paired=[]
        primary=protocol['primary_policy']; baseline=primary.replace('dca_','favourite_',1)
        for slug,s in window_signals.items():
            a,b=indexed.get((slug,primary)),indexed.get((slug,baseline))
            if s.get('direction') and slug in labels and a and b and a['status']!='pending' and b['status']!='pending':
                paired.append({'slug':slug,'opened_ms':a['opened_ms'],'pnl':(a['pnl'] or 0)-(b['pnl'] or 0)})
        return {'status':'diagnostic_only_no_live_approval','protocol_hash':experiment['hash'],
            'protocol_id':protocol['id'],'primary_policy':primary,'generated_ms':now_ms,
            'elapsed_days':(now_ms-experiment['started_ms'])/86_400_000,
            'final_review_due_ms':experiment['started_ms']+protocol['validation_days']*86_400_000,
            'windows_observed':len(windows),'labelled_markets':len(labels),
            'frozen_dca_signals':sum(bool(s.get('direction')) for s in window_signals.values()),
            'window_reasons':dict(Counter(r['reason'] for r in windows)),
            'replay_verified':replay_verified,'replay_mismatches':replay_mismatches,
            'policies':output,'paired_dca_minus_favourite':{'n':len(paired),
                'pnl_difference':sum(r['pnl'] for r in paired),
                'mean_difference_block_95':block_interval(paired,first,last,protocol['bootstrap_block_days'])},
            'limitations':[
                'Displayed depth shadow fills, no exchange execution; cash-equivalent fees.',
                'Arrival REST book measured after target delay plus RTT; not an exact 250/500/1000ms exchange fill.',
                'Bootstrap intervals are diagnostic and unreliable with few days or rare losses; zero observed losses is not zero risk.',
                'All scenarios share markets; do not pool sample sizes or PnL. Continuous peeking does not establish significance.',
                'Fixed boundary/08-22 UTC/11:30 rule experiment differs from old latest_5m paper and live continuous-window plus calibration.',
                'No oracle prediction model is tested: Binance supplies signals; Polymarket confirms outcome labels.',
                'No automatic calibration approval, historical holdout claim, or live deployment.'
            ]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=report(args.capture)
    body=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:
        args.output.write_text(body,encoding='utf-8')
    print(body)


if __name__=='__main__':
    main()
