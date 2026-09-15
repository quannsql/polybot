# Variant B — frozen deployment specification

User requested B, not the automatically ranked alternative A. B keeps the existing
`q1.5_z1.25_memory_old_signal_aux_shock` gate and additionally requires Z >= 0.75
when completed 15m Bollinger midpoint slope does not agree with the chosen side.
Slope = current completed BB20 midpoint minus its value four 15m bars earlier.
Invalid/missing slope does not count as agreement. The original direction is not changed.
Z uses completed minutes through T+12; the band availability grid is T+10.

Deployment profile: `q1.5_z1.25_memory_old_signal_aux_shock_slope15_z0.75`.
BTC fixed 15m contract, entry T+750..755s, reference >=0.85, reference age <=75s,
price padding 0.01 rounded DOWN to market tick, $20 maximum all-in per order,
$50 configured bankroll, one persistent live submission maximum. Existing
wallet/state/attempt lock are preserved. Restart does not authorize another order.

## Verification

`python -B audit_variant_b.py` rebuilds production features from BTC/ETH raw
minute archives (Bot1 directory read-only), compares all 410 candidate decisions
and individual inputs against the archived research, and asserts 281 wins / 281
kept. Reference+1c modeled PnL = $218.9020978767, versus $191.4714468574 for
the previous 297/300 gate. B excludes 3 losses and 16 winners, and sacrifices
$7.45 in the later period. This is retrospective, reused-data selection, NOT
independent validation or measured order-book fill performance.

Full suite: 136 tests passed (disable unrelated globally installed pytest plugin
autoload if needed with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`). Tests cover conditional
B boundaries, missing inputs, original gate precedence, completed candle causality,
exact approval profile matching and unchanged deployment risk limits.

Audit details: `logs/remaining_losses_1230/production_b_audit.json` (local ignored
artifact; source hashes included). Research: `REMAINING_LOSSES_1230_RESULT.md`.

## Price-cap investigation, before B deployment (15 Sep 2026 UTC)

Live journal since 14 Sep 16:47 UTC: 29 distinct examined markets, 4 DCA setups,
2 strong-gate passes, 1 reference below 0.85, 1 eligible frozen reference.
That eligible setup had reference 0.955, reference age 19s, tick-rounded cap
0.96 and actual ask 0.99. Four repeated quotes in the entry window all exceeded
the cap: ONE skipped setup, not four orders. No submission existed at inspection.

The independent paper collector still uses **11:30, $30, no B/strong gate**:
64 assessed markets, 4 reference-eligible setups. At +500ms all 4 asks exceeded
their respective caps; at +1000ms 3 of 4 still did. The fourth's ask dropped
from 0.93 to 0.91 under its 0.92 cap, allowing a shadow fill. Depth100/depth50
and 250/500/1000ms are parallel scenarios, NOT separate market setups. These
tiny samples are evidence of a real execution constraint, not a stable rate
for B at 12:30. The collectors overlap one market; do not pool their counts.

Historical backtest has reference quotes and assumed +1c fills, not historical
ask/depth at execution: its rejection rate is UNKNOWN, not zero. More volume
does not force sellers to quote under this strategy's limit. Widening the cap
would change execution economics and requires a separate comparison.

Example before fees, assuming the entire $20 fills at one price: a winning
0.96 purchase earns $0.8333, a winning 0.99 purchase earns $0.2020; either can
lose the $20. Fees reduce the winning proceeds further. The reference is not
a calibrated win probability. The live cap remains unchanged for this release.

Venue explanation: https://docs.polymarket.com/concepts/prices-orderbook
