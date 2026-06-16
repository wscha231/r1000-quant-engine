#!/usr/bin/env python3
"""Smoke tests for self-correction queue closure."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_self_correction_queue_closure import run  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def queue_item(experiment_id: str, payload_hash: str) -> dict[str, object]:
    return {
        "experiment_id": experiment_id,
        "payload_hash": payload_hash,
        "source_leak": "concentrated:structural_underinvestment_bull",
        "source_run_id": "27516185696",
        "status": "queued",
        "production_mutation_allowed": False,
        "requires_user_approval": True,
    }


def test_queue_closure_maps_verifier_decisions_to_statuses() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        queue_path = root / "router_queue.json"
        verifier_path = root / "verifier_summary.json"
        out = root / "out"
        write_json(
            queue_path,
            {
                "schema_version": "self-correction-router-v1.1",
                "production_mutation_allowed": False,
                "queued_experiments": [
                    queue_item("conc_continuation_winner_relaxation", "payload-ready"),
                    queue_item("conc_bull_floor_stock_min", "payload-reject"),
                    queue_item("conc_reentry_quality", "payload-blocked"),
                    queue_item("conc_theme_leadership_boost", "payload-open"),
                ],
                "duplicate_suppressed_count": 1,
                "duplicate_suppressed": [{"experiment_id": "duplicate"}],
                "stale_payloads": [{"experiment_id": "stale_old", "status": "stale"}],
            },
        )
        write_json(
            verifier_path,
            {
                "schema_version": "ab-result-verifier-v1",
                "status": "review_candidate_ready",
                "production_activation_allowed": False,
                "dispatch_context": {"workflow_run_id": "123456"},
                "candidates": [
                    {
                        "experiment_id": "conc_continuation_winner_relaxation",
                        "payload_hash": "payload-ready",
                        "candidate_run": "run-ready",
                        "decision": "promote_candidate_review_only",
                        "review_valid_for_promotion": True,
                        "issues": [],
                        "cagr": 0.52,
                        "max_dd": -0.26,
                        "is_cagr": 0.31,
                    },
                    {
                        "experiment_id": "conc_bull_floor_stock_min",
                        "candidate_run": "run-rejected",
                        "decision": "reject_regression",
                        "review_valid_for_promotion": False,
                        "issues": ["is_cagr_delta_below_min:-1.0pp"],
                    },
                    {
                        "experiment_id": "conc_reentry_quality",
                        "payload_hash": "payload-blocked",
                        "candidate_run": "run-blocked",
                        "decision": "blocked_oos_lock",
                        "review_valid_for_promotion": False,
                        "issues": ["oos_is_cagr_ratio_above_lock"],
                    },
                ],
            },
        )
        payload = run(
            Namespace(
                queue_path=str(queue_path),
                verifier_summary=[str(verifier_path)],
                verifier_dir=[],
                output_dir=str(out),
            )
        )
        by_id = {item["experiment_id"]: item for item in payload["queue_state"]}
        assert by_id["conc_continuation_winner_relaxation"]["status"] == "ready_for_human_review"
        assert by_id["conc_continuation_winner_relaxation"]["workflow_run_id"] == "123456"
        assert by_id["conc_bull_floor_stock_min"]["status"] == "rejected"
        assert by_id["conc_reentry_quality"]["status"] == "measured"
        assert by_id["conc_reentry_quality"]["requires_followup"] is True
        assert by_id["conc_theme_leadership_boost"]["status"] == "queued"
        assert by_id["conc_theme_leadership_boost"]["closure_match_status"] == "unmatched"
        assert payload["matched_item_count"] == 3
        assert payload["ready_for_human_review_count"] == 1
        assert payload["rejected_count"] == 1
        assert payload["measured_count"] == 1
        assert payload["duplicate_suppressed_count"] == 1
        assert payload["stale_payload_count"] == 1
        assert payload["production_mutation_allowed"] is False
        assert payload["live_trading_allowed"] is False
        assert (out / "summary.json").exists()
        assert (out / "queue_state.jsonl").exists()
        assert (out / "deduped_queue.json").exists()
        assert (out / "stale_payloads.json").exists()
        assert (out / "closure_report.md").exists()


if __name__ == "__main__":
    test_queue_closure_maps_verifier_decisions_to_statuses()
    print("self_correction_queue_closure_smoke: PASS")
