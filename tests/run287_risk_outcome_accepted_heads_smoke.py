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


def test_legacy_migration_root_rejects_forgery_and_reuses_exact_head() -> None:
    """Entirely synthetic six-head state; no network, credentials or Drive."""
    import socket
    import shutil
    import unittest
    from unittest.mock import patch
    from tools import build_run287_risk_outcome_legacy_migration as migration
    from tools.build_run287_risk_outcome_parent_preflight import build_receipt
    from tests.run287_risk_outcome_parent_preflight_smoke import base_kwargs, PAPER_DATES
    from tests.run287_paper_ledger_transaction_smoke import ledger_args, prepare
    from tools.run_daily_simulated_fill_ledger import run as run_paper_ledger
    from tools import run287_paper_ledger_integrity as paper_integrity

    checks = unittest.TestCase()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
        socket.socket, "connect", side_effect=RuntimeError("network forbidden")
    ), patch.object(socket, "create_connection", side_effect=RuntimeError("network forbidden")):
        root = Path(tmp)
        kwargs = base_kwargs(root)
        shutil.move(root / "heads", root / "paper_heads")
        selection = paper_integrity.select_verified_immutable_paper_head(root / "paper_heads")
        Path(kwargs["paper_immutable_head_selection_path"]).write_bytes(migration.raw_json(selection))
        verifier = paper_integrity.build_integrity_verifier_receipt(
            root / "paper", immutable_head_selection=kwargs["paper_immutable_head_selection_path"])
        Path(kwargs["paper_integrity_verifier_receipt_path"]).write_bytes(
            paper_integrity.integrity_verifier_receipt_bytes(verifier))
        kwargs.update(event_name="workflow_dispatch", allow_quarantined_legacy_outcome_parent=True)
        receipt, code = build_receipt(**kwargs)
        checks.assertEqual(code, 0)
        evidence = {
            "preflight": migration.raw_json(receipt),
            "legacy_summary": kwargs["legacy_summary_path"].read_bytes(),
            "legacy_events": b"",
            "paper_selection": kwargs["paper_immutable_head_selection_path"].read_bytes(),
            "paper_verifier": kwargs["paper_integrity_verifier_receipt_path"].read_bytes(),
        }
        paper = receipt["observed_state"]["paper_ledger"]
        args = dict(evidence=evidence, paper_dir=root / "paper", code_sha=kwargs["source_commit_sha"])
        # The real fixed pins must reject the synthetic identities.
        with checks.assertRaisesRegex(ValueError, "reviewed_paper_identity_changed"):
            migration.construct(**args)
        with patch.object(migration, "PAPER_TERMINAL", paper["snapshot_hash"]), patch.object(
            migration, "PAPER_ROOT", paper["immutable_root_snapshot_hash"]
        ):
            digest = migration.build(**args, output=root / "build")
            head = root / "build/staged" / digest
            manifest = migration.verify(head=head, paper_dir=root / "paper", code_sha=args["code_sha"])
            checks.assertEqual(manifest["parent_acceptance_status"], "QUARANTINED_LEGACY")
            checks.assertEqual(manifest["outcome_chain"]["trusted_event_count"], 0)
            checks.assertEqual(manifest["as_of_date"], "2026-07-17")
            checks.assertEqual(manifest["migration"]["session_date"], kwargs["session_date"])
            for key in migration.FALSE_FLAGS:
                checks.assertIs(manifest[key], False)
                checks.assertIs(manifest["migration"]["gate"][key], False)
            staged = stage_head(latest_run=root / "build", expected_manifest_sha256=digest, output_dir=head)
            checks.assertEqual(staged["status"], "ALREADY_STAGED_EXACT_MATCH")
            checks.assertEqual(select_heads(heads_root=head.parent)["accepted_head_count"], 1)
            for field, value in (("satisfied", False), ("satisfied", 1),
                                 ("conflicting_authorization_requested", True),
                                 ("one_time_only", False), ("separate_user_approval_required", False),
                                 ("mode", "genesis"), ("required_input", "allow_risk_outcome_genesis_bootstrap")):
                changed = json.loads(evidence["preflight"])
                changed["authorization"][field] = value
                bad = {**evidence, "preflight": migration.raw_json(changed)}
                with checks.assertRaisesRegex(ValueError, "preflight_exact_recomputation_failed"):
                    migration.construct(**{**args, "evidence": bad})
            for key in ("legacy_summary", "legacy_events", "paper_verifier", "paper_selection"):
                with checks.assertRaises((ValueError, KeyError)):
                    migration.construct(**{**args, "evidence": {**evidence, key: evidence[key] + b"tamper"}})
            checks.assertEqual(migration.verify(
                head=head, paper_dir=root / "paper", code_sha="f" * 40), manifest)
            with checks.assertRaisesRegex(ValueError, "preflight_source_mismatch"):
                migration.construct(**{**args, "code_sha": "f" * 40})
            # A generic-manager-valid manifest with a changed migration binding is still divergent.
            divergent = json.loads((head / "manifest.json").read_bytes())
            divergent["migration"]["session_date"] = "2026-09-01"
            other_sha = migration.sha(migration.raw_json(divergent))
            other = root / "divergent" / other_sha
            import shutil
            shutil.copytree(head, other)
            (other / "manifest.json").write_bytes(migration.raw_json(divergent))
            with checks.assertRaisesRegex(ValueError, "migration_root_not_exact_reconstruction"):
                migration.verify(head=other, paper_dir=root / "paper", code_sha=args["code_sha"])
            producer_changed = json.loads((head / "manifest.json").read_bytes())
            producer_changed["source_identity"]["commit_sha"] = "f" * 40
            producer_sha = migration.sha(migration.raw_json(producer_changed))
            producer_head = root / "producer_changed" / producer_sha
            shutil.copytree(head, producer_head)
            (producer_head / "manifest.json").write_bytes(migration.raw_json(producer_changed))
            with checks.assertRaisesRegex(ValueError, "preflight_source_mismatch"):
                migration.verify(head=producer_head, paper_dir=root / "paper",
                                 code_sha="f" * 40)
            # Verify-only reruns emit their own immutable receipt, never another root.
            shutil.copytree(head, root / "accepted" / digest)
            shutil.copytree(root / "paper", root / "paper_current")
            shutil.copytree(root / "paper_heads", root / "paper_heads_current")
            (root / "legacy_current").mkdir()
            (root / "legacy_current/summary.json").write_bytes(evidence["legacy_summary"])
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch",
                                         "GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "2",
                                         "REQUESTED_SESSION_DATE": "2026-09-30"}), patch.object(
                sys, "argv", ["migration", "receipt", "--root", str(root), "--head", digest,
                              "--code-sha", args["code_sha"], "--before", "1"]
            ):
                checks.assertEqual(migration.main(), 0)
            receipts = list((root / "receipts").glob("*.json"))
            checks.assertEqual(len(receipts), 1)
            rerun = json.loads(receipts[0].read_bytes())
            checks.assertEqual(receipts[0].stem, migration.sha(receipts[0].read_bytes()))
            checks.assertEqual(rerun["status"], "IDEMPOTENT_VERIFY_ONLY")
            checks.assertEqual(rerun["before_committed_head_count"], 1)
            checks.assertEqual(rerun["after_committed_head_count"], 1)
            checks.assertEqual(rerun["expected_master_sha"], args["code_sha"])
            checks.assertEqual(rerun["observed_master_sha"], args["code_sha"])
            checks.assertEqual(rerun["reviewed_code_sha"], args["code_sha"])
            checks.assertEqual(rerun["migration_producer_sha"], args["code_sha"])
            checks.assertEqual(rerun["current_verifier_sha"], args["code_sha"])
            for field, key in (("paper_verifier_receipt_sha256", "paper_verifier"),
                               ("legacy_summary_sha256", "legacy_summary"),
                               ("legacy_event_log_sha256", "legacy_events"),
                               ("preflight_receipt_sha256", "preflight")):
                checks.assertEqual(rerun[field], sha256_bytes(evidence[key]))
            checks.assertEqual(list((root / "accepted").iterdir()), [root / "accepted" / digest])
            # A later current master reuses the original producer and head bytes.
            original_manifest = (head / "manifest.json").read_bytes()
            shutil.rmtree(root / "paper")
            shutil.rmtree(root / "paper_heads")
            checks.assertEqual(migration.prepare_recovery(root, "f" * 40), digest)
            checks.assertEqual((head / "manifest.json").read_bytes(), original_manifest)
            checks.assertEqual(migration.verify(
                head=head, paper_dir=root / "paper", code_sha="f" * 40), manifest)
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch",
                                         "GITHUB_RUN_ID": "1000", "GITHUB_RUN_ATTEMPT": "1",
                                         "REQUESTED_SESSION_DATE": "2026-09-30"}), patch.object(
                sys, "argv", ["migration", "receipt", "--root", str(root), "--head", digest,
                              "--code-sha", "f" * 40, "--before", "1"]
            ):
                checks.assertEqual(migration.main(), 0)
            later = next(json.loads(path.read_bytes()) for path in (root / "receipts").glob("*.json")
                         if json.loads(path.read_bytes())["workflow_run_id"] == "1000")
            checks.assertEqual(later["migration_producer_sha"], args["code_sha"])
            checks.assertEqual(later["current_verifier_sha"], "f" * 40)
            checks.assertEqual(later["before_committed_head_count"], 1)
            checks.assertEqual(later["after_committed_head_count"], 1)
            checks.assertEqual([path.name for path in (root / "accepted").iterdir()], [digest])
            def recover_with_current_state() -> None:
                shutil.rmtree(root / "paper")
                shutil.rmtree(root / "paper_heads")
                checks.assertEqual(migration.prepare_recovery(root, "f" * 40), digest)
                checks.assertEqual((head / "manifest.json").read_bytes(), original_manifest)

            # Paper may advance while the original migration remains the only outcome head.
            successor_run = root / "successor_run"
            shutil.copytree(root / "paper_current", successor_run / "paper")
            prepare(successor_run, [*PAPER_DATES, "2026-07-27"])
            checks.assertEqual(run_paper_ledger(ledger_args(
                successor_run, "2026-07-27", suppress_new_orders=True))["status"],
                "completed")
            successor = json.loads((successor_run / "paper/snapshot_integrity.json").read_bytes())
            successor_sha = successor["snapshot_hash"]
            shutil.copytree(successor_run / "paper",
                            root / "paper_heads_current" / successor_sha)
            shutil.copytree(successor_run / "paper", root / "paper_successor")
            # Interrupted publication: immutable P7 exists while mutable alias is still P6.
            recover_with_current_state()
            shutil.rmtree(root / "paper_current")
            shutil.copytree(successor_run / "paper", root / "paper_current")
            recover_with_current_state()

            # A later outcome head may advance the mutable legacy alias while paper stays P6.
            shutil.rmtree(root / "paper_current")
            shutil.copytree(root / "paper", root / "paper_current")
            shutil.rmtree(root / "paper_heads_current" / successor_sha)
            child_latest, _ = make_latest_run(
                root / "child_latest", as_of_date="2026-07-27",
                parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
                event_numbers=[1], paper_snapshot_hash=paper["snapshot_hash"],
                paper_previous_snapshot_hash=manifest["paper_snapshot"]["previous_snapshot_hash"],
                paper_ancestor_snapshot_hashes=manifest["paper_snapshot"]["ancestor_snapshot_hashes"],
                **verified_parent_kwargs(root / "accepted" / digest))
            child_manifest_path = child_latest / "run287_accepted_publication/manifest.json"
            child_manifest = json.loads(child_manifest_path.read_bytes())
            child_manifest["paper_snapshot"] = manifest["paper_snapshot"]
            write_json(child_manifest_path, child_manifest)
            child_sha = sha256_bytes(child_manifest_path.read_bytes())
            child = stage_fixture(root / "accepted", latest=child_latest,
                                  manifest_sha256=child_sha)
            # The exact quarantined predecessor may still be the mutable alias.
            recover_with_current_state()
            # R0 -> R1 committed while mutable alias still represents R0.
            root_head = root / "accepted" / digest
            shutil.copyfile(root_head / "run287_risk_outcome_archive/summary.json",
                            root / "legacy_current/summary.json")
            root_event = root_head / "run287_risk_outcome_archive/risk_outcome_events.jsonl"
            alias_event = root / "legacy_current/risk_outcome_events.jsonl"
            if root_event.is_file():
                shutil.copyfile(root_event, alias_event)
            else:
                alias_event.unlink(missing_ok=True)
            recover_with_current_state()
            shutil.copyfile(child / "run287_risk_outcome_archive/summary.json",
                            root / "legacy_current/summary.json")
            shutil.copyfile(child / "run287_risk_outcome_archive/risk_outcome_events.jsonl",
                            root / "legacy_current/risk_outcome_events.jsonl")
            recover_with_current_state()
            checks.assertEqual(migration.accepted_chain(root)[0]["accepted_head_count"], 2)

            # Both mutable aliases can advance, while recovery still uses P6/L0.
            shutil.rmtree(root / "paper_current")
            shutil.copytree(root / "paper_successor", root / "paper_current")
            shutil.copytree(root / "paper_successor", root / "paper_heads_current" / successor_sha)
            recover_with_current_state()
            checks.assertEqual(migration.verify(
                head=head, paper_dir=root / "paper", code_sha="f" * 40), manifest)
            checks.assertEqual(migration.inventory(
                digest + "/manifest.json\n" + child_sha + "/manifest.json"),
                sorted([digest, child_sha]))
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch",
                                         "GITHUB_RUN_ID": "1001", "GITHUB_RUN_ATTEMPT": "1",
                                         "REQUESTED_SESSION_DATE": "2026-09-30"}), patch.object(
                sys, "argv", ["migration", "receipt", "--root", str(root), "--head", digest,
                              "--code-sha", "f" * 40, "--before", "2"]
            ):
                checks.assertEqual(migration.main(), 0)
            advanced = next(json.loads(path.read_bytes()) for path in (root / "receipts").glob("*.json")
                            if json.loads(path.read_bytes())["workflow_run_id"] == "1001")
            checks.assertEqual((advanced["before_committed_head_count"],
                                advanced["after_committed_head_count"]), (2, 2))
            checks.assertEqual(advanced["migration_producer_sha"], args["code_sha"])
            checks.assertEqual(advanced["current_verifier_sha"], "f" * 40)

            # R0 -> R1 -> R2 committed while mutable alias still represents R1.
            successor_publication = json.loads(
                (root / "paper_successor/accepted_publication.json").read_bytes())
            successor_snapshot = {
                key: successor[key] for key in (
                    "snapshot_hash", "previous_snapshot_hash",
                    "ancestor_snapshot_hashes", "genesis_identity_sha256", "file_count")
            }
            successor_snapshot["transaction_mode"] = successor_publication["transaction_mode"]
            grand_latest, _ = make_latest_run(
                root / "grand_latest", as_of_date="2026-07-28",
                parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
                event_numbers=[1, 2], paper_snapshot_hash=successor_sha,
                paper_previous_snapshot_hash=successor["previous_snapshot_hash"],
                paper_ancestor_snapshot_hashes=successor["ancestor_snapshot_hashes"],
                **verified_parent_kwargs(child))
            grand_manifest_path = grand_latest / "run287_accepted_publication/manifest.json"
            grand_manifest = json.loads(grand_manifest_path.read_bytes())
            grand_manifest["paper_snapshot"] = successor_snapshot
            write_json(grand_manifest_path, grand_manifest)
            grand_sha = sha256_bytes(grand_manifest_path.read_bytes())
            grandchild = stage_fixture(root / "accepted", latest=grand_latest,
                                       manifest_sha256=grand_sha)
            recover_with_current_state()
            checks.assertEqual(migration.accepted_chain(root)[0]["accepted_head_count"], 3)

            # A fork/disconnect in accepted lineage still fails closed.
            sibling_latest, _ = make_latest_run(
                root / "sibling_latest", as_of_date="2026-07-29",
                parent_acceptance_status="VERIFIED_ACCEPTED_HEAD",
                event_numbers=[1, 3], paper_snapshot_hash=successor_sha,
                paper_previous_snapshot_hash=successor["previous_snapshot_hash"],
                paper_ancestor_snapshot_hashes=successor["ancestor_snapshot_hashes"],
                **verified_parent_kwargs(child))
            sibling_manifest_path = sibling_latest / "run287_accepted_publication/manifest.json"
            sibling_manifest = json.loads(sibling_manifest_path.read_bytes())
            sibling_manifest["paper_snapshot"] = successor_snapshot
            write_json(sibling_manifest_path, sibling_manifest)
            sibling_sha = sha256_bytes(sibling_manifest_path.read_bytes())
            sibling = stage_fixture(root / "accepted", latest=sibling_latest,
                                    manifest_sha256=sibling_sha)
            with checks.assertRaisesRegex(ValueError, "accepted_head_fork_detected"):
                migration.accepted_chain(root)
            shutil.rmtree(sibling)

            # Missing immutable ancestry, a non-descendant chain and bad aliases block.
            original_legacy_alias = (root / "legacy_current/summary.json").read_bytes()
            (root / "legacy_current/summary.json").write_bytes(b"changed")
            with checks.assertRaisesRegex(ValueError, "current_legacy_alias_not_in_accepted_lineage"):
                migration.current_state(
                    root, migration.accepted_chain(root)[0], manifest, evidence)
            (root / "legacy_current/summary.json").write_bytes(original_legacy_alias)
            (root / "legacy_current/summary.json").unlink()
            with checks.assertRaisesRegex(ValueError, "evidence_not_regular"):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            (root / "legacy_current/summary.json").write_bytes(original_legacy_alias)

            # Alias identity must have a physically present immutable head.
            saved_alias_head = root / "saved_alias_head"
            shutil.move(root / "paper_heads_current" / successor_sha, saved_alias_head)
            with checks.assertRaisesRegex(ValueError, "current_paper_alias_not_in_immutable_chain"):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            shutil.move(saved_alias_head, root / "paper_heads_current" / successor_sha)

            # Corrupted mutable alias bytes fail physical integrity verification.
            alias_fixture = root / "paper_current/h1_fixture/file_000.json"
            alias_fixture_raw = alias_fixture.read_bytes()
            alias_fixture.write_bytes(b"{}")
            with checks.assertRaises(Exception):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            alias_fixture.write_bytes(alias_fixture_raw)

            # A physically valid alias older than the migration P6 snapshot is stale.
            shutil.rmtree(root / "paper_current")
            stale_digest = selection["chain_snapshot_hashes"][-2]
            shutil.copytree(root / "paper_heads_current" / stale_digest,
                            root / "paper_current")
            with checks.assertRaisesRegex(ValueError, "current_paper_alias_predates_migration_snapshot"):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            shutil.rmtree(root / "paper_current")
            shutil.copytree(root / "paper_successor", root / "paper_current")

            saved_middle = root / "saved_middle"
            shutil.move(root / "paper_heads_current" / selection["chain_snapshot_hashes"][2],
                        saved_middle)
            with checks.assertRaises(Exception):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            shutil.move(saved_middle, root / "paper_heads_current" / selection["chain_snapshot_hashes"][2])
            saved_terminal = root / "saved_terminal"
            saved_successor = root / "saved_successor"
            shutil.move(root / "paper_heads_current" / paper["snapshot_hash"], saved_terminal)
            shutil.move(root / "paper_heads_current" / successor_sha, saved_successor)
            shutil.rmtree(root / "paper_current")
            shutil.copytree(root / "paper_heads_current" / selection["chain_snapshot_hashes"][-2],
                            root / "paper_current")
            with checks.assertRaisesRegex(ValueError, "current_paper_chain_not_original_descendant"):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            shutil.move(saved_terminal, root / "paper_heads_current" / paper["snapshot_hash"])
            shutil.move(saved_successor, root / "paper_heads_current" / successor_sha)
            shutil.rmtree(root / "paper_current")
            shutil.copytree(root / "paper_successor", root / "paper_current")
            (root / "paper_current/snapshot_integrity.json").unlink()
            with checks.assertRaises(Exception):
                migration.current_state(root, migration.accepted_chain(root)[0], manifest, evidence)
            shutil.copyfile(root / "paper_successor/snapshot_integrity.json",
                            root / "paper_current/snapshot_integrity.json")
            # A historical paper file change invalidates the root even with saved verifier.
            (root / "paper/h1_fixture/file_000.json").write_text("{}")
            with checks.assertRaises(ValueError):
                migration.verify(head=head, paper_dir=root / "paper", code_sha=args["code_sha"])
    checks.assertEqual(migration.inventory(""), [])
    valid = "a" * 64 + "/manifest.json"
    checks.assertEqual(migration.inventory(valid), ["a" * 64])
    checks.assertEqual(migration.inventory(valid + "\n" + "b" * 64 + "/manifest.json"),
                       ["a" * 64, "b" * 64])
    with checks.assertRaisesRegex(ValueError, "uncommitted_remote_head_requires_recovery"):
        migration.inventory(valid + "\n" + "b" * 64 + "/manifest.json\n" +
                            "c" * 64 + "/run287_risk_outcome_archive/summary.json")
    for raw in (valid + "\n" + valid,
                "a" * 64 + "/run287_risk_outcome_archive/summary.json", "unknown/manifest.json",
                valid + "\n" + "a" * 64 + "/unexpected.json"):
        with checks.assertRaises(ValueError):
            migration.inventory(raw)


def main() -> None:
    tests = [
        test_legacy_migration_root_rejects_forgery_and_reuses_exact_head,
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
