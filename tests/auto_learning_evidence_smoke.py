#!/usr/bin/env python3
"""Smoke checks for AutoLearning evidence source priority."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_auto_learning_evidence import load_auto_learning_evidence  # noqa: E402


def test_autolearning_prefers_broker_ledger_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = root / "outputs"
        (run / "broker_replay" / "main").mkdir(parents=True)
        (run / "broker_replay" / "concentrated").mkdir(parents=True)
        (run / "broker_trade_journal" / "main").mkdir(parents=True)
        (run / "broker_trade_journal" / "concentrated").mkdir(parents=True)
        (run / "broker_trade_journal").mkdir(parents=True, exist_ok=True)
        (run / "reports").mkdir(parents=True, exist_ok=True)
        (run / "broker_replay" / "main" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.21, "sharpe": 1.0, "max_dd": -0.36}),
            encoding="utf-8",
        )
        (run / "broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.35, "sharpe": 1.1, "max_dd": -0.40}),
            encoding="utf-8",
        )
        rows = [
            {
                "trade_id": "main_000001",
                "portfolio_kind": "main",
                "ticker": "AAA",
                "entry_regime_state": "bull",
                "entry_sleeve": "future_winner",
                "exit_reason": "target_exit",
                "realized_return": 0.25,
                "alpha_vs_benchmark": 0.10,
                "holding_days": 45,
            }
        ]
        pd.DataFrame(rows).to_csv(run / "broker_trade_journal" / "main" / "round_trips.csv", index=False)
        pd.DataFrame(rows).to_csv(run / "broker_trade_journal" / "combined_round_trips.csv", index=False)
        pd.DataFrame(columns=list(rows[0].keys())).to_csv(
            run / "broker_trade_journal" / "concentrated" / "round_trips.csv",
            index=False,
        )
        evidence = load_auto_learning_evidence(latest_run=run, root=root)
        assert evidence["evidence_mode"] == "broker_ledger"
        assert evidence["metrics"]["main"]["cagr"] == 0.21
        assert evidence["metrics"]["concentrated"]["max_dd"] == -0.40
        assert evidence["combined_trade_journal"]["trade_count"] == 1
        assert evidence["combined_trade_journal"]["avg_return_by_sleeve"]["future_winner"] == 0.25


def main() -> int:
    test_autolearning_prefers_broker_ledger_evidence()
    print("auto_learning_evidence_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
