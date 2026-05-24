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
        "outputs/concentrated_trade_journal/",
        "outputs/alpha_sprint_backtest/",
        "outputs/position_aware_risk_replay/",
        "outputs/position_risk_weekly_validation/",
        "outputs/broker_replay/",
        "outputs/event_target_books/",
        "outputs/event_broker_replay/",
        "outputs/weekly_leader_snapshots/",
        "outputs/weekly_leader_broker_replay/",
        "outputs/cost_sensitivity/",
        "outputs/trade_attribution/",
        "outputs/broker_position_risk_replay/",
        "outputs/broker_execution_policy_replay/",
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
        "outputs/account_evaluation/",
        "outputs/governance_catalyst/",
        "outputs/style_regime_report/",
        "outputs/macro_policy_engine/",
        "outputs/cash_policy/",
        "outputs/main_cash_drag_replay/",
        "outputs/crisis_reentry_replay/",
        "outputs/broker_crisis_reentry_replay/",
        "outputs/monster_lifecycle_replay/",
        "outputs/lifecycle_review_overlay_main/",
        "outputs/monster_lifecycle_review_main/",
        "outputs/monster_lifecycle_review_concentrated/",
        "outputs/historical_trade_journey/",
        "outputs/selection_audit/",
        "outputs/ten_year_backtest_readiness/",
        "outputs/weekly_evaluation/",
        "outputs/theme_leadership_tape/",
        "outputs/theme_concentration_challenger/",
        "outputs/evidence_discovery_universe",
        "outputs/auto_learning_v2/",
        "outputs/winner_lifecycle/",
        "outputs/winner_onset_study/",
        "outputs/shakeout_breakdown_study/",
        "outputs/autolearning_winner_challenger/",
        "outputs/policy_fusion/",
    ):
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
    for token in [
        "tools/run_leader_drop_diagnostics_sidecar.py",
        "tools/run_governance_catalyst_report.py",
        "tools/run_style_regime_report.py",
        "tools/run_macro_policy_engine.py",
        "tools/run_cash_policy_attribution.py",
        "tools/run_main_cash_drag_replay.py",
        "tools/run_crisis_reentry_replay.py",
        "tools/run_broker_crisis_reentry_replay.py",
        "tools/run_position_risk_weekly_validation.py",
        "tools/build_operating_target_books.py",
        "tools/build_event_target_books.py",
        "tools/build_weekly_leader_target_books.py",
        "tools/archive_target_snapshots.py",
        "tools/run_broker_ledger_replay.py",
        "tools/run_broker_position_risk_replay.py",
        "tools/run_broker_execution_policy_replay.py",
        "tools/run_operating_event_backtest.py",
        "tools/run_broker_gap_attribution.py",
        "tools/run_broker_trade_journal.py",
        "tools/run_account_order_preview.py",
        "tools/run_live_trading_safety_audit.py",
        "tools/run_live_trading_risk_controls.py",
        "tools/run_monster_recommendation_bridge.py",
        "tools/run_operating_snapshot.py",
        "tools/run_user_portfolio_reports.py",
        "tools/run_portfolio_system_guard.py",
        "--account-mode simulated",
        "tools/run_account_evaluation.py",
        "--max-fill-lag-days 7",
        "tools/run_selection_audit.py",
        "tools/run_dataset_coverage_audit.py",
        "tools/check_10y_backtest_readiness.py",
        "tools/audit_data_readiness.py",
        "tools/run_weekly_evaluation.py",
        "tools/run_theme_leadership_tape.py",
        "tools/run_theme_concentration_challenger.py",
        "tools/run_auto_learning_v2.py",
        "tools/run_winner_lifecycle_reports.py",
        "tools/run_winner_onset_study.py",
        "tools/run_shakeout_breakdown_study.py",
        "tools/run_autolearning_winner_challenger.py",
        "tools/run_alphaops_policy_fusion.py",
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
        "outputs/full_rebuild_logs/target_snapshot_archive.log",
        "outputs/full_rebuild_logs/data_readiness.log",
        "outputs/full_rebuild_logs/broker_ledger_replay_main.log",
        "outputs/full_rebuild_logs/broker_ledger_replay_concentrated.log",
        "outputs/full_rebuild_logs/event_target_books.log",
        "outputs/full_rebuild_logs/event_broker_replay_main.log",
        "outputs/full_rebuild_logs/event_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/weekly_leader_target_books.log",
        "outputs/full_rebuild_logs/weekly_leader_broker_replay_main.log",
        "outputs/full_rebuild_logs/weekly_leader_broker_replay_concentrated.log",
        "outputs/full_rebuild_logs/cost_sensitivity_main.log",
        "outputs/full_rebuild_logs/cost_sensitivity_concentrated.log",
        "outputs/full_rebuild_logs/broker_position_risk_replay_main.log",
        "outputs/full_rebuild_logs/broker_position_risk_replay_concentrated.log",
        "outputs/full_rebuild_logs/broker_execution_policy_replay_main.log",
        "outputs/full_rebuild_logs/broker_execution_policy_replay_concentrated.log",
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
        "outputs/full_rebuild_logs/portfolio_system_guard.log",
        "outputs/full_rebuild_logs/account_evaluation.log",
        "outputs/full_rebuild_logs/selection_audit.log",
        "outputs/full_rebuild_logs/dataset_coverage_audit.log",
        "outputs/full_rebuild_logs/ten_year_backtest_readiness.log",
        "outputs/full_rebuild_logs/weekly_evaluation.log",
        "outputs/full_rebuild_logs/theme_leadership_tape.log",
        "outputs/full_rebuild_logs/theme_concentration_challenger.log",
        "outputs/full_rebuild_logs/auto_learning_v2.log",
        "outputs/full_rebuild_logs/winner_lifecycle.log",
        "outputs/full_rebuild_logs/winner_onset_study.log",
        "outputs/full_rebuild_logs/shakeout_breakdown_study.log",
        "outputs/full_rebuild_logs/autolearning_winner_challenger.log",
        "outputs/full_rebuild_logs/policy_fusion.log",
        "tools/build_concentrated_trade_journal.py",
        "--extra-trades outputs/concentrated_trade_journal/trades.csv",
        "auto_learning_promote_live",
        "outputs/reports/main_monthly_weights.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main",
        "--target-book outputs/reports/operating_main_target_book.csv",
        "--target-book outputs/reports/operating_concentrated_target_book.csv",
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
        "outputs/target_snapshots/latest_manifest.json",
        "outputs/data_readiness/summary.json",
        "outputs/main_v2_backtest/monthly_holdings.csv --period-map outputs/reports/regime_by_month.csv --price-cache cache_prices --portfolio-kind main --output-dir outputs/position_risk_weekly_validation/main_v2",
    ]:
        assert token in text, token


