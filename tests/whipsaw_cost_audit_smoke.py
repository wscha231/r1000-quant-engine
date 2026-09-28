#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_whipsaw_cost_audit import run, whipsaw_events  # noqa: E402


def test_whipsaw_event_math() -> None:
    trades = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "side": "BUY",
                "quantity": 10,
                "fill_price": 80.0,
                "fee_usd": 2.0,
                "date": "2026-01-01",
                "signal_date": "2025-12-31",
                "reason": "target_rebalance",
            },
            {
                "ticker": "AAA",
                "side": "SELL",
                "quantity": 10,
                "fill_price": 100.0,
                "fee_usd": 2.5,
                "date": "2026-02-01",
                "signal_date": "2026-01-31",
                "reason": "target_rebalance",
            },
            {
                "ticker": "AAA",
                "side": "BUY",
                "quantity": 6,
                "fill_price": 150.0,
                "fee_usd": 2.25,
                "date": "2026-03-01",
                "signal_date": "2026-02-28",
                "reason": "target_rebalance",
            },
            {
                "ticker": "BBB",
                "side": "SELL",
                "quantity": 5,
                "fill_price": 200.0,
                "fee_usd": 2.5,
                "date": "2026-02-01",
                "signal_date": "2026-01-31",
                "reason": "target_rebalance",
            },
            {
                "ticker": "BBB",
                "side": "BUY",
                "quantity": 5,
                "fill_price": 180.0,
                "fee_usd": 2.25,
                "date": "2026-02-15",
                "signal_date": "2026-02-14",
                "reason": "target_rebalance",
            },
        ]
    )
    events = whipsaw_events(trades, max_rebuy_days=90)
    assert len(events) == 2
    aaa = events[events["ticker"].eq("AAA")].iloc[0]
    assert aaa["matched_quantity"] == 6
    assert round(float(aaa["price_return_while_out"]), 6) == 0.5
    assert round(float(aaa["missed_reentry_cost_usd"]), 6) == 300.0
    bbb = events[events["ticker"].eq("BBB")].iloc[0]
    assert round(float(bbb["avoided_loss_usd"]), 6) == 100.0
    assert bool(bbb["whipsaw_positive"]) is False


def test_whipsaw_audit_writes_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        broker = latest / "broker_replay" / "concentrated"
        broker.mkdir(parents=True)
        pd.DataFrame(
            [
                {"ticker": "AAA", "side": "SELL", "quantity": 10, "fill_price": 100.0, "fee_usd": 2.5, "date": "2026-02-01", "signal_date": "2026-01-31", "reason": "target_rebalance"},
                {"ticker": "AAA", "side": "BUY", "quantity": 10, "fill_price": 130.0, "fee_usd": 3.25, "date": "2026-03-01", "signal_date": "2026-02-28", "reason": "target_rebalance"},
            ]
        ).to_csv(broker / "trades.csv", index=False)
        (broker / "metrics.json").write_text(
            json.dumps({"metric_mode": "broker_ledger_next_close", "ending_capital_usd": 10000.0, "cagr": 0.4, "max_dd": -0.2}),
            encoding="utf-8",
        )
        out = root / "audit"
        payload = run(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "trades": "",
                    "portfolio": "concentrated",
                    "output_dir": str(out),
                    "max_rebuy_days": 90,
                },
            )()
        )
        assert payload["event_count"] == 1
        assert payload["positive_whipsaw_count"] == 1
        assert round(float(payload["total_missed_reentry_cost_usd"]), 6) == 300.0
        assert (out / "whipsaw_events.csv").exists()
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_whipsaw_event_math()
    test_whipsaw_audit_writes_outputs()
    print("whipsaw_cost_audit_smoke: PASS")
