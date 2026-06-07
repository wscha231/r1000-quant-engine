# AlphaOps Data System Contract

This contract is the operating rule for AlphaOps vNext production replay,
current holdings, and future CAGR/MDD improvement work.

## Core Principle

Performance work starts only after data readiness and data utilization pass.
A broker replay can produce metrics while still being invalid for production
policy decisions if the run did not restore or use the required data lake.

Before changing selection, sizing, cash, or risk rules, every agent must verify:

- `outputs/data_readiness/summary.json`
  - `ready_for_fullrun=true` for collector/full rebuild decisions
  - `ready_for_policy_replay=true` is acceptable for fast production replay
    when PIT SEC/Form4/13F/ETF stores are already restored
  - no hard blockers for the run type being analyzed
  - `feature_source_coverage` reports monthly operating-target-book coverage
    for price/momentum, macro/regime, theme, SEC/smart-money, quality, and
    broker-policy feature groups
- `outputs/data_readiness/feature_source_coverage.csv`
  - monthly source-group coverage extracted from operating target books
  - inspect `available_from` warnings before treating a run as PIT-safe
- `outputs/reports/dataset_coverage_audit.json`
  - candidate book coverage is current and full enough for the target run
  - SEC-enriched candidate materialization is reported when evidence exists
- `outputs/sec_enriched_candidate_replay/summary.json`
  - row counts and evidence coverage are recorded
  - smart-money and 13F evidence are not only summary-only sidecars
- `outputs/alphaops_vnext/summary.json`
  - `candidate_book` points to
    `outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`
    when SEC/13F/ETF evidence exists
- `outputs/portfolio_system_guard/error_check.json`
  - `hard_error_count=0` for production-valid analysis

## Current Acceptance Baseline

Latest verified broker-ledger production replay:

- GitHub Actions run: `27086825471`
- Artifact: `7462319137`
- Artifact size: `83,533,903` bytes
- Branch: `codex/alphaops-integrated-replay`
- Commit: `7b635cb1f4a3cf984b044bf2ce2a2fdf25701779`
- Source full rebuild replayed: `27076153505`
- Metric mode: broker ledger next-close fills with costs and cash
- Production flags:
  - `production_applied=true`
  - `sidecar_only=false`
  - `sidecar_applied_to_production=true`
  - `current_holdings_source=alphaops_vnext_policy_target_book`
  - `official_metric_mode=broker_ledger_next_close`
- Data gate:
  - `portfolio_system_guard.hard_error_count=0`
  - `portfolio_system_guard.targets_pass=true`
  - replay `data_readiness_status` may still report the missing canonical SEC
    companyfacts archive inherited from the source fullrun; that is a full
    data-readiness blocker, not a policy-replay blocker.

Current broker metrics from that run:

- Main: CAGR `35.2189%`, MDD `-23.2403%`, Sharpe `1.3814`,
  average cash `31.0751%`
- Concentrated: CAGR `50.7545%`, MDD `-22.9944%`, Sharpe `1.5937`,
  average cash `43.5393%`

Current acceptance targets:

- Main: CAGR at or above `35%`, MDD no worse than `-25%`
- Concentrated: CAGR at or above `50%`, MDD no worse than `-25%`
- Official evidence: broker trade / broker ledger next-close only

Current target margins:

- Main CAGR passes by `0.2189pp`; MDD passes by `1.7597pp`.
- Concentrated CAGR passes by `0.7545pp`; MDD passes by `2.0056pp`.

Current blocker:

- No hard policy-replay blocker is active; both official broker target gates
  pass on run `27086825471`.
- The remaining active blocker is full data-readiness: replay artifacts can
  still report `data_readiness_status=blocked` when the source fullrun cannot
  prove canonical `data_raw/free/sec/companyfacts.zip` availability.
