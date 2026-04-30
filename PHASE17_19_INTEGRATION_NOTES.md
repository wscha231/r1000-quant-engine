# Phase 17-19 Integration Notes

Generated: 2026-04-30 KST

Branch: `codex/integrate-phase17-19`

## Integration Policy

This branch starts from current `origin/master` and ports Claude branch
functionality in a staged way. The goal is to preserve the proven production
baseline while surfacing the new tactical, journal, and orchestration tooling.

Production selection behavior is intentionally not changed by blind weight
increases. New columns and sidecar outputs are added first; any future allocation
change must pass A/B backtests against the current Phase 15-D/16/17A baseline.

## Preserved From Master

- ADR USD market-cap normalization.
- Concentrated continuation-winner override.
- Phase 15-D baseline rotation.
- Phase 16 CAGR-push settings.
- Current `full_rebuild_manual.yml` inputs for `global_alpha_universe`,
  `backtest_years`, `fast_mode`, cache preflight, and Google Drive sync.

## Ported Functionality

- Trade journal sidecar:
  - `r1000_trade_journal.py`
  - `tools/grade_trades.py`
  - `r1000_pipeline.backtest_portfolio` writes `outputs/trade_journal/*`.
- Tactical research backtester:
  - `r1000_tactical_backtest.py`
  - `tactical_backtest_monthly.yml`
- Explosive mover research stack:
  - `tools/build_explosive_pattern_db.py`
  - `tools/train_explosion_classifier.py`
  - `tools/explosive_mover_scan_daily.py`
  - `explosive_pattern_train_monthly.yml`
  - `explosive_mover_daily.yml`
- Daily macro and ETF sidecars:
  - `tools/macro_daily_snapshot.py`
  - `tools/etf_leadership_snapshot.py`
  - related workflows.
- Trade insight and PR-only feature-gate proposal tools:
  - `tools/trade_insights.py`
  - `tools/feature_gate_proposal.py`
  - `quarterly_trade_insights.yml`
  - `auto_feature_gate_proposal_quarterly.yml`
- Orchestrator inspection scaffold:
  - `r1000_orchestrator.py`
  - `tools/run_orchestrator.py`
  - `MANDATE_REGISTRY` metadata in `r1000_config.py`.

## Production Feature Surface

The feature store now surfaces:

- `explosion_entry_score`
- `explosion_exit_score`
- `explosion_net_score`
- `regime_state`
- `regime_state_score`

These columns are for scanners, journal analysis, and future A/B tests. They are
not added to `DEFAULT_FEATURES` in this integration pass, so current model
selection behavior is preserved. If explosion models are missing, the explosion
columns fill with `0.0`.

`ENGINE_REUSE_VERSION` is bumped because feature-store schema changes.

## Disabled / Deferred

- `auto_baseline_rotation_weekly.yml` is not ported. Automatic baseline rotation
  should stay PR/manual until metrics paths and gate semantics are proven.
- The orchestrator is report-only. It does not replace production portfolio
  construction.
- ETF leadership does not alter production sector caps in this pass.
- Auto feature gates are proposal-only until separately reviewed and enabled.

## Next Validation Run

Recommended first cloud run:

- workflow: `Full Rebuild (Manual / Long-Run)`
- branch: `codex/integrate-phase17-19`
- `universe_mode=global_alpha_universe`
- `backtest_years=8`
- `fast_mode=true`
- `skip_collector=false` for first schema/cache rebuild
- cache suffix: `phase17-19-sidecar`

Primary verdict questions:

- Did core CAGR remain at or above the Phase 15-D/16 baseline range?
- Did concentrated CAGR remain above 30% with continuation winners intact?
- Are ADR market caps still normalized and selected counts visible?
- Are `regime_state` and `explosion_*` columns present in `scored_latest.csv`?
- Did `outputs/trade_journal/*` and sidecar artifacts generate without changing
  backtest metrics?
