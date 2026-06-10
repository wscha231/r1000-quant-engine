#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_position_risk_review import build_review, write_outputs


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
                        "valid_for_production": True,
                        "cagr": 0.20,
                        "max_dd": -0.33,
                        "sharpe": 1.0,
                        "broker_trade_count": 100,
                        "total_fees_usd": 1000.0,
                    },
                    "concentrated": {
                        "status": "completed",
                        "official_metric_mode": "broker_ledger_next_close",
                        "valid_for_production": True,
                        "cagr": 0.34,
                        "max_dd": -0.39,
                        "sharpe": 1.1,
                        "broker_trade_count": 20,
                        "total_fees_usd": 500.0,
                    },
                },
            },
        )
        _write_json(
            root / "broker_position_risk_replay" / "main" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_position_risk_next_close",
                "valid_for_production": True,
                "cagr": 0.198,
                "max_dd": -0.27,
                "sharpe": 1.05,
                "trade_count": 80,
                "total_fees_usd": 700.0,
                "risk_exit_count": 7,
                "risk_trim_count": 3,
            },
        )
        _write_json(
            root / "broker_position_risk_replay" / "concentrated" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_position_risk_next_close",
                "valid_for_production": True,
                "cagr": 0.28,
                "max_dd": -0.31,
                "sharpe": 0.95,
                "trade_count": 16,
                "total_fees_usd": 300.0,
                "risk_exit_count": 4,
                "risk_trim_count": 1,
            },
        )
        payload = build_review(root)
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        rows = {row["portfolio_kind"]: row for row in payload["rows"]}
        assert rows["main"]["decision"] == "BROKER_LEDGER_CANDIDATE"
        assert rows["main"]["position_risk_mdd_improvement"] > 0.05
        assert rows["main"]["position_risk_trade_count_delta"] == -20
        assert rows["concentrated"]["decision"] == "REJECT_CAGR_DRAG"
        out = root / "operator_review"
        write_outputs(payload, out)
        assert (out / "position_risk_review.json").exists()
        report = (out / "position_risk_review.md").read_text(encoding="utf-8")
        assert "Production activation allowed: `false`" in report
        assert "broker_ledger_position_risk_next_close" in report
    print("position_risk_review_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
