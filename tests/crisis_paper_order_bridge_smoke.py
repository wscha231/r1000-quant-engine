#!/usr/bin/env python3
"""Smoke test for crisis paper-action to order-preview bridge."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_crisis_paper_order_bridge import run  # noqa: E402
import tools.run_account_order_preview as order_preview  # noqa: E402


def fake_load_price_series(price_cache: Path, ticker: str) -> pd.DataFrame:
    closes = {"AAA": [100.0, 100.0, 100.0], "BBB": [50.0, 50.0, 50.0]}.get(str(ticker).upper(), [])
    if not closes:
        return pd.DataFrame()
    idx = pd.bdate_range(start="2026-01-02", periods=len(closes))
    return pd.DataFrame({"close": closes, "open": closes}, index=idx)


def write_portfolio_fixture(root: Path, portfolio: str) -> None:
    broker = root / "broker_replay" / portfolio
    broker.mkdir(parents=True)
    (broker / "account_state_latest.json").write_text(
        json.dumps(
            {
                "as_of_date": "2026-01-02",
                "cash_usd": 1000.0,
                "positions": [{"ticker": "AAA", "shares": 80.0, "cost_basis": 90.0}],
            }
        ),
        encoding="utf-8",
    )
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"ticker": "AAA", "target_weight": 0.30},
            {"ticker": "BBB", "target_weight": 0.60},
        ]
    ).to_csv(reports / f"operating_{portfolio}_target_book.csv", index=False)


def test_crisis_paper_order_bridge_requires_approval_and_blocks_new_buys() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        order_preview.load_price_series = fake_load_price_series
        write_portfolio_fixture(root, "main")
        write_portfolio_fixture(root, "concentrated")
        monitor = root / "daily_crisis_monitor"
        monitor.mkdir()
        (monitor / "summary.json").write_text(
            json.dumps(
                {
                    "state": "DEFENSE_REVIEW",
                    "raw_state": "DEFENSE_REVIEW",
                    "auto_trade_allowed": False,
                    "paper_actions_only": True,
                    "paper_action_candidates": [
                        {"action_type": "block_new_buys", "priority": 1, "scope": "new_positions"},
                        {"action_type": "raise_cash", "priority": 2, "target_cash_weight": 0.50},
                        {"action_type": "trim_position", "priority": 3, "ticker": "AAA", "current_weight": 0.80},
                    ],
                }
            ),
            encoding="utf-8",
        )
        out = root / "bridge"
        payload = run(Namespace(latest_run=str(root), price_cache=str(cache), output_dir=str(out), cost_bps=25.0))
        assert payload["status"] == "completed"
        assert payload["auto_trade_allowed"] is False
        assert payload["paper_only"] is True
        assert payload["approval_required"] is True
        main_orders = pd.read_csv(out / "main" / "paper_orders_preview.csv")
        assert not main_orders.empty
        assert main_orders["approval_required"].astype(bool).all()
        blocked = main_orders[main_orders["status"].astype(str).eq("blocked_new_buy_pending_approval")]
        assert "BBB" in set(blocked["ticker"].astype(str))
        derived = pd.read_csv(out / "main" / "paper_action_target_book.csv")
        assert "CASH" in set(derived["ticker"].astype(str))
        assert (out / "summary.md").exists()


if __name__ == "__main__":
    test_crisis_paper_order_bridge_requires_approval_and_blocks_new_buys()
    print("crisis_paper_order_bridge_smoke: PASS")
