#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_crisis_governor import (  # noqa: E402
    apply_exposure_ladder,
    compute_reentry_score,
    crisis_zone,
    evaluate_exposure_target,
    reentry_exposure_multiplier,
)


def test_crisis_governor_ladders_cash_only_in_crisis() -> None:
    assert crisis_zone(0.10) == "normal"
    assert crisis_zone(0.40) == "caution"
    assert crisis_zone(0.60) == "defense"
    assert crisis_zone(0.85) == "crisis"

    weights = pd.Series({"AAA": 0.50, "BBB": 0.45, "CASH": 0.05})
    normal = apply_exposure_ladder(weights, crisis_score=0.10)
    crisis_target = evaluate_exposure_target(0.85)
    crisis = apply_exposure_ladder(weights, crisis_score=0.85, target=crisis_target)

    assert abs(float(normal.sum()) - 1.0) < 1e-12
    assert abs(float(crisis.sum()) - 1.0) < 1e-12
    assert float(crisis["CASH"]) >= 0.25
    assert float(crisis["AAA"]) < float(normal["AAA"])
    assert crisis_target.block_new_buys is True

    healthy = pd.Series(
        {
            "vix_zscore_60d": 0.1,
            "qqq_close": 110.0,
            "qqq_ma20": 100.0,
            "qqq_ma50": 95.0,
            "spy_20d_dd": 0.0,
            "hy_oas_zscore_60d": 0.1,
            "spy_5d_dd": 0.0,
        }
    )
    assert compute_reentry_score(healthy) > 0.75
    assert reentry_exposure_multiplier(0.80, prior_multiplier=0.25) == 1.0


if __name__ == "__main__":
    test_crisis_governor_ladders_cash_only_in_crisis()
    print("crisis_governor_smoke: PASS")
