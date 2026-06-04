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
6. Keep large data in Drive/object storage and commit only code, docs, tests,
   and small manifests.
7. Update `CHANGELOG.md` in the same commit as any material pipeline or data
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
