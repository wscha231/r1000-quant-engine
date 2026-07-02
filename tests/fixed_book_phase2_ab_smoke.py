#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_fixed_book_concentrated_sizing_ab import run as run_sizing  # noqa: E402
from tools.run_fixed_book_hold_exit_timing_ab import run as run_hold_exit  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


class Args:
    pass


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


def _base_args(root: Path, target: Path, cache: Path, out_name: str) -> Args:
    args = Args()
    args.target_book = str(target)
    args.price_cache = str(cache)
    args.output_dir = str(root / out_name)
    args.portfolio_kind = "concentrated"
    args.starting_capital = 100_000.0
    args.cost_bps = 25.0
    args.max_fill_lag_days = 7
    args.replay_end_date = ""
    args.official_baseline_end_date = ""
    args.cash_carry_mode = "none"
    args.cash_rate_source = "DGS3MO"
    args.cash_rate_path = ""
    args.cash_rate_lag_days = 1
    args.cash_carry_haircut_bps = 50.0
    args.cash_carry_day_count = 365
    return args


def _write_hold_exit_book(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "rebalance_date": "2026-01-02",
                "ticker": "AAA",
                "weight": 0.40,
                "target_weight": 0.40,
                "rs_benchmark_3m": 0.12,
                "rs_benchmark_6m": 0.18,
                "price_above_ma200": 1.0,
                "actual_results_score": 1.0,
            },
            {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.40, "target_weight": 0.40},
            {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.20, "target_weight": 0.20},
            {"rebalance_date": "2026-01-09", "ticker": "BBB", "weight": 0.50, "target_weight": 0.50},
            {"rebalance_date": "2026-01-09", "ticker": "CCC", "weight": 0.30, "target_weight": 0.30},
            {"rebalance_date": "2026-01-09", "ticker": "CASH", "weight": 0.20, "target_weight": 0.20},
        ]
    ).to_csv(path, index=False)


def _write_sizing_book(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "rebalance_date": "2026-01-02",
                "ticker": "AAA",
                "weight": 0.36,
                "target_weight": 0.36,
                "rs_benchmark_3m": 0.15,
                "volatility_63d": 0.35,
            },
            {
                "rebalance_date": "2026-01-02",
                "ticker": "BBB",
                "weight": 0.30,
                "target_weight": 0.30,
                "rs_benchmark_3m": 0.05,
                "volatility_63d": 0.20,
            },
            {
                "rebalance_date": "2026-01-02",
                "ticker": "CCC",
                "weight": 0.24,
                "target_weight": 0.24,
                "rs_benchmark_3m": -0.03,
                "volatility_63d": 0.15,
            },
            {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.10, "target_weight": 0.10},
        ]
    ).to_csv(path, index=False)


def test_fixed_book_hold_exit_extends_dropped_leader_without_regenerating_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100, 102, 104, 106, 108, 110, 112, 114],
            "BBB": [100, 100, 101, 101, 102, 102, 103, 103],
            "CCC": [50, 51, 52, 53, 54, 55, 56, 57],
        }.items():
            _write_px(cache, ticker, [float(v) for v in closes])
        target = root / "hold_exit_book.csv"
        _write_hold_exit_book(target)

        args = _base_args(root, target, cache, "hold_exit")
        args.arms = "baseline_cash_carry,delay_target_exit_only_if_leader,partial_replace_50"
        payload = run_hold_exit(args)

        assert payload["status"] == "completed"
        metrics = pd.read_csv(root / "hold_exit" / "arm_metrics.csv")
        assert set(metrics["broker_status"]) == {"completed"}
        actions = pd.read_csv(root / "hold_exit" / "delay_target_exit_only_if_leader" / "actions.csv")
        assert "AAA" in set(actions["ticker"])
        adjusted = pd.read_csv(root / "hold_exit" / "delay_target_exit_only_if_leader" / "target_book.csv")
        assert "AAA" in set(adjusted.loc[adjusted["rebalance_date"].eq("2026-01-09"), "ticker"])
        assert adjusted.groupby("rebalance_date")["weight"].sum().max() <= 1.000001


def test_fixed_book_sizing_preserves_names_cash_and_respects_cap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100, 110, 120, 130, 140, 150, 160, 170],
            "BBB": [80, 82, 84, 86, 88, 90, 92, 94],
            "CCC": [50, 49, 50, 49, 50, 49, 50, 49],
        }.items():
            _write_px(cache, ticker, [float(v) for v in closes])
        target = root / "sizing_book.csv"
        _write_sizing_book(target)

        args = _base_args(root, target, cache, "sizing")
        args.arms = "baseline_cash_carry,equal_weight_with_cash_preserved,rs_plus_low_vol_blend"
        args.max_single_weight = 0.30
        payload = run_sizing(args)

        assert payload["status"] == "completed"
        metrics = pd.read_csv(root / "sizing" / "arm_metrics.csv")
        assert set(metrics["broker_status"]) == {"completed"}
        assert int(metrics.loc[metrics["arm"].eq("equal_weight_with_cash_preserved"), "cap_breach_count"].iloc[0]) == 0
        adjusted = pd.read_csv(root / "sizing" / "equal_weight_with_cash_preserved" / "target_book.csv")
        stocks = adjusted[~adjusted["ticker"].eq("CASH")]
        assert set(stocks["ticker"]) == {"AAA", "BBB", "CCC"}
        assert stocks["weight"].max() <= 0.300001
        assert abs(float(stocks["weight"].sum()) - 0.90) < 1e-6
        assert abs(float(adjusted.loc[adjusted["ticker"].eq("CASH"), "weight"].sum()) - 0.10) < 1e-6


def main() -> int:
    test_fixed_book_hold_exit_extends_dropped_leader_without_regenerating_names()
    test_fixed_book_sizing_preserves_names_cash_and_respects_cap()
    print("fixed_book_phase2_ab_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
