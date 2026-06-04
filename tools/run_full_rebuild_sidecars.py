#!/usr/bin/env python3
"""Run full rebuild sidecars outside the GitHub workflow YAML.

The GitHub Actions parser rejects very large `run: |` blocks once expression
scanning crosses its limit. Keeping the long sidecar command list here lets the
workflow expose small profile inputs while this tool owns generation behavior.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


SHELL_SCRIPT = r"""set -e
set -o pipefail
SIDECAR_PROFILE="${SIDECAR_PROFILE:-research_full}"
ARTIFACT_PROFILE="${ARTIFACT_PROFILE:-unknown}"
GDRIVE_SYNC_MODE="${GDRIVE_SYNC_MODE:-unknown}"
PORTFOLIO_POLICY="${PORTFOLIO_POLICY:-production_baseline}"
APPROVED_TARGET_POLICY_PATH="${APPROVED_TARGET_POLICY_PATH:-outputs/promotion_review/approved_target_policy.json}"
echo "[sidecar] profile=${SIDECAR_PROFILE} artifact_profile=${ARTIFACT_PROFILE} gdrive_sync_mode=${GDRIVE_SYNC_MODE} portfolio_policy=${PORTFOLIO_POLICY}"

run_patch_manifest() {
  local run_id="${GITHUB_RUN_ID:-local}"
  python tools/run_patch_application_manifest.py --latest-run outputs --output outputs/patch_application_manifest.json --run-id "$run_id" --head-sha "${GITHUB_SHA:-}" --branch "${GITHUB_REF_NAME:-}" --artifact-id "$run_id" --sidecar-profile "$SIDECAR_PROFILE" --artifact-profile "$ARTIFACT_PROFILE" --gdrive-sync-mode "$GDRIVE_SYNC_MODE" --portfolio-policy "$PORTFOLIO_POLICY" --approved-target-policy-path "$APPROVED_TARGET_POLICY_PATH" 2>&1 | tee outputs/full_rebuild_logs/patch_application_manifest.log || true
}

run_sidecar_promotion_hook() {
  echo "[sidecar-promotion] pre_broker_replay_target_override_hook mode=${PORTFOLIO_POLICY}"
  local hook_mode="$PORTFOLIO_POLICY"
  if [ "$hook_mode" = "alphaops_vnext_production" ]; then
    echo "[sidecar-promotion] alphaops_vnext_production already replaced operating target books; skipping shadow bridge"
  elif [ "$hook_mode" = "integrated_shadow" ]; then
    python tools/run_sidecar_promotion_bridge.py --mode integrated_shadow --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log || true
  elif [ "$hook_mode" = "market_leader_shadow" ]; then
    echo "[sidecar-promotion] writing outputs/operator_review/projected_holdings_after_market_leader_target.csv"
    python tools/run_sidecar_promotion_bridge.py --mode market_leader_shadow --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log || true
  elif [ "$hook_mode" = "approved_integrated" ]; then
    python tools/run_sidecar_promotion_bridge.py --mode approved_integrated --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log
  else
    python tools/run_sidecar_promotion_bridge.py --mode production_baseline --latest-run outputs --price-cache cache_prices --output-root outputs --approved-policy "$APPROVED_TARGET_POLICY_PATH" --source-integrated-dir outputs/integrated_theme_leader_crisis_replay 2>&1 | tee outputs/full_rebuild_logs/sidecar_promotion_bridge.log || true
  fi
}

build_long_crisis_inputs() {
  echo "[long-crisis] building inputs before integrated replay"
  python tools/run_long_crisis_dataset_builder.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_dataset_builder.log || true
  python tools/run_long_crisis_signal_learning.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_signal_learning.log || true
  python tools/run_long_crisis_threshold_search.py 2>&1 | tee outputs/full_rebuild_logs/long_crisis_threshold_search.log || true
}

