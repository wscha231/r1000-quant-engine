# Run287 Chameleon macro-input FREE_PROXY shadow result

## Outcome

The provenance-complete input normalizer was implemented as the second
Chameleon causal family. It acquires or reads official FRED graph and Cboe
history, explicit local daily-bar caches, and an explicit universe file. It
then writes a hashed XNYS calendar, source audit, source lineage, normalized
metric ledger, normalized context ledger, and an optional invocation of the
already-merged report-only risk engine.

The normalizer has no selector, target-book, TradeIntent, order, ledger,
backtest, fullrun, production, live-trading, or promotion surface.

All historical observations in this result are `FREE_PROXY`:

- FRED graph CSV is current vintage rather than ALFRED vintage history;
- historical Cboe and local daily closes do not carry archived publication
  timestamps; and
- local universe files do not prove historical constituent membership.

Consequently these artifacts are not admissible evidence for historical A/B,
champion replacement, or trading activation.

## Frozen data contract

`docs/run287_chameleon_macro_inputs_contract.json` freezes:

- a six-calendar-year XNYS window and decision time 15 minutes after close;
- the exact FRED and Cboe source registry;
- conservative FRED availability policies;
- a minimum 500 simultaneous symbols for breadth/correlation evidence;
- a maximum 1,200 explicit universe symbols;
- `FREE_PROXY` historical truth and no missing-value carry or imputation;
- explicit unsupported options/leadership/portfolio-fragility fields; and
- the complete report-only safety envelope.

Every consumed local input is hashed before and after reading. A changed file
blocks the top-level manifest. Network responses are copied into the isolated
output and hashed. Missing sources omit components rather than substituting an
index, VIX, or current snapshot.

## Real-data shadows

### 2026-07-02 requested date

Artifact:
`outputs/run287_chameleon_macro_input_shadow_20260702_20260829_v5`

- source-ready count: 19 / 23;
- normalized metrics: 45,733 rows and 34 components;
- context: 1,507 XNYS sessions;
- universe files loaded: 955;
- 200-session-valid breadth symbols at as-of: 297;
- result: `READY_CHAMELEON_MACRO_RISK_REPORT_ONLY_DATA_INSUFFICIENT`;
- reason: fewer than 500 universe symbols had the component-required valid
  history after 2026-06-22, so market breadth and correlation were
  intentionally unavailable on 2026-07-02;
- no new buys were authorized by the engine (`new_buys_frozen=true`), and no
  portfolio action surface existed.

This run exposed a real data-update bottleneck: the benchmark SPY cache reached
2026-07-02, while the broad cross-section's last 500-symbol-ready session was
2026-06-22.

### 2026-06-22 common-coverage date

Artifact:
`outputs/run287_chameleon_macro_input_shadow_20260622_20260829_v4`

- source-ready count: 19 / 23;
- normalized metrics: 45,744 rows and 34 components;
- context: 1,507 XNYS sessions;
- universe files loaded: 955;
- 200-session-valid breadth symbols at as-of: 634;
- ready axes: 8 / 10;
- required market-breadth, volatility, and credit axes: all ready;
- FREE_PROXY risk score: 40.3369172694;
- red axes: 0;
- observed/effective state: `NORMAL` / `NORMAL`;
- sentiment overlay: `NONE`, with greed readiness false because options data
  was deliberately absent;
- result: `READY_CHAMELEON_MACRO_RISK_REPORT_ONLY`.

The two unavailable axes were options sentiment and cross-asset. HYG, LQD,
TLT, and UUP were absent from the local cache. Equity/index put-call history
was not substituted from a third-party snapshot.

## Current bottlenecks and next gates

1. Refresh the explicit universe and all price caches to a common XNYS
   decision date before any state/rotation A/B. Updating SPY alone is
   insufficient.
2. Start append-only forward collection for Cboe, macro releases, options, and
   universe coverage with actual collection timestamps. FRED graph history
   remains current-vintage `FREE_PROXY`; ALFRED vintages require a separately
   proven keyed collector.
3. Add official/archived equity and index put-call inputs. Until then extreme
   greed cannot become ready.
4. Add TLT/UUP/HYG/LQD or another preregistered, licensed cross-asset bundle.
   Missing cross-asset data must not be synthesized.
5. Run 63 forward sessions of report-only shadow before enabling a separate
   market-state/rotation-sleeve A/B. No historical CAGR/MDD claim can be made
   from these current-vintage/free-close inputs.

No workflow dispatch, accepted-head migration, chronological catch-up,
portfolio A/B, selector, backtest, target/order/ledger write, or automatic
promotion was executed.
