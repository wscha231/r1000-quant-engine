#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import verify_run287_complete_current_cross_section as verifier


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path), "exists": True}


def fixture(root: Path, *, missing_scaled_value: float = 0.0) -> argparse.Namespace:
    valuation_date = "2026-07-10"
    available = "2026-07-12T03:00:00Z"
    decision = "2026-07-12T03:05:00Z"

    technical_latest_path = root / "technical_latest.csv"
    technical_audit_path = root / "technical_audit.csv"
    action_audit_path = root / "action_audit.csv"
    official_document_path = root / "official.htm"
    pd.DataFrame({"ticker": ["AAA", "DD"]}).to_csv(
        technical_latest_path, index=False
    )
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "status": "parity_pass",
                "ticker_parity_pass": True,
                "frozen_reference_available": True,
                "parity_applicable": True,
                "technical_current_row_ready": True,
                "decision_ranking_allowed": False,
            },
            {
                "ticker": "DD",
                "status": "current_only_ready_exact_corporate_action",
                "ticker_parity_pass": True,
                "frozen_reference_available": True,
                "parity_applicable": False,
                "technical_current_row_ready": True,
                "decision_ranking_allowed": False,
            },
        ]
    ).to_csv(technical_audit_path, index=False)
    pd.DataFrame(
        [
            {
                "ticker": "DD",
                "failed_frozen_parity_ratio": 0.8333333333333334,
                "frozen_parity_failure_preserved": True,
                "corporate_action_quarantine": True,
                "current_technical_recompute_all_match": True,
                "current_context_append_allowed": True,
                "decision_ranking_allowed": False,
            }
        ]
    ).to_csv(action_audit_path, index=False)
    official_document_path.write_text(
        "official SEC reverse split fixture", encoding="utf-8"
    )
    technical_manifest_path = root / "technical_manifest.json"
    write_json(
        technical_manifest_path,
        {
            "status": "TECHNICAL_PARITY_READY_MACRO_FUNDAMENTAL_BLOCKED",
            "valuation_price_cutoff_date": valuation_date,
            "current_cross_section_complete": True,
            "current_cross_section_verification_passed": False,
            "corporate_action_recovery_ready": True,
            "corporate_action_quarantine": True,
            "frozen_parity_reclassified_as_pass": False,
            "network_requests_executed": 1,
            "decision_ranking_allowed": False,
            "selector_executed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "source_inputs_mutated": False,
            "price_refresh_resolved_ticker_count": 1,
            "terminal_nontradable_tickers": ["TERM"],
            "parity": {"ticker_threshold": 0.90},
            "delta_eligibility": {"no_frozen_reference_tickers": []},
            "sec_contract": {
                "accession_number": "0001666700-26-000046",
                "exact_acceptance": True,
                "future_row_count": 0,
            },
            "outputs": {
                "latest_technical_features": record(technical_latest_path),
                "ticker_audit": record(technical_audit_path),
                "corporate_action_recovery_audit": record(action_audit_path),
                "official_sec_document": record(official_document_path),
            },
        },
    )

    universe_path = root / "universe.csv"
    refresh_path = root / "refresh.csv"
    pd.DataFrame(
        {
            "ticker": ["AAA", "DD", "TERM", "CASH"],
            "is_equity_issuer": [True, True, True, False],
        }
    ).to_csv(universe_path, index=False)
    pd.DataFrame({"ticker": ["AAA", "DD", "TERM"]}).to_csv(
        refresh_path, index=False
    )
    preflight_manifest_path = root / "preflight_manifest.json"
    write_json(
        preflight_manifest_path,
        {
            "status": "BLOCKED_BOUNDED_DECISION_REFRESH",
            "decision_date": valuation_date,
            "quick_rescore_dispatched": False,
            "target_books_mutated": False,
            "network_requests_executed": 0,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "fullrun_executed": False,
            "source_inputs_mutated": False,
            "source_inputs": {"universe_snapshot": record(universe_path)},
            "outputs": {"refresh_batches": record(refresh_path)},
        },
    )
    model_meta_path = root / "model_meta.json"
    write_json(
        model_meta_path,
        {
            "model_features": ["x", "y"],
            "scaler": {"x": {"median": 0, "scale": 1}, "y": {"median": 0, "scale": 1}},
        },
    )

    feature_frame_path = root / "feature.parquet"
    selection_context_path = root / "selection_context.parquet"
    scaled_path = root / "scaled.parquet"
    provenance_path = root / "provenance.csv"
    coverage_path = root / "coverage.csv"
    pd.DataFrame(
        {
            "ticker": ["AAA", "DD"],
            "valuation_price_cutoff_date": [valuation_date, valuation_date],
            "feature_available_from": [available, available],
            "decision_ranking_allowed": [False, False],
            "x": [1.0, 2.0],
            "y": [np.nan, np.nan],
            "accepted": ["2026-07-09", "2026-07-10"],
        }
    ).to_parquet(feature_frame_path)
    pd.DataFrame(
        {
            "ticker": ["AAA", "DD"],
            "valuation_price_cutoff_date": [valuation_date, valuation_date],
            "feature_available_from": [available, available],
            "decision_ranking_allowed": [False, False],
            "revenues_ttm": [10.0, 20.0],
            "op_income_ttm": [2.0, 3.0],
            "net_income_ttm": [1.0, 2.0],
            "assets": [100.0, 200.0],
            "liabilities": [40.0, 80.0],
        }
    ).to_parquet(selection_context_path)
    pd.DataFrame(
        {
            "ticker": ["AAA", "DD"],
            "x": [1.0, 2.0],
            "y": [missing_scaled_value, missing_scaled_value],
        }
    ).to_parquet(scaled_path)
    pd.DataFrame(
        [
            {
                "model_feature_order": 0,
                "column": "x",
                "raw_nonmissing_count": 2,
                "raw_missing_neutral_count": 0,
                "raw_finite_ratio": 1.0,
                "scaled_finite_count": 2,
                "scaler_missing_neutral_value": 0.0,
            },
            {
                "model_feature_order": 1,
                "column": "y",
                "raw_nonmissing_count": 0,
                "raw_missing_neutral_count": 2,
                "raw_finite_ratio": 0.0,
                "scaled_finite_count": 2,
                "scaler_missing_neutral_value": 0.0,
            },
        ]
    ).to_csv(provenance_path, index=False)
    pd.DataFrame(
        {
            "ticker": ["AAA", "DD"],
            "decision_ranking_allowed": [False, False],
            "raw_model_feature_nonmissing_count": [1, 1],
            "raw_model_feature_missing_neutral_count": [1, 1],
            "scaled_model_feature_finite_count": [2, 2],
        }
    ).to_csv(coverage_path, index=False)
    feature_manifest_path = root / "feature_manifest.json"
    write_json(
        feature_manifest_path,
        {
            "status": "CURRENT_CROSS_SECTION_ASSEMBLED_VERIFICATION_REQUIRED",
            "valuation_price_cutoff_date": valuation_date,
            "decision_time_utc": decision,
            "feature_available_from": available,
            "full_current_cross_section_assembled": True,
            "complete_cross_section_verification_passed": False,
            "decision_ranking_allowed": False,
            "model_scoring_executed": False,
            "selector_executed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "network_requests_executed": 0,
            "source_inputs_mutated": False,
            "source_immutability": {"all_verified_files_unchanged": True},
            "coverage": {
                "pilot_current_ticker_count": 2,
                "decision_eligible_equity_count": 2,
                "full_equity_queue_count": 3,
                "terminal_nontradable_excluded_count": 1,
                "price_refresh_resolved_ticker_count": 1,
                "remaining_price_refresh_ticker_count": 0,
                "model_feature_count": 2,
                "selection_context_column_count": 9,
                "raw_model_feature_finite_ratio": 0.5,
                "raw_model_missing_cell_count": 2,
                "raw_all_missing_feature_count": 1,
                "scaled_model_feature_finite_ratio": 1.0,
                "future_statement_date_row_count": 0,
            },
            "source_inputs": {
                "technical_manifest": record(technical_manifest_path),
                "preflight_manifest": record(preflight_manifest_path),
                "model_meta": record(model_meta_path),
            },
            "outputs": {
                "pilot_feature_frame": record(feature_frame_path),
                "pilot_selection_context": record(selection_context_path),
                "pilot_scaled_model_input": record(scaled_path),
                "model_feature_provenance": record(provenance_path),
                "ticker_feature_coverage": record(coverage_path),
            },
        },
    )
    return argparse.Namespace(
        feature_manifest=str(feature_manifest_path),
        expected_feature_sha256=sha(feature_manifest_path),
        technical_manifest=str(technical_manifest_path),
        expected_technical_sha256=sha(technical_manifest_path),
        valuation_date=valuation_date,
        expected_universe_count=3,
        expected_context_count=2,
        expected_price_refresh_count=1,
        expected_model_feature_count=2,
        expected_terminal_tickers="TERM",
        expected_non_equity_tickers="CASH",
        expected_corporate_action_tickers="DD",
        expected_all_missing_features="y",
        missing_neutral_tolerance=1e-12,
        output_dir=str(root / "output"),
    )


