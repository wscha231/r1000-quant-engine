#!/usr/bin/env python3
"""Synthetic checks for the Run287 review-only dual-tempo audit."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_dual_tempo_policy as dual  # noqa: E402


def quality_row(ticker: str, complete: bool = True) -> dict[str, object]:
    return {
        "ticker": ticker,
        "candidate_status": "REVIEW_CANDIDATE_COMPLETE" if complete else "NOT_CURRENT_REVIEW_CANDIDATE",
        "exact_debt_component_coverage": 1.0 if complete else 0.6667,
        "core_quality_coverage": 0.80 if complete else 0.40,
        "economic_durability_score": 0.40 if complete else -0.10,
        "balance_resilience_score": 0.30 if complete else -0.20,
        "market_confirmation_score_clean": 0.30,
        "pit_future_row": False,
        "future_fundamental_row": False,
        "future_feature_row": False,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-dual-tempo-") as raw:
        root = Path(raw)
        risk_path = root / "risk.csv"
        quality_path = root / "quality.csv"
        current_path = root / "current.parquet"
        regime_path = root / "regime.json"
        latest_path = root / "latest_regime.txt"
        breaks_path = root / "breaks.csv"
        output = root / "out"
        pd.DataFrame([
            {"as_of_date": "2026-07-16", "available_from": "2026-07-17T04:15:00Z", "portfolio_kind": "main", "ticker": "AAA", "current_weight": 0.25, "risk_state": "NORMAL"},
            {"as_of_date": "2026-07-16", "available_from": "2026-07-17T04:15:00Z", "portfolio_kind": "main", "ticker": "BBB", "current_weight": 0.25, "risk_state": "WATCH"},
            {"as_of_date": "2026-07-16", "available_from": "2026-07-17T04:15:00Z", "portfolio_kind": "concentrated", "ticker": "CCC", "current_weight": 0.50, "risk_state": "ALERT"},
            {"as_of_date": "2026-07-16", "available_from": "2026-07-17T04:15:00Z", "portfolio_kind": "concentrated", "ticker": "DDD", "current_weight": 0.50, "risk_state": "ALERT"},
        ]).to_csv(risk_path, index=False)
        pd.DataFrame([
            quality_row("AAA"), quality_row("BBB"), quality_row("CCC"), quality_row("DDD"), quality_row("EEE")
        ]).to_csv(quality_path, index=False)
        rows = []
        for portfolio in ("main", "concentrated"):
            for ticker, selected, rank in [("AAA", False, 10), ("BBB", False, 20), ("CCC", False, 30), ("DDD", False, 40), ("EEE", True, 1)]:
                rows.append({
                    "decision_date": "2026-07-16", "portfolio_kind": portfolio,
                    "scenario": "strict_registered_current", "ticker": ticker,
                    "selector_selected": selected, "final_rank": rank,
                })
        pd.DataFrame(rows).to_parquet(current_path, index=False)
        regime_path.write_text(json.dumps({"current_state": {"crisis_state": "GREEN", "date": "2026-07-16"}}), encoding="utf-8")
        latest_path.write_text(
            "r1000 Regime Snapshot — 2026-07-16\nSPY > 200MA: True\nVIX level: 16.0\nRegime label: normal\n",
            encoding="utf-8",
        )
        pd.DataFrame([{
            "ticker": "DDD",
            "break_status": "CONFIRMED_EXACT_ACCEPTED_BREAK",
            "available_from": "2026-07-17T03:00:00Z",
        }]).to_csv(breaks_path, index=False)
        args = argparse.Namespace(
            contract=str(ROOT / "docs" / "run287_dual_tempo_policy_contract_v1.json"),
            risk_watch=str(risk_path), quality_universe=str(quality_path),
            current_status=str(current_path), regime_manifest=str(regime_path),
            latest_regime_text=str(latest_path), factor_summary="", factor_residuals="",
            fundamental_breaks=str(breaks_path), output_dir=str(output),
        )
        result = dual.build(args)
        detail = pd.read_csv(output / "security_tempo_state.csv").set_index("ticker")
        assert detail.loc["AAA", "tempo_state"] == "COMPOUND_HOLD"
        assert detail.loc["BBB", "tempo_state"] == "WATCH"
        assert detail.loc["CCC", "tempo_state"] == "DEFEND"
        assert "no_exact_fundamental_break" in detail.loc["CCC", "reason_codes"]
        assert detail.loc["DDD", "tempo_state"] == "ROTATE"
        assert not bool(detail["portfolio_action_authorized"].any())
        assert not bool(detail["orders_generated"].any())
        portfolios = pd.read_csv(output / "portfolio_tempo_state.csv").set_index("portfolio_kind")
        assert portfolios.loc["concentrated", "portfolio_tempo_state"] == "ROTATE"
        assert result["rotate_count"] == 1
        assert result["status"] == dual.READY_STATUS
        assert result["target_books_mutated"] is False
        assert result["cash_policy_mutated"] is False

        same = dual.build(args)
        assert same["history_row_count"] == 4

    print("run287_dual_tempo_policy_smoke: PASS")


if __name__ == "__main__":
    main()
