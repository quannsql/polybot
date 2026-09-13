"""Build a paper-only calibration from locally captured, API-confirmed labels."""
import argparse
import json
from pathlib import Path
import sqlite3
import time
from polymarket_bot.advanced_research import fit_calibration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, default=Path('advanced_paper_capture/capture.sqlite3'))
    parser.add_argument('--output', type=Path, default=Path('advanced_paper_capture/calibration.json'))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(Path('D:/polybot').resolve()):
        raise ValueError('Output must stay in Bot2')
    db = sqlite3.connect(args.capture.resolve().as_uri()+'?mode=ro', uri=True)
    rows = []
    try:
        for payload, received, label_json in db.execute('''SELECT o.payload,l.received_ms,l.payload
                FROM advanced_observations o JOIN advanced_labels l ON o.slug=l.slug'''):
            row = json.loads(payload); label = json.loads(label_json)
            row.update(settlement_status=label['status'], settlement_received_ms=received,
                       correct=row['side'] == label.get('winner'))
            rows.append(row)
    finally:
        db.close()
    model = fit_calibration(rows, int(time.time()*1000))
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(model, indent=2), encoding='utf-8')
    print(json.dumps({'cells': len(model['cells']), 'eligible_cells': sum(c['n'] >= model['min_samples'] for c in model['cells'].values()),
                      'mode': model['mode'], 'note': 'No eligible cells means no edge entries; no fabricated default probability.'}))


if __name__ == '__main__':
    main()
