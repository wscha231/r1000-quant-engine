#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_shakeout_guard_applied_screen import screen_portfolio, target_book_path  # noqa: E402


def _candidate_row(ticker: str, *, score_level: float, leader: bool) -> dict[str, object]:
    return {
        "rebalance_date": "2021-06-30",
        "ticker": ticker,
        "sector": "Technology",
        "industry_group": "Semiconductors" if leader else "Software",
        "market_leader_lane_score": score_level,
        "quality_compounder_lane_score": 0.0,
        "emerging_tenbagger_lane_score": 0.0,
        "top7_manager_discovery_lane_score": 0.0,
        "cyclical_recovery_lane_score": 0.0,
        "crisis_beneficiary_lane_score": 0.0,
        "rs_spy_1w": 0.02 if leader else -0.01,
        "rs_qqq_1w": 0.01 if leader else -0.01,
        "rs_spy_1m": -0.01 if leader else -0.02,
        "rs_qqq_1m": -0.02 if leader else -0.02,
        "rs_spy_3m": 0.05 if leader else -0.03,
        "rs_qqq_3m": 0.04 if leader else -0.03,
        "rs_spy_6m": 0.12 if leader else -0.05,
        "rs_qqq_6m": 0.10 if leader else -0.05,
        "rs_benchmark_1w": 0.01 if leader else -0.01,
        "rs_benchmark_1m": -0.02 if leader else -0.02,
        "rs_benchmark_3m": 0.04 if leader else -0.03,
        "rs_benchmark_6m": 0.10 if leader else -0.05,
        "rs_semis_3m": 0.06 if leader else -0.02,
        "industry_group_strength_score": 1.0 if leader else -1.0,
        "industry_within_leader_rank": 1.0 if leader else -1.0,
        "oneil_leadership_score": 1.0 if leader else -1.0,
        "sub_industry_rs_score": 1.0 if leader else -1.0,
        "industry_leader_gap": 1.0 if leader else -1.0,
        "sec_form4_cluster_buy_score": 0.8 if leader else 0.0,
        "sec_13f_smart_money_score": 0.7 if leader else 0.0,
        "etf_holdings_score_shadow": 0.6 if leader else 0.0,
        "price_above_ma200": 1.0,
        "price_above_ma50": 1.0,
        "systemic_crisis_score": 0.0,
        "macro_risk_off_score": 0.0,
    }


def test_screen_counts_only_actual_shakeout_suppression() -> None:
    lead = _candidate_row("LEAD", score_level=0.1, leader=True)
    # Keep PIT evidence coverage present for confidence, but do not give the
    # incumbent a positive evidence score boost. That lets peer-band TRIM fire.
    lead["sec_form4_cluster_buy_score"] = 0.0
    lead["sec_13f_smart_money_score"] = 0.0
    lead["etf_holdings_score_shadow"] = 0.0
    peers: list[dict[str, object]] = []
    for ticker in ("PEER1", "PEER2", "PEER3"):
        peer = _candidate_row(ticker, score_level=100.0, leader=False)
        peer.update(
            {
                "rs_spy_1m": 0.20,
                "rs_qqq_1m": 0.20,
                "rs_spy_3m": 0.30,
                "rs_qqq_3m": 0.30,
                "rs_spy_6m": 0.50,
                "rs_qqq_6m": 0.50,
                "rs_benchmark_1w": 10.0,
                "rs_benchmark_3m": 10.0,
                "rs_benchmark_6m": 10.0,
                "rs_semis_1m": 10.0,
                "rs_semis_3m": 10.0,
                "relative_strength_composite": 999.0,
                "portfolio_future_winner_engine_score": 999.0,
                "dollar_vol_20d": 10_000_000_000,
                "market_cap_live": 1_000_000_000_000,
            }
        )
        peers.append(peer)
    candidates = pd.DataFrame(
        [
            lead,
            *peers,
        ]
    )
    target_book = pd.DataFrame(
        [
            {"rebalance_date": "2021-05-31", "ticker": "LEAD", "weight": 1.0},
            {"rebalance_date": "2021-06-30", "ticker": "LEAD", "weight": 1.0},
        ]
    )
    target_book["rebalance_date"] = pd.to_datetime(target_book["rebalance_date"]).dt.normalize()

    rows, summary = screen_portfolio(candidates, target_book, portfolio="main")

    assert summary["status"] == "screen_passed"
    assert summary["prior_holding_evaluated_rows"] == 1
    assert summary["suppressed_rows"] == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "LEAD"
    assert row["baseline_state"] == "TRIM"
    assert row["shakeout_state"] == "HOLD"
    assert str(row["shakeout_reason"]).startswith("shakeout_guard_prod_suppressed_trim:")


def test_screen_blocks_missing_books_without_false_positive() -> None:
    rows, summary = screen_portfolio(pd.DataFrame(), pd.DataFrame(), portfolio="concentrated")
    assert rows == []
    assert summary["status"] == "blocked"
    assert summary["suppressed_rows"] == 0


def test_target_book_path_falls_back_to_alphaops_official_book() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        alphaops = root / "alphaops_vnext"
        alphaops.mkdir(parents=True)
        expected = alphaops / "official_main_target_book.csv"
        expected.write_text("rebalance_date,ticker,weight\n2021-06-30,AAA,1.0\n", encoding="utf-8")
        assert target_book_path(root, "main") == expected


if __name__ == "__main__":
    test_screen_counts_only_actual_shakeout_suppression()
    test_screen_blocks_missing_books_without_false_positive()
    test_target_book_path_falls_back_to_alphaops_official_book()
    print("shakeout_guard_applied_screen_smoke passed")
