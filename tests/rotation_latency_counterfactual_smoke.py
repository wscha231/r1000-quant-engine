#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_rotation_latency_counterfactual import run
from tools.run_weekly_evaluation import px_cache_name


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_rotation_latency_counterfactual_runs_three_arms() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100.0] * 80,
            "BBB": [100.0] * 80,
            "CCC": [100.0 + i for i in range(80)],
            "DDD": [100.0 - i * 0.2 for i in range(80)],
        }.items():
            _write_px(cache, ticker, closes)

        base = root / "base_target_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.4, "target_weight": 0.4},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.3, "target_weight": 0.3},
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.3, "target_weight": 0.3},
            ]
        ).to_csv(base, index=False)

        prev_current = root / "current.csv"
        pd.DataFrame(
            [
                {"portfolio": "concentrated", "ticker": "AAA", "current_weight": 0.4},
                {"portfolio": "concentrated", "ticker": "BBB", "current_weight": 0.3},
                {"portfolio": "concentrated", "ticker": "CASH", "current_weight": 0.3},
            ]
        ).to_csv(prev_current, index=False)

        prev_raw = root / "raw.csv"
        pd.DataFrame(
            [
                {"portfolio": "concentrated", "ticker": "CCC", "target_weight": 0.7},
                {"portfolio": "concentrated", "ticker": "CASH", "target_weight": 0.3},
            ]
        ).to_csv(prev_raw, index=False)

        current_target = root / "current_target_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-15", "ticker": "DDD", "weight": 0.6, "target_weight": 0.6},
                {"rebalance_date": "2026-01-15", "ticker": "CASH", "weight": 0.4, "target_weight": 0.4},
            ]
        ).to_csv(current_target, index=False)

        args = argparse.Namespace(
            base_target_book=str(base),
            previous_current_holdings=str(prev_current),
            previous_raw_target=str(prev_raw),
            current_target_book=str(current_target),
            price_cache=str(cache),
            output_dir=str(root / "out"),
            portfolio_kind="concentrated",
            decision_date="2026-01-02",
            replay_end_date="2026-03-31",
            starting_capital=10000.0,
            cost_bps=25.0,
            fractional_shares=False,
            max_fill_lag_days=7,
            max_reasonable_weight_sum=1.05,
            oos_start="2026-02-01",
            oos_end="",
            oos2_start="",
            oos2_end="",
            cash_carry_mode="none",
            cash_rate_source=None,
            cash_rate_path=None,
            cash_rate_lag_days=None,
            cash_carry_haircut_bps=None,
            cash_carry_day_count=None,
        )
        payload = run(args)
        assert payload["research_only"] is True
        assert payload["fullrun_executed"] is False
        assert payload["production_activation_allowed"] is False
        assert len(payload["arms"]) == 3
        assert {arm["arm"] for arm in payload["arms"]} == {
            "june_operating_hold",
            "june_raw_rotation",
            "july_actual_rotation_applied_early",
        }
        assert (root / "out" / "metrics.csv").exists()
        raw_target = pd.read_csv(root / "out" / "june_raw_rotation" / "target_book.csv")
        final = raw_target[raw_target["rebalance_date"].eq("2026-01-02")]
        assert abs(final["weight"].sum() - 1.0) < 1e-12
        assert "Rotation Latency Counterfactual" in (root / "out" / "report.md").read_text(encoding="utf-8")


def main() -> int:
    test_rotation_latency_counterfactual_runs_three_arms()
    print("rotation_latency_counterfactual_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
