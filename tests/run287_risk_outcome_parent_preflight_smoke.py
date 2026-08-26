#!/usr/bin/env python3
"""Smoke tests for the read-only risk-outcome parent preflight receipt."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_risk_outcome_parent_preflight import (  # noqa: E402
    FALSE_SAFETY_FLAGS,
    build_receipt,
    sha256_bytes,
    write_receipt,
)


KNOWN_LEGACY_SUMMARY_SHA256 = (
    "5a57e4becef19668dce45803eb77185bc"
    "6c60bcf9b58522df939e9a48a56654c"
)
FAILED_RUN_SHA = "f28321d011d0705cf8fdd43f1f98647f85557d42"
PAPER_TERMINAL = (
    "65fa6f5b4b12729811b72a90661fc744"
    "320826dfe868ec6da2632768b1ec02a7"
)
PAPER_GENESIS = (
    "ef78e63c9e52607a6473ca4c07179cb"
    "92a5f29a85eeb43031e8a47cd09b4f267"
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )


def write_known_legacy_summary(path: Path) -> None:
    payload = {
        "as_of_date": "2026-07-17",
        "blockers": [],
        "distinct_decision_week_count": 0,
        "fullrun_executed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "live_trading_enabled": False,
        "mechanism_review_gate": {
            "normal_63d_count": 0,
            "warning_63d_count": 0,
        },
        "mechanism_review_ready": False,
        "orders_generated": False,
        "portfolio_transition_allowed": False,
        "price_universe_unique_ticker_count": 1,
        "production_activation_allowed": False,
        "review_only": True,
        "schema_version": "run287-risk-outcome-archive-v1",
        "signal_observation_count": 0,
        "status": "SKIPPED_NO_DECISION_OBSERVATIONS",
        "target_books_mutated": False,
    }
    write_json(path, payload)
    assert sha256_bytes(path.read_bytes()) == KNOWN_LEGACY_SUMMARY_SHA256
    assert len(path.read_bytes()) == 668


def write_paper_integrity(path: Path) -> None:
    ancestors = ["a" * 64, "b" * 64, "c" * 64, "d" * 64, "e" * 64]
    write_json(
        path,
        {
            "ancestor_snapshot_hashes": ancestors,
            "as_of_date": "2026-07-24",
            "generated_at_utc": "2026-08-05T04:58:54Z",
            "genesis_identity_sha256": PAPER_GENESIS,
            "previous_snapshot_hash": ancestors[0],
            "schema_version": (
                "run287-paper-ledger-snapshot-integrity-v2"
            ),
            "snapshot_hash": PAPER_TERMINAL,
            "status": "VERIFIED",
        },
    )


def base_kwargs(root: Path) -> dict:
    summary = root / "outcome" / "summary.json"
    paper = root / "paper" / "snapshot_integrity.json"
    write_known_legacy_summary(summary)
    write_paper_integrity(paper)
    return {
        "event_name": "schedule",
        "source_commit_sha": FAILED_RUN_SHA,
        "source_run_id": "31071342439",
        "source_run_attempt": "1",
        "source_job_key": "refresh",
        "session_date": "2026-08-05",
        "remote_head_discovery_confirmed": True,
        "remote_committed_head_count": 0,
        "remote_legacy_outcome_state": "PRESENT_FETCHED",
        "legacy_summary_path": summary,
        "legacy_event_log_path": root / "outcome" / "events.jsonl",
        "paper_integrity_path": paper,
        "allow_risk_outcome_genesis_bootstrap": False,
        "allow_quarantined_legacy_outcome_parent": False,
        "generated_at_utc": "2026-08-26T00:00:00Z",
    }


def assert_safe(receipt: dict) -> None:
    assert receipt["review_only"] is True
    for field in FALSE_SAFETY_FLAGS:
        assert receipt[field] is False


def test_failed_schedule_receipt_is_exact_and_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_ONE_TIME_LEGACY_QUARANTINE_"
            "AUTHORIZATION_REQUIRED"
        )
        observed = receipt["observed_state"]
        assert observed["remote_committed_accepted_head_count"] == 0
        assert observed[
            "remote_committed_accepted_head_absence_proven"
        ] is True
        legacy = observed["legacy_parent"]
        assert legacy["summary_sha256"] == KNOWN_LEGACY_SUMMARY_SHA256
        assert legacy["summary_bytes"] == 668
        assert legacy["byte_exact_allowlist_match"] is True
        assert observed["paper_ledger"]["snapshot_hash"] == PAPER_TERMINAL
        assert receipt["authorization"]["satisfied"] is False
        assert receipt["blockers"] == [
            "explicit_workflow_dispatch_authorization_required"
        ]
        assert_safe(receipt)


def test_explicit_legacy_dispatch_opens_only_existing_boundary() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_quarantined_legacy_outcome_parent"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 0
        assert receipt["status"] == "READY_ONE_TIME_LEGACY_QUARANTINE"
        assert receipt["authorization"]["satisfied"] is True
        assert receipt["next_action"] == (
            "continue_to_existing_one_time_parent_anchor_boundary"
        )
        assert receipt["accepted_head_created"] is False
        assert receipt["parent_anchor_created"] is False
        assert_safe(receipt)


def test_unknown_legacy_bytes_never_receive_authority() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_quarantined_legacy_outcome_parent"] = True
        summary = Path(kwargs["legacy_summary_path"])
        summary.write_bytes(summary.read_bytes().rstrip(b"\n"))
        try:
            build_receipt(**kwargs)
        except ValueError as exc:
            assert "legacy_summary_sha256_not_allowlisted" in str(exc)
        else:
            raise AssertionError("unknown legacy bytes were accepted")


def test_remote_absence_and_paper_integrity_are_mandatory() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["remote_head_discovery_confirmed"] = False
        try:
            build_receipt(**kwargs)
        except ValueError as exc:
            assert "remote_accepted_head_discovery_not_confirmed" in str(exc)
        else:
            raise AssertionError("unconfirmed remote absence was accepted")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["remote_committed_head_count"] = 1
        try:
            build_receipt(**kwargs)
        except ValueError as exc:
            assert "remote_accepted_head_absence_not_proven" in str(exc)
        else:
            raise AssertionError("existing accepted head was ignored")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        Path(kwargs["paper_integrity_path"]).unlink()
        try:
            build_receipt(**kwargs)
        except ValueError as exc:
            assert "paper_integrity_missing" in str(exc)
        else:
            raise AssertionError("missing paper integrity was accepted")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        paper_path = Path(kwargs["paper_integrity_path"])
        paper = json.loads(paper_path.read_text(encoding="utf-8"))
        paper["as_of_date"] = "2026-7-24"
        write_json(paper_path, paper)
        try:
            build_receipt(**kwargs)
        except ValueError as exc:
            assert "paper_integrity_as_of_date_invalid" in str(exc)
        else:
            raise AssertionError("invalid paper as-of date was accepted")


def test_genesis_requires_exact_absence_and_separate_dispatch() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        Path(kwargs["legacy_summary_path"]).unlink()
        kwargs["remote_legacy_outcome_state"] = "PROVEN_ABSENT"
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_ONE_TIME_GENESIS_AUTHORIZATION_REQUIRED"
        )

        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_risk_outcome_genesis_bootstrap"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 0
        assert receipt["status"] == "READY_ONE_TIME_GENESIS"
        assert receipt["observed_state"]["legacy_parent"]["state"] == (
            "PROVEN_ABSENT"
        )
        assert_safe(receipt)


def test_mismatched_and_mutually_exclusive_authorizations_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_risk_outcome_genesis_bootstrap"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_PARENT_MODE_AUTHORIZATION_MISMATCH"
        )

        kwargs["allow_quarantined_legacy_outcome_parent"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_MUTUALLY_EXCLUSIVE_BOOTSTRAP_AUTHORIZATIONS"
        )
        assert_safe(receipt)


def test_receipt_write_is_complete_and_replayable() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        receipt, _ = build_receipt(**kwargs)
        output = root / "receipt" / "receipt.json"
        write_receipt(output, receipt)
        assert json.loads(output.read_text(encoding="utf-8")) == receipt
        assert not output.with_name(".receipt.json.tmp").exists()


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"run287_risk_outcome_parent_preflight_smoke: {len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
