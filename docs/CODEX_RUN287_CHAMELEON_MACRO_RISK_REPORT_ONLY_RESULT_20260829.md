# Run287 Chameleon 10-axis macro-risk report-only implementation

## Scope

This change implements the first causal family from Chameleon Engine v2:
decision-time point-in-time market-risk observation. It does not implement a
cash target, hedge, portfolio sleeve transition, holding exit, smart-money
candidate, target book, order, or durable-ledger mutation.

The implementation is intentionally separate from the rejected fixed VIX,
monthly drawdown/cash-floor, broad gross-floor, and canonical crisis/re-entry
policy families. A state classification is evidence for a later A/B; it is not
portfolio authority.

## Frozen contract

`docs/run287_chameleon_macro_risk_contract.json` freezes:

- ten axes and weights summing exactly to 1.0;
- registered component names and their risk direction;
- a trailing five-year / maximum 1,260-session empirical midrank percentile;
- 252 minimum observations per component;
- red-axis threshold at PIT risk percentile 80;
- readiness at 8/10 axes with breadth, volatility, and credit all ready;
- weight normalization across available axes only after that readiness gate;
- NORMAL / RISK_ALERT / RISK_DEFENSE / EXTREME_FEAR thresholds;
- two-session entry and five-session release confirmation;
- portfolio fragility as a separate one-level defense-confidence annotation;
- five-condition extreme-greed confirmation and three-stage fear recovery;
- a complete false safety envelope for selector, target, TradeIntent, order,
  ledger, fullrun, production, live trading, and automatic promotion.

The red threshold was not explicit in the v2 prose. It is fixed at 80 before
any real outcome test and may not be tuned from a favored crisis episode.

## Input contracts

The metric ledger is long-form, one row per decision date and component. A
separate hashed XNYS calendar artifact supplies the canonical
`decision_date` / `decision_time_utc` / `nyse_session_ordinal` mapping. Metric
dates must equal the complete calendar slice between their first and last
decision; renumbering after an omitted session cannot pass. Every metric row
requires:

- `decision_date` and one common `decision_time_utc` for that date;
- a contiguous NYSE session ordinal and immutable calendar-source hash, so
  confirmation cannot silently count weekdays or skip a trading session;
- registered `axis`, `component`, and `risk_direction`;
- finite `raw_value`;
- `source_observation_date` and exact `available_from`;
- `source_kind`, immutable `source_sha256`, and
  `FREE_PROXY/FORWARD_PIT/PIT_VERIFIED` truth class.

The optional daily context table carries SPY recovery levels, breadth and HY
confirmation, market-new-low and breadth-narrowing flags, and the portfolio
fundamental-weakness ratio. Context availability must not exceed the decision
time and must match both the metric decision timestamp and hashed calendar
mapping. Context rows require the same observation date, source kind, source
hash, and truth class as metric rows; current-vintage context cannot claim
`PIT_VERIFIED`.

The engine performs no network collection. FRED/ALFRED, Cboe, breadth, credit,
options, and cross-asset source normalization is a separate data-producer
change. Current-vintage values must not be relabeled as historical
`PIT_VERIFIED` evidence.

## Outputs

`tools/build_run287_chameleon_macro_risk.py` emits an append-only run directory
containing:

- `component_percentiles.csv`;
- `macro_risk_axes.csv` and `macro_risk_snapshot.json`;
- `market_state_history.csv` and `market_state.json`;
- `sentiment_overlay_history.csv` and `sentiment_overlay.json`;
- `backtest_truth_manifest.json`, `manifest.json`, and `report.md`.

When fewer than eight axes or any required axis is unavailable, the engine
does not carry a risk score forward. It retains only the previously confirmed
effective state, marks state change disallowed, and sets `new_buys_frozen`.
Any future `available_from`, future observation date, unregistered component,
direction mismatch, invalid source hash, or duplicate decision component is a
hard blocked artifact.

`market_state.json` contains `target_weights=null` and
`policy_handoff_implemented=false`. No TradeIntent output exists.

## Validation

`tests/run287_chameleon_macro_risk_smoke.py` covers:

- exact weights, axes, readiness, and nonexecution envelope;
- trailing-only percentiles unchanged by a future outlier;
- a single VIX axis unable to create defense or extreme fear;
- 8/10 plus mandatory-axis readiness and missing-data buy freeze;
- two-session entry and five-session release hysteresis;
- five-session greed entry/release and ordered fear-recovery stages;
- deterministic semantic outputs, source immutability, null target weights,
  and future-availability hard failure.

## Exact-head review follow-up

The first exact-head Codex review found nine valid fail-closed gaps. The final
implementation now:

- binds every decision row to the bytes and exact mapping of a supplied XNYS
  calendar artifact;
- rejects decision timestamps that belong to another New York session date;
- applies metric-equivalent observation/source/truth rules to context rows;
- confirms elevated and released severity boundaries across alternating
  observed labels instead of resetting on every label change;
- requires five consecutive below-three-condition sessions to release greed;
- blocks invalid explicit `--as-of` values;
- accepts only the canonical contract path and frozen semantic hash;
- serializes every missing/non-finite pandas or NumPy scalar as strict JSON
  `null`; and
- preserves date-only `decision_date` in the sentiment snapshot.

## Remaining gates

No historical or current real-data state has been produced by this change. No
backtest, fullrun, workflow dispatch, accepted-head migration, chronological
catch-up, target/order/ledger write, champion replacement, production, or live
trading action was executed.

The next causal change is a provenance-complete source normalizer and
report-only real-data shadow. Only after that evidence is stable should a
separate market-state/rotation-sleeve A/B be implemented. Holding policy,
fear/greed cash behavior, 13F/Form 4 candidate discovery, and hedge sidecar
remain separate later causal families.
