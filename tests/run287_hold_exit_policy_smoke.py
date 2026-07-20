#!/usr/bin/env python3
"""Smoke tests for the canonical Run287 P5 hold and sell-taxonomy policy."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.run287_hold_exit_policy import (  # noqa: E402
    LeadershipPersistencePolicy,
    SELL_TAXONOMY,
    build_leadership_persistence_book,
    classify_execution_sell,
)
from tools.security_lifecycle import REQUIRED_COLUMNS  # noqa: E402


def candidate_row(day: str, ticker: str, score: float, rs: float, sector: str) -> dict[str, object]:
    return {
        "rebalance_date": day,
        "ticker": ticker,
        "alphaops_vnext_score": score,
        "rs_benchmark_1w": 0.05,
        "rs_benchmark_3m": rs,
        "price_above_ma50": 1.0,
        "price_above_ma200": 1.0,
        "leader_tier": "DUAL_LEADER",
        "rs_sector_3m": 0.10,
        "industry_group_strength_score": 0.20,
        "portfolio_risk_entry_block_score": 0.10,
        "portfolio_stale_mega_leader_score": 0.0,
        "emerging_tenbagger_hard_reject_reason": "",
        "top7_standalone_blocked": False,
        "pit_evidence_blocked": False,
        "primary_lane": "MARKET_LEADER",
        "sector": sector,
        "industry_group": sector + " Group",
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lifecycle = root / "lifecycle.csv"
        pd.DataFrame(columns=sorted(REQUIRED_COLUMNS)).to_csv(lifecycle, index=False)
        control = pd.DataFrame(
            [
                {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.40, "sector": "Tech", "industry_group": "Tech Group"},
                {"rebalance_date": "2024-01-31", "ticker": "BBB", "weight": 0.40, "sector": "Health", "industry_group": "Health Group"},
                {"rebalance_date": "2024-01-31", "ticker": "CASH", "weight": 0.20, "sector": "", "industry_group": ""},
                {"rebalance_date": "2024-02-29", "ticker": "CCC", "weight": 0.40, "sector": "Tech", "industry_group": "Tech Group"},
                {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 0.40, "sector": "Health", "industry_group": "Health Group"},
                {"rebalance_date": "2024-02-29", "ticker": "CASH", "weight": 0.20, "sector": "", "industry_group": ""},
            ]
        )
        rows = []
        for day in ("2024-01-31", "2024-02-29"):
            rows.extend(
                [
                    candidate_row(day, "AAA", 1.00, 0.30, "Tech"),
                    candidate_row(day, "BBB", 0.50, 0.05, "Health"),
                    candidate_row(day, "CCC", 1.10, 0.20, "Tech"),
                ]
            )
            for index in range(7):
                rows.append(candidate_row(day, f"X{index}", 0.20 + index * 0.01, -0.20 + index * 0.02, "Other"))
        treatment, decisions, exits, audit = build_leadership_persistence_book(
            control,
            pd.DataFrame(rows),
            portfolio="main",
            lifecycle_path=lifecycle,
            policy=LeadershipPersistencePolicy(),
        )
        assert audit["status"] == "APPLIED", audit
        assert audit["applied_retention_count"] == 1
        feb = treatment[pd.to_datetime(treatment["rebalance_date"]).eq(pd.Timestamp("2024-02-29"))]
        assert "AAA" in set(feb["ticker"])
        assert "CCC" not in set(feb["ticker"])
        assert abs(float(feb["weight"].sum()) - 1.0) < 1e-12
        assert abs(float(feb.loc[feb["ticker"].eq("CASH"), "weight"].sum()) - 0.20) < 1e-12
        assert set(exits.get("sell_taxonomy", pd.Series(dtype=str))).issubset(set(SELL_TAXONOMY))
        assert decisions.iloc[0]["reason"] == "fixed_margin_not_met"

        assert classify_execution_sell(
            ticker="AAA", target_weight=0.0, target_gross_reduced=False,
            replacement_tickers={"CCC"},
        )[0] == "REPLACEMENT_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.2, target_gross_reduced=True,
        )[0] == "RISK_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.0, target_gross_reduced=False,
            lifecycle_terminal=True,
        )[0] == "LIFECYCLE_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.0, target_gross_reduced=False,
            thesis_break=True,
        )[0] == "THESIS_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.3, target_gross_reduced=False,
        )[0] == "EXECUTION_RECONCILIATION"
    print("run287_hold_exit_policy_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
