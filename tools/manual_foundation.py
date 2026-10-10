#!/usr/bin/env python3
"""Offline manual pinning/preflight only; no worker, board or accepted-state writes."""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import run_agent_board as board
from tools.check_run287_do_not_repeat import evaluate_candidate, normalize
from tools.build_run287_u0_v2_github_census import validated_do_not_repeat_entries

MANIFEST = 'research/control_plane/manual_playbooks_v1.json'
SCHEMA = 'research/control_plane/manual_task_packet_schema.json'
CATALOG = 'docs/pr_reuse_catalog.json'
DNR = 'docs/run287_do_not_repeat_registry.json'
OPERATING_CONTRACTS = ['AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                       'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md']
PLAYBOOK_IDS = {'L0_RESUME_HANDOFF': 'A0', 'A1_SOURCE_ADMISSION_REFRESH': 'A1',
                'A6_INDEPENDENT_QA': 'A6'}
# Independently verified review baseline, not a value supplied by the manifest.
# Git commit 86bdcd474ae12d240d1dac31f72f758f45f26843 contains this manifest
# blob and these retained version identities. Changes to the anchor require
# a separately reviewed code change; packet/manifest rehashing cannot reset it.
VERSION_ANCHOR_HEAD = '86bdcd474ae12d240d1dac31f72f758f45f26843'
VERSION_ANCHOR_BLOB = 'cc4f0ced44f12210b88b001ee1a2a87b827cdbe0'
VERSION_ANCHOR = (('L0_RESUME_HANDOFF', '1.0.0'),
                  ('A1_SOURCE_ADMISSION_REFRESH', '1.0.0'),
                  ('A6_INDEPENDENT_QA', '1.0.0'))
# Canonical SHA256 of each actual reviewed row, excluding only status and its
# derived playbook_sha256. Status may become SUPERSEDED; its content stays fixed.
# Every subsequently adopted version requires its own independently reviewed
# entry here. Unanchored CURRENT rows are proposals, never adopted versions.
VERSION_ANCHOR_CONTENT = {
    ('L0_RESUME_HANDOFF', '1.0.0'): 'c9f3a1d54fbcb699b20565e73a469c0c5b1a7c49e917bb395ab9f646da60159c',
    ('A1_SOURCE_ADMISSION_REFRESH', '1.0.0'): 'bdb5291b17aa145394a076c5865ccd73cfeb9943c6436943587db2ab7031caa6',
    ('A6_INDEPENDENT_QA', '1.0.0'): 'bed61231c97ea31ec5b23127af5481d6121713331d1925faa39b363ff4ff34ce',
}
# Actual frozen Reader imports/default registry, including its NYSE calendar.
# Collector-only imports are not consumed by the read-only Reader path.
A1_READER_DEPENDENCIES = [
    'tools/research_data_access.py', 'data_static/research_dataset_registry_v1.json',
    'tools/long_history_lake.py', 'tools/macro_history_sources.py',
    'tools/macro_research_checkpoint.py', 'tools/run_data_freshness_contract.py',
    'r1000_legacy_input_guard.py']
# The board is already a common fixed dependency. Its mandatory local import,
# source_identity() inputs and AST-read mission/gate literals must travel with
# that pin, even when a proposed Toolbox omits them. Other state/task inputs
# remain the independently verified caller's explicit dependency responsibility.
BOARD_INPUT_DEPENDENCIES = [
    'mission_contract.py', 'r1000_config.py', 'requirements_github.txt',
    'research/control_plane/system_state_schema.json', 'tools/materialize_system_state.py']
# Existing default PR-validation program closure traced at source HEAD
# 2677e0281ce8fa98154a296885275b70db3fed50: 235 registered scripts plus
# their fixed local Python import/read helpers (including the three combined
# suites). Master e89c8f61 (#595) adds the frozen Stage A/B smoke/helper consumed
# by the existing fullrun_runtime_source_manifest smoke entrypoint below.
# Keep these mandatory independently of mutable Toolbox/runner rows;
# deleting a helper must not remove its required pin. This is a path inventory,
# not a claim of approved semantics or completed proof. Changes to the proof
# procedure require reviewing/updating its consumed inputs, like the Reader.
A6_FIXED_PROOF_PROGRAMS = (
    'aggressive/__init__.py',
    'aggressive/agg_config.py',
    'aggressive/data_alpaca.py',
    'aggressive/entry_precision.py',
    'aggressive/executor.py',
    'aggressive/exit_management.py',
    'aggressive/finnhub_cache_loader.py',
    'aggressive/finnhub_client.py',
    'aggressive/position_sizing.py',
    'aggressive/scanner.py',
    'aggressive/signals_technical.py',
    'aggressive/telegram_alert.py',
    'aggressive/universe.py',
    'mission_contract.py',
    'r1000_alphaops_reporting.py',
    'r1000_auto_learning_evidence.py',
    'r1000_auto_learning_policy.py',
    'r1000_bootstrap_ci.py',
    'r1000_candidate_lanes.py',
    'r1000_config.py',
    'r1000_crisis_governor.py',
    'r1000_data_collector.py',
    'r1000_features.py',
    'r1000_helpers.py',
    'r1000_layer4_swap.py',
    'r1000_legacy_input_guard.py',
    'r1000_long_crisis_liquidity.py',
    'r1000_main_v2.py',
    'r1000_market_leader_engine.py',
    'r1000_ml_predictor.py',
    'r1000_operator.py',
    'r1000_orchestrator.py',
    'r1000_paper_executor.py',
    'r1000_pattern_miner.py',
    'r1000_pipeline.py',
    'r1000_portfolio_state.py',
    'r1000_rebalance_advisor.py',
    'r1000_rebalance_advisor_v3.py',
    'r1000_rebalance_advisor_v4.py',
    'r1000_regime_data.py',
    'r1000_risk_sensing.py',
    'r1000_sidecar_promotion.py',
    'r1000_signals.py',
    'r1000_tactical_alpha.py',
    'r1000_tactical_backtest.py',
    'r1000_themes.py',
    'r1000_top30_institutional.py',
    'r1000_trade_journal.py',
    'research/evaluation_v2_admission.py',
    'research/investment_methodology_v1.py',
    'research/moat_quality_v2.py',
    'research/multi_asset_v1/__init__.py',
    'research/multi_asset_v1/contracts.py',
    'research/multi_asset_v1/decisions.py',
    'research/multi_asset_v1/fundamentals.py',
    'research/multi_asset_v1/prices.py',
    'research/multi_asset_v1/runtime.py',
    'research/multi_asset_v1/sources.py',
    'research/theme_etf_runtime_v1/__init__.py',
    'research/theme_etf_runtime_v1/runtime.py',
    'research/theme_etf_runtime_v1/strict.py',
    'run_local.py',
    'tests/__init__.py',
    'tests/a3_candidate_packet_v1_smoke.py',
    'tests/ab_result_verifier_smoke.py',
    'tests/account_evaluation_smoke.py',
    'tests/account_evaluation_window_gate_smoke.py',
    'tests/adr_candidate_scanner_smoke.py',
    'tests/adr_universe_apply_smoke.py',
    'tests/agent_board_smoke.py',
    'tests/agent_shared_lessons_contract_smoke.py',
    'tests/alpha_beta_attribution_smoke.py',
    'tests/alpha_selector_broker_grid_smoke.py',
    'tests/alphaops_vnext_policy_replay_smoke.py',
    'tests/api_credentials_check_smoke.py',
    'tests/audit_features.py',
    'tests/auto_learning_evidence_smoke.py',
    'tests/auto_learning_proposal_only_smoke.py',
    'tests/auto_learning_v2_smoke.py',
    'tests/auto_policy_challenger_smoke.py',
    'tests/baseline_lock_smoke.py',
    'tests/broker_cash_carry_smoke.py',
    'tests/broker_crisis_reentry_replay_smoke.py',
    'tests/broker_execution_policy_replay_smoke.py',
    'tests/broker_gap_attribution_smoke.py',
    'tests/broker_gate_contract_smoke.py',
    'tests/broker_ledger_correctness_smoke.py',
    'tests/broker_ledger_replay_smoke.py',
    'tests/broker_position_risk_grid_sweep_smoke.py',
    'tests/broker_position_risk_replay_smoke.py',
    'tests/bull_floor_overlay_smoke.py',
    'tests/cagr_walkforward_smoke.py',
    'tests/candidate_lanes_smoke.py',
    'tests/candidate_reassessment_bridge_smoke.py',
    'tests/candidate_reassessment_clock_smoke.py',
    'tests/candidate_reassessment_free_first_smoke.py',
    'tests/candidate_registry_v1_smoke.py',
    'tests/cash_contract_smoke.py',
    'tests/chameleon_library_semantic_boundary_smoke.py',
    'tests/chameleon_market_context_v2_library_smoke.py',
    'tests/clean7y_window_preflight_smoke.py',
    'tests/collect_earnings_estimates_smoke.py',
    'tests/conc_dropped_leader_rescue_screen_smoke.py',
    'tests/concentrated_broker_variant_review_smoke.py',
    'tests/concentrated_cap_replacement_audit_smoke.py',
    'tests/concentrated_score_sizing_broker_ab_smoke.py',
    'tests/concentrated_sizing_ab_screen_smoke.py',
    'tests/control_plane_agent_contract_smoke.py',
    'tests/cost_sensitivity_sidecar_smoke.py',
    'tests/crisis_paper_order_bridge_smoke.py',
    'tests/crisis_state_engine_smoke.py',
    'tests/cross_market_gold_set_v1_smoke.py',
    'tests/daily_crisis_monitor_long_crisis_smoke.py',
    'tests/daily_crisis_paper_actions_smoke.py',
    'tests/daily_market_close_gate_smoke.py',
    'tests/daily_market_snapshot_smoke.py',
    'tests/daily_simulated_fill_ledger_smoke.py',
    'tests/daily_user_current_contract_smoke.py',
    'tests/data_alpaca_adjustment_smoke.py',
    'tests/data_catalog_smoke.py',
    'tests/data_coverage_gate_smoke.py',
    'tests/data_freshness_contract_smoke.py',
    'tests/data_freshness_macro_snapshot_smoke.py',
    'tests/data_readiness_smoke.py',
    'tests/decision_cadence_review_smoke.py',
    'tests/direct_fullrun_guard_smoke.py',
    'tests/earnings_consensus_h1_smoke.py',
    'tests/earnings_estimate_archive_manifest_smoke.py',
    'tests/earnings_estimate_catchup_universe_smoke.py',
    'tests/earnings_estimate_incremental_universe_smoke.py',
    'tests/earnings_estimate_source_probe_smoke.py',
    'tests/earnings_estimate_workflow_rotation_smoke.py',
    'tests/eodhd_calendar_trends_library_smoke.py',
    'tests/era_aware_promotion_policy_smoke.py',
    'tests/era_aware_scoring_challenger_smoke.py',
    'tests/era_leadership_sidecar_smoke.py',
    'tests/estimate_confirm_selection_smoke.py',
    'tests/estimate_feed_backtest_neutrality_smoke.py',
    'tests/estimate_revision_features_smoke.py',
    'tests/etf_holding_event_builder_smoke.py',
    'tests/etf_holdings_overlay_smoke.py',
    'tests/etf_nport_history_smoke.py',
    'tests/evaluation_v2_admission_smoke.py',
    'tests/event_target_books_smoke.py',
    'tests/evidence_readiness_smoke.py',
    'tests/execution_cost_capacity_sidecar_smoke.py',
    'tests/execution_lag_review_smoke.py',
    'tests/fast_crash_env_override_smoke.py',
    'tests/fast_full_drift_audit_smoke.py',
    'tests/form4_transaction_event_builder_smoke.py',
    'tests/forward_estimate_universe_plan_smoke.py',
    'tests/forward_paper_price_universe_smoke.py',
    'tests/free_data_forward_paper_ledger_smoke.py',
    'tests/free_data_selection_overlay_smoke.py',
    'tests/free_market_context_library_smoke.py',
    'tests/frozen_stage_ab_fairness_smoke.py',
    'tests/fullrun_latest_cross_section_preflight_smoke.py',
    'tests/fullrun_runtime_source_manifest_smoke.py',
    'tests/fullrun_source_manifest_smoke.py',
    'tests/fusion_candidate_review_smoke.py',
    'tests/hold_duration_leak_screen_smoke.py',
    'tests/integrated_leader_crisis_replay_smoke.py',
    'tests/integrated_theme_leader_crisis_replay_smoke.py',
    'tests/investment_methodology_v1_smoke.py',
    'tests/is_attribution_smoke.py',
    'tests/label_availability_purge_smoke.py',
    'tests/leader_hysteresis_smoke.py',
    'tests/leader_lifecycle_audit_smoke.py',
    'tests/leadership_persistence_applied_screen_smoke.py',
    'tests/long_history_lake_smoke.py',
    'tests/macro_circuit_breaker_filter_smoke.py',
    'tests/macro_research_cycle_smoke.py',
    'tests/macro_technical_evidence_smoke.py',
    'tests/manual_foundation_smoke.py',
    'tests/market_leader_challenger_smoke.py',
    'tests/market_leader_engine_smoke.py',
    'tests/metric_hygiene_report_smoke.py',
    'tests/moat_quality_v2_smoke.py',
    'tests/nav_metrics_v2_smoke.py',
    'tests/neutral_regime_churn_filter_smoke.py',
    'tests/oos_lock_audit_smoke.py',
    'tests/oos_lock_smoke.py',
    'tests/operating_event_backtest_smoke.py',
    'tests/operating_target_books_smoke.py',
    'tests/patch_application_manifest_smoke.py',
    'tests/performance_ledger_smoke.py',
    'tests/pit_estimate_guidance_sample_request_smoke.py',
    'tests/pit_estimate_guidance_source_gate_smoke.py',
    'tests/pit_membership_audit_smoke.py',
    'tests/pit_membership_producer_smoke.py',
    'tests/pit_top_manager_follow_study_smoke.py',
    'tests/portfolio_system_guard_smoke.py',
    'tests/position_cleanup_review_smoke.py',
    'tests/position_risk_review_smoke.py',
    'tests/post_disclosure_alpha_candidates_smoke.py',
    'tests/post_disclosure_alpha_labeler_smoke.py',
    'tests/post_disclosure_alpha_pipeline_smoke.py',
    'tests/post_disclosure_overlay_challenger_smoke.py',
    'tests/post_disclosure_signal_learning_smoke.py',
    'tests/product_analytics_v1_smoke.py',
    'tests/public_market_quotes_smoke.py',
    'tests/public_portfolio_dashboard_smoke.py',
    'tests/public_project_results_smoke.py',
    'tests/regime_capacity_filter_smoke.py',
    'tests/replay_integrity_preflight_smoke.py',
    'tests/replay_price_cache_smoke.py',
    'tests/research_data_access_smoke.py',
    'tests/research_handoff_package_smoke.py',
    'tests/reserve_asset_policy_smoke.py',
    'tests/review_dispatcher_smoke.py',
    'tests/right_tail_drop_counterfactual_audit_smoke.py',
    'tests/right_tail_entry_signal_audit_smoke.py',
    'tests/run287_accepted_publication_manifest_smoke.py',
    'tests/run287_agent_github_operating_standard_smoke.py',
    'tests/run287_b002_fundamental_delta_smoke.py',
    'tests/run287_benchmark_event_sidecar_smoke.py',
    'tests/run287_candidate_gate_stability_smoke.py',
    'tests/run287_candidate_risk_watch_smoke.py',
    'tests/run287_catchup_drive_readiness_smoke.py',
    'tests/run287_catchup_price_capture_smoke.py',
    'tests/run287_catchup_price_evidence_smoke.py',
    'tests/run287_catchup_target_evidence_smoke.py',
    'tests/run287_chameleon_macro_inputs_smoke.py',
    'tests/run287_chameleon_macro_risk_smoke.py',
    'tests/run287_complete_current_cross_section_verifier_smoke.py',
    'tests/run287_crisis_policy_evaluation_smoke.py',
    'tests/run287_crisis_policy_smoke.py',
    'tests/run287_current_advisory_selector_smoke.py',
    'tests/run287_current_crisis_state_sidecar_smoke.py',
    'tests/run287_current_decision_frame_contract_smoke.py',
    'tests/run287_current_decision_score_only_smoke.py',
    'tests/run287_current_decision_score_stack_smoke.py',
    'tests/run287_current_selector_no_write_smoke.py',
    'tests/run287_daily_paper_bootstrap_smoke.py',
    'tests/run287_daily_research_monitor_smoke.py',
    'tests/run287_decision_observation_archive_smoke.py',
    'tests/run287_do_not_repeat_registry_smoke.py',
    'tests/run287_exact_packet_input_registry_smoke.py',
    'tests/run287_exact_packet_producer_smoke.py',
    'tests/run287_exact_packet_source_bundle_smoke.py',
    'tests/run287_exact_packet_upstream_smoke.py',
    'tests/run287_expected_return_challenger_smoke.py',
    'tests/run287_github_secret_scope_smoke.py',
    'tests/run287_hold_exit_evaluation_smoke.py',
    'tests/run287_hold_exit_policy_smoke.py',
    'tests/run287_holding_risk_watch_smoke.py',
    'tests/run287_macro_sidecar_smoke.py',
    'tests/run287_multiple_testing_gate_smoke.py',
    'tests/run287_nasdaq_zeeh_sample_smoke.py',
    'tests/run287_next_scheduled_artifact_gate_smoke.py',
    'tests/run287_next_single_ab_readiness_smoke.py',
    'tests/run287_ohlcv_location_timing_challenger_smoke.py',
    'tests/run287_ohlcv_location_timing_workflow_smoke.py',
    'tests/run287_ohlcv_pattern_memory_smoke.py',
    'tests/run287_operating_scorecard_smoke.py',
    'tests/run287_paper_immutable_head_selector_smoke.py',
    'tests/run287_paper_ledger_transaction_smoke.py',
    'tests/run287_paper_publication_recovery_smoke.py',
    'tests/run287_paper_snapshot_continuity_smoke.py',
    'tests/run287_promotion_gate_smoke.py',
    'tests/run287_recent_companyfacts_smoke.py',
    'tests/run287_recent_sec_delta_smoke.py',
    'tests/run287_repo_ci_artifact_hygiene_smoke.py',
    'tests/run287_reserve_asset_evaluation_smoke.py',
    'tests/run287_review_complete_gate_smoke.py',
    'tests/run287_risk_outcome_accepted_heads_smoke.py',
    'tests/run287_risk_outcome_archive_smoke.py',
    'tests/run287_risk_outcome_parent_preflight_smoke.py',
    'tests/run287_same_close_target_books_smoke.py',
    'tests/run287_scored_latest_refresh_smoke.py',
    'tests/run287_sector_leadership_challenger_smoke.py',
    'tests/run287_sector_leadership_workflow_smoke.py',
    'tests/run287_sector_rs_materialization_evaluation_smoke.py',
    'tests/run287_selector_benchmark_price_recovery_smoke.py',
    'tests/run287_system_foundation_review_smoke.py',
    'tests/run287_u0_experiment_audit_smoke.py',
    'tests/run287_u0_v2_github_census_smoke.py',
    'tests/run287_u0_v3_acceptance_smoke.py',
    'tests/run287_u0_v3_recovery_census_smoke.py',
    'tests/sec_13f_cusip_mapping_smoke.py',
    'tests/sec_13f_filing_freshness_smoke.py',
    'tests/sec_13f_parser_smoke.py',
    'tests/sec_13f_position_event_builder_smoke.py',
    'tests/sec_13f_publication_verification_smoke.py',
    'tests/sec_candidate_enrichment_smoke.py',
    'tests/sec_cik_schema_smoke.py',
    'tests/sec_evidence_learning_pipeline_smoke.py',
    'tests/sec_filing_quality_event_smoke.py',
    'tests/sec_form4_parser_smoke.py',
    'tests/sec_guidance_goldset_packet_smoke.py',
    'tests/sec_guidance_goldset_review_gate_smoke.py',
    'tests/sec_management_guidance_scout_smoke.py',
    'tests/sec_overlay_consistency_smoke.py',
    'tests/sec_pit_available_from_smoke.py',
    'tests/sec_submissions_collector_history_smoke.py',
    'tests/security_basis_registry_smoke.py',
    'tests/security_lifecycle_smoke.py',
    'tests/self_correction_queue_closure_smoke.py',
    'tests/self_correction_router_smoke.py',
    'tests/seven_year_lock_smoke.py',
    'tests/shakeout_disclosure_reversal_study_smoke.py',
    'tests/shakeout_guard_applied_screen_smoke.py',
    'tests/sidecar_promotion_bridge_smoke.py',
    'tests/sizing_signal_screen_smoke.py',
    'tests/smart_money_top30_smoke.py',
    'tests/smoke_test.py',
    'tests/strategy_logic_ledger_smoke.py',
    'tests/strengthened_gates_smoke.py',
    'tests/subdaily_exit_compare_smoke.py',
    'tests/subdaily_exit_grid_sweep_smoke.py',
    'tests/superperformance_trader_replay_smoke.py',
    'tests/system_acceptance_audit_smoke.py',
    'tests/system_state_materializer_smoke.py',
    'tests/target_book_drift_audit_smoke.py',
    'tests/ten_year_backtest_readiness_smoke.py',
    'tests/test_p0_3_authority_census.py',
    'tests/test_p0_4_artifact_inventory.py',
    'tests/theme_etf_source_bridge_smoke.py',
    'tests/top_manager_discovery_signals_smoke.py',
    'tests/trade_attribution_analysis_smoke.py',
    'tests/universe_health_audit_smoke.py',
    'tests/user_current_research_notice_smoke.py',
    'tests/weekly_evaluation_smoke.py',
    'tests/weekly_leader_target_books_smoke.py',
    'tests/workflow_artifact_smoke.py',
    'tools/aggregate_product_analytics.py',
    'tools/apply_adr_universe_update.py',
    'tools/archive_run287_decision_observation.py',
    'tools/archive_run287_ohlcv_pattern_memory.py',
    'tools/archive_target_snapshots.py',
    'tools/audit_data_readiness.py',
    'tools/audit_evidence_readiness.py',
    'tools/audit_pit_estimate_guidance_source.py',
    'tools/audit_run287_next_scheduled_artifact_gate.py',
    'tools/audit_run287_next_single_ab_readiness.py',
    'tools/audit_run287_u0_experiment_inventory.py',
    'tools/audit_sec_13f_filing_freshness.py',
    'tools/audit_target_book_drift.py',
    'tools/auto_learning_promote.py',
    'tools/auto_policy_challenger.py',
    'tools/bootstrap_run287_daily_paper_accounts.py',
    'tools/build_concentrated_trade_journal.py',
    'tools/build_crisis_governed_target_books.py',
    'tools/build_daily_market_snapshot.py',
    'tools/build_daily_user_current_contract.py',
    'tools/build_data_catalog.py',
    'tools/build_earnings_estimate_archive_manifest.py',
    'tools/build_etf_nport_history.py',
    'tools/build_event_target_books.py',
    'tools/build_explosive_pattern_db.py',
    'tools/build_forward_estimate_catchup_universe.py',
    'tools/build_forward_estimate_incremental_universe.py',
    'tools/build_forward_estimate_universe_plan.py',
    'tools/build_forward_paper_price_universe.py',
    'tools/build_fullrun_runtime_source_manifest.py',
    'tools/build_gdrive_sync_manifest.py',
    'tools/build_operating_target_books.py',
    'tools/build_p0_3_authority_census.py',
    'tools/build_p0_4_artifact_inventory.py',
    'tools/build_pit_estimate_guidance_sample_request.py',
    'tools/build_pit_membership_by_month.py',
    'tools/build_public_portfolio_dashboard.py',
    'tools/build_public_project_results.py',
    'tools/build_replay_price_cache.py',
    'tools/build_run287_accepted_publication_manifest.py',
    'tools/build_run287_b002_fundamental_delta.py',
    'tools/build_run287_benchmark_event_sidecar.py',
    'tools/build_run287_candidate_risk_watch.py',
    'tools/build_run287_catchup_price_capture.py',
    'tools/build_run287_catchup_price_evidence.py',
    'tools/build_run287_catchup_target_evidence.py',
    'tools/build_run287_chameleon_macro_inputs.py',
    'tools/build_run287_chameleon_macro_risk.py',
    'tools/build_run287_current_crisis_state_sidecar.py',
    'tools/build_run287_current_decision_frame.py',
    'tools/build_run287_exact_packet_input_registry.py',
    'tools/build_run287_exact_packet_source_bundle.py',
    'tools/build_run287_exact_static_archive.py',
    'tools/build_run287_feature_frame_pilot.py',
    'tools/build_run287_holding_risk_watch.py',
    'tools/build_run287_macro_sidecar.py',
    'tools/build_run287_ohlcv_location_timing_challenger.py',
    'tools/build_run287_operating_scorecard.py',
    'tools/build_run287_risk_outcome_legacy_migration.py',
    'tools/build_run287_risk_outcome_parent_anchor.py',
    'tools/build_run287_risk_outcome_parent_preflight.py',
    'tools/build_run287_same_close_target_books.py',
    'tools/build_run287_u0_v2_github_census.py',
    'tools/build_run287_u0_v3_acceptance.py',
    'tools/build_run287_u0_v3_recovery_census.py',
    'tools/build_sec_13f_cusip_ticker_map.py',
    'tools/build_sec_13f_manager_universe.py',
    'tools/build_sec_guidance_goldset_packet.py',
    'tools/build_security_basis_registry.py',
    'tools/build_top_manager_discovery_signals.py',
    'tools/build_weekly_leader_target_books.py',
    'tools/candidate_reassessment_bridge.py',
    'tools/chameleon_market_context_v2.py',
    'tools/check_10y_backtest_readiness.py',
    'tools/check_pr_review_complete.py',
    'tools/check_run287_artifact_hygiene.py',
    'tools/check_run287_catchup_drive_readiness.py',
    'tools/check_run287_do_not_repeat.py',
    'tools/check_run287_github_secret_scope.py',
    'tools/collect_alphavantage_listing_status.py',
    'tools/collect_earnings_estimates_finnhub.py',
    'tools/collect_fmp_earnings_calendar_history.py',
    'tools/collect_run287_recent_sec_delta.py',
    'tools/compare_adr_backtest.py',
    'tools/concentrated_score_sizing_reweight.py',
    'tools/configure_macro_research_drive.py',
    'tools/create_healthy_baseline_lock.py',
    'tools/create_run287_catchup_scope_attestation.py',
    'tools/crisis_state_engine.py',
    'tools/data_coverage_gate.py',
    'tools/earnings_consensus_h1.py',
    'tools/earnings_estimate_drive_generation.py',
    'tools/eodhd_calendar_trends.py',
    'tools/etf_leadership_snapshot.py',
    'tools/evaluate_run287_crisis_policy.py',
    'tools/evaluate_run287_hold_exit_replacement.py',
    'tools/evaluate_run287_reserve_asset_policy.py',
    'tools/evaluate_run287_sector_rs_materialization.py',
    'tools/evaluate_sec_guidance_goldset_reviews.py',
    'tools/execution_cost_model.py',
    'tools/explosive_mover_scan_daily.py',
    'tools/fetch_run287_recent_companyfacts.py',
    'tools/free_market_context.py',
    'tools/frozen_stage_ab_fairness.py',
    'tools/historical_replay_lib.py',
    'tools/long_history_lake.py',
    'tools/macro_daily_snapshot.py',
    'tools/macro_history_sources.py',
    'tools/macro_research_checkpoint.py',
    'tools/macro_research_cycle.py',
    'tools/macro_technical_study.py',
    'tools/manage_run287_risk_outcome_accepted_heads.py',
    'tools/manual_foundation.py',
    'tools/materialize_system_state.py',
    'tools/monthly_ic_monitor.py',
    'tools/nav_metrics_v2.py',
    'tools/package_research_handoff.py',
    'tools/prepare_run287_legacy_paper_migration.py',
    'tools/prepare_run287_paper_publication_recovery.py',
    'tools/probe_earnings_estimate_sources.py',
    'tools/probe_run287_nasdaq_zeeh_sample.py',
    'tools/recover_run287_selector_benchmark_price.py',
    'tools/refresh_companyfacts_bulk.py',
    'tools/refresh_cycle_play_universe.py',
    'tools/refresh_public_market_quotes.py',
    'tools/research_data_access.py',
    'tools/reserve_asset_policy.py',
    'tools/resolve_run287_risk_outcomes.py',
    'tools/restore_run287_exact_static_archive.py',
    'tools/run287_candidate_gate_stability_audit.py',
    'tools/run287_catchup_scope_consumption.py',
    'tools/run287_code_identity.py',
    'tools/run287_crisis_policy.py',
    'tools/run287_hold_exit_policy.py',
    'tools/run287_paper_ledger_integrity.py',
    'tools/run287_pinned_git_import.py',
    'tools/run287_promotion_gate.py',
    'tools/run287_research_report_html.py',
    'tools/run287_research_score_handoff.py',
    'tools/run_13f_position_event_builder.py',
    'tools/run_ab_result_verifier.py',
    'tools/run_account_evaluation.py',
    'tools/run_account_order_preview.py',
    'tools/run_adr_candidate_scanner.py',
    'tools/run_agent_board.py',
    'tools/run_alpha_beta_attribution.py',
    'tools/run_alpha_selector_broker_grid.py',
    'tools/run_alphaops_policy_fusion.py',
    'tools/run_alphaops_vnext_policy_replay.py',
    'tools/run_auto_learning_v2.py',
    'tools/run_autolearning_winner_challenger.py',
    'tools/run_broker_crisis_reentry_replay.py',
    'tools/run_broker_execution_policy_replay.py',
    'tools/run_broker_gap_attribution.py',
    'tools/run_broker_ledger_replay.py',
    'tools/run_broker_position_risk_grid_sweep.py',
    'tools/run_broker_position_risk_replay.py',
    'tools/run_broker_trade_journal.py',
    'tools/run_cagr_walkforward.py',
    'tools/run_cash_policy_attribution.py',
    'tools/run_cash_reentry_quality_audit.py',
    'tools/run_clean7y_window_preflight.py',
    'tools/run_conc_dropped_leader_rescue_screen.py',
    'tools/run_concentrated_broker_variant_review.py',
    'tools/run_concentrated_cap_replacement_audit.py',
    'tools/run_concentrated_score_sizing_broker_ab.py',
    'tools/run_concentrated_sizing_ab_screen.py',
    'tools/run_cost_sensitivity_sidecar.py',
    'tools/run_crisis_paper_order_bridge.py',
    'tools/run_crisis_reentry_replay.py',
    'tools/run_crisis_signal_builder.py',
    'tools/run_daily_crisis_monitor.py',
    'tools/run_daily_market_session_gate.py',
    'tools/run_daily_simulated_fill_ledger.py',
    'tools/run_data_freshness_contract.py',
    'tools/run_dataset_coverage_audit.py',
    'tools/run_decision_cadence_review.py',
    'tools/run_entry_exit_timing_audit.py',
    'tools/run_era_aware_scoring_challenger.py',
    'tools/run_era_leadership_sidecar.py',
    'tools/run_etf_holding_event_builder.py',
    'tools/run_etf_holdings_refresh.py',
    'tools/run_execution_cost_capacity_sidecar.py',
    'tools/run_execution_lag_review.py',
    'tools/run_fast_full_drift_audit.py',
    'tools/run_form4_transaction_event_builder.py',
    'tools/run_free_data_engine_validation.py',
    'tools/run_free_data_forward_paper_ledger.py',
    'tools/run_free_data_lake_bootstrap.py',
    'tools/run_free_data_selection_overlay.py',
    'tools/run_full_rebuild_sidecars.py',
    'tools/run_fullrun_latest_cross_section_preflight.py',
    'tools/run_fusion_candidate_review.py',
    'tools/run_governance_catalyst_report.py',
    'tools/run_hold_duration_leak_screen.py',
    'tools/run_integrated_leader_crisis_replay.py',
    'tools/run_integrated_theme_leader_crisis_replay.py',
    'tools/run_is_attribution.py',
    'tools/run_latest_price_date_audit.py',
    'tools/run_leader_drop_diagnostics_sidecar.py',
    'tools/run_leader_lifecycle_audit.py',
    'tools/run_leadership_persistence_applied_screen.py',
    'tools/run_lever_sweep.py',
    'tools/run_live_trading_risk_controls.py',
    'tools/run_live_trading_safety_audit.py',
    'tools/run_long_crisis_dataset_builder.py',
    'tools/run_long_crisis_signal_learning.py',
    'tools/run_long_crisis_threshold_search.py',
    'tools/run_macro_circuit_breaker_filter.py',
    'tools/run_macro_policy_engine.py',
    'tools/run_main_cash_drag_replay.py',
    'tools/run_market_leader_challenger.py',
    'tools/run_mdd_cash_overlay_research.py',
    'tools/run_metric_hygiene_report.py',
    'tools/run_monster_recommendation_bridge.py',
    'tools/run_multi_asset_leadership.py',
    'tools/run_neutral_regime_churn_filter.py',
    'tools/run_oos_lock_audit.py',
    'tools/run_operating_event_backtest.py',
    'tools/run_operating_snapshot.py',
    'tools/run_patch_application_manifest.py',
    'tools/run_performance_ledger.py',
    'tools/run_pit_membership_audit.py',
    'tools/run_pit_top_manager_follow_study.py',
    'tools/run_portfolio_goal_search.py',
    'tools/run_portfolio_system_guard.py',
    'tools/run_position_aware_risk_replay.py',
    'tools/run_position_cleanup_review.py',
    'tools/run_position_risk_review.py',
    'tools/run_position_risk_weekly_validation.py',
    'tools/run_post_disclosure_alpha_candidates.py',
    'tools/run_post_disclosure_alpha_labeler.py',
    'tools/run_post_disclosure_alpha_pipeline.py',
    'tools/run_post_disclosure_overlay_challenger.py',
    'tools/run_post_disclosure_signal_learning.py',
    'tools/run_pr_validation.py',
    'tools/run_regime_capacity_filter.py',
    'tools/run_replay_integrity_preflight.py',
    'tools/run_review_dispatcher.py',
    'tools/run_right_tail_drop_counterfactual_audit.py',
    'tools/run_right_tail_entry_signal_audit.py',
    'tools/run_run287_current_advisory_selector.py',
    'tools/run_run287_current_decision_score_only.py',
    'tools/run_run287_current_decision_score_stack_audit.py',
    'tools/run_run287_current_model_score_dryrun.py',
    'tools/run_run287_current_score_stack_audit.py',
    'tools/run_run287_current_selector_no_write.py',
    'tools/run_run287_daily_research_monitor.py',
    'tools/run_run287_exact_packet_producer.py',
    'tools/run_run287_exact_packet_upstream.py',
    'tools/run_run287_expected_return_challenger.py',
    'tools/run_run287_multiple_testing_gate.py',
    'tools/run_run287_promotion_gate.py',
    'tools/run_run287_scored_latest_refresh.py',
    'tools/run_run287_sector_leadership_challenger.py',
    'tools/run_sec_13f_parser.py',
    'tools/run_sec_enriched_candidate_replay.py',
    'tools/run_sec_evidence_learning_pipeline.py',
    'tools/run_sec_filing_quality_event.py',
    'tools/run_sec_form4_parser.py',
    'tools/run_sec_institutional_signals.py',
    'tools/run_sec_management_guidance_scout.py',
    'tools/run_sec_ownership_signals.py',
    'tools/run_sec_submissions_collector.py',
    'tools/run_selection_audit.py',
    'tools/run_selection_quality_report.py',
    'tools/run_self_correction_queue_closure.py',
    'tools/run_self_correction_router.py',
    'tools/run_shakeout_breakdown_study.py',
    'tools/run_shakeout_disclosure_reversal_study.py',
    'tools/run_shakeout_guard_applied_screen.py',
    'tools/run_sidecar_promotion_bridge.py',
    'tools/run_sizing_signal_screen.py',
    'tools/run_smart_money_top30.py',
    'tools/run_stock_selection_quality_audit.py',
    'tools/run_strategy_logic_ledger.py',
    'tools/run_style_regime_report.py',
    'tools/run_subdaily_exit_compare.py',
    'tools/run_subdaily_exit_grid_sweep.py',
    'tools/run_superperformance_trader_replay.py',
    'tools/run_system_acceptance_audit.py',
    'tools/run_theme_concentration_challenger.py',
    'tools/run_theme_leadership_tape.py',
    'tools/run_trade_attribution_analysis.py',
    'tools/run_universe_health_audit.py',
    'tools/run_user_current_report.py',
    'tools/run_user_portfolio_reports.py',
    'tools/run_weekly_evaluation.py',
    'tools/run_winner_lifecycle_reports.py',
    'tools/run_winner_onset_study.py',
    'tools/security_lifecycle.py',
    'tools/stage_run287_price_batch.py',
    'tools/sync_cloud_to_drive.py',
    'tools/theme_etf_source_bridge.py',
    'tools/theme_etf_upstream_admission.py',
    'tools/trade_insights.py',
    'tools/train_explosion_classifier.py',
    'tools/validate_daily_close_prices.py',
    'tools/validate_target_book_cash_contract.py',
    'tools/verify_fullrun_source_manifest.py',
    'tools/verify_run287_artifact_manifest.py',
    'tools/verify_run287_catchup_scope_attestation.py',
    'tools/verify_run287_complete_current_cross_section.py',
    'tools/verify_sec_13f_publication.py',
    'tools/write_run287_price_refresh_attempt.py',
)
CLASSES = {'REUSE_NOW', 'SELECTIVE_PORT', 'HISTORICAL_LESSON', 'DO_NOT_REPEAT', 'SUPERSEDED'}
TIERS = ('T0_READ', 'T1_COMPUTE', 'T2_PREPARE')
REVIEW_REPOSITORY = 'wscha231/r1000-quant-engine'
ContractError = board.ContractError


def path_at(root: Path, value: str) -> Path:
    """Repository-relative exact paths, never traversal/globs/symlink aliases."""
    if not isinstance(value, str) or not value or any(c in value for c in '\\:*?[]\x00'):
        raise ContractError('invalid_path')
    parts = value.split('/')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in parts):
        raise ContractError('invalid_path')
    root = root.resolve()
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ContractError('symlink_path')
    return path