SIDECAR_CANDIDATE_BOOK="outputs/reports/candidate_replay_book.csv"
build_sec_enriched_candidate_book() {
  SIDECAR_CANDIDATE_BOOK="outputs/reports/candidate_replay_book.csv"
  local enriched="outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv"
  if [ -s "$enriched" ]; then
    SIDECAR_CANDIDATE_BOOK="$enriched"
    echo "[sec-enrich] using existing enriched candidate book: $SIDECAR_CANDIDATE_BOOK"
    return 0
  fi
  echo "[sec-enrich] building PIT-safe evidence-enriched candidate replay book"
  if [ ! -s "$SIDECAR_CANDIDATE_BOOK" ]; then
    echo "[sec-enrich] missing base candidate replay book; sidecars will use default resolver"
    return 0
  fi
  python tools/run_sec_enriched_candidate_replay.py --candidate-book "$SIDECAR_CANDIDATE_BOOK" --output-dir outputs/sec_enriched_candidate_replay 2>&1 | tee outputs/full_rebuild_logs/sec_enriched_candidate_replay.log || true
  if [ -s "$enriched" ]; then
    SIDECAR_CANDIDATE_BOOK="$enriched"
    echo "[sec-enrich] using enriched candidate book: $SIDECAR_CANDIDATE_BOOK"
  else
    echo "[sec-enrich] enriched candidate book unavailable; using base candidate book"
  fi
}

run_alphaops_vnext_production() {
  if [ "$PORTFOLIO_POLICY" = "alphaops_vnext_production" ]; then
    echo "[alphaops-vnext] replacing operating target books before broker replay"
    build_sec_enriched_candidate_book
    python tools/run_alphaops_vnext_policy_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/alphaops_vnext --portfolio-kind both --main-target-n 15 --concentrated-target-n 5 --production-output-mode replace_operating --skip-broker-replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log
  fi
}

run_decision_cadence_review() {
  echo "[decision-cadence] reviewing daily/weekly/monthly decision cadence"
  python tools/run_decision_cadence_review.py --latest-run outputs --price-cache cache_prices --output-dir outputs/decision_cadence 2>&1 | tee outputs/full_rebuild_logs/decision_cadence_review.log || true
}

run_metric_hygiene_report() {
  echo "[metric-hygiene] separating official broker-ledger metrics from deprecated legacy/proxy metrics"
  python tools/run_metric_hygiene_report.py --latest-run outputs --output-dir outputs/metric_hygiene 2>&1 | tee outputs/full_rebuild_logs/metric_hygiene_report.log || true
}

if [ "$SIDECAR_PROFILE" = "phase_g_only" ]; then
  echo "[sidecar] phase_g_only is handled by phase_g_crisis_evidence_liquidity_replay.yml; skipping full rebuild sidecars."
  mkdir -p outputs/full_rebuild_logs
  BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
  run_patch_manifest
  exit 0
