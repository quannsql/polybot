"""Offline production-gate parity audit; never connects to exchanges or trades."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_poly_research import read_minutes
from polymarket_bot.entry_gates import PROFILE_B, decide, evaluate
from research_gate_combinations_1230 import inputs
from research_remaining_losses_1230 import entry_inputs, keep, RULES

ROOT = Path(__file__).resolve().parent


def run():
    source = ROOT / 'logs/gate_combinations_1230/candidates.json'
    rows = json.loads(source.read_text())
    meta = json.loads((ROOT / 'timeframe_research_20260913/summary.json').read_text())['metadata']
    paths = [Path(s['path']) for s in meta['sources']]
    own, own_meta = read_minutes(paths)
    peer, peer_meta = read_minutes([p.with_name(p.name.replace('BTCUSDT', 'ETHUSDT')) for p in paths])
    assert [s['sha256'] for s in own_meta['sources']] == [s['sha256'] for s in meta['sources']]
    rule = next(r for r in RULES if r['id'] == 'against_slope_z0.75')
    retained, audited = [], []
    for row in rows:
        start = pd.Timestamp(row['start'], unit='s', tz='UTC')
        at = start + pd.Timedelta(minutes=12)
        frames = [f.loc[(f.index >= at-pd.Timedelta(days=4)) & (f.index < at)].reset_index()
                  for f in (own, peer)]
        gate = evaluate(*frames, start=start, signal_at=row['signal_at'],
                        side=row['side'], source=row['source'], profile=PROFILE_B)
        expected = decide(inputs(row))[0] and keep(entry_inputs(row), rule)
        assert gate['keep'] == bool(expected), (row['slug'], gate, expected)
        assert gate['inputs']['slope15_agrees'] == row['features']['slope15_agrees']
        for key, archived in [('z', 'lead_z'), ('vol', 'vol_ratio')]:
            actual, saved = gate['inputs'][key], row['features'][archived]
            assert (actual is None and saved is None) or np.isclose(actual, saved, rtol=1e-8, atol=1e-8)
        for flag in ('memory', 'old_signal', 'aux_shock'):
            assert gate['inputs'][flag] == inputs(row)[flag], (row['slug'], flag)
        audited.append(dict(slug=row['slug'], gate=gate))
        if gate['keep']:
            retained.append(row)
    assert len(rows) == 410 and len(retained) == 281 and sum(r['won'] for r in retained) == 281
    pnl = sum(r['pnl1'] for r in retained)
    assert abs(pnl-218.9020978767) < 1e-7
    report = dict(profile=PROFILE_B, original_candidates=len(rows), kept=len(retained),
                  wins=sum(r['won'] for r in retained), pnl_reference_plus_1c=pnl,
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  code_sha256=hashlib.sha256((ROOT/'polymarket_bot/entry_gates.py').read_bytes()).hexdigest(),
                  minute_sources=dict(btc=own_meta, eth=peer_meta), gates=audited,
                  limitation='Historical input/mask parity, not a historical order-book execution test or future win-rate guarantee.')
    out = ROOT/'logs/remaining_losses_1230/production_b_audit.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('minute_sources','gates')}))


if __name__ == '__main__':
    run()