def allowed_file_at(root: Path, value: str) -> Path:
    """Validate one explicit allowed file; existing directories are never file scope."""
    path = path_at(root, value)
    if path.exists() and path.is_dir():
        raise ContractError('allowed_file_is_directory')
    return path


def semantic_version(value: str) -> tuple[int, int, int]:
    if (not isinstance(value, str) or re.fullmatch(
            r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', value) is None):
        raise ContractError('invalid_playbook_version')
    return tuple(int(part) for part in value.split('.'))


def payload_hash(value: dict, hash_field: str) -> str:
    return board.digest({key: item for key, item in value.items() if key != hash_field})


def validate_shape(value: dict, *, scope: bool = False, root: Path = ROOT) -> None:
    schema = board.read_json(path_at(root, SCHEMA))
    # Resolve this one existing contract locally; never retrieve a schema URL.
    task_schema = board.read_json(path_at(root, 'research/control_plane/task_packet_schema.json'))
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(task_schema)
    except SchemaError as exc:
        raise ContractError('manual_schema_contract_invalid') from exc
    authority = task_schema['properties']['authority']
    schema['properties']['authority'] = authority
    schema['$defs']['scope']['properties']['authority'] = authority
    if scope:
        schema = {'$schema': schema['$schema'], '$defs': schema['$defs'], '$ref': '#/$defs/scope'}
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ContractError('manual_schema_contract_invalid') from exc
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise ContractError('manual_schema_invalid:' + '/'.join(map(str, errors[0].absolute_path)))


def load_playbook(playbook_id: str, root: Path = ROOT, *,
                  propose_successor: bool = False) -> tuple[dict, dict]:
    manifest = board.read_json(path_at(root, MANIFEST))
    if (not isinstance(manifest, dict)
            or manifest.get('schema_version') != 'manual-playbooks-v1'
            or set(manifest.get('current_versions', {})) != set(PLAYBOOK_IDS)):
        raise ContractError('manual_manifest_invalid')
    current = {}
    seen = set()
    rows_by_identity = {}
    for row in manifest.get('playbooks', []):
        identity = (row['playbook_id'], row['playbook_version'])
        semantic_version(row['playbook_version'])
        if identity in seen or row['playbook_id'] not in PLAYBOOK_IDS:
            raise ContractError('duplicate_or_unknown_playbook')
        seen.add(identity)
        rows_by_identity[identity] = row
        if row['playbook_sha256'] != payload_hash(row, 'playbook_sha256'):
            raise ContractError('playbook_hash_mismatch')
        if (row['owner'] != PLAYBOOK_IDS[row['playbook_id']]
                or board.digest(row['authority']) != board.digest(board.AUTHORITY)
                or row['authority_tier_max'] not in TIERS
                or row['mode'] != ('READ_ONLY' if row['owner'] == 'A6' else 'PROPOSAL_ONLY')):
            raise ContractError('playbook_authority')
        if (not all(isinstance(row.get(k), dict) and row[k] for k in ('process', 'proof', 'learning'))
                or not isinstance(row.get('toolbox_refs'), list) or not row['toolbox_refs']):
            raise ContractError('manual_layers_missing')
        if row['status'] == 'CURRENT':
            for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                 ('proof', 'checks'), ('learning', 'steps')):
                instructions = row[layer].get(field)
                if (not isinstance(instructions, list) or not instructions
                        or any(not isinstance(item, str) or not item.strip()
                               for item in instructions)):
                    reason = ('manual_stop_condition_invalid' if field == 'stop_condition'
                              else 'manual_instructions_invalid:' + layer + '.' + field)
                    raise ContractError(reason)
            if row['playbook_id'] in current:
                raise ContractError('multiple_current_playbooks')
            current[row['playbook_id']] = row
    if set(current) != set(PLAYBOOK_IDS):
        raise ContractError('missing_current_playbook')
    for key, row in current.items():
        if row['playbook_version'] != manifest['current_versions'][key]:
            raise ContractError('stale_current_version')
        semantic_version(manifest['current_versions'][key])
        history = [version for book_id, version in seen
                   if book_id == key and version != row['playbook_version']]
        if history and row.get('supersedes') is None:
            raise ContractError('missing_playbook_predecessor')
        if row.get('supersedes') is not None:
            previous = (key, row['supersedes'])
            if previous not in seen or previous == (key, row['playbook_version']):
                raise ContractError('invalid_supersedes')
            predecessor = rows_by_identity[previous]
            if predecessor.get('status') != 'SUPERSEDED':
                raise ContractError('predecessor_not_superseded')
            latest = max(history, key=semantic_version)
            if semantic_version(row['playbook_version']) <= semantic_version(latest):
                raise ContractError('playbook_version_not_increasing')
            if row['supersedes'] != latest:
                raise ContractError('playbook_predecessor_not_latest')
    for identity, reviewed_hash in VERSION_ANCHOR_CONTENT.items():
        anchor = rows_by_identity.get(identity)
        if anchor is None:
            raise ContractError('missing_reviewed_playbook_anchor')
        if board.digest({k: v for k, v in anchor.items()
                         if k not in ('status', 'playbook_sha256')}) != reviewed_hash:
            raise ContractError('reviewed_playbook_content_changed')
    for key, version in VERSION_ANCHOR:
        if semantic_version(current[key]['playbook_version']) < semantic_version(version):
            raise ContractError('playbook_version_not_increasing')
        # Retain a coherent chain all the way to the reviewed initial version,
        # including intermediate SUPERSEDED rows, rather than only the last edge.
        for (book_id, historical_version), row in rows_by_identity.items():
            if book_id != key or semantic_version(historical_version) <= semantic_version(version):
                continue
            older = [v for b, v in seen if b == key
                     and semantic_version(v) < semantic_version(historical_version)]
            predecessor = max(older, key=semantic_version)
            if (row.get('supersedes') != predecessor
                    or rows_by_identity[(key, predecessor)].get('status') != 'SUPERSEDED'):
                raise ContractError('reviewed_playbook_lineage_invalid')
    for identity, row in rows_by_identity.items():
        if identity not in VERSION_ANCHOR_CONTENT:
            # Retaining a predecessor asserts adoption. An unreviewed row may
            # only be the sole current version in an explicit successor proposal.
            if row['status'] != 'CURRENT':
                raise ContractError('unreviewed_retained_playbook_version')
            if not propose_successor:
                raise ContractError('unreviewed_playbook_version')
            if row['playbook_id'] != playbook_id:
                raise ContractError('unselected_unreviewed_playbook_version')
    if playbook_id not in current:
        raise ContractError('unknown_playbook')
    return manifest, current[playbook_id]


def load_do_not_repeat_registry(root: Path = ROOT) -> dict:
    registry = board.read_json(path_at(root, DNR))
    if not isinstance(registry, dict):
        raise ContractError('do_not_repeat_registry_invalid')
    if registry.get('match_fields') != ['signal', 'mechanism', 'book', 'window']:
        raise ContractError('do_not_repeat_match_fields_not_canonical')
    try:
        validated_do_not_repeat_entries(registry)
    except ValueError as exc:
        raise ContractError('do_not_repeat_registry_invalid:' + str(exc)) from exc
    # Registry identities/descriptors are JSON text, like candidate identities;
    # the census validator's str() compatibility must not admit coerced objects.
    if any(not isinstance(item[field], str) for item in registry['entries']
           for field in ('id', 'status', 'signal', 'mechanism', 'book', 'window')):
        raise ContractError('do_not_repeat_registry_invalid:nontext_entry_field')
    policy = registry.get('reuse_policy') or {}
    if not isinstance(policy, dict):
        raise ContractError('do_not_repeat_threshold_invalid')
    threshold = policy.get('minimum_component_coverage_increase_pp', 5.0)
    try:
        valid_threshold = (type(threshold) in (int, float)
                           and math.isfinite(threshold) and threshold >= 0)
    except (OverflowError, ValueError):
        valid_threshold = False
    if not valid_threshold:
        raise ContractError('do_not_repeat_threshold_invalid')
    return registry


def catalog_timestamp(value, reason: str) -> datetime:
    # Check the original clock/offset before datetime can normalize it.
    if (not isinstance(value, str) or re.fullmatch(
            r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}:[0-9]{2}'
            r'(?:[.,][0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])',
            value) is None):
        raise ContractError(reason)
    try:
        return board.timestamp(value)
    except (ContractError, ValueError, TypeError, AttributeError, OverflowError) as exc:
        raise ContractError(reason) from exc


