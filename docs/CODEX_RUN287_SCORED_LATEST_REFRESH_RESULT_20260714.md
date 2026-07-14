# Run287 scored_latest refresh result - 2026-07-14

## Outcome

- Completed-session gate: `READY_COMPLETED_SESSION`
- Price and feature session: `2026-07-13`
- Current context: `989 / 989` exact closes
- Technical features refreshed: `42`
- Frozen model features: `238`
- Refreshed score rows / columns: `989 / 705`
- Research-eligible rows: `347`
- Canonical SHA-256:
  `9cbb6586f995b59446d4c65d67acca3c428ebfbf9c75d1e33ebde58efcf906a0`

The canonical research snapshot is now
`cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv`.
Fullrun, selector, target-book generation, backtest, production, and live
trading were not executed.

## Exact-close and leakage gates

- Provider maximum date: `2026-07-13`
- Provider rows after the decision session: `0`
- Ticker refresh audit: `PASS 989 / 989`
- Duplicate tickers: `0`
- Non-finite technical prices: `0`
- Non-finite scores: `0`
- Eligible research ranks: unique `1..347`
- Ineligible rows with a research rank: `0`
- Same-close execution: prohibited
- Earliest permissible execution convention: next close

## Symbol-lifecycle recovery

The first append-only attempt blocked because Yahoo returned no 2026-07-13
bar for logical ticker `IAC`. The issuer's SEC filing identifies People
Incorporated and trading symbol `PPLI`; the provider has a 2026-07-13 PPLI
close of `45.89`. The successful packet records explicit provider override
`IAC=PPLI`. It does not rewrite the historical logical ticker or carry forward
the 2026-07-10 close.

## Score-stack correction

The recovered audit context already contains old `pred_*` fields. Merging new
predictions without removing those fields makes pandas suffix both copies and
can cause the registered stack to create default-zero prediction columns. The
new lane removes stale prediction fields before the registered merge. All six
non-ranker prediction outputs are nonzero for all 989 rows.

On 738 tickers shared with the prior canonical snapshot, refreshed score
Spearman correlation is `0.9120704`. This is a current-decision refresh, not new
historical CAGR/MDD evidence.

## Diagnostic overlay only

The archived estimate snapshot was applied to the refreshed score in a separate
output. It matches 15 forward-signal rows and changes eight names in the top 30
relative to the prior 2026-07-13 overlay. Local listing-status data was absent,
so all 989 lifecycle rows were missing-neutral. The diff is therefore review
evidence only and did not update the immutable forward ledger or either target
book.

## Evidence

- Successful packet:
  `outputs/run287_scored_latest_refresh_20260714_close_20260713_v2/`
- Fail-closed first attempt:
  `outputs/run287_scored_latest_refresh_20260714_close_20260713/`
- Diagnostic overlay:
  `outputs/free_data_selection_overlay_scored_20260713_v2/`
- Session gate:
  `outputs/run287_scored_latest_session_gate_20260714/session.json`
