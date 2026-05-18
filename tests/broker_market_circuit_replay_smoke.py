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

from tools.run_broker_market_circuit_replay import run
from tools.run_weekly_evaluation import px_cache_name


def write_px(cache: Path, ticker: str, closes: list[float], dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame({"Adj Close": closes, "Close": closes, "Open": closes}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_broker_market_circuit_replay_outputs_account_metrics() -> None:
    tmp = REPO_ROOT / "_tmp_broker_market_circuit_smoke"
    if tmp.exists():
        shutil.rmtree(tmp)
    cache = tmp / "cache_prices"
    cache.mkdir(parents=True)
    dates = pd.bdate_range("2020-01-02", periods=170)
    spy = [100.0 + i * 0.05 for i in range(len(dates))]
    for i in range(80, 105):
        spy[i] = spy[i - 1] * 0.975
    for i in range(105, len(spy)):
        spy[i] = spy[i - 1] * 1.006
    stock = [50.0 + i * 0.04 for i in range(len(dates))]
    for i in range(80, 105):
        stock[i] = stock[i - 1] * 0.965
    for i in range(105, len(stock)):
        stock[i] = stock[i - 1] * 1.008
    write_px(cache, "SPY", spy, dates)
    write_px(cache, "AAA", stock, dates)
    write_px(cache, "BBB", [x * 0.8 for x in stock], dates)
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
        output_dir = str(tmp / "out")
        portfolio_kind = "main"
        starting_capital = 100000.0
        fill_mode = "next_close"
        cost_bps = 25.0
        no_integer_shares = False
        max_fill_lag_days = 7
        caution_multiplier = 0.60
        crisis_multiplier = 0.25
        trigger_mode = "ma50"

    metrics = run(Args())
    assert metrics["status"] == "completed"
    assert metrics["research_only"] is True
    assert metrics["production_activation_allowed"] is False
    assert metrics["valid_for_production"] is True
    assert metrics["circuit_event_count"] > 2
    states = pd.read_csv(tmp / "out" / "market_circuit_states.csv")
    assert {"normal", "caution", "crisis"}.intersection(set(states["state"].astype(str)))
    payload = json.loads((tmp / "out" / "metrics.json").read_text(encoding="utf-8"))
    assert payload["metric_mode"] == "broker_market_circuit_next_close"
    assert payload["trigger_mode"] == "ma50"
    shutil.rmtree(tmp)


def main() -> int:
    test_broker_market_circuit_replay_outputs_account_metrics()
    print("broker_market_circuit_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
