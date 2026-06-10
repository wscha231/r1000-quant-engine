#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_monster_recommendation_bridge import run


class Args:
    pass


def _args(root: Path) -> Args:
    args = Args()
    args.latest_run = str(root)
    args.output_dir = str(root / "monster_recommendations")
    args.max_candidates = 5
    return args


def test_monster_recommendations_attach_to_main_and_concentrated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pd.DataFrame([{"ticker": "AAA", "target_weight": 0.10}, {"ticker": "STALE", "target_weight": 0.08}]).to_csv(
            root / "portfolio_latest.csv",
            index=False,
        )
        pd.DataFrame([{"ticker": "CCC", "target_weight": 0.25}]).to_csv(root / "concentrated_portfolio_latest.csv", index=False)
        pd.DataFrame(
            [
                {"ticker": "MISS", "score": 9.0, "portfolio_monster_early_score": 0.8},
                {"ticker": "CHAL", "score": 8.0, "h6_dynamic_leader_score": 0.7},
            ]
        ).to_csv(root / "scored_latest.csv", index=False)
        life = root / "winner_lifecycle"
        life.mkdir()
        pd.DataFrame([{"ticker": "MISS", "missed_winner_score": 1.5, "diagnosis": "strong_3m_momentum"}]).to_csv(
            life / "missed_winner_report.csv",
            index=False,
        )
        pd.DataFrame([{"ticker": "STALE", "stale_winner_score": 1.0, "diagnosis": "under_benchmark_3m"}]).to_csv(
            life / "stale_winner_report.csv",
            index=False,
        )
        pd.DataFrame([{"held_ticker": "AAA", "challenger_ticker": "CHAL", "rotation_score": 0.9}]).to_csv(
            life / "leadership_rotation_report.csv",
            index=False,
        )
        monster = root / "monster_lifecycle_review_main"
        monster.mkdir()
        pd.DataFrame([{"rebalance_date": "2026-01-31", "ticker": "AAA", "stage": "winner", "weight": 0.16}]).to_csv(
            monster / "holdings.csv",
            index=False,
        )

        payload = run(_args(root))
        assert payload["status"] == "completed"
        unified = pd.read_csv(root / "monster_recommendations" / "unified_recommendations.csv")
        assert {"main", "concentrated"}.issubset(set(unified["portfolio"]))
        stale = unified[unified["ticker"] == "STALE"].iloc[0]
        assert stale["monster_recommendation"] == "review_trim_or_replace"
        assert "MISS" in set(unified["ticker"])
        assert "CHAL" in set(unified["ticker"])


def main() -> int:
    test_monster_recommendations_attach_to_main_and_concentrated()
    print("monster_recommendation_bridge_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
