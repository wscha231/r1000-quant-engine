# Automation Strategy

This repo keeps scheduled GitHub Actions small in count and explicit in
responsibility. When the trading system changes, update this file, the
workflow that owns the cadence, and the smoke-test topology guard in the same
commit.

## Cadence Matrix

| Cadence | Workflow | Owns | Production impact |
| --- | --- | --- | --- |
| Manual long-run | `full_rebuild_manual.yml` | full data rebuild, backtests, verdicts, GDrive sync, auto-learning diagnostics | Generates production artifacts; no blind baseline rotation |
| Daily after close | `after_close_daily.yml` | scanner, macro pulse, ETF leadership, explosive alerts, tactical review, paper dry-run, Layer 4 suggestions | Dry-run/report-only unless manual `execute=true` |
| Weekly | `weekly_data_refresh.yml` | Finnhub substrate refresh and theme discovery | Data refresh only |
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
