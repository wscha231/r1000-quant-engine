#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_concentrated_broker_grid import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_px(cache: Path, ticker: str, closes: list[float], dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame({"Adj Close": closes, "Close": closes, "Open": closes}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_concentrated_broker_grid_replays_comparison_variants() -> None:
    tmp = REPO_ROOT / "_tmp_concentrated_broker_grid_smoke"
    if tmp.exists():
        shutil.rmtree(tmp)
    reports = tmp / "outputs" / "reports"
    reports.mkdir(parents=True)
    cache = tmp / "cache_prices"
    cache.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-02", periods=120)
    write_px(cache, "AAA", [40 + i * 0.2 for i in range(len(dates))], dates)
    write_px(cache, "BBB", [30 + i * 0.1 for i in range(len(dates))], dates)
    write_px(cache, "CCC", [20 + i * 0.05 for i in range(len(dates))], dates)

    target = reports / "operating_concentrated_target_book.csv"
    pd.DataFrame(
        [
            {"rebalance_date": "2020-01-31", "ticker": "AAA", "weight": 0.5, "target_stock_names": 2, "weighting_mode": "winner_take_all", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2020-01-31", "ticker": "BBB", "weight": 0.5, "target_stock_names": 2, "weighting_mode": "winner_take_all", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2020-01-31", "ticker": "AAA", "weight": 0.34, "target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2020-01-31", "ticker": "BBB", "weight": 0.33, "target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2020-01-31", "ticker": "CCC", "weight": 0.33, "target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
        ]
    ).to_csv(target, index=False)
    pd.DataFrame(
        [
            {"portfolio_mode": "concentrated_alpha", "target_stock_names": 2, "weighting_mode": "winner_take_all", "rebalance_interval_months": 1, "strategy_cagr": 0.8, "max_dd": -0.3, "sharpe": 1.2},
            {"portfolio_mode": "concentrated_alpha", "target_stock_names": 3, "weighting_mode": "score_power", "rebalance_interval_months": 1, "strategy_cagr": 0.5, "max_dd": -0.1, "sharpe": 1.4},
        ]
    ).to_csv(reports / "concentrated_strategy_comparison.csv", index=False)

    class Args:
        target_book = str(target)
        price_cache = str(cache)
        output_dir = str(tmp / "grid")
        max_variants = 2
        starting_capital = 100000.0
        fill_mode = "next_close"
        cost_bps = 25.0
        no_integer_shares = False
        max_fill_lag_days = 7
        tail_row_fill_fallback_same_close = False

    payload = run(Args())
    assert payload["status"] == "completed"
    assert payload["valid_for_production"] is True
    assert payload["variant_count"] == 2
    summary = pd.read_csv(tmp / "grid" / "summary.csv")
    assert len(summary) == 2
    assert set(summary["target_stock_names"].astype(str)) == {"2", "3"}
    best = json.loads((tmp / "grid" / "best_metrics.json").read_text(encoding="utf-8"))
    assert best["metric_mode"] == "concentrated_broker_grid_best_next_close"
    shutil.rmtree(tmp)


def main() -> int:
    test_concentrated_broker_grid_replays_comparison_variants()
    print("concentrated_broker_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
