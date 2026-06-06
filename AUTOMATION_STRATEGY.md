# Automation Strategy

This repo keeps scheduled GitHub Actions small in count and explicit in
responsibility. When the trading system changes, update this file, the
workflow that owns the cadence, and the smoke-test topology guard in the same
commit.

## Cadence Matrix

| Cadence | Workflow | Owns | Production impact |
| --- | --- | --- | --- |
| PR / push CI | `pr_validation.yml` | Tier-1 code-level smoke + leakage audit + topology guard via `tools/run_pr_validation.py` | No data, no model impact |
| Manual long-run | `full_rebuild_manual.yml` | full data rebuild, backtests, verdicts, GDrive sync, auto-learning diagnostics | Generates production artifacts; no blind baseline rotation |
| Daily after close | `after_close_daily.yml` | scanner, macro pulse, ETF leadership, explosive alerts, tactical review, paper dry-run, Layer 4 suggestions | Dry-run/report-only unless manual `execute=true` |
| Weekly | `weekly_data_refresh.yml` | Finnhub substrate refresh, theme discovery, PIT data freshness review, and universe/coverage gap reporting | Data refresh only |
| Monthly | `monthly_research.yml` | cycle-play universe refresh, ADR/macro IC, tactical sleeve backtest, explosive pattern model retrain | Research/model artifacts only |
| Quarterly | `quarterly_auto_learning.yml` | trade insights, feature-gate proposals, promotion dry-run or gated manual promotion | Scheduled runs diagnostic; manual promotion only after gates pass |
| Monthly legacy bridge | `unified_monthly.yml` | `scored_unified.csv` bridge for legacy advisors/tools | Data bridge only |
| Monthly proposal | `layer4_monthly_swap.yml` | Layer 4 swap proposal and optional manual paper execution | Scheduled runs dry-run; live requires manual input |
| Manual smoke | `gdrive_smoke_test.yml` | Google Drive credential verification | No model impact |

## Rules For Future System Changes

1. Any new sleeve, feature family, data source, or promotion path must declare
   which workflow cadence owns it.
2. Daily scheduled jobs must run after the US close. Use `22:xx UTC` unless a
   script has its own market-calendar guard.
3. Expensive end-to-end rebuilds stay manual. Scheduled jobs can refresh data
   and diagnostics, but should not burn the full rebuild budget automatically.
4. A workflow may auto-generate proposals. It must not auto-change production
   weights, feature gates, or live execution unless the code has explicit
   promotion thresholds and a test that verifies those thresholds.
5. If a workflow is split or added, update `tests/smoke_test.py` so stale,
   duplicate schedules do not silently return.
6. Keep `full_rebuild_manual.yml` as the source of truth for artifact export:
   `outputs/reports/`, `outputs/trade_journal/`, and `outputs/auto_learning/`
   must reach artifacts, GDrive, and `cloud_results/`.
7. Data-quality failures are fixed before policy tuning. A run that misses PIT
   SEC/Form4/13F/ETF/macro restore, enriched candidate usage, operating target
   books, or official broker metrics is not valid evidence for CAGR/MDD
   promotion.

## Code-Level Validation Tiers

Use the cheapest tier that catches the class of bug you are worried about.
Run a heavier tier only when the cheaper tier passes. Each new critical
smoke test should be added to `tools/run_pr_validation.py::DEFAULT_TESTS`
so Tier 0 and Tier 1 stay in sync.

| Tier | Tool | Target runtime | Catches | When to use |
| --- | --- | --- | --- | --- |
| 0 | `py -3 tools/run_pr_validation.py` (local) | ~20-40 s | Syntax, import errors, smoke regressions, leakage audit, workflow topology drift | Every change before push |
| 1 | `pr_validation.yml` (CI, auto) | ~2-3 min | Same as Tier 0 on the canonical Linux/Python 3.12 runner | Every push to non-master branches and PRs |
| 2 | `alphaops_replay_sidecars_manual.yml` (CI, manual dispatch) | ~10-30 min | Real-data broker-ledger, position risk, execution policy, weekly leader, theme concentration sidecar metrics from a completed full rebuild's artifacts | Before promoting a sidecar's behavior or comparing alternate cost / overlay parameterizations |
| 3 | `full_rebuild_manual.yml` (CI, manual dispatch) | ~2-3 h fast / ~5-6 h full | Full data collection, 84-month backtests, baseline metric refresh, GDrive sync | Strategy-level regression, baseline rotation, new universe mode |

Tiers 0 and 1 do not depend on `cloud_results/` artifacts and do not
download market data. Tier 2 requires a `source_run_id` from a prior
Tier 3 run. Tier 3 is the only workflow that produces production
artifacts.

## Data Quality Gate

Before reading performance, inspect:

- `outputs/portfolio_system_guard/data_quality_update_plan.json`
- `outputs/portfolio_system_guard/error_check.json`
- `outputs/data_readiness/summary.json`
- `outputs/reports/dataset_coverage_audit.json`
- `outputs/sec_enriched_candidate_replay/summary.json`
- `outputs/full_rebuild_logs/sec_evidence_restore_manifest.json`

Target decisions use only broker-ledger next-close metrics. Deprecated
weight-level backtests, screenshots, and research-only sidecars can suggest
hypotheses but cannot pass production targets.
