#!/usr/bin/env python3
"""Smoke test for the bounded Reserve-mode evaluator."""
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.evaluate_run287_reserve_asset_policy import evaluate  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_prices(cache: Path, ticker: str, closes: list[float], start: str = "2020-01-02") -> None:
    index = pd.bdate_range(start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": 1_000_000,
        },
        index=index,
    ).to_parquet(cache / px_cache_name(ticker))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        closes = [100.0 + index * 0.1 for index in range(30)]
        for ticker in ("AAA", "SPY", "BIL"):
            write_prices(cache, ticker, closes)
        write_prices(cache, "SGOV", closes[:5], start="2020-02-03")
        rows = [
            {"rebalance_date": "2020-01-02", "ticker": "AAA", "weight": 0.60},
            {"rebalance_date": "2020-01-02", "ticker": "CASH", "weight": 0.40},
        ]
        main_book = root / "main.csv"
        concentrated_book = root / "concentrated.csv"
        pd.DataFrame(rows).to_csv(main_book, index=False)
        pd.DataFrame(rows).to_csv(concentrated_book, index=False)
        rate = root / "rates.csv"
        pd.DataFrame([{"date": "2019-12-31", "value": 3.0}]).to_csv(rate, index=False)
        out = root / "out"
        payload = evaluate(
            Namespace(
                main_target_book=str(main_book),
                concentrated_target_book=str(concentrated_book),
                price_cache=str(cache),
                cash_rate_path=str(rate),
                output_dir=str(out),
                starting_capital=10000.0,
                cost_bps=25.0,
                cash_haircut_bps=50.0,
            )
        )
        assert payload["status"] == "READY_RESERVE_ASSET_RESEARCH", payload
        assert all(row["passed"] for row in payload["zero_yield_exact_parity"].values())
        metrics = pd.read_csv(out / "reserve_mode_metrics.csv")
        assert len(metrics) == 8
        assert set(metrics["mode"]) == {
            "BROKER_CASH_OR_MMF",
            "DGS3MO_CARRY",
            "BIL_TOTAL_RETURN",
            "SGOV_TOTAL_RETURN",
        }
        assert set(metrics.loc[metrics["mode"].eq("SGOV_TOTAL_RETURN"), "status"]) == {"BLOCKED_SHORT_HISTORY"}
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["fullrun_executed"] is False
        assert summary["production_enabled"] is False
        assert summary["live_trading_enabled"] is False
    print("run287_reserve_asset_evaluation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
