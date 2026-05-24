#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_crisis_governor_replay import compute_governed_curve  # noqa: E402


def test_governor_replay_reduces_synthetic_crisis_mdd_without_cash_drag() -> None:
    dates = pd.bdate_range("2020-01-02", periods=300)
    returns = np.full(len(dates), 0.0008)
    returns[70:95] = -0.012
    returns[95:130] = 0.004
    equity = pd.DataFrame({"date": dates, "return": returns, "cash_weight": 0.05})
    features = pd.DataFrame(index=dates)
    features["crisis_score"] = 0.05
    features.loc[dates[70:95], "crisis_score"] = 0.85
    features["vix_zscore_60d"] = np.where(features["crisis_score"] > 0.5, 3.0, 0.1)
    features["qqq_close"] = 100.0
    features["qqq_ma20"] = 100.0
    features["qqq_ma50"] = 100.0
    features["spy_20d_dd"] = np.where(features["crisis_score"] > 0.5, -0.20, 0.0)
    features["hy_oas_zscore_60d"] = np.where(features["crisis_score"] > 0.5, 2.0, 0.1)
    features["spy_5d_dd"] = np.where(features["crisis_score"] > 0.5, -0.10, 0.0)

    governed, summary = compute_governed_curve(equity, features, "date", "return", "cash_weight", "main")
    assert summary["governed_mdd"] > summary["original_mdd"]
    assert float(governed.loc[70:94, "governed_cash_weight"].min()) >= 0.25
    assert float(governed.loc[0:40, "governed_cash_weight"].mean()) <= 0.051


if __name__ == "__main__":
    test_governor_replay_reduces_synthetic_crisis_mdd_without_cash_drag()
    print("crisis_governor_replay_smoke: PASS")
