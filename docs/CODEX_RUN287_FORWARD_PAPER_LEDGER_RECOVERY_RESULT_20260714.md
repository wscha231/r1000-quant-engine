# Run287 Forward Paper Ledger Recovery Result

## Outcome

The forward paper lane is restored as an append-only, paper-only evidence
archive. It is now wired into the existing bounded 993-name estimate archive
after the latest completed NYSE close. It does not change either target book,
cash, orders, CAGR/MDD, production, or live trading.

The implementation recovers the previously lost v2 source exactly from commit
`2f3c9750` and adds only the bounded price-universe helper and durable daily
workflow integration needed to keep collecting evidence.

## Preserved local state

The existing untracked ledger was not deleted or rewritten.

- Schema: `free-data-forward-paper-ledger-v2`
- Decision dates: `1`
- Observations: `30`
- Unique tickers: `30`
- Distinct true-forward tickers: `10`
- Resolved 63D outcomes: `0`
- Review state: `UNDERPOWERED`
- Event log SHA-256:
  `80210b87ffbe70cb78a05969b61f7df67d8721c35a61b4785e4852ebed3516d6`

Those first 30 observations came from the earlier candidate-only capture. The
current v2 replay correctly refuses to infer the missing contemporaneous base
rank, reports `contemporaneous_base_selection_rank_required`, and still permits
elapsed outcomes for already frozen observations to be resolved. New decision
dates must use the full v2 ranked universe and exact 30/30/30 cohorts.

## Daily sequence

The scheduled estimate workflow now performs the following bounded sequence:

1. Restore the estimate archive, prior paper ledger, prior overlay, and the
   dedicated forward-paper price cache from durable cache/Google Drive.
2. Resolve the latest completed NYSE session and proceed only 90 minutes after
   close and no more than 36 hours after that close.
3. Build a current research-only overlay from the canonical scored universe and
   the just-collected forward estimate snapshot. Missing evidence stays neutral.
4. Require exact `base top-30`, `overlay top-30`, and `overlay ranks 31-60`
   matched-control cohorts.
5. Refresh prices only for the cohort union, unresolved prior observations, and
   SPY. The cache starts at `2026-07-01`; it is not a signal backfill.
6. Append immutable observations and resolve only outcomes whose 21D, 63D, or
   126D close has actually elapsed.
7. Persist both mutable current state and immutable per-run evidence to Google
   Drive and GitHub artifacts.

The daily checkout is also bounded to the canonical latest baseline, queue
shards, static data, and tools. It excludes dated full-rebuild archives. This
uses the same reversible sparse-checkout approach already validated in PR CI.

## Important freshness caveat

The tracked canonical `scored_latest.csv` currently has one `feature_date`,
`2026-06-24` (741 rows; Git blob 5,275,586 bytes). A new forward observation may
combine this disclosed, already-available base score with a newly observed
estimate snapshot, but it must not be described as a full-universe score
recalculated on the decision date. This is a base-score freshness bottleneck,
not permission to run a full rebuild.

The first successful scheduled run after merge must be inspected for its exact
source hashes, cohort counts, decision/source times, and price manifest before
the archive is treated as continuously operational.

## Validation

- Restored v2 core compared with `2f3c9750`: exact match.
- Selection overlay smoke: `5/5 PASS`.
- Forward paper ledger smoke: `17/17 PASS`.
- Bounded price-universe smoke: `PASS`.
- Free historical data/backfill smoke: `11/11 PASS`.
- Earnings workflow rotation/forward archive smoke: `PASS`.
- Workflow artifact smoke and all workflow YAML parsing: `PASS`.
- Python compilation and `git diff --check`: `PASS`.

## Promotion gates

The lane remains `UNDERPOWERED`. Review requires at least 50 distinct
true-forward tickers, 200 resolved unique 63D outcomes, 12 decision-week blocks
at 21D, and 8 at 63D, followed by the frozen return, bootstrap, drawdown, and
126D direction checks. Until then:

- no historical backtest acceptance;
- no portfolio A/B;
- no target-book or cash mutation;
- no fullrun;
- no production or live trading.

PIT Russell membership and delisting-return bias also remain unresolved, so a
future paper pass cannot by itself make the system production-ready.

## First end-to-end run

The merged workflow was dispatched once on `master` as GitHub Actions run
[`29303018492`](https://github.com/wscha231/r1000-quant-engine/actions/runs/29303018492)
at commit `29060b0c3731cd74b11818e17ec8af378ac2625b`. It completed successfully in
7 minutes 3 seconds.

- Checkout: 18 seconds.
- Completed-session gate: `2026-07-13` close at `2026-07-13T20:00:00Z`.
- Source observation: `2026-07-14T03:16:59Z`, after that close; therefore the
  new cohort's first eligible reference is the next NYSE close, not 7/13.
- Full ranked rows: 741.
- Exact new cohort: base top-30 `30`, overlay top-30 `30`, ranks 31-60 control
  `30`; 60 unique cohort tickers and no capture blocker.
- New signal observations: 60.
- Existing observations receiving their first next-close reference: 30.
- Total ledger observations: 90 across two decision dates and 60 unique
  tickers.
- Distinct true-forward tickers: 11; resolved 63D outcomes: 0; status remains
  `UNDERPOWERED`.
- Bounded price cache: 61 tickers, 61 written, zero failures, actual bars from
  `2026-07-01` through `2026-07-13`.
- New ledger event-log SHA-256:
  `e36035a1cb64a3d8c001da6b7a958af1b8bfcda415676b722acab99876c189b9`.
- New current-status SHA-256:
  `f9e15d31acb52a6c241dff9c01ed4e6f92bc27f2d84a9b8300fc178ee7c00ef6`.

The deliberately small manual collection attempted 16 watchlist tickers and
found true estimate rows for 10 (`62.5%`). The collector reported
`blocked_partial_coverage` with vendor-blocked errors, but the contract kept
missing names neutral and the cumulative archive supplied 13 matched forward
rows for the overlay. This run validates the forward-ledger integration, not
the scheduled 993-name queue's completeness.

GitHub artifact upload and Google Drive current/per-run persistence completed.
Post-run `rclone check --one-way` found zero differences for all eight ledger
files and all four overlay files; the dedicated Drive price cache contains 62
objects including its manifest.