- Do not dispatch another policy replay unless code or policy behavior changes.
  The next non-policy action is to run `data_readiness_preflight.yml` with
  `sec_companyfacts=true` and verify `ready_for_fullrun=true` before spending a
  new full rebuild.
- If a later full rebuild or replay misses targets again, use run
  `27086825471` as the official broker-ledger acceptance baseline and compare
  daily broker equity/trade/cash paths before adding any new selection or cash
  rule.
- Data maintenance run `26987903823` on commit
  `0bf0fdae6583c33ebae0af10071ecc620ba028f5` refreshed
  `data_raw/free/sec/companyfacts.zip` from SEC bulk companyfacts
  (`1321.2 MB`, `19831` members), refreshed target-book price cache to
  `512` tickers, and completed with `coverage_readiness=ready_for_proxy_replay`.
- Replay artifacts that use source full run `26797935603` may still show
  `ready_for_fullrun=false` because that archived source run predates the
  companyfacts refresh. Before judging a new full rebuild, run
  `data_readiness_preflight.yml` or a new full rebuild after Drive restore and
  verify `ready_for_fullrun=true`.
- Data Readiness Preflight run `27054390871` on commit
  `0e1019683f5b5621094f6c7985f45fab4aa2baa9` restored companyfacts, price,
  macro, Form4, 13F, and ETF stores, but correctly reported
  `ready_for_policy_replay=false` for the default
  `cloud_results/full_rebuild/latest_global_alpha_universe` snapshot because
  both operating target books lacked `sec_smart_money` feature columns. Do not
  use that snapshot for policy target decisions until operating books are
  rebuilt from the SEC-enriched candidate replay or the missing evidence is
  explicitly neutralized.
- AlphaOps replay candidate resolution must prefer
  `sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv` before
  `reports/candidate_replay_book.csv`. This keeps Form4, 13F, ETF, and
  smart-money features available to `evidence_support_score` and preserved in
  operating target books for data-readiness and guard audits.

## Storage Contract

GitHub stores code, schemas, workflows, tests, docs, and small manifests.
It must not store large raw archives, PIT parquet stores, price caches, or full
replay bundles.

Google Drive or object storage is the canonical large-data lake:

- `data_raw/free/sec/`
  - SEC companyfacts/submissions archives and raw filing snapshots
- `data_raw/free/prices/`
  - raw price bars and provider reconciliation artifacts
- `data_raw/free/macro/`
  - FRED, BLS, BEA, Treasury, and other official macro snapshots
- `data_raw/free/universe_proxy/`
  - symbol maps, static/proxy universes, eligibility snapshots, and labels
- `data_pit/sec/`
  - `form4_transactions.parquet`
  - `institutional_13f_holdings.parquet`
  - `sec_ownership_signals.parquet`
  - PIT event and manager-follow datasets when present
- `data_pit/etf_holdings/`
  - `etf_holdings.parquet`
- `data_pit/macro/`
  - daily long-crisis and macro policy features
- `cache_prices/`
  - replay price cache, restored as an accelerator but not trusted alone
- `manifests/`
  - data snapshot manifests, row counts, freshness, PIT labels, and gaps

## Update Cadence

Minimum expected freshness:

- Price cache:
  - daily on trading days
  - replay can refresh missing or stale names before broker metrics
- SEC Form4:
  - daily or next available workflow run
  - every row must carry `available_from`
- 13F:
  - at least quarterly, refreshed after filings are available
  - every row must carry `available_from`
- ETF holdings:
  - weekly or when provider snapshots change
  - every row must carry `available_from` or `latest_available_from`
- Macro:
  - daily for market/crisis monitors where the source updates daily
  - release-lagged series must preserve their publication lag
- Universe:
  - current/proxy universe labels must be explicit
  - do not describe proxy-universe results as official Russell 1000 history