def load_catalog(root: Path = ROOT) -> dict:
    value = board.read_json(path_at(root, CATALOG))
    if (not isinstance(value, dict)
            or value.get('schema_version') != 'pr-reuse-catalog-v1'
            or value.get('do_not_repeat_registry') != DNR
            or value.get('lessons_ledger') != 'docs/AGENT_SHARED_LESSONS_LEDGER.md'):
        raise ContractError('catalog_contract')
    entries = value.get('entries')
    if not isinstance(entries, list):
        raise ContractError('catalog_entries')
    registry = load_do_not_repeat_registry(root)
    indexed = {str(item['id']).strip(): item for item in registry['entries']}
    seen = set()
    for row in entries:
        if not isinstance(row, dict):
            raise ContractError('catalog_entry_shape')
        entry_id, classification = row.get('entry_id'), row.get('classification')
        if not isinstance(entry_id, str) or not entry_id or entry_id in seen or classification not in CLASSES:
            raise ContractError('catalog_duplicate_or_classification')
        seen.add(entry_id)

        catalog_timestamp(row.get('verified_at'), 'catalog_verified_at_invalid')
        master = row.get('last_verified_master')
        if not isinstance(master, str) or re.fullmatch('[0-9a-f]{40}', master) is None:
            raise ContractError('catalog_last_verified_master_invalid')

        has_successor = row.get('superseded_by') is not None
        if (classification == 'SUPERSEDED') != has_successor:
            raise ContractError('catalog_supersedes_invariant')

        expiry = row.get('expiry')
        if expiry is not None:
            expiry_at = catalog_timestamp(expiry, 'catalog_expiry_invalid')
            if classification == 'REUSE_NOW' and expiry_at <= datetime.now(timezone.utc):
                raise ContractError('catalog_reuse_expired')

        source_kind = row.get('source_kind')
        metadata, heads = row.get('source_metadata'), row.get('source_heads')
        if (source_kind not in {'PR', 'ISSUE'} or not isinstance(metadata, dict)
                or not metadata or not isinstance(heads, dict)):
            raise ContractError('catalog_source_identity')
        for ref, item in metadata.items():
            if (not isinstance(ref, str) or re.fullmatch(r'#\d+', ref) is None
                    or not isinstance(item, dict) or item.get('kind') != source_kind):
                raise ContractError('catalog_source_identity')
        if source_kind == 'ISSUE':
            if heads:
                raise ContractError('catalog_issue_has_source_head')
        else:
            if set(heads) != set(metadata):
                raise ContractError('catalog_pr_head_identity')
            if any(not isinstance(sha, str) or re.fullmatch('[0-9a-f]{40}', sha) is None
                   for sha in heads.values()):
                raise ContractError('catalog_pr_head_identity')

        for field in ('current_equivalent', 'toolbox_refs'):
            paths = row.get(field)
            if (not isinstance(paths, list) or not all(isinstance(item, str) and item for item in paths)
                    or len(set(paths)) != len(paths)):
                raise ContractError('catalog_path_set')
            for item in paths:
                path_at(root, item)

        dependencies = row.get('dependency_hashes')
        if not isinstance(dependencies, dict):
            raise ContractError('catalog_dependency_hash')
        for path, sha in dependencies.items():
            path_at(root, path)
            if not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None:
                raise ContractError('catalog_dependency_hash')
        if classification == 'REUSE_NOW':
            consumed = set(row['current_equivalent']) | set(row['toolbox_refs'])
            if not consumed or not consumed.issubset(dependencies):
                raise ContractError('catalog_unpinned_reuse_path')

        refs = row.get('do_not_repeat_refs')
        if (not isinstance(refs, list)
                or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
                or len(set(refs)) != len(refs)):
            raise ContractError('do_not_repeat_refs_invalid')
        if any(ref not in indexed for ref in refs):
            raise ContractError('do_not_repeat_ref_missing')
        if classification == 'DO_NOT_REPEAT' and not any(indexed[ref]['blocked_reuse'] is True for ref in refs):
            raise ContractError('do_not_repeat_unbound')

    for row in entries:
        if row.get('superseded_by') and (row['superseded_by'] not in seen or row['superseded_by'] == row['entry_id']):
            raise ContractError('catalog_invalid_supersedes')
    return value


