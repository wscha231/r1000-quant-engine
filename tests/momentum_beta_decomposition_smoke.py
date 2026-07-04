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

from tools.run_momentum_beta_decomposition import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def test_momentum_beta_decomposition_outputs_research_tables() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        dates = pd.bdate_range("2025-01-01", periods=260)
        pd.DataFrame(
            {
                "Open": range(100, 360),
                "Close": range(100, 360),
                "Adj Close": range(100, 360),
                "Volume": [1_000_000] * len(dates),
            },
            index=dates,
        ).to_parquet(cache / px_cache_name("SPY"))
        rows = []
        tickers = [f"T{i}" for i in range(8)]
        for month, dt in enumerate(pd.date_range("2025-03-31", periods=8, freq="ME")):
            for idx, ticker in enumerate(tickers):
                rows.append(
                    {
                        "rebalance_date": dt.date().isoformat(),
                        "ticker": ticker,
                        "portfolio_kind": "concentrated",
                        "weight": 0.1 if idx < 5 else 0.0,
                        "period_forward_return": 0.01 * (idx + 1) + month * 0.001,
                        "mom_12m": idx,
                    }
                )
        book = root / "operating_concentrated_target_book.csv"
        pd.DataFrame(rows).to_csv(book, index=False)
        payload = run(
            argparse.Namespace(
                target_books=[str(book)],
                price_cache=str(cache),
                market_ticker="SPY",
                output_dir=str(root / "out"),
            )
        )
        assert payload["status"] == "completed", payload
        assert payload["research_only"] is True
        assert payload["selection_or_weight_change_allowed"] is False
        assert (root / "out" / "factor_returns.csv").exists()
        assert (root / "out" / "regression_table.csv").exists()


def main() -> int:
    test_momentum_beta_decomposition_outputs_research_tables()
    print("momentum_beta_decomposition_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
