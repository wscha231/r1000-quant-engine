#!/usr/bin/env python3
"""Canonical source/code identity for the Run287 exact-packet chain.

The identity deliberately combines the current Git commit with the canonical
text bytes that will actually execute.  This makes an uncommitted or
cross-platform line-ending change visible without making CRLF versus LF alone
produce a different identity.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-exact-packet-code-identity-v1"
IDENTITY_FILES: dict[str, str] = {
    "workflow": ".github/workflows/daily_operating_selection_refresh.yml",
    "code_identity": "tools/run287_code_identity.py",
    "upstream_builder": "tools/run_run287_exact_packet_upstream.py",
    "scored_latest_builder": "tools/run_run287_scored_latest_refresh.py",
    "source_bundle_builder": "tools/build_run287_exact_packet_source_bundle.py",
    "input_registry_builder": "tools/build_run287_exact_packet_input_registry.py",
    "packet_producer": "tools/run_run287_exact_packet_producer.py",
    "selector_builder": "tools/run_run287_current_selector_no_write.py",
    "candidate_risk_builder": "tools/build_run287_candidate_risk_watch.py",
}


def _canonical_text_bytes(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(_canonical_text_bytes(content)).hexdigest()


def _git_output(repo_root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=repo_root,
        stderr=subprocess.DEVNULL,
        timeout=15,
    ).strip()


def identity_sha256(identity: Mapping[str, Any]) -> str:
    semantic = {
        str(key): value
        for key, value in identity.items()
        if str(key) != "identity_sha256"
    }
    serialized = json.dumps(
        semantic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def current_code_identity(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    try:
        revision_lines = (
            _git_output(root, "rev-parse", "HEAD", "HEAD^{tree}")
            .decode("ascii")
            .splitlines()
        )
        if len(revision_lines) != 2:
            raise ValueError("Git did not return commit and tree identities")
        source_commit, source_tree = revision_lines
    except (
        OSError,
        UnicodeDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise ValueError("current Git source identity is unavailable") from exc

    files: dict[str, dict[str, Any]] = {}
    for label, relative_path in IDENTITY_FILES.items():
        path = root / relative_path
        if not path.is_file():
            raise ValueError(f"code identity file is missing: {relative_path}")
        working_hash = _sha256(path.read_bytes())
        files[label] = {
            "path": relative_path,
            "sha256": working_hash,
        }

    identity: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_commit_sha": source_commit,
        "source_tree_sha": source_tree,
        "files": files,
    }
    identity["identity_sha256"] = identity_sha256(identity)
    return identity


def code_identity_failures(
    expected: Any,
    *,
    current: Mapping[str, Any] | None = None,
    prefix: str = "code_identity",
) -> list[str]:
    failures: list[str] = []
    if not isinstance(expected, Mapping):
        return [f"{prefix}:schema"]
    if expected.get("schema_version") != SCHEMA_VERSION:
        failures.append(f"{prefix}:schema")
    for field in ("source_commit_sha", "source_tree_sha"):
        value = str(expected.get(field) or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{40,64}", value) is None:
            failures.append(f"{prefix}:{field}")
    files = expected.get("files")
    if not isinstance(files, Mapping):
        failures.append(f"{prefix}:files_schema")
        files = {}
    missing = sorted(set(IDENTITY_FILES).difference(files))
    extra = sorted(set(files).difference(IDENTITY_FILES))
    if missing:
        failures.append(f"{prefix}:files_missing:{','.join(missing)}")
    if extra:
        failures.append(f"{prefix}:files_extra:{','.join(extra)}")
    for label, relative_path in IDENTITY_FILES.items():
        record = files.get(label)
        if not isinstance(record, Mapping):
            continue
        if str(record.get("path") or "") != relative_path:
            failures.append(f"{prefix}:file_path:{label}")
        digest = str(record.get("sha256") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            failures.append(f"{prefix}:file_sha256:{label}")
    recorded_identity = str(expected.get("identity_sha256") or "").strip().lower()
    if (
        re.fullmatch(r"[0-9a-f]{64}", recorded_identity) is None
        or recorded_identity != identity_sha256(expected)
    ):
        failures.append(f"{prefix}:identity_sha256")
    if current is not None and dict(expected) != dict(current):
        failures.append(f"{prefix}:current_mismatch")
    return failures
