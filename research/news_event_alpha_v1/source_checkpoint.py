"""Hash-pinned, data-only SEC cache transfer. Not a model/admission receipt.

The cloud runner persists content-addressed objects once and a small manifest
per attempt. Frozen submission pages + verified URL receipts reconstruct the
remaining queue. No pickle, archive extraction, code execution or remote delete.
"""
from __future__ import annotations
from pathlib import Path
import re
from urllib.parse import urlsplit

from .admission import checked_file, json_load, read_bounded, reparse_point, sha256, HEX64
from .execution import require
from .runtime import canonical_bytes, utc
from .source_capture import MAX_BODY, MAX_STORED, exclusive_bytes, _outside_git, validate_capture_plan
from .source_bridge import sec_url

SCHEMA = "news-sec-resume-checkpoint-v1"
MAX_FILES = 2401
MAX_BYTES = MAX_STORED + 8 * 1024 * 1024
MANIFEST_LIMIT = 2 * 1024 * 1024
CODE_PATHS = (
    "research/news_event_alpha_v1/runtime.py", "research/news_event_alpha_v1/admission.py",
    "research/news_event_alpha_v1/execution.py", "research/news_event_alpha_v1/source_bridge.py",
    "research/news_event_alpha_v1/source_capture.py", "research/news_event_alpha_v1/source_checkpoint.py",
    "research/news_event_alpha_v1/shared_reader.py", "tools/run_news_research_cloud.py",
)
RECEIPT_FIELDS = {"schema", "source_url", "raw_sha256", "bytes", "ingested_at", "source_public_at",
                  "source_id", "readback_verified", "rights_granted_by_this_receipt", "historical_pit_certified"}


def code_fingerprint(repo: Path) -> str:
    return sha256(canonical_bytes({p: sha256(read_bounded(checked_file(repo, p))) for p in CODE_PATHS}))


def check_pin(pin: str) -> None:
    require(type(pin) is str and HEX64.fullmatch(pin) is not None, "RESUME_HASH_PIN_REQUIRED")


def cache_path(path: str) -> bool:
    return type(path) is str and (path == "CAPTURE_PLAN.json" or
        re.fullmatch(r"objects/[0-9a-f]{64}|receipts/[0-9a-f]{64}\.json", path) is not None)


def _validate_cache(files: dict[str, bytes], *, as_of: str) -> dict:
    require("CAPTURE_PLAN.json" in files and len(files) <= MAX_FILES, "RESUME_CACHE_FILE_COUNT")
    require(all(cache_path(p) for p in files), "RESUME_CACHE_PATH")
    require(sum(map(len, files.values())) <= MAX_BYTES, "RESUME_CACHE_BYTE_BUDGET")
    plan = json_load(files["CAPTURE_PLAN.json"])
    ciks, _, _ = validate_capture_plan(plan, as_of=as_of)
    require(plan.get("document_progression") == "REMAINING_UNCAPTURED", "RESUME_PROGRESS_CONTRACT")
    used = set()
    for path, raw in files.items():
        if not path.startswith("receipts/"):
            continue
        r = json_load(raw)
        require(type(r) is dict and set(r) == RECEIPT_FIELDS, "RESUME_RECEIPT_FIELDS")
        url = sec_url(r["source_url"])
        u = urlsplit(url)
        if u.netloc == "data.sec.gov":
            require(any(u.path.startswith("/submissions/CIK" + c) for c in ciks), "RESUME_SOURCE_SCOPE")
        else:
            require(u.path.split("/")[4] in {str(int(c)) for c in ciks}, "RESUME_SOURCE_SCOPE")
        require(path == "receipts/" + sha256(url.encode("ascii")) + ".json", "RESUME_URL_BINDING")
        check_pin(r["raw_sha256"])
        member = "objects/" + r["raw_sha256"]
        require(member in files and sha256(files[member]) == r["raw_sha256"], "RESUME_RAW_BINDING")
        require(type(r["bytes"]) is int and 0 < r["bytes"] == len(files[member]) <= MAX_BODY, "RESUME_RECEIPT_BYTES")
        require(r["schema"] == "sec-capture-receipt-p0.3" and r["source_id"] == "SEC_EDGAR"
                and r["readback_verified"] is True and r["source_public_at"] is None
                and r["rights_granted_by_this_receipt"] is False and r["historical_pit_certified"] is False,
                "RESUME_RECEIPT_AUTHORITY")
        require(utc(r["ingested_at"]) <= utc(as_of), "RESUME_RECEIPT_FUTURE")
        if u.netloc == "data.sec.gov":
            require(type(json_load(files[member])) is dict, "RESUME_EXPECTED_JSON")
        used.add(member)
    require({p for p in files if p.startswith("objects/")} == used, "RESUME_ORPHAN_OBJECT")
    return plan