fi
if [ "$SIDECAR_PROFILE" = "operating_minimal" ] || [ "$SIDECAR_PROFILE" = "official" ]; then
  python tools/build_operating_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/operating_target_books.log
  run_alphaops_vnext_production
  run_sidecar_promotion_hook
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_main.log
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log
  python tools/run_mdd_cash_overlay_research.py --latest-run outputs --output-dir outputs/mdd_cash_overlay_research --cost-bps 25 --confirm-days 2 --release-step 0.10 --change-band 0.03 2>&1 | tee outputs/full_rebuild_logs/mdd_cash_overlay_research.log || true
  if [ "$SIDECAR_PROFILE" = "official" ]; then
    python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_position_risk_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_main.log || true
    python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_position_risk_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log || true
  fi
  python tools/run_account_order_preview.py --account-state outputs/broker_replay/main/account_state_latest.json --target outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/account_ledger_preview/main --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_main.log || true
  python tools/run_account_order_preview.py --account-state outputs/broker_replay/concentrated/account_state_latest.json --target outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/account_ledger_preview/concentrated --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_concentrated.log || true
  python tools/run_live_trading_safety_audit.py --latest-run outputs --output-dir outputs/live_trading_safety 2>&1 | tee outputs/full_rebuild_logs/live_trading_safety_audit.log || true
  python tools/run_live_trading_risk_controls.py --latest-run outputs --price-cache cache_prices --output-dir outputs/live_trading_risk_controls --account-mode simulated 2>&1 | tee outputs/full_rebuild_logs/live_trading_risk_controls.log || true
  python tools/run_macro_policy_engine.py --latest-run outputs --output-dir outputs/macro_policy_engine 2>&1 | tee outputs/full_rebuild_logs/macro_policy_engine.log || true
  python tools/run_cash_policy_attribution.py --latest-run outputs --output-dir outputs/cash_policy 2>&1 | tee outputs/full_rebuild_logs/cash_policy_attribution.log || true
  python tools/run_portfolio_goal_search.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/portfolio_goal_search.log || true
  python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation 2>&1 | tee outputs/full_rebuild_logs/account_evaluation.log || true
  run_metric_hygiene_report
  python tools/run_operating_snapshot.py --latest-run outputs --output-dir outputs/operating_snapshot 2>&1 | tee outputs/full_rebuild_logs/operating_snapshot.log || true
  python tools/run_user_portfolio_reports.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_portfolio_reports 2>&1 | tee outputs/full_rebuild_logs/user_portfolio_reports.log || true
  python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
  python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report.log
  python tools/run_daily_crisis_monitor.py --latest-run outputs --output-dir outputs/daily_crisis_monitor 2>&1 | tee outputs/full_rebuild_logs/daily_crisis_monitor.log || true
  run_decision_cadence_review
  python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness.log || true
  python tools/run_dataset_coverage_audit.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/dataset_coverage_audit.log || true
  python tools/run_portfolio_system_guard.py --latest-run outputs --output-dir outputs/portfolio_system_guard 2>&1 | tee outputs/full_rebuild_logs/portfolio_system_guard.log || true
  if [ "$SIDECAR_PROFILE" = "official" ]; then
    python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_execution_policy_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_main.log || true
    python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_execution_policy_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --buy-band 0.04 --sell-band 0.06 --winner-overweight-band 0.15 --new-entry-scale 0.85 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log || true
    python tools/run_execution_lag_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/execution_lag_review.log || true
    python tools/run_position_risk_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_risk_review.log || true
    python tools/run_concentrated_broker_variant_review.py --latest-run outputs --price-cache cache_prices --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/concentrated_broker_variant_review.log || true
    python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
    BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
    python tools/create_healthy_baseline_lock.py --latest-run outputs --output-dir outputs/baseline_lock --run-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/baseline_lock.log || true
    build_sec_enriched_candidate_book
    python tools/run_market_leader_challenger.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/market_leader_challenger --baseline-lock "outputs/baseline_lock/healthy_baseline_${BASELINE_RUN_ID}.json" --allow-missing-baseline-lock 2>&1 | tee outputs/full_rebuild_logs/market_leader_challenger.log || true
    python tools/run_superperformance_trader_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/superperformance_trader_replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/superperformance_trader_replay.log || true
    build_long_crisis_inputs
    python tools/run_integrated_theme_leader_crisis_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/integrated_theme_leader_crisis_replay --baseline-lock outputs/baseline_lock/active_baseline.json --portfolio-kind both --cost-bps 25 --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log || true
    if [ "$PORTFOLIO_POLICY" = "integrated_shadow" ] || [ "$PORTFOLIO_POLICY" = "market_leader_shadow" ]; then
      run_sidecar_promotion_hook
    fi
    python tools/run_strategy_logic_ledger.py --latest-run outputs --integrated-output outputs/integrated_theme_leader_crisis_replay --output-dir outputs/strategy_logic_ledger --run-id "$BASELINE_RUN_ID" --commit-sha "${GITHUB_SHA:-}" --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/strategy_logic_ledger.log || true
    run_decision_cadence_review
    run_patch_manifest
    python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report_final.log || true
  fi
  BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
  run_patch_manifest
  python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report_final.log || true
  echo "[sidecar] ${SIDECAR_PROFILE} completed; heavy research sidecars skipped."
  exit 0
