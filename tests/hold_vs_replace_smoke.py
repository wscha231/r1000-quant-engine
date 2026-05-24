#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_hold_vs_replace import (  # noqa: E402
    classify_position_state,
    evaluate_portfolio_holds_vs_replaces,
    select_replacement_candidate,
)


def test_hold_vs_replace_prioritizes_broken_heavy_and_pit_safe_candidates() -> None:
    assert classify_position_state("WIN", 120.0, 100.0, rs_rank=80).state == "winner_intact"
    assert classify_position_state("BROKEN", 80.0, 100.0, rs_rank=20).state == "broken"
    assert classify_position_state("MISSING", 80.0, float("nan")).state == "review_required"

    candidates = pd.DataFrame(
        [
            {"ticker": "FUTURE", "score_z": 2.0, "sector": "tech", "quality_growth_score": 0.9, "available_from_ts": "2026-01-10"},
            {"ticker": "EARLY", "score_z": 1.8, "sector": "health", "quality_growth_score": 0.9, "available_from_ts": "2026-01-02"},
        ]
    )
    best = select_replacement_candidate(
        held_score_z=0.0,
        candidates=candidates,
        held_sector="tech",
        crisis_zone="normal",
        as_of_date=pd.Timestamp("2026-01-05"),
        threshold_sigma=0.75,
    )
    assert best is not None
    assert best["ticker"] == "EARLY"

    holdings = pd.DataFrame(
        [
            {"ticker": "SMALL_BROKEN", "current_price": 80.0, "entry_price": 100.0, "weight": 0.10, "score_z": 0.0, "sector": "tech"},
            {"ticker": "BIG_BROKEN", "current_price": 70.0, "entry_price": 100.0, "weight": 0.40, "score_z": 0.0, "sector": "tech"},
            {"ticker": "WINNER", "current_price": 130.0, "entry_price": 100.0, "weight": 0.50, "score_z": 1.0, "sector": "industrial", "rs_rank": 85},
        ]
    )
    decisions = evaluate_portfolio_holds_vs_replaces(
        holdings,
        candidates,
        crisis_zone="normal",
        max_replacements=1,
        as_of_date=pd.Timestamp("2026-01-05"),
        sector_policy="allow",
    )
    replaced = decisions[decisions["action"].eq("replace")]
    assert len(replaced) == 1
    assert replaced.iloc[0]["ticker"] == "BIG_BROKEN"
    assert "WINNER" in set(decisions[decisions["action"].eq("hold")]["ticker"])


if __name__ == "__main__":
    test_hold_vs_replace_prioritizes_broken_heavy_and_pit_safe_candidates()
    print("hold_vs_replace_smoke: PASS")
