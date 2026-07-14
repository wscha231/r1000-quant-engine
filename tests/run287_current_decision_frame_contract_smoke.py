#!/usr/bin/env python3
"""Low-cost contracts for current-decision frame serialization and safety."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_current_decision_frame import (  # noqa: E402
    normalize_acceptance_columns,
    normalize_period_columns,
    values_differ,
)


def test_mixed_sec_dates_normalize_without_changing_instants() -> None:
    frame = pd.DataFrame(
        {
            "accepted": ["2026-04-08 00:00:00", pd.Timestamp("2026-07-10T16:17:17Z")],
            "fund_period": ["2026-03-31", pd.Timestamp("2026-06-30")],
        }
    )
    normalized = normalize_period_columns(normalize_acceptance_columns(frame))
    assert str(normalized.loc[1, "accepted"]) == "2026-07-10 16:17:17"
    assert normalized["fund_period"].tolist() == ["2026-03-31", "2026-06-30"]


def test_numeric_delta_tolerance_and_missing_change() -> None:
    assert values_differ(1.0, 1.0 + 1e-13) is False
    assert values_differ(float("nan"), float("nan")) is False
    assert values_differ(float("nan"), 0.0) is True


if __name__ == "__main__":
    test_mixed_sec_dates_normalize_without_changing_instants()
    test_numeric_delta_tolerance_and_missing_change()
    print("run287_current_decision_frame_contract_smoke: PASS")
