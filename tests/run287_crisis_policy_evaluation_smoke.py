#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.evaluate_run287_crisis_policy import evaluate  # noqa: E402


def test_evaluator_rejects_cagr_loss_and_cash_trap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = pd.bdate_range("2020-01-02", periods=100)
        pd.DataFrame({"date": dates, "equity_usd": range(100, 200)}).to_csv(root / "base.csv", index=False)
        pd.DataFrame(
            {"date": dates, "equity_usd": [100.0 + 0.5 * index for index in range(len(dates))]}
        ).to_csv(root / "policy.csv", index=False)
        pd.DataFrame(
            [
                {"snapshot_date": dates[0], "canonical_crisis_state": "GREEN", "stock_weight": 0.7, "cash_weight": 0.3},
                {"snapshot_date": dates[10], "canonical_crisis_state": "CRISIS", "stock_weight": 0.5, "cash_weight": 0.5},
                {"snapshot_date": dates[20], "canonical_crisis_state": "REENTRY_STAGE_1", "stock_weight": 0.2, "cash_weight": 0.8},
                {"snapshot_date": dates[30], "canonical_crisis_state": "GREEN", "stock_weight": 0.7, "cash_weight": 0.3},
            ]
        ).to_csv(root / "audit.csv", index=False)
        (root / "broker.json").write_text(json.dumps({"cagr": 0.1, "trade_count": 4, "total_fees_usd": 10}), encoding="utf-8")
        (root / "baseline.json").write_text(json.dumps({"cagr": 0.2}), encoding="utf-8")
        result = evaluate(
            argparse.Namespace(
                state_audit=str(root / "audit.csv"),
                baseline_equity=str(root / "base.csv"),
                policy_equity=str(root / "policy.csv"),
                broker_metrics=str(root / "broker.json"),
                baseline_metrics=str(root / "baseline.json"),
                output=str(root / "result.json"),
            )
        )
        assert result["status"] == "REJECTED_POLICY_PROMOTION"
        assert "negative_full_period_cagr_delta" in result["promotion_failures"]
        assert "green_cash_trap_detected" in result["promotion_failures"]
        assert result["fullrun_executed"] is False


if __name__ == "__main__":
    test_evaluator_rejects_cagr_loss_and_cash_trap()
    print("run287_crisis_policy_evaluation_smoke: PASS")
