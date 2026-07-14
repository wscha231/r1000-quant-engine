#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import run_run287_current_selector_no_write as selector


def test_provider_prices_are_normalized_for_pinned_policy() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["aaa", "AAA"],
            "Date": ["2026-07-10", "2026-07-13"],
            "Open": [99.0, 101.0],
            "Close": [100.0, 102.0],
            "Adj Close": [50.0, 51.0],
        }
    )
    prices = selector.normalized_provider_prices(source)
    assert set(prices) == {"AAA"}
    frame = prices["AAA"]
    assert list(frame.columns) == ["close", "open"]
    assert frame.index.max() == pd.Timestamp("2026-07-13")
    assert float(frame.loc[pd.Timestamp("2026-07-13"), "close"]) == 51.0
    assert float(frame.loc[pd.Timestamp("2026-07-13"), "open"]) == 50.5


def test_marked_weight_contract_uses_exact_close_and_cash() -> None:
    watch = pd.DataFrame(
        {
            "as_of_date": ["2026-07-13", "2026-07-13"],
            "portfolio_kind": ["main", "concentrated"],
            "ticker": ["AAA", "BBB"],
            "current_weight": [0.8, 0.7],
            "price_exact_asof": [True, True],
        }
    )
    summary = {
        "portfolio_summaries": {
            "main": {"estimated_current_equity_usd": 100.0, "cash_usd": 20.0},
            "concentrated": {
                "estimated_current_equity_usd": 100.0,
                "cash_usd": 30.0,
            },
        }
    }
    frames = selector.marked_weight_frames(
        watch, summary, pd.Timestamp("2026-07-13")
    )
    for frame in frames.values():
        assert abs(float(frame["weight"].sum()) - 1.0) <= 1e-12
        assert "CASH" in set(frame["ticker"])


def test_noop_turnover_and_cost_are_zero() -> None:
    projection = pd.DataFrame(
        {
            "portfolio_kind": ["main", "main"],
            "scenario": ["noop", "noop"],
            "ticker": ["AAA", "CASH"],
            "advisory_weight": [0.8, 0.2],
        }
    )
    prior = pd.DataFrame({"ticker": ["AAA", "CASH"], "weight": [0.8, 0.2]})
    detail, summary = selector.comparison_rows(
        projection,
        {"main": prior},
        {"main": prior},
        {"main": 100000.0},
    )
    row = summary.iloc[0]
    assert float(row["one_way_turnover_vs_marked"]) == 0.0
    assert float(row["estimated_cost_usd_25bps"]) == 0.0
    assert float(row["estimated_cost_usd_100bps"]) == 0.0
    assert bool(detail["execution_allowed"].eq(False).all())


def test_asset_cost_excludes_cash_but_turnover_includes_it() -> None:
    projection = pd.DataFrame(
        {
            "portfolio_kind": ["main", "main"],
            "scenario": ["cash_raise", "cash_raise"],
            "ticker": ["AAA", "CASH"],
            "advisory_weight": [0.6, 0.4],
        }
    )
    marked = pd.DataFrame({"ticker": ["AAA", "CASH"], "weight": [0.8, 0.2]})
    _detail, summary = selector.comparison_rows(
        projection,
        {"main": marked},
        {"main": marked},
        {"main": 100000.0},
    )
    row = summary.iloc[0]
    assert abs(float(row["one_way_turnover_vs_marked"]) - 0.2) <= 1e-12
    assert abs(float(row["asset_absolute_trade_weight"]) - 0.2) <= 1e-12
    assert abs(float(row["estimated_cost_usd_25bps"]) - 50.0) <= 1e-12


def test_holding_risk_conflicts_are_diagnostic_only() -> None:
    projection = pd.DataFrame(
        {
            "portfolio_kind": ["main", "main", "main"],
            "scenario": ["risk", "risk", "risk"],
            "ticker": ["AAA", "NEW", "CASH"],
            "advisory_weight": [0.5, 0.3, 0.2],
        }
    )
    marked = pd.DataFrame(
        {"ticker": ["AAA", "CASH"], "weight": [0.4, 0.6]}
    )
    detail, summary = selector.comparison_rows(
        projection,
        {"main": marked},
        {"main": marked},
        {"main": 100000.0},
    )
    watch = pd.DataFrame(
        {
            "portfolio_kind": ["main"],
            "ticker": ["AAA"],
            "risk_state": ["ALERT"],
            "advisory_action": ["FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW"],
            "reason_codes": ["shock"],
        }
    )
    detail, summary = selector.attach_holding_risk_diagnostics(
        detail, summary, watch
    )
    row = summary.iloc[0]
    assert int(row["incremental_buy_risk_review_conflict_count"]) == 1
    assert int(row["incremental_buy_freeze_conflict_count"]) == 1
    assert int(row["proposed_new_entry_without_risk_watch_count"]) == 1
    assert bool(row["risk_watch_promotion_allowed"]) is False
    assert bool(detail["execution_allowed"].eq(False).all())


def main() -> int:
    test_provider_prices_are_normalized_for_pinned_policy()
    test_marked_weight_contract_uses_exact_close_and_cash()
    test_noop_turnover_and_cost_are_zero()
    test_asset_cost_excludes_cash_but_turnover_includes_it()
    test_holding_risk_conflicts_are_diagnostic_only()
    print("run287_current_selector_no_write_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
