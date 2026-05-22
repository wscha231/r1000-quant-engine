#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_current_portfolio_status_report import build_report  # noqa: E402


def _write_fixture(root: Path, portfolio: str, ticker: str, shares: float, price: float, cash: float) -> None:
    broker = root / "broker_replay" / portfolio
    broker.mkdir(parents=True, exist_ok=True)
    equity = cash + shares * price
    pd.DataFrame(
        [
            {
                "date": "2026-05-10",
                "equity_usd": equity,
                "cash_usd": cash,
                "cash_weight": cash / equity,
                "stock_value_usd": shares * price,
                "position_count": 1,
                "fill_mode": "next_close",
            }
        ]
    ).to_csv(broker / "equity_curve.csv", index=False)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-05-10",
                "ticker": ticker,
                "shares": shares,
                "price": price,
                "market_value_usd": shares * price,
                "weight": shares * price / equity,
                "cost_basis": price - 5.0,
                "unrealized_pnl_usd": shares * 5.0,
                "realized_pnl_usd": 0.0,
            }
        ]
    ).to_csv(broker / "positions_latest.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "side": "BUY",
                "quantity": shares,
                "fill_price": price - 5.0,
                "gross_value": shares * (price - 5.0),
                "fee_usd": 1.0,
                "date": "2026-05-01",
            }
        ]
    ).to_csv(broker / "trades.csv", index=False)
    (broker / "account_state_latest.json").write_text(
        json.dumps({"as_of_date": "2026-05-10", "equity_usd": equity, "cash_usd": cash}),
        encoding="utf-8",
    )


def test_current_portfolio_status_report_extends_to_requested_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_fixture(root, "main", "AAA", 10.0, 100.0, 100.0)
        _write_fixture(root, "concentrated", "BBB", 20.0, 50.0, 0.0)

        def loader(tickers: list[str], start_date: str, end_date: str) -> dict[str, pd.Series]:
            assert set(tickers) == {"AAA", "BBB"}
            idx = pd.to_datetime(["2026-05-11", "2026-05-12"])
            return {
                "AAA": pd.Series([101.0, 110.0], index=idx),
                "BBB": pd.Series([49.0, 55.0], index=idx),
            }

        out = root / "status"
        payload = build_report(
            Namespace(latest_run=str(root), output_dir=str(out), as_of_date="2026-05-12", no_yfinance=False),
            price_loader=loader,
        )
        assert payload["status"] == "completed"
        assert payload["portfolios"]["main"]["evaluated_as_of_date"] == "2026-05-12"

        holdings = pd.read_csv(out / "main" / "current_holdings_latest.csv")
        aaa = holdings[holdings["ticker"].eq("AAA")].iloc[0]
        cash = holdings[holdings["ticker"].eq("CASH")].iloc[0]
        assert round(float(aaa["price"]), 2) == 110.0
        assert round(float(aaa["market_value_usd"]), 2) == 1100.0
        assert round(float(cash["weight"]), 4) == round(100.0 / 1200.0, 4)

        windows = pd.read_csv(out / "performance_windows.csv")
        assert {"main", "concentrated"} <= set(windows["portfolio"])
        assert "FULL" in set(windows["horizon"])
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_current_portfolio_status_report_extends_to_requested_close()
    print("current_portfolio_status_report_smoke: PASS")
