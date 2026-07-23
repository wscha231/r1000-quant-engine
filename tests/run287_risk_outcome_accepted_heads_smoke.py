#!/usr/bin/env python3
"""Smoke tests for immutable Run287 risk-outcome accepted heads."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.manage_run287_risk_outcome_accepted_heads import (  # noqa: E402
    EMPTY_SHA256,
    OUTCOME_FALSE_SAFETY_FIELDS,
    _linear_chain,
    select_heads,
    stage_head,
    verify_head,
)
from tools.build_run287_risk_outcome_parent_anchor import (  # noqa: E402
    build_anchor,
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def make_chain(
    *,
    event_payload: bytes,
    as_of_date: str,
    parent_acceptance_status: str,
    parent_accepted_manifest_sha256: str,
    parent_accepted_manifest_bytes: int = 0,
    parent_accepted_manifest_as_of_date: str = "",
    parent_event_payload: bytes | None = None,
    parent_summary_sha256: str = "c" * 64,
    parent_summary_bytes: int = 1,
    parent_quarantined_prefix_event_count: int = 0,
) -> dict[str, Any]:
    event_count = len(event_payload.splitlines())
    if parent_acceptance_status == "NO_PRIOR_STATE":
        parent_anchor_status = "GENESIS_EMPTY"
        parent_summary_sha256 = ""
        parent_summary_bytes = 0
        parent_payload = b""
        parent_as_of_date = ""
        quarantined = 0
    else:
        parent_payload = (
            event_payload
            if parent_event_payload is None
            else parent_event_payload
        )
        parent_anchor_status = (
            "VERIFIED_PARENT"
            if parent_payload
            else "VERIFIED_EMPTY_PARENT"
        )
        parent_as_of_date = (
            parent_accepted_manifest_as_of_date or as_of_date
        )
        quarantined = (
            len(parent_payload.splitlines())
            if parent_acceptance_status == "QUARANTINED_LEGACY"
            else parent_quarantined_prefix_event_count
        )
    return {
        "schema_version": "run287-risk-outcome-chain-v1",
        "status": "VERIFIED_APPEND_ONLY",
        "parent_anchor_sha256": "a" * 64,
        "parent_anchor_status": parent_anchor_status,
        "parent_summary_sha256": parent_summary_sha256,
        "parent_summary_bytes": parent_summary_bytes,
        "parent_event_log_sha256": sha256_bytes(parent_payload),
        "parent_event_log_bytes": len(parent_payload),
        "parent_event_count": len(parent_payload.splitlines()),
        "parent_as_of_date": parent_as_of_date,
        "carried_quarantined_prefix_event_count": quarantined,
        "current_event_log_sha256": sha256_bytes(event_payload),
        "current_event_log_bytes": len(event_payload),
        "current_event_count": event_count,
        "current_as_of_date": as_of_date,
        "exact_parent_prefix_verified": True,
        "append_only_verified": True,
        "trusted_event_count": event_count - quarantined,
        "parent_acceptance_status": parent_acceptance_status,
        "parent_accepted_manifest_sha256":
            parent_accepted_manifest_sha256,
        "parent_accepted_manifest_bytes":
            parent_accepted_manifest_bytes,
        "parent_accepted_manifest_as_of_date":
            parent_accepted_manifest_as_of_date,
    }


def make_latest_run(
    root: Path,
    *,
    as_of_date: str,
    parent_acceptance_status: str,
    parent_accepted_manifest_sha256: str,
    parent_accepted_manifest_bytes: int = 0,
    parent_accepted_manifest_as_of_date: str = "",
    parent_event_payload: bytes | None = None,
    parent_summary_sha256: str = "c" * 64,
    parent_summary_bytes: int = 1,
    parent_quarantined_prefix_event_count: int = 0,
    paper_snapshot_hash: str | None = None,
    paper_previous_snapshot_hash: str | None = None,
    paper_ancestor_snapshot_hashes: list[str] | None = None,
    event_numbers: list[int],
) -> tuple[Path, str]:
    latest = root
    event_payload = b"".join(
        (
            json.dumps(
                {
                    "event_id": f"event-{number}",
                    "event_type": (
                        "risk_signal_observed"
                        if number % 2
                        else "forward_outcome_observed"
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for number in event_numbers
    )
    chain = make_chain(
        event_payload=event_payload,
        as_of_date=as_of_date,
        parent_acceptance_status=parent_acceptance_status,
        parent_accepted_manifest_sha256=parent_accepted_manifest_sha256,
        parent_accepted_manifest_bytes=parent_accepted_manifest_bytes,
        parent_accepted_manifest_as_of_date=(
            parent_accepted_manifest_as_of_date
        ),
        parent_event_payload=parent_event_payload,
        parent_summary_sha256=parent_summary_sha256,
        parent_summary_bytes=parent_summary_bytes,
        parent_quarantined_prefix_event_count=(
            parent_quarantined_prefix_event_count
        ),
    )
    archive = latest / "run287_risk_outcome_archive"
    archive.mkdir(parents=True)
    event_path = archive / "risk_outcome_events.jsonl"
    event_path.write_bytes(event_payload)
    summary = {
        "schema_version": "run287-risk-outcome-archive-v1",
        "status": "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY",
        "as_of_date": as_of_date,
        "blockers": [],
        "outputs": {"event_log_sha256": sha256_bytes(event_payload)},
        "signal_observation_count": sum(
            number % 2 for number in event_numbers
        ),
        "forward_outcome_event_count": sum(
            number % 2 == 0 for number in event_numbers
        ),
        "outcome_chain": chain,
        "review_only": True,
        **{field: False for field in OUTCOME_FALSE_SAFETY_FIELDS},
    }
    summary_path = archive / "summary.json"
    write_json(summary_path, summary)
    manifest = {
        "schema_version": "run287-accepted-publication-manifest-v1",
        "status": "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY",
        "as_of_date": as_of_date,
        "source_identity": {
            "commit_sha": "a" * 40,
            "workflow": (
                "owner/repo/.github/workflows/"
                "daily_operating_selection_refresh.yml@refs/heads/master"
            ),
            "run_id": "123",
            "run_attempt": "1",
            "promotion_gate_sha256": "d" * 64,
        },
        "paper_snapshot": {
            "snapshot_hash": (
                paper_snapshot_hash
                or (
                    "b" * 64
                    if parent_accepted_manifest_sha256 == ""
                    else "e" * 64
                )
            ),
            "genesis_identity_sha256": "8" * 64,
            "previous_snapshot_hash": (
                paper_previous_snapshot_hash
                if paper_previous_snapshot_hash is not None
                else (
                    ""
                    if parent_accepted_manifest_sha256 == ""
                    else "b" * 64
                )
            ),
            "ancestor_snapshot_hashes": (
                paper_ancestor_snapshot_hashes
                if paper_ancestor_snapshot_hashes is not None
                else (
                    []
                    if parent_accepted_manifest_sha256 == ""
                    else ["b" * 64]
                )
            ),
            "file_count": 3,
            "transaction_mode": "MARK_ONLY",
        },
        "outcome_status": summary["status"],
        "outcome_chain": chain,
        "files": {
            "promotion_gate": {
                "path": "run287_promotion_gate/promotion_gate.json",
                "sha256": "d" * 64,
            },
            "risk_outcome_summary": {
                "path": "run287_risk_outcome_archive/summary.json",
                "sha256": sha256_bytes(summary_path.read_bytes()),
                "bytes": summary_path.stat().st_size,
            },
            "risk_outcome_event_log": {
                "path":
                    "run287_risk_outcome_archive/risk_outcome_events.jsonl",
                "sha256": sha256_bytes(event_payload),
            },
        },
        "review_only": True,
        "automatic_champion_replacement_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }
    manifest_path = latest / "run287_accepted_publication" / "manifest.json"
    write_json(manifest_path, manifest)
    return latest, sha256_bytes(manifest_path.read_bytes())


def make_skipped_latest_run(root: Path) -> tuple[Path, str]:
    latest, _ = make_latest_run(
        root,
        as_of_date="2026-07-22",
        parent_acceptance_status="QUARANTINED_LEGACY",
        parent_accepted_manifest_sha256="",
        event_numbers=[],
    )
    summary_path = latest / "run287_risk_outcome_archive/summary.json"
    event_path = (
        latest
        / "run287_risk_outcome_archive"
        / "risk_outcome_events.jsonl"
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "SKIPPED_NO_DECISION_OBSERVATIONS"
    summary.pop("outputs")
    write_json(summary_path, summary)
    event_path.unlink()

    manifest_path = latest / "run287_accepted_publication/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outcome_status"] = summary["status"]
    manifest["files"]["risk_outcome_summary"]["sha256"] = sha256_bytes(
        summary_path.read_bytes()
    )
    manifest["files"]["risk_outcome_summary"]["bytes"] = (
        summary_path.stat().st_size
    )
    del manifest["files"]["risk_outcome_event_log"]
    write_json(manifest_path, manifest)
    return latest, sha256_bytes(manifest_path.read_bytes())


def stage_fixture(
    heads: Path,
    *,
    latest: Path,
    manifest_sha256: str,
) -> Path:
    target = heads / manifest_sha256
    result = stage_head(
        latest_run=latest,
        expected_manifest_sha256=manifest_sha256,
        output_dir=target,
    )
    assert result["status"] == "STAGED_NEW_ACCEPTED_HEAD"
    return target


def verified_parent_kwargs(head: Path) -> dict[str, Any]:
    manifest_path = head / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    event_path = head / "run287_risk_outcome_archive/risk_outcome_events.jsonl"
    return {
        "parent_accepted_manifest_sha256": head.name,
        "parent_accepted_manifest_bytes": manifest_path.stat().st_size,
        "parent_accepted_manifest_as_of_date": manifest["as_of_date"],
        "parent_event_payload": (
            event_path.read_bytes() if event_path.is_file() else b""
        ),
        "parent_summary_sha256":
            manifest["files"]["risk_outcome_summary"]["sha256"],
        "parent_summary_bytes":
            manifest["files"]["risk_outcome_summary"]["bytes"],
        "parent_quarantined_prefix_event_count":
            manifest["outcome_chain"][
                "carried_quarantined_prefix_event_count"
            ],
    }


def reseal_event_payload(
    latest: Path,
    *,
    event_payload: bytes,
    signal_observation_count: int,
    forward_outcome_event_count: int,
) -> str:
    event_path = (
        latest
        / "run287_risk_outcome_archive"
        / "risk_outcome_events.jsonl"
    )
    event_path.write_bytes(event_payload)
    summary_path = latest / "run287_risk_outcome_archive/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    event_count = len(event_payload.splitlines())
    chain = summary["outcome_chain"]
    chain["current_event_log_sha256"] = sha256_bytes(event_payload)
    chain["current_event_log_bytes"] = len(event_payload)
    chain["current_event_count"] = event_count
    chain["trusted_event_count"] = (
        event_count - chain["carried_quarantined_prefix_event_count"]
    )
    summary["outputs"]["event_log_sha256"] = sha256_bytes(event_payload)
    summary["signal_observation_count"] = signal_observation_count
    summary["forward_outcome_event_count"] = (
        forward_outcome_event_count
    )
    write_json(summary_path, summary)

    manifest_path = latest / "run287_accepted_publication/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outcome_chain"] = chain
    manifest["files"]["risk_outcome_summary"]["sha256"] = sha256_bytes(
        summary_path.read_bytes()
    )
    manifest["files"]["risk_outcome_summary"]["bytes"] = (
        summary_path.stat().st_size
    )
    manifest["files"]["risk_outcome_event_log"]["sha256"] = (
        sha256_bytes(event_payload)
    )
    write_json(manifest_path, manifest)
    return sha256_bytes(manifest_path.read_bytes())


def assert_raises(fragment: str, callback: Any) -> None:
    try:
        callback()
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {fragment!r}")


def test_normal_two_head_chain_verify_and_idempotent_stage() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        first_latest, first_sha = make_latest_run(
            root / "latest-1",
            as_of_date="2026-07-21",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        first_head = stage_fixture(
            heads,
            latest=first_latest,
            manifest_sha256=first_sha,
        )
        second_latest, second_sha = make_latest_run(
            root / "latest-2",
            as_of_date="2026-07-22",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **verified_parent_kwargs(first_head),
            event_numbers=[1, 2],
        )
        second_head = stage_fixture(
            heads,
            latest=second_latest,
            manifest_sha256=second_sha,
        )

        selection = select_heads(
            heads_root=heads,
            now_utc="2026-07-23T00:00:00Z",
        )
        assert selection["root_accepted_manifest_sha256"] == first_sha
        assert selection["terminal_accepted_manifest_sha256"] == second_sha
        assert selection["selected_accepted_manifest_sha256"] == second_sha
        assert selection["chain_accepted_manifest_sha256s"] == [
            first_sha,
            second_sha,
        ]
        verified = verify_head(
            head_dir=second_head,
            expected_manifest_sha256=second_sha,
        )
        assert verified["status"] == "VERIFIED_ACCEPTED_HEAD"
        assert verified["outcome_event_count"] == 2
        anchor = build_anchor(
            second_head / "run287_risk_outcome_archive/summary.json",
            (
                second_head
                / "run287_risk_outcome_archive"
                / "risk_outcome_events.jsonl"
            ),
            parent_accepted_manifest_path=second_head / "manifest.json",
            expected_parent_accepted_manifest_sha256=second_sha,
            now_utc="2026-07-23T00:00:00Z",
        )
        assert anchor["status"] == "VERIFIED_PARENT"
        assert (
            anchor["parent_acceptance_status"]
            == "VERIFIED_ACCEPTED_HEAD"
        )
        assert anchor["parent_accepted_manifest_sha256"] == second_sha

        repeated = stage_head(
            latest_run=second_latest,
            expected_manifest_sha256=second_sha,
            output_dir=second_head,
        )
        assert repeated["status"] == "ALREADY_STAGED_EXACT_MATCH"
        assert first_head.is_dir()


def test_event_tamper_is_rejected_without_relying_on_folder_manifest() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, manifest_sha256 = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="QUARANTINED_LEGACY",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        head = stage_fixture(
            root / "heads",
            latest=latest,
            manifest_sha256=manifest_sha256,
        )
        (head / "run287_risk_outcome_archive/risk_outcome_events.jsonl").write_text(
            '{"event_id":"tampered"}\n',
            encoding="utf-8",
        )
        assert_raises(
            "accepted_head_outcome_event_log_sha256_mismatch",
            lambda: verify_head(
                head_dir=head,
                expected_manifest_sha256=manifest_sha256,
            ),
        )
        assert_raises(
            "accepted_head_output_exists_not_exact_match",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=head,
            ),
        )


def test_skipped_archive_allows_missing_empty_event_log() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, manifest_sha256 = make_skipped_latest_run(root / "latest")
        head = stage_fixture(
            root / "heads",
            latest=latest,
            manifest_sha256=manifest_sha256,
        )
        assert not (
            head
            / "run287_risk_outcome_archive"
            / "risk_outcome_events.jsonl"
        ).exists()
        verified = verify_head(
            head_dir=head,
            expected_manifest_sha256=manifest_sha256,
        )
        assert verified["outcome_status"] == (
            "SKIPPED_NO_DECISION_OBSERVATIONS"
        )
        assert verified["outcome_event_log_sha256"] == EMPTY_SHA256
        assert verified["outcome_event_log_bytes"] == 0
        assert verified["outcome_event_count"] == 0


def test_fork_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        parent_latest, parent_sha = make_latest_run(
            root / "parent",
            as_of_date="2026-07-20",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        parent_head = stage_fixture(
            heads,
            latest=parent_latest,
            manifest_sha256=parent_sha,
        )
        for suffix, date, events in (
            ("child-a", "2026-07-21", [1, 2]),
            ("child-b", "2026-07-22", [1, 3]),
        ):
            child_latest, child_sha = make_latest_run(
                root / suffix,
                as_of_date=date,
                parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
                **verified_parent_kwargs(parent_head),
                event_numbers=events,
            )
            stage_fixture(
                heads,
                latest=child_latest,
                manifest_sha256=child_sha,
            )
        assert_raises(
            "accepted_head_fork_detected",
            lambda: select_heads(heads_root=heads),
        )


def test_orphan_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        orphan_latest, orphan_sha = make_latest_run(
            root / "orphan",
            as_of_date="2026-07-22",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            parent_accepted_manifest_sha256="d" * 64,
            parent_accepted_manifest_bytes=1,
            parent_accepted_manifest_as_of_date="2026-07-21",
            parent_event_payload=(
                b'{"event_id":"event-1",'
                b'"event_type":"risk_signal_observed"}\n'
            ),
            event_numbers=[1],
        )
        stage_fixture(
            heads,
            latest=orphan_latest,
            manifest_sha256=orphan_sha,
        )
        assert_raises(
            "accepted_head_parent_missing",
            lambda: select_heads(heads_root=heads),
        )


def test_child_parent_manifest_identity_must_match_actual_parent() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        parent_latest, parent_sha = make_latest_run(
            root / "parent",
            as_of_date="2026-07-20",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        parent_head = stage_fixture(
            heads,
            latest=parent_latest,
            manifest_sha256=parent_sha,
        )
        wrong_parent = verified_parent_kwargs(parent_head)
        wrong_parent["parent_accepted_manifest_bytes"] += 1
        child_latest, child_sha = make_latest_run(
            root / "child",
            as_of_date="2026-07-21",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **wrong_parent,
            event_numbers=[1, 2],
        )
        stage_fixture(
            heads,
            latest=child_latest,
            manifest_sha256=child_sha,
        )
        assert_raises(
            "accepted_head_parent_identity_mismatch",
            lambda: select_heads(heads_root=heads),
        )


def test_child_parent_outcome_state_must_match_actual_parent() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        parent_latest, parent_sha = make_latest_run(
            root / "parent",
            as_of_date="2026-07-20",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        parent_head = stage_fixture(
            heads,
            latest=parent_latest,
            manifest_sha256=parent_sha,
        )
        forged_parent = verified_parent_kwargs(parent_head)
        forged_parent["parent_event_payload"] = (
            b'{"event_id":"event-9",'
            b'"event_type":"risk_signal_observed"}\n'
        )
        child_latest, child_sha = make_latest_run(
            root / "child",
            as_of_date="2026-07-21",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **forged_parent,
            event_numbers=[9, 2],
        )
        stage_fixture(
            heads,
            latest=child_latest,
            manifest_sha256=child_sha,
        )
        assert_raises(
            "accepted_head_parent_state_mismatch",
            lambda: select_heads(heads_root=heads),
        )


def test_multiple_roots_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        for suffix, date, status in (
            ("root-a", "2026-07-21", "NO_PRIOR_STATE"),
            ("root-b", "2026-07-22", "QUARANTINED_LEGACY"),
        ):
            latest, manifest_sha256 = make_latest_run(
                root / suffix,
                as_of_date=date,
                parent_acceptance_status=status,
                parent_accepted_manifest_sha256="",
                event_numbers=[1],
            )
            stage_fixture(
                heads,
                latest=latest,
                manifest_sha256=manifest_sha256,
            )
        assert_raises(
            "accepted_head_root_count_invalid:2",
            lambda: select_heads(heads_root=heads),
        )


def test_source_identity_is_required() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        manifest_path = (
            latest / "run287_accepted_publication" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_identity"]["commit_sha"] = "not-a-commit"
        write_json(manifest_path, manifest)
        manifest_sha256 = sha256_bytes(manifest_path.read_bytes())
        assert_raises(
            "accepted_head_source_identity_invalid",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_summary_size_attestation_is_reverified() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        manifest_path = (
            latest / "run287_accepted_publication" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["risk_outcome_summary"]["bytes"] += 1
        write_json(manifest_path, manifest)
        manifest_sha256 = sha256_bytes(manifest_path.read_bytes())
        assert_raises(
            "accepted_head_outcome_summary_bytes_mismatch",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_promotion_gate_identity_must_match_attested_file() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        manifest_path = (
            latest / "run287_accepted_publication" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_identity"]["promotion_gate_sha256"] = "c" * 64
        write_json(manifest_path, manifest)
        manifest_sha256 = sha256_bytes(manifest_path.read_bytes())
        assert_raises(
            "accepted_head_promotion_gate_binding_invalid",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_child_paper_snapshot_must_descend_from_parent_paper() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        parent_latest, parent_sha = make_latest_run(
            root / "parent",
            as_of_date="2026-07-20",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        parent_head = stage_fixture(
            heads,
            latest=parent_latest,
            manifest_sha256=parent_sha,
        )
        child_latest, _ = make_latest_run(
            root / "child",
            as_of_date="2026-07-21",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **verified_parent_kwargs(parent_head),
            event_numbers=[1, 2],
        )
        manifest_path = (
            child_latest
            / "run287_accepted_publication"
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["paper_snapshot"].update(
            {
                "snapshot_hash": "f" * 64,
                "previous_snapshot_hash": "9" * 64,
                "ancestor_snapshot_hashes": ["9" * 64],
            }
        )
        write_json(manifest_path, manifest)
        child_sha = sha256_bytes(manifest_path.read_bytes())
        stage_fixture(
            heads,
            latest=child_latest,
            manifest_sha256=child_sha,
        )
        assert_raises(
            "accepted_head_parent_paper_not_ancestor",
            lambda: select_heads(heads_root=heads),
        )


def test_child_paper_genesis_must_match_parent_paper() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        parent_latest, parent_sha = make_latest_run(
            root / "parent",
            as_of_date="2026-07-20",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        parent_head = stage_fixture(
            heads,
            latest=parent_latest,
            manifest_sha256=parent_sha,
        )
        child_latest, _ = make_latest_run(
            root / "child",
            as_of_date="2026-07-21",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **verified_parent_kwargs(parent_head),
            event_numbers=[1, 2],
        )
        manifest_path = (
            child_latest
            / "run287_accepted_publication"
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["paper_snapshot"]["genesis_identity_sha256"] = "7" * 64
        write_json(manifest_path, manifest)
        child_sha = sha256_bytes(manifest_path.read_bytes())
        stage_fixture(
            heads,
            latest=child_latest,
            manifest_sha256=child_sha,
        )
        assert_raises(
            "accepted_head_parent_paper_genesis_mismatch",
            lambda: select_heads(heads_root=heads),
        )


def test_summary_event_type_counts_must_match_parsed_log() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        event_payload = (
            latest
            / "run287_risk_outcome_archive"
            / "risk_outcome_events.jsonl"
        ).read_bytes()
        manifest_sha256 = reseal_event_payload(
            latest,
            event_payload=event_payload,
            signal_observation_count=0,
            forward_outcome_event_count=1,
        )
        assert_raises(
            "accepted_head_summary_event_count_mismatch",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_duplicate_event_id_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        event_payload = (
            b'{"event_id":"duplicate","event_type":'
            b'"risk_signal_observed"}\n'
            b'{"event_id":"duplicate","event_type":'
            b'"forward_outcome_observed"}\n'
        )
        manifest_sha256 = reseal_event_payload(
            latest,
            event_payload=event_payload,
            signal_observation_count=1,
            forward_outcome_event_count=1,
        )
        assert_raises(
            "accepted_head_event_id_duplicate",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_missing_event_id_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        event_payload = b'{"event_type":"risk_signal_observed"}\n'
        manifest_sha256 = reseal_event_payload(
            latest,
            event_payload=event_payload,
            signal_observation_count=1,
            forward_outcome_event_count=0,
        )
        assert_raises(
            "accepted_head_event_id_invalid",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_duplicate_event_json_key_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        event_payload = (
            b'{"event_id":"event-a","event_id":"event-b",'
            b'"event_type":"risk_signal_observed"}\n'
        )
        manifest_sha256 = reseal_event_payload(
            latest,
            event_payload=event_payload,
            signal_observation_count=1,
            forward_outcome_event_count=0,
        )
        assert_raises(
            "accepted_head_event_log_duplicate_json_key",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_unknown_event_type_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, _ = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        event_payload = (
            b'{"event_id":"event-a","event_type":"unknown"}\n'
        )
        manifest_sha256 = reseal_event_payload(
            latest,
            event_payload=event_payload,
            signal_observation_count=1,
            forward_outcome_event_count=0,
        )
        assert_raises(
            "accepted_head_event_type_invalid",
            lambda: stage_head(
                latest_run=latest,
                expected_manifest_sha256=manifest_sha256,
                output_dir=root / "heads" / manifest_sha256,
            ),
        )


def test_hash_named_verify_rejects_extra_file_and_symlink() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        latest, manifest_sha256 = make_latest_run(
            root / "latest",
            as_of_date="2026-07-22",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        head = stage_fixture(
            root / "heads",
            latest=latest,
            manifest_sha256=manifest_sha256,
        )
        extra = head / "unexpected.txt"
        extra.write_text("unexpected\n", encoding="utf-8")
        assert_raises(
            "accepted_head_bundle_file_set_mismatch",
            lambda: verify_head(
                head_dir=head,
                expected_manifest_sha256=manifest_sha256,
            ),
        )
        extra.unlink()
        link = head / "unexpected-link.json"
        os.symlink("manifest.json", link)
        assert_raises(
            "accepted_head_bundle_symlink_forbidden",
            lambda: verify_head(
                head_dir=head,
                expected_manifest_sha256=manifest_sha256,
            ),
        )


def test_linear_chain_handles_more_than_recursion_limit() -> None:
    node_count = 1_305
    paper_snapshot = {
        "snapshot_hash": "b" * 64,
        "genesis_identity_sha256": "8" * 64,
        "previous_snapshot_hash": "",
        "ancestor_snapshot_hashes": [],
        "file_count": 3,
        "transaction_mode": "MARK_ONLY",
    }
    nodes: dict[str, dict[str, Any]] = {}
    chain_order = [
        f"{node_count - index:064x}"
        for index in range(node_count)
    ]
    for index, sha256 in enumerate(chain_order):
        parent = chain_order[index - 1] if index else ""
        chain = {
            "parent_acceptance_status": (
                "VERIFIED_ACCEPTED_HEAD"
                if parent
                else "NO_PRIOR_STATE"
            ),
            "parent_accepted_manifest_sha256": parent,
            "parent_accepted_manifest_bytes": 1 if parent else 0,
            "parent_accepted_manifest_as_of_date": (
                "2026-07-22" if parent else ""
            ),
            "parent_anchor_status": (
                "VERIFIED_EMPTY_PARENT" if parent else "GENESIS_EMPTY"
            ),
            "parent_summary_sha256": "c" * 64 if parent else "",
            "parent_summary_bytes": 1 if parent else 0,
            "parent_event_log_sha256": EMPTY_SHA256,
            "parent_event_log_bytes": 0,
            "parent_event_count": 0,
            "parent_as_of_date": "2026-07-22" if parent else "",
            "carried_quarantined_prefix_event_count": 0,
            "current_event_log_sha256": EMPTY_SHA256,
            "current_event_log_bytes": 0,
            "current_event_count": 0,
            "trusted_event_count": 0,
        }
        nodes[sha256] = {
            "as_of_date": "2026-07-22",
            "outcome_chain": chain,
            "paper_snapshot": dict(paper_snapshot),
            "files": {
                "risk_outcome_summary": {
                    "sha256": "c" * 64,
                    "bytes": 1,
                }
            },
            "_accepted_head_manifest_bytes": 1,
        }
    root_sha256, terminal_sha256, selected_chain = _linear_chain(nodes)
    assert root_sha256 == chain_order[0]
    assert terminal_sha256 == chain_order[-1]
    assert selected_chain == chain_order


def test_three_generation_offline_bundle_chain_is_recoverable() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        bundles = root / "persistent-bundles"
        parent_latest, parent_sha = make_latest_run(
            root / "parent",
            as_of_date="2026-07-20",
            parent_acceptance_status="NO_PRIOR_STATE",
            parent_accepted_manifest_sha256="",
            event_numbers=[1],
        )
        parent_head = stage_fixture(
            bundles,
            latest=parent_latest,
            manifest_sha256=parent_sha,
        )
        child_one_latest, child_one_sha = make_latest_run(
            root / "child-one",
            as_of_date="2026-07-21",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **verified_parent_kwargs(parent_head),
            paper_snapshot_hash="e" * 64,
            paper_previous_snapshot_hash="b" * 64,
            paper_ancestor_snapshot_hashes=["b" * 64],
            event_numbers=[1, 2],
        )
        child_one_head = stage_fixture(
            bundles,
            latest=child_one_latest,
            manifest_sha256=child_one_sha,
        )
        child_two_latest, child_two_sha = make_latest_run(
            root / "child-two",
            as_of_date="2026-07-22",
            parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
            **verified_parent_kwargs(child_one_head),
            paper_snapshot_hash="f" * 64,
            paper_previous_snapshot_hash="e" * 64,
            paper_ancestor_snapshot_hashes=["e" * 64, "b" * 64],
            event_numbers=[1, 2, 3],
        )
        stage_fixture(
            bundles,
            latest=child_two_latest,
            manifest_sha256=child_two_sha,
        )
        assert {
            path.name
            for path in bundles.iterdir()
            if path.is_dir()
        } == {parent_sha, child_one_sha, child_two_sha}
        for manifest_sha256 in (
            parent_sha,
            child_one_sha,
            child_two_sha,
        ):
            assert verify_head(
                head_dir=bundles / manifest_sha256,
                expected_manifest_sha256=manifest_sha256,
            )["status"] == "VERIFIED_ACCEPTED_HEAD"
        selection = select_heads(heads_root=bundles)
        assert selection["chain_accepted_manifest_sha256s"] == [
            parent_sha,
            child_one_sha,
            child_two_sha,
        ]
        assert (
            selection["terminal_accepted_manifest_sha256"]
            == child_two_sha
        )


def main() -> None:
    tests = [
        test_normal_two_head_chain_verify_and_idempotent_stage,
        test_event_tamper_is_rejected_without_relying_on_folder_manifest,
        test_skipped_archive_allows_missing_empty_event_log,
        test_fork_is_rejected,
        test_orphan_is_rejected,
        test_child_parent_manifest_identity_must_match_actual_parent,
        test_child_parent_outcome_state_must_match_actual_parent,
        test_multiple_roots_are_rejected,
        test_source_identity_is_required,
        test_summary_size_attestation_is_reverified,
        test_promotion_gate_identity_must_match_attested_file,
        test_child_paper_snapshot_must_descend_from_parent_paper,
        test_child_paper_genesis_must_match_parent_paper,
        test_summary_event_type_counts_must_match_parsed_log,
        test_duplicate_event_id_is_rejected,
        test_missing_event_id_is_rejected,
        test_duplicate_event_json_key_is_rejected,
        test_unknown_event_type_is_rejected,
        test_hash_named_verify_rejects_extra_file_and_symlink,
        test_linear_chain_handles_more_than_recursion_limit,
        test_three_generation_offline_bundle_chain_is_recoverable,
    ]
    for test in tests:
        test()
    print(f"run287_risk_outcome_accepted_heads_smoke: {len(tests)} passed")


if __name__ == "__main__":
    main()