- SEC companyfacts bulk archive:
  - refresh when older than 3 days before a full collector rebuild
  - do not download the 1GB+ archive in every scheduled daily run
  - use the explicit `sec_companyfacts=true` workflow input when readiness
    reports `data_raw/free/sec/companyfacts.zip` missing
  - for a readiness-only recovery, dispatch `data_readiness_preflight.yml`
    with `sec_companyfacts=true`; it refreshes
    `data_raw/free/sec/companyfacts.zip`, reruns the audit, and syncs the
    archive back to Drive canonical paths without spending a full rebuild
  - after refresh, preserve the archive at
    `data_raw/free/sec/companyfacts.zip` so readiness audits and future agents
    share one canonical path

## Full-Period Data Quality Audit Plan

Run the audit before any new full rebuild, and inspect it before every policy
replay that will be used for target decisions. The audit must cover the whole
historical period, not only the latest holdings.

Required audit dimensions:

- Universe:
  - monthly eligibility snapshot exists for every rebalance month
  - ticker changes, delistings, ADR eligibility, and proxy Russell 1000 labels
    are explicit
  - current-universe-only tests are labelled research-only
- Prices:
  - adjusted OHLCV exists for every selected ticker through every broker exit
  - split/dividend adjustments are internally consistent
  - stale bars, missing next-close fills, and max fill lag are counted
  - replay price manifests must never report an end date after the audit date
  - replay price manifest `end` must come from actual cached bars, not the
    provider request end date
  - a missing replay price manifest `end` is a data blocker, because fullrun
    and policy replay freshness cannot be proven without an observed-bar date
  - SPY and QQQ are always present for regime and broker replay windows
- Macro:
  - daily market stress features are available through the latest trading date
  - release-lagged series use publication dates and are never backfilled into
    earlier rebalance dates
  - rate, credit, liquidity, volatility, breadth, and QQQ-vs-SPY damage fields
    are available for every rebalance month used by production policy
- SEC/Form4/13F:
  - every event row has `available_from` or `latest_available_from`
  - 13F availability is based on public filing accepted time, not report period
  - future evidence is zeroed before scoring and missing evidence is neutral
- ETF/theme:
  - historical ETF holdings are PIT-only; latest ETF holdings are discovery
    aids and cannot be used as historical production evidence
  - theme taxonomy changes are versioned and linked to the rebalance date that
    first used them
  - daily theme leadership tape is retained separately from production target
    books
- Broker accounting:
  - broker replay uses operating target books, integer shares, cash, costs, and
    next-close fills
  - target pass/fail is never taken from deprecated weight-level metrics

Guard outputs:

- `outputs/data_readiness/summary.json`
- `outputs/data_readiness/feature_source_coverage.csv`
- `outputs/portfolio_system_guard/data_quality_update_plan.json`
- `outputs/portfolio_system_guard/error_check.json`
- `outputs/portfolio_system_guard/system_guard_report.md`

If any required data source fails, fix the data store, restore step, or PIT
normalization first. Do not compensate for missing data by adding selection or
cash rules.

## Leadership And Macro Feature Roadmap

The system goal is not simply to hold more cash. It should find dominant themes
early, concentrate into the true leaders, and exit before leadership changes.
New features must be added as PIT data first, then evaluated through broker
trade attribution.

Priority feature families:

- Theme leadership:
  - theme-level relative strength versus SPY, QQQ, sector ETF, and equal-weight
    peer basket
  - theme breadth: percent of members above 20/50/200-day moving averages,
    new highs, and volume-thrust participation
  - leader concentration: top 1/3/5 names share of theme return and volume
  - theme phase: emerging, confirmed, climax, fading, failed recovery
- Leadership change / exit:
  - QQQ-vs-SPY damage while nominal indexes are still positive
  - leader underperformance versus its theme and benchmark over 1/2/4 weeks
  - failed breakout / failed recovery after high-weight entry
  - volume exhaustion and volatility expansion after a climax run
