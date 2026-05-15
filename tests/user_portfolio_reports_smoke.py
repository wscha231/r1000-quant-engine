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

from tools.run_user_portfolio_reports import build_reports  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_portfolio_fixture(root: Path, portfolio: str) -> None:
    broker = root / "broker_replay" / portfolio
    broker.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2025-12-31",
                "equity_usd": 100000,
                "cash_usd": 10000,
                "cash_weight": 0.10,
                "stock_value_usd": 90000,
                "position_count": 1,
                "fill_mode": "next_close",
            },
            {
                "date": "2026-01-31",
                "equity_usd": 120000,
                "cash_usd": 12000,
                "cash_weight": 0.10,
                "stock_value_usd": 108000,
                "position_count": 1,
                "fill_mode": "next_close",
            },
        ]
    ).to_csv(broker / "equity_curve.csv", index=False)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-31",
                "ticker": "AAA",
                "shares": 100,
                "price": 108,
                "market_value_usd": 10800,
                "weight": 0.09,
                "cost_basis": 90,
                "unrealized_pnl_usd": 1800,
                "realized_pnl_usd": 25,
            }
        ]
    ).to_csv(broker / "positions_latest.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "side": "BUY",
                "quantity": 100,
                "fill_price": 90,
                "gross_value": 9000,
                "fee_usd": 22.5,
                "date": "2025-12-31",
            }
        ]
    ).to_csv(broker / "trades.csv", index=False)
    (broker / "account_state_latest.json").write_text(
        json.dumps(
            {
                "as_of_date": "2026-01-31",
                "equity_usd": 120000,
                "cash_usd": 12000,
                "cash_weight": 0.10,
                "position_count": 1,
            }
        ),
        encoding="utf-8",
    )
    preview = root / "account_ledger_preview" / portfolio
    preview.mkdir(parents=True)
    target_ticker = "AAA" if portfolio == "main" else "BBB"
    target_weight = 0.60 if portfolio == "main" else 0.50
    target_cash = 1.0 - target_weight
    (preview / "preview_metrics.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "as_of_date": "2026-01-31",
                "account_state_as_of_date": "2026-01-31",
                "equity_usd": 120000,
                "cash_usd": 12000,
                "cash_weight": 0.10,
                "target_cash_weight": target_cash,
                "projected_cash_weight": target_cash,
                "order_count": 0,
                "ready_order_count": 0,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "shares": 100,
                "price": 108,
                "market_value_usd": 10800,
                "current_weight": 0.09,
            },
            {
                "ticker": "BBB",
                "shares": 0,
                "price": 55,
                "market_value_usd": 0,
                "current_weight": 0.0,
            },
        ]
    ).to_csv(preview / "positions_current.csv", index=False)
    pd.DataFrame([{"ticker": target_ticker, "target_weight": target_weight}]).to_csv(preview / "target_weights.csv", index=False)
    pd.DataFrame(columns=["ticker", "side", "quantity", "current_weight", "target_weight", "trade_value_delta_usd"]).to_csv(
        preview / "orders_preview.csv",
        index=False,
    )
    pd.DataFrame(
        [
            {"ticker": target_ticker, "projected_weight": target_weight},
            {"ticker": "CASH", "projected_weight": target_cash},
        ]
    ).to_csv(preview / "projected_positions_after_orders.csv", index=False)

    journal = root / "broker_trade_journal" / portfolio
    journal.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "entry_date": "2025-12-31",
                "entry_signal_date": "2025-12-30",
                "entry_reason": "target_rebalance",
                "entry_sleeve": "future_winner",
                "quantity_open": 100,
                "entry_price": 90,
            }
        ]
    ).to_csv(journal / "open_positions.csv", index=False)


