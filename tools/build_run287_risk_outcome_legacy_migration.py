#!/usr/bin/env python3
"""Local-only #509 quarantined root construction and exact readback verification.

No network or Drive client is available here. The dispatch workflow owns remote
discovery and manifest-last persistence under the daily workflow concurrency lock.
Original evidence bytes live inside the manifest because the existing immutable
head manager intentionally permits only manifest, summary and event-log files.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_risk_outcome_parent_preflight as preflight
from tools.build_run287_risk_outcome_parent_anchor import build_anchor
from tools import manage_run287_risk_outcome_accepted_heads as heads

PAPER_TERMINAL = "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7"
PAPER_ROOT = "f904fa6bd1d4280f688f99b4562837e48ad196942f75a3b9ad0b2aeb917709a3"
LEGACY_SHA = "5a57e4becef19668dce45803eb77185bc6c60bcf9b58522df939e9a48a56654c"
WORKFLOW = "run287_risk_outcome_legacy_migration.yml"
FALSE_FLAGS = tuple(sorted(set(heads.MANIFEST_FALSE_SAFETY_FIELDS +
    heads.OUTCOME_FALSE_SAFETY_FIELDS + (
        "paper_ledger_mutated", "paper_fill_generated", "broker_order_generated",
        "alpha_logic_changed", "score_changed", "risk_threshold_changed",
        "champion_promoted", "automatic_promotion_allowed", "ledger_mutated",
    ))))


def raw_json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def read(path: Path) -> bytes:
    require(path.is_file() and not path.is_symlink(), "evidence_not_regular")
    return path.read_bytes()


def obj(raw: bytes) -> dict:
    return preflight.strict_json_object(raw, label="migration_evidence")


def envelope() -> dict:
    return {"review_only": True, "lineage_repair_only": True,
            **{key: False for key in FALSE_FLAGS}}


def inventory(raw: str) -> list[str]:
    """Strict recursive files-only remote inventory; duplicates are not hidden."""
    paths = raw.splitlines()
    require(len(paths) == len(set(paths)), "duplicate_remote_path")
    allowed = {"manifest.json", heads.SUMMARY_RELATIVE_PATH.as_posix(),
               heads.EVENT_LOG_RELATIVE_PATH.as_posix()}
    for path in paths:
        parts = path.split("/", 1)
        require(len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0])
                and parts[1] in allowed, "unexpected_remote_file")
    committed = sorted(path.split("/")[0] for path in paths
                       if path.endswith("/manifest.json"))
    require(len(committed) <= 1, "multiple_accepted_heads")
    require(all(path.split("/")[0] in committed for path in paths),
            "uncommitted_remote_head_requires_recovery")
    return committed


def construct(evidence: dict[str, bytes], paper_dir: Path, code_sha: str) -> tuple[dict, bytes]:
    """Recompute the preflight from exact evidence and verified local paper state."""
    require(re.fullmatch(r"[0-9a-f]{40}", code_sha) is not None, "code_sha_invalid")
    receipt = obj(evidence["preflight"])
    expected_authorization = {
        "mode": "legacy_quarantine", "required_event_name": "workflow_dispatch",
        "required_input": "allow_quarantined_legacy_outcome_parent", "requested": True,
        "conflicting_authorization_requested": False, "satisfied": True,
        "one_time_only": True, "separate_user_approval_required": True,
    }
    require(raw_json(receipt.get("authorization", {})) == raw_json(expected_authorization),
            "preflight_exact_recomputation_failed")
    source = receipt["source"]
    require(source["source_commit_sha"] == code_sha and
            source["event_name"] == "workflow_dispatch", "preflight_source_mismatch")
    require(sha(evidence["legacy_summary"]) == LEGACY_SHA, "legacy_hash_mismatch")
    require(evidence["legacy_events"] == b"", "legacy_events_not_empty")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for key, raw in evidence.items():
            (root / key).write_bytes(raw)
        expected, exit_code = preflight.build_receipt(
            **source, remote_head_discovery_confirmed=True,
            remote_committed_head_count=0, remote_legacy_outcome_state="PRESENT_FETCHED",
            legacy_summary_path=root / "legacy_summary",
            legacy_event_log_path=root / "legacy_events",
            paper_integrity_path=paper_dir / "snapshot_integrity.json",
            paper_integrity_verifier_receipt_path=root / "paper_verifier",
            paper_immutable_head_selection_path=root / "paper_selection",
            allow_risk_outcome_genesis_bootstrap=False,
            allow_quarantined_legacy_outcome_parent=True,
            generated_at_utc=receipt["generated_at_utc"],
        )
        # Exact bytes reject integer booleans, missing fields and forged READY labels.
        require(exit_code == 0 and raw_json(expected) == evidence["preflight"],
                "preflight_exact_recomputation_failed")
        require(expected["status"] == "READY_ONE_TIME_LEGACY_QUARANTINE",
                "preflight_not_legacy_ready")
        anchor = build_anchor(root / "legacy_summary", root / "legacy_events",
                              allow_quarantined_legacy_parent=True,
                              now_utc=receipt["generated_at_utc"])
    paper = expected["observed_state"]["paper_ledger"]
    require(paper["snapshot_hash"] == PAPER_TERMINAL and
            paper["immutable_terminal_snapshot_hash"] == PAPER_TERMINAL and
            paper["immutable_root_snapshot_hash"] == PAPER_ROOT and
            paper["immutable_head_count"] == 6 and paper["as_of_date"] == "2026-07-24",
            "reviewed_paper_identity_changed")
    require(source["session_date"] >= paper["as_of_date"], "session_precedes_paper")
    # This is a lineage repair at the legacy date, not a completed economic session.
    as_of = anchor["parent_as_of_date"]
    chain = {key: anchor[key] for key in (
        "parent_summary_sha256", "parent_summary_bytes", "parent_event_log_sha256",
        "parent_event_log_bytes", "parent_event_count", "parent_as_of_date",
        "carried_quarantined_prefix_event_count", "parent_acceptance_status",
        "parent_accepted_manifest_sha256", "parent_accepted_manifest_bytes",
        "parent_accepted_manifest_as_of_date")}
    chain.update(schema_version=heads.OUTCOME_CHAIN_SCHEMA, status="VERIFIED_APPEND_ONLY",
                 parent_anchor_status=anchor["status"], parent_anchor_sha256=sha(raw_json(anchor)),
                 current_event_log_sha256=sha(b""), current_event_log_bytes=0,
                 current_event_count=0, current_as_of_date=as_of,
                 exact_parent_prefix_verified=True, append_only_verified=True, trusted_event_count=0)
    summary = {"schema_version": heads.OUTCOME_ARCHIVE_SCHEMA,
               "status": "SKIPPED_NO_DECISION_OBSERVATIONS", "as_of_date": as_of,
               "blockers": [], "signal_observation_count": 0, "forward_outcome_event_count": 0,
               "outcome_chain": chain, **envelope()}
    summary_raw = raw_json(summary)
    gate = {"schema_version": "run287-legacy-migration-only-gate-v1", **envelope()}
    paper_manifest = obj(read(paper_dir / "snapshot_integrity.json"))
    snapshot = {key: paper_manifest[key] for key in (
        "snapshot_hash", "previous_snapshot_hash", "ancestor_snapshot_hashes",
        "genesis_identity_sha256", "file_count")}
    accepted_paper = obj(read(paper_dir / "accepted_publication.json"))
    require(accepted_paper.get("schema_version") == "run287-paper-accepted-publication-v1"
            and accepted_paper.get("as_of_date") == paper["as_of_date"]
            and accepted_paper.get("transaction_mode") in heads.PAPER_TRANSACTION_MODES,
            "paper_publication_identity_invalid")
    snapshot["transaction_mode"] = accepted_paper["transaction_mode"]
    manifest = {
        "schema_version": heads.ACCEPTED_MANIFEST_SCHEMA, "status": heads.ACCEPTED_MANIFEST_STATUS,
        "as_of_date": as_of, "outcome_status": summary["status"], "outcome_chain": chain,
        "paper_snapshot": snapshot, "parent_acceptance_status": "QUARANTINED_LEGACY",
        "source_identity": {"commit_sha": code_sha, "workflow": WORKFLOW,
                            "run_id": source["source_run_id"], "run_attempt": source["source_run_attempt"],
                            "promotion_gate_sha256": sha(raw_json(gate))},
        "files": {
            "risk_outcome_summary": {"path": heads.SUMMARY_RELATIVE_PATH.as_posix(),
                                     "sha256": sha(summary_raw), "bytes": len(summary_raw)},
            "risk_outcome_event_log": {"path": heads.EVENT_LOG_RELATIVE_PATH.as_posix(),
                                       "sha256": sha(b""), "bytes": 0},
            "promotion_gate": {"path": heads.PROMOTION_GATE_RELATIVE_PATH.as_posix(),
                               "sha256": sha(raw_json(gate)), "bytes": len(raw_json(gate))}},
        "migration": {"schema_version": "run287-legacy-migration-root-v1",
                      "expected_master_sha": code_sha, "current_master_sha": code_sha,
                      "reviewed_code_sha": code_sha, "session_date": source["session_date"],
                      "paper_identity": paper, "parent_anchor": anchor, "gate": gate,
                      "evidence": {key: {"sha256": sha(raw), "bytes": len(raw),
                                         "base64": base64.b64encode(raw).decode()}
                                   for key, raw in evidence.items()}},
        **envelope(),
    }
    return manifest, summary_raw


def build(*, evidence: dict[str, bytes], paper_dir: Path, code_sha: str, output: Path) -> str:
    manifest, summary = construct(evidence, paper_dir, code_sha)
    digest = sha(raw_json(manifest))
    for path, raw in ((output / "run287_accepted_publication/manifest.json", raw_json(manifest)),
                      (output / heads.SUMMARY_RELATIVE_PATH, summary),
                      (output / heads.EVENT_LOG_RELATIVE_PATH, b""),
                      (output / heads.PROMOTION_GATE_RELATIVE_PATH, raw_json(manifest["migration"]["gate"]))):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
    heads.stage_head(latest_run=output, expected_manifest_sha256=digest,
                     output_dir=output / "staged" / digest)
    return digest


def verify(*, head: Path, paper_dir: Path, code_sha: str) -> dict:
    heads.verify_head(head_dir=head, expected_manifest_sha256=head.name)
    raw = read(head / "manifest.json")
    manifest = obj(raw)
    evidence = {}
    for key, record in manifest["migration"]["evidence"].items():
        value = base64.b64decode(record["base64"], validate=True)
        require(sha(value) == record["sha256"] and len(value) == record["bytes"],
                "embedded_evidence_hash_mismatch")
        evidence[key] = value
    require(set(evidence) == {"preflight", "legacy_summary", "legacy_events",
                              "paper_selection", "paper_verifier"}, "evidence_set_invalid")
    expected, summary = construct(evidence, paper_dir, code_sha)
    require(raw_json(expected) == raw and read(head / heads.SUMMARY_RELATIVE_PATH) == summary,
            "migration_root_not_exact_reconstruction")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inventory", "build", "verify", "receipt"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--code-sha", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--before", type=int, choices=(0, 1))
    args = parser.parse_args()
    root = args.root
    if args.mode == "inventory":
        found = inventory(root.read_text())
        print(found[0] if found else "EMPTY")
        return 0
    if args.mode == "build":
        evidence = {key: read(root / filename) for key, filename in {
            "preflight": "preflight.json", "legacy_summary": "legacy/summary.json",
            "paper_selection": "selection.json", "paper_verifier": "verifier.json"}.items()}
        event = root / "legacy/risk_outcome_events.jsonl"
        evidence["legacy_events"] = read(event) if event.exists() or event.is_symlink() else b""
        print(build(evidence=evidence, paper_dir=root / "paper", code_sha=args.code_sha,
                    output=root / "build"))
        return 0
    require(re.fullmatch(r"[0-9a-f]{64}", args.head) is not None, "head_invalid")
    selection = heads.select_heads(heads_root=root / "accepted")
    require(selection["accepted_head_count"] == 1 and
            selection["selected_accepted_manifest_sha256"] == args.head, "readback_graph_changed")
    manifest = verify(head=root / "accepted" / args.head, paper_dir=root / "paper",
                      code_sha=args.code_sha)
    current_legacy = read(root / "legacy/summary.json")
    current_events_path = root / "legacy/risk_outcome_events.jsonl"
    current_events = (read(current_events_path)
                      if current_events_path.exists() or current_events_path.is_symlink() else b"")
    require(sha(current_legacy) == LEGACY_SHA and current_events == b"",
            "current_legacy_identity_changed")
    if args.mode == "receipt":
        require(args.before in (0, 1), "before_count_required")
        require(os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch", "event_invalid")
        binding = manifest["migration"]
        receipt = {"schema_version": "run287-legacy-migration-receipt-v1",
                   "status": "PERSISTED_READBACK_VERIFIED" if args.before == 0 else "IDEMPOTENT_VERIFY_ONLY",
                   "workflow_run_id": os.environ["GITHUB_RUN_ID"],
                   "workflow_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                   "event_name": os.environ["GITHUB_EVENT_NAME"],
                   "expected_master_sha": args.code_sha, "current_master_sha": args.code_sha,
                   "reviewed_code_sha": args.code_sha,
                   "session_date": os.environ["REQUESTED_SESSION_DATE"],
                   "migration_session_date": binding["session_date"],
                   "paper_terminal": PAPER_TERMINAL, "paper_root": PAPER_ROOT,
                   "evidence_hashes": {key: value["sha256"] for key, value in binding["evidence"].items()},
                   "preflight_status": "READY_ONE_TIME_LEGACY_QUARANTINE",
                   "accepted_manifest_sha256": args.head,
                   "before_committed_head_count": args.before, "after_committed_head_count": 1,
                   "readback_verification_status": "VERIFIED_ACCEPTED_HEAD", **envelope()}
        raw = raw_json(receipt)
        destination = root / "receipts" / (sha(raw) + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
