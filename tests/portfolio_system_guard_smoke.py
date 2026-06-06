#!/usr/bin/env python3
"""Smoke tests for the portfolio system target guard."""
from __future__ import annotations

import csv
import sys
import json
import os
import shutil
import uuid
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_portfolio_system_guard import run  # noqa: E402


class TestWorkspace:
    def __init__(self, name: str) -> None:
        base = Path(os.environ.get("R1000_TEST_TMPDIR", REPO_ROOT.parent / "_tmp"))
        self.path = base / f"{name}_{uuid.uuid4().hex}"

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def feature_source_coverage_fixture() -> dict:
    groups = [
        "price_momentum",
        "macro_regime",
        "theme_leadership",
        "sec_smart_money",
        "quality_confirmation",
        "broker_policy",
    ]
    books = {}
    for portfolio in ("main", "concentrated"):
        books[portfolio] = {
            "categories": {group: {"present_columns": [f"{group}_field"]} for group in groups},
            "pit_available_from_check": {
                "available_from_columns": ["latest_available_from"],
                "rows_with_any_future_available_from": 0,
                "max_future_days": 0,
            },
        }
    return {
        "status": "ok",
        "overall": {
            "pit_future_available_from_rows": 0,
            "available_from_column_count": 2,
            "missing_feature_groups_by_portfolio": {group: [] for group in groups},
        },
        "books": books,
    }


