#!/usr/bin/env python3
"""Offline smoke for the scored-latest diagnostic selector diff."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_scored_latest_selector_diff import audit  # noqa: E402


def write_account(path: Path, portfolio: str, tickers: list[str]) -> None:
    payload = {
        "portfolio_kind": portfolio,
        "as_of_date": "2026-07-10",
        "positions": [{"ticker": ticker, "shares": 10} for ticker in tickers],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed(root: Path) -> tuple[Path, Path, dict[str, Path]]:
    scored = root / "scored.csv"
    risk = root / "risk.csv"
    rows = []
    for rank, ticker in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], 1):
        rows.append(
            {
                "ticker": ticker,
                "score": 7 - rank,
                "research_score_rank": rank,
                "research_eligible_after_quarantine": True,
                "technical_available_after_close": "2026-07-13",
                "score_available_from": "2026-07-14T04:00:00Z",
                "decision_feature_complete": False,
                "decision_ranking_allowed": False,
                "portfolio_candidate_gate_label": "core_strict",
            }
        )
    rows.append(
        {
            "ticker": "ZZZ",
            "score": -1,
            "research_score_rank": None,
            "research_eligible_after_quarantine": False,
            "technical_available_after_close": "2026-07-13",
            "score_available_from": "2026-07-14T04:00:00Z",
            "decision_feature_complete": False,
            "decision_ranking_allowed": False,
            "portfolio_candidate_gate_label": "rejected",
        }
    )
    pd.DataFrame(rows).to_csv(scored, index=False)

    risk_rows = []
    holdings = {"main": ["CCC", "ZZZ"], "concentrated": ["BBB"]}
    for portfolio, tickers in holdings.items():
        for ticker in tickers:
            risk_rows.append(
                {
                    "as_of_date": "2026-07-13",
                    "portfolio_kind": portfolio,
                    "ticker": ticker,
                    "shares": 10,
                    "current_weight": 0.3,
                    "risk_state": "ALERT" if ticker == "ZZZ" else "NORMAL",
                    "advisory_action": "NO_CHANGE",
                    "reason_codes": "fixture",
                    "portfolio_return_contribution_1d": -0.01,
                }
            )
    pd.DataFrame(risk_rows).to_csv(risk, index=False)
    accounts = {}
    for portfolio, tickers in holdings.items():
        path = root / f"{portfolio}.json"
        write_account(path, portfolio, tickers)
        accounts[portfolio] = path
    return scored, risk, accounts


def test_diagnostic_diff_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        scored, risk, accounts = seed(root)
        out = root / "out"
        summary = audit(
            scored_path=scored,
            risk_path=risk,
            account_paths=accounts,
            output_dir=out,
            as_of_date="2026-07-13",
            challenger_rank_ceiling=4,
        )
        assert summary["status"] == "READY_DIAGNOSTIC_SELECTOR_DIFF_REVIEW"
        assert summary["registered_selector_allowed"] is False
        assert summary["registered_selector_executed"] is False
        assert summary["orders_generated"] is False
        assert summary["target_books_mutated"] is False
        held = pd.read_csv(out / "held_score_risk_audit.csv")
        zzz = held[held["ticker"] == "ZZZ"].iloc[0]
        assert zzz["review_bucket"] == "HELD_INELIGIBLE_REVIEW"
        assert set(held["trade_instruction"]) == {"NONE_REVIEW_ONLY"}
        pairs = pd.read_csv(out / "rank_gap_review_pairs.csv")
        assert not pairs.empty
        assert set(pairs["execution_allowed"].astype(str).str.lower()) == {"false"}


def test_asof_mismatch_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        scored, risk, accounts = seed(root)
        frame = pd.read_csv(scored)
        frame.loc[0, "technical_available_after_close"] = "2026-07-10"
        frame.to_csv(scored, index=False)
        try:
            audit(
                scored_path=scored,
                risk_path=risk,
                account_paths=accounts,
                output_dir=root / "out",
                as_of_date="2026-07-13",
            )
        except ValueError as exc:
            assert "technical_asof_mismatch" in str(exc)
        else:
            raise AssertionError("mixed technical dates must fail closed")


if __name__ == "__main__":
    test_diagnostic_diff_is_fail_closed()
    test_asof_mismatch_fails_closed()
    print("run287_scored_latest_selector_diff_smoke: PASS")
