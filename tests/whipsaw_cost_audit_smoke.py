#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_whipsaw_cost_audit as audit  # noqa: E402


def _trades(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    return frame


def _equity() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": pd.Timestamp("2020-01-01"), "equity_usd": 1000.0},
            {"date": pd.Timestamp("2020-01-31"), "equity_usd": 1000.0},
            {"date": pd.Timestamp("2020-05-31"), "equity_usd": 1000.0},
        ]
    )


def _sell_buy(sell_price: float, buy_price: float, buy_date: str = "2020-01-31") -> pd.DataFrame:
    return _trades(
        [
            {
                "ticker": "AAA",
                "side": "SELL",
                "quantity": 2,
                "fill_price": sell_price,
                "gross_value": sell_price * 2,
                "date": "2020-01-01",
                "reason": "target_rebalance",
            },
            {
                "ticker": "AAA",
                "side": "BUY",
                "quantity": 2,
                "fill_price": buy_price,
                "gross_value": buy_price * 2,
                "date": buy_date,
                "reason": "target_rebalance",
            },
        ]
    )


def test_sell_then_higher_rebuy_counts_one_event() -> None:
    events = audit.match_whipsaw_events(_sell_buy(100.0, 140.0), _equity(), portfolio="concentrated", lookback_months=3)

    assert len(events) == 1
    row = events.iloc[0]
    assert row["ticker"] == "AAA"
    assert abs(float(row["rebuy_premium"]) - 0.40) < 1e-12
    assert bool(row["positive_rebuy_premium"]) is True


def test_cheaper_rebuy_is_event_but_not_positive_drag() -> None:
    events = audit.match_whipsaw_events(_sell_buy(100.0, 90.0), _equity(), portfolio="concentrated", lookback_months=3)
    summary = audit.summarize(events, portfolio="concentrated", years=1.0, lookback_months=3)

    assert len(events) == 1
    assert summary["positive_premium_share"] == 0.0
    assert summary["recoverable_ceiling_full_pp"] == 0.0
    assert summary["estimated_signed_drag_pp_full"] < 0.0


def test_sell_without_rebuy_has_no_event() -> None:
    trades = _trades(
        [
            {
                "ticker": "AAA",
                "side": "SELL",
                "quantity": 2,
                "fill_price": 100.0,
                "gross_value": 200.0,
                "date": "2020-01-01",
            }
        ]
    )

    events = audit.match_whipsaw_events(trades, _equity(), portfolio="main", lookback_months=3)

    assert events.empty


def test_rebuy_after_lookback_is_ignored() -> None:
    events = audit.match_whipsaw_events(_sell_buy(100.0, 160.0, "2020-05-31"), _equity(), portfolio="main", lookback_months=3)

    assert events.empty


def test_weighted_drag_math_uses_matched_quantity_and_equity() -> None:
    events = audit.match_whipsaw_events(_sell_buy(100.0, 150.0), _equity(), portfolio="main", lookback_months=3)
    row = events.iloc[0]

    assert abs(float(row["sold_weight"]) - 0.20) < 1e-12
    assert abs(float(row["weighted_drag_return"]) - 0.10) < 1e-12


def test_verdict_thresholds() -> None:
    assert audit.verdict(5, 3.0) == "whipsaw_drag_material"
    assert audit.verdict(5, 1.0) == "whipsaw_drag_minor"
    assert audit.verdict(5, 0.99) == "insufficient_events"
    assert audit.verdict(4, 10.0) == "insufficient_events"


def test_empty_summary_is_insufficient() -> None:
    summary = audit.summarize(pd.DataFrame(), portfolio="concentrated", years=7.0, lookback_months=3)

    assert summary["whipsaw_event_count"] == 0
    assert summary["verdict"] == "insufficient_events"


if __name__ == "__main__":
    test_sell_then_higher_rebuy_counts_one_event()
    test_cheaper_rebuy_is_event_but_not_positive_drag()
    test_sell_without_rebuy_has_no_event()
    test_rebuy_after_lookback_is_ignored()
    test_weighted_drag_math_uses_matched_quantity_and_equity()
    test_verdict_thresholds()
    test_empty_summary_is_insufficient()
    print("whipsaw_cost_audit_smoke: PASS")
