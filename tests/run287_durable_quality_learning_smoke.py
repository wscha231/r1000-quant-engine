#!/usr/bin/env python3
"""Synthetic checks for the durable-quality and decision-learning sidecar."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_durable_quality_learning as quality  # noqa: E402


def fixture_context() -> pd.DataFrame:
    rows = []
    for idx in range(12):
        strong = idx == 11
        rows.append(
            {
                "ticker": f"T{idx:02d}",
                "Name": f"Test {idx}",
                "sector": "Information Technology",
                "industry": "Software",
                "fund_effective_accepted": "2026-07-10T20:00:00Z",
                "feature_available_from": "2026-07-13T20:00:00Z",
                "assets": 100.0,
                "liabilities": 15.0 if strong else 40.0 + idx,
                "debt_to_equity_delta_4q": -0.2 if strong else 0.02 * idx,
                "interest_coverage": 25.0 if strong else 2.0 + idx,
                "fcf_margin": 0.35 if strong else 0.02 * idx,
                "dilution_penalty": -0.02 if strong else 0.01 * idx,
                "roic_approx": 0.40 if strong else 0.02 * idx,
                "gross_margin_ttm": 0.80 if strong else 0.20 + 0.02 * idx,
                "op_margin_ttm": 0.45 if strong else 0.01 * idx,
                "margin_stability_8q": 0.20 if strong else -0.10 + 0.01 * idx,
                "capital_efficiency_score": 2.0 if strong else -0.5 + 0.1 * idx,
                "sales_cagr_3y": 0.35 if strong else 0.01 * idx,
                "rd_intensity": 0.25 if strong else 0.01 * idx,
                "rule_of_40": 0.70 if strong else 0.02 * idx,
                "rs_sector_6m": 0.50 if strong else -0.3 + 0.04 * idx,
                "near_52w_high_pct": 0.99 if strong else 0.40 + 0.03 * idx,
                "price_above_ma200": 1.0 if strong else float(idx >= 6),
                "dynamic_leader_score": 2.0 if strong else -1.0 + 0.1 * idx,
                "score_total": float(idx),
                "ranking_eligible": True,
            }
        )
    return pd.DataFrame(rows)


def test_quality_separates_proxy_coverage_and_fixed_horizon_grading() -> None:
    context = fixture_context()
    universe = quality.build_quality_universe(
        context, pd.Timestamp("2026-07-14T05:00:00Z")
    )
    best = universe.set_index("ticker").loc["T11"]
    assert best["candidate_status"] == "REVIEW_CANDIDATE_PARTIAL"
    assert best["debt_measurement_status"] == "TOTAL_LIABILITIES_PROXY_ONLY"
    assert float(best["exact_debt_component_coverage"]) == 0.0
    assert bool(best["textual_business_moat_review_required"])

    current = pd.DataFrame(
        [
            {
                "ticker": "T11",
                "portfolio_kind": "main",
                "scenario": "strict_registered_current",
                "prior_weight": 0.0,
                "operating_target_weight": 0.10,
                "selector_selected": True,
                "outcome_21d_status": "completed",
                "outcome_21d_spy_excess_total_return": 0.05,
                "outcome_63d_status": "completed",
                "outcome_63d_spy_excess_total_return": 0.08,
            },
            {
                "ticker": "T00",
                "portfolio_kind": "main",
                "scenario": "strict_registered_current",
                "prior_weight": 0.0,
                "operating_target_weight": 0.0,
                "selector_selected": False,
                "outcome_21d_status": "completed",
                "outcome_21d_spy_excess_total_return": 0.02,
                "outcome_63d_status": "pending_not_elapsed_or_price_unavailable",
                "outcome_63d_spy_excess_total_return": np.nan,
            },
        ]
    )
    risk = pd.DataFrame(
        [
            {
                "portfolio_kind": "main",
                "ticker": "T11",
                "risk_state": "ALERT",
                "risk_advisory_action": "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW",
            }
        ]
    )
    checklist = quality.build_trade_checklist(current, universe, risk)
    best_check = checklist.set_index("ticker").loc["T11"]
    assert best_check["buy_hold_checklist_status"] == "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW"
    assert not bool(best_check["portfolio_action_authorized"])
    notebook = quality.build_mistake_notebook(checklist)
    grades = notebook.set_index("ticker")
    assert int(grades.loc["T11", "grade_horizon"]) == 63
    assert grades.loc["T11", "answer_label"] == "CORRECT_OWN"
    assert int(grades.loc["T00", "grade_horizon"]) == 21
    assert grades.loc["T00", "answer_label"] == "MISSED_WINNER"
    assert not bool(grades["automatic_checklist_change_allowed"].any())


def test_end_to_end_writes_review_only_manifest() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-quality-") as raw:
        root = Path(raw)
        context_path = root / "context.parquet"
        status_path = root / "status.parquet"
        output = root / "out"
        fixture_context().to_parquet(context_path, index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "T11",
                    "portfolio_kind": "main",
                    "scenario": "strict_registered_current",
                    "prior_weight": 0.0,
                    "operating_target_weight": 0.10,
                    "selector_selected": True,
                    "outcome_21d_status": "pending_not_elapsed_or_price_unavailable",
                    "outcome_63d_status": "pending_not_elapsed_or_price_unavailable",
                }
            ]
        ).to_parquet(status_path, index=False)
        result = quality.build(
            argparse.Namespace(
                selection_context=str(context_path),
                current_status=str(status_path),
                decision_time_utc="2026-07-14T05:00:00Z",
                risk_watch="",
                output_dir=str(output),
            )
        )
        assert result["status"].endswith("REVIEW_ONLY")
        assert result["answer_ready_count"] == 0
        assert result["exact_debt_complete_count"] == 0
        assert not result["rank_mutated"]
        assert not result["orders_generated"]
        assert not result["fullrun_executed"]
        manifest = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert manifest["automatic_checklist_change_allowed"] is False
        assert (output / "report.md").is_file()


if __name__ == "__main__":
    test_quality_separates_proxy_coverage_and_fixed_horizon_grading()
    test_end_to_end_writes_review_only_manifest()
    print("run287_durable_quality_learning_smoke: PASS")
