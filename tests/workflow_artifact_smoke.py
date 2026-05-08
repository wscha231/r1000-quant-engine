#!/usr/bin/env python3
"""Static checks for full rebuild artifact/export hygiene."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"
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
    "outputs/reports/leader_drop_diagnostics_*.csv",
    "outputs/reports/leader_drop_diagnostics_summary.json",
    "outputs/reports/leader_drop_diagnostics_report.md",
    "outputs/reports/dataset_coverage_audit.*",
]


def test_workflow_keeps_monthly_books() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in MONTHLY_BOOK_TOKENS:
        assert token in text, token
    assert "outputs/equity_curve.csv" in text
    for token in (
        "outputs/main_v2_backtest/",
        "outputs/concentrated_policy_replay/",
        "outputs/concentrated_trade_journal/",
        "outputs/alpha_sprint_backtest/",
        "outputs/position_aware_risk_replay/",
        "outputs/governance_catalyst/",
        "outputs/style_regime_report/",
        "outputs/macro_policy_engine/",
        "outputs/cash_policy/",
        "outputs/main_cash_drag_replay/",
        "outputs/crisis_reentry_replay/",
        "outputs/monster_lifecycle_replay/",
        "outputs/lifecycle_review_overlay_main/",
        "outputs/monster_lifecycle_review_main/",
        "outputs/monster_lifecycle_review_concentrated/",
        "outputs/historical_trade_journey/",
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
        "tools/run_dataset_coverage_audit.py",
        "outputs/full_rebuild_logs/leader_drop_diagnostics_sidecar.log",
        "outputs/full_rebuild_logs/governance_catalyst_report.log",
        "outputs/full_rebuild_logs/style_regime_report.log",
        "outputs/full_rebuild_logs/macro_policy_engine.log",
        "outputs/full_rebuild_logs/cash_policy_attribution.log",
        "outputs/full_rebuild_logs/main_cash_drag_replay.log",
        "outputs/full_rebuild_logs/crisis_reentry_replay.log",
        "outputs/full_rebuild_logs/dataset_coverage_audit.log",
        "tools/build_concentrated_trade_journal.py",
        "--extra-trades outputs/concentrated_trade_journal/trades.csv",
        "auto_learning_promote_live",
    ]:
        assert token in text, token


def main() -> int:
    test_workflow_keeps_monthly_books()
    test_cloud_results_copy_is_not_nested()
    test_pipeline_exports_monthly_books()
    test_workflow_runs_latest_diagnostics_sidecars()
    print("workflow artifact smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
