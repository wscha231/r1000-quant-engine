#!/usr/bin/env python3
"""Smoke checks for alpha-selector leader-basket circuit grid."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_alpha_selector_leader_circuit_grid import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2025-10-01") -> None:
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


def test_leader_circuit_grid_builds_daily_state_without_forward_labels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "leader_circuit"
        cache.mkdir()
        # Rise, break, and recover enough to exercise state transitions.
        aaa = [100 + i for i in range(30)] + [130, 124, 118, 111, 106, 102, 99, 101, 104, 108] + [110 + i for i in range(35)]
        bbb = [50 + 0.5 * i for i in range(len(aaa))]
        _write_px(cache, "AAA", aaa)
        _write_px(cache, "BBB", bbb)
        target = root / "target_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2025-10-01", "ticker": "AAA", "weight": 0.70, "Name": "Leader A"},
                {"rebalance_date": "2025-10-01", "ticker": "BBB", "weight": 0.30, "Name": "Leader B"},
            ]
        ).to_csv(target, index=False)
        payload = run(
            argparse.Namespace(
                alpha_selector_dir=str(root / "missing_alpha_selector_dir"),
                target_book=str(target),
                top_variants=1,
                price_cache=str(cache),
                portfolio_kind="main",
                output_dir=str(out),
                grid="0.80:0.50",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                no_integer_shares=False,
                max_fill_lag_days=7,
            )
        )
        assert payload["status"] == "completed"
        assert payload["valid_for_production"] is True
        summary = pd.read_csv(out / "summary.csv")
        assert len(summary) == 1
        states = pd.read_csv(next(out.glob("*/leader_circuit_states.csv")))
        assert {"date", "state", "multiplier", "dd20", "dd50"}.issubset(states.columns)
        circuit_target = pd.read_csv(next(out.glob("*/leader_circuit_target_book.csv")))
        assert set(circuit_target["ticker"]) == {"AAA", "BBB"}
        assert float(circuit_target["weight"].max()) <= 0.70


def main() -> int:
    test_leader_circuit_grid_builds_daily_state_without_forward_labels()
    print("alpha_selector_leader_circuit_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
