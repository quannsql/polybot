"""Standalone figures from the offline loss audit; never infer unobserved bids."""
import json
import os

from research_twap_loss_audit import OUT, BASE, load_bids

os.environ.setdefault('MPLCONFIGDIR', str((OUT / 'mplconfig').resolve()))

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

def minute_label(value, _):
    seconds = int(round(value * 60))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def main():
    summary = json.loads((OUT / 'summary.json').read_text())
    records = {loss['trade']['start']: dict(parsed=dict(tokens={})) for loss in summary['losses']}
    # GitHub covers the only loser with any captured book; actual token mapping
    # for HF still comes from official records, never from an inferred side.
    for start in records:
        records[start] = json.loads((BASE / f'raw/markets/{start}/combined.json').read_text())
    bids = load_bids(records)
    plt.rcParams.update({'font.size':10, 'axes.spines.top':False, 'axes.spines.right':False})
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), width_ratios=(1.55, 1), constrained_layout=True)
    fig.suptitle('Three TWAP model losses: warning signals and observed bids', fontsize=17, weight='bold')
    for i, loss in enumerate(summary['losses']):
        trade = loss['trade']; left, right = axes[i]
        points = [p for p in loss['timeline'] if p is not None]
        left.plot([p['delay']/60 for p in points], [p['lead_bps'] for p in points],
                  label='TWAP60 lead', color='#2563eb', linewidth=2)
        left.plot([p['delay']/60 for p in points],
                  [float('nan') if p['spot_lead_bps'] is None else p['spot_lead_bps'] for p in points],
                  label='Chainlink spot lead', color='#f59e0b', linewidth=1.8)
        left.axhline(0, color='#64748b', linewidth=1)
        left.axhline(5, color='#64748b', linewidth=.8, linestyle=':', label='Entry minimum 5bp')
        left.axvline(14, color='#9333ea', linestyle='--', linewidth=1, label='Assumed buy at14:00')
        alert = loss['exits']['spot_cross']['alert']
        left.axvline(alert['delay']/60, color='#dc2626', linewidth=1, linestyle=':',
                     label=f"Spot-cross alert {minute_label(alert['delay']/60, None)}")
        left.set_title(f"Start {loss['vietnam'][:16]} Vietnam | {trade['side'].upper()}", loc='left', weight='bold')
        left.set_ylabel('Lead in bp: positive favors purchased side')
        left.set_xlim(12.5, 15)
        left.set_xticks([12.5, 13, 13.5, 14, 14.5, 15])
        left.xaxis.set_major_formatter(FuncFormatter(minute_label))
        left.grid(alpha=.15)
        if i == 0:
            left.legend(fontsize=8, loc='lower left', ncol=2)
        right.axhline(trade['assumed_price'], color='#9333ea', linestyle='--', linewidth=1,
                      label=f"Assumed purchase {trade['assumed_price']:.3f}")
        quotes = [q for q in bids.groups.get((trade['start'], trade['side']), [])
                  if trade['decision_seconds']*1000 <= q['captured_ms'] < (trade['start']+900)*1000
                  and bids.at(trade['start'], trade['side'], q['captured_ms'])[0] is not None]
        if quotes:
            right.scatter([(q['captured_ms']/1000-trade['start'])/60 for q in quotes],
                          [q['bid'] for q in quotes], s=10, color='#0f766e', label='Captured bid, depth unknown')
            sale = loss['exits']['spot_cross']['exit']
            if sale['status'] == 'indicative_bid_only':
                right.scatter([(sale['quote']['captured_ms']/1000-trade['start'])/60],
                              [sale['bid']], s=65, color='#dc2626', zorder=5,
                              label=f"Alert +500ms bid {sale['bid']:.2f}")
        else:
            right.text(.5, .48, 'NO MATCHING ORDER BOOK\nExit price and PnL unknown',
                       transform=right.transAxes, ha='center', va='center', color='#64748b')
        right.set_ylim(0, 1.03); right.set_xlim(14, 15)
        right.set_xticks([14, 14.25, 14.5, 14.75, 15])
        right.xaxis.set_major_formatter(FuncFormatter(minute_label))
        right.set_ylabel('Outcome token bid ($/share)')
        right.set_title('Price benchmarks only; no certified fills', loc='left', fontsize=10)
        right.grid(alpha=.15); right.legend(fontsize=8, loc='upper right')
    axes[-1,0].set_xlabel('Time since market start (minute:second)')
    axes[-1,1].set_xlabel('Time since market start (minute:second)')
    fig.savefig(OUT / 'loss_paths.png', dpi=160)
    fig.savefig(OUT / 'loss_paths.svg')
    plt.close(fig)
    print(OUT / 'loss_paths.png')


if __name__ == '__main__':
    main()