fi
python tools/run_main_v2_backtest.py --latest-run outputs --output-dir outputs/main_v2_backtest 2>&1 | tee outputs/full_rebuild_logs/main_v2_backtest.log || true
python tools/run_concentrated_policy_replay.py --latest-run outputs --output-dir outputs/concentrated_policy_replay --price-cache cache_prices --run-broker-replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/concentrated_policy_replay.log || true
python tools/run_concentrated_position_risk_replay.py --latest-run outputs --output-dir outputs/concentrated_position_risk_replay 2>&1 | tee outputs/full_rebuild_logs/concentrated_position_risk_replay.log || true
python tools/run_alpha_sprint_backtest.py --latest-run outputs --output-dir outputs/alpha_sprint_backtest 2>&1 | tee outputs/full_rebuild_logs/alpha_sprint_backtest.log || true
python tools/run_position_aware_risk_replay.py --holdings outputs/main_v2_backtest/monthly_holdings.csv --output-dir outputs/position_aware_risk_replay 2>&1 | tee outputs/full_rebuild_logs/position_aware_risk_replay.log || true
python tools/build_operating_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/operating_target_books.log
run_alphaops_vnext_production
run_sidecar_promotion_hook
python tools/archive_target_snapshots.py --latest-run outputs --price-cache cache_prices --output-dir outputs/target_snapshots 2>&1 | tee outputs/full_rebuild_logs/target_snapshot_archive.log
python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/main_monthly_weights.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main.log || true
python tools/run_position_risk_weekly_validation.py --holdings outputs/main_v2_backtest/monthly_holdings.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main_v2 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_main_v2.log || true
python tools/run_position_risk_weekly_validation.py --holdings outputs/reports/concentrated_strategy_holdings.csv --period-map outputs/reports/concentrated_strategy_monthly.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/position_risk_weekly_validation/concentrated 2>&1 | tee outputs/full_rebuild_logs/position_risk_weekly_validation_concentrated.log || true
python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_main.log
python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log
python tools/run_mdd_cash_overlay_research.py --latest-run outputs --output-dir outputs/mdd_cash_overlay_research --cost-bps 25 --confirm-days 2 --release-step 0.10 --change-band 0.03 2>&1 | tee outputs/full_rebuild_logs/mdd_cash_overlay_research.log || true
python tools/build_event_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/event_target_books --reports-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/event_target_books.log || true
if [ -s outputs/reports/event_main_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/event_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/event_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/event_broker_replay_main.log || true
fi
if [ -s outputs/reports/event_concentrated_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/event_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/event_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/event_broker_replay_concentrated.log || true
fi
python tools/build_weekly_leader_target_books.py --latest-run outputs --price-cache cache_prices --output-dir outputs/weekly_leader_snapshots --reports-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_target_books.log || true
if [ -s outputs/reports/weekly_leader_main_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/weekly_leader_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/weekly_leader_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_broker_replay_main.log || true
fi
if [ -s outputs/reports/weekly_leader_concentrated_target_book.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/weekly_leader_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/weekly_leader_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/weekly_leader_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_cost_sensitivity_sidecar.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/cost_sensitivity/main --cost-bps-list 25 50 75 100 --baseline-cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/cost_sensitivity_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_cost_sensitivity_sidecar.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/cost_sensitivity/concentrated --cost-bps-list 25 50 75 100 --baseline-cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/cost_sensitivity_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_neutral_regime_churn_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_churn_filtered.csv --diagnostics outputs/churn_filter/main/diagnostics.json --swap-threshold 2 --window-months 6 --target-regimes neutral 2>&1 | tee outputs/full_rebuild_logs/churn_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_churn_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_churn_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/churn_filtered_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/churn_filtered_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_macro_filtered.csv --diagnostics outputs/macro_circuit_filter/main/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.5 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_macro_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_macro_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/macro_circuit_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_macro_circuit_breaker_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_macro_filtered.csv --diagnostics outputs/macro_circuit_filter/concentrated/diagnostics.json --price-cache cache_prices --ma-window 200 --confirm-days 3 --halve-factor 0.5 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_filter_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_macro_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_macro_filtered.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/macro_circuit_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/macro_circuit_broker_replay_concentrated.log || true
fi
if [ -s outputs/reports/operating_main_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_main_target_book.csv --output-book outputs/reports/operating_main_target_book_regime_capacity_filtered.csv --diagnostics outputs/regime_capacity_filter/main/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25" 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_main.log || true
fi
if [ -s outputs/reports/operating_main_target_book_regime_capacity_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_main_target_book_regime_capacity_filtered.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/regime_capacity_broker_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_main.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book.csv ]; then
  python tools/run_regime_capacity_filter.py --input-book outputs/reports/operating_concentrated_target_book.csv --output-book outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv --diagnostics outputs/regime_capacity_filter/concentrated/diagnostics.json --multipliers "bear=0.5,deep_bear=0.25,neutral=0.85" --regime-source-book outputs/reports/operating_main_target_book.csv 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_filter_concentrated.log || true
fi
if [ -s outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv ]; then
  python tools/run_broker_ledger_replay.py --target-book outputs/reports/operating_concentrated_target_book_regime_capacity_filtered.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/regime_capacity_broker_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/regime_capacity_broker_replay_concentrated.log || true
fi
python tools/run_trade_attribution_analysis.py --latest-run outputs --output-dir outputs/trade_attribution 2>&1 | tee outputs/full_rebuild_logs/trade_attribution_analysis.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_position_risk_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_main.log || true
python tools/run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_position_risk_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log || true
python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/broker_execution_policy_replay/main --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_main.log || true
python tools/run_broker_execution_policy_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/broker_execution_policy_replay/concentrated --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 --buy-band 0.04 --sell-band 0.06 --winner-overweight-band 0.15 --new-entry-scale 0.85 2>&1 | tee outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log || true
python tools/run_operating_event_backtest.py --latest-run outputs --output-dir outputs/operating_event_backtest 2>&1 | tee outputs/full_rebuild_logs/operating_event_backtest.log || true
python tools/run_broker_gap_attribution.py --latest-run outputs --output-dir outputs/broker_gap_attribution 2>&1 | tee outputs/full_rebuild_logs/broker_gap_attribution.log || true
python tools/run_broker_trade_journal.py --latest-run outputs --output-dir outputs/broker_trade_journal 2>&1 | tee outputs/full_rebuild_logs/broker_trade_journal.log || true
python tools/run_account_order_preview.py --account-state outputs/broker_replay/main/account_state_latest.json --target outputs/reports/operating_main_target_book.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/account_ledger_preview/main --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_main.log || true
python tools/run_account_order_preview.py --account-state outputs/broker_replay/concentrated/account_state_latest.json --target outputs/reports/operating_concentrated_target_book.csv --price-cache cache_prices --portfolio-kind concentrated --output-dir outputs/account_ledger_preview/concentrated --cost-bps 25 2>&1 | tee outputs/full_rebuild_logs/account_order_preview_concentrated.log || true
python tools/run_live_trading_safety_audit.py --latest-run outputs --output-dir outputs/live_trading_safety 2>&1 | tee outputs/full_rebuild_logs/live_trading_safety_audit.log || true
python tools/run_live_trading_risk_controls.py --latest-run outputs --price-cache cache_prices --output-dir outputs/live_trading_risk_controls --account-mode simulated 2>&1 | tee outputs/full_rebuild_logs/live_trading_risk_controls.log || true
python tools/run_monster_lifecycle_replay.py --latest-run outputs --policy concentrated --output-dir outputs/monster_lifecycle_replay 2>&1 | tee outputs/full_rebuild_logs/monster_lifecycle_replay.log || true
python tools/run_lifecycle_review_overlay.py --latest-run outputs --policy lifecycle_review_main --output-dir outputs/lifecycle_review_overlay_main 2>&1 | tee outputs/full_rebuild_logs/lifecycle_review_overlay_main.log || true
python tools/run_monster_lifecycle_replay.py --latest-run outputs --policy lifecycle_review_main --output-dir outputs/monster_lifecycle_review_main 2>&1 | tee outputs/full_rebuild_logs/monster_lifecycle_review_main.log || true
python tools/run_monster_lifecycle_replay.py --latest-run outputs --policy lifecycle_review_concentrated --output-dir outputs/monster_lifecycle_review_concentrated 2>&1 | tee outputs/full_rebuild_logs/monster_lifecycle_review_concentrated.log || true
python tools/run_orchestrator_replay.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/orchestrator_replay.log || true
python tools/run_leader_drop_diagnostics_sidecar.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/leader_drop_diagnostics_sidecar.log || true
python tools/run_governance_catalyst_report.py --latest-run outputs --output-dir outputs/governance_catalyst 2>&1 | tee outputs/full_rebuild_logs/governance_catalyst_report.log || true
python tools/run_style_regime_report.py --latest-run outputs --output-dir outputs/style_regime_report 2>&1 | tee outputs/full_rebuild_logs/style_regime_report.log || true
python tools/run_macro_policy_engine.py --latest-run outputs --output-dir outputs/macro_policy_engine 2>&1 | tee outputs/full_rebuild_logs/macro_policy_engine.log || true
python tools/run_cash_policy_attribution.py --latest-run outputs --output-dir outputs/cash_policy 2>&1 | tee outputs/full_rebuild_logs/cash_policy_attribution.log || true
python tools/run_main_cash_drag_replay.py --latest-run outputs --output-dir outputs/main_cash_drag_replay 2>&1 | tee outputs/full_rebuild_logs/main_cash_drag_replay.log || true
python tools/run_crisis_reentry_replay.py --latest-run outputs --output-dir outputs/crisis_reentry_replay 2>&1 | tee outputs/full_rebuild_logs/crisis_reentry_replay.log || true
python tools/run_broker_crisis_reentry_replay.py --latest-run outputs --price-cache cache_prices --output-dir outputs/broker_crisis_reentry_replay/main --policy-id fast_reentry --fill-mode next_close --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/broker_crisis_reentry_replay.log || true
python tools/run_portfolio_goal_search.py --latest-run outputs 2>&1 | tee outputs/full_rebuild_logs/portfolio_goal_search.log || true
python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation 2>&1 | tee outputs/full_rebuild_logs/account_evaluation.log || true
run_metric_hygiene_report
python tools/run_historical_trade_journey.py --latest-run outputs --output-dir outputs/historical_trade_journey 2>&1 | tee outputs/full_rebuild_logs/historical_trade_journey.log || true
python tools/run_selection_audit.py --latest-run outputs --output-dir outputs/selection_audit 2>&1 | tee outputs/full_rebuild_logs/selection_audit.log || true
python tools/run_dataset_coverage_audit.py --latest-run outputs --output-dir outputs/reports 2>&1 | tee outputs/full_rebuild_logs/dataset_coverage_audit.log || true
python tools/check_10y_backtest_readiness.py --latest-run outputs --output-dir outputs/ten_year_backtest_readiness 2>&1 | tee outputs/full_rebuild_logs/ten_year_backtest_readiness.log || true
python tools/audit_data_readiness.py --latest-run outputs --price-cache cache_prices --output-dir outputs/data_readiness 2>&1 | tee outputs/full_rebuild_logs/data_readiness.log || true
python tools/run_weekly_evaluation.py --latest-run outputs --price-cache cache_prices --output-dir outputs/weekly_evaluation --stale-days-threshold 10 2>&1 | tee outputs/full_rebuild_logs/weekly_evaluation.log || true
python tools/run_theme_leadership_tape.py --scored outputs/scored_latest.csv --price-cache cache_prices --output-dir outputs/theme_leadership_tape 2>&1 | tee outputs/full_rebuild_logs/theme_leadership_tape.log || true
python tools/run_theme_concentration_challenger.py --latest-run outputs --output-dir outputs/theme_concentration_challenger --top-n 3 --single-name-cap 0.50 --cost-bps 50 2>&1 | tee outputs/full_rebuild_logs/theme_concentration_challenger.log || true
BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
python tools/create_healthy_baseline_lock.py --latest-run outputs --output-dir outputs/baseline_lock --run-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/baseline_lock.log || true
build_sec_enriched_candidate_book
python tools/run_market_leader_challenger.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/market_leader_challenger --baseline-lock "outputs/baseline_lock/healthy_baseline_${BASELINE_RUN_ID}.json" --allow-missing-baseline-lock 2>&1 | tee outputs/full_rebuild_logs/market_leader_challenger.log || true
python tools/run_superperformance_trader_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/superperformance_trader_replay --cost-bps 25 --max-fill-lag-days 7 2>&1 | tee outputs/full_rebuild_logs/superperformance_trader_replay.log || true
build_long_crisis_inputs
python tools/run_integrated_theme_leader_crisis_replay.py --latest-run outputs --candidate-book "$SIDECAR_CANDIDATE_BOOK" --price-cache cache_prices --output-dir outputs/integrated_theme_leader_crisis_replay --baseline-lock outputs/baseline_lock/active_baseline.json --portfolio-kind both --cost-bps 25 --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log || true
if [ "$PORTFOLIO_POLICY" = "integrated_shadow" ] || [ "$PORTFOLIO_POLICY" = "market_leader_shadow" ]; then
  run_sidecar_promotion_hook
fi
python tools/run_strategy_logic_ledger.py --latest-run outputs --integrated-output outputs/integrated_theme_leader_crisis_replay --output-dir outputs/strategy_logic_ledger --run-id "$BASELINE_RUN_ID" --commit-sha "${GITHUB_SHA:-}" --artifact-id "$BASELINE_RUN_ID" 2>&1 | tee outputs/full_rebuild_logs/strategy_logic_ledger.log || true
python tools/run_auto_learning_v2.py --latest-run outputs --output-dir outputs/auto_learning_v2 --research-dir outputs/auto_learning_v2/research 2>&1 | tee outputs/full_rebuild_logs/auto_learning_v2.log || true
python tools/run_winner_lifecycle_reports.py --latest-run outputs --output-dir outputs/winner_lifecycle 2>&1 | tee outputs/full_rebuild_logs/winner_lifecycle.log || true
python tools/run_winner_onset_study.py --scored outputs/scored_latest.csv --top-tickers 80 --limit 80 --years 10 --output-dir outputs/winner_onset_study 2>&1 | tee outputs/full_rebuild_logs/winner_onset_study.log || true
python tools/run_shakeout_breakdown_study.py --scored outputs/scored_latest.csv --top-tickers 80 --limit 80 --years 10 --output-dir outputs/shakeout_breakdown_study 2>&1 | tee outputs/full_rebuild_logs/shakeout_breakdown_study.log || true
python tools/run_shakeout_disclosure_reversal_study.py --events data_pit/sec/13f_position_events.parquet --events data_pit/sec/form4_transaction_events.parquet --events data_pit/etf_holdings/etf_holding_events.parquet --price-cache cache_prices --output-dir outputs/shakeout_disclosure_reversal_study 2>&1 | tee outputs/full_rebuild_logs/shakeout_disclosure_reversal_study.log || true
python tools/run_pit_top_manager_follow_study.py --events data_pit/sec/13f_position_events.parquet --labels data_pit/sec/post_disclosure_alpha_labels.parquet --output-dir outputs/pit_top_manager_follow_study --cohort-pit data_pit/sec/pit_top_manager_cohorts.parquet --follow-events-pit data_pit/sec/top_manager_13f_follow_events.parquet --horizons 21,63,126,252 --ranking-horizon 63 --ranking-lookback-days 1095 --cohort-refresh-months 6 --top-n 10 --min-manager-events 8 --history-years 8 2>&1 | tee outputs/full_rebuild_logs/pit_top_manager_follow_study.log || true
python tools/run_autolearning_winner_challenger.py --latest-run outputs --autolearning-dir outputs/auto_learning_v2 --lifecycle-dir outputs/winner_lifecycle --onset-dir outputs/winner_onset_study --shakeout-dir outputs/shakeout_breakdown_study --cash-drag-dir outputs/main_cash_drag_replay --main-v2-replay-dir outputs/main_v2_backtest --concentrated-replay-dir outputs/concentrated_policy_replay --alpha-sprint-replay-dir outputs/alpha_sprint_backtest --position-risk-replay-dir outputs/position_aware_risk_replay --monster-lifecycle-replay-dir outputs/monster_lifecycle_replay --output-dir outputs/autolearning_winner_challenger 2>&1 | tee outputs/full_rebuild_logs/autolearning_winner_challenger.log || true
python tools/run_alphaops_policy_fusion.py --latest-run outputs --output-dir outputs/policy_fusion 2>&1 | tee outputs/full_rebuild_logs/policy_fusion.log || true
python tools/run_monster_recommendation_bridge.py --latest-run outputs --output-dir outputs/monster_recommendations 2>&1 | tee outputs/full_rebuild_logs/monster_recommendations.log || true
python tools/run_operating_snapshot.py --latest-run outputs --output-dir outputs/operating_snapshot 2>&1 | tee outputs/full_rebuild_logs/operating_snapshot.log || true
python tools/run_user_portfolio_reports.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_portfolio_reports 2>&1 | tee outputs/full_rebuild_logs/user_portfolio_reports.log || true
python tools/run_position_cleanup_review.py --latest-run outputs --output-dir outputs/operator_review 2>&1 | tee outputs/full_rebuild_logs/position_cleanup_review.log || true
BASELINE_RUN_ID="${GITHUB_RUN_ID:-local}"
python tools/run_daily_crisis_monitor.py --latest-run outputs --output-dir outputs/daily_crisis_monitor 2>&1 | tee outputs/full_rebuild_logs/daily_crisis_monitor.log || true
run_decision_cadence_review
python tools/run_portfolio_system_guard.py --latest-run outputs --output-dir outputs/portfolio_system_guard 2>&1 | tee outputs/full_rebuild_logs/portfolio_system_guard.log || true
run_patch_manifest
python tools/run_user_current_report.py --latest-run outputs --price-cache cache_prices --output-dir outputs/user_current --strict 2>&1 | tee outputs/full_rebuild_logs/user_current_report.log || true
run_patch_manifest

"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run profile-gated full rebuild sidecars")
    parser.add_argument(
        "--profile",
        choices=["operating_minimal", "official", "research_full", "phase_g_only"],
        default="operating_minimal",
        help="Sidecar generation profile from full_rebuild_manual.yml",
    )
    parser.add_argument("--artifact-profile", default=os.environ.get("ARTIFACT_PROFILE", "unknown"))
    parser.add_argument("--gdrive-sync-mode", default=os.environ.get("GDRIVE_SYNC_MODE", "unknown"))
    parser.add_argument("--portfolio-policy", choices=["production_baseline", "integrated_shadow", "market_leader_shadow", "approved_integrated", "alphaops_vnext_production"], default=os.environ.get("PORTFOLIO_POLICY", "production_baseline"))
    parser.add_argument("--approved-target-policy-path", default=os.environ.get("APPROVED_TARGET_POLICY_PATH", "outputs/promotion_review/approved_target_policy.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = os.environ.copy()
    env["SIDECAR_PROFILE"] = args.profile
    env["ARTIFACT_PROFILE"] = args.artifact_profile
    env["GDRIVE_SYNC_MODE"] = args.gdrive_sync_mode
    env["PORTFOLIO_POLICY"] = args.portfolio_policy
    env["APPROVED_TARGET_POLICY_PATH"] = args.approved_target_policy_path
    if os.name == "nt":
        print("run_full_rebuild_sidecars.py is intended for the GitHub Linux runner", file=sys.stderr)
        return 2
    completed = subprocess.run(["bash", "-lc", SHELL_SCRIPT], env=env, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