def lookup_reuse(entry_id: str, root: Path = ROOT) -> dict:
    catalog = load_catalog(root)
    matches = [row for row in catalog['entries'] if row['entry_id'] == entry_id]
    if len(matches) != 1:
        raise ContractError('catalog_entry_unknown')
    row = matches[0]
    if row['classification'] == 'SUPERSEDED' or row.get('superseded_by') is not None:
        raise ContractError('catalog_superseded')
    registry = load_do_not_repeat_registry(root)
    indexed = {str(item['id']).strip(): item for item in registry['entries']}
    blocked = []
    for ref in row['do_not_repeat_refs']:
        if ref not in indexed:
            raise ContractError('do_not_repeat_ref_missing')
        if indexed[ref].get('blocked_reuse') is True:
            blocked.append(ref)
    if row['classification'] == 'DO_NOT_REPEAT' and not blocked:
        raise ContractError('do_not_repeat_unbound')
    for path, sha in row['dependency_hashes'].items():
        if board.file_hash(path_at(root, path)) != sha:
            raise ContractError('catalog_dependency_changed:' + path)
    return {'entry': row, 'allowed': row['classification'] == 'REUSE_NOW' and not blocked,
            'blocked_registry_ids': blocked, 'economic_authority': False}


def required_dependencies(playbook_id: str, root: Path = ROOT, *,
                          propose_successor: bool = False) -> list[str]:
    manifest, playbook = load_playbook(playbook_id, root, propose_successor=propose_successor)
    reader = A1_READER_DEPENDENCIES if playbook_id == 'A1_SOURCE_ADMISSION_REFRESH' else []
    proofs = list(A6_FIXED_PROOF_PROGRAMS) if playbook_id == 'A6_INDEPENDENT_QA' else []
    return sorted(set(OPERATING_CONTRACTS + BOARD_INPUT_DEPENDENCIES + reader + proofs + manifest['policy_refs'] + playbook['toolbox_refs'] + [
        MANIFEST, SCHEMA, CATALOG, DNR,
        'tools/manual_foundation.py', 'tools/run_agent_board.py',
        'tools/check_run287_do_not_repeat.py',
        'tools/build_run287_u0_v2_github_census.py',
        'research/control_plane/agent_contracts_v2.yaml',
        'research/control_plane/task_packet_schema.json']))


