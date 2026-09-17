#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_whipsaw_pit_feature_screen import add_pit_features, run, screen_summary  # noqa: E402
from tools.run_whipsaw_cost_audit import whipsaw_events  # noqa: E402


def test_pit_join_and_predicates() -> None:
    trades = pd.DataFrame(
        [
            {"ticker": "AAA", "side": "SELL", "quantity": 10, "fill_price": 100.0, "fee_usd": 1.0, "shares_after": 0, "date": "2026-02-03", "signal_date": "2026-01-31", "reason": "target_rebalance"},
            {"ticker": "AAA", "side": "BUY", "quantity": 10, "fill_price": 140.0, "fee_usd": 1.4, "shares_after": 10, "date": "2026-03-03", "signal_date": "2026-02-28", "reason": "target_rebalance"},
            {"ticker": "BBB", "side": "SELL", "quantity": 5, "fill_price": 200.0, "fee_usd": 1.0, "shares_after": 3, "date": "2026-02-03", "signal_date": "2026-01-31", "reason": "target_rebalance"},
            {"ticker": "BBB", "side": "BUY", "quantity": 4, "fill_price": 180.0, "fee_usd": 1.0, "shares_after": 7, "date": "2026-03-03", "signal_date": "2026-02-28", "reason": "target_rebalance"},
        ]
    )
    book = pd.DataFrame(
        [
            {
                "rebalance_date": "2026-01-31",
                "ticker": "AAA",
                "weight": 0.20,
                "holding_state": "HOLD",
                "hold_replace_decision": "keep_prior_holding",
                "leader_tier": "DUAL_LEADER",
                "rs_benchmark_3m": 0.10,
                "rs_benchmark_6m": 0.15,
                "price_above_ma200": 1.0,
                "actual_results_score": 0.5,
                "eps_revision_score": 0.0,
                "event_reaction_score": 0.0,
            },
            {
                "rebalance_date": "2026-01-31",
                "ticker": "BBB",
                "weight": 0.10,
                "holding_state": "HOLD",
                "hold_replace_decision": "keep_prior_holding",
                "leader_tier": "DUAL_LEADER",
                "rs_benchmark_3m": 0.10,
                "rs_benchmark_6m": 0.15,
                "price_above_ma200": 1.0,
                "actual_results_score": 0.5,
            },
        ]
    )
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"])
    events = whipsaw_events(trades, max_rebuy_days=90)
    enriched = add_pit_features(events, book)
    assert len(enriched) == 2
    aaa = enriched[enriched["ticker"].eq("AAA")].iloc[0]
    assert bool(aaa["full_exit"]) is True
    assert bool(aaa["thesis_intact_actual_results"]) is True
    assert bool(aaa["full_exit_thesis_intact_actual"]) is True
    bbb = enriched[enriched["ticker"].eq("BBB")].iloc[0]
    assert bool(bbb["full_exit"]) is False
    assert bool(bbb["partial_sell_thesis_intact_actual"]) is True

    summary = screen_summary(enriched, oos_start=pd.Timestamp("2026-02-01"))
    by_pred = {row["predicate"]: row for row in summary}
    assert by_pred["thesis_intact_actual_results"]["event_count"] == 2
    assert by_pred["full_exit_thesis_intact_actual"]["event_count"] == 1
    assert by_pred["partial_sell_thesis_intact_actual"]["event_count"] == 1


def test_whipsaw_pit_feature_screen_writes_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        broker = latest / "broker_replay" / "concentrated"
        reports = latest / "reports"
        broker.mkdir(parents=True)
        reports.mkdir(parents=True)
        pd.DataFrame(
            [
                {"ticker": "AAA", "side": "SELL", "quantity": 10, "fill_price": 100.0, "fee_usd": 1.0, "shares_after": 0, "date": "2026-02-03", "signal_date": "2026-01-31", "reason": "target_rebalance"},
                {"ticker": "AAA", "side": "BUY", "quantity": 10, "fill_price": 140.0, "fee_usd": 1.4, "shares_after": 10, "date": "2026-03-03", "signal_date": "2026-02-28", "reason": "target_rebalance"},
            ]
        ).to_csv(broker / "trades.csv", index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "AAA",
                    "weight": 0.20,
                    "holding_state": "HOLD",
                    "hold_replace_decision": "keep_prior_holding",
                    "leader_tier": "DUAL_LEADER",
                    "rs_benchmark_3m": 0.10,
                    "rs_benchmark_6m": 0.15,
                    "price_above_ma200": 1.0,
                    "actual_results_score": 0.5,
                }
            ]
        ).to_csv(reports / "operating_concentrated_target_book.csv", index=False)
        out = root / "screen"
        payload = run(
            type(
                "Args",
                (),
                {
                    "latest_run": str(latest),
                    "trades": "",
                    "target_book": "",
                    "portfolio": "concentrated",
                    "output_dir": str(out),
                    "max_rebuy_days": 90,
                    "oos_start": "2026-02-01",
                    "min_events": 1,
                    "min_oos_events": 1,
                },
            )()
        )
        assert payload["event_count"] == 1
        assert payload["pit_joined_event_count"] == 1
        assert payload["screen_pass"] is True
        assert (out / "whipsaw_pit_events.csv").exists()
        assert (out / "predicate_summary.csv").exists()
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_pit_join_and_predicates()
    test_whipsaw_pit_feature_screen_writes_outputs()
    print("whipsaw_pit_feature_screen_smoke: PASS")
