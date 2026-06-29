#!/usr/bin/env bash
set -euo pipefail
# Review-only generated commands. Inspect before running.

# bootstrap_free_data_for_8y_window
# 8-year broker-ledger window is not ready; extend/restore price and free-data cache first.
gh workflow run free_data_lake_bootstrap.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f latest_run=cloud_results/full_rebuild/latest_global_alpha_universe -f max_price_tickers=0 -f price_mode=target_books -f run_proxy_replay=true -f sec_companyfacts=true -f sync_to_gdrive=true

# full_rebuild_8y_official_after_data_bootstrap
# After free-data bootstrap, run the official 8-year broker-ledger rebuild with the production policy.
# blocked until completed_plan_id: bootstrap_free_data_for_8y_window
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=official-8y-window -f experiment_env_json= -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=false -f universe_mode=global_alpha_universe

# ab_conc_continuation_winner_relaxation
# Concentrated CAGR or Tier-2 gate is short; relax continuation-winner filters only as a review A/B.
# blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=ab_conc_continuation_winner_relaxation -f 'experiment_env_json={"PHASE_CONCENTRATED_CONTINUATION_RELAX_ENABLED": "1"}' -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=true -f universe_mode=global_alpha_universe

# ab_conc_bull_floor_stock_min
# Concentrated CAGR or Tier-2 gate is short; measure bull/strong_bull stock-floor exposure as an isolated A/B.
# blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=ab_conc_bull_floor_stock_min -f 'experiment_env_json={"PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED": "1"}' -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=true -f universe_mode=global_alpha_universe

# ab_conc_reentry_quality
# Concentrated CAGR or Tier-2 gate is short; measure reentry quality after cash/defense states as an isolated A/B.
# blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=ab_conc_reentry_quality -f 'experiment_env_json={"PHASE_CONCENTRATED_REENTRY_QUALITY_ENABLED": "1"}' -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=true -f universe_mode=global_alpha_universe

# ab_conc_theme_leadership_boost
# Concentrated CAGR or Tier-2 gate is short; test theme-leadership confirmation boost as an isolated A/B.
# blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=ab_conc_theme_leadership_boost -f 'experiment_env_json={"PHASE_THEME_LEADERSHIP_BOOST_ENABLED": "1"}' -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=true -f universe_mode=global_alpha_universe

# ab_conc_concentration_cap_relaxation
# Concentrated CAGR or Tier-2 gate is short; test confirmed-winner cap relaxation while preserving broker-ledger gates.
# blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap
# gh workflow run full_rebuild_manual.yml --repo wscha231/r1000-quant-engine --ref codex/integration-main-conc-target-hooks-20260629 -f artifact_profile=minimal -f backtest_years=8 -f cache_key_suffix=ab_conc_concentration_cap_relaxation -f 'experiment_env_json={"PHASE_CONCENTRATED_CAP_RELAX_ENABLED": "1"}' -f fast_mode=true -f gdrive_sync_mode=minimal -f portfolio_policy=alphaops_vnext_production -f sidecar_profile=operating_minimal -f skip_collector=true -f universe_mode=global_alpha_universe

