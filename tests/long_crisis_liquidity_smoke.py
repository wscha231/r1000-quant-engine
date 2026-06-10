#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_long_crisis_liquidity import build_long_crisis_features, cash_raise_decision, monthly_release_lag  # noqa: E402
from tools.run_long_crisis_signal_learning import run as run_signal_learning  # noqa: E402
from tools.run_long_crisis_threshold_search import run as run_threshold_search  # noqa: E402
from tools.run_long_crisis_validation_report import run as run_validation_report  # noqa: E402


def test_long_crisis_liquidity_features_and_tools() -> None:
    dates = pd.bdate_range("1999-01-04", "2011-12-30")
    close = pd.Series(100.0, index=dates)
    close += np.linspace(0, 40, len(close))
    crisis_mask = (dates >= "2008-09-01") & (dates <= "2008-11-28")
    close.loc[crisis_mask] = np.linspace(float(close.loc[crisis_mask].iloc[0]), 75.0, int(crisis_mask.sum()))
    close.loc[dates > "2008-11-28"] = np.linspace(80.0, 150.0, int((dates > "2008-11-28").sum()))

    vix = pd.Series(18.0, index=dates)
    vix.loc[(dates >= "2008-08-15") & (dates <= "2008-12-15")] = 55.0
    hy = pd.Series(3.5, index=dates)
    hy.loc[(dates >= "2008-08-15") & (dates <= "2009-02-15")] = 11.0
    dgs10 = pd.Series(4.0, index=dates)
    dxy = pd.Series(100.0, index=dates)
    dxy.loc[(dates >= "2008-08-15") & (dates <= "2008-12-15")] = 112.0
    monthly = pd.date_range("1998-01-01", "2012-01-01", freq="MS")
    m2 = pd.Series(np.linspace(7000, 9000, len(monthly)), index=monthly)
    m2.loc[(monthly >= "2008-04-01") & (monthly <= "2008-12-01")] = np.linspace(8800, 8200, int(((monthly >= "2008-04-01") & (monthly <= "2008-12-01")).sum()))
    fed = pd.Series(900_000.0, index=dates)
    rrp = pd.Series(50.0, index=dates)
    tga = pd.Series(200_000.0, index=dates)
    tga.loc[(dates >= "2008-07-01") & (dates <= "2008-10-31")] = 600_000.0

    features = build_long_crisis_features(
        close,
        {
            "vix": vix,
            "hy_oas": hy,
            "dgs10": dgs10,
            "dxy": dxy,
            "m2": m2,
            "fed_assets": fed,
            "reverse_repo": rrp,
            "tga": tga,
        },
        start="1999-01-01",
    )
    assert not features.empty
    assert "liquidity_confirmation_score" in features.columns
    assert "future_63d_drawdown_le_15pct" in features.columns
    assert features.loc["2008-09-15":"2008-10-15", "crisis_score"].max() > 0.45
    assert features.loc["2008-07-01":"2008-09-15", "future_63d_drawdown_le_15pct"].sum() > 0

    lagged_m2 = monthly_release_lag(m2, months=1)
    assert pd.isna(lagged_m2.loc[pd.Timestamp("1998-01-01")])
    assert lagged_m2.loc[pd.Timestamp("1998-02-01")] == m2.loc[pd.Timestamp("1998-01-01")]

    row = features.loc[pd.Timestamp("2008-09-15")]
    decision = cash_raise_decision(row, float(row["crisis_score"]), mid_threshold=0.40)
    assert decision.allowed is True

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        feat_path = root / "long_features.parquet"
        out_dir = root / "out"
        features.to_parquet(feat_path, index=True)

        payload = run_signal_learning(
            type("Args", (), {"features": str(feat_path), "output_dir": str(out_dir), "label": "future_63d_drawdown_le_15pct"})()
        )
        assert payload["status"] == "completed"
        payload = run_threshold_search(
            type(
                "Args",
                (),
                {
                    "features": str(feat_path),
                    "output_dir": str(out_dir),
                    "label": "future_63d_drawdown_le_15pct",
                    "crisis_gates": "0.25,0.35,0.45",
                    "liquidity_gates": "0.05,0.15,0.25",
                    "trend_gates": "0.05,0.15,0.25",
                    "max_signal_rate": 0.60,
                    "max_false_positive_rate": 0.80,
                },
            )()
        )
        assert payload["status"] == "completed"
        assert (out_dir / "best_thresholds.json").exists()
        payload = run_validation_report(
            type("Args", (), {"features": str(feat_path), "thresholds": str(out_dir / "best_thresholds.json"), "output_dir": str(out_dir)})()
        )
        assert payload["status"] == "completed"
        assert json.loads((out_dir / "best_thresholds.json").read_text())["governor_thresholds"]["mid"] > 0


if __name__ == "__main__":
    test_long_crisis_liquidity_features_and_tools()
    print("long_crisis_liquidity_smoke: PASS")

