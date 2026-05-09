#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_gap_attribution import run


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reports = root / "reports"
        reports.mkdir()
        for name in ["main_monthly_weights.csv", "concentrated_strategy_holdings.csv"]:
            rows = [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "weighted_forward_return": 0.10,
                    "target_stock_names": "3",
                    "weighting_mode": "score_power",
                    "active_rebalance_interval_months": "1",
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "weighted_forward_return": -0.05,
                    "target_stock_names": "3",
                    "weighting_mode": "score_power",
                    "active_rebalance_interval_months": "1",
                },
            ]
            pd.DataFrame(rows).to_csv(reports / name, index=False)
        for portfolio in ["main", "concentrated"]:
            broker = root / "broker_replay" / portfolio
            broker.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"date": "2026-01-31", "equity_usd": 100000, "cash_weight": 0.0},
                    {"date": "2026-02-28", "equity_usd": 98000, "cash_weight": 0.0},
                ]
            ).to_csv(broker / "equity_curve.csv", index=False)
            pd.DataFrame([{"date": "2026-01-31", "ticker": "AAA", "fee_usd": 10.0, "gross_value": 100000.0}]).to_csv(
                broker / "trades.csv", index=False
            )
            (broker / "metrics.json").write_text(
                json.dumps({"status": "completed", "metric_mode": "broker_ledger_next_close", "cagr": -0.20, "max_dd": -0.02, "sharpe": -1.0, "trade_count": 1, "total_fees_usd": 10.0, "gross_traded_usd": 100000.0}),
                encoding="utf-8",
            )
        out = root / "out"
        payload = run(root, out)
        assert payload["main"]["target_forward"]["uses_forward_returns"] is True
        assert payload["main"]["broker_ledger"]["metric_mode"] == "broker_ledger_next_close"
        assert (out / "gap_attribution_summary.json").exists()
        assert (out / "gap_attribution_report.md").exists()
    print("broker_gap_attribution_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
