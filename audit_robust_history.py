"""Exploratory sensitivity of already-reused history. Does not fit probabilities."""
import argparse
import json
from pathlib import Path

from research_late_entries import build
from report_robust_paper import block_interval


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('logs/robust_history_audit.json'))
    args=parser.parse_args()
    rows,_=build()
    rows=rows[rows.reference.ge(.85)]
    results=[]
    for delay in (630,690,750):
        for period in ('validation','confirmation'):
            # Identical markets for both costs; no changing sample at +3c.
            part=rows[(rows.delay==delay)&(rows.period==period)&rows.cost_1c.notna()&rows.cost_3c.notna()]
            item={'delay':delay,'period':period,'n_same_markets':len(part),
                  'win_rate':float(part.correct.mean()) if len(part) else None,
                  'fresh_reference_le_1500ms':int(part.quote_age.le(1.5).sum()),
                  'fresh_reference_le_15s':int(part.quote_age.le(15).sum())}
            for padding in ('1c','3c'):
                points=[{'opened_ms':int(r.decision_at.timestamp()*1000),'pnl':getattr(r,'pnl_'+padding)} for r in part.itertuples()]
                first=int(rows[rows.period==period].decision_at.min().timestamp()*1000)//86_400_000
                last=int(rows[rows.period==period].decision_at.max().timestamp()*1000)//86_400_000
                item[padding]={'pnl_5usd':float(part['pnl_'+padding].sum()),
                    'mean_pnl_5usd':float(part['pnl_'+padding].mean()) if len(part) else None,
                    'diagnostic_block_95':block_interval(points,first,last)}
            results.append(item)
    result={'status':'exploratory_reused_history_not_forward_validation',
            'limitations':'Lighter-derived signals, sparse reference prices, cached fee metadata; no historical depth/latency proof. $5 arithmetic only; no $30 executable PnL extrapolation.',
            'results':results}
    args.output.parent.mkdir(exist_ok=True,parents=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
