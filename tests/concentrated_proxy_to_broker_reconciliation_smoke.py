#!/usr/bin/env python3
"""Smoke test for concentrated proxy-to-broker reconciliation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_concentrated_proxy_to_broker_reconciliation import run  # noqa: E402


def test_concentrated_reconciliation_emits_gap_without_forward_labels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        (latest / "portfolio_goal_search").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        (latest / "reports").mkdir(parents=True)
        (latest / "portfolio_goal_search" / "goal_search_summary.json").write_text(
            json.dumps(
                {
                    "best_concentrated": {
                        "candidate_id": "concentrated_position_risk_proxy",
                        "portfolio": "concentrated",
                        "cagr": 0.55,
                        "max_dd": -0.14,
                        "sharpe": 1.9,
                        "valid_for_production": False,
                    },
                    "best_production_concentrated": {
                        "candidate_id": "concentrated_broker_ledger_replay",
                        "portfolio": "concentrated",
                        "cagr": 0.35,
                        "max_dd": -0.23,
                        "sharpe": 1.3,
                        "valid_for_production": True,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (latest / "broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "cagr": 0.35,
                    "max_dd": -0.23,
                    "sharpe": 1.3,
                    "trade_count": 2,
                    "total_fees_usd": 123.0,
                    "avg_cash_weight": 0.18,
                    "valid_for_production": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {"date": "2026-01-02", "ticker": "AAA", "side": "BUY", "quantity": 10, "gross_value": 1_000, "fee_usd": 5, "cash_delta": -1_005},
                {"date": "2026-02-02", "ticker": "AAA", "side": "SELL", "quantity": 10, "gross_value": 1_100, "fee_usd": 5, "cash_delta": 1_095},
            ]
        ).to_csv(latest / "broker_replay" / "concentrated" / "trades.csv", index=False)
        pd.DataFrame(
            [
                {"date": "2026-01-02", "equity_usd": 100_000, "cash_usd": 20_000, "cash_weight": 0.20},
                {"date": "2026-01-03", "equity_usd": 101_000, "cash_usd": 18_000, "cash_weight": 0.18},
            ]
        ).to_csv(latest / "broker_replay" / "concentrated" / "equity_curve.csv", index=False)
        pd.DataFrame([{"rebalance_date": "2026-01-02", "ticker": "LEAK", "period_forward_return": 9.99}]).to_csv(
            latest / "reports" / "candidate_replay_book.csv",
            index=False,
        )
        payload = run(latest, root / "out")
        assert payload["status"] == "completed", payload
        assert abs(float(payload["cagr_gap"]) - 0.20) < 1e-9
        assert payload["uses_forward_labels_for_selection"] is False
        assert (root / "out" / "trade_path_diff.csv").exists()
        assert (root / "out" / "missed_upside_after_cash.csv").exists()
        saved = json.loads((root / "out" / "conversion_gap_summary.json").read_text(encoding="utf-8"))
        assert saved["proxy_candidate"]["candidate_id"] == "concentrated_position_risk_proxy"


def main() -> int:
    test_concentrated_reconciliation_emits_gap_without_forward_labels()
    print("concentrated_proxy_to_broker_reconciliation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
