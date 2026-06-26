#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_sizing_signal_screen import screen_portfolio  # noqa: E402


def _rows(*, inverse_oos: bool = False) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for split_date, prefix in [("2021-06-30", "IS"), ("2025-06-30", "OOS")]:
        for i in range(120):
            score = float(i)
            forward = score / 100.0
            if inverse_oos and prefix == "OOS":
                forward = -forward
            rows.append(
                {
                    "rebalance_date": split_date,
                    "ticker": f"{prefix}{i}",
                    "alphaops_vnext_score": score,
                    "alphaops_vnext_weight_score": score,
                    "weighting_score": score,
                    "weight": score / 1000.0,
                    "target_weight": score / 1000.0,
                    "period_forward_return": forward,
                }
            )
    return rows


def test_screen_detects_oos_positive_sizing_signal() -> None:
    _rows_data, summary = screen_portfolio(pd.DataFrame(_rows()), "concentrated")

    assert summary["status"] == "screen_passed"
    assert "alphaops_vnext_score" in summary["positive_signals"]
    score = next(item for item in summary["signal_summaries"] if item["signal"] == "alphaops_vnext_score")
    assert score["candidate_positive"] is True
    assert score["oos"]["high_minus_low"] > 0


def test_screen_rejects_is_only_signal_when_oos_breaks() -> None:
    _rows_data, summary = screen_portfolio(pd.DataFrame(_rows(inverse_oos=True)), "concentrated")

    score = next(item for item in summary["signal_summaries"] if item["signal"] == "alphaops_vnext_score")
    assert score["candidate_positive"] is False
    assert summary["status"] == "no_positive_sizing_signal"


if __name__ == "__main__":
    test_screen_detects_oos_positive_sizing_signal()
    test_screen_rejects_is_only_signal_when_oos_breaks()
    print("sizing_signal_screen_smoke passed")
