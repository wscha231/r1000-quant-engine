#!/usr/bin/env python3
"""Smoke for era-aware promotion policy handoff into the guarded bridge."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from r1000_sidecar_promotion import file_sha256, run_approved_integrated  # noqa: E402


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_approved_bridge_accepts_era_aware_source_only_with_manual_gates() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        write_text(reports / "operating_main_target_book.csv", "rebalance_date,ticker,weight\n2026-01-31,AAA,0.9\n")
        write_text(reports / "operating_concentrated_target_book.csv", "rebalance_date,ticker,weight\n2026-01-31,OLD,0.9\n")
        source = latest / "era_aware_scoring_challenger" / "concentrated_target_book.csv"
        write_text(source, "rebalance_date,ticker,weight\n2026-01-31,ERA,0.9\n2026-01-31,CASH,0.1\n")
        write_json(
            latest / "promotion_review" / "integrated_target_promotion_check.json",
            {
                "main_promotion_gate": {"status": "rejected", "blockers": ["not_requested"]},
                "concentrated_promotion_gate": {"status": "rejected", "blockers": ["era_source_requires_manual_review"]},
            },
        )
        policy = {
            "approved_portfolios": ["concentrated"],
            "source_run_id": "era_candidate_run",
            "source_policy_concentrated": "era_aware",
            "source_case_id_concentrated": "era_aware",
            "source_target_book_path_concentrated": str(source),
            "source_target_book_sha256_concentrated": file_sha256(source),
            "main": {"approved": False, "source_policy": "era_aware", "source_case_id": "era_aware"},
            "concentrated": {
                "approved": True,
                "source_policy": "era_aware",
                "source_case_id": "era_aware",
                "source_target_book_path": str(source),
                "source_target_book_sha256": file_sha256(source),
                "manual_gate_override": True,
                "allow_stale_holding_exit_override": True,
                "manual_gate_override_reason": "Human-approved era-aware candidate after separate A/B verifier pass.",
            },
            "human_approved": True,
            "production_mutation_allowed": True,
            "allow_replace_operating_target_books": True,
        }
        policy_path = latest / "promotion_review" / "approved_target_policy.json"
        write_json(policy_path, policy)
        before_main = file_sha256(reports / "operating_main_target_book.csv")
        old_env = os.environ.get("ALLOW_PRODUCTION_MUTATION")
        os.environ["ALLOW_PRODUCTION_MUTATION"] = "1"
        try:
            audit = run_approved_integrated(
                latest_run=latest,
                output_root=latest,
                policy_path=policy_path,
                integrated_dir=latest / "integrated_theme_leader_crisis_replay",
            )
        finally:
            if old_env is None:
                os.environ.pop("ALLOW_PRODUCTION_MUTATION", None)
            else:
                os.environ["ALLOW_PRODUCTION_MUTATION"] = old_env
        assert audit["status"] == "applied"
        assert [row["portfolio"] for row in audit["actual_changes"]] == ["concentrated"]
        assert audit["actual_changes"][0]["source_policy"] == "era_aware"
        assert audit["actual_changes"][0]["source_case_id"] == "era_aware"
        assert audit["actual_changes"][0]["gate_override_used"] is True
        assert file_sha256(reports / "operating_main_target_book.csv") == before_main
        assert file_sha256(reports / "operating_concentrated_target_book.csv") == file_sha256(source)


if __name__ == "__main__":
    test_approved_bridge_accepts_era_aware_source_only_with_manual_gates()
    print("era_aware_promotion_policy_smoke: PASS")
