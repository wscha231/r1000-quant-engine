# Earnings / Consensus H1 + Historical Layer-B — 2026-09-18

Status: **RESEARCH_ONLY**. No selector, target-book, paper-ledger, broker, workflow, or production mutation.

## Queue clarification

The 2026-09-17 canonical queue contains 993 rows: 992 vendor-eligible equities plus one non-equity placeholder.

- fresh successful snapshots reused: 48
- stale successful snapshots due for refresh: 12
- uncovered/no-success-yet retry waiting: 932
- placeholder: 1
- selected for that collector run: 62 = 50 rotating uncovered + 12 stale refresh

Therefore `12` is **not** “12 selected out of 62.” There are 60 prior successful forward-snapshot names in the queue state (48 fresh + 12 stale), while 932 names still have no successful forward snapshot.

At the current default retry budget of 50 uncovered names per run, a complete pass across 932 uncovered names requires at least 19 runs before failures, cooldowns, and provider limits are considered.

## Confirmed H1 semantic defects in the existing collector

1. Recommendation bull/bear balance is written to `est_eps_revision_breadth`; it is not analyst EPS estimate-revision breadth.
2. Missing EPS/revenue/dispersion values may be zero-filled, making missing indistinguishable from an explicit economic zero.
3. FY1/FY2 comparison does not make fiscal-period identity first-class, so fiscal-year roll can masquerade as a revision.
4. Snapshot availability is date-level fetch time; provider publication / first-seen / observation / collection timestamps are not separated.
5. Current forward consensus is forward-only and must never be backfilled into historical decision dates.
6. Earnings surprise should reference the last eligible same-period consensus before announcement availability.
7. Recommendation, target-price and estimate reactions to one earnings event require a causal-event identity to avoid double/triple counting.
8. `uncovered_retry_waiting` does not distinguish never-attempted, transient failure, provider no-coverage, entitlement-blocked and quarantined names.

## H1 contract added in this branch

`tools/earnings_consensus_h1.py` provides a safe semantic layer:

- missing numeric -> `None`; explicit vendor zero remains `0.0`
- `recommendation_balance` is separated from revision breadth
- true `est_eps_revision_breadth` remains unavailable unless analyst-level estimate-change evidence exists
- EPS/revenue period end is retained explicitly
- revisions require the same fiscal period
- `observed_at`, `first_seen_at`, `provider_published_at`, `available_at`, `collected_at` are separated
- frozen pre-event consensus excludes future snapshots
- causal event ID is stable
- queue states distinguish never-attempted / transient / no-coverage / entitlement / quarantine / fresh / stale

This branch does **not** yet replace `tools/collect_earnings_estimates_finnhub.py`; integration is intentionally a separate causal change after the contract tests pass.

## Historical Layer-B boundary

Historical consensus is split into two tiers:

- **B1**: values reconstructable at an old decision date from the archived candidate book: contemporaneous TTM revenue/net income/OCF/CAPEX, market cap, growth, margin, ATR and liquidity fields.
- **B2**: forward consensus/revisions only from dates where a real archived forward snapshot existed. Current forward estimates are never copied backward.

The recovered source has 47,435 rows, 981 tickers and 85 decision dates from 2019-05-31 to 2026-05-29. Source audit says no feature/price row was after its decision day, but intraday PIT provenance is not certified; B1 is therefore labeled `PIT_PROXY_RESEARCH_ONLY`.

B1 fixed research contract (not tuned to results):

- candidate leadership: 1m/3m/6m/12m = 20% / 30% / 30% / 20%
- candidate threshold: top 20% leadership with industry-strength confirmation
- expected-return proxy inside candidates: growth 35%, quality 25%, sector-relative valuation yields 25%, risk/liquidity 15%
- Main: 15 stocks, 20% hold buffer
- Concentrated: 8 stocks, 20% hold buffer
- transaction cost: 25 bps per traded stock notional
- regime aggregate exposure only: strong_bull/bull 100%, neutral 90%, bear 65%, deep_bear 40%

Future `r_1m`, `y_blend`, and `period_forward_return` are explicitly excluded from feature construction. A regression test flips all future outcomes and requires identical features/selections.

## B1 replay result

These are monthly/checkpoint drawdowns, **not daily-certified MDD**.

### Main

- full period CAGR: **22.75%**
- checkpoint MDD: **-23.75%**
- annualized monthly Sharpe: **1.262**
- 2019-2021 CAGR: **29.76%**
- 2022-2023 CAGR: **5.55%**
- 2024-2026 CAGR: **30.83%**

### Concentrated

- full period CAGR: **21.85%**
- checkpoint MDD: **-22.82%**
- annualized monthly Sharpe: **1.126**
- 2019-2021 CAGR: **34.90%**
- 2022-2023 CAGR: **0.70%**
- 2024-2026 CAGR: **27.52%**

## Interpretation

B1 fails the project CAGR objective and must **not** be promoted. The weak 2022-2023 result is not unique to B1: the fixed Leadership Core and the momentum comparator were also materially weaker in that regime. This supports the original architecture that Recovery / Reversal-Panic must be modeled separately from established leadership; it does not justify tuning B1 weights to force the 35% objective.

The next research steps are:

1. integrate the H1 semantic contract into the collector in a separate PR;
2. make queue retry class/cooldown explicit before increasing API volume;
3. build B2 only from real archived forward snapshots from their actual first-available dates;
4. add a separately preregistered Recovery lane and validate it in temporal/shadow OOS;
5. expand daily price coverage before claiming daily MDD.
