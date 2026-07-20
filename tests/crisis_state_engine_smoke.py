#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.crisis_state_engine import build_historical_daily_crisis_state  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def test_historical_crisis_state_reuses_long_crisis_gate_pit_safely() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        features_path = root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        thresholds_path = root / "outputs" / "long_crisis_learning" / "best_thresholds.json"
        cache.mkdir(parents=True)
        features_path.parent.mkdir(parents=True)
        thresholds_path.parent.mkdir(parents=True)

        dates = pd.bdate_range("2025-01-02", "2025-04-30")
        values: list[float] = []
        for idx, _dt in enumerate(dates):
            if idx < 20:
                values.append(100.0)
            elif idx < 35:
                values.append(100.0 - (idx - 19) * 1.8)
            elif idx < 60:
                values.append(73.0 + (idx - 35) * 1.2)
            else:
                values.append(103.0 + (idx - 60) * 0.2)
        pd.DataFrame({"date": dates, "Adj Close": values, "Close": values}, index=dates).to_parquet(cache / px_cache_name("SPY"))

        feature_dates = pd.bdate_range("2025-01-02", "2025-04-30")
        features = pd.DataFrame(
            {
                "crisis_score": [0.10] * 15 + [0.85] * 15 + [0.20] * (len(feature_dates) - 30),
                "liquidity_confirmation_score": [0.05] * 15 + [0.70] * 15 + [0.05] * (len(feature_dates) - 30),
                "market_trend_damage_score": [0.05] * 15 + [0.65] * 15 + [0.05] * (len(feature_dates) - 30),
                "credit_stress_score": [0.05] * len(feature_dates),
                "qqq_below_ma200": [0.0] * len(feature_dates),
                "volatility_stress_score": [0.10] * len(feature_dates),
                "future_63d_drawdown": [-0.50] * len(feature_dates),
                "false_alarm_no_drawdown_63d": [1] * len(feature_dates),
            },
            index=feature_dates,
        )
        features.to_parquet(features_path)
        thresholds_path.write_text(
            json.dumps(
                {
                    "governor_thresholds": {"low": 0.30, "mid": 0.50, "high": 0.75},
                    "cash_hard_gate": {"liquidity_gate": 0.35, "trend_gate": 0.35, "credit_gate": 0.55},
                }
            ),
            encoding="utf-8",
        )

        states = build_historical_daily_crisis_state(
            cache,
            pd.Timestamp("2025-01-02"),
            pd.Timestamp("2025-04-30"),
            long_crisis_features=features_path,
            long_crisis_thresholds=thresholds_path,
        )
        assert not states.empty
        assert "future_63d_drawdown" not in states.columns
        assert "false_alarm_no_drawdown_63d" not in states.columns
        assert states["future_labels_excluded"].eq(True).all()
        assert "CRISIS" in set(states["crisis_state"]), states["crisis_state"].value_counts().to_dict()
        assert states["crisis_state"].astype(str).str.startswith("REENTRY_STAGE_").any()
        reentry = states[states["crisis_state"].astype(str).str.startswith("REENTRY_STAGE_")]
        assert reentry["reentry_stage"].astype(str).str.startswith("REENTRY_STAGE_").any()
        assert states["cash_gate_reason"].astype(str).str.contains("systemic_confirmation_pass").any()


if __name__ == "__main__":
    test_historical_crisis_state_reuses_long_crisis_gate_pit_safely()
    print("crisis_state_engine_smoke: PASS")
