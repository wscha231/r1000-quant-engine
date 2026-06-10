#!/usr/bin/env python3
"""Smoke checks for broker-ledger round-trip trade journal."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_trade_journal import run  # noqa: E402


class Args:
    pass


def test_broker_trade_journal_pairs_round_trips_and_excludes_forward_labels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        out = root / "journal"
        (latest / "broker_replay" / "main").mkdir(parents=True)
        (latest / "broker_replay" / "concentrated").mkdir(parents=True)
        (latest / "reports").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "side": "BUY",
                    "quantity": 10,
                    "fill_price": 100.0,
                    "gross_value": 1000.0,
                    "fee_usd": 2.5,
                    "cash_delta": -1002.5,
                    "cash_after": 8997.5,
                    "shares_after": 10,
                    "date": "2026-01-05",
                    "signal_date": "2026-01-02",
                    "reason": "target_rebalance",
                    "target_weight": 0.50,
                    "fill_mode": "next_close",
                },
                {
                    "ticker": "AAA",
                    "side": "SELL",
                    "quantity": 10,
                    "fill_price": 120.0,
                    "gross_value": 1200.0,
                    "fee_usd": 3.0,
                    "cash_delta": 1197.0,
                    "cash_after": 10194.5,
                    "shares_after": 0,
                    "date": "2026-02-05",
                    "signal_date": "2026-02-02",
                    "reason": "target_exit",
                    "target_weight": "",
                    "fill_mode": "next_close",
                },
            ]
        ).to_csv(latest / "broker_replay" / "main" / "trades.csv", index=False)
        pd.DataFrame(columns=["ticker", "side"]).to_csv(latest / "broker_replay" / "concentrated" / "trades.csv", index=False)
        (latest / "broker_replay" / "main" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.2, "sharpe": 1.0, "max_dd": -0.1, "trade_count": 2}),
            encoding="utf-8",
        )
        (latest / "broker_replay" / "concentrated" / "metrics.json").write_text("{}", encoding="utf-8")
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "Name": "AAA INC",
                    "sector": "Technology",
                    "score": 5.0,
                    "r_1m": 0.99,
                    "period_forward_return": 0.99,
                    "portfolio_sleeve_label": "future_winner",
                    "regime_state": "bull",
                    "rs_acceleration_score": 0.8,
                    "explosion_entry_score": 0.4,
                }
            ]
        ).to_csv(latest / "reports" / "candidate_replay_book.csv", index=False)
        pd.DataFrame(
            [{"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.5, "raw_score": 5.0}]
        ).to_csv(latest / "reports" / "main_monthly_weights.csv", index=False)
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(
            latest / "reports" / "concentrated_strategy_holdings.csv",
            index=False,
        )
        args = Args()
        args.latest_run = str(latest)
        args.output_dir = str(out)
        payload = run(args)
        assert payload["main"]["status"] == "completed"
        rows = pd.read_csv(out / "main" / "round_trips.csv")
        assert len(rows) == 1
        assert rows.iloc[0]["entry_sleeve"] == "future_winner"
        assert rows.iloc[0]["entry_regime_state"] == "bull"
        assert rows.iloc[0]["realized_return"] > 0.18
        assert "r_1m" not in rows.columns
        assert "period_forward_return" not in rows.columns
        assert (out / "combined_round_trips.csv").exists()
        assert (out / "summary.json").exists()


def main() -> int:
    test_broker_trade_journal_pairs_round_trips_and_excludes_forward_labels()
    print("broker_trade_journal_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