def _write_price_cache(root: Path, ticker: str, close: float) -> None:
    cache = root / "cache_prices"
    cache.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-01-01", "2026-01-31")
    frame = pd.DataFrame(
        {
            "Open": [close - 1.0] * len(dates),
            "Close": [close] * len(dates),
            "Adj Close": [close] * len(dates),
            "Volume": [1_000_000] * len(dates),
        },
        index=dates,
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def test_user_portfolio_reports_separate_recommendations_from_current_holdings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "Name": "Alpha Inc",
                    "sector": "Technology",
                    "weight": 0.60,
                    "reference_price": 108,
                    "portfolio_sleeve_label": "future_winner",
                    "portfolio_selection_path": "monster_early",
                    "score_total": 4.2,
                }
            ]
        ).to_csv(root / "portfolio_latest.csv", index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "BBB",
                    "Name": "Beta Inc",
                    "sector": "Industrials",
                    "weight": 0.50,
                    "reference_price": 50,
                    "concentrated_selection_source": "leader_rotation",
                    "concentrated_score": 7.0,
                }
            ]
        ).to_csv(root / "concentrated_portfolio_latest.csv", index=False)
        _write_portfolio_fixture(root, "main")
        _write_portfolio_fixture(root, "concentrated")
        _write_price_cache(root, "AAA", 110.0)
        _write_price_cache(root, "BBB", 55.0)

        out = root / "user_portfolio_reports"
        payload = build_reports(Namespace(latest_run=str(root), output_dir=str(out), price_cache=str(root / "cache_prices"), as_of_date=""))
        assert payload["status"] == "completed"
        assert payload["as_of_date"] == "2026-01-31"

        rec = pd.read_csv(out / "main" / "recommendation_latest.csv")
        assert {
            "ticker",
            "recommendation_date",
            "recommended_next_review_date",
            "recommended_weight",
            "current_account_weight",
            "projected_account_weight_after_orders",
            "trade_action_from_current",
            "target_value_per_100k_usd",
            "estimated_shares_per_100k",
            "buy_logic",
            "reference_price_date",
            "reference_price_source",
        } <= set(rec.columns)
        assert rec.iloc[0]["ticker"] == "AAA"
        assert rec.iloc[0]["reference_price"] == 110.0
        assert rec.iloc[0]["reference_price_source"] == "price_cache_latest_close"
        assert rec.iloc[0]["estimated_shares_per_100k"] == 545
        assert round(float(rec.iloc[0]["current_account_weight"]), 4) == 0.09
        cash_rec = rec[rec["ticker"].eq("CASH")].iloc[0]
        assert cash_rec["suggested_action"] == "RESERVE_CASH"
        assert round(float(cash_rec["recommended_weight"]), 4) == 0.4

        current = pd.read_csv(out / "main" / "current_operating_holdings_latest.csv")
        assert {
            "entry_date",
            "avg_entry_price",
            "return_since_entry_pct",
            "current_weight",
            "recommendation_date",
            "current_account_last_trade_date",
            "current_account_stale_days",
            "pending_order_count_to_recommendation",
            "recommended_target_weight",
            "projected_weight_after_recommendation_orders",
            "recommended_trade_action",
        } <= set(current.columns)
        aaa = current[current["ticker"].eq("AAA")].iloc[0]
        assert aaa["entry_date"] == "2025-12-31"
        assert round(float(aaa["return_since_entry_pct"]), 4) == 0.2
        assert round(float(aaa["recommended_target_weight"]), 4) == 0.6
        assert "CASH" in set(current["ticker"])
        cash_current = current[current["ticker"].eq("CASH")].iloc[0]
        assert round(float(cash_current["recommended_target_weight"]), 4) == 0.4

        scorecard = pd.read_csv(out / "main" / "performance_scorecard.csv")
        assert {"1M", "FULL"} <= set(scorecard["horizon"])
        assert (out / "main" / "recommendation_weights_pie.svg").exists()
        assert (out / "main" / "current_weights_bar.svg").exists()
        assert (out / "main_recommendation_latest.csv").exists()
        assert (out / "main_current_operating_holdings_latest.csv").exists()
        assert (out / "concentrated_recommendation_latest.csv").exists()
        assert (out / "concentrated_current_operating_holdings_latest.csv").exists()
        assert (out / "index.md").exists()


if __name__ == "__main__":
    test_user_portfolio_reports_separate_recommendations_from_current_holdings()
    print("user_portfolio_reports_smoke: PASS")
