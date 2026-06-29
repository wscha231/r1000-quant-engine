#!/usr/bin/env bash
set -euo pipefail
# Review-only generated commands. Inspect before running.

# bootstrap_free_data_for_eight_year_window
# 8-year price cache is not ready; restore/extend target-book price history first.
gh workflow run free_data_lake_bootstrap.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f latest_run=cloud_results/full_rebuild/latest_global_alpha_universe -f max_price_tickers=0 -f price_mode=target_books -f run_proxy_replay=true -f sec_companyfacts=true -f sync_to_gdrive=true

# full_rebuild_eight_year_official_window
# Run the official 8-year broker-ledger rebuild after data readiness is available.
# blocked until completed_plan_id: bootstrap_free_data_for_eight_year_window
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=official-eight_year-window -f experiment_env_json= -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=false -f universe_mode=global_alpha_universe

