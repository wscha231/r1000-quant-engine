"""Verify a bounded, exact-run market-session skip artifact. No account writes."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import zipfile

import pandas as pd
from tools.run_daily_market_session_gate import evaluate_market_session


def verify_skip(artifact: dict, archive: Path, source_run: dict) -> dict:
    run_id = source_run.get("id")
    sha = source_run.get("head_sha")
    if (type(run_id) is not int or run_id <= 0 or
        re.fullmatch(r"[0-9a-f]{40}", str(sha)) is None or
        source_run.get("status") != "completed" or source_run.get("conclusion") != "success" or
        type(source_run.get("run_attempt")) is not int or source_run["run_attempt"] <= 0):
        raise ValueError("skip_source_run_invalid")
    associated = artifact.get("workflow_run") or {}
    size = artifact.get("size_in_bytes")
    digest = artifact.get("digest")
    if (artifact.get("name") != f"daily-market-session-gate-{run_id}" or
        type(artifact.get("id")) is not int or artifact["id"] <= 0 or
        artifact.get("expired") is not False or
        type(size) is not int or not 0 < size <= 1024**2 or
        re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)) is None or
        associated.get("id") != run_id or associated.get("head_sha") != sha):
        raise ValueError("skip_artifact_identity_invalid")
    if archive.stat().st_size != size:
        raise ValueError("skip_archive_size_mismatch")
    content = archive.read_bytes()
    if "sha256:" + hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("skip_archive_digest_mismatch")
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        entries = z.infolist()
        if (len(entries) != 1 or entries[0].filename != "daily_market_session_gate.json" or
            entries[0].file_size > 16384 or entries[0].is_dir() or
            stat.S_ISLNK(entries[0].external_attr >> 16) or entries[0].flag_bits & 1):
            raise ValueError("skip_archive_members_invalid")
        gate = json.loads(z.read(entries[0]).decode("utf-8"))
    if (not isinstance(gate, dict) or gate.get("ready") is not False or
        gate.get("forced") is not False or gate.get("selected_session_explicit") is not False or
        gate.get("min_close_age_minutes") != 90 or gate.get("max_close_age_hours") != 18.0 or
        gate.get("status") not in {"SKIP_STALE_SESSION", "SKIP_CLOSE_SETTLEMENT_BUFFER", "SKIP_NO_COMPLETED_SESSION"}):
        raise ValueError("skip_gate_is_not_supported_noop")
    def stamp(value):
        result=pd.Timestamp(value)
        if pd.isna(result) or result.tzinfo is None:raise ValueError("skip_time_invalid")
        return result.tz_convert("UTC")
    observed = stamp(gate["checked_at_utc"])
    start = stamp(source_run.get("run_started_at") or source_run["created_at"])
    end = stamp(source_run["updated_at"])
    created = stamp(artifact["created_at"])
    # GitHub artifact timestamps may be rounded to whole seconds.
    if not (start <= observed <= end and start <= created <= end and observed < created + pd.Timedelta(seconds=1)):
        raise ValueError("skip_receipt_outside_source_attempt")
    replay = evaluate_market_session(now_utc=observed, min_close_age_minutes=90, max_close_age_hours=18)
    if gate != replay:
        raise ValueError("skip_calendar_replay_mismatch")
    return {"schema_version": "run287-sector-session-skip-v1",
        "status": "SKIPPED_UPSTREAM_MARKET_SESSION", "reason": gate["status"],
        "source_run_id": run_id, "source_run_attempt": source_run["run_attempt"],
        "source_commit_sha": sha, "source_artifact_id": artifact["id"],
        "source_artifact_sha256": digest.removeprefix("sha256:"),
        "market_session_gate": gate, "ready": False, "research_only": True,
        "orders_generated": False, "ledger_mutated": False, "target_books_mutated": False}
