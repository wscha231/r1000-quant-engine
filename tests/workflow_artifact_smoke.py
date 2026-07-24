#!/usr/bin/env python3
"""Static checks for full rebuild artifact/export hygiene."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"
REPLAY_WORKFLOW = ROOT / ".github" / "workflows" / "alphaops_replay_sidecars_manual.yml"
FREE_DATA_WORKFLOW = ROOT / ".github" / "workflows" / "free_data_lake_bootstrap.yml"
FREE_DATA_DAILY_WORKFLOW = ROOT / ".github" / "workflows" / "free_data_daily_update.yml"
DATA_PREFLIGHT_WORKFLOW = ROOT / ".github" / "workflows" / "data_readiness_preflight.yml"
DAILY_OPERATING_WORKFLOW = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages_deploy.yml"
PR_VALIDATION_WORKFLOW = ROOT / ".github" / "workflows" / "pr_validation.yml"
PORTFOLIO_GUARD_WORKFLOW = ROOT / ".github" / "workflows" / "portfolio_system_guard.yml"
PIPELINE = ROOT / "r1000_pipeline.py"

MONTHLY_BOOK_TOKENS = [
    "outputs/reports/main_monthly_weights.csv",
    "outputs/reports/tactical_monthly_weights.csv",
    "outputs/reports/alpha_sprint_monthly_weights.csv",
    "outputs/reports/regime_by_month.csv",
    "outputs/reports/sleeve_returns_by_month.csv",
    "outputs/reports/candidate_replay_book.csv",
    "outputs/reports/concentrated_strategy_monthly.csv",
    "outputs/reports/concentrated_strategy_holdings.csv",
    "outputs/reports/operating_*_target_book.csv",
    "outputs/reports/operating_target_books_*",
    "outputs/target_snapshots/",
    "outputs/data_readiness/",
    "outputs/universe_health/",
    "outputs/reports/leader_drop_diagnostics_*.csv",
    "outputs/reports/leader_drop_diagnostics_summary.json",
    "outputs/reports/leader_drop_diagnostics_report.md",
    "outputs/reports/dataset_coverage_audit.*",
]


def test_workflow_yaml_files_parse() -> None:
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception:
        return
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise AssertionError(f"{path.name} is not valid YAML: {exc}") from exc


def test_pr_workflows_sparse_checkout_only_required_rebuild_data() -> None:
    required_paths = [
        ".github",
        "aggressive",
        "auto_learning_v2",
        "backtest_results",
        "data_static",
        "docs",
        "outputs",
        "reports",
        "research",
        "tests",
        "tools",
    ]
    for workflow in (PR_VALIDATION_WORKFLOW, PORTFOLIO_GUARD_WORKFLOW):
        text = workflow.read_text(encoding="utf-8")
        assert "sparse-checkout: |" in text, workflow.name
        assert "sparse-checkout-cone-mode: true" in text, workflow.name
        for path in required_paths:
            assert f"            {path}\n" in text, f"{workflow.name}: {path}"
        sparse_block = text.split("sparse-checkout: |", 1)[1].split(
            "sparse-checkout-cone-mode:", 1
        )[0]
        assert "cloud_results/" not in sparse_block
        assert "tests" in sparse_block


def test_pr_validation_does_not_duplicate_same_sha_push_and_pr_jobs() -> None:
    text = PR_VALIDATION_WORKFLOW.read_text(encoding="utf-8")
    trigger_block = text.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "pull_request:" in trigger_block
    assert "workflow_dispatch:" in trigger_block
    assert "push:" not in trigger_block
    assert "check_run287_artifact_hygiene.py" in text


def test_portfolio_guard_requires_checksum_locked_fixture() -> None:
    text = PORTFOLIO_GUARD_WORKFLOW.read_text(encoding="utf-8")
    assert 'default: "tests/fixtures/run287_canonical_baseline"' in text
    assert "verify_run287_artifact_manifest.py" in text
    assert "RUN287_LATEST_RUN" in text
    assert "UNSUPPORTED_BASELINE_PATH" in (
        ROOT / "tools" / "verify_run287_artifact_manifest.py"
    ).read_text(encoding="utf-8")


def test_workflow_keeps_monthly_books() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in MONTHLY_BOOK_TOKENS:
        assert token in text, token
    assert "outputs/equity_curve.csv" in text
    for token in (
        "outputs/main_v2_backtest/",
        "outputs/concentrated_policy_replay/",
        "outputs/target_snapshots/",
        "outputs/data_readiness/",
        "outputs/universe_health/",
        "outputs/data_freshness_contract/",
        "outputs/concentrated_trade_journal/",
        "outputs/alpha_sprint_backtest/",
        "outputs/position_aware_risk_replay/",
        "outputs/position_risk_weekly_validation/",
        "outputs/broker_replay/",
        "outputs/legacy_monthly_broker_replay/",
        "outputs/event_target_books/",
        "outputs/event_broker_replay/",
        "outputs/weekly_leader_snapshots/",
        "outputs/weekly_leader_broker_replay/",
        "outputs/cost_sensitivity/",
        "outputs/trade_attribution/",
        "copy_dir_clean outputs/trade_attribution",
        "outputs/broker_position_risk_replay/",
        "outputs/broker_position_risk_grid_wide_trailing/",
        "outputs/broker_parabolic_risk_replay/",
        "outputs/broker_execution_policy_replay/",
        "outputs/mdd_cash_overlay_research/",
        "outputs/operating_event_backtest/",
        "outputs/broker_gap_attribution/",
        "outputs/broker_trade_journal/",
        "outputs/account_ledger_preview/",
        "outputs/live_trading_safety/",
        "outputs/live_trading_risk_controls/",
        "outputs/monster_recommendations/",
        "outputs/operating_snapshot/",
        "outputs/user_portfolio_reports/",
        "outputs/portfolio_system_guard/",
        "outputs/system_acceptance_audit/",
        "outputs/review_dispatcher/",
        "outputs/review_dispatcher_self_correction/",
        "outputs/self_correction_queue/",
        "outputs/ab_result_verifier/",
        "outputs/adr_candidates/",
        "outputs/account_evaluation/",
        "outputs/oos_lock/",
        "outputs/eight_year_backtest_readiness/",
        "outputs/era_aware_scoring_challenger/",
        "outputs/metric_hygiene/",
        "outputs/governance_catalyst/",
        "outputs/style_regime_report/",
        "outputs/macro_policy_engine/",
        "outputs/cash_policy/",
        "outputs/stock_selection_quality/",
        "outputs/entry_exit_timing_audit/",
        "outputs/cash_reentry_quality/",
        "outputs/data_freshness_contract/",
        "outputs/alpha_plane_measurement_status.json",
        "outputs/alpha_beta_attribution/",
        "outputs/fusion_candidate_review/",
        "outputs/cagr_walkforward/",
        "outputs/daily_market_snapshot/",
        "outputs/full_rebuild_logs/alpha_beta_attribution.log",
        "outputs/full_rebuild_logs/fusion_candidate_review.log",
        "outputs/full_rebuild_logs/cagr_walkforward.log",
        "outputs/full_rebuild_logs/daily_market_snapshot.log",
        "copy_dir_clean outputs/stock_selection_quality",
        "copy_dir_clean outputs/entry_exit_timing_audit",
        "copy_dir_clean outputs/cash_reentry_quality",
        "copy_dir_clean outputs/data_freshness_contract",
        'cp outputs/alpha_plane_measurement_status.json "$DEST/"',
        "outputs/main_cash_drag_replay/",
        "outputs/crisis_reentry_replay/",
        "outputs/broker_crisis_reentry_replay/",
        "outputs/monster_lifecycle_replay/",
        "outputs/lifecycle_review_overlay_main/",
        "outputs/monster_lifecycle_review_main/",
        "outputs/monster_lifecycle_review_concentrated/",
        "outputs/historical_trade_journey/",
        "outputs/selection_audit/",
        "outputs/eight_year_backtest_readiness/",
        "outputs/era_aware_scoring_challenger/",
        "outputs/ten_year_backtest_readiness/",
        "outputs/weekly_evaluation/",
        "outputs/theme_leadership_tape/",
        "outputs/theme_concentration_challenger/",
        "outputs/baseline_lock/",
        "outputs/sec_enriched_candidate_replay/",
        "outputs/market_leader_challenger/",
        "outputs/superperformance_trader_replay/",
        "outputs/integrated_theme_leader_crisis_replay/",
        "outputs/strategy_logic_ledger/",
        "outputs/shadow_operating/",
        "outputs/promotion_review/",
        "outputs/promotion_review/era_aware_approved_target_policy_candidate.json",
        "outputs/decision_cadence/",
        "outputs/patch_application_manifest.json",
        "outputs/replay_integrity/patch_application_manifest.json",
        "outputs/auto_learning_v2/",
        "outputs/winner_lifecycle/",
        "outputs/winner_onset_study/",
        "outputs/shakeout_breakdown_study/",
        "outputs/autolearning_winner_challenger/",
        "outputs/policy_fusion/",
    ):
        assert token in text, token


def test_operating_minimal_artifact_is_phase_g_replay_ready() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "name: user-operating-minimal-${{ inputs.universe_mode }}-${{ github.run_id }}",
        "outputs/backtest_metrics.json",
        "outputs/concentrated_backtest_metrics.json",
        "outputs/portfolio_latest.csv",
        "outputs/concentrated_portfolio_latest.csv",
        "outputs/scored_latest.csv",
        "outputs/reports/main_monthly_weights.csv",
        "outputs/reports/concentrated_strategy_holdings.csv",
        "outputs/reports/regime_by_month.csv",
        "outputs/reports/operating_*_target_book.csv",
        "outputs/reports/operating_target_books_*",
        "outputs/reports/candidate_replay_book.csv",
        "outputs/reports/dataset_coverage_audit.*",
        "cache_prices/replay_price_cache_manifest.json",
        "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
        "outputs/sec_enriched_candidate_replay/summary.json",
        "outputs/sec_enriched_candidate_replay/report.md",
        "outputs/data_readiness/",
        "outputs/universe_health/",
        "outputs/metric_hygiene/",
        "outputs/portfolio_system_guard/",
        'cp outputs/backtest_metrics.json "$DEST/"',
        "outputs/broker_replay/main/trades.csv",
        "outputs/broker_replay/main/cash_ledger.csv",
        "outputs/broker_replay/main/equity_curve.csv",
        "outputs/broker_replay/concentrated/trades.csv",
        'for file in metrics.json account_state_latest.json positions_latest.csv trades.csv cash_ledger.csv equity_curve.csv target_vs_actual_weights.csv; do',
        'cp outputs/reports/main_monthly_weights.csv "$DEST/reports/"',
        'cp outputs/reports/regime_by_month.csv "$DEST/reports/"',
        'cp outputs/reports/dataset_coverage_audit.* "$DEST/reports/"',
        'cp cache_prices/replay_price_cache_manifest.json "$DEST/manifests/"',
        'copy_dir_clean outputs/data_readiness "$DEST/data_readiness"',
        'copy_dir_clean outputs/universe_health "$DEST/universe_health"',
        'copy_dir_clean outputs/sec_enriched_candidate_replay "$DEST/sec_enriched_candidate_replay"',
        "--target outputs/reports/operating_main_target_book.csv",
        "--target outputs/reports/operating_concentrated_target_book.csv",
    ]:
        assert token in text, token


def test_official_artifact_keeps_market_leader_replay_source() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "name: official-broker-ledger-${{ inputs.universe_mode }}-${{ github.run_id }}",
        "outputs/reports/candidate_replay_book.csv",
        "cache_prices/replay_price_cache_manifest.json",
        "outputs/sec_enriched_candidate_replay/",
        "outputs/integrated_theme_leader_crisis_replay/",
        "outputs/strategy_logic_ledger/",
        "outputs/patch_application_manifest.json",
        "outputs/replay_integrity/patch_application_manifest.json",
        'cp outputs/reports/candidate_replay_book.csv "$DEST/reports/"',
    ]:
        assert token in text, token


def test_cloud_results_copy_is_not_nested() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "copy_dir_clean()" in text
    bad_tokens = [
        'cp -r outputs/orchestrator "$DEST/orchestrator"',
        'cp -r outputs/trade_journal "$DEST/trade_journal"',
        'cp -r outputs/concentrated_trade_journal "$DEST/concentrated_trade_journal"',
        'cp -r outputs/auto_learning "$DEST/auto_learning"',
        'cp -r outputs/orchestrator_replay "$DEST/orchestrator_replay"',
        'cp -r outputs/portfolio_goal_search "$DEST/portfolio_goal_search"',
    ]
    for token in bad_tokens:
        assert token not in text, token


def test_pipeline_exports_monthly_books() -> None:
    text = PIPELINE.read_text(encoding="utf-8")
    for token in [
        "main_monthly_weights_path",
        "tactical_monthly_weights_path",
        "alpha_sprint_monthly_weights_path",
        "regime_by_month_path",
        "sleeve_returns_by_month_path",
        "candidate_replay_book_path",
        "_write_monthly_mandate_books()",
    ]:
        assert token in text, token
    for token in [
        'replay_source["source_universe"] = source_values',
        "annotate_portfolio_candidate_gate(replay_source.copy(), cfg)",
        '"revenues_ttm"',
        '"gross_profit_ttm"',
        '"sales_growth_yoy"',
        '"eps_growth_yoy"',
        '"mom_1m"',
        '"mom_3m"',
        '"rs_benchmark_3m"',
        '"cash_weight_start"',
        '"cash_weight_end"',
        "avg_cash_weight_start",
        "avg_cash_weight_end",
    ]:
        assert token in text, token


def test_workflow_runs_latest_diagnostics_sidecars() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    sidecar_tool = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    combined = text + "\n" + sidecar_tool
    for token in [
        "tools/run_leader_drop_diagnostics_sidecar.py",
        "tools/run_governance_catalyst_report.py",
        "tools/run_style_regime_report.py",
        "tools/run_macro_policy_engine.py",
        "tools/run_cash_policy_attribution.py",
        "tools/run_stock_selection_quality_audit.py",
        "tools/run_entry_exit_timing_audit.py",
        "tools/run_cash_reentry_quality_audit.py",
        "tools/run_alpha_beta_attribution.py",
        "tools/run_fusion_candidate_review.py",
        "tools/run_data_freshness_contract.py",
        "tools/run_universe_health_audit.py",
        "run_universe_health_audit",
        "outputs/universe_health/",
        "--min-r1000-base 400",
        "run_data_freshness_contract",
        "outputs/data_freshness_contract/",
        "--source-context full_rebuild_sidecar",
        "--freshness-contract-non-fatal",
        "write_alpha_plane_measurement_status",
        "alpha_plane_measurement_status_v1",
        "--source-run-id",
        "--source-artifact-name",
        "tools/run_main_cash_drag_replay.py",
        "tools/run_crisis_reentry_replay.py",
        "tools/run_broker_crisis_reentry_replay.py",
        "tools/run_position_risk_weekly_validation.py",
        "tools/build_operating_target_books.py",
        "tools/build_replay_price_cache.py",
        "tools/build_daily_market_snapshot.py",
        "tools/run_cagr_walkforward.py",
        "tools/build_event_target_books.py",
        "tools/build_weekly_leader_target_books.py",
        "tools/archive_target_snapshots.py",
        "tools/run_broker_ledger_replay.py",
        "tools/run_broker_position_risk_replay.py",
        "tools/run_broker_position_risk_grid_sweep.py",
        "--disable-distribution-exit",
        "--candidate-id main_broker_parabolic_risk_replay",
        "tools/run_broker_execution_policy_replay.py",
        "tools/run_mdd_cash_overlay_research.py",
        "tools/run_operating_event_backtest.py",
        "tools/run_broker_gap_attribution.py",
        "tools/run_broker_trade_journal.py",
        "tools/run_account_order_preview.py",
        "tools/run_live_trading_safety_audit.py",
        "tools/run_live_trading_risk_controls.py",
        "tools/run_monster_recommendation_bridge.py",
        "tools/run_operating_snapshot.py",
        "tools/run_user_portfolio_reports.py",
        "tools/run_position_cleanup_review.py",
        "tools/run_portfolio_system_guard.py",
        "tools/run_adr_candidate_scanner.py",
        "tools/run_system_acceptance_audit.py",
        "tools/run_review_dispatcher.py",
        "tools/run_metric_hygiene_report.py",
        "--account-mode simulated",
        "tools/run_account_evaluation.py",
        "tools/run_oos_lock_audit.py",
        "tools/check_10y_backtest_readiness.py --latest-run outputs --min-years 8 --output-dir outputs/eight_year_backtest_readiness",
        'tools/check_10y_backtest_readiness.py --latest-run outputs --min-years 8 --output-dir outputs/eight_year_backtest_readiness --ref "${GITHUB_REF_NAME:-master}" --repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}"',
        "tools/run_era_aware_scoring_challenger.py",
        "--max-fill-lag-days 7",
        "tools/run_selection_audit.py",
        "tools/run_dataset_coverage_audit.py",
        "tools/check_10y_backtest_readiness.py",
        "tools/audit_data_readiness.py",
        "tools/run_weekly_evaluation.py",
        "tools/run_theme_leadership_tape.py",
        "tools/run_theme_concentration_challenger.py",
        "tools/create_healthy_baseline_lock.py",
        "tools/run_market_leader_challenger.py",
        "tools/run_sec_enriched_candidate_replay.py",
        "tools/run_superperformance_trader_replay.py",
        "tools/run_integrated_theme_leader_crisis_replay.py",
        "tools/run_strategy_logic_ledger.py",
        "tools/run_sidecar_promotion_bridge.py",
        "tools/run_decision_cadence_review.py",
        "tools/run_patch_application_manifest.py",
        "tools/run_alphaops_vnext_policy_replay.py",
        "tools/run_auto_learning_v2.py",
        "tools/run_winner_lifecycle_reports.py",
        "tools/run_winner_onset_study.py",
        "tools/run_shakeout_breakdown_study.py",
        "tools/run_shakeout_disclosure_reversal_study.py",
        "tools/run_autolearning_winner_challenger.py",
        "tools/run_alphaops_policy_fusion.py",
        "data_raw/free/sec/companyfacts.zip",
        "cp outputs/companyfacts.zip data_raw/free/sec/companyfacts.zip",
        "--max-age-days 3",
        "VALID_PRIMARY_OUTPUTS",
        "RUN_ARTIFACT_VALID",
        "GUARD_HARD_ERRORS",
        "portfolio_system_guard_hard_errors",
        "BRANCH_NAME",
        "SAFE_BRANCH",
        "GDRIVE_SCOPE",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/outputs",
        "failed_runs/${GITHUB_RUN_ID}",
        "Failed/cancelled partial runs must not overwrite",
        "outputs/full_rebuild_logs/leader_drop_diagnostics_sidecar.log",
        "outputs/full_rebuild_logs/governance_catalyst_report.log",
        "outputs/full_rebuild_logs/style_regime_report.log",
        "outputs/full_rebuild_logs/macro_policy_engine.log",
        "outputs/full_rebuild_logs/cash_policy_attribution.log",
        "outputs/full_rebuild_logs/main_cash_drag_replay.log",
        "outputs/full_rebuild_logs/crisis_reentry_replay.log",
        "outputs/full_rebuild_logs/broker_crisis_reentry_replay.log",
        "outputs/full_rebuild_logs/position_risk_weekly_validation_main.log",
        "outputs/full_rebuild_logs/position_risk_weekly_validation_main_v2.log",
        "outputs/full_rebuild_logs/position_risk_weekly_validation_concentrated.log",
        "outputs/full_rebuild_logs/operating_target_books.log",
        "outputs/full_rebuild_logs/replay_price_cache_refresh.log",
        "outputs/full_rebuild_logs/target_snapshot_archive.log",
        "outputs/full_rebuild_logs/data_readiness.log",
        "outputs/full_rebuild_logs/data_readiness_pre_broker.log",
        "outputs/full_rebuild_logs/universe_health_audit.log",
        "outputs/full_rebuild_logs/data_freshness_contract.log",
        "outputs/full_rebuild_logs/broker_ledger_replay_main.log",
        "outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log",
        "outputs/full_rebuild_logs/subdaily_exit_grid_wide_trailing.log",
        "outputs/full_rebuild_logs/broker_position_risk_grid_wide_trailing.log",
        "outputs/full_rebuild_logs/legacy_monthly_broker_replay_main.log",
        "outputs/full_rebuild_logs/legacy_monthly_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/event_target_books.log",
        "outputs/full_rebuild_logs/event_broker_replay_main.log",
        "outputs/full_rebuild_logs/event_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/weekly_leader_target_books.log",
        "outputs/full_rebuild_logs/weekly_leader_broker_replay_main.log",
        "outputs/full_rebuild_logs/weekly_leader_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/cost_sensitivity_main.log",
        "outputs/full_rebuild_logs/cost_sensitivity_concentrated.log",
        "outputs/full_rebuild_logs/macro_circuit_filter_main_factor25.log",
        "outputs/full_rebuild_logs/macro_circuit_filter_main_factor00.log",
        "outputs/full_rebuild_logs/macro_circuit_broker_replay_main_factor25.log",
        "outputs/full_rebuild_logs/macro_circuit_broker_replay_main_factor00.log",
        "outputs/full_rebuild_logs/regime_capacity_filter_concentrated_neutral90.log",
        "outputs/full_rebuild_logs/regime_capacity_broker_replay_concentrated_neutral90.log",
        "outputs/full_rebuild_logs/broker_position_risk_replay_main.log",
        "outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log",
        "outputs/full_rebuild_logs/broker_parabolic_risk_replay_main.log",
        "outputs/full_rebuild_logs/broker_parabolic_risk_replay_concentrated.log",
        "outputs/full_rebuild_logs/broker_execution_policy_replay_main.log",
        "outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log",
        "outputs/full_rebuild_logs/mdd_cash_overlay_research.log",
        "outputs/full_rebuild_logs/operating_event_backtest.log",
        "outputs/full_rebuild_logs/broker_gap_attribution.log",
        "outputs/full_rebuild_logs/broker_trade_journal.log",
        "outputs/full_rebuild_logs/account_order_preview_main.log",
        "outputs/full_rebuild_logs/account_order_preview_concentrated.log",
        "outputs/full_rebuild_logs/live_trading_safety_audit.log",
        "outputs/full_rebuild_logs/live_trading_risk_controls.log",
        "outputs/full_rebuild_logs/monster_recommendations.log",
        "outputs/full_rebuild_logs/operating_snapshot.log",
        "outputs/full_rebuild_logs/user_portfolio_reports.log",
        "outputs/full_rebuild_logs/position_cleanup_review.log",
        "outputs/full_rebuild_logs/portfolio_system_guard.log",
        "outputs/full_rebuild_logs/adr_candidate_scanner.log",
        "outputs/full_rebuild_logs/system_acceptance_audit.log",
        "outputs/full_rebuild_logs/review_dispatcher.log",
        "outputs/full_rebuild_logs/review_dispatcher_self_correction.log",
        "outputs/full_rebuild_logs/account_evaluation.log",
        "outputs/full_rebuild_logs/oos_lock.log",
        "outputs/full_rebuild_logs/alpha_beta_attribution.log",
        "outputs/full_rebuild_logs/fusion_candidate_review.log",
        "outputs/full_rebuild_logs/metric_hygiene_report.log",
        "outputs/full_rebuild_logs/selection_audit.log",
        "outputs/full_rebuild_logs/dataset_coverage_audit.log",
        "outputs/full_rebuild_logs/eight_year_backtest_readiness.log",
        "outputs/full_rebuild_logs/era_aware_scoring_challenger.log",
        "outputs/full_rebuild_logs/ten_year_backtest_readiness.log",
        "outputs/full_rebuild_logs/weekly_evaluation.log",
        "outputs/full_rebuild_logs/theme_leadership_tape.log",
        "outputs/full_rebuild_logs/theme_concentration_challenger.log",
        "outputs/full_rebuild_logs/baseline_lock.log",
        "outputs/full_rebuild_logs/sec_enriched_candidate_replay.log",
        "outputs/full_rebuild_logs/market_leader_challenger.log",
        "outputs/full_rebuild_logs/superperformance_trader_replay.log",
        "outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log",
        "outputs/full_rebuild_logs/strategy_logic_ledger.log",
        "outputs/full_rebuild_logs/sidecar_promotion_bridge.log",
        "outputs/full_rebuild_logs/decision_cadence_review.log",
        "outputs/full_rebuild_logs/patch_application_manifest.log",
        "outputs/full_rebuild_logs/auto_learning_v2.log",
        "outputs/full_rebuild_logs/winner_lifecycle.log",
        "outputs/full_rebuild_logs/winner_onset_study.log",
        "outputs/full_rebuild_logs/shakeout_breakdown_study.log",
        "outputs/full_rebuild_logs/shakeout_disclosure_reversal_study.log",
        "outputs/full_rebuild_logs/autolearning_winner_challenger.log",
        "outputs/full_rebuild_logs/policy_fusion.log",
        "tools/build_concentrated_trade_journal.py",
        "--extra-trades outputs/concentrated_trade_journal/trades.csv",
        "auto_learning_promote_live",
        "outputs/reports/main_monthly_weights.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main",
        "--target-book outputs/reports/operating_main_target_book.csv",
        "--target-book outputs/reports/operating_concentrated_target_book.csv",
        "portfolio_policy",
        "alphaops_vnext_production",
        "approved_target_policy_path",
        "pre_broker_replay_target_override_hook",
        "--portfolio-policy",
        "--approved-target-policy-path",
        "outputs/operator_review/projected_holdings_after_integrated_target.csv",
        "outputs/operator_review/projected_holdings_after_market_leader_target.csv",
        "outputs/alphaops_vnext/",
        "outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log",
        "market_leader_shadow",
        "--target-book outputs/reports/event_main_target_book.csv",
        "--target-book outputs/reports/event_concentrated_target_book.csv",
        "outputs/reports/event_*_target_book.csv",
        "outputs/event_target_books/",
        "outputs/event_broker_replay/",
        "outputs/reports/weekly_leader_*_target_book.csv",
        "outputs/weekly_leader_snapshots/",
        "outputs/weekly_leader_broker_replay/",
        "outputs/subdaily_exit_grid_wide_trailing",
        "outputs/broker_position_risk_grid_wide_trailing",
        "outputs/cost_sensitivity/",
        "outputs/trade_attribution/",
        "outputs/target_snapshots/latest_manifest.json",
        "outputs/data_readiness/summary.json",
        "outputs/main_v2_backtest/monthly_holdings.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main_v2",
        "--output-dir outputs/subdaily_exit_grid_wide_trailing --portfolio-kind both --hard-stop-grid=disabled --trailing-stop-grid=-0.25,-0.30,-0.35,-0.45 --trailing-activation 0.30 --relative-trim-threshold -99 --relative-exit-threshold -99",
        "--output-dir outputs/broker_position_risk_grid_wide_trailing --portfolio-kind both --hard-stop-grid=disabled --trailing-stop-grid=-0.25,-0.30,-0.35,-0.45 --trailing-activation 0.30 --relative-trim-threshold -99 --relative-exit-threshold -99",
    ]:
        assert token in combined, token


def test_sidecar_promotion_hook_runs_before_primary_broker_replay() -> None:
    sidecar_tool = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    operating_idx = sidecar_tool.index('if [ "$SIDECAR_PROFILE" = "operating_minimal" ]')
    refresh_idx = sidecar_tool.index("refresh_replay_price_cache", operating_idx)
    build_idx = sidecar_tool.index("tools/build_operating_target_books.py")
    hook_idx = sidecar_tool.index("run_sidecar_promotion_hook", build_idx)
    replay_idx = sidecar_tool.index("--target-book outputs/reports/operating_main_target_book.csv", build_idx)
    assert refresh_idx < build_idx
    assert build_idx < hook_idx < replay_idx
    assert "build_long_crisis_inputs" in sidecar_tool
    assert "tools/run_long_crisis_dataset_builder.py" in sidecar_tool


def test_subdaily_wide_trailing_grid_runs_after_primary_broker_replay() -> None:
    sidecar_tool = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    build_idx = sidecar_tool.index("tools/build_operating_target_books.py")
    replay_idx = sidecar_tool.index("--target-book outputs/reports/operating_concentrated_target_book.csv", build_idx)
    grid_idx = sidecar_tool.index("tools/run_subdaily_exit_grid_sweep.py", replay_idx)
    broker_grid_idx = sidecar_tool.index("tools/run_broker_position_risk_grid_sweep.py", grid_idx)
    mdd_idx = sidecar_tool.index("tools/run_mdd_cash_overlay_research.py", broker_grid_idx)
    assert replay_idx < grid_idx < broker_grid_idx < mdd_idx
    grid_call = sidecar_tool[grid_idx:broker_grid_idx]
    assert "--latest-run outputs" in grid_call
    assert "--portfolio-kind both" in grid_call
    assert "--hard-stop-grid=disabled" in grid_call
    assert "--relative-trim-threshold -99" in grid_call
    broker_grid_call = sidecar_tool[broker_grid_idx:mdd_idx]
    assert "--latest-run outputs" in broker_grid_call
    assert "--portfolio-kind both" in broker_grid_call
    assert "--hard-stop-grid=disabled" in broker_grid_call
    assert "--relative-trim-threshold -99" in broker_grid_call


def test_operating_acceptance_audit_runs_after_attribution_inputs() -> None:
    sidecar_tool = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    operating_idx = sidecar_tool.index('if [ "$SIDECAR_PROFILE" = "operating_minimal" ]')
    mdd_idx = sidecar_tool.index("tools/run_mdd_cash_overlay_research.py", operating_idx)
    trade_idx = sidecar_tool.index("tools/run_trade_attribution_analysis.py", operating_idx)
    is_idx = sidecar_tool.index("tools/run_is_attribution.py", operating_idx)
    alpha_beta_idx = sidecar_tool.index("tools/run_alpha_beta_attribution.py", operating_idx)
    fusion_idx = sidecar_tool.index("tools/run_fusion_candidate_review.py", alpha_beta_idx)
    era_idx = sidecar_tool.index("tools/run_era_leadership_sidecar.py", operating_idx)
    oos_idx = sidecar_tool.index("tools/run_oos_lock_audit.py", operating_idx)
    adr_idx = sidecar_tool.index("tools/run_adr_candidate_scanner.py", operating_idx)
    self_correction_idx = sidecar_tool.index("tools/run_self_correction_router.py", operating_idx)
    self_dispatcher_idx = sidecar_tool.index("--payloads outputs/self_correction_router/workflow_dispatch_payloads.json", self_correction_idx)
    acceptance_idx = sidecar_tool.index("tools/run_system_acceptance_audit.py", operating_idx)
    dispatcher_idx = sidecar_tool.index("--payloads outputs/system_acceptance_audit/workflow_dispatch_payloads.json", acceptance_idx)
    assert mdd_idx < acceptance_idx
    assert trade_idx < acceptance_idx
    assert is_idx < acceptance_idx
    assert is_idx < alpha_beta_idx < acceptance_idx
    assert alpha_beta_idx < fusion_idx < acceptance_idx
    assert era_idx < acceptance_idx
    assert oos_idx < acceptance_idx
    assert adr_idx < acceptance_idx
    assert self_correction_idx < self_dispatcher_idx < acceptance_idx
    assert acceptance_idx < dispatcher_idx
    self_correction_call = sidecar_tool[self_correction_idx:acceptance_idx]
    assert "--latest-run outputs" in self_correction_call
    assert '--ref "${GITHUB_REF_NAME:-master}"' in self_correction_call
    assert '--repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}"' in self_correction_call
    assert "--output-dir outputs/review_dispatcher_self_correction" in self_correction_call


def test_fast_replay_workflow_uses_artifacts_not_full_rebuild() -> None:
    text = REPLAY_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "AlphaOps Replay Sidecars",
        "source_run_id",
        "gh run download",
        "tools/build_replay_price_cache.py",
        "tools/build_operating_target_books.py",
        "tools/run_alphaops_vnext_policy_replay.py",
        "tools/build_event_target_books.py",
        "tools/build_weekly_leader_target_books.py",
        "tools/archive_target_snapshots.py",
        "tools/run_broker_trade_journal.py",
        "tools/run_account_order_preview.py",
        "tools/run_live_trading_safety_audit.py",
        "tools/run_live_trading_risk_controls.py",
        "tools/run_monster_recommendation_bridge.py",
        "tools/run_operating_snapshot.py",
        "tools/run_user_portfolio_reports.py",
        "tools/run_user_current_report.py",
        "tools/run_position_cleanup_review.py",
        "tools/run_patch_application_manifest.py",
        "--account-mode simulated",
        "tools/run_account_evaluation.py",
        "tools/audit_data_readiness.py",
        "tools/run_broker_position_risk_replay.py",
        "tools/run_broker_execution_policy_replay.py",
        "tools/run_broker_gap_attribution.py",
        "collector-cache--${{ runner.os }}-",
        "Run this workflow from a branch that contains the AlphaOps replay tools",
        "restored price cache files",
        "refreshing missing/stale replay price cache",
        "--required-tickers SPY QQQ",
        "--refresh-stale-days 2",
        "Restore evidence overlays from Google Drive",
        "outputs/sec_institutional_signals",
        "outputs/sec_ownership_signals",
        "data_pit/sec",
        "data_pit/etf_holdings",
        "data_pit/macro",
        "sec_evidence_restore_manifest.json",
        "using restored enriched candidate book for vNext",
        "built enriched candidate book for vNext",
        "outputs/reports/main_monthly_weights.csv",
        "outputs/reports/operating_main_target_book.csv",
        "outputs/reports/operating_concentrated_target_book.csv",
        "outputs/reports/operating_target_books_*",
        "outputs/reports/operating_*_target_book_regime_capacity*.csv",
        "outputs/reports/operating_*_target_book_macro*.csv",
        "portfolio_policy",
        "alphaops_vnext_production",
        "--portfolio-policy \"$PORTFOLIO_POLICY\"",
        "source_vnext_official_main_target_book.csv",
        "candidate_replay_book missing; restoring archived vNext official operating target books",
        "alphaops_vnext_production requires candidate_replay_book or archived official vNext target books",
        "sync_replay_to_gdrive",
        "inputs.sync_replay_to_gdrive",
        "run_extended_research_sidecars",
        "inputs.run_extended_research_sidecars",
        "leader_gate_enabled",
        "cycle_leadership_mask_enabled",
        "PHASE_LEADER_GATE_ENABLED",
        "PHASE_CYCLE_LEADERSHIP_MASK_ENABLED",
        "skipping extended research sidecars",
        "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
        "!outputs/alphaops_vnext/lane_scores_history.csv",
        "!outputs/alphaops_vnext/rejected_by_reason.csv",
        "Upload extended replay research artifact",
        "outputs/alphaops_vnext/",
        "outputs/full_rebuild_logs/alphaops_vnext_policy_replay.log",
        "outputs/target_snapshots/",
        "outputs/data_readiness/",
        "outputs/sec_enriched_candidate_replay/summary.json",
        "outputs/reports/dataset_coverage_audit.*",
        "outputs/reports/regime_by_month.csv",
        "outputs/position_risk_weekly_validation/main",
        "outputs/position_risk_weekly_validation/main_v2",
        "tools/run_broker_ledger_replay.py",
        "--target-book outputs/reports/operating_main_target_book.csv",
        "--target-book outputs/reports/operating_concentrated_target_book.csv",
        "--target-book outputs/reports/main_monthly_weights.csv",
        "--target-book outputs/reports/concentrated_strategy_holdings.csv",
        "--target-book outputs/reports/event_main_target_book.csv",
        "--target-book outputs/reports/event_concentrated_target_book.csv",
        "outputs/reports/event_*_target_book.csv",
        "outputs/event_target_books/",
        "outputs/event_broker_replay/",
        "outputs/reports/weekly_leader_*_target_book.csv",
        "outputs/weekly_leader_snapshots/",
        "outputs/weekly_leader_broker_replay/",
        "outputs/cost_sensitivity/",
        "outputs/trade_attribution/",
        "outputs/full_rebuild_logs/event_target_books.log",
        "outputs/full_rebuild_logs/event_broker_replay_main.log",
        "outputs/full_rebuild_logs/event_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/weekly_leader_target_books.log",
        "outputs/full_rebuild_logs/weekly_leader_broker_replay_main.log",
        "outputs/full_rebuild_logs/weekly_leader_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/cost_sensitivity_main.log",
        "outputs/full_rebuild_logs/cost_sensitivity_concentrated.log",
        "tools/run_operating_event_backtest.py",
        "outputs/operating_event_backtest/",
        "outputs/broker_position_risk_replay/",
        "outputs/broker_parabolic_risk_replay/",
        "outputs/legacy_monthly_broker_replay/",
        "outputs/broker_execution_policy_replay/",
        "outputs/broker_gap_attribution/",
        "outputs/broker_trade_journal/",
        "outputs/account_ledger_preview/",
        "outputs/live_trading_safety/",
        "outputs/live_trading_risk_controls/",
        "outputs/monster_recommendations/",
        "outputs/operating_snapshot/",
        "outputs/user_portfolio_reports/",
        "outputs/user_current/",
        "outputs/operator_review/",
        "outputs/account_evaluation/",
        "outputs/metric_hygiene/",
        "outputs/full_rebuild_logs/target_snapshot_archive.log",
        "outputs/full_rebuild_logs/data_readiness.log",
        "tools/run_theme_leadership_tape.py",
        "tools/run_theme_concentration_challenger.py",
        "tools/run_portfolio_goal_search.py",
        "tools/run_account_evaluation.py",
        "tools/run_metric_hygiene_report.py",
        "tools/run_portfolio_system_guard.py",
        "tools/create_healthy_baseline_lock.py",
        "tools/run_long_crisis_dataset_builder.py",
        "tools/run_long_crisis_signal_learning.py",
        "tools/run_long_crisis_threshold_search.py",
        "tools/run_sec_enriched_candidate_replay.py",
        "tools/run_superperformance_trader_replay.py",
        "tools/run_integrated_theme_leader_crisis_replay.py",
        "tools/run_strategy_logic_ledger.py",
        "tools/run_patch_application_manifest.py",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/replay_outputs",
        "outputs/baseline_lock/",
        "outputs/sec_enriched_candidate_replay/",
        "outputs/superperformance_trader_replay/",
        "outputs/integrated_theme_leader_crisis_replay/",
        "outputs/strategy_logic_ledger/",
        "outputs/patch_application_manifest.json",
        "outputs/full_rebuild_logs/integrated_theme_leader_crisis_replay.log",
        "outputs/full_rebuild_logs/superperformance_trader_replay.log",
        "outputs/full_rebuild_logs/strategy_logic_ledger.log",
        "outputs/full_rebuild_logs/patch_application_manifest.log",
        "outputs/full_rebuild_logs/position_cleanup_review.log",
        "outputs/full_rebuild_logs/metric_hygiene_report.log",
        "BASE_SRC=\"$(find source_artifacts -type f -name backtest_metrics.json -print -quit | xargs -r dirname)\"",
        "base source=$BASE_SRC",
        "CANDIDATE_SRC=\"$(dirname \"$(dirname \"$CANDIDATE_BOOK\")\")\"",
        "SOURCE_REPORT_CANDIDATE_BOOK=\"$(find source_artifacts -type f -path '*/reports/candidate_replay_book.csv' -print -quit)\"",
        "SOURCE_ENRICHED_CANDIDATE_BOOK=\"$(find source_artifacts -type f -path '*/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv' -print -quit)\"",
        "CANDIDATE_BOOK=\"${SOURCE_ENRICHED_CANDIDATE_BOOK:-${SOURCE_REPORT_CANDIDATE_BOOK:-$REPO_FALLBACK_CANDIDATE_BOOK}}\"",
        "REPO_FALLBACK_CANDIDATE_BOOK=\"$(find cloud_results/full_rebuild/failed_runs -type f -path \"*/${{ inputs.source_run_id }}_*/reports/candidate_replay_book.csv\" -print -quit 2>/dev/null || true)\"",
        "selected source with replay candidate",
        "policy replay may restore archived target books",
        "using restored enriched candidate book for vNext",
        "using base candidate book for vNext",
        "continue-on-error: true",
    ]:
        assert token in text, token
    for forbidden in [
        "python run_local.py --full",
        "Refresh SEC companyfacts bulk archive",
        "Full Rebuild START",
        "rm -f outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
    ]:
        assert forbidden not in text, forbidden


def test_free_data_lake_workflow_restores_drive_and_runs_proxy_replay() -> None:
    text = FREE_DATA_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "Free Data Lake Bootstrap",
        "tools/run_free_data_lake_bootstrap.py",
        "tools/run_free_data_engine_validation.py",
        "tools/check_10y_backtest_readiness.py",
        '--ref "${GITHUB_REF_NAME:-master}"',
        '--repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}"',
        "data_raw/free",
        "data_pit/free",
        "manifests/free_data",
        "cache_prices",
        "companyfacts.zip",
        "GOOGLE_SERVICE_ACCOUNT_KEY",
        "RCLONE_CONFIG_GDRIVE",
        "gdrive_smoke_test",
        "run_proxy_replay",
        "tools/run_broker_ledger_replay.py",
        "outputs/free_data_proxy_backtest/",
        "outputs/free_data_engine_validation/",
        "outputs/ten_year_backtest_readiness/",
        "data_pit/free/coverage_audit.json",
        "manifests/free_data/latest_manifest.json",
        "SAFE_BRANCH",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/free_data_lake_bootstrap",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/ten_year_backtest_readiness",
    ]:
        assert token in text, token
    for forbidden in [
        "git commit",
        "python run_local.py --full",
    ]:
        assert forbidden not in text, forbidden


def test_free_data_daily_workflow_updates_metrics_after_close() -> None:
    text = FREE_DATA_DAILY_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "Free Data Daily Update",
        "schedule:",
        "30 23 * * 1-5",
        "pandas_market_calendars",
        "MARKET_READY",
        "LAST_NYSE_CLOSE_UTC",
        "tools/run_free_data_lake_bootstrap.py",
        "price-mode target_books",
        "tools/run_broker_ledger_replay.py",
        "outputs/free_data_proxy_backtest/",
        "tools/run_free_data_engine_validation.py",
        "tools/check_10y_backtest_readiness.py",
        '--ref "${GITHUB_REF_NAME:-master}"',
        '--repo "${GITHUB_REPOSITORY:-wscha231/r1000-quant-engine}"',
        "outputs/free_data_engine_validation/",
        "outputs/ten_year_backtest_readiness/",
        "CAGR",
        "MaxDD",
        "sec_companyfacts",
        "SEC_COMPANYFACTS",
        "--sec-companyfacts",
        "--sec-max-age-days",
    ]:
        assert token in text, token
    for forbidden in [
        "python run_local.py --full",
        "git commit",
    ]:
        assert forbidden not in text, forbidden


def test_data_readiness_preflight_workflow_restores_drive_and_audits_without_full_rebuild() -> None:
    text = DATA_PREFLIGHT_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "Data Readiness Preflight",
        "schedule:",
        "15 0 * * 2-6",
        "tools/audit_data_readiness.py",
        "cache_prices",
        "data_raw/free",
        "data_pit/free",
        "data_pit/sec",
        "data_pit/etf_holdings",
        "data_pit/macro",
        "manifests/free_data",
        "LATEST_RUN_INPUT",
        "restore_requested_latest_run",
        'restore_requested_latest_run "$LATEST_RUN_INPUT"',
        "skip unsafe latest_run restore path",
        "companyfacts.zip",
        "sec_companyfacts",
        "sec_max_age_days",
        "Refresh SEC companyfacts when requested",
        "tools/refresh_companyfacts_bulk.py",
        "sec_companyfacts_refresh.log",
        "rclone copyto data_raw/free/sec/companyfacts.zip",
        "outputs/data_readiness/",
        "outputs/full_rebuild_logs/data_readiness.log",
        "data-readiness-preflight-${{ github.run_id }}",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/data_readiness",
        "RCLONE_CONFIG_GDRIVE",
        "GOOGLE_SERVICE_ACCOUNT_KEY",
    ]:
        assert token in text, token


def test_daily_operating_selection_refresh_workflow_updates_fresh_data_contract() -> None:
    text = DAILY_OPERATING_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "Daily Operating Selection Refresh",
        "15 1 * * 2-6",
        "force_run",
        "strict_selection",
        "allow_risk_outcome_genesis_bootstrap",
        "allow_quarantined_legacy_outcome_parent",
        "LATEST_RUN_INPUT",
        "hydrate outputs/ from requested latest_run",
        "cache_prices",
        "data_pit/sec",
        "data_pit/etf_holdings",
        "data_pit/macro",
        "Refresh current price cache",
        "Build daily market snapshot",
        "Label restored-target revaluation input",
        "Build operating target books",
        "tools/build_replay_price_cache.py",
        "tools/build_daily_market_snapshot.py",
        "outputs/portfolio_latest.csv",
        "outputs/concentrated_portfolio_latest.csv",
        "timeout 8m python tools/build_replay_price_cache.py",
        "timeout 10m python tools/build_daily_market_snapshot.py",
        "outputs/daily_market_snapshot/",
        "data_pit/free/market_snapshot/",
        "data_raw/free/market_snapshot/",
        "outputs/full_rebuild_logs/daily_market_snapshot.log",
        "price cache refresh failed or timed out",
        "daily market snapshot failed or timed out",
        "tools/build_operating_target_books.py",
        "timeout 3m python tools/build_operating_target_books.py",
        "tools/run_sec_enriched_candidate_replay.py",
        "timeout 8m python tools/run_sec_enriched_candidate_replay.py",
        "using restored SEC-enriched candidate replay",
        "SEC-enriched candidate replay failed or timed out",
        "daily_sec_enriched_candidate_replay.log",
        "restored_target_revaluation_candidate_book.csv",
        "RESTORED_TARGET_REVALUATION_ONLY",
        "same_close_selector_recomputed",
        "daily_candidate_source",
        "LAST_NYSE_SESSION_DATE",
        "tools/run_daily_market_session_gate.py",
        "--min-close-age-minutes 90",
        "--max-close-age-hours 18",
        "Record completed market session gate",
        "tools/validate_daily_close_prices.py",
        "Require exact completed-session close prices",
        "outputs/daily_market_session_gate/",
        "close_price_coverage.json",
        "exact_close_coverage",
        "building SEC-enriched candidate replay",
        "outputs/sec_enriched_candidate_replay/",
        "--require-current-latest-target",
        "--required-tickers SPY QQQ SMH SOXX",
        '--refresh-through-date "$LAST_NYSE_SESSION_DATE"',
        "--max-scored 0",
        "Refresh daily macro snapshot",
        "tools/macro_daily_snapshot.py",
        "--out-dir data_pit/macro",
        "data_pit/macro/latest.json",
        "data_raw/free/macro/daily_snapshot/latest.json",
        "outputs/full_rebuild_logs/daily_macro_snapshot.log",
        "tools/audit_data_readiness.py",
        "tools/run_data_freshness_contract.py",
        "--require-current-operating-books",
        "--source-context daily_operating_refresh",
        "outputs/data_freshness_contract/",
        "outputs/daily_operating_selection_refresh/",
        "Ensure review-only forward paper bootstrap",
        "tools/bootstrap_run287_daily_paper_accounts.py",
        "outputs/daily_simulated_fill_ledger/bootstrap/main_account.json",
        "outputs/daily_simulated_fill_ledger/bootstrap/concentrated_account.json",
        "daily_paper_bootstrap.log",
        "--expected-seed-date 2026-07-13",
        "--starting-capital 100000",
        "tools/run_daily_simulated_fill_ledger.py",
        "--decision-time-utc \"$DECISION_CUTOFF_UTC\"",
        "--security-lifecycle-events data_static/run287_exact_packet/security_lifecycle_events.csv",
        "outputs/daily_simulated_fill_ledger/",
        "daily_simulated_fill_ledger.log",
        "paper_archive/run287_daily_simulated_fill_ledger",
        "tools/build_run287_holding_risk_watch.py",
        "outputs/holding_risk_watch/",
        "daily_holding_risk_watch.log",
        "paper_archive/run287_holding_risk_watch",
        "tools/run_run287_exact_packet_upstream.py",
        "outputs/run287_exact_packet_upstream/",
        "outputs/run287_exact_packet_input_sources/",
        "daily_run287_exact_packet_upstream.log",
        "--attempt-id \"${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}\"",
        "--allow-network",
        "run287_exact_static_archive_v1.zip",
        "66ca4b6a6a61cb7e9a3a47e2f6d26aa42f30a9b96a25d07699c6cdeb8faf1d84",
        "tools/restore_run287_exact_static_archive.py",
        "run287_research_static",
        "research_static/run287_exact_static_archive_v1.zip",
        "git fetch --no-tags --depth=1 origin 15176",
        "feature_store/scored_oos_latest.parquet",
        "restore_dir models models",
        "restore_file data_raw/sec/company_tickers.json data_raw/free/sec/company_tickers.json",
        "tools/build_run287_exact_packet_input_registry.py",
        "outputs/run287_exact_packet_input_registry/",
        "run287_exact_packet_input_sources/source_bundle.json",
        "daily_run287_exact_packet_input_registry.log",
        "tools/run_run287_exact_packet_producer.py",
        "outputs/run287_exact_packet_producer/",
        "run287_exact_packet_input_registry/registry.json",
        "daily_run287_exact_packet_producer.log",
        "tools/build_run287_same_close_target_books.py",
        "outputs/run287_same_close_decision/",
        "daily_run287_same_close_target_books.log",
        "--suppress-new-orders",
        "zero new orders generated",
        "run287_current_selector_no_write_exact_close_",
        "run287_candidate_risk_watch_exact_close_",
        "exact_packet_ready",
        "tools/archive_run287_decision_observation.py",
        "outputs/run287_decision_observation_archive/",
        "daily_run287_decision_observation_archive.log",
        "Restore verified risk-outcome accepted head",
        "tools/manage_run287_risk_outcome_accepted_heads.py",
        "paper_archive/run287_risk_outcome_accepted_heads",
        "outputs/run287_risk_outcome_parent_accepted/manifest.json",
        "outputs/run287_risk_outcome_accepted_head_bundles",
        "outputs/run287_risk_outcome_accepted_head_manifests",
        "quarantined invalid GitHub-cache accepted head",
        "transient paper-archive discovery failure",
        "authoritative configured-base absence confirmed; first bootstrap may create it",
        "authoritative outcome configured-base absence confirmed; first bootstrap may create it",
        'rclone lsf "gdrive:" --dirs-only',
        "PAPER_CANONICAL_REMOTE_STATE=PROVEN_PRESENT",
        "PAPER_CANONICAL_REMOTE_STATE=PROVEN_ABSENT",
        "PAPER_DURABLE_RESTORE_MODE=UNAVAILABLE",
        "PAPER_DURABLE_RESTORE_MODE=IMMUTABLE_HEAD",
        "PAPER_DURABLE_RESTORE_MODE=VERIFIED_CANONICAL",
        "PAPER_DURABLE_RESTORE_MODE=VERIFIED_LEGACY_MIGRATION_SOURCE",
        "assert_remote_canonical_absent",
        "canonical Drive state appeared after authoritative absence preflight",
        "transient paper-head listing failure",
        "discard partial remote view and use only verified cache state",
        "authoritative Drive head discovery is unavailable",
        "cached accepted-state manifest has no complete verified bundle or authoritative remote commit",
        "cached accepted-publication marker is absent from the complete verified cache/remote union",
        "authoritative legacy outcome archive could not be fetched exactly",
        "outcome genesis requires proven absence of authoritative legacy state",
        "legacy outcome parent requires explicit one-time workflow_dispatch authorization",
        "outcome genesis requires explicit one-time workflow_dispatch authorization",
        "genesis and legacy-quarantine bootstrap authorizations are mutually exclusive",
        "allow_verified_paper_canonical_head_bootstrap",
        "ALLOW_VERIFIED_PAPER_CANONICAL_HEAD_BOOTSTRAP",
        "run287-verified-paper-canonical-bootstrap-v1",
        "EXPLICIT_ONE_TIME_MIGRATION_AUTHORIZED",
        "explicitly adopted integrity-valid pre-head Drive canonical",
        "PAPER_VERIFIED_CANONICAL_BOOTSTRAP_PENDING",
        "migration evidence mismatch",
        "committed explicitly attested pre-head canonical in the verified immutable chain",
        "persist_immutable_paper_head",
        "--select-immutable-heads-root",
        "--install-immutable-heads-root",
        "select_head_set \"$PAPER_PROSPECTIVE_HEADS\"",
        "committed immutable terminal differs from local state",
        "immutable terminal changed during canonical mirror publication",
        "ignore incomplete uncommitted immutable head",
        "--exclude snapshot_integrity.json",
        '"$remote_head/snapshot_integrity.json"',
        "daily_run287_outcome_parent_paper_continuity.json",
        "ACCEPTED_OUTCOME_PAPER_IS_ANCESTOR",
        "ancestor_snapshot_hashes",
        "persist_immutable_outcome_head",
        "Freeze accepted risk-outcome parent",
        "tools/build_run287_risk_outcome_parent_anchor.py",
        "outputs/run287_risk_outcome_parent_anchor/anchor.json",
        "daily_run287_risk_outcome_parent_anchor.log",
        "--parent-accepted-manifest",
        "--expected-parent-accepted-manifest-sha256",
        "--allow-quarantined-legacy-parent",
        "--parent-anchor outputs/run287_risk_outcome_parent_anchor/anchor.json",
        "--expected-prior-invocation-summary-sha256",
        "Resolve append-only forward outcomes",
        "tools/resolve_run287_risk_outcomes.py",
        "Build runtime operating scorecard",
        "tools/build_run287_operating_scorecard.py",
        "outputs/run287_operating_scorecard/",
        "daily_run287_operating_scorecard.log",
        "Evaluate single promotion and rollback gate",
        "Build post-gate operating reports",
        "Verify accepted publication manifest",
        "tools/build_run287_accepted_publication_manifest.py",
        "outputs/run287_accepted_publication/manifest.json",
        "id: paper_integrity",
        "id: risk_outcome_accepted_parent",
        "id: risk_outcome_parent",
        "id: risk_outcomes",
        "id: operating_scorecard",
        "id: promotion_gate",
        "id: accepted_publication",
        "promotion_gate_sha256=",
        "--expected-risk-outcome-parent-anchor-sha256",
        "--expected-promotion-gate-sha256",
        "manifest_sha256=",
        "--expected-manifest-sha256",
        "--verify-manifest",
        "Reverify accepted publication before GitHub publication",
        "Reverify accepted publication before refreshed cache",
        "id: paper_persist",
        "steps.accepted_publication.outcome == 'success'",
        "if-no-files-found: error",
        "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/accepted_paper_transaction",
        "paper_archive/run287_decision_observation_archive",
        "--allow-missing",
        "--require-exact-close",
        "GENERATED_AT_UTC=\"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"",
        "--available-from \"$GENERATED_AT_UTC\"",
        "catchup_price_evidence_run_id",
        "catchup_price_evidence_artifact_digest",
        "catchup_secret_scope_attestation_comment_id",
        "Restore immutable catch-up price evidence",
        "Restore validated cross-mode paper continuity cache",
        "Verify owner scope attestation for catch-up",
        "Consume owner scope attestation once",
        "Reverify one-time scope attestation before local paper transaction",
        "Enforce one-time durable scope before local paper transaction",
        "Reverify one-time scope attestation before durable persistence",
        "durable_scope_persist_preflight",
        "run287_durable_scope_persist.json",
        "run287_durable_scope_consumption_persist.json",
        "exact workflow-run lease expired before persistence start",
        "Enforce durable Drive for chronological catch-up",
        "tools/check_run287_catchup_drive_readiness.py",
        "RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY",
        "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE",
        "RUN287_DURABLE_ENVIRONMENT_ATTESTATION",
        "RUN287_DURABLE_ENVIRONMENT_NAME",
        "run287_durable_scope_initial.json",
        "tools/verify_run287_catchup_scope_attestation.py",
        "tools/run287_catchup_scope_consumption.py",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_COMMENT_ID",
        "--phase mutation",
        "daily-paper-continuity-v1-",
        "outputs/run287_paper_immutable_head_bundles",
        "origin_verification_mode",
        "DEFAULT_BRANCH_ANCESTOR",
        "APPROVED_LEGACY_ARTIFACT_PIN",
        "workflow_identity_verified",
        "repository_identity_verified",
        "head_lineage_verified",
        "actions/runs/${EVIDENCE_RUN_ID}",
        "actions/workflows/daily_operating_selection_refresh.yml",
        "compare/${ARTIFACT_HEAD_SHA}...${GITHUB_SHA}",
        "validate_github_compare_payload",
        "unsafe catch-up artifact archive member",
        "tools/build_run287_catchup_price_evidence.py",
        "tools/build_run287_catchup_target_evidence.py",
        "Restore immutable catch-up target evidence for legacy migration",
        "id: catchup_target_evidence",
        "env.PAPER_LEGACY_MIGRATION_PENDING == 'yes'",
        "outputs/run287_catchup_target_evidence/",
        "outputs/run287_catchup_target_evidence_status.json",
        "--price-evidence-manifest",
        "--replay-only",
        "Enforce default-branch sole writer",
        "Persist validated forward paper ledger state",
        "Reverify default head before accepted publication and cache",
        "default_head_publication_gate",
        "Reverify default head immediately before accepted cache saves",
        "default_head_cache_gate",
        "Reverify default head after accepted publication",
        "final_default_head_gate",
        "assert_current_default_head",
        "--max-fill-lag-days 7",
        "daily-operating-selection-refresh",
        "cancel-in-progress: false",
        "environment: run287-paper-durable",
        "review_only",
        "canonical_production_sync",
        "live_trading_enabled",
        "production_mutation_allowed",
        "human_approval_required",
        "source_of_truth_level",
        "tools/build_daily_user_current_contract.py",
        "outputs/user_current/02_target_weights.csv",
        "outputs/user_current/03_order_preview.csv",
        "outputs/user_current/08_rebalance_decision.json",
        "outputs/user_current/DAILY_REVIEW_ONLY.md",
        "outputs/full_rebuild_logs/daily_user_current_contract.log",
        "STRICT_SELECTION",
        'if [ "${GITHUB_EVENT_NAME}" = "workflow_dispatch" ] && [ "${STRICT_SELECTION:-false}" != "true" ]; then',
        "daily target mutation is always fail-closed",
        '--asof-date "$LAST_NYSE_SESSION_DATE"',
        "--strict-selection",
        'core_coverage.get("required_for_target_mutation") is not False',
        "--freshness-status outputs/data_freshness_contract/status.json",
        "--freshness-snapshot-manifest outputs/data_freshness_contract/data_snapshot_manifest.json",
        '--expected-source-run-id "${GITHUB_RUN_ID}"',
        '--expected-source-commit-sha "${GITHUB_SHA}"',
        '--expected-source-branch "${GITHUB_REF_NAME}"',
        '--expected-source-artifact-name "daily-operating-selection-refresh-${GITHUB_RUN_ID}"',
        "fail-closed freshness mutation gate is not satisfied",
        "outputs/full_rebuild_logs/data_freshness_contract.log",
        "daily-operating-selection-refresh-${{ github.run_id }}",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/daily_operating_selection_refresh",
        "actions/cache/save@v4",
        "RCLONE_CONFIG_GDRIVE",
        "GOOGLE_SERVICE_ACCOUNT_KEY",
    ]:
        assert token in text, token
    assert "--minimum-core-candidate-coverage 0.98" not in text
    exact_close_step = text[
        text.index("- name: Require exact completed-session close prices"):
        text.index("- name: Refresh daily macro snapshot")
    ]
    for token in (
        "CATCHUP_PRICE_CACHE: ${{ steps.catchup_price_evidence.outputs.price_cache }}",
        "CATCHUP_MAIN_TARGET: ${{ steps.catchup_target_evidence.outputs.main_target }}",
        "CATCHUP_CONCENTRATED_TARGET: ${{ steps.catchup_target_evidence.outputs.concentrated_target }}",
        "CATCHUP_TARGET_MANIFEST: ${{ steps.catchup_target_evidence.outputs.target_manifest }}",
        'CLOSE_PRICE_CACHE="cache_prices"',
        'CLOSE_MAIN_TARGET="outputs/reports/operating_main_target_book.csv"',
        'CLOSE_CONCENTRATED_TARGET="outputs/reports/operating_concentrated_target_book.csv"',
        'if [ "${PAPER_CATCHUP_MODE:-no}" = "yes" ]; then',
        'CLOSE_PRICE_CACHE="${CATCHUP_PRICE_CACHE:?missing immutable catch-up price cache}"',
        'CLOSE_MAIN_TARGET="${CATCHUP_MAIN_TARGET:?missing immutable catch-up main target}"',
        'CLOSE_CONCENTRATED_TARGET="${CATCHUP_CONCENTRATED_TARGET:?missing immutable catch-up concentrated target}"',
        'CLOSE_MAIN_TARGET="outputs/daily_simulated_fill_ledger/main/effective_target_latest.csv"',
        'CLOSE_CONCENTRATED_TARGET="outputs/daily_simulated_fill_ledger/concentrated/effective_target_latest.csv"',
        'test -s "$CLOSE_PRICE_CACHE/manifest.json"',
        'test -s "${CATCHUP_TARGET_MANIFEST:?missing immutable catch-up target manifest}"',
        '--price-cache "$CLOSE_PRICE_CACHE"',
        '--target "$CLOSE_MAIN_TARGET"',
        '--target "$CLOSE_CONCENTRATED_TARGET"',
    ):
        assert token in exact_close_step, token
    assert "--price-cache cache_prices" not in exact_close_step
    paper_step = text[
        text.index("- name: Run transactional paper ledger and same-close selector"):
        text.index("- name: Verify transactional forward paper snapshot")
    ]
    for token in (
        'PAPER_MAIN_TARGET="outputs/reports/operating_main_target_book.csv"',
        'PAPER_CONCENTRATED_TARGET="outputs/reports/operating_concentrated_target_book.csv"',
        'PAPER_MAIN_TARGET="${CATCHUP_MAIN_TARGET:?missing immutable catch-up main target}"',
        'PAPER_CONCENTRATED_TARGET="${CATCHUP_CONCENTRATED_TARGET:?missing immutable catch-up concentrated target}"',
        'CATCHUP_TARGET_SOURCE_DIR="outputs/run287_catchup_target_source/${PAPER_AS_OF}"',
        'DURABLE_TARGET_SOURCE_DIR="outputs/daily_simulated_fill_ledger/replay_target_source/${PAPER_AS_OF}"',
        'PAPER_STATE_AS_OF="$(python -c',
        'if [ "$PAPER_STATE_AS_OF" = "$PAPER_AS_OF" ]; then',
        'test -s "$DURABLE_TARGET_SOURCE_DIR/main.csv"',
        'test -s "$DURABLE_TARGET_SOURCE_DIR/concentrated.csv"',
        'SOURCE_MAIN_TARGET="$DURABLE_TARGET_SOURCE_DIR/main.csv"',
        'SOURCE_CONCENTRATED_TARGET="$DURABLE_TARGET_SOURCE_DIR/concentrated.csv"',
        'rm -f',
        '"$CATCHUP_TARGET_SOURCE_DIR/main.csv"',
        '"$CATCHUP_TARGET_SOURCE_DIR/concentrated.csv"',
        'cmp -s',
        'PAPER_MAIN_TARGET="$CATCHUP_TARGET_SOURCE_DIR/main.csv"',
        'PAPER_CONCENTRATED_TARGET="$CATCHUP_TARGET_SOURCE_DIR/concentrated.csv"',
        '--main-target "$PAPER_MAIN_TARGET"',
        '--concentrated-target "$PAPER_CONCENTRATED_TARGET"',
    ):
        assert token in paper_step, token
    for forbidden in [
        "python run_local.py --full",
        "git commit",
        "tools/run_broker_ledger_replay.py",
        'payload.get("head_commit")',
    ]:
        assert forbidden not in text, forbidden
    freshness_idx = text.index("python tools/run_data_freshness_contract.py")
    persistent_restore_idx = text.index(
        "- name: Restore persistent data and operating outputs"
    )
    catchup_target_evidence_idx = text.index(
        "- name: Restore immutable catch-up target evidence for legacy migration"
    )
    exact_close_gate_idx = text.index(
        "- name: Require exact completed-session close prices"
    )
    durable_catchup_drive_idx = text.index(
        "- name: Enforce durable Drive for chronological catch-up"
    )
    paper_idx = text.index("python tools/run_daily_simulated_fill_ledger.py")
    accepted_parent_restore_idx = text.index(
        "- name: Restore verified risk-outcome accepted head"
    )
    holding_risk_idx = text.index("python tools/build_run287_holding_risk_watch.py")
    exact_upstream_idx = text.index("python tools/run_run287_exact_packet_upstream.py")
    input_registry_idx = text.index("python tools/build_run287_exact_packet_input_registry.py")
    exact_packet_idx = text.index("python tools/run_run287_exact_packet_producer.py")
    same_close_idx = text.index("python tools/build_run287_same_close_target_books.py")
    selected_paper_idx = text.index("python tools/run_daily_simulated_fill_ledger.py", paper_idx + 1)
    integrity_idx = text.index(
        "python tools/run287_paper_ledger_integrity.py", selected_paper_idx
    )
    parent_clear_idx = text.index(
        "rm -rf outputs/run287_risk_outcome_parent_anchor"
    )
    parent_idx = text.index(
        "python tools/build_run287_risk_outcome_parent_anchor.py"
    )
    decision_archive_idx = text.index("python tools/archive_run287_decision_observation.py")
    outcome_idx = text.index("python tools/resolve_run287_risk_outcomes.py", decision_archive_idx)
    scorecard_clear_idx = text.index(
        "rm -rf outputs/run287_operating_scorecard"
    )
    scorecard_idx = text.index("python tools/build_run287_operating_scorecard.py")
    promotion_clear_idx = text.index("rm -rf outputs/run287_promotion_gate")
    promotion_idx = text.index("python tools/run_run287_promotion_gate.py")
    snapshot_idx = text.index("python tools/run_operating_snapshot.py")
    accepted_clear_idx = text.index(
        "rm -rf outputs/run287_accepted_publication"
    )
    accepted_idx = text.index(
        "python tools/build_run287_accepted_publication_manifest.py"
    )
    assert freshness_idx < paper_idx, "freshness must fail closed before any paper-ledger mutation"
    assert (
        persistent_restore_idx
        < catchup_target_evidence_idx
        < exact_close_gate_idx
        < paper_idx
    ), (
        "legacy target evidence must be restored only after durable-state "
        "classification and before close validation or paper mutation"
    )
    assert durable_catchup_drive_idx < paper_idx, (
        "catch-up must prove durable Drive availability before any paper-ledger mutation"
    )
    assert accepted_parent_restore_idx < paper_idx < snapshot_idx, "the immutable prior outcome head must be restored before the paper account is advanced"
    assert paper_idx < holding_risk_idx < snapshot_idx, "holding risk must use the marked paper account before reports"
    assert holding_risk_idx < exact_upstream_idx < input_registry_idx < exact_packet_idx < same_close_idx < selected_paper_idx < integrity_idx < parent_clear_idx < parent_idx < decision_archive_idx < outcome_idx < scorecard_idx < promotion_idx < snapshot_idx < accepted_idx, "paper ledger must verify integrity and freeze the restored outcome parent before outcomes; scorecard, promotion, and reports must be hash-bound before accepted publication"
    assert text.count(
        "--parent-anchor outputs/run287_risk_outcome_parent_anchor/anchor.json"
    ) == 1, "both resolver invocations must reuse the single frozen parent through RISK_OUTCOME_ARGS"
    assert text.count("--expected-prior-invocation-summary-sha256") == 1
    assert text.index(
        "python tools/manage_run287_risk_outcome_accepted_heads.py select"
    ) < parent_idx
    accepted_head_verify_idx = text.index(
        "python tools/manage_run287_risk_outcome_accepted_heads.py verify",
        accepted_parent_restore_idx,
    )
    accepted_paper_continuity_idx = text.index(
        "daily_run287_outcome_parent_paper_continuity.json"
    )
    accepted_head_install_idx = text.index(
        'cp -a "$SELECTED_HEAD/run287_risk_outcome_archive"'
    )
    assert (
        accepted_head_verify_idx
        < accepted_paper_continuity_idx
        < accepted_head_install_idx
    ), "an accepted outcome head must prove paper ancestry before installation"
    assert text.index(
        "python tools/manage_run287_risk_outcome_accepted_heads.py stage"
    ) > accepted_idx
    assert outcome_idx < scorecard_clear_idx < scorecard_idx
    assert scorecard_idx < promotion_clear_idx < promotion_idx
    assert snapshot_idx < accepted_clear_idx < accepted_idx
    assert "run_daily_simulated_fill_ledger.py --" not in text
    assert "daily_simulated_fill_ledger.log || true" not in text
    for log_name in (
        "daily_operating_snapshot.log",
        "daily_user_portfolio_reports.log",
        "daily_user_current_report.log",
        "daily_user_current_contract.log",
    ):
        assert f"{log_name} || true" not in text, (
            "post-gate operating report failures must block accepted publication"
        )
    assert text.count("steps.accepted_publication.outcome == 'success'") >= 5
    accepted_upload = text[
        text.index("- name: Upload accepted paper transaction artifact"):
        text.index("- name: Save validated forward paper state cache")
    ]
    for path in (
        "outputs/run287_decision_observation_archive/",
        "outputs/run287_risk_outcome_parent_accepted/",
        "outputs/run287_risk_outcome_parent_anchor/",
        "outputs/run287_risk_outcome_accepted_head_bundles/",
        "outputs/run287_risk_outcome_accepted_head_manifests/",
        "outputs/run287_risk_outcome_archive/",
        "outputs/run287_risk_outcome_price_cache/",
        "outputs/run287_operating_scorecard/",
        "outputs/run287_promotion_gate/",
        "outputs/run287_accepted_publication/",
        "outputs/run287_paper_immutable_head_bundles/",
    ):
        assert path in accepted_upload, path
    accepted_drive = text[
        text.index("- name: Sync accepted paper transaction to Google Drive"):
        text.index("- name: Save refreshed GitHub cache")
    ]
    persist_step_idx = text.index(
        "- name: Persist validated forward paper ledger state"
    )
    accepted_upload_idx = text.index(
        "- name: Upload accepted paper transaction artifact"
    )
    accepted_cache_idx = text.index(
        "- name: Save validated forward paper state cache"
    )
    continuity_cache_idx = text.index(
        "- name: Save validated cross-mode paper continuity cache"
    )
    accepted_drive_idx = text.index(
        "- name: Sync accepted paper transaction to Google Drive"
    )
    assert (
        persist_step_idx
        < accepted_upload_idx
        < accepted_cache_idx
        < continuity_cache_idx
        < accepted_drive_idx
    ), "canonical paper persistence must precede every accepted publication/cache"
    assert (
        'DEST="${BASE}research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/accepted_paper_transaction"'
        in accepted_drive
    )
    assert (
        '${GITHUB_RUN_ID}/daily_operating_selection_refresh' not in accepted_drive
    ), "accepted Drive publication must not share the always-on diagnostic namespace"
    assert "outputs/run287_decision_observation_archive" in accepted_drive
    assert "outputs/run287_risk_outcome_parent_accepted" in accepted_drive
    assert "outputs/run287_risk_outcome_parent_anchor" in accepted_drive
    assert "outputs/run287_risk_outcome_accepted_head_manifests" in accepted_drive
    assert "outputs/run287_risk_outcome_price_cache" in accepted_drive
    assert accepted_drive.index(
        'rclone copyto "$f" "$DEST/$f"'
    ) < accepted_drive.index(
        "rclone copy outputs/run287_accepted_publication"
    ), "the accepted manifest must be the final remote acceptance marker"
    diagnostic_drive = text[
        text.index("- name: Sync daily operating artifact to Google Drive"):
        text.index("- name: Persist validated forward paper ledger state")
    ]
    assert "--verify-manifest" not in diagnostic_drive, (
        "always-on diagnostic publication must not require an accepted manifest"
    )
    assert "outputs/run287_risk_outcome_parent_anchor" in diagnostic_drive
    assert "outputs/run287_risk_outcome_parent_accepted" in diagnostic_drive
    assert "outputs/run287_risk_outcome_accepted_head_manifests" in diagnostic_drive
    cache_save = text[
        text.index("- name: Save validated forward paper state cache"):
        text.index("- name: Sync accepted paper transaction to Google Drive")
    ]
    assert "outputs/run287_accepted_publication" in cache_save
    assert "outputs/run287_risk_outcome_accepted_head_bundles" in cache_save
    assert "outputs/run287_risk_outcome_accepted_head_manifests" in cache_save
    assert "daily-paper-continuity-v1-" in cache_save
    assert "outputs/run287_paper_immutable_head_bundles" in cache_save
    assert text.count("--verify-manifest") >= 4
    assert text.count("--expected-manifest-sha256") >= 4


def test_pages_deploy_keeps_prior_site_without_completed_session_artifact() -> None:
    text = PAGES_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "Check for completed-session daily artifact",
        "actions/github-script@v7",
        "daily-operating-selection-refresh-${runId}",
        "no completed-session artifact",
        "Resolve Pages publication gate",
        "deploy_ready",
        "steps.publish_gate.outputs.ready == 'yes'",
        "needs.build.outputs.deploy_ready == 'yes'",
    ]:
        assert token in text, token


def main() -> int:
    test_workflow_yaml_files_parse()
    test_pr_workflows_sparse_checkout_only_required_rebuild_data()
    test_pr_validation_does_not_duplicate_same_sha_push_and_pr_jobs()
    test_portfolio_guard_requires_checksum_locked_fixture()
    test_workflow_keeps_monthly_books()
    test_cloud_results_copy_is_not_nested()
    test_pipeline_exports_monthly_books()
    test_workflow_runs_latest_diagnostics_sidecars()
    test_sidecar_promotion_hook_runs_before_primary_broker_replay()
    test_fast_replay_workflow_uses_artifacts_not_full_rebuild()
    test_free_data_lake_workflow_restores_drive_and_runs_proxy_replay()
    test_free_data_daily_workflow_updates_metrics_after_close()
    test_data_readiness_preflight_workflow_restores_drive_and_audits_without_full_rebuild()
    test_daily_operating_selection_refresh_workflow_updates_fresh_data_contract()
    test_pages_deploy_keeps_prior_site_without_completed_session_artifact()
    print("workflow artifact smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