def validate_packet(packet: dict, scope: dict, *, expected_base: str,
                    expected_review_head: str | None = None, root: Path = ROOT,
                    propose_successor: bool = False) -> dict:
    """Scope/base come from the independently verified task, never from packet claims.

    Consistent JSON/hash proves pinning, not human approval or completed work.
    """
    validate_shape(packet, root=root)
    validate_shape(scope, scope=True, root=root)
    if not re.fullmatch('[0-9a-f]{40}', expected_base):
        raise ContractError('expected_base_invalid')
    if packet['base_sha'] != expected_base or scope['base_sha'] != expected_base:
        raise ContractError('wrong_base')
    manifest, playbook = load_playbook(packet['playbook_id'], root,
                                      propose_successor=propose_successor)
    is_a6 = playbook['owner'] == 'A6'
    if is_a6:
        if expected_review_head is None:
            raise ContractError('expected_review_head_required')
        if re.fullmatch('[0-9a-f]{40}', expected_review_head) is None:
            raise ContractError('expected_review_head_invalid')
        if packet['review_identity'] != scope['review_identity'] or packet['review_identity'] is None:
            raise ContractError('wrong_review_identity')
        if packet['review_identity']['head_sha'] != expected_review_head:
            raise ContractError('stale_review_head')
    elif packet['review_identity'] is not None or scope['review_identity'] is not None:
        raise ContractError('unexpected_review_identity')
    if (packet['playbook_version'] != playbook['playbook_version']
            or packet['playbook_sha256'] != playbook['playbook_sha256']):
        raise ContractError('stale_playbook')
    if packet['packet_sha256'] != payload_hash(packet, 'packet_sha256'):
        raise ContractError('packet_hash_mismatch')
    if packet['owner'] != playbook['owner'] or packet['owner'] != scope['owner']:
        raise ContractError('wrong_owner')
    if packet['mode'] != playbook['mode']:
        raise ContractError('wrong_mode')
    for authority in (packet['authority'], scope['authority']):
        if board.digest(authority) != board.digest(board.AUTHORITY):
            raise ContractError('authority_escalation')
    if TIERS.index(packet['authority_tier']) > min(TIERS.index(scope['authority_tier']), TIERS.index(playbook['authority_tier_max'])):
        raise ContractError('authority_tier_escalation')
    if packet['dependencies'] != scope['dependencies']:
        raise ContractError('wrong_dependency')
    if not set(required_dependencies(packet['playbook_id'], root,
                                    propose_successor=propose_successor)).issubset(packet['dependencies']):
        raise ContractError('missing_dependency')
    for path, sha in packet['dependencies'].items():
        if board.file_hash(path_at(root, path)) != sha:
            raise ContractError('dependency_bytes_changed:' + path)
    for path in scope['allowed_files'] + packet['allowed_files']:
        allowed_file_at(root, path)
    if not set(packet['allowed_files']).issubset(scope['allowed_files']):
        raise ContractError('file_scope_escalation')
    if packet['owner'] == 'A6' and packet['allowed_files']:
        raise ContractError('qa_source_write')
    if (packet['toolbox_refs'] != playbook['toolbox_refs']
            or packet['proof_set'] != playbook['proof_set']
            or not set(playbook['process']['stop_condition']).issubset(packet['stop_condition'])):
        raise ContractError('manual_contract_changed')
    load_catalog(root)
    reuse = [lookup_reuse(key, root) for key in packet['reuse_entries']]
    if any(not row['allowed'] for row in reuse):
        raise ContractError('catalog_reuse_not_allowed')
    if 'do_not_repeat_candidate' in packet:
        candidate = packet['do_not_repeat_candidate']
        if any(not isinstance(candidate.get(field), str) or not normalize(candidate[field])
               for field in ('signal', 'mechanism', 'book', 'window')):
            raise ContractError('do_not_repeat_identity_invalid')
        registry = load_do_not_repeat_registry(root)
        coverage = candidate.get('component_coverage_increase_pp', 0.0)
        try:
            valid_coverage = type(coverage) in (int, float) and math.isfinite(coverage)
        except (OverflowError, ValueError):
            valid_coverage = False
        if not valid_coverage:
            raise ContractError('do_not_repeat_coverage_invalid')
        result = evaluate_candidate(registry, **candidate)
        if not result['allowed']:
            raise ContractError('BLOCKED_DO_NOT_REPEAT')
    proposals = ({playbook['playbook_id']: playbook['playbook_version']}
                 if (playbook['playbook_id'], playbook['playbook_version']) not in VERSION_ANCHOR_CONTENT
                 else {})
    result = {'schema_version': 'manual-packet-preflight-v1',
            'status': 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY' if proposals else 'VALIDATED_PREPARE_ONLY',
            'task_key': packet['task_key'], 'packet_sha256': packet['packet_sha256'],
            'playbook_id': packet['playbook_id'], 'playbook_version': packet['playbook_version'],
            'playbook_sha256': packet['playbook_sha256'], 'base_sha': expected_base,
            'review_identity': copy.deepcopy(packet['review_identity']),
            'dependency_sha256': board.digest(packet['dependencies']),
            'proof_results': {key: 'NOT_RUN' for key in packet['proof_set']},
            'output_receipt': copy.deepcopy(packet['output_receipt']),
            'authority': copy.deepcopy(board.AUTHORITY), 'worker_invoked': False,
            'completed_task': False, 'economic_authority': False}
    if proposals:
        result['proposed_playbook_versions'] = proposals
        result['adoption_requires_independent_anchor_review'] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--scope', type=Path, required=True, help='Independently verified task scope; not approval authentication')
    parser.add_argument('--expected-base', required=True, help='Independently verified live master SHA')
    parser.add_argument('--expected-review-head', help='Independently verified exact implementation PR HEAD for A6')
    parser.add_argument('--propose-successor', action='store_true',
                        help='Prepare an unadopted versioned successor; adoption requires a separately reviewed content anchor')
    args = parser.parse_args()
    try:
        result = validate_packet(board.read_json(args.packet), board.read_json(args.scope),
                                 expected_base=args.expected_base,
                                 expected_review_head=args.expected_review_head,
                                 propose_successor=args.propose_successor)
    except (ContractError, OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        print(json.dumps({'status': 'BLOCKED_INPUT', 'reason': str(exc), 'worker_invoked': False}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
