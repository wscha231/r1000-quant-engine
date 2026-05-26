#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_execution_lag_review import build_review, write_outputs


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_json(
            root / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "portfolios": {
                    "main": {
                        "status": "completed",
                        "official_metric_mode": "broker_ledger_next_close",
                        "cagr": 0.20,
                        "max_dd": -0.33,
                        "sharpe": 1.0,
                        "broker_trade_count": 100,
                        "latest_cash_weight": 0.25,
                    },
                    "concentrated": {
                        "status": "completed",
                        "official_metric_mode": "broker_ledger_next_close",
                        "cagr": 0.32,
                        "max_dd": -0.38,
                        "sharpe": 1.1,
                        "broker_trade_count": 20,
                        "latest_cash_weight": 0.0,
                    },
                },
            },
        )
        _write_json(
            root / "user_current" / "02_cash_summary.json",
            {
                "cash_policy_flag": "cash_above_target",
                "combined_projected_cash_weight_after_ready_orders": 0.02,
                "by_portfolio": {
                    "main": {"cash_weight": 0.25, "projected_cash_weight": 0.04},
                    "concentrated": {"cash_weight": 0.0, "projected_cash_weight": 0.0},
                },
            },
        )
        _write_json(
            root / "broker_execution_policy_replay" / "main" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_execution_policy_next_close",
                "broker_ledger_valid": True,
                "valid_for_production": False,
                "research_only": True,
                "cagr": 0.198,
                "max_dd": -0.29,
                "sharpe": 1.05,
                "trade_count": 80,
                "avg_cash_weight": 0.05,
            },
        )
        _write_json(
            root / "account_ledger_preview" / "main" / "preview_metrics.json",
            {
                "equity_usd": 100000,
                "buy_gross_usd": 40000,
                "sell_gross_usd": 20000,
                "ready_order_count": 10,
                "blocked_order_count": 0,
            },
        )
        payload = build_review(root)
        assert payload["research_only"] is True
        main = payload["rows"][0]
        assert main["portfolio_kind"] == "main"
        assert main["execution_policy_valid_for_production"] is False
        assert main["execution_policy_broker_ledger_valid"] is True
        assert main["decision"] == "RESEARCH_CANDIDATE_MDD_IMPROVED"
        out = root / "operator_review"
        write_outputs(payload, out)
        assert (out / "execution_lag_review.json").exists()
        report = (out / "execution_lag_review.md").read_text(encoding="utf-8")
        assert "Production activation allowed: `false`" in report
        assert "broker_ledger_execution_policy_next_close" in report
    print("execution_lag_review_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