def freeze_cache(root: Path, output: Path, *, as_of: str, code_hash: str,
                 parent_checkpoint: str | None = None) -> dict:
    """Stage only plan/objects/receipts; never exports, logs, secrets or programs."""
    check_pin(code_hash)
    if parent_checkpoint is not None:
        check_pin(parent_checkpoint)
    root, output = Path(root), Path(output)
    _outside_git(root); _outside_git(output)
    require(not output.exists() and not output.resolve().is_relative_to(root.resolve()), "RESUME_OUTPUT_EXISTS_OR_NESTED")
    files = {"CAPTURE_PLAN.json": read_bounded(checked_file(root, "CAPTURE_PLAN.json"))}
    for folder in ("objects", "receipts"):
        directory = root / folder
        require(not reparse_point(directory), "RESUME_REPARSE_POINT")
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            rel = path.relative_to(root).as_posix()
            require(cache_path(rel), "RESUME_CACHE_PATH")
            files[rel] = read_bounded(checked_file(root, rel))
    plan = _validate_cache(files, as_of=as_of)
    m = {"schema": SCHEMA, "purpose": "FROZEN_SOURCE_CACHE_NOT_MODEL_INPUT", "generated_at": as_of,
         "code_fingerprint": code_hash, "parent_checkpoint_sha256": parent_checkpoint,
         "plan_sha256": sha256(files["CAPTURE_PLAN.json"]), "model_training_eligible": False,
         "selector_eligible": False, "files": []}
    for rel, raw in sorted(files.items()):
        h = sha256(raw)
        exclusive_bytes(output / "objects" / h, raw)
        m["files"].append({"path": rel, "sha256": h, "bytes": len(raw)})
    raw = canonical_bytes(m)
    require(len(raw) <= MANIFEST_LIMIT, "RESUME_MANIFEST_BUDGET")
    exclusive_bytes(output / "CHECKPOINT.json", raw)
    return {"checkpoint_sha256": sha256(raw), "manifest": m, "plan": plan}


def validate_checkpoint_manifest(raw: bytes, *, expected_hash: str, code_hash: str, as_of: str) -> dict:
    check_pin(expected_hash); check_pin(code_hash)
    require(len(raw) <= MANIFEST_LIMIT and sha256(raw) == expected_hash, "RESUME_MANIFEST_HASH")
    m = json_load(raw)
    require(type(m) is dict and m.get("schema") == SCHEMA
            and m.get("purpose") == "FROZEN_SOURCE_CACHE_NOT_MODEL_INPUT", "RESUME_MANIFEST_SCHEMA")
    require(m.get("selector_eligible") is False and m.get("model_training_eligible") is False, "RESUME_AUTHORITY")
    require(m.get("code_fingerprint") == code_hash, "RESUME_CODE_CHANGED_REVIEW_MIGRATION")
    require(utc(m["generated_at"]) <= utc(as_of), "RESUME_CHECKPOINT_FUTURE")
    check_pin(m["plan_sha256"])
    if m.get("parent_checkpoint_sha256") is not None:
        check_pin(m["parent_checkpoint_sha256"])
    fs = m.get("files")
    require(type(fs) is list and 1 <= len(fs) <= MAX_FILES, "RESUME_MANIFEST_FILES")
    seen, total = set(), 0
    for e in fs:
        require(type(e) is dict and cache_path(e.get("path")) and e["path"] not in seen, "RESUME_MANIFEST_PATH")
        seen.add(e["path"]); check_pin(e.get("sha256"))
        require(type(e.get("bytes")) is int and 0 < e["bytes"] <= MAX_BODY, "RESUME_FILE_BUDGET")
        total += e["bytes"]
    require("CAPTURE_PLAN.json" in seen and total <= MAX_BYTES, "RESUME_CACHE_BYTE_BUDGET")
    return m


def restore_cache(snapshot: Path, target: Path, *, expected_hash: str, code_hash: str, as_of: str) -> dict:
    snapshot, target = Path(snapshot), Path(target)
    _outside_git(snapshot); _outside_git(target)
    require(not target.exists() and not target.resolve().is_relative_to(snapshot.resolve()), "RESUME_TARGET_EXISTS_OR_NESTED")
    raw = read_bounded(checked_file(snapshot, "CHECKPOINT.json"), MANIFEST_LIMIT)
    m = validate_checkpoint_manifest(raw, expected_hash=expected_hash, code_hash=code_hash, as_of=as_of)
    files = {}
    for e in m["files"]:
        data = read_bounded(checked_file(snapshot, "objects/" + e["sha256"]))
        require(len(data) == e["bytes"] and sha256(data) == e["sha256"], "RESUME_OBJECT_HASH")
        files[e["path"]] = data
    expected_files = {"CHECKPOINT.json"} | {"objects/" + e["sha256"] for e in m["files"]}
    actual = set()
    for p in snapshot.rglob("*"):
        require(not reparse_point(p), "RESUME_REPARSE_POINT")
        if p.is_file():
            actual.add(p.relative_to(snapshot).as_posix())
    require(actual == expected_files, "RESUME_UNDECLARED_FILE")
    require(sha256(files["CAPTURE_PLAN.json"]) == m["plan_sha256"], "RESUME_PLAN_HASH")
    plan = _validate_cache(files, as_of=as_of)
    # No target created until every member and receipt has passed.
    for rel, data in files.items():
        exclusive_bytes(target / rel, data)
    return plan
