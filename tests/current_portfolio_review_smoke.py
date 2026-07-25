#!/usr/bin/env python3
"""Smoke checks for exact-close current portfolio review."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_current_portfolio_review import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, close: float) -> None:
    frame = pd.DataFrame(
        {
            "Open": [close],
            "Close": [close],
            "Adj Close": [close],
            "Volume": [1_000_000],
        },
        index=pd.DatetimeIndex(["2026-07-24"]),
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "review"
        cache.mkdir()
        (cache / "replay_price_cache_manifest.json").write_text(
            json.dumps({"schema_version": "test-price-cache-v1"}),
            encoding="utf-8",
        )
        _write_price(cache, "AAA", 110.0)
        _write_price(cache, "BBB", 80.0)

        current = root / "current.json"
        current.write_text(
            json.dumps(
                {
                    "as_of_date": "2026-07-24",
                    "valuation_close_date": "2026-07-23",
                    "current_portfolios": {
                        "main": {
                            "equity_usd": 1_000.0,
                            "cash_weight": 0.10,
                            "positions": [{"ticker": "AAA", "shares": 8.0}],
                        },
                        "concentrated": {
                            "equity_usd": 1_000.0,
                            "cash_weight": 0.20,
                            "positions": [{"ticker": "BBB", "shares": 10.0}],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        tape = root / "tape.json"
        tape.write_text(
            json.dumps({"common_close_date": "2026-07-24"}), encoding="utf-8"
        )
        costs = root / "costs.csv"
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "variant_id": "main_test",
                    "cost_bps": 25.0,
                    "cagr": 0.30,
                    "max_dd": -0.20,
                    "sharpe": 1.0,
                },
                {
                    "portfolio_kind": "concentrated",
                    "variant_id": "concentrated_test",
                    "cost_bps": 25.0,
                    "cagr": 0.55,
                    "max_dd": -0.30,
                    "sharpe": 1.0,
                },
            ]
        ).to_csv(costs, index=False)

        payload = run(current, cache, tape, costs, output)
        assert payload["decision"] == "RETAIN_ACCEPTED_CHAMPION"
        assert not payload["challenger_evaluation"]["main"]["cagr_pass"]
        assert not payload["challenger_evaluation"]["concentrated"]["drawdown_pass"]
        assert payload["portfolio_summaries"]["main"]["exact_close_coverage"] == 1.0
        holdings = pd.read_csv(output / "current_holdings_exact_close.csv")
        for _, group in holdings.groupby("portfolio"):
            assert abs(group["current_weight"].sum() - 1.0) < 1e-9
            assert (group["reconstruction_action"] == "RETAIN").all()

    print("current_portfolio_review_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
