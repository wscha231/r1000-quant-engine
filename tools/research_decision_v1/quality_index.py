"""Pure immutable-reference index transitions. No remote/local filesystem writes.

Storage and reviewer authorization remain caller responsibilities. Self-hashes
provide integrity, not proof of author identity or production approval.
"""
from __future__ import annotations
import copy
import re
from .data import digest, timestamp, validate_persistable_sources
from .quality import _closed, _require, _text

FIELDS = {"kind", "security_id", "data_kind", "observed_at", "cutoff", "path", "sha256", "source_sha",
          "source_ref", "merge_status", "status", "independent_review", "review_receipt_hash"}


def empty_index() -> dict:
    value = {"schema_version": "quality-research-index-v1", "artifact_resolution": "relative_to_index_commit", "companies": {}, "events": []}
    return {**value, "index_hash": digest(value)}


def advance_index(index: dict, event: dict, *, expected_parent_hash: str) -> dict:
    """Preserve failure visibility and do not promote executions to reviews."""
    body = {k: v for k, v in index.items() if k != "index_hash"}
    _require(index.get("index_hash") == digest(body) == expected_parent_hash, "index_parent_mismatch")
    _require(body.get("schema_version") == "quality-research-index-v1", "index_schema")
    _closed(event, FIELDS, "index_event_schema")
    validate_persistable_sources(event)
    _require(event["kind"] in {"review", "execution"}, "index_event_kind")
    _require(event["data_kind"] in {"REAL", "SYNTHETIC"}, "index_data_kind")
    _require(event["merge_status"] in {"unmerged", "merged", "local_only"}, "merge_status")
    _require(type(event["independent_review"]) is bool, "review_flag_type")
    for field in ("security_id", "path", "source_ref"):
        _text(event[field], "index_reference")
    _require(re.fullmatch(r"(?:US:[A-Z][A-Z0-9.\-]{0,9}|KR:[0-9]{6})", event["security_id"]) is not None,
             "index_security_identity")
    _require(re.fullmatch(r"[0-9a-f]{64}", event["sha256"]) is not None, "snapshot_hash")
    _require(re.fullmatch(r"[0-9a-f]{40}", event["source_sha"]) is not None, "source_commit")
    _require(event["path"].startswith("research/decision_v1/") and
             not any(x in {"", ".", ".."} for x in event["path"].split("/")) and "\\" not in event["path"], "snapshot_path")
    stamp = timestamp(event["observed_at"])
    _require(timestamp(event["cutoff"]) <= stamp, "event_before_cutoff")
    if event["kind"] == "review":
        _require(event["status"] in {"reviewed_complete", "reviewed_partial"}, "review_status")
        _require(isinstance(event["review_receipt_hash"], str) and
                 re.fullmatch(r"[0-9a-f]{64}", event["review_receipt_hash"]) is not None, "review_receipt_required")
    else:
        _require(event["status"] in {"success", "blocked", "failed"}, "execution_status")
        _require(event["review_receipt_hash"] is None, "execution_is_not_review")
    result = copy.deepcopy(body)
    event_hash = digest(event)
    if any(e["event_hash"] == event_hash for e in result["events"]):
        return copy.deepcopy(index)
    # Synthetic receipts cannot replace real reviewed or execution pointers.
    identity = event["data_kind"] + ":" + event["security_id"]
    entry = result["companies"].setdefault(identity, {"latest_reviewed_snapshot": None,
        "latest_execution_manifest": None, "latest_successful_execution_manifest": None})
    pointer = "latest_reviewed_snapshot" if event["kind"] == "review" else "latest_execution_manifest"
    previous = entry[pointer]
    if previous is not None:
        _require(stamp != timestamp(previous["observed_at"]), "ambiguous_same_time_event")
    if previous is None or stamp > timestamp(previous["observed_at"]):
        entry[pointer] = copy.deepcopy(event)
    if event["kind"] == "execution" and event["status"] == "success":
        prior_success = entry["latest_successful_execution_manifest"]
        if prior_success is None or stamp > timestamp(prior_success["observed_at"]):
            entry["latest_successful_execution_manifest"] = copy.deepcopy(event)
    result["events"].append({"event_hash": event_hash, "reference": copy.deepcopy(event)})
    result["index_hash"] = digest(result)
    return result
