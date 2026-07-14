#!/usr/bin/env python3
"""Regression contracts for the current-decision score-stack audit."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_current_decision_score_stack_audit import (  # noqa: E402
    ACTIVE_PREDICTION_COLUMNS,
    prediction_activity_rows,
)
from tools.run_run287_current_score_stack_audit import (  # noqa: E402
    PREDICTION_COLUMNS,
    compare_frames,
    prepare_context_for_stack,
)


def test_stale_predictions_are_removed_before_fresh_join() -> None:
    context = pd.DataFrame(
        {
            "ticker": ["ZZZ", "AAA", "MMM"],
            "feature": [1.0, 2.0, 3.0],
            **{column: [-9.0, -9.0, -9.0] for column in PREDICTION_COLUMNS},
        }
    )
    fresh = pd.DataFrame(
        {
            "ticker": ["ZZZ", "AAA", "MMM"],
            **{
                column: [float(index), float(index + 1), float(index + 2)]
                for index, column in enumerate(PREDICTION_COLUMNS)
            },
        }
    )

    prepared = prepare_context_for_stack(context)
    merged = prepared.merge(fresh, on="ticker", validate="one_to_one", sort=False)

    assert context[PREDICTION_COLUMNS].eq(-9.0).all().all()
    assert prepared.columns.tolist() == ["ticker", "feature"]
    assert not any(column.endswith(("_x", "_y")) for column in merged)
    assert merged[PREDICTION_COLUMNS].equals(fresh[PREDICTION_COLUMNS])
    assert merged["ticker"].tolist() == ["ZZZ", "AAA", "MMM"]


def test_prediction_activity_rejects_silent_all_zero_heads() -> None:
    predictions = pd.DataFrame(
        {
            column: np.zeros(4, dtype=float)
            for column in ACTIVE_PREDICTION_COLUMNS
        }
    )
    rows = prediction_activity_rows(predictions, tolerance=1e-12)
    assert len(rows) == len(ACTIVE_PREDICTION_COLUMNS)
    assert not any(row["nonzero_nonconstant_pass"] for row in rows)


def test_prediction_activity_accepts_finite_varying_heads() -> None:
    predictions = pd.DataFrame(
        {
            column: np.asarray([0.1, 0.2, -0.1, 0.4], dtype=float) + index
            for index, column in enumerate(ACTIVE_PREDICTION_COLUMNS)
        }
    )
    rows = prediction_activity_rows(predictions, tolerance=1e-12)
    assert all(row["finite_count"] == 4 for row in rows)
    assert all(row["nonzero_nonconstant_pass"] for row in rows)


def test_prediction_passthrough_comparison_is_exact_and_fail_closed() -> None:
    left = pd.DataFrame({"head": [0.1, 0.2, 0.3]})
    exact = compare_frames(left, left.copy(), ["head"], tolerance=1e-12)
    changed = left.copy()
    changed.loc[1, "head"] = 0.0
    mismatch = compare_frames(left, changed, ["head"], tolerance=1e-12)
    assert exact[0]["parity_pass"] is True
    assert mismatch[0]["parity_pass"] is False
    assert mismatch[0]["mismatch_count"] == 1


if __name__ == "__main__":
    test_stale_predictions_are_removed_before_fresh_join()
    test_prediction_activity_rejects_silent_all_zero_heads()
    test_prediction_activity_accepts_finite_varying_heads()
    test_prediction_passthrough_comparison_is_exact_and_fail_closed()
    print("run287_current_decision_score_stack_smoke: PASS")
