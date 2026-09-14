# Fixed forward experiment, version 1

The purpose is to test a rules-based DCA strategy against contemporaneously
observed costs and final Polymarket outcomes. This is paper research. It does
not approve a calibration or arm live trading.

## Frozen protocol

`robustness_protocol.json`, decision/capture source files and installed direct
dependency versions are hashed and recorded before collection. Reusing the
database with a different protocol/code/dependencies is rejected.
New data, not the reused April–September history, forms the validation set.

- Binance BTCUSDT closed candles; DCA signal frozen at the 15-minute boundary.
- The existing shared `signal.snapshot` implementation, router and auxiliary
  enabled, 08–22 UTC, boundary policy, 240 five-minute bars and 28 daily bars.
- Entry evaluation at 11:30, allowing at most two seconds for the initial
  REST request to finish. No retrospective entry if this window is missed.
- Ask >=0.85, spread <=0.03, cap=min(initial ask+0.01,0.97), rounded down to tick.
- Each independent scenario has a $30 all-in cash-equivalent shadow budget.
- Primary scenario: DCA, 500 ms added wait, 100% displayed ask depth.
- Diagnostic scenarios: 250 and 1000 ms added wait, and 50% remaining depth.
- Market-favourite baseline at the same time and filters. The paired comparison
  is restricted to windows with a frozen DCA direction and confirmed labels.
- 28-day observation period; day 7 is a data-quality checkpoint, not early approval.

This is a new fixed rules strategy experiment, not exact parity with the old
latest_5m paper experiment or the live continuous-window calibrated strategy.
There is no justified probability available for an edge filter yet. A successful
rules experiment must not be presented as validation of a different live policy.

## Recorded evidence

Closed candles, signal source/direction, raw Gamma rules and fee metadata,
both REST books at decision and delayed observations, request/receive timestamps,
measured RTT, fixed order cap and source timestamp are persisted. The collector
stores compressed raw market WSS events around the entry window, with local
receipt timestamps and explicit reconnect gaps. Chainlink is recorded for audit;
it is not substituted for the Binance signal or used to invent a price-to-beat.

REST observation time is target delay PLUS request RTT. The simulator does not
claim an exact 250/500/1000 ms exchange fill, and WSS packets are archived rather
than claimed to be a fully validated exchange-orderbook replay. FOK cost simulation
uses the later observed asks under the original cap. Book age must be <=1500 ms;
unsupported fees, missing depth and unavailable data cause skips, never fills.

Each market/scenario is recorded once. Gamma resolution and CLOB winner must agree.
Pending positions never contribute to settled PnL. Captured observations replay
through the same pure cost function; mismatches are reported.

## Reporting and limitations

The report, refreshed every five minutes, contains independent policy results,
market counts, actual delays, skip reasons, paired DCA-minus-favourite PnL,
three-day-block bootstrap intervals with a fixed seed, and a $50 fixed-$30
portfolio replay. Known payouts are credited only at the first observed confirmed
label; immediate redemption at that point is an explicit simplifying assumption.
Pending positions are kept at cost, not marked to market. No hidden bankroll top-up.

The final 28-day review must consider coverage, missed entries, source groups,
net PnL, block confidence intervals, depth/latency sensitivity, paired baseline,
drawdown and capital lockup. The software never labels a strategy approved.
Twenty-eight days can still be insufficient; particularly few independent days
or zero observed losses make bootstrap confidence intervals unreliable. Repeated
dashboard checks are not sequential significance tests. Do not pool scenarios.

Historical sensitivity can be rerun with `audit_robust_history.py`; its output is
explicitly exploratory because those prices and parameter choices were already
examined. No historical fill-price or latency accuracy is manufactured.

The rerun on the cached history found, for the same 194 early-period markets at
12:30/ref>=0.85, $5-budget PnL changing from +$14.80 with +1 cent padding to
-$4.62 with +3 cents. The 3-day-block 95% interval for mean PnL already crossed
zero at +1 cent. At 11:30 no retained historical quote in either period had an
age <=1500 ms. These are sensitivity diagnostics, not validation of the new
Binance/ask-based protocol. In particular, same-sample filtering can remove the
only loss from a small historical subset; an all-winning subset is not proof of
zero loss risk, and bootstrap cannot synthesize an unseen tail loss.

Remaining work after collection: regime-stratified analysis, independent final
validation of any subsequently changed configuration, and actual execution
reconciliation. Archived WSS alone does not resolve exchange queue priority or
prove our own hypothetical order would have filled.

## Operations

The `polybot-robust-paper` container uses `Dockerfile.robustness`, no live SDK,
no secrets and no automatic restart. It stops after 28 days or if free disk
space falls below 2 GiB. `polybot-robust-data` persists the database, raw stream
archives and report. The older paper dataset remains in its original volume.

Read-only report:

```bash
sudo docker exec polybot-robust-paper python -B report_robust_paper.py \
  --capture /app/robust_forward/capture.sqlite3
```

The existing HTTPS dashboard displays the new experiment using its same login.
To stop collection without deleting evidence:

```bash
sudo docker stop -t 30 polybot-robust-paper
```
