#!/usr/bin/env python3
"""Fail-closed contracts for the Run287 current-decision score-only lane."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import stage_run287_price_batch as checkpoint  # noqa: E402
from tools.run_run287_current_decision_score_only import (  # noqa: E402
    BLOCKED_STATUS,
    READY_STATUS,
    build,
)


FEATURES = ["f1", "f2"]
TICKERS = ["ZZZ", "AAA", "MMM"]


def write_fixture(
    root: Path,
    *,
    ranking_enabled: bool = False,
    feature_available_from: str = "2026-07-13T23:59:59+00:00",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    scaled_path = root / "scaled.parquet"
    context_path = root / "context.parquet"
    coverage_path = root / "coverage.csv"
    meta_path = root / "model_meta.json"
    manifest_path = root / "decision_manifest.json"

    scaled = pd.DataFrame(
        {
            "ticker": TICKERS,
            "f1": [0.0, 1.0, -1.0],
            "f2": [0.0, 2.0, 0.5],
        }
    )
    scaled.to_parquet(scaled_path, index=False)
    context = pd.DataFrame(
        {
            "ticker": TICKERS,
            "pred_lin_ret": [0.0, np.nan, 0.1],
            "pred_lin_p": [0.5, np.nan, 0.4],
            "pred_future_winner_ret": [0.0, np.nan, -0.1],
            "pred_future_winner_p": [0.5, np.nan, 0.6],
        }
    )
    context.to_parquet(context_path, index=False)
    pd.DataFrame(
        {
            "ticker": TICKERS,
            "raw_model_feature_finite_count": [2, 2, 2],
            "scaled_model_feature_finite_count": [2, 2, 2],
            "decision_feature_complete": [False, False, False],
        }
    ).to_csv(coverage_path, index=False)
    meta = {
        "model_features": FEATURES,
        "ranking_enabled": ranking_enabled,
        "updated_at": "2026-04-23T12:33:17",
        "ridge": {"coef": [0.1, 0.2], "intercept": 0.01},
        "logreg": {"coef": [0.3, -0.1], "intercept": -0.2},
        "future_ridge": {"coef": [-0.2, 0.4], "intercept": 0.02},
        "future_logreg": {"coef": [0.15, 0.25], "intercept": -0.1},
    }
    checkpoint.write_json(meta_path, meta)

    manifest = {
        "schema_version": "run287-current-decision-frame-v1",
        "status": "READY_COMPLETE_CURRENT_DECISION_FRAME",
        "valuation_price_cutoff_date": "2026-07-13",
        "decision_time_utc": "2026-07-14T05:00:00+00:00",
        "feature_available_from": feature_available_from,
        "current_decision_data_complete": True,
        "research_model_scoring_prerequisite_passed": True,
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "coverage": {
            "decision_ticker_count": 3,
            "model_feature_count": 2,
            "future_feature_row_count": 0,
            "scaled_missing_neutral_violation_count": 0,
            "scaled_model_feature_finite_ratio": 1.0,
        },
        "outputs": {
            "scaled_model_input": checkpoint.fingerprint(scaled_path),
            "selection_context": checkpoint.fingerprint(context_path),
            "ticker_feature_coverage": checkpoint.fingerprint(coverage_path),
        },
        "source_inputs": {"model_meta": checkpoint.fingerprint(meta_path)},
    }
    checkpoint.write_json(manifest_path, manifest)
    return manifest_path


def args_for(manifest: Path, output_dir: Path, expected_hash: str) -> argparse.Namespace:
    return argparse.Namespace(
        decision_frame_manifest=str(manifest),
        expected_decision_frame_sha256=expected_hash,
        valuation_date="2026-07-13",
        expected_context_count=3,
        expected_model_feature_count=2,
        parity_tolerance=1e-12,
        output_dir=str(output_dir),
    )


def test_ready_lane_preserves_order_and_never_ranks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = write_fixture(root)
        expected_hash = checkpoint.fingerprint(manifest)["sha256"]
        output_dir = root / "ready"
        payload = build(args_for(manifest, output_dir, expected_hash))

        assert payload["status"] == READY_STATUS
        assert payload["coverage"]["ticker_count"] == 3
        assert payload["coverage"]["prediction_head_count"] == 4
        assert payload["coverage"]["engine_independent_parity_pass_count"] == 4
        assert payload["coverage"]["newly_scored_max_count"] == 1
        assert payload["decision_ranking_allowed"] is False
        assert payload["rank_executed"] is False
        assert payload["selector_executed"] is False
        assert payload["backtest_executed"] is False
        assert payload["fullrun_executed"] is False
        assert payload["network_requests_executed"] == 0

        predictions = pd.read_csv(output_dir / "ticker_order_model_predictions.csv")
        assert predictions["ticker"].tolist() == TICKERS
        assert predictions["decision_ranking_allowed"].eq(False).all()
        assert np.isfinite(
            predictions[
                [
                    "pred_lin_ret",
                    "pred_lin_p",
                    "pred_future_winner_ret",
                    "pred_future_winner_p",
                ]
            ].to_numpy(dtype=float)
        ).all()


def test_wrong_manifest_hash_blocks_before_scoring() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = write_fixture(root)
        output_dir = root / "blocked_hash"
        payload = build(args_for(manifest, output_dir, "0" * 64))
        assert payload["status"] == BLOCKED_STATUS
        assert "input_hash_mismatch:decision_frame_manifest" in payload[
            "contract_failures"
        ]
        assert payload["model_scoring_executed"] is False
        assert not (output_dir / "ticker_order_model_predictions.csv").exists()


def test_future_feature_and_ranking_enabled_both_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        future_manifest = write_fixture(
            root / "future",
            feature_available_from="2026-07-14T05:00:01+00:00",
        )
        future_hash = checkpoint.fingerprint(future_manifest)["sha256"]
        future_payload = build(
            args_for(future_manifest, root / "future_output", future_hash)
        )
        assert future_payload["status"] == BLOCKED_STATUS
        assert "future_feature_leakage" in future_payload["contract_failures"]

        ranking_manifest = write_fixture(root / "ranking", ranking_enabled=True)
        ranking_hash = checkpoint.fingerprint(ranking_manifest)["sha256"]
        ranking_payload = build(
            args_for(ranking_manifest, root / "ranking_output", ranking_hash)
        )
        assert ranking_payload["status"] == BLOCKED_STATUS
        assert "frozen_model_meta_ranking_enabled" in ranking_payload[
            "contract_failures"
        ]


if __name__ == "__main__":
    test_ready_lane_preserves_order_and_never_ranks()
    test_wrong_manifest_hash_blocks_before_scoring()
    test_future_feature_and_ranking_enabled_both_fail_closed()
    print("run287_current_decision_score_only_smoke: PASS")
