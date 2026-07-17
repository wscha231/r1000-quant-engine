#!/usr/bin/env python3
"""Synthetic fixed-horizon entry/exit answer-notebook checks."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_historical_trade_answer_notebook as notebook  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, dates: pd.DatetimeIndex, close: np.ndarray) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Close": close}, index=dates).to_parquet(cache / px_cache_name(ticker))


def test_fixed_next_close_exit_path_and_labels() -> None:
    dates = pd.bdate_range("2024-01-02", periods=220)
    spy = np.linspace(100.0, 120.0, len(dates))
    aaa = np.linspace(100.0, 180.0, len(dates))
    bbb = np.linspace(100.0, 80.0, len(dates))
    trades = pd.DataFrame(
        [
            {
                "trade_id": "a",
                "ticker": "AAA",
                "entry_date": dates[10],
                "exit_date": dates[50],
                "realized_return": 0.20,
                "alpha_vs_benchmark": 0.10,
                "exit_reason": "scheduled_rebalance",
                "entry_sleeve": "compounder",
                "entry_regime_state": "bull",
                "source_journal": "main",
            },
            {
                "trade_id": "b",
                "ticker": "BBB",
                "entry_date": dates[10],
                "exit_date": dates[50],
                "realized_return": -0.15,
                "alpha_vs_benchmark": -0.10,
                "exit_reason": "scheduled_rebalance",
                "entry_sleeve": "scout",
                "entry_regime_state": "bull",
                "source_journal": "main",
            },
        ]
    )
    with tempfile.TemporaryDirectory(prefix="run287-trade-answer-") as raw:
        root = Path(raw)
        cache = root / "cache"
        write_price(cache, "SPY", dates, spy)
        write_price(cache, "AAA", dates, aaa)
        write_price(cache, "BBB", dates, bbb)
        graded = notebook.grade_trades(trades, cache).set_index("ticker")
        assert graded.loc["AAA", "post_exit_entry_date"] == dates[51].date().isoformat()
        assert int(graded.loc["AAA", "exit_grade_horizon"]) == 63
        assert graded.loc["AAA", "exit_answer"] == "POSSIBLE_PREMATURE_EXIT_REVIEW"
        assert graded.loc["AAA", "entry_answer"] == "GOOD_ENTRY_POSITIVE_ALPHA"
        assert graded.loc["BBB", "exit_answer"] == "GOOD_EXIT_AVOIDED_UNDERPERFORMANCE"
        assert graded.loc["BBB", "entry_answer"] == "WRONG_ENTRY_LOSS_AND_LAG"
        assert bool(graded["replacement_relative_answer_unknown"].all())
        assert not bool(graded["automatic_checklist_change_allowed"].any())


def test_end_to_end_manifest_is_non_executable() -> None:
    dates = pd.bdate_range("2024-01-02", periods=220)
    with tempfile.TemporaryDirectory(prefix="run287-trade-answer-build-") as raw:
        root = Path(raw)
        cache = root / "cache"
        write_price(cache, "SPY", dates, np.linspace(100.0, 120.0, len(dates)))
        write_price(cache, "AAA", dates, np.linspace(100.0, 180.0, len(dates)))
        trade_path = root / "trades.csv"
        pd.DataFrame(
            [
                {
                    "trade_id": "a",
                    "ticker": "AAA",
                    "entry_date": dates[10].date().isoformat(),
                    "exit_date": dates[50].date().isoformat(),
                    "realized_return": 0.20,
                    "alpha_vs_benchmark": 0.10,
                    "exit_reason": "scheduled_rebalance",
                    "entry_sleeve": "compounder",
                    "entry_regime_state": "bull",
                    "source_journal": "main",
                }
            ]
        ).to_csv(trade_path, index=False)
        output = root / "out"
        result = notebook.build(
            argparse.Namespace(
                trade_journal=str(trade_path),
                price_cache=str(cache),
                output_dir=str(output),
            )
        )
        assert result["trade_count"] == 1
        assert result["exit_grade_ready_count"] == 1
        assert not result["backtest_executed"]
        assert not result["orders_generated"]
        assert not result["production_activation_allowed"]
        manifest = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert manifest["automatic_checklist_change_allowed"] is False
        assert (output / "report.md").is_file()


if __name__ == "__main__":
    test_fixed_next_close_exit_path_and_labels()
    test_end_to_end_manifest_is_non_executable()
    print("run287_historical_trade_answer_notebook_smoke: PASS")
