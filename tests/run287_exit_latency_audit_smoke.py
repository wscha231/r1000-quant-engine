#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_exit_latency_audit import run  # noqa: E402


class Args:
    pass


def test_exit_latency_audit_detects_ex_ante_signal_lag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main = root / "main"
        main.mkdir()
        dates = pd.bdate_range("2022-01-03", periods=12)
        equity_values = [100000, 105000, 104000, 101000, 98000, 94000, 90000, 88000, 87000, 86000, 85000, 84500]
        pd.DataFrame(
            {
                "date": [d.date().isoformat() for d in dates],
                "equity_usd": equity_values,
                "cash_weight": [0.1] * len(dates),
            }
        ).to_csv(main / "equity_curve.csv", index=False)

        prices = [100, 105, 104, 101, 98, 94, 90, 88, 87, 86, 85, 84.5]
        pd.DataFrame(
            {
                "date": [d.date().isoformat() for d in dates],
                "ticker": ["AAA"] * len(dates),
                "shares": [900] * len(dates),
                "price": prices,
                "market_value_usd": [900 * p for p in prices],
                "weight": [0.9] * len(dates),
                "cost_basis": [100] * len(dates),
                "unrealized_pnl_usd": [900 * (p - 100) for p in prices],
            }
        ).to_csv(main / "holdings_daily.csv", index=False)

        target = root / "target_book.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2022-01-03",
                    "ticker": "AAA",
                    "target_weight": 0.9,
                    "hold_replace_decision": "hold",
                    "main_quality_hold_weak_timing_trim_status": "not_applicable",
                    "trend_template_full": 1.0,
                    "rs_benchmark_1m": 0.1,
                    "rs_benchmark_3m": 0.1,
                    "ticker_ret_1m": 0.1,
                },
                {
                    "rebalance_date": "2022-01-06",
                    "ticker": "AAA",
                    "target_weight": 0.0,
                    "hold_replace_decision": "target_exit",
                    "main_quality_hold_weak_timing_trim_status": "applied",
                    "trend_template_full": 0.0,
                    "rs_benchmark_1m": -0.2,
                    "rs_benchmark_3m": -0.1,
                    "ticker_ret_1m": -0.15,
                },
            ]
        ).to_csv(target, index=False)

        args = Args()
        args.main_root = str(main)
        args.target_book = str(target)
        args.output_dir = str(root / "out")
        args.lookback_days = 10
        args.top_n = 5
        args.material_latency_days = 5
        args.material_loss_bps = 10.0
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["fullrun_dispatched"] is False
        assert payload["threshold_tuning_performed"] is False
        assert payload["latency_candidate_present"] is True
        assert payload["diagnosis"] == "exit_latency_candidate_for_ex_ante_counterfactual"
        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "position_latency.csv").exists()
        assert (root / "out" / "report.md").exists()


def main() -> int:
    test_exit_latency_audit_detects_ex_ante_signal_lag()
    print("run287_exit_latency_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
