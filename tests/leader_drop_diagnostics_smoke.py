#!/usr/bin/env python3
"""Smoke test for unified leader-drop diagnostics."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_leader_drop_diagnostics import run  # noqa: E402


def test_leader_drop_diagnostics_tracks_prefilter_and_order_feasibility() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "ticker": "DROP",
                    "Name": "Dropped Leader",
                    "universe_source": "theme_overlay",
                    "in_latest_pre_filter": True,
                    "in_latest_scoring_universe": False,
                    "failed_dd_1y": True,
                    "drop_reason": "failed_dd_1y",
                },
                {
                    "ticker": "HOLD",
                    "Name": "Held Leader",
                    "universe_source": "r1000",
                    "in_latest_pre_filter": True,
                    "in_latest_scoring_universe": True,
                },
            ]
        ).to_csv(reports / "leader_drop_diagnostics_latest.csv", index=False)
        pd.DataFrame(
            [
                {
                    "ticker": "HOLD",
                    "Name": "Held Leader",
                    "sector": "Tech",
                    "score_total": 5.0,
                    "portfolio_future_winner_engine_score": 0.8,
                    "portfolio_monster_early_score": 0.7,
                    "period_forward_return": 0.30,
                },
                {
                    "ticker": "MISS",
                    "Name": "Missed Leader",
                    "sector": "Tech",
                    "score_total": 4.5,
                    "portfolio_future_winner_engine_score": 0.9,
                    "portfolio_monster_early_score": 0.75,
                    "period_forward_return": 0.40,
                },
            ]
        ).to_csv(latest / "scored_latest.csv", index=False)
        pd.DataFrame([{"ticker": "HOLD", "weight": 0.30}]).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame([{"ticker": "CONC", "weight": 0.50}]).to_csv(latest / "concentrated_portfolio_latest.csv", index=False)
        for portfolio in ["main", "concentrated"]:
            out = latest / "account_ledger_preview" / portfolio
            out.mkdir(parents=True)
            pd.DataFrame([{"ticker": "HOLD" if portfolio == "main" else "CONC", "target_weight": 0.30}]).to_csv(
                out / "target_weights.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    {
                        "ticker": "HOLD" if portfolio == "main" else "CONC",
                        "side": "BUY",
                        "quantity": 10,
                        "status": "ready",
                    }
                ]
            ).to_csv(out / "orders_preview.csv", index=False)
            pd.DataFrame(columns=["ticker", "side", "quantity", "status"]).to_csv(out / "order_deltas_review.csv", index=False)
        payload = run(latest, root / "out", watchlist="DROP,MISS,ABSENT")
        assert payload["status"] == "completed", payload
        assert payload["rows"] >= 4, payload
        detail = pd.read_csv(root / "out" / "leader_drop_by_gate.csv")
        drop = detail[detail["ticker"].eq("DROP")].iloc[0]
        assert drop["drop_reason"] == "filtered_before_scoring:failed_dd_1y"
        hold = detail[detail["ticker"].eq("HOLD")].iloc[0]
        assert hold["drop_reason"] == "selected_target_actionable_order"
        absent = detail[detail["ticker"].eq("ABSENT")].iloc[0]
        assert absent["drop_reason"] == "not_in_latest_universe_or_missing_data"
        missed = pd.read_csv(root / "out" / "missed_leader_candidates.csv")
        assert "MISS" in set(missed["ticker"])


def main() -> int:
    test_leader_drop_diagnostics_tracks_prefilter_and_order_feasibility()
    print("leader_drop_diagnostics_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
