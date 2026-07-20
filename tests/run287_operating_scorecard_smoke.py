#!/usr/bin/env python3
"""Smoke checks for the canonical private Run287 operating scorecard."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_operating_scorecard import (  # noqa: E402
    build_scorecard,
    load_registry,
    render_report,
    validate_metric_migration,
)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(root: Path, *, paper: bool = True, reset_count: int = 0) -> Path:
    p6 = root / "p6.json"
    write_json(p6, {
        "rank_stability": {"mean_score_spearman": 0.6, "mean_top_10_overlap": 0.3, "mean_top_30_overlap": 0.4},
        "sector_etf_excess_status": "BLOCKED_MISSING_PINNED_SECTOR_ETF_CACHE",
        "selection_quality_delta": [{"selected_minus_control": 0.01}],
    })
    p6_metrics = root / "p6_metrics.csv"
    pd.DataFrame([{
        "window": "oos", "portfolio": "main", "cohort": "selected", "horizon_sessions": 63,
        "resolved_count": 10, "mean_return": 0.1, "median_return": 0.08,
        "mean_spy_excess": 0.02, "mean_qqq_excess": 0.01, "mean_sector_neutral_excess": 0.03,
    }]).to_csv(p6_metrics, index=False)
    p5 = root / "p5.json"
    portfolio = {
        "control_parity": {"expected": {"cagr": 0.35, "max_dd": -0.25, "sharpe": 1.2,
                                          "trade_count": 5, "total_fees_usd": 10}},
        "holding_statistics": {"completed_lot_count": 5, "median_holding_days": 30,
                               "pct_held_365d_plus": 0, "exit_reentry_churn_63_sessions": 1},
        "sell_taxonomy_counts": {"RISK_EXIT": 2},
        "counterfactual_summary": {"status": "NO_EVENTS"},
        "cost_sensitivity": {
            "25bps": {"control_fees": 10, "control_cagr": 0.35},
            "50bps": {"control_fees": 20, "control_cagr": 0.34},
            "100bps": {"control_fees": 40, "control_cagr": 0.32},
        },
    }
    write_json(p5, {"control_parity_passed": True,
                    "portfolios": {"main": portfolio, "concentrated": portfolio}})
    p4 = root / "p4.json"
    write_json(p4, {"double_count_check_passed": True, "reason_reconciliation_passed": True})
    p4_metrics = root / "p4_metrics.csv"
    pd.DataFrame([
        {"portfolio": name, "mode": "DGS3MO_CARRY", "average_reserve_weight": 0.2,
         "latest_reserve_weight": 0.1, "reserve_return_contribution_usd_vs_broker_cash": 100,
         "cash_interest_accrued_usd": 50, "reserve_turnover_usd": 0, "reserve_fees_usd": 0,
         "delta_cagr_pp_vs_broker_cash": 0.5}
        for name in ("main", "concentrated")
    ]).to_csv(p4_metrics, index=False)
    reasons = root / "reasons.json"
    write_json(reasons, [{"reason_weights": {"capacity_unallocated": 0.2, "crisis_reserve": 0,
                                              "reentry_pending": 0, "data_block_reserve": 0,
                                              "transaction_buffer": 0, "residual_cash": 0}}])
    crisis = root / "crisis.json"
    write_json(crisis, {
        "status": "REJECTED_POLICY_PROMOTION",
        "full_period": {"mdd_delta": 0.02, "cagr_delta": -0.1},
        "state_evaluation": {
            "defense_episode_count": 2, "false_defense_episode_count": 1,
            "cash_trap_snapshot_count": 3, "false_reentry_redefense_count": 1,
            "reentry_recovery_business_days": {
                level: {"median": index + 1} for index, level in enumerate(("25", "50", "75", "95"))
            },
        },
    })
    forward = root / "forward.json"
    write_json(forward, {
        "coverage": {"decision_date_count": 1},
        "review_readiness": {
            "status": "UNDERPOWERED", "review_ready": False,
            "distinct_true_forward_ticker_count": 10,
            "sample_checks": {"decision_week_blocks_21d": {"actual": 0},
                              "decision_week_blocks_63d": {"actual": 0}},
            "cohort_metrics": {"true_forward_arm": {
                horizon: {"completed_count": 0} for horizon in ("21d", "63d", "126d")
            }},
        },
    })
    paper_path = root / "paper.json"
    integrity_path = root / "integrity.json"
    if paper:
        write_json(paper_path, {"integrity": {"account_reset_count": reset_count}, "fill_count": 2})
        write_json(integrity_path, {"verified": True})

    files = {
        "p6_selection_summary": (p6, "json", True, "historical", "selection_quality"),
        "p6_selection_metrics": (p6_metrics, "csv", True, "historical", "selection_quality"),
        "p5_hold_exit": (p5, "json", True, "historical", "holding_exit_execution"),
        "p4_reserve_summary": (p4, "json", True, "historical", "reserve"),
        "p4_reserve_metrics": (p4_metrics, "csv", True, "historical", "reserve"),
        "p4_main_reserve_reasons": (reasons, "json", True, "historical", "reserve"),
        "p4_concentrated_reserve_reasons": (reasons, "json", True, "historical", "reserve"),
        "p3_main_crisis": (crisis, "json", True, "historical", "risk_defense_reentry"),
        "p3_concentrated_crisis": (crisis, "json", True, "historical", "risk_defense_reentry"),
        "current_paper_summary": (paper_path, "json", False, "current_paper_execution", "execution_integrity"),
        "current_paper_integrity": (integrity_path, "json", False, "current_paper_execution", "execution_integrity"),
        "true_forward_summary": (forward, "json", True, "true_forward", "forward_evidence"),
    }
    sources = []
    for source_id, (path, fmt, required, lane, section) in files.items():
        sources.append({
            "id": source_id, "evidence_class": lane, "section": section,
            "path": str(path), "format": fmt,
            "expected_sha256": digest(path) if path.exists() else None,
            "as_of_date": "2026-07-10", "metric_mode": "fixture",
            "required": required, "disposition": "ABSORBED_SOURCE",
        })
    registry = root / "registry.json"
    write_json(registry, {
        "schema_version": "run287-operating-scorecard-source-registry-v1",
        "metric_definition_version": "run287-operating-scorecard-metrics-v1",
        "migration_note": "initial fixture", "scorecard_as_of_date": "2026-07-20",
        "sources": sources,
    })
    return registry


def test_scorecard_keeps_evidence_lanes_and_provenance_separate() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td))
        scorecard = build_scorecard(load_registry(registry_path), source_registry_path=registry_path)
        assert scorecard["headline_performance_trust"] == "TRUSTED"
        assert scorecard["evidence_status"] == {
            "historical": "AVAILABLE_PARTIAL",
            "current_paper_execution": "AVAILABLE",
            "true_forward": "UNDERPOWERED",
        }
        assert scorecard["historical_acceptance_overwritten_by_forward"] is False
        assert scorecard["source_artifacts_copied"] is False
        assert scorecard["absorbed_source_count"] >= 2
        assert all(row["provenance"]["source_sha256"] for row in scorecard["metrics"] if row["status"] == "AVAILABLE")
        assert "UNAVAILABLE" in render_report(scorecard)


def test_missing_optional_paper_is_unavailable_not_zero() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td), paper=False)
        scorecard = build_scorecard(load_registry(registry_path), source_registry_path=registry_path)
        assert scorecard["evidence_status"]["current_paper_execution"] == "UNAVAILABLE"
        rows = [row for row in scorecard["metrics"] if row["evidence_class"] == "current_paper_execution"]
        assert rows and all(row["value"] is None for row in rows)


def test_integrity_error_marks_headline_not_trusted() -> None:
    with tempfile.TemporaryDirectory() as td:
        registry_path = make_fixture(Path(td), reset_count=1)
        scorecard = build_scorecard(load_registry(registry_path), source_registry_path=registry_path)
        assert scorecard["headline_performance_trust"] == "NOT_TRUSTED"
        assert any("account_reset_count" in value for value in scorecard["integrity_errors"])
        assert all(row["trust"] == "NOT_TRUSTED" for row in scorecard["headline_performance"].values())


def test_metric_definition_change_requires_migration_note() -> None:
    previous = {"metric_definition_version": "v1"}
    try:
        validate_metric_migration(previous, {"metric_definition_version": "v2", "migration_note": ""})
    except ValueError as exc:
        assert "migration note" in str(exc)
    else:
        raise AssertionError("missing migration note must fail")
    validate_metric_migration(previous, {"metric_definition_version": "v2", "migration_note": "units changed"})


def main() -> int:
    test_scorecard_keeps_evidence_lanes_and_provenance_separate()
    test_missing_optional_paper_is_unavailable_not_zero()
    test_integrity_error_marks_headline_not_trusted()
    test_metric_definition_change_requires_migration_note()
    print("run287_operating_scorecard_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
