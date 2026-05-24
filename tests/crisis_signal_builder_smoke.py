#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_crisis_signal_builder import compute_composite_crisis_score  # noqa: E402


def test_composite_crisis_score_is_pit_stable_and_rises_in_crisis() -> None:
    dates = pd.bdate_range("2022-01-03", periods=260)
    features = pd.DataFrame(index=dates)
    features["spy_20d_dd"] = -0.01
    features["qqq_20d_dd"] = -0.01
    features["spy_below_ma200"] = 0.0
    features["qqq_below_ma200"] = 0.0
    features["vix_zscore_60d"] = 0.0
    features["hy_oas_zscore_60d"] = 0.0
    features["dgs10_20d_change"] = 0.0

    crisis_slice = slice(120, 170)
    features.iloc[crisis_slice, features.columns.get_loc("spy_20d_dd")] = -0.18
    features.iloc[crisis_slice, features.columns.get_loc("qqq_20d_dd")] = -0.25
    features.iloc[crisis_slice, features.columns.get_loc("spy_below_ma200")] = 1.0
    features.iloc[crisis_slice, features.columns.get_loc("qqq_below_ma200")] = 1.0
    features.iloc[crisis_slice, features.columns.get_loc("vix_zscore_60d")] = 3.0
    features.iloc[crisis_slice, features.columns.get_loc("hy_oas_zscore_60d")] = 2.5
    features.iloc[crisis_slice, features.columns.get_loc("dgs10_20d_change")] = 0.35

    score = compute_composite_crisis_score(features)
    assert float(score.iloc[40]) < 0.30
    assert float(score.iloc[140]) > 0.55

    truncated = features.iloc[:150].copy()
    truncated_score = compute_composite_crisis_score(truncated)
    assert np.isclose(float(score.iloc[140]), float(truncated_score.iloc[140]), atol=1e-12)


if __name__ == "__main__":
    test_composite_crisis_score_is_pit_stable_and_rises_in_crisis()
    print("crisis_signal_builder_smoke: PASS")
