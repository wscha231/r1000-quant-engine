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

from tools.run_alpha_selector_market_circuit_grid import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_px(cache: Path, ticker: str, closes: list[float], dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame({"Adj Close": closes, "Close": closes, "Open": closes}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def write_target(path: Path, dates: pd.DatetimeIndex, tickers: tuple[str, str], weight: float = 0.5) -> None:
    rows = []
    for dt in [dates[20], dates[70], dates[120]]:
        for ticker in tickers:
            rows.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "weight": weight})
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_alpha_selector_market_circuit_grid_selects_best_source_variant() -> None:
    tmp = REPO_ROOT / "_tmp_alpha_selector_market_circuit_grid_smoke"
    if tmp.exists():
        shutil.rmtree(tmp)
    cache = tmp / "cache_prices"
    alpha = tmp / "alpha_selector"
    cache.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-02", periods=180)
    qqq = [100.0 + i * 0.03 for i in range(len(dates))]
    for i in range(85, 112):
        qqq[i] = qqq[i - 1] * 0.975
    for i in range(112, len(qqq)):
        qqq[i] = qqq[i - 1] * 1.005
    strong = [50.0 + i * 0.04 for i in range(len(dates))]
    weak = [40.0 + i * 0.01 for i in range(len(dates))]
    for i in range(85, 112):
        strong[i] = strong[i - 1] * 0.965
        weak[i] = weak[i - 1] * 0.985
    for i in range(112, len(strong)):
        strong[i] = strong[i - 1] * 1.007
        weak[i] = weak[i - 1] * 1.001
    write_px(cache, "QQQ", qqq, dates)
    write_px(cache, "AAA", strong, dates)
    write_px(cache, "BBB", [x * 0.9 for x in strong], dates)
    write_px(cache, "CCC", weak, dates)
    write_px(cache, "DDD", [x * 0.95 for x in weak], dates)
    write_target(alpha / "strong_variant" / "target_book.csv", dates, ("AAA", "BBB"))
    write_target(alpha / "weak_variant" / "target_book.csv", dates, ("CCC", "DDD"))
    pd.DataFrame(
        [
            {"variant_id": "strong_variant", "status": "completed", "target_distance": 0.1, "cagr": 0.2},
            {"variant_id": "weak_variant", "status": "completed", "target_distance": 0.2, "cagr": 0.1},
        ]
    ).to_csv(alpha / "summary.csv", index=False)

    class Args:
        alpha_selector_dir = str(alpha)
        target_book = ""
        price_cache = str(cache)
        portfolio_kind = "main"
        output_dir = str(tmp / "out")
        top_variants = 2
        grid = "0.80:0.50"
        trigger_modes = "return_ma,ma50"
        starting_capital = 100000.0
        fill_mode = "next_close"
        cost_bps = 25.0
        no_integer_shares = False
        max_fill_lag_days = 7

    payload = run(Args())
    assert payload["status"] == "completed"
    assert payload["valid_for_production"] is True
    assert payload["metric_mode"] == "alpha_selector_market_circuit_grid_best_next_close"
    assert payload["variant_count"] == 2
    assert (tmp / "out" / "summary.csv").exists()
    best = json.loads((tmp / "out" / "best_metrics.json").read_text(encoding="utf-8"))
    assert best["candidate_id"] == "main_alpha_selector_market_circuit_grid"
    summary = pd.read_csv(tmp / "out" / "summary.csv")
    assert len(summary) == 2
    assert set(summary["alpha_selector_variant"]) == {"strong_variant", "weak_variant"}
    shutil.rmtree(tmp)


def main() -> int:
    test_alpha_selector_market_circuit_grid_selects_best_source_variant()
    print("alpha_selector_market_circuit_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
