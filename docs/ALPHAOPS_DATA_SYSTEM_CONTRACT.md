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

- GitHub Actions run: `26990030997`
- Branch: `codex/alphaops-integrated-replay`
- Commit: `3ff15b4446eacc4cd6699701430e13cb6e340019`
- Source full rebuild replayed: `26797935603`
- Metric mode: broker ledger next-close fills with costs and cash
- Production flags:
  - `production_applied=true`
  - `sidecar_only=false`
  - `sidecar_applied_to_production=true`
  - `current_holdings_source=alphaops_vnext_policy_target_book`
  - `official_metric_mode=broker_ledger_next_close`
- Data gate:
  - `ready_for_policy_replay=true`
  - `policy_replay_blockers=[]`
  - `portfolio_system_guard.hard_error_count=0`
  - SEC-enriched candidate source:
    `outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`

Current broker metrics from that run:

- Main: CAGR `30.7638%`, MDD `-34.8303%`, Sharpe `1.1941`,
  average cash `24.3092%`
- Concentrated: CAGR `42.8243%`, MDD `-29.3356%`, Sharpe `1.2954`,
  average cash `34.6905%`

Current acceptance targets:

- Main: CAGR at or above `30%`, MDD no worse than `-25%`
- Concentrated: CAGR at or above `45%`, MDD no worse than `-25%`
- Official evidence: broker trade / broker ledger next-close only

Remaining performance gaps:

- Main CAGR passes, but MDD needs about `9.8303pp` additional improvement.
- Concentrated CAGR needs about `2.1757pp` additional improvement and MDD
  needs about `4.3356pp` additional improvement.

Current data blocker:

- Fast policy replay is valid because restored PIT SEC/Form4/13F/ETF/macro
  stores and the SEC-enriched candidate book are available.
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
  - after refresh, preserve the archive at
    `data_raw/free/sec/companyfacts.zip` so readiness audits and future agents
    share one canonical path

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
6. If full rebuild readiness is blocked only by missing companyfacts, refresh
   `data_raw/free/sec/companyfacts.zip` through the data workflow before
   spending another full rebuild run.
7. Keep large data in Drive/object storage and commit only code, docs, tests,
   and small manifests.
8. Update `CHANGELOG.md` in the same commit as any material pipeline or data
   contract change.

## Performance Work After Data Passes

Once the data gate passes, CAGR/MDD improvement should restart from broker
trade evidence, not research-only metrics:

- main target: CAGR at or above 30%, MDD no worse than -25%
- concentrated target: CAGR at or above 45%, MDD no worse than -25%
- metric source: broker ledger next-close fills with costs and cash

Priority research after data-valid replay:

- identify MDD-period trades where enriched evidence would have changed rank,
  size, hold, trim, or cash state before the loss
- compare cash re-entry timing against candidate confirmation and relative
  strength recovery
- separate data gaps from policy errors in the trade attribution report
- keep rules narrow, PIT-safe, and reversible when broker replay rejects them
