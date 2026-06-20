#!/usr/bin/env python3
"""Smoke tests for B2 alpha/beta attribution."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_alpha_beta_attribution import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, dates: pd.DatetimeIndex, returns: np.ndarray) -> None:
    price = 100.0 * np.cumprod(1.0 + returns)
    frame = pd.DataFrame({"Adj Close": price, "Close": price, "Open": price}, index=dates)
    cache.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache / px_cache_name(ticker))


def _build_fixture(root: Path) -> tuple[Path, Path]:
    latest = root / "latest"
    cache = root / "cache_prices"
    dates = pd.bdate_range("2024-01-02", periods=90)
    # Varying returns avoid a degenerate regression. QQQ/SMH/SOXX equal SPY so
    # the fixture pins SPY beta ~= 1 and residual alpha ~= 0.
    spy_returns = np.array([0.001 + ((i % 7) - 3) * 0.0002 for i in range(len(dates))], dtype=float)
    for ticker in ("SPY", "QQQ", "SMH", "SOXX"):
        _write_price(cache, ticker, dates, spy_returns)
    equity = 100_000.0 * np.cumprod(1.0 + spy_returns)
    for portfolio in ("main", "concentrated"):
        broker = latest / "broker_replay" / portfolio
        broker.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "date": dates.date.astype(str),
                "equity_usd": equity,
                "cash_weight": [0.10] * len(dates),
            }
        ).to_csv(broker / "equity_curve.csv", index=False)
        (broker / "metrics.json").write_text(
            json.dumps({"cagr": 0.25, "max_dd": -0.05, "metric_mode": "broker_ledger_next_close"}),
            encoding="utf-8",
        )
        holdings_rows = []
        for i, dt in enumerate(dates):
            holdings_rows.append({"date": dt.date().isoformat(), "ticker": "AAA", "market_value_usd": 60_000 + i * 150, "weight": 0.60})
            holdings_rows.append({"date": dt.date().isoformat(), "ticker": "BBB", "market_value_usd": 30_000 + i * 30, "weight": 0.30})
        pd.DataFrame(holdings_rows).to_csv(broker / "holdings_daily.csv", index=False)
    return latest, cache


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest, cache = _build_fixture(root)
        out = root / "out"
        payload = run(latest, cache, out)
        assert payload["schema_version"] == "alpha-beta-attribution-v1"
        assert payload["production_mutation_allowed"] is False
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
        assert (out / "portfolio_factor_summary.csv").exists()
        for portfolio in ("main", "concentrated"):
            block = payload["portfolios"][portfolio]
            assert block["status"] == "completed", block
            assert block["observations"] >= 80, block
            assert abs(float(block["spy_beta"]) - 1.0) < 1e-6, block
            assert abs(float(block["stock_selection_residual_alpha"])) < 1e-6, block
            assert abs(float(block["smh_soxx_semiconductor_beta"])) < 1e-9, block
            assert "sector_theme_beta_proxy" in block
            assert block["name_contribution_status"] == "completed"
            assert block["top_1_winner_contribution"] > 0
            assert (out / portfolio / "factor_returns.csv").exists()
            assert (out / portfolio / "name_contribution.csv").exists()
    print("alpha beta attribution smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