- Macro regime:
  - 2-year, 10-year, real-yield and yield-curve pressure
  - credit spread and high-yield stress
  - VIX/VVIX and realized-volatility regime
  - dollar, oil, copper/gold, liquidity, inflation surprise, and Fed policy
    pressure
  - sector/theme sensitivity to rate, inflation, energy, and liquidity shocks
- Data governance:
  - every new feature column declares source, update cadence, publication lag,
    PIT availability column, and fallback behavior when missing
  - every feature experiment reports whether the signal helped in broker
    trades, not only row-level or weight-level proxies

## Replay Gate

`alphaops_replay_sidecars_manual.yml` must restore the evidence lake from
Google Drive before running vNext production replay. The restore step must
include `data_pit/sec`, `data_pit/etf_holdings`, `data_pit/macro`, and the
SEC/ETF output sidecars, then write
`outputs/full_rebuild_logs/sec_evidence_restore_manifest.json`.

If Drive restore is unavailable, the run may still upload research artifacts,
but the production guard must block promotion when evidence exists only as
summaries and vNext did not use the enriched candidate book.

Required production checks:

- `data_readiness_ready_for_production_replay`
- `sec_enriched_candidate_materialized_for_audit`
- `alphaops_vnext_uses_sec_enriched_candidate_book`
- broker replay target-book checks for both main and concentrated portfolios

## PIT Rule

All evidence fields ending in `_available_from`, plus `available_from`,
`latest_available_from`, and `evidence_available_from`, are point-in-time
availability fields. vNext must normalize timezone-aware and timezone-naive
values before comparison and zero future evidence before scoring.

Missing evidence is neutral:

- no positive boost
- no penalty
- never a standalone buy rule

Top7, 13F, Form4, ETF, and smart-money fields are positive support only after
the PIT check passes.

## Current Holdings Rule

Current holdings must display broker-rule metrics and data-validity state
together:

- `metric_mode=broker_ledger_next_close`
- `current_holdings_source=alphaops_vnext_policy_target_book`
- `production_applied=true`
- `sidecar_only=false`
- `sidecar_applied_to_production=true`
- latest data readiness and portfolio guard state

Do not present deprecated weight-level metrics as production ship evidence.

## Agent Workflow

When resuming AlphaOps work, agents must follow this order:

1. Check the latest run SHA against the branch head SHA.
2. Inspect `data_readiness`, `dataset_coverage_audit`,
   `sec_enriched_candidate_replay`, `alphaops_vnext`, and
   `portfolio_system_guard` artifacts before interpreting CAGR/MDD.
3. If data readiness or enriched-candidate usage fails, fix data restore,
   data materialization, PIT enforcement, or guard wiring first.
4. Only after `hard_error_count=0`, analyze broker replay trades, cash, MDD,
   current holdings, and target-book changes.
5. Prefer fast replay for policy-only changes. Use full rebuild only when
   collectors, feature generation, universe construction, or schemas change.
6. If full rebuild readiness is blocked only by missing companyfacts, dispatch
   `data_readiness_preflight.yml` with `sec_companyfacts=true` or run the free
   data workflow with the same input before spending another full rebuild run.
7. Keep large data in Drive/object storage and commit only code, docs, tests,
   and small manifests.
8. Update `CHANGELOG.md` in the same commit as any material pipeline or data
   contract change.

## Performance Work After Data Passes

Once the data gate passes, CAGR/MDD improvement should restart from broker
trade evidence, not research-only metrics:

- main target: CAGR at or above 35%, MDD no worse than -25%
- concentrated target: CAGR at or above 50%, MDD no worse than -25%
- metric source: broker ledger next-close fills with costs and cash

Priority research after data-valid replay:

- identify MDD-period trades where enriched evidence would have changed rank,
  size, hold, trim, or cash state before the loss
- compare cash re-entry timing against candidate confirmation and relative
  strength recovery
- separate data gaps from policy errors in the trade attribution report
- keep rules narrow, PIT-safe, and reversible when broker replay rejects them