def test_portfolio_system_guard_reports_target_gaps() -> None:
    with TestWorkspace("portfolio_system_guard") as tmp:
        out_dir = tmp / "guard"
        latest = tmp / "latest"
        write_json(
            latest / "broker_replay" / "main" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.21,
                "max_dd": -0.36,
                "sharpe": 0.97,
                "avg_cash_weight": 0.24,
                "end_date": "2026-01-10",
                "target_book": "outputs/reports/operating_main_target_book.csv",
            },
        )
        write_json(latest / "broker_replay" / "main" / "account_state_latest.json", {"cash_weight": 0.24})
        write_json(
            latest / "broker_replay" / "concentrated" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.34,
                "max_dd": -0.40,
                "sharpe": 1.09,
                "avg_cash_weight": 0.31,
                "end_date": "2026-01-10",
                "target_book": "outputs/reports/operating_concentrated_target_book.csv",
                "target_book_filter": {"target_stock_names": "4", "weighting_mode": "score_power"},
            },
        )
        write_json(latest / "broker_replay" / "concentrated" / "account_state_latest.json", {"cash_weight": 0.31})
        write_json(latest / "backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(latest / "concentrated_backtest_metrics.json", {"strategy_cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_json(
            latest / "operating_event_backtest" / "operating_event_backtest_summary.json",
            {
                "status": "completed",
                "daily_risk_overlay_validated": True,
                "daily_risk_action_evidence_count": 2,
                "full_nonmonthly_entry_replacement_validated": False,
            },
        )
        write_json(
            latest / "data_readiness" / "summary.json",
            {
                "status": "ready",
                "ready_for_fullrun": True,
                "ready_for_policy_replay": True,
                "blockers": [],
                "policy_replay_blockers": [],
                "warnings": [],
                "feature_source_coverage": feature_source_coverage_fixture(),
            },
        )
        write_json(
            latest / "reports" / "dataset_coverage_audit.json",
            {
                "status": "completed",
                "sec_enriched_candidate_present": True,
                "sec_enriched_evidence_summary": {"rows_with_smart_money_evidence": 10},
            },
        )
        write_json(
            latest / "sec_enriched_candidate_replay" / "summary.json",
            {"status": "ok", "rows_with_smart_money_evidence": 10},
        )
        write_json(
            latest / "alphaops_vnext" / "summary.json",
            {
                "status": "completed",
                "candidate_book": "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv",
                "production_policy": "alphaops_vnext_production",
            },
        )
        write_json(
            latest / "alphaops_vnext" / "production_activation.json",
            {
                "production_policy": "alphaops_vnext_production",
                "production_applied": True,
                "sidecar_only": False,
                "sidecar_applied_to_production": True,
                "current_holdings_source": "alphaops_vnext_policy_target_book",
            },
        )
        write_json(
            latest / "full_rebuild_logs" / "sec_evidence_restore_manifest.json",
            {"restored": ["data_pit/sec", "data_pit/etf_holdings", "data_pit/macro"], "missing": [], "errors": []},
        )
        write_json(latest / "theme_leadership_tape" / "summary.json", {"top_theme": "ai_compute", "top_theme_state": "emerging_leader"})
        write_json(latest / "macro_circuit_filter" / "main" / "diagnostics.json", {"status": "completed"})
        write_json(latest / "macro_circuit_filter" / "concentrated" / "diagnostics.json", {"status": "completed"})
        write_csv(latest / "reports" / "main_monthly_weights.csv", [{"rebalance_date": "2025-12-31", "ticker": "AAA", "weight": 1.0}])
        write_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            [{"rebalance_date": "2025-12-31", "ticker": "AAA", "weight": 1.0, "target_stock_names": 4, "weighting_mode": "score_power"}],
        )
        write_csv(latest / "reports" / "operating_main_target_book.csv", [{"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.0}])
        write_csv(
            latest / "reports" / "operating_concentrated_target_book.csv",
            [{"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.0, "target_stock_names": 4, "weighting_mode": "score_power"}],
        )
        write_csv(latest / "portfolio_latest.csv", [{"ticker": "AAA", "weight": 0.5}, {"ticker": "BBB", "weight": 0.5}])
        write_csv(
            latest / "concentrated_portfolio_latest.csv",
            [{"rebalance_date": "2026-01-10", "ticker": "AAA", "weight": 1.0, "target_stock_names": 4, "weighting_mode": "score_power"}],
        )
        write_csv(
            latest / "broker_replay" / "main" / "positions_latest.csv",
            [{"ticker": f"T{i}", "weight": 0.1} for i in range(10)],
        )
        write_csv(
            latest / "operating_snapshot" / "current_operating_holdings_latest.csv",
            [{"portfolio_kind": "main", "ticker": "AAA", "current_weight": 1.0}],
        )
        result = run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(out_dir),
                main_cagr_target=0.30,
                main_max_dd_target=-0.20,
                concentrated_cagr_target=0.50,
                concentrated_max_dd_target=-0.25,
                strict_targets=False,
            )
        )
        assert result["overall_status"] == "blocked"
        assert result["targets_pass"] is False
        assert len(result["portfolio_status"]) == 2
        main = result["portfolio_status"][0]
        concentrated = result["portfolio_status"][1]
        assert main["portfolio"] == "main"
        assert concentrated["portfolio"] == "concentrated"
        assert main["metric_source"] == "broker_ledger_next_close"
        assert concentrated["metric_source"] == "broker_ledger_next_close"
        assert main["cagr_gap_pp"] > 0
        assert concentrated["cagr_gap_pp"] > 0
        main_metric_check = next(row for row in result["error_checks"] if row["check"] == "main_metrics_available")
        assert main_metric_check["severity"] in {"ok", "warn"}
        checks = {row["check"]: row for row in result["error_checks"]}
        assert checks["main_target_book_reaches_broker_end"]["passed"] is True
        assert checks["main_operating_target_book_available"]["passed"] is True
        assert checks["main_historical_research_book_reaches_broker_end"]["severity"] == "warn"
        assert checks["main_broker_replay_uses_operating_target_book"]["passed"] is True
        assert checks["concentrated_operating_target_book_available"]["passed"] is True
        assert checks["concentrated_broker_replay_uses_operating_target_book"]["passed"] is True
        assert checks["operating_event_backtest_available"]["passed"] is True
        assert checks["daily_risk_overlay_backtest_validated"]["passed"] is True
        assert checks["full_nonmonthly_entry_replacement_backtest_validated"]["severity"] == "warn"
        assert checks["data_readiness_ready_for_production_replay"]["passed"] is True
        assert checks["sec_enriched_candidate_materialized_for_audit"]["passed"] is True
        assert checks["alphaops_vnext_uses_sec_enriched_candidate_book"]["passed"] is True
        assert checks["alphaops_vnext_production_flags_correct"]["passed"] is True
        assert checks["main_official_broker_metrics_valid_for_production"]["passed"] is True
        assert checks["concentrated_official_broker_metrics_valid_for_production"]["passed"] is True
        assert checks["sec_drive_restore_manifest_available"]["passed"] is True
        assert checks["theme_leadership_tape_available"]["passed"] is True
        assert checks["macro_circuit_diagnostics_available"]["passed"] is True
        assert checks["feature_source_coverage_available"]["passed"] is True
        assert checks["feature_source_coverage_pit_available_from_clean"]["passed"] is True
        assert checks["feature_source_groups_present_for_target_books"]["passed"] is True
        assert checks["current_only_operating_holdings_available"]["passed"] is True
        assert checks["main_current_position_count_near_latest_target_count"]["passed"] is False
        assert checks["concentrated_replay_filter_matches_latest_target"]["passed"] is True
        cash_trap = {row["portfolio"]: row for row in result["cash_trap_guard"]}
        assert cash_trap["main"]["cash_trap"] is True
        assert cash_trap["concentrated"]["cash_trap"] is True
        assert "avg_cash_high_without_mdd_target_pass" in cash_trap["main"]["reasons"]
        assert result["data_quality_update_plan"]["metric_contract"]["official_source"] == "broker_ledger_next_close"
        assert result["data_quality_update_plan"]["readiness"]["ready_for_policy_replay"] is True
        assert result["data_quality_update_plan"]["feature_source_coverage"]["pit_future_available_from_rows"] == 0
        assert result["data_quality_update_plan"]["large_data_restore"]["manifest_available"] is True
        assert (out_dir / "system_guard_report.md").exists()
        assert (out_dir / "target_gap.json").exists()
        assert (out_dir / "data_quality_update_plan.json").exists()


def test_portfolio_system_guard_blocks_stale_historical_broker_replay() -> None:
    with TestWorkspace("portfolio_system_guard_stale") as tmp:
        out_dir = tmp / "guard"
        latest = tmp / "latest"
        write_json(
            latest / "broker_replay" / "main" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.21,
                "max_dd": -0.30,
                "sharpe": 1.0,
                "end_date": "2026-05-08",
                "target_book": "outputs/reports/main_monthly_weights.csv",
            },
        )
        write_json(
            latest / "broker_replay" / "concentrated" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.31,
                "max_dd": -0.39,
                "sharpe": 1.0,
                "end_date": "2026-05-08",
                "target_book": "outputs/reports/concentrated_strategy_holdings.csv",
            },
        )
        write_csv(latest / "reports" / "main_monthly_weights.csv", [{"rebalance_date": "2026-02-27", "ticker": "AAA", "weight": 0.72}, {"rebalance_date": "2026-02-27", "ticker": "CASH", "weight": 0.28}])
        write_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            [{"rebalance_date": "2026-02-27", "ticker": "AAA", "weight": 1.0}],
        )
        write_csv(latest / "portfolio_latest.csv", [{"ticker": "BBB", "weight": 1.0}])
        write_csv(latest / "concentrated_portfolio_latest.csv", [{"ticker": "BBB", "weight": 1.0}])
        result = run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(out_dir),
                main_cagr_target=0.30,
                main_max_dd_target=-0.20,
                concentrated_cagr_target=0.50,
                concentrated_max_dd_target=-0.25,
                strict_targets=False,
            )
        )
        checks = {row["check"]: row for row in result["error_checks"]}
        assert result["overall_status"] == "blocked"
        assert checks["main_target_book_reaches_broker_end"]["severity"] == "error"
        assert checks["main_operating_target_book_available"]["severity"] == "error"
        assert checks["main_broker_replay_uses_operating_target_book"]["severity"] == "error"
        assert checks["concentrated_target_book_reaches_broker_end"]["severity"] == "error"
        assert checks["concentrated_operating_target_book_available"]["severity"] == "error"
        assert checks["concentrated_broker_replay_uses_operating_target_book"]["severity"] == "error"