def test_complete_current_cross_section_passes_nonranking_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = verifier.build(fixture(root))
        assert payload["status"] == "READY_COMPLETE_CURRENT_CROSS_SECTION_NONRANKING"
        assert payload["complete_cross_section_verification_passed"] is True
        assert payload["research_model_scoring_prerequisite_passed"] is True
        assert payload["decision_ranking_allowed"] is False
        assert payload["coverage"]["decision_eligible_ticker_count"] == 2
        assert payload["coverage"]["scaled_missing_neutral_violation_count"] == 0
        tickers = pd.read_csv(root / "output" / "cross_section_ticker_audit.csv")
        assert len(tickers) == 4
        assert bool(tickers.loc[tickers["ticker"].eq("DD"), "corporate_action_quarantine"].iloc[0])


def test_nonzero_scaled_value_for_raw_missing_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = verifier.build(fixture(root, missing_scaled_value=1.0))
        assert payload["status"] == "BLOCKED_COMPLETE_CURRENT_CROSS_SECTION_VERIFICATION"
        assert "scaled_missing_neutral_violation_count:2" in payload["contract_failures"]


def main() -> int:
    test_complete_current_cross_section_passes_nonranking_gate()
    test_nonzero_scaled_value_for_raw_missing_blocks()
    print("run287_complete_current_cross_section_verifier_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
