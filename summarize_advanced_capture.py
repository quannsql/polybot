"""Read-only capture QA and settled maker queue scenarios, never actual PnL."""
import argparse
import json
from pathlib import Path
import sqlite3
from collections import Counter
from decimal import Decimal


def summarize(path):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        kinds = dict(db.execute('SELECT kind,count(*) FROM events GROUP BY kind'))
        oracle = Counter(); accepted = Counter(); skips = Counter(); intents = {}; results = {}
        for kind, slug, payload in db.execute('SELECT kind,slug,payload FROM events ORDER BY id'):
            p = json.loads(payload)
            if kind == 'advanced_oracle_raw':
                topic = p['event'].get('topic', 'unknown'); oracle[topic] += 1
                if p.get('accepted'):
                    accepted[topic] += 1
            if kind in ['advanced_book_skip', 'advanced_oracle_skip', 'advanced_tick_error']:
                skips[p.get('reason', p.get('error', 'unknown'))] += 1
            if kind == 'maker_probe_intent':
                intents[(p['token'],p['placed_ms'])] = {'slug': slug, 'side': p['side']}
            if kind == 'maker_probe_result':
                results[(p['token'],p['placed_ms'])] = p
        labels = {s:json.loads(p) for s,p in db.execute('SELECT slug,payload FROM advanced_labels')}
        scenarios = []
        for key,p in results.items():
            context = intents.get(key)
            if not context:
                continue
            label = labels.get(context['slug'], {})
            fill = Decimal(p['shares_scenario_filled']); price = Decimal(p['price'])
            valid = not p['invalidated_by_gap']
            pnl = (fill*(int(context['side']==label.get('winner'))-price)
                   if valid and label.get('status')=='confirmed' else None)
            scenarios.append({**context, **p, 'settlement_status': label.get('status','pending'),
                               'queue_scenario_pnl': str(pnl) if pnl is not None else None})
        return {'events': kinds, 'oracle_frames_by_topic': dict(oracle), 'accepted_live_points': dict(accepted),
                'skip_reasons': dict(skips), 'maker_scenarios': scenarios,
                'warning': 'Both-side independent queue probes, not DCA strategy trades or real fills. No portfolio PnL claim.'}
    finally:
        db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture', type=Path, default=Path('advanced_paper_capture_v3/capture.sqlite3'))
    p.add_argument('--output', type=Path, default=Path('advanced_paper_capture_v3/qa_summary.json'))
    args=p.parse_args()
    if not args.output.resolve().is_relative_to(Path('D:/polybot').resolve()):
        raise ValueError('Output must stay in Bot2')
    result=summarize(args.capture)
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='maker_scenarios'}, indent=2))
    print('maker_scenarios',len(result['maker_scenarios']),
          'nonzero_queue_fills',sum(Decimal(x['shares_scenario_filled'])>0 for x in result['maker_scenarios']))


if __name__=='__main__':
    main()