def test_fast_replay_workflow_uses_artifacts_not_full_rebuild() -> None:
    text = REPLAY_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "AlphaOps Replay Sidecars",
        "source_run_id",
        "gh run download",
        "tools/build_replay_price_cache.py",
        "tools/build_operating_target_books.py",
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
        "--refresh-stale-days 2",
        "outputs/reports/main_monthly_weights.csv",
        "outputs/reports/operating_main_target_book.csv",
        "outputs/reports/operating_concentrated_target_book.csv",
        "outputs/reports/operating_target_books_*",
        "outputs/target_snapshots/",
        "outputs/data_readiness/",
        "outputs/reports/regime_by_month.csv",
        "outputs/position_risk_weekly_validation/main",
        "outputs/position_risk_weekly_validation/main_v2",
        "tools/run_broker_ledger_replay.py",
        "--target-book outputs/reports/operating_main_target_book.csv",
        "--target-book outputs/reports/operating_concentrated_target_book.csv",
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
        "outputs/broker_execution_policy_replay/",
        "outputs/broker_gap_attribution/",
        "outputs/broker_trade_journal/",
        "outputs/account_ledger_preview/",
        "outputs/live_trading_safety/",
        "outputs/live_trading_risk_controls/",
        "outputs/monster_recommendations/",
        "outputs/operating_snapshot/",
        "outputs/user_portfolio_reports/",
        "outputs/account_evaluation/",
        "outputs/full_rebuild_logs/target_snapshot_archive.log",
        "outputs/full_rebuild_logs/data_readiness.log",
        "tools/run_theme_leadership_tape.py",
        "tools/run_theme_concentration_challenger.py",
        "tools/run_portfolio_goal_search.py",
        "tools/run_account_evaluation.py",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/replay_outputs",
    ]:
        assert token in text, token
    for forbidden in [
        "python run_local.py --full",
        "Refresh SEC companyfacts bulk archive",
        "Full Rebuild START",
    ]:
        assert forbidden not in text, forbidden


def test_free_data_lake_workflow_restores_drive_and_runs_proxy_replay() -> None:
    text = FREE_DATA_WORKFLOW.read_text(encoding="utf-8")
    for token in [
        "Free Data Lake Bootstrap",
        "tools/run_free_data_lake_bootstrap.py",
        "tools/run_free_data_engine_validation.py",
        "tools/check_10y_backtest_readiness.py",
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
        "outputs/free_data_engine_validation/",
        "outputs/ten_year_backtest_readiness/",
        "CAGR",
        "MaxDD",
    ]:
        assert token in text, token
    for forbidden in [
        "--sec-companyfacts",
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
        "manifests/free_data",
        "companyfacts.zip",
        "outputs/data_readiness/",
        "outputs/full_rebuild_logs/data_readiness.log",
        "data-readiness-preflight-${{ github.run_id }}",
        "research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/data_readiness",
        "RCLONE_CONFIG_GDRIVE",
        "GOOGLE_SERVICE_ACCOUNT_KEY",
    ]:
        assert token in text, token
    for forbidden in [
        "python run_local.py --full",
        "git commit",
        "tools/run_broker_ledger_replay.py",
    ]:
        assert forbidden not in text, forbidden


def main() -> int:
    test_workflow_yaml_files_parse()
    test_workflow_keeps_monthly_books()
    test_cloud_results_copy_is_not_nested()
    test_pipeline_exports_monthly_books()
    test_workflow_runs_latest_diagnostics_sidecars()
    test_fast_replay_workflow_uses_artifacts_not_full_rebuild()
    test_free_data_lake_workflow_restores_drive_and_runs_proxy_replay()
    test_free_data_daily_workflow_updates_metrics_after_close()
    test_data_readiness_preflight_workflow_restores_drive_and_audits_without_full_rebuild()
    print("workflow artifact smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