def test_portfolio_system_guard_blocks_data_readiness_failures() -> None:
    with TestWorkspace("portfolio_system_guard_data") as tmp:
        out_dir = tmp / "guard"
        latest = tmp / "latest"
        for portfolio in ("main", "concentrated"):
            target = f"outputs/reports/operating_{portfolio}_target_book.csv"
            write_json(
                latest / "broker_replay" / portfolio / "metrics.json",
                {
                    "status": "completed",
                    "metric_mode": "broker_ledger_next_close",
                    "valid_for_production": True,
                    "cagr": 0.60,
                    "max_dd": -0.10,
                    "sharpe": 2.0,
                    "end_date": "2026-01-10",
                    "target_book": target,
                },
            )
        write_csv(latest / "reports" / "main_monthly_weights.csv", [{"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.0}])
        write_csv(latest / "reports" / "concentrated_strategy_holdings.csv", [{"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.0}])
        write_csv(latest / "reports" / "operating_main_target_book.csv", [{"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.0}])
        write_csv(latest / "reports" / "operating_concentrated_target_book.csv", [{"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.0}])
        write_csv(latest / "portfolio_latest.csv", [{"ticker": "AAA", "weight": 1.0}])
        write_csv(latest / "concentrated_portfolio_latest.csv", [{"ticker": "AAA", "weight": 1.0}])
        feature_coverage = feature_source_coverage_fixture()
        feature_coverage["status"] = "pit_review"
        feature_coverage["overall"]["pit_future_available_from_rows"] = 3
        write_json(
            latest / "data_readiness" / "summary.json",
            {
                "status": "blocked",
                "ready_for_fullrun": False,
                "ready_for_policy_replay": False,
                "blockers": ["no SEC companyfacts archive was found"],
                "policy_replay_blockers": ["macro data was not found"],
                "warnings": ["canonical data_raw/free/sec/companyfacts.zip is missing"],
                "feature_source_coverage": feature_coverage,
            },
        )
        write_json(
            latest / "reports" / "dataset_coverage_audit.json",
            {
                "status": "completed",
                "sec_enriched_candidate_present": False,
                "sec_enriched_evidence_summary": {"rows_with_smart_money_evidence": 5},
            },
        )
        write_json(latest / "sec_enriched_candidate_replay" / "summary.json", {"rows_with_smart_money_evidence": 5})
        write_json(
            latest / "alphaops_vnext" / "summary.json",
            {
                "candidate_book": "outputs/reports/candidate_replay_book.csv",
                "production_policy": "alphaops_vnext_production",
            },
        )
        write_json(latest / "alphaops_vnext" / "production_activation.json", {"production_policy": "alphaops_vnext_production"})

        result = run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(out_dir),
                main_cagr_target=0.30,
                main_max_dd_target=-0.20,
                concentrated_cagr_target=0.50,
                concentrated_max_dd_target=-0.25,
                strict_targets=False,
            )
        )
        checks = {row["check"]: row for row in result["error_checks"]}
        assert result["overall_status"] == "blocked"
        assert checks["data_readiness_ready_for_production_replay"]["severity"] == "error"
        assert checks["feature_source_coverage_pit_available_from_clean"]["severity"] == "error"
        assert checks["sec_enriched_candidate_materialized_for_audit"]["severity"] == "error"
        assert checks["alphaops_vnext_uses_sec_enriched_candidate_book"]["severity"] == "error"


if __name__ == "__main__":
    test_portfolio_system_guard_reports_target_gaps()
    test_portfolio_system_guard_blocks_stale_historical_broker_replay()
    test_portfolio_system_guard_blocks_data_readiness_failures()
    print("portfolio_system_guard_smoke: ok")
