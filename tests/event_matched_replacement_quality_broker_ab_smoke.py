#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_event_matched_replacement_quality_broker_ab import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    frame = pd.DataFrame(
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "adj_close": closes,
            "volume": 1000000,
        }
    )
    frame.to_parquet(cache_dir / px_cache_name(ticker), index=False)


def test_event_matched_broker_ab_preserves_cash_and_applies_fixed_swap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        dates = ["2026-01-30", "2026-02-27"]
        target = root / "target.csv"
        swaps = root / "swaps.csv"
        baseline_metrics = root / "baseline_metrics.json"
        for ticker, closes in {
            "AAA": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
            "OLD": [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10],
            "WIN": [10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
        }.items():
            _write_px(cache, ticker, closes, start="2026-01-30")
        pd.DataFrame(
            [
                {"rebalance_date": dates[0], "ticker": "AAA", "weight": 0.30, "target_weight": 0.30},
                {"rebalance_date": dates[0], "ticker": "OLD", "weight": 0.20, "target_weight": 0.20},
                {"rebalance_date": dates[0], "ticker": "CASH", "weight": 0.50, "target_weight": 0.50},
                {"rebalance_date": dates[1], "ticker": "AAA", "weight": 0.30, "target_weight": 0.30},
                {"rebalance_date": dates[1], "ticker": "OLD", "weight": 0.20, "target_weight": 0.20},
                {"rebalance_date": dates[1], "ticker": "CASH", "weight": 0.50, "target_weight": 0.50},
            ]
        ).to_csv(target, index=False)
        pd.DataFrame(
            [
                {
                    "rule": "rank_top15_and_revenue_ge10",
                    "rebalance_date": dates[0],
                    "added_ticker": "WIN",
                    "removed_ticker": "OLD",
                    "replacement_weight": 0.20,
                }
            ]
        ).to_csv(swaps, index=False)
        baseline_metrics.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "metric_mode": "broker_ledger_next_close",
                    "cagr": 0.10,
                    "max_dd": -0.10,
                    "sharpe": 0.5,
                    "years": 1.0,
                    "end_date": "2026-02-13",
                    "windows": {
                        "full": {"status": "completed", "cagr": 0.10, "max_dd": -0.10, "sharpe": 0.5},
                    },
                }
            ),
            encoding="utf-8",
        )
        payload = run(
            argparse.Namespace(
                target_book=str(target),
                fixed_swaps=str(swaps),
                price_cache=str(cache),
                baseline_metrics=str(baseline_metrics),
                baseline_replay_dir="",
                output_dir=str(root / "out"),
                starting_capital=10000.0,
                cost_bps=25.0,
                fractional_shares=False,
                max_fill_lag_days=7,
                max_reasonable_weight_sum=1.05,
                replay_end_date="2026-02-13",
                official_baseline_end_date="2026-02-13",
                oos_start="",
                oos_end="",
                oos2_start="",
                oos2_end="",
                cash_carry_mode="none",
                cash_rate_source="DGS3MO",
                cash_rate_path="",
                cash_rate_lag_days=1,
                cash_carry_haircut_bps=50.0,
                cash_carry_day_count=365,
                concentration_absolute_top1_warning=0.40,
                concentration_absolute_top1_block=0.45,
                concentration_absolute_top3_warning=0.85,
                concentration_absolute_top3_severe_warning=0.90,
            )
        )
        assert payload["status"] == "completed"
        assert payload["diagnostics"]["requested_swap_count"] == 1
        assert payload["diagnostics"]["applied_count"] == 1
        assert payload["production_activation_allowed"] is False
        assert payload["fullrun_allowed"] is False
        out_book = pd.read_csv(root / "out" / "event_matched_target_book.csv")
        day = out_book[out_book["rebalance_date"].eq(dates[0])]
        assert set(day["ticker"]) == {"AAA", "WIN", "CASH"}
        assert abs(day.loc[day["ticker"].eq("CASH"), "weight"].sum() - 0.50) < 1e-12
        assert (root / "out" / "broker_replay" / "metrics.json").exists()


def main() -> int:
    test_event_matched_broker_ab_preserves_cash_and_applies_fixed_swap()
    print("event_matched_replacement_quality_broker_ab_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
