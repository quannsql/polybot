# Historical approximation of fixed 11:30 protocol

Executed on 2026-09-14 using cached predictions and confirmed Polymarket labels
from 2026-04-19 through 2026-09-03 (138 calendar days). Configuration was not
optimized during this run. Historical features are Lighter-derived, not Binance.

The existing 1,413 latest-signal opportunities reduce to 801 boundary signals,
then 475 in the 08–22 UTC session. All 475 have cached confirmed labels;
473 have an as-of outcome reference within 75 seconds at T+690. None of these
473 references has age <=1.5 seconds; only 30 have age <=15 seconds.

Historical executable asks do not exist in these inputs. The model substitutes
reference+1/2/3 cents as an assumed ask, applies the 0.85–0.97 price filter to
that assumed ask, and includes cached per-market fee costs. No spread, depth,
latency or FOK claim is made. The padding is an assumed price, not measured
slippage or the live order cap relative to an actual decision ask.

## Primary approximation: reference +1 cent, $30 all-in per trade

| Period | Trades | Wins | Win rate | Total PnL | Mean PnL |
|---|---:|---:|---:|---:|---:|
| Apr 19–Jul 13 | 55 | 49 | 89.09% | -$66.56 | -$1.210 |
| Jul 14–Sep 03 | 18 | 18 | 100% | +$45.79 | +$2.544 |
| Combined | 73 | 67 | 91.78% | -$20.77 | -$0.285 |

The combined diagnostic 3-day-block bootstrap 95% interval for mean PnL is
[-$2.285, +$1.455]. The all-winning later subset is small; resampling it cannot
discover unobserved losses. Neither period is a pristine holdout because the
history was previously investigated.

## Price sensitivity

| Assumed ask | Eligible trades | Win rate | Total PnL |
|---|---:|---:|---:|
| Reference +1c | 73 | 91.78% | -$20.77 |
| Reference +2c | 76 | 89.47% | -$73.94 |
| Reference +3c | 67 | 88.06% | -$90.45 |

Filtering assumed ask changes membership in each scenario. On the same 55
markets eligible under all three prices, PnL is respectively -$42.63,
-$59.04 and -$75.08. Do not add scenarios.

## Actual $50 capital constraint

For the +1c combined chronological scenario, an initial $50 wallet takes 17
trades and ends with $21.63, skipping the remaining 56 opportunities because
cash is below the fixed $30 stake. The unlimited-capital -$20.77 result above
is not the PnL of this constrained portfolio. Payout credit at contract expiry
is optimistic: settlement/redemption delays, gas and historical liquidity are
not observed. Separate-period portfolios reset to $50 and cannot be added.

## Reproduction

```powershell
.\.venv-trial\Scripts\python.exe -B backtest_fixed_protocol_history.py
```

`logs/fixed_protocol_history/summary.json` stores configuration, counters,
source hashes, source-group results and intervals. `trades.json` contains each
selected market, assumed ask, quote age, fee-inclusive cost, shares and PnL.
Inputs and Bot1 are unchanged. No approval or change to the running forward
experiment is made. This historical approximation does not demonstrate
profitability of the frozen configuration.
