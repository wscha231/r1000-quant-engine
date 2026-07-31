#!/usr/bin/env python3
"""Persist exact-close OHLCV pattern observations and forward outcomes.

This is a research-only sidecar.  It records descriptive return-transition
fingerprints and resolves them only from an exact archived NYSE target session.
It cannot write portfolio targets, orders, cash, or champion state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_holding_risk_watch import (  # noqa: E402
    sha256_file,
)


SCHEMA_VERSION = "run287-ohlcv-pattern-memory-v1"
READY_STATUS = "READY_OHLCV_PATTERN_MEMORY_RESEARCH_ONLY"
BLOCKED_STATUS = "BLOCKED_OHLCV_PATTERN_MEMORY"
OBSERVATION_SCHEMA_VERSION = "run287-ohlcv-pattern-observation-v1"
OUTCOME_SCHEMA_VERSION = "run287-ohlcv-pattern-outcome-v1"
ACCEPTED_HEAD_SCHEMA_VERSION = "run287-ohlcv-pattern-accepted-head-v1"
ACCEPTED_HEAD_STATUS = "ACCEPTED_OHLCV_PATTERN_MEMORY_HEAD"
RECOVERY_EVIDENCE_SCHEMA_VERSION = (
    "run287-ohlcv-pattern-recovery-evidence-v1"
)
RECOVERY_EVIDENCE_STATUS = "IMMUTABLE_PATTERN_RECOVERY_EVIDENCE"
PINNED_CONTRACT_SHA256 = (
    "30c1e17224d68f5d006ca4da5fd403f31037efb3c1b7871918fed50329c16202"
)

FEATURE_FIELDS = (
    "prior_return_1d",
    "return_1d",
    "return_2d",
    "return_transition_signature",
    "prior_down_current_up",
    "return_transition_sessions_consecutive",
    "return_transition_session_dates",
    "return_transition_data_reason",
    "historical_replay_materialized",
    "prior_loss_recovery_fraction",
    "gap_return",
    "intraday_return",
    "close_location_in_bar",
    "true_range_atr14",
    "prior_true_range_atr14",
    "atr14_pct",
    "realized_vol_20d",
    "realized_vol_63d",
    "realized_vol_ratio_20d_63d",
    "realized_vol_20d_past_percentile",
    "volume_z_20d_past_only",
    "volume_ratio_20d_past_only",
    "return_5d",
    "return_21d",
    "return_63d",
    "return_126d",
    "return_252d",
    "above_ma20",
    "above_ma50",
    "above_ma200",
    "location_state",
    "range_21d_position",
    "range_63d_position",
    "range_126d_position",
    "range_252d_position",
    "vix_level",
    "vix_return_1d",
    "vix_z_63d",
    "vix_past_percentile",
    "market_risk_off_confirmed",
    "index_damage_confirmed",
    "is_held",
    "is_current_selector",
    "is_proposed_entry",
    "portfolios",
    "marked_weight_max",
    "advisory_weight_max",
    "shadow_action",
    "shadow_reason_codes",
    "data_reason",
)
OBSERVATION_RETRY_PROVENANCE_FIELDS = {
    "available_from",
    "observation_accepted_at_utc",
    "source_summary_sha256",
    "source_observations_sha256",
    "source_benchmark_sha256",
}
OUTCOME_RETRY_PROVENANCE_FIELDS = {
    "source_summary_sha256",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_clean(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(nested) for nested in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite(value)
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        json_clean(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def sha256_prefixes(
    path: Path,
    byte_counts: Iterable[int],
) -> dict[int, str]:
    boundaries = sorted({int(value) for value in byte_counts})
    if any(value < 0 for value in boundaries):
        raise ValueError(f"accepted head prefix length invalid:{path}")
    digest = hashlib.sha256()
    results: dict[int, str] = {}
    if not boundaries:
        return results
    if boundaries[-1] > 0 and not path.is_file():
        raise ValueError(f"accepted head prefix file missing:{path}")
    position = 0
    if boundaries[-1] == 0:
        return {0: digest.hexdigest()}
    with path.open("rb") as handle:
        for boundary in boundaries:
            remaining = boundary - position
            while remaining > 0:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError(
                        f"accepted head prefix truncated:{path}"
                    )
                digest.update(block)
                position += len(block)
                remaining -= len(block)
            results[boundary] = digest.hexdigest()
    return results


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            timeout=10,
        ).strip()
    except Exception:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required:{path}")
    return payload


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with staged.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def json_document_text(payload: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            json_clean(dict(payload)),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(path, json_document_text(payload))


def anticipated_json_fingerprint(
    path: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    encoded = json_document_text(payload).encode("utf-8")
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def atomic_copy_verified(
    source: Path,
    destination: Path,
    expected_sha256: str,
) -> None:
    if sha256_file(source) != expected_sha256:
        raise ValueError(f"recovery evidence source changed:{source}")
    if source.resolve() == destination.resolve():
        return
    if destination.is_file():
        if sha256_file(destination) != expected_sha256:
            raise ValueError(f"immutable recovery evidence mismatch:{destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as read_handle, staged.open("wb") as write_handle:
            for chunk in iter(lambda: read_handle.read(1024 * 1024), b""):
                write_handle.write(chunk)
            write_handle.flush()
            os.fsync(write_handle.fileno())
        if sha256_file(staged) != expected_sha256:
            raise ValueError(f"recovery evidence copy mismatch:{destination}")
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def persist_recovery_evidence(
    *,
    memory_dir: Path,
    valuation_date: str,
    contract_sha256: str,
    source_paths: Mapping[str, Path],
    sources: Mapping[str, Mapping[str, Any]],
) -> tuple[Path, Path]:
    records: dict[str, dict[str, Any]] = {}
    filenames: set[str] = set()
    for label, source_path in source_paths.items():
        source_audit = sources.get(label) or {}
        filename = source_path.name
        expected_sha256 = str(source_audit.get("sha256") or "")
        if (
            not filename
            or filename in filenames
            or not expected_sha256
            or source_path.is_file() is not True
        ):
            raise ValueError(f"recovery evidence source invalid:{label}")
        filenames.add(filename)
        records[label] = {
            "filename": filename,
            "bytes": int(source_path.stat().st_size),
            "sha256": expected_sha256,
        }
    base = {
        "schema_version": RECOVERY_EVIDENCE_SCHEMA_VERSION,
        "status": RECOVERY_EVIDENCE_STATUS,
        "session_date": valuation_date,
        "memory_contract_sha256": contract_sha256,
        "files": records,
    }
    bundle_id = canonical_hash(base)
    bundle_dir = (
        memory_dir
        / "recovery_evidence"
        / valuation_date.replace("-", "")
        / bundle_id
    )
    for label, source_path in source_paths.items():
        record = records[label]
        atomic_copy_verified(
            source_path,
            bundle_dir / str(record["filename"]),
            str(record["sha256"]),
        )
    payload = {**base, "bundle_id": bundle_id}
    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.is_file():
        if read_json(manifest_path) != payload:
            raise ValueError(
                f"immutable recovery evidence manifest mismatch:{manifest_path}"
            )
    else:
        atomic_write_json(manifest_path, payload)
    return bundle_dir / source_paths["timing_summary"].name, manifest_path


def select_recovery_evidence_summary(
    *,
    memory_dir: Path,
    session_date: str,
    expected_summary_sha256: str = "",
    accepted_summary_sha256s: Iterable[str] = (),
    required_endpoint_payload_sha256s: Iterable[str] = (),
    required_observation_payload_sha256s: Iterable[str] = (),
    contract_sha256: str,
) -> Path:
    matches: list[tuple[Path, str]] = []
    accepted_summary_hashes = {
        str(value)
        for value in accepted_summary_sha256s
        if value
    }
    if expected_summary_sha256:
        accepted_summary_hashes.add(expected_summary_sha256)
    required_endpoint_hashes = {
        str(value)
        for value in required_endpoint_payload_sha256s
        if value
    }
    required_observation_hashes = {
        str(value)
        for value in required_observation_payload_sha256s
        if value
    }
    if (
        not accepted_summary_hashes
        and not required_endpoint_hashes
        and not required_observation_hashes
    ):
        raise ValueError("recovery evidence provenance required")
    session_root = (
        memory_dir / "recovery_evidence" / session_date.replace("-", "")
    )
    for manifest_path in sorted(session_root.glob("*/manifest.json")):
        payload = read_json(manifest_path)
        bundle_id = str(payload.get("bundle_id") or "")
        base = {
            str(key): value
            for key, value in payload.items()
            if key != "bundle_id"
        }
        if (
            payload.get("schema_version")
            != RECOVERY_EVIDENCE_SCHEMA_VERSION
            or payload.get("status") != RECOVERY_EVIDENCE_STATUS
            or payload.get("session_date") != session_date
            or payload.get("memory_contract_sha256") != contract_sha256
            or not bundle_id
            or manifest_path.parent.name != bundle_id
            or canonical_hash(base) != bundle_id
        ):
            raise ValueError(
                f"immutable recovery evidence manifest invalid:{manifest_path}"
            )
        files = payload.get("files") or {}
        if set(files) != {
            "timing_summary",
            "timing_observations",
            "timing_benchmark",
            "timing_outcome_endpoints",
        }:
            raise ValueError(
                f"recovery evidence file set invalid:{manifest_path}"
            )
        filenames: set[str] = set()
        for label, raw_record in files.items():
            record = raw_record or {}
            filename = str(record.get("filename") or "")
            path = manifest_path.parent / filename
            expected_sha = str(record.get("sha256") or "")
            if (
                not filename
                or Path(filename).name != filename
                or filename in filenames
                or not expected_sha
                or not path.is_file()
                or record.get("bytes") is None
                or int(record["bytes"]) != path.stat().st_size
                or sha256_file(path) != expected_sha
            ):
                raise ValueError(
                    f"recovery evidence file invalid:{label}:{path}"
                )
            filenames.add(filename)
        summary_record = files["timing_summary"]
        summary_matches = bool(
            not accepted_summary_hashes
            or str(summary_record.get("sha256") or "")
            in accepted_summary_hashes
        )
        endpoint_record = files["timing_outcome_endpoints"]
        endpoint_path = (
            manifest_path.parent
            / str(endpoint_record.get("filename") or "")
        )
        candidate_endpoint_hashes = {
            canonical_hash(row)
            for row in read_jsonl(endpoint_path)
        }
        observations_record = files["timing_observations"]
        observations_path = (
            manifest_path.parent
            / str(observations_record.get("filename") or "")
        )
        benchmark_record = files["timing_benchmark"]
        benchmark_path = (
            manifest_path.parent
            / str(benchmark_record.get("filename") or "")
        )
        summary_path = (
            manifest_path.parent
            / str(summary_record.get("filename") or "")
        )
        candidate_observation_hashes = {
            canonical_hash(event_comparison_payload(row))
            for row in source_observations(
                valuation_date=session_date,
                summary=read_json(summary_path),
                security_rows=read_jsonl(observations_path),
                benchmark_rows=pd.read_csv(
                    benchmark_path,
                    low_memory=False,
                ).to_dict("records"),
                contract_sha256=contract_sha256,
                source_summary_sha256=str(
                    summary_record.get("sha256") or ""
                ),
                source_observations_sha256=str(
                    observations_record.get("sha256") or ""
                ),
                source_benchmark_sha256=str(
                    benchmark_record.get("sha256") or ""
                ),
            )
        }
        endpoint_matches = bool(
            not required_endpoint_hashes
            or required_endpoint_hashes.issubset(
                candidate_endpoint_hashes
            )
        )
        observation_matches = bool(
            not required_observation_hashes
            or required_observation_hashes.issubset(
                candidate_observation_hashes
            )
        )
        if summary_matches and endpoint_matches and observation_matches:
            matches.append((
                summary_path,
                canonical_hash(
                    {
                        "endpoint_payload_sha256s": sorted(
                            candidate_endpoint_hashes
                        ),
                        "observation_payload_sha256s": sorted(
                            candidate_observation_hashes
                        ),
                    }
                ),
            ))
    if len(matches) > 1:
        recovery_signatures = {signature for _, signature in matches}
        if len(recovery_signatures) == 1:
            return sorted(path for path, _ in matches)[0]
    if len(matches) != 1:
        raise ValueError(
            "recovery evidence summary match count:"
            f"{session_date}:{sorted(accepted_summary_hashes)}:"
            f"{len(matches)}"
        )
    return matches[0][0]


def resolve_output(
    summary_path: Path,
    summary: Mapping[str, Any],
    key: str,
) -> tuple[Path, dict[str, Any]]:
    record = (summary.get("outputs") or {}).get(key) or {}
    raw = str(record.get("path") or "")
    path = Path(raw)
    if raw and not path.is_absolute():
        path = summary_path.parent / path
    elif (
        raw
        and path.is_absolute()
        and "recovery_evidence" in summary_path.parts
        and (summary_path.parent / path.name).is_file()
    ):
        # The original summary bytes (and therefore its source identity) stay
        # immutable.  A later runner may have a different absolute workspace,
        # so use the content-addressed sibling copy only after hash validation.
        path = summary_path.parent / path.name
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "").lower()
    audit.update(expected_sha256=expected, hash_matches=audit["sha256"] == expected)
    if not expected or audit["exists"] is not True or audit["hash_matches"] is not True:
        raise ValueError(f"source output fingerprint mismatch:{key}")
    return path, audit


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL object required:{path}:{line_number}")
        rows.append(payload)
    return rows


def event_without_chain(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in row.items()
        if key not in {"previous_event_hash", "event_hash"}
    }


def stable_source_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in row.items()
        if key not in {"available_from", "observation_accepted_at_utc"}
    }


def event_comparison_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = event_without_chain(row)
    if payload.get("schema_version") == OBSERVATION_SCHEMA_VERSION:
        payload = {
            key: value
            for key, value in payload.items()
            if key not in OBSERVATION_RETRY_PROVENANCE_FIELDS
        }
    elif payload.get("schema_version") == OUTCOME_SCHEMA_VERSION:
        payload = {
            key: value
            for key, value in payload.items()
            if key not in OUTCOME_RETRY_PROVENANCE_FIELDS
        }
    return payload


def validate_chain(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_schema: str,
    contract_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    accepted: list[dict[str, Any]] = []
    identities: dict[str, dict[str, Any]] = {}
    previous = ""
    for index, raw in enumerate(rows):
        row = dict(raw)
        if str(row.get("schema_version") or "") != expected_schema:
            raise ValueError(f"archive schema drift:{index}")
        if str(row.get("memory_contract_sha256") or "") != contract_sha256:
            raise ValueError(f"archive contract drift:{index}")
        identity = str(row.get("event_id") or "")
        if not identity or identity in identities:
            raise ValueError(f"archive event identity invalid:{index}")
        if str(row.get("previous_event_hash") or "") != previous:
            raise ValueError(f"archive chain parent mismatch:{index}")
        expected_hash = canonical_hash(
            {**event_without_chain(row), "previous_event_hash": previous}
        )
        if str(row.get("event_hash") or "") != expected_hash:
            raise ValueError(f"archive event hash mismatch:{index}")
        accepted.append(row)
        identities[identity] = row
        previous = expected_hash
    return accepted, identities, previous


def attach_chain(
    row: Mapping[str, Any],
    previous_event_hash: str,
) -> dict[str, Any]:
    payload = {
        **json_clean(dict(row)),
        "previous_event_hash": previous_event_hash,
    }
    payload["event_hash"] = canonical_hash(payload)
    return payload


def append_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    payloads = list(rows)
    if not payloads:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for payload in payloads:
            handle.write(
                json.dumps(
                    json_clean(dict(payload)),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
    return len(payloads)


def accepted_head_payload_without_id(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in payload.items()
        if key != "head_id"
    }


def validate_accepted_head_state(
    *,
    memory_dir: Path,
    observations: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    contract_sha256: str,
    allow_unaccepted_events: bool = False,
) -> dict[str, Any]:
    heads_root = memory_dir / "accepted_heads"
    pointer_path = memory_dir / "accepted_head.json"
    manifests: dict[str, dict[str, Any]] = {}
    if heads_root.is_dir():
        for path in sorted(heads_root.glob("*/manifest.json")):
            payload = read_json(path)
            head_id = str(payload.get("head_id") or "")
            if (
                payload.get("schema_version") != ACCEPTED_HEAD_SCHEMA_VERSION
                or payload.get("status") != ACCEPTED_HEAD_STATUS
                or payload.get("memory_contract_sha256") != contract_sha256
                or path.parent.name != head_id
                or canonical_hash(
                    accepted_head_payload_without_id(payload)
                )
                != head_id
                or head_id in manifests
            ):
                raise ValueError(f"immutable accepted head invalid:{path}")
            manifests[head_id] = payload
    if not manifests:
        if pointer_path.exists():
            raise ValueError("accepted head pointer exists without manifests")
        if (observations or outcomes) and not allow_unaccepted_events:
            raise ValueError("unanchored pattern memory events")
        return {
            "head_id": "",
            "observation_event_count": 0,
            "resolved_outcome_event_count": 0,
            "observation_chain_head": "",
            "outcome_chain_head": "",
        }
    parents = {
        str(payload.get("parent_head_id") or "")
        for payload in manifests.values()
        if payload.get("parent_head_id")
    }
    for parent in parents:
        if parent not in manifests:
            raise ValueError(f"accepted head parent missing:{parent}")
    terminals = sorted(set(manifests) - parents)
    roots = [
        head_id
        for head_id, payload in manifests.items()
        if not payload.get("parent_head_id")
    ]
    if len(terminals) != 1 or len(roots) != 1:
        raise ValueError("accepted head fork or root ambiguity")
    terminal_id = terminals[0]
    lineage: set[str] = set()
    cursor = terminal_id
    while cursor:
        if cursor in lineage:
            raise ValueError("accepted head cycle")
        lineage.add(cursor)
        cursor = str(manifests[cursor].get("parent_head_id") or "")
    if lineage != set(manifests):
        raise ValueError("accepted head disconnected lineage")
    def validate_manifest_chain(
        head_id: str,
        manifest: Mapping[str, Any],
    ) -> None:
        observation_count = int(
            manifest.get("observation_event_count") or 0
        )
        outcome_count = int(
            manifest.get("resolved_outcome_event_count") or 0
        )
        if (
            len(observations) < observation_count
            or len(outcomes) < outcome_count
        ):
            raise ValueError(
                f"accepted pattern memory rollback detected:{head_id}"
            )
        observation_head = (
            str(observations[observation_count - 1].get("event_hash") or "")
            if observation_count
            else ""
        )
        outcome_head = (
            str(outcomes[outcome_count - 1].get("event_hash") or "")
            if outcome_count
            else ""
        )
        if (
            observation_head != manifest.get("observation_chain_head")
            or outcome_head != manifest.get("outcome_chain_head")
        ):
            raise ValueError(
                f"accepted pattern memory prefix chain mismatch:{head_id}"
            )

    for head_id, manifest in manifests.items():
        validate_manifest_chain(head_id, manifest)

    for label, path, count_key, hash_key in (
        (
            "observation",
            memory_dir / "observations.jsonl",
            "observation_bytes",
            "observation_sha256",
        ),
        (
            "outcome",
            memory_dir / "outcomes.jsonl",
            "outcome_bytes",
            "outcome_sha256",
        ),
    ):
        prefix_hashes = sha256_prefixes(
            path,
            (
                int(manifest.get(count_key) or 0)
                for manifest in manifests.values()
            ),
        )
        for head_id, manifest in manifests.items():
            expected_bytes = int(manifest.get(count_key) or 0)
            expected_hash = str(manifest.get(hash_key) or "")
            if prefix_hashes[expected_bytes] != expected_hash:
                raise ValueError(
                    f"accepted {label} prefix hash mismatch:{head_id}"
                )

    if not pointer_path.is_file():
        if not allow_unaccepted_events:
            raise ValueError("accepted head pointer missing")
        if len(manifests) != 1 or manifests[terminal_id].get(
            "parent_head_id"
        ):
            raise ValueError(
                "accepted head pointer missing with ambiguous manifests"
            )
        return {
            "head_id": "",
            "observation_event_count": 0,
            "resolved_outcome_event_count": 0,
            "observation_chain_head": "",
            "outcome_chain_head": "",
            "pointer_repair_required": True,
            "uncommitted_descendant_manifest_count": 1,
        }

    pointer = read_json(pointer_path)
    accepted_id = str(pointer.get("head_id") or "")
    accepted_path = heads_root / accepted_id / "manifest.json"
    pointer_valid = bool(
        pointer.get("schema_version") == ACCEPTED_HEAD_SCHEMA_VERSION
        and pointer.get("status") == ACCEPTED_HEAD_STATUS
        and accepted_id in manifests
        and pointer.get("manifest_sha256") == sha256_file(accepted_path)
    )
    if not pointer_valid:
        raise ValueError("accepted head pointer mismatch")

    descendant_count = 0
    cursor = terminal_id
    while cursor != accepted_id:
        descendant_count += 1
        cursor = str(manifests[cursor].get("parent_head_id") or "")
        if not cursor:
            raise ValueError("accepted head pointer is not in terminal lineage")

    accepted = manifests[accepted_id]
    observation_count = int(accepted.get("observation_event_count") or 0)
    outcome_count = int(
        accepted.get("resolved_outcome_event_count") or 0
    )
    has_unaccepted_events = bool(
        len(observations) > observation_count
        or len(outcomes) > outcome_count
    )
    if (
        not allow_unaccepted_events
        and (descendant_count or has_unaccepted_events)
    ):
        raise ValueError("unaccepted pattern memory suffix")
    return {
        **accepted,
        "pointer_repair_required": bool(descendant_count),
        "uncommitted_descendant_manifest_count": descendant_count,
    }


def prepare_accepted_head(
    *,
    memory_dir: Path,
    observations: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    contract_sha256: str,
    accepted_through: str,
    expected_session_count: int,
    missing_session_dates: list[str],
    missing_origin_observation_count: int,
) -> dict[str, Any]:
    prior = validate_accepted_head_state(
        memory_dir=memory_dir,
        observations=observations,
        outcomes=outcomes,
        contract_sha256=contract_sha256,
        allow_unaccepted_events=True,
    )
    observation_head = (
        str(observations[-1].get("event_hash") or "") if observations else ""
    )
    outcome_head = (
        str(outcomes[-1].get("event_hash") or "") if outcomes else ""
    )
    if (
        prior.get("observation_event_count") == len(observations)
        and prior.get("resolved_outcome_event_count") == len(outcomes)
        and prior.get("observation_chain_head") == observation_head
        and prior.get("outcome_chain_head") == outcome_head
        and prior.get("head_id")
    ):
        return {
            str(key): value
            for key, value in prior.items()
            if key
            not in {
                "pointer_repair_required",
                "uncommitted_descendant_manifest_count",
            }
        }
    observations_path = memory_dir / "observations.jsonl"
    outcomes_path = memory_dir / "outcomes.jsonl"
    observation_fingerprint = fingerprint(observations_path)
    outcome_fingerprint = fingerprint(outcomes_path)
    base = {
        "schema_version": ACCEPTED_HEAD_SCHEMA_VERSION,
        "status": ACCEPTED_HEAD_STATUS,
        "parent_head_id": str(prior.get("head_id") or ""),
        "memory_contract_sha256": contract_sha256,
        "accepted_through": accepted_through,
        "observation_event_count": len(observations),
        "resolved_outcome_event_count": len(outcomes),
        "observation_chain_head": observation_head,
        "outcome_chain_head": outcome_head,
        "observation_bytes": int(observation_fingerprint["bytes"]),
        "observation_sha256": str(
            observation_fingerprint["sha256"]
            or hashlib.sha256(b"").hexdigest()
        ),
        "outcome_bytes": int(outcome_fingerprint["bytes"]),
        "outcome_sha256": str(
            outcome_fingerprint["sha256"]
            or hashlib.sha256(b"").hexdigest()
        ),
        "expected_session_count": int(expected_session_count),
        "missing_session_dates": list(missing_session_dates),
        "session_coverage_complete": not missing_session_dates,
        "missing_origin_observation_count": int(
            missing_origin_observation_count
        ),
        "observation_data_coverage_complete": (
            missing_origin_observation_count == 0
        ),
        "research_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "champion_changed": False,
    }
    head_id = canonical_hash(base)
    payload = {**base, "head_id": head_id}
    return payload


def publish_accepted_head(
    *,
    memory_dir: Path,
    accepted_head: Mapping[str, Any],
) -> dict[str, Any]:
    payload = json_clean(dict(accepted_head))
    head_id = str(payload.get("head_id") or "")
    if (
        not head_id
        or canonical_hash(accepted_head_payload_without_id(payload))
        != head_id
    ):
        raise ValueError("prepared accepted head invalid")
    manifest_path = memory_dir / "accepted_heads" / head_id / "manifest.json"
    created_manifest = False
    if manifest_path.exists():
        if canonical_hash(read_json(manifest_path)) != canonical_hash(payload):
            raise ValueError("immutable accepted head payload changed")
    else:
        atomic_write_json(manifest_path, payload)
        created_manifest = True
    pointer = {
        "schema_version": ACCEPTED_HEAD_SCHEMA_VERSION,
        "status": ACCEPTED_HEAD_STATUS,
        "head_id": head_id,
        "manifest_sha256": sha256_file(manifest_path),
    }
    try:
        atomic_write_json(memory_dir / "accepted_head.json", pointer)
    except Exception:
        if created_manifest:
            manifest_path.unlink(missing_ok=True)
            manifest_path.parent.rmdir()
        raise
    return payload


@lru_cache(maxsize=None)
def exact_target_session(origin: str, horizon: int) -> str:
    start = pd.Timestamp(origin)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=start.date().isoformat(),
        end_date=(start + pd.Timedelta(days=400)).date().isoformat(),
    )
    sessions = [
        pd.Timestamp(value).date().isoformat()
        for value in schedule.index
        if pd.Timestamp(value).date().isoformat() > origin
    ]
    if len(sessions) < horizon:
        raise ValueError(f"NYSE horizon unavailable:{origin}:{horizon}")
    return sessions[horizon - 1]


def validate_chronological_observation_session(
    *,
    valuation_date: str,
    durable_head: Mapping[str, Any],
    forward_launch_session: str,
) -> str:
    accepted_through = str(durable_head.get("accepted_through") or "")
    if accepted_through and valuation_date == accepted_through:
        return accepted_through
    required_session = (
        exact_target_session(accepted_through, 1)
        if accepted_through
        else forward_launch_session
    )
    if valuation_date != required_session:
        raise ValueError(
            "pattern memory requires chronological session:"
            f"{required_session}!={valuation_date}"
        )
    return required_session


def expected_forward_sessions(
    launch_session: str,
    as_of_date: str,
) -> list[str]:
    launch = pd.Timestamp(launch_session).normalize()
    as_of = pd.Timestamp(as_of_date).normalize()
    if launch > as_of:
        raise ValueError(
            "pattern memory valuation precedes forward launch session:"
            f"{as_of_date}<{launch_session}"
        )
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=launch.date().isoformat(),
        end_date=as_of.date().isoformat(),
    )
    sessions = [
        pd.Timestamp(value).date().isoformat()
        for value in schedule.index
    ]
    if not sessions or sessions[0] != launch.date().isoformat():
        raise ValueError(
            f"forward launch session is not an exact NYSE session:{launch_session}"
        )
    if sessions[-1] != as_of.date().isoformat():
        raise ValueError(
            f"pattern memory as-of is not an exact NYSE session:{as_of_date}"
        )
    return sessions


def source_observations(
    *,
    valuation_date: str,
    summary: Mapping[str, Any],
    security_rows: list[Mapping[str, Any]],
    benchmark_rows: list[Mapping[str, Any]],
    contract_sha256: str,
    source_summary_sha256: str,
    source_observations_sha256: str,
    source_benchmark_sha256: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    allowed_patterns = {
        "DOWN_TO_UP_REVERSAL",
        "UP_TO_DOWN_REVERSAL",
        "CONTINUED_DOWN",
        "CONTINUED_UP",
        "FLAT_OR_INSUFFICIENT",
    }
    common = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "event_type": "OBSERVATION",
        "as_of_date": valuation_date,
        "available_from": summary.get("available_from"),
        "observation_accepted_at_utc": (
            (summary.get("forward_observation_window") or {}).get(
                "observation_accepted_at_utc"
            )
        ),
        "memory_contract_sha256": contract_sha256,
        "source_summary_sha256": source_summary_sha256,
        "source_observations_sha256": source_observations_sha256,
        "source_benchmark_sha256": source_benchmark_sha256,
        "research_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "champion_changed": False,
    }
    for source_kind, rows in (
        ("SECURITY", security_rows),
        ("BENCHMARK", benchmark_rows),
    ):
        for raw in rows:
            clean = json_clean(dict(raw))
            if (
                source_kind == "SECURITY"
                and clean.get("is_pattern_outcome_carry") is True
                and not any(
                    clean.get(field) is True
                    for field in (
                        "is_held",
                        "is_current_selector",
                        "is_proposed_entry",
                    )
                )
            ):
                continue
            ticker = str(clean.get("ticker") or "").strip().upper()
            if not ticker:
                raise ValueError(f"source ticker missing:{source_kind}")
            row_date = str(clean.get("as_of_date") or valuation_date)
            if row_date != valuation_date:
                raise ValueError(f"source row date mismatch:{source_kind}:{ticker}")
            close = finite(clean.get("close"))
            pattern = str(
                clean.get("return_transition_signature")
                or "FLAT_OR_INSUFFICIENT"
            )
            if pattern not in allowed_patterns:
                raise ValueError(
                    f"source pattern invalid:{source_kind}:{ticker}:{pattern}"
                )
            payload = {
                **common,
                "source_kind": source_kind,
                "ticker": ticker,
                "observed_close": close,
                "data_ready": bool(
                    close is not None
                    and not str(clean.get("data_reason") or "")
                    and clean.get("return_transition_sessions_consecutive")
                    is not False
                    and not str(
                        clean.get("return_transition_data_reason") or ""
                    )
                ),
                "source_payload_sha256": canonical_hash(
                    stable_source_row(clean)
                ),
                **{
                    field: clean.get(field)
                    for field in FEATURE_FIELDS
                    if field in clean
                },
                "return_transition_signature": pattern,
            }
            payload["event_id"] = canonical_hash(
                {
                    "schema_version": OBSERVATION_SCHEMA_VERSION,
                    "source_kind": source_kind,
                    "ticker": ticker,
                    "as_of_date": valuation_date,
                    "memory_contract_sha256": contract_sha256,
                }
            )
            output.append(payload)
    ordered = sorted(
        output,
        key=lambda row: (str(row["source_kind"]), str(row["ticker"])),
    )
    identities = [str(row["event_id"]) for row in ordered]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate source observation identity")
    benchmark_tickers = {
        str(row["ticker"])
        for row in ordered
        if row["source_kind"] == "BENCHMARK"
    }
    if not {"SPY", "QQQ"}.issubset(benchmark_tickers):
        raise ValueError("required benchmark observation missing")
    return ordered


def merge_new_events(
    *,
    existing: list[dict[str, Any]],
    identities: Mapping[str, Mapping[str, Any]],
    proposed: Iterable[Mapping[str, Any]],
    previous_hash: str,
) -> tuple[list[dict[str, Any]], str]:
    new_rows: list[dict[str, Any]] = []
    chain_head = previous_hash
    seen = set(identities)
    for raw in proposed:
        payload = json_clean(dict(raw))
        identity = str(payload.get("event_id") or "")
        prior = identities.get(identity)
        if prior is not None:
            if canonical_hash(event_comparison_payload(prior)) != canonical_hash(
                event_comparison_payload(payload)
            ):
                raise ValueError(f"same identity payload changed:{identity}")
            continue
        if not identity or identity in seen:
            raise ValueError(f"duplicate proposed event identity:{identity}")
        chained = attach_chain(payload, chain_head)
        new_rows.append(chained)
        chain_head = str(chained["event_hash"])
        seen.add(identity)
    return new_rows, chain_head


def validate_observation_session_cohort(
    *,
    valuation_date: str,
    existing: Iterable[Mapping[str, Any]],
    proposed: Iterable[Mapping[str, Any]],
    durable_accepted_through: str,
) -> None:
    existing_ids = {
        str(row.get("event_id") or "")
        for row in existing
        if str(row.get("as_of_date") or "") == valuation_date
    }
    proposed_ids = {
        str(row.get("event_id") or "")
        for row in proposed
        if str(row.get("as_of_date") or "") == valuation_date
    }
    if durable_accepted_through == valuation_date:
        if existing_ids != proposed_ids:
            raise ValueError(
                "accepted observation session cohort changed:"
                f"{valuation_date}"
            )
        return
    if not existing_ids.issubset(proposed_ids):
        raise ValueError(
            "unaccepted observation recovery cohort lost identities:"
            f"{valuation_date}"
        )


def required_unaccepted_retry_session(
    *,
    observations: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    durable_head: Mapping[str, Any],
) -> str:
    observation_count = int(
        durable_head.get("observation_event_count") or 0
    )
    outcome_count = int(
        durable_head.get("resolved_outcome_event_count") or 0
    )
    if (
        observation_count > len(observations)
        or outcome_count > len(outcomes)
    ):
        raise ValueError("unaccepted suffix base count exceeds archive")
    dates = {
        str(row.get("as_of_date") or "")
        for row in observations[observation_count:]
        if row.get("as_of_date")
    }
    dates.update(
        str(
            row.get("recorded_during_session")
            or row.get("target_session_date")
            or ""
        )
        for row in outcomes[outcome_count:]
        if (
            row.get("recorded_during_session")
            or row.get("target_session_date")
        )
    )
    dates.discard("")
    if len(dates) > 1:
        raise ValueError(
            "unaccepted pattern suffix spans multiple sessions:"
            + ",".join(sorted(dates))
        )
    return next(iter(dates), "")


def proposed_outcomes(
    *,
    observations: Iterable[Mapping[str, Any]],
    endpoints: Iterable[Mapping[str, Any]],
    existing_outcome_ids: set[str],
    as_of_date: str,
    horizons: Iterable[int],
    contract_sha256: str,
    source_summary_sha256: str,
) -> tuple[list[dict[str, Any]], int]:
    rows = list(observations)
    exact: dict[tuple[str, str, str], Mapping[str, Any]] = {
        (
            str(row.get("source_kind") or ""),
            str(row.get("ticker") or ""),
            str(row.get("as_of_date") or ""),
        ): row
        for row in rows
    }
    endpoint_map: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    endpoint_ids: set[str] = set()
    for raw in endpoints:
        endpoint = json_clean(dict(raw))
        if (
            endpoint.get("schema_version")
            != "run287-ohlcv-forward-outcome-endpoint-v1"
        ):
            raise ValueError("outcome endpoint schema")
        endpoint_id = str(endpoint.get("endpoint_id") or "")
        expected_endpoint_id = canonical_hash(
            {
                "schema_version": endpoint.get("schema_version"),
                "observation_event_id": endpoint.get(
                    "observation_event_id"
                ),
                "horizon_nyse_sessions": endpoint.get(
                    "horizon_nyse_sessions"
                ),
                "target_session_date": endpoint.get(
                    "target_session_date"
                ),
            }
        )
        origin_date = str(endpoint.get("origin_session_date") or "")
        horizon_value = int(endpoint.get("horizon_nyse_sessions") or 0)
        target_session = str(endpoint.get("target_session_date") or "")
        if (
            not endpoint_id
            or endpoint_id in endpoint_ids
            or endpoint_id != expected_endpoint_id
            or horizon_value <= 0
            or exact_target_session(origin_date, horizon_value)
            != target_session
            or endpoint.get("adjustment_basis_as_of") != target_session
        ):
            raise ValueError("outcome endpoint identity")
        endpoint_ids.add(endpoint_id)
        key = (
            str(endpoint.get("observation_event_id") or ""),
            int(endpoint.get("horizon_nyse_sessions") or 0),
            str(endpoint.get("target_session_date") or ""),
        )
        if key in endpoint_map:
            raise ValueError("duplicate outcome endpoint key")
        endpoint_map[key] = endpoint
    proposed: list[dict[str, Any]] = []
    missing_exact = 0
    for observation in rows:
        origin = str(observation.get("as_of_date") or "")
        origin_close = finite(observation.get("observed_close"))
        if (
            not origin
            or origin_close in (None, 0.0)
            or observation.get("data_ready") is not True
        ):
            continue
        for horizon_value in horizons:
            horizon = int(horizon_value)
            target_date = exact_target_session(origin, horizon)
            if target_date > as_of_date:
                continue
            identity = canonical_hash(
                {
                    "schema_version": OUTCOME_SCHEMA_VERSION,
                    "observation_event_id": observation["event_id"],
                    "horizon_nyse_sessions": horizon,
                    "target_session_date": target_date,
                    "memory_contract_sha256": contract_sha256,
                }
            )
            if (
                identity in existing_outcome_ids
                and target_date < as_of_date
            ):
                continue
            endpoint_key = (
                str(observation.get("event_id") or ""),
                horizon,
                target_date,
            )
            endpoint = endpoint_map.get(endpoint_key)
            origin_close = finite(
                (endpoint or {}).get(
                    "origin_close_on_target_adjustment_basis"
                )
            )
            target_close = finite(
                (endpoint or {}).get(
                    "target_close_on_target_adjustment_basis"
                )
            )
            if (
                endpoint is None
                or endpoint.get("exact_target_session") is not True
                or str(endpoint.get("data_reason") or "")
                or endpoint.get("source_kind")
                != observation.get("source_kind")
                or endpoint.get("ticker") != observation.get("ticker")
                or endpoint.get("origin_session_date") != origin
                or origin_close in (None, 0.0)
                or target_close is None
            ):
                if identity in existing_outcome_ids:
                    raise ValueError(
                        "accepted outcome retry endpoint incomplete:"
                        f"{identity}"
                    )
                missing_exact += 1
                continue
            forward_return = target_close / float(origin_close) - 1.0
            benchmark_return = None
            excess_spy = None
            benchmark_endpoint = None
            if str(observation.get("source_kind")) == "SECURITY":
                benchmark_origin = exact.get(("BENCHMARK", "SPY", origin))
                benchmark_endpoint = endpoint_map.get(
                    (
                        str((benchmark_origin or {}).get("event_id") or ""),
                        horizon,
                        target_date,
                    )
                )
                benchmark_origin_close = finite(
                    (benchmark_endpoint or {}).get(
                        "origin_close_on_target_adjustment_basis"
                    )
                )
                benchmark_target_close = finite(
                    (benchmark_endpoint or {}).get(
                        "target_close_on_target_adjustment_basis"
                    )
                )
                if (
                    benchmark_endpoint is None
                    or benchmark_endpoint.get("exact_target_session") is not True
                    or str(benchmark_endpoint.get("data_reason") or "")
                    or benchmark_origin_close in (None, 0.0)
                    or benchmark_target_close is None
                ):
                    if identity in existing_outcome_ids:
                        raise ValueError(
                            "accepted outcome retry SPY endpoint incomplete:"
                            f"{identity}"
                        )
                    missing_exact += 1
                    continue
                benchmark_return = (
                    benchmark_target_close / float(benchmark_origin_close) - 1.0
                )
                excess_spy = forward_return - benchmark_return
            proposed.append(
                {
                    "schema_version": OUTCOME_SCHEMA_VERSION,
                    "event_type": "OUTCOME",
                    "event_id": identity,
                    "observation_event_id": observation["event_id"],
                    "source_kind": observation.get("source_kind"),
                    "ticker": observation.get("ticker"),
                    "pattern_signature": observation.get(
                        "return_transition_signature"
                    ),
                    "origin_session_date": origin,
                    "target_session_date": target_date,
                    "horizon_nyse_sessions": horizon,
                    "origin_close": origin_close,
                    "target_close": target_close,
                    "source_endpoint_payload_sha256": canonical_hash(
                        endpoint
                    ),
                    "spy_endpoint_payload_sha256": (
                        canonical_hash(benchmark_endpoint)
                        if benchmark_endpoint is not None
                        else None
                    ),
                    "adjustment_basis_as_of": target_date,
                    "adjustment_basis_policy": (
                        "both_endpoints_from_target_session_hash_verified_"
                        "adjusted_history"
                    ),
                    "forward_return": forward_return,
                    "spy_forward_return": benchmark_return,
                    "excess_return_vs_spy": excess_spy,
                    "recorded_during_session": as_of_date,
                    "resolution_policy": "EXACT_ARCHIVED_NYSE_TARGET_SESSION_ONLY",
                    "memory_contract_sha256": contract_sha256,
                    "source_summary_sha256": source_summary_sha256,
                    "research_only": True,
                    "portfolio_transition_allowed": False,
                    "orders_generated": False,
                    "target_books_mutated": False,
                    "champion_changed": False,
                }
            )
    return sorted(
        proposed,
        key=lambda row: (
            str(row["target_session_date"]),
            str(row["source_kind"]),
            str(row["ticker"]),
            int(row["horizon_nyse_sessions"]),
        ),
    ), missing_exact


def aggregate_outcomes(
    observations: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
    minimum_resolved: int,
    minimum_resolution_coverage: float,
    as_of_date: str,
    horizons: Iterable[int],
    session_coverage_complete: bool = True,
    observation_data_coverage_complete: bool = True,
) -> list[dict[str, Any]]:
    observation_rows = list(observations)
    outcome_rows = list(outcomes)
    observation_map = {
        str(row.get("event_id") or ""): row for row in observation_rows
    }
    grouped: dict[tuple[str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for outcome in outcome_rows:
        observation = observation_map.get(
            str(outcome.get("observation_event_id") or "")
        ) or {}
        key = (
            str(observation.get("source_kind") or outcome.get("source_kind") or ""),
            str(
                observation.get("return_transition_signature")
                or outcome.get("pattern_signature")
                or ""
            ),
            int(outcome.get("horizon_nyse_sessions") or 0),
        )
        grouped[key].append(outcome)
    matured: dict[tuple[str, str, int], int] = defaultdict(int)
    for observation in observation_rows:
        origin = str(observation.get("as_of_date") or "")
        if not origin:
            continue
        for horizon_value in horizons:
            horizon = int(horizon_value)
            if exact_target_session(origin, horizon) <= as_of_date:
                key = (
                    str(observation.get("source_kind") or ""),
                    str(
                        observation.get("return_transition_signature")
                        or "FLAT_OR_INSUFFICIENT"
                    ),
                    horizon,
                )
                matured[key] += 1
    aggregates: list[dict[str, Any]] = []
    for source_kind, pattern, horizon in sorted(set(grouped) | set(matured)):
        rows = grouped.get((source_kind, pattern, horizon), [])
        count = len(rows)
        matured_count = int(matured.get((source_kind, pattern, horizon), 0))
        missing_count = max(0, matured_count - count)
        resolution_coverage = (
            count / matured_count if matured_count > 0 else 0.0
        )
        statistics_ready = bool(
            count >= minimum_resolved
            and resolution_coverage >= minimum_resolution_coverage
            and session_coverage_complete
            and observation_data_coverage_complete
        )
        result: dict[str, Any] = {
            "source_kind": source_kind,
            "pattern_signature": pattern,
            "horizon_nyse_sessions": horizon,
            "matured_observation_count": matured_count,
            "resolved_observation_count": count,
            "missing_exact_outcome_count": missing_count,
            "resolution_coverage": resolution_coverage,
            "minimum_resolution_coverage": minimum_resolution_coverage,
            "minimum_required": minimum_resolved,
            "session_coverage_complete": session_coverage_complete,
            "observation_data_coverage_complete": (
                observation_data_coverage_complete
            ),
            "underpowered": not statistics_ready,
            "directional_statistics_published": statistics_ready,
        }
        if statistics_ready:
            returns = np.asarray(
                [float(row["forward_return"]) for row in rows],
                dtype=float,
            )
            excess = [
                float(value)
                for value in (
                    row.get("excess_return_vs_spy") for row in rows
                )
                if finite(value) is not None
            ]
            result["directional_statistics"] = {
                "mean_forward_return": float(returns.mean()),
                "median_forward_return": float(np.median(returns)),
                "positive_return_rate": float((returns > 0.0).mean()),
                "mean_excess_return_vs_spy": (
                    float(np.mean(excess)) if excess else None
                ),
            }
        aggregates.append(result)
    return aggregates


def has_powered_security_evidence(
    aggregates: Iterable[Mapping[str, Any]],
) -> bool:
    return any(
        row.get("source_kind") == "SECURITY"
        and row.get("directional_statistics_published") is True
        for row in aggregates
    )


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Run287 OHLCV shock/rebound pattern memory",
        "",
        f"- status: `{summary.get('status')}`",
        f"- accepted through: `{summary.get('accepted_through')}`",
        f"- observation events: `{summary.get('observation_event_count')}`",
        f"- resolved outcome events: `{summary.get('resolved_outcome_event_count')}`",
        f"- completed sessions / decision weeks: `{summary.get('completed_sessions')}` / `{summary.get('decision_weeks')}`",
        f"- expected / missing sessions: `{summary.get('expected_session_count')}` / `{summary.get('missing_session_count')}`",
        f"- session coverage complete: `{summary.get('session_coverage_complete')}`",
        f"- missing origin observations: `{summary.get('missing_origin_observation_count')}`",
        f"- observation data coverage complete: `{summary.get('observation_data_coverage_complete')}`",
        f"- proposal eligible: `{summary.get('proposal_eligible')}`",
        "- append-only forward research only; no target, order, cash, champion, production, or live mutation",
        "- one rebound is a descriptive fingerprint, never automatic evidence of trend repair",
        "",
        "| Source | Pattern | Horizon | Matured | Resolved | Missing | Coverage | Minimum | Underpowered |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.get("aggregates") or []:
        lines.append(
            f"| {row.get('source_kind')} | `{row.get('pattern_signature')}` | "
            f"{row.get('horizon_nyse_sessions')} | "
            f"{row.get('matured_observation_count')} | "
            f"{row.get('resolved_observation_count')} | "
            f"{row.get('missing_exact_outcome_count')} | "
            f"{float(row.get('resolution_coverage') or 0.0):.1%} | "
            f"{row.get('minimum_required')} | "
            f"`{row.get('underpowered')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def blocked_payload(
    failures: list[str],
    sources: Mapping[str, Any],
    started: float,
    failed_session_date: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": failures,
        "failed_session_date": failed_session_date,
        "missing_session_dates": (
            [failed_session_date] if failed_session_date else []
        ),
        "session_coverage_complete": False,
        "observation_data_coverage_complete": False,
        "proposal_eligible": False,
        "directional_statistics_published": False,
        "aggregates": [],
        "research_only": True,
        "forward_observation_only": True,
        "advisory_only": True,
        "automatic_model_update_allowed": False,
        "automatic_champion_promotion_allowed": False,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "champion_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(sources),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }


def blocked(
    output_dir: Path,
    failures: list[str],
    sources: Mapping[str, Any],
    started: float,
    failed_session_date: str = "",
) -> dict[str, Any]:
    payload = blocked_payload(
        failures,
        sources,
        started,
        failed_session_date,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.md"
    payload["outputs"] = {}
    atomic_write_json(output_dir / "summary.json", payload)
    try:
        atomic_write_text(report_path, render_report(payload))
        payload["outputs"]["report"] = fingerprint(report_path)
    except Exception as exc:
        report_path.unlink(missing_ok=True)
        payload["report_publication_failure"] = (
            f"{type(exc).__name__}:{exc}"
        )
    atomic_write_json(output_dir / "summary.json", payload)
    atomic_write_json(
        output_dir / "last_attempt.json",
        {
            "schema_version": SCHEMA_VERSION,
            "status": BLOCKED_STATUS,
            "failed_session_date": failed_session_date,
            "summary_sha256": sha256_file(output_dir / "summary.json"),
        },
    )
    return payload


def record_failed_session(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    reason = str(args.record_failed_session_reason or "").strip()
    if not reason:
        raise ValueError("failed-session reason required")
    return blocked(
        output_dir,
        [f"session_failure:{reason}"],
        {},
        time.perf_counter(),
        failed_session_date=str(args.valuation_date),
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources: dict[str, Any] = {}
    preserve_blocked_publication = bool(
        getattr(args, "preserve_blocked_publication", False)
    )
    commit_head_preserve_blocked_publication = bool(
        getattr(
            args,
            "commit_head_preserve_blocked_publication",
            False,
        )
    )
    preserve_public_marker = bool(
        preserve_blocked_publication
        or commit_head_preserve_blocked_publication
    )
    pending_session_date = str(
        getattr(args, "pending_session_date", "") or ""
    )
    try:
        if (
            preserve_blocked_publication
            and commit_head_preserve_blocked_publication
        ):
            raise ValueError("pattern publication modes are mutually exclusive")
        if preserve_public_marker:
            if not pending_session_date:
                raise ValueError(
                    "pending session date required for preserved publication"
                )
            public_marker = read_json(output_dir / "summary.json")
            if (
                public_marker.get("status") != BLOCKED_STATUS
                or public_marker.get("proposal_eligible") is not False
                or str(public_marker.get("failed_session_date") or "")
                != pending_session_date
            ):
                raise ValueError(
                    "preserved recovery requires exact current-session "
                    "BLOCKED marker"
                )
        contract_path = repo_path(args.contract)
        contract = read_json(contract_path)
        sources["contract"] = fingerprint(contract_path)
        if contract.get("schema_version") != "run287-ohlcv-pattern-memory-contract-v1":
            raise ValueError("memory contract schema")
        contract_sha256 = str(sources["contract"]["sha256"])
        if contract_sha256 != PINNED_CONTRACT_SHA256:
            raise ValueError(
                "pattern memory contract hash changed without explicit "
                f"immutable-chain migration:{contract_sha256}"
            )
        expected_sessions = expected_forward_sessions(
            str(
                contract["forward_learning"][
                    "accepted_forward_launch_session"
                ]
            ),
            args.valuation_date,
        )

        summary_path = repo_path(args.timing_summary)
        summary = read_json(summary_path)
        sources["timing_summary"] = fingerprint(summary_path)
        source_contract = contract["source_contract"]
        if summary.get("schema_version") != source_contract["schema_version"]:
            raise ValueError("timing summary schema")
        if summary.get("status") not in set(source_contract["ready_statuses"]):
            raise ValueError(f"timing summary not READY:{summary.get('status')}")
        if str(summary.get("as_of_date") or "") != args.valuation_date:
            raise ValueError("timing summary valuation date")
        for key in (
            "portfolio_transition_allowed",
            "orders_generated",
            "target_books_mutated",
            "selector_weights_changed",
            "cash_policy_changed",
            "champion_changed",
            "backtest_executed",
            "fullrun_executed",
            "production_activation_allowed",
            "live_trading_enabled",
        ):
            if summary.get(key) is not False:
                raise ValueError(f"unsafe timing summary:{key}")

        observations_path, sources["timing_observations"] = resolve_output(
            summary_path,
            summary,
            "forward_observations",
        )
        benchmark_path, sources["timing_benchmark"] = resolve_output(
            summary_path,
            summary,
            "benchmark_location",
        )
        endpoint_path, sources["timing_outcome_endpoints"] = resolve_output(
            summary_path,
            summary,
            "forward_outcome_endpoints",
        )
        security_rows = read_jsonl(observations_path)
        endpoint_rows = read_jsonl(endpoint_path)
        benchmark_rows = pd.read_csv(benchmark_path, low_memory=False).to_dict(
            "records"
        )
        proposed_observations = source_observations(
            valuation_date=args.valuation_date,
            summary=summary,
            security_rows=security_rows,
            benchmark_rows=benchmark_rows,
            contract_sha256=contract_sha256,
            source_summary_sha256=str(sources["timing_summary"]["sha256"]),
            source_observations_sha256=str(
                sources["timing_observations"]["sha256"]
            ),
            source_benchmark_sha256=str(sources["timing_benchmark"]["sha256"]),
        )

        observations_archive = output_dir / "observations.jsonl"
        outcomes_archive = output_dir / "outcomes.jsonl"
        existing_observations, observation_ids, observation_head = validate_chain(
            read_jsonl(observations_archive),
            expected_schema=OBSERVATION_SCHEMA_VERSION,
            contract_sha256=contract_sha256,
        )
        existing_outcomes, outcome_ids, outcome_head = validate_chain(
            read_jsonl(outcomes_archive),
            expected_schema=OUTCOME_SCHEMA_VERSION,
            contract_sha256=contract_sha256,
        )
        durable_parent_head = validate_accepted_head_state(
            memory_dir=output_dir,
            observations=existing_observations,
            outcomes=existing_outcomes,
            contract_sha256=contract_sha256,
            allow_unaccepted_events=True,
        )
        required_retry_session = required_unaccepted_retry_session(
            observations=existing_observations,
            outcomes=existing_outcomes,
            durable_head=durable_parent_head,
        )
        if (
            required_retry_session
            and required_retry_session != args.valuation_date
        ):
            raise ValueError(
                "unaccepted pattern session requires exact retry:"
                f"{required_retry_session}!={args.valuation_date}"
            )
        existing_dates = [
            str(row.get("as_of_date") or "")
            for row in existing_observations
            if row.get("as_of_date")
        ]
        if existing_dates and args.valuation_date < max(existing_dates):
            raise ValueError(
                f"out-of-order observation:{args.valuation_date}<{max(existing_dates)}"
            )
        validate_chronological_observation_session(
            valuation_date=args.valuation_date,
            durable_head=durable_parent_head,
            forward_launch_session=str(
                contract["forward_learning"][
                    "accepted_forward_launch_session"
                ]
            ),
        )
        validate_observation_session_cohort(
            valuation_date=args.valuation_date,
            existing=existing_observations,
            proposed=proposed_observations,
            durable_accepted_through=str(
                durable_parent_head.get("accepted_through") or ""
            ),
        )
        new_observations, observation_head = merge_new_events(
            existing=existing_observations,
            identities=observation_ids,
            proposed=proposed_observations,
            previous_hash=observation_head,
        )
        all_observations = [*existing_observations, *new_observations]
        proposed_resolutions, missing_exact = proposed_outcomes(
            observations=all_observations,
            endpoints=endpoint_rows,
            existing_outcome_ids=set(outcome_ids),
            as_of_date=args.valuation_date,
            horizons=contract["forward_learning"][
                "outcome_horizons_nyse_sessions"
            ],
            contract_sha256=contract_sha256,
            source_summary_sha256=str(
                sources["timing_summary"]["sha256"]
            ),
        )
        new_outcomes, outcome_head = merge_new_events(
            existing=existing_outcomes,
            identities=outcome_ids,
            proposed=proposed_resolutions,
            previous_hash=outcome_head,
        )

        for label in (
            "timing_summary",
            "timing_observations",
            "timing_benchmark",
            "timing_outcome_endpoints",
        ):
            path = Path(str(sources[label]["path"]))
            if sha256_file(path) != str(sources[label]["sha256"]):
                raise ValueError(f"source changed before append:{label}")

        _, recovery_manifest_path = persist_recovery_evidence(
            memory_dir=output_dir,
            valuation_date=args.valuation_date,
            contract_sha256=contract_sha256,
            source_paths={
                "timing_summary": summary_path,
                "timing_observations": observations_path,
                "timing_benchmark": benchmark_path,
                "timing_outcome_endpoints": endpoint_path,
            },
            sources=sources,
        )
        sources["recovery_evidence_manifest"] = fingerprint(
            recovery_manifest_path
        )

        appended_observations = append_rows(
            observations_archive,
            new_observations,
        )
        appended_outcomes = append_rows(outcomes_archive, new_outcomes)
        all_outcomes = [*existing_outcomes, *new_outcomes]
        minimum = int(
            contract["forward_learning"][
                "minimum_resolved_observations_per_pattern_horizon"
            ]
        )
        minimum_resolution_coverage = float(
            contract["forward_learning"][
                "minimum_resolution_coverage_for_directional_statistics"
            ]
        )
        sessions = sorted(
            {
                str(row.get("as_of_date"))
                for row in all_observations
                if row.get("as_of_date")
            }
        )
        missing_session_dates = sorted(
            set(expected_sessions) - set(sessions)
        )
        session_coverage_complete = not missing_session_dates
        missing_origin_observation_count = sum(
            1
            for row in all_observations
            if row.get("data_ready") is not True
            or finite(row.get("observed_close")) in (None, 0.0)
        )
        observation_data_coverage_complete = (
            missing_origin_observation_count == 0
        )
        aggregates = aggregate_outcomes(
            all_observations,
            all_outcomes,
            minimum,
            minimum_resolution_coverage,
            args.valuation_date,
            contract["forward_learning"][
                "outcome_horizons_nyse_sessions"
            ],
            session_coverage_complete=session_coverage_complete,
            observation_data_coverage_complete=(
                observation_data_coverage_complete
            ),
        )
        weeks = sorted(
            {
                f"{pd.Timestamp(value).isocalendar().year}-W{pd.Timestamp(value).isocalendar().week:02d}"
                for value in sessions
            }
        )
        minimum_sessions = int(
            contract["forward_learning"][
                "minimum_completed_sessions_before_proposal"
            ]
        )
        minimum_weeks = int(
            contract["forward_learning"][
                "minimum_decision_weeks_before_proposal"
            ]
        )
        powered = has_powered_security_evidence(aggregates)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": READY_STATUS,
            "contract_failures": [],
            "accepted_through": max(sessions) if sessions else "",
            "observation_event_count": len(all_observations),
            "resolved_outcome_event_count": len(all_outcomes),
            "appended_observation_count": appended_observations,
            "appended_outcome_count": appended_outcomes,
            "exact_target_observation_missing_count": missing_exact,
            "completed_sessions": len(sessions),
            "decision_weeks": len(weeks),
            "expected_session_count": len(expected_sessions),
            "missing_session_count": len(missing_session_dates),
            "missing_session_dates": missing_session_dates,
            "session_coverage_complete": session_coverage_complete,
            "missing_origin_observation_count": (
                missing_origin_observation_count
            ),
            "observation_data_coverage_complete": (
                observation_data_coverage_complete
            ),
            "minimum_completed_sessions_before_proposal": minimum_sessions,
            "minimum_decision_weeks_before_proposal": minimum_weeks,
            "minimum_resolved_per_pattern_horizon": minimum,
            "minimum_resolution_coverage_for_directional_statistics": (
                minimum_resolution_coverage
            ),
            "powered_security_evidence": powered,
            "proposal_eligible": bool(
                len(sessions) >= minimum_sessions
                and len(weeks) >= minimum_weeks
                and powered
                and session_coverage_complete
                and observation_data_coverage_complete
            ),
            "aggregates": aggregates,
            "observation_chain_head": observation_head,
            "outcome_chain_head": outcome_head,
            "durable_parent_head_id": durable_parent_head.get("head_id") or "",
            "research_only": True,
            "forward_observation_only": True,
            "advisory_only": True,
            "automatic_model_update_allowed": False,
            "automatic_champion_promotion_allowed": False,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "champion_changed": False,
            "historical_cagr_mdd_evidence_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "memory_contract_sha256": contract_sha256,
            "source_inputs": sources,
            "outputs": {
                "observations": fingerprint(observations_archive),
                "outcomes": fingerprint(outcomes_archive),
            },
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "performance": {"elapsed_seconds": time.perf_counter() - started},
            "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
        }
        report_text = render_report(payload)
        report_sha256 = hashlib.sha256(
            report_text.encode("utf-8")
        ).hexdigest()
        staged_report_path = (
            output_dir
            / "deferred_reports"
            / args.valuation_date.replace("-", "")
            / f"{report_sha256}.md"
        )
        if staged_report_path.is_file():
            if sha256_file(staged_report_path) != report_sha256:
                raise ValueError(
                    f"immutable staged report mismatch:{staged_report_path}"
                )
        else:
            atomic_write_text(staged_report_path, report_text)
        if preserve_public_marker:
            payload["outputs"]["deferred_report"] = fingerprint(
                staged_report_path
            )
        else:
            report_path = output_dir / "report.md"
            payload["outputs"]["staged_report"] = fingerprint(
                staged_report_path
            )
        accepted_head = prepare_accepted_head(
            memory_dir=output_dir,
            observations=all_observations,
            outcomes=all_outcomes,
            contract_sha256=contract_sha256,
            accepted_through=max(sessions) if sessions else "",
            expected_session_count=len(expected_sessions),
            missing_session_dates=missing_session_dates,
            missing_origin_observation_count=(
                missing_origin_observation_count
            ),
        )
        payload["accepted_head_id"] = accepted_head["head_id"]
        payload["durable_parent_head_id"] = str(
            accepted_head.get("parent_head_id") or ""
        )
        if preserve_blocked_publication:
            # The existing exact-current-session BLOCKED summary, report,
            # last-attempt marker, and accepted head remain untouched. The
            # post-ledger call performs the one public/head commit.
            payload["publication_deferred"] = True
            payload["pending_publication_session"] = pending_session_date
            payload["prepared_accepted_head_id"] = accepted_head["head_id"]
            return payload
        if commit_head_preserve_blocked_publication:
            publish_accepted_head(
                memory_dir=output_dir,
                accepted_head=accepted_head,
            )
            payload["publication_deferred"] = True
            payload["accepted_head_committed"] = True
            payload["public_blocked_marker_preserved"] = True
            payload["pending_publication_session"] = pending_session_date
            return payload

        manifest_path = (
            output_dir
            / "accepted_heads"
            / str(accepted_head["head_id"])
            / "manifest.json"
        )
        manifest_fingerprint = anticipated_json_fingerprint(
            manifest_path,
            accepted_head,
        )
        pointer_payload = {
            "schema_version": ACCEPTED_HEAD_SCHEMA_VERSION,
            "status": ACCEPTED_HEAD_STATUS,
            "head_id": accepted_head["head_id"],
            "manifest_sha256": manifest_fingerprint["sha256"],
        }
        payload["outputs"]["accepted_head"] = (
            anticipated_json_fingerprint(
                output_dir / "accepted_head.json",
                pointer_payload,
            )
        )
        payload["outputs"]["accepted_head_manifest"] = manifest_fingerprint
        # Make the public summary the final visibility commit.  A hard stop at
        # any earlier point must leave an exact-session BLOCKED marker rather
        # than a READY summary whose accepted pointer is still the parent.
        pending_publication = blocked(
            output_dir,
            ["session_failure:accepted_head_publication_pending"],
            sources,
            started,
            failed_session_date=str(args.valuation_date),
        )
        pending_summary_path = output_dir / "summary.json"
        pending_report_path = output_dir / "report.md"
        pending_last_attempt_path = output_dir / "last_attempt.json"
        pending_summary = read_json(pending_summary_path)
        pending_last_attempt = read_json(pending_last_attempt_path)
        pending_report = (
            (pending_publication.get("outputs") or {}).get("report") or {}
        )
        if (
            pending_summary.get("status") != BLOCKED_STATUS
            or pending_summary.get("proposal_eligible") is not False
            or str(pending_summary.get("failed_session_date") or "")
            != str(args.valuation_date)
            or pending_last_attempt.get("status") != BLOCKED_STATUS
            or pending_last_attempt.get("summary_sha256")
            != sha256_file(pending_summary_path)
            or pending_report.get("hash_matches") is False
            or pending_report.get("exists") is not True
            or not pending_report_path.is_file()
            or pending_report.get("sha256")
            != sha256_file(pending_report_path)
        ):
            raise ValueError(
                "accepted-head publication pending marker incomplete"
            )
        publish_accepted_head(
            memory_dir=output_dir,
            accepted_head=accepted_head,
        )
        if sha256_file(staged_report_path) != report_sha256:
            raise ValueError("staged report changed before public commit")
        atomic_write_text(
            report_path,
            staged_report_path.read_text(encoding="utf-8"),
        )
        payload["outputs"]["report"] = fingerprint(report_path)
        atomic_write_json(output_dir / "summary.json", payload)
        atomic_write_json(
            output_dir / "last_attempt.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": READY_STATUS,
                "accepted_through": payload["accepted_through"],
                "summary_sha256": sha256_file(output_dir / "summary.json"),
            },
        )
        return payload
    except Exception as exc:
        if preserve_public_marker:
            payload = blocked_payload(
                [f"{type(exc).__name__}:{exc}"],
                sources,
                started,
                pending_session_date or str(args.valuation_date),
            )
            payload["public_blocked_marker_preserved"] = True
            return payload
        return blocked(
            output_dir,
            [f"{type(exc).__name__}:{exc}"],
            sources,
            started,
            failed_session_date=(
                pending_session_date
                if preserve_public_marker and pending_session_date
                else str(args.valuation_date)
            ),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timing-summary",
        default="",
    )
    parser.add_argument("--record-failed-session-reason", default="")
    parser.add_argument(
        "--preserve-blocked-publication",
        action="store_true",
    )
    parser.add_argument(
        "--commit-head-preserve-blocked-publication",
        action="store_true",
    )
    parser.add_argument("--pending-session-date", default="")
    parser.add_argument(
        "--contract",
        default="docs/run287_ohlcv_pattern_memory_contract.json",
    )
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--output-dir",
        default=(
            "outputs/run287_decision_observation_archive/"
            "ohlcv_pattern_memory"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record_mode = bool(str(args.record_failed_session_reason or "").strip())
    payload = record_failed_session(args) if record_mode else build(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return (
        0
        if record_mode or payload.get("status") == READY_STATUS
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
