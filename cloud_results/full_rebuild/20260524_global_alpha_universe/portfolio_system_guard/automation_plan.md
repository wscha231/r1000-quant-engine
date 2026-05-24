# Portfolio Automation Plan

Production defaults remain unchanged. Automation is split by runtime cost and promotion risk.

## fast_guard

- Owner: `.github/workflows/portfolio_system_guard.yml`
- Role: Fast PR/manual target gap, artifact, error, and promotion-blocker check from committed data.

## data_refresh

- Owner: `.github/workflows/weekly_data_refresh.yml`
- Role: Refresh Finnhub/theme substrate before deeper rebuilds.

## full_rebuild

- Owner: `.github/workflows/full_rebuild_manual.yml`
- Role: Manual long-run only; use skip_collector=true and fast_mode=true when cached data exists.

## aggressive_lab

- Owner: `.github/workflows/aggressive_lab_manual.yml and tools/run_aggressive_experiment_matrix.py`
- Role: Discovery experiments; failures are retained as research artifacts.

## auto_learning

- Owner: `.github/workflows/quarterly_auto_learning.yml and tools/run_auto_learning_v2.py`
- Role: Feature gates plus Alpha Scientist hypotheses. Proposal-only by default.

## Target Management

- Concentrated full orchestrator replay at 20-30% capacity with caps.
- Main v2 historical replay with target N 12/15 and future_winner-heavy sleeve allocation.
- Risk sensing Layer 1/3/4 position-aware exits to keep MaxDD improvement without CAGR drag.
- Alpha Sprint bull-only replay using breakout/RS/catalyst fallback because explosion_* is dormant.
