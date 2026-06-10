#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_daily_crisis_monitor import build_monitor  # noqa: E402


def test_daily_crisis_monitor_uses_learned_long_crisis_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest_run = root / "outputs"
        feature_path = root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        thresholds_path = root / "outputs" / "long_crisis_learning" / "best_thresholds.json"
        feature_path.parent.mkdir(parents=True)
        thresholds_path.parent.mkdir(parents=True)

        idx = pd.bdate_range("2026-01-02", periods=3)
        features = pd.DataFrame(
            {
                "crisis_score": [0.10, 0.25, 0.80],
                "liquidity_confirmation_score": [0.05, 0.10, 0.60],
                "market_trend_damage_score": [0.05, 0.10, 0.58],
                "credit_stress_score": [0.02, 0.10, 0.20],
                "future_63d_drawdown": [0.0, -0.10, -0.30],
                "future_63d_drawdown_le_15pct": [0, 0, 1],
            },
            index=idx,
        )
        features.to_parquet(feature_path)
        thresholds_path.write_text(
            json.dumps(
                {
                    "governor_thresholds": {"low": 0.30, "mid": 0.50, "high": 0.75},
                    "cash_hard_gate": {"liquidity_gate": 0.35, "trend_gate": 0.35, "credit_gate": 0.55},
                }
            ),
            encoding="utf-8",
        )

        payload = build_monitor(
            SimpleNamespace(
                latest_run=str(latest_run),
                output_dir=str(root / "monitor"),
                history=str(root / "monitor" / "state_history.json"),
                update_history=False,
                long_crisis_features=str(feature_path),
                long_crisis_thresholds=str(thresholds_path),
            )
        )
        assert payload["raw_state"] == "DEFENSE_REVIEW", payload
        assert payload["long_crisis"]["available"] is True
        assert payload["long_crisis"]["future_labels_excluded"] is True
        assert payload["long_crisis"]["cash_gate_reason"] == "systemic_confirmation_pass"
        assert "future_63d_drawdown" not in (root / "monitor" / "summary.json").read_text(encoding="utf-8")


def test_daily_crisis_monitor_blocks_unconfirmed_vix_only_cash_raise() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest_run = root / "outputs"
        feature_path = root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        thresholds_path = root / "outputs" / "long_crisis_learning" / "best_thresholds.json"
        feature_path.parent.mkdir(parents=True)
        thresholds_path.parent.mkdir(parents=True)

        idx = pd.bdate_range("2026-01-02", periods=2)
        pd.DataFrame(
            {
                "crisis_score": [0.20, 0.70],
                "liquidity_confirmation_score": [0.02, 0.05],
                "market_trend_damage_score": [0.04, 0.10],
                "credit_stress_score": [0.01, 0.05],
                "volatility_stress_score": [0.20, 0.95],
            },
            index=idx,
        ).to_parquet(feature_path)
        thresholds_path.write_text(
            json.dumps({"governor_thresholds": {"low": 0.30, "mid": 0.50, "high": 0.75}}),
            encoding="utf-8",
        )

        payload = build_monitor(
            SimpleNamespace(
                latest_run=str(latest_run),
                output_dir=str(root / "monitor"),
                history=str(root / "monitor" / "state_history.json"),
                update_history=False,
                long_crisis_features=str(feature_path),
                long_crisis_thresholds=str(thresholds_path),
            )
        )
        assert payload["raw_state"] == "WATCH", payload
        assert payload["long_crisis"]["cash_gate_reason"] == "blocked_no_liquidity_or_trend_confirmation"


if __name__ == "__main__":
    test_daily_crisis_monitor_uses_learned_long_crisis_gate()
    test_daily_crisis_monitor_blocks_unconfirmed_vix_only_cash_raise()
    print("daily_crisis_monitor_long_crisis_smoke: PASS")
