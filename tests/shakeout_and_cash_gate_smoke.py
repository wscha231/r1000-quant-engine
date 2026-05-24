#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_hold_vs_replace import evaluate_portfolio_holds_vs_replaces  # noqa: E402
from tools.build_crisis_governed_target_books import build_governed_book  # noqa: E402


def test_shakeout_guard_blocks_replace_and_cash() -> None:
    holdings = pd.DataFrame(
        [
            {
                "ticker": "LEADER",
                "current_price": 82.0,
                "entry_price": 100.0,
                "weight": 0.40,
                "score_z": 0.5,
                "sector": "semis",
                "rs_rank": 70,
                "sector_rs_rank": 90,
                "theme_rs_rank": 88,
                "ma200": 78.0,
                "evidence_score": 0.75,
                "negative_evidence_score": 0.05,
                "liquidity_confirmation_score": 0.10,
                "market_trend_damage_score": 0.10,
            }
        ]
    )
    candidates = pd.DataFrame(
        [
            {
                "ticker": "REPLACER",
                "score_z": 2.5,
                "sector": "software",
                "quality_growth_score": 0.9,
                "candidate_source": "future_winner",
            }
        ]
    )
    decisions = evaluate_portfolio_holds_vs_replaces(
        holdings,
        candidates,
        crisis_zone="normal",
        sector_policy="allow",
    )
    row = decisions.iloc[0]
    assert row["shakeout_guard"] == "shakeout_probable"
    assert row["action"] == "trim"
    assert float(row["trim_pct"]) <= 0.25
    assert pd.isna(row["candidate_ticker"]) or not str(row["candidate_ticker"]).strip()

    systemic = holdings.copy()
    systemic["liquidity_confirmation_score"] = 0.80
    systemic["market_trend_damage_score"] = 0.80
    decisions = evaluate_portfolio_holds_vs_replaces(
        systemic.drop(columns=["evidence_score"]),
        pd.DataFrame(),
        crisis_zone="crisis",
        concentrated_floor=0.0,
        sector_policy="allow",
    )
    row = decisions.iloc[0]
    assert row["shakeout_guard"] == "systemic_crisis_confirmed"
    assert row["action"] == "cash"


def test_crisis_target_book_cash_hard_gate_blocks_vix_only_cash_raise() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.70},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.25},
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.05},
            ]
        ).to_csv(target, index=False)

        dates = pd.bdate_range("2026-01-02", periods=10)
        features = pd.DataFrame(index=dates)
        features["crisis_score"] = 0.85
        features["liquidity_confirmation_score"] = 0.05
        features["market_trend_damage_score"] = 0.10
        features["credit_stress_score"] = 0.00
        features["shakeout_guard_score"] = 0.75
        feature_path = root / "features.parquet"
        features.to_parquet(feature_path)

        _, audit, summary = build_governed_book(
            target_book=target,
            crisis_features=feature_path,
            portfolio_kind="main",
            mode="conservative",
            cash_hard_gate=True,
        )
        assert summary["status"] == "completed"
        assert audit["cash_hard_gate_allowed"].eq(False).any()
        assert audit["cash_weight"].max() <= 0.10

        features["liquidity_confirmation_score"] = 0.80
        features["market_trend_damage_score"] = 0.80
        features["shakeout_guard_score"] = 0.00
        features.to_parquet(feature_path)
        _, audit, _ = build_governed_book(
            target_book=target,
            crisis_features=feature_path,
            portfolio_kind="main",
            mode="conservative",
            cash_hard_gate=True,
        )
        assert audit["cash_hard_gate_allowed"].eq(True).all()
        assert audit["cash_weight"].max() >= 0.25


if __name__ == "__main__":
    test_shakeout_guard_blocks_replace_and_cash()
    test_crisis_target_book_cash_hard_gate_blocks_vix_only_cash_raise()
    print("shakeout_and_cash_gate_smoke: PASS")
