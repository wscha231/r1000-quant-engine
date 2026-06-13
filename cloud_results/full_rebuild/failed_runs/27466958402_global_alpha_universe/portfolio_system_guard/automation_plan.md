# Portfolio Automation Plan

Production defaults remain unchanged. Automation is split by runtime cost and promotion risk.

## fast_guard

- Owner: `.github/workflows/portfolio_system_guard.yml`
- Role: Fast PR/manual target gap, artifact, error, and promotion-blocker check from committed data.

## data_refresh

- Owner: `.github/workflows/weekly_data_refresh.yml`
- Role: Refresh substrate data, PIT freshness, universe, theme, and coverage diagnostics before deeper rebuilds.

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

- Run data quality and PIT coverage checks before interpreting CAGR/MDD.
- Use broker-trade attribution to separate data gaps from policy errors across the full period.
- Improve theme leadership and macro regime features before adding broad cash or sizing rules.
- Promote only reversible PIT-safe rules that improve official broker MDD without losing target CAGR.
