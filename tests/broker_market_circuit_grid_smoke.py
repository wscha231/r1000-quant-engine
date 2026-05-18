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

from tools.run_broker_market_circuit_grid import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_px(cache: Path, ticker: str, closes: list[float], dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame({"Adj Close": closes, "Close": closes, "Open": closes}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_broker_market_circuit_grid_writes_best_metrics() -> None:
    tmp = REPO_ROOT / "_tmp_broker_market_circuit_grid_smoke"
    if tmp.exists():
        shutil.rmtree(tmp)
    cache = tmp / "cache_prices"
    cache.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-02", periods=170)
    qqq = [100.0 + i * 0.04 for i in range(len(dates))]
    for i in range(80, 105):
        qqq[i] = qqq[i - 1] * 0.975
    for i in range(105, len(qqq)):
        qqq[i] = qqq[i - 1] * 1.005
    stock = [50.0 + i * 0.03 for i in range(len(dates))]
    for i in range(80, 105):
        stock[i] = stock[i - 1] * 0.965
    for i in range(105, len(stock)):
        stock[i] = stock[i - 1] * 1.007
    write_px(cache, "QQQ", qqq, dates)
    write_px(cache, "AAA", stock, dates)
    write_px(cache, "BBB", [x * 0.9 for x in stock], dates)
    target = tmp / "target.csv"
    pd.DataFrame(
        [
            {"rebalance_date": "2020-01-31", "ticker": "AAA", "weight": 0.5},
            {"rebalance_date": "2020-01-31", "ticker": "BBB", "weight": 0.5},
            {"rebalance_date": "2020-04-30", "ticker": "AAA", "weight": 0.5},
            {"rebalance_date": "2020-04-30", "ticker": "BBB", "weight": 0.5},
        ]
    ).to_csv(target, index=False)

    class Args:
        target_book = str(target)
        price_cache = str(cache)
        output_dir = str(tmp / "grid")
        portfolio_kind = "main"
        grid = "0.80:0.50,0.60:0.25"
        starting_capital = 100000.0
        fill_mode = "next_close"
        cost_bps = 25.0
        no_integer_shares = False
        max_fill_lag_days = 7
        trigger_modes = "return_ma,ma50"

    payload = run(Args())
    assert payload["status"] == "completed"
    assert payload["valid_for_production"] is True
    assert payload["market_circuit_grid"] is True
    assert payload["variant_count"] == 4
    assert (tmp / "grid" / "summary.csv").exists()
    best = json.loads((tmp / "grid" / "best_metrics.json").read_text(encoding="utf-8"))
    assert best["metric_mode"] == "broker_market_circuit_grid_best_next_close"
    summary = pd.read_csv(tmp / "grid" / "summary.csv")
    assert len(summary) == 4
    assert set(summary["trigger_mode"]) == {"return_ma", "ma50"}
    shutil.rmtree(tmp)


def main() -> int:
    test_broker_market_circuit_grid_writes_best_metrics()
    print("broker_market_circuit_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
