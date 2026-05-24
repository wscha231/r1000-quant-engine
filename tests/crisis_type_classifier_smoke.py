#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_crisis_type_classifier import Thresholds, classify_rows  # noqa: E402


def test_crisis_type_classifier_detects_shock_and_slow_bear() -> None:
    dates = pd.bdate_range("2020-01-02", periods=520)
    features = pd.DataFrame(index=dates)
    features["crisis_score"] = 0.05
    features["spy_5d_dd"] = 0.0
    features["spy_20d_dd"] = 0.0
    features["qqq_20d_dd"] = 0.0
    features["vix_zscore_60d"] = 0.0
    features["hy_oas_zscore_60d"] = 0.0
    features["ten_year_20d_change_bps"] = 0.0
    features["spy_below_ma200"] = 0.0
    features["qqq_below_ma200"] = 0.0

    shock = slice(60, 85)
    features.iloc[shock, features.columns.get_loc("crisis_score")] = 0.85
    features.iloc[shock, features.columns.get_loc("spy_5d_dd")] = -0.12
    features.iloc[shock, features.columns.get_loc("vix_zscore_60d")] = 4.0
    features.iloc[shock, features.columns.get_loc("hy_oas_zscore_60d")] = 3.0

    slow = slice(260, 340)
    features.iloc[slow, features.columns.get_loc("crisis_score")] = np.linspace(0.35, 0.75, 80)
    features.iloc[slow, features.columns.get_loc("spy_20d_dd")] = -0.12
    features.iloc[slow, features.columns.get_loc("qqq_20d_dd")] = -0.20
    features.iloc[slow, features.columns.get_loc("ten_year_20d_change_bps")] = 45.0
    features.iloc[slow, features.columns.get_loc("spy_below_ma200")] = 1.0
    features.iloc[slow, features.columns.get_loc("qqq_below_ma200")] = 1.0

    out = classify_rows(features, Thresholds())
    assert (out.iloc[60:85]["crisis_type"] == "shock_crash").sum() >= 10
    assert (out.iloc[300:340]["crisis_type"] == "slow_bear").sum() >= 10


if __name__ == "__main__":
    test_crisis_type_classifier_detects_shock_and_slow_bear()
    print("crisis_type_classifier_smoke: PASS")
