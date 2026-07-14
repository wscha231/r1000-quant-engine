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
