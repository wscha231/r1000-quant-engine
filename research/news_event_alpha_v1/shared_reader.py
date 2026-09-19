"""Bounded source-capture exchange for research consumers, NEVER model admission.

Uses P0-3's actual source parser and byte/provenance checks. A shared capture
contains SEC references awaiting economic/security/price review, not picks,
expected returns, or a new accepted model/portfolio ledger.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import shutil

from .admission import checked_file, json_load, read_bounded, reparse_point, safe_rel, sha256, HEX40, HEX64
from .execution import require
from .runtime import canonical_bytes, utc
from .source_bridge import load_export, index_export
from .source_capture import exclusive_bytes, _outside_git

SCHEMA = "news-source-sharing-v1"
MAX_BYTES = 160 * 1024 * 1024
MAX_FILES = 1205
REPORT_NAME = "capture_report.json"


def _read(root: Path, name: str) -> bytes:
    require(not reparse_point(root), "SHARED_ROOT_REPARSE")
    return read_bounded(checked_file(root, name))


def _capture_view(root: Path, *, as_of: str, top_n: int) -> dict:
    report = json_load(_read(root, REPORT_NAME))
    require(report.get("schema") == "sec-capture-report-p0.3", "SHARED_REPORT_SCHEMA")
    require(report.get("status") in {"CAPTURED_REVIEW_REQUIRED", "PARTIAL_BLOCKED"}, "SHARED_CAPTURE_STATUS")
    require(report.get("historical_training_run") is False and report.get("has_price_or_security_approval") is False,
            "SHARED_CAPTURE_AUTHORITY")
    export = root / "source_export"
    m, files, _ = load_export(export, now=as_of, index_only=True)
    require(sha256(_read(export, "export_manifest.json")) == report.get("export_manifest_sha256"), "SHARED_EXPORT_HASH")
    require(utc(report["generated_at"]) == utc(m["generated_at"]) <= utc(as_of), "SHARED_GENERATED_AT")
    ix = index_export(m, files)
    raw_urls = {f["source_url"] for f in m["files"] if f["role"] == "raw_object"}
    refs = []
    for row in ix["candidates"]:
        # This is a deterministic filing preview, NOT a score-based selection.
        refs.append({k: row[k] for k in (
            "candidate_id", "cik", "accession_number", "form_type", "filing_date",
            "accepted_at", "source_public_at", "primary_document_url",
            "descriptive_event_tags", "is_amendment", "blockers")})
        refs[-1]["primary_bytes_captured"] = row["primary_document_url"] in raw_urls
    require(len(refs) == report["indexed_filing_candidates"], "SHARED_CANDIDATE_COUNT")
    captured = sum(x["primary_bytes_captured"] for x in refs)
    require(captured == report["captured_documents"], "SHARED_DOCUMENT_COUNT")
    complete = (report["status"] == "CAPTURED_REVIEW_REQUIRED"
                and not ix["unresolved_history_urls"]
                and report.get("history_pages_complete") is True
                and captured == len(refs) and not report.get("blockers"))
    return {
        "schema_version": "news-source-consumer-view-v1",
        "status": "SOURCE_CAPTURE_REVIEW_REQUIRED" if complete else "PARTIAL_SOURCE_CAPTURE",
        "source_commit": m["source_commit"], "generated_at": m["generated_at"],
        "data_cutoff": m["data_cutoff"], "window_start": m["window_start"], "window_end": m["window_end"],
        "indexed_filing_count": len(refs), "captured_primary_count": captured,
        "excluded_count": len(ix["excluded_records"]),
        "missing_history_urls": ix["unresolved_history_urls"],
        "capture_blockers": report["blockers"], "filing_preview": refs[:top_n],
        "preview_order": "FILING_DATE_THEN_CANDIDATE_ID_NOT_INVESTMENT_RANK",
        "whole_market_coverage_certified": False, "historical_pit_certified": False,
        "research_only": True, "model_training_eligible": False, "selector_eligible": False,
        "official_score_contribution": 0, "expected_returns": None,
        "price_as_of": None, "rs": None, "theme_breadth": None,
    }


def build_shared_capture(capture_root: Path, attempt_id: str, output: Path, *, as_of: str,
                         synthetic: bool = False) -> dict:
    require(type(synthetic) is bool, "SHARED_SYNTHETIC_TYPE")
    require(type(attempt_id) is str and len(attempt_id) == 32 and
            all(c in "0123456789abcdef" for c in attempt_id), "SHARED_ATTEMPT_ID")
    output = Path(output); _outside_git(output)
    require(not output.exists(), "SHARED_OUTPUT_EXISTS")
    report = json_load(_read(Path(capture_root), f"attempts/{attempt_id}/CAPTURE_REPORT.json"))
    require(report.get("attempt_id") == attempt_id, "SHARED_REPORT_ATTEMPT")
    export = Path(capture_root) / "exports" / attempt_id
    m, files, _ = load_export(export, now=as_of, index_only=True)
    require(HEX40.fullmatch(m["source_commit"]) is not None, "SHARED_SOURCE_SHA")
    # Only the declared export members, not arbitrary files or a caller-supplied export_dir.
    objects = {"source_export/export_manifest.json": _read(export, "export_manifest.json"),
               REPORT_NAME: canonical_bytes({k:v for k,v in report.items() if k != "export_dir"})}
    objects.update({"source_export/" + safe_rel(name): raw for name, raw in files.items()})
    require(len(objects) <= MAX_FILES and sum(map(len, objects.values())) <= MAX_BYTES, "SHARED_BUDGET")
    for rel, raw in objects.items():
        exclusive_bytes(output / rel, raw)
    view = _capture_view(output, as_of=as_of, top_n=5)
    manifest = {"schema_version": SCHEMA, "record_role": "CAPTURE_EXCHANGE_NOT_ACCEPTED_MODEL_STATE",
                "source_commit": m["source_commit"], "generated_at": m["generated_at"],
                "data_cutoff": m["data_cutoff"], "attempt_id": attempt_id,
                "synthetic": synthetic, "research_only": True, "selector_eligible": False,
                "model_training_eligible": False,
                "files": [{"path": rel, "sha256": sha256(raw), "bytes": len(raw)}
                          for rel, raw in sorted(objects.items())]}
    raw = canonical_bytes(manifest)
    exclusive_bytes(output / "manifest.json", raw)
    checked = read_shared_capture(output, expected_manifest_sha256=sha256(raw), as_of=as_of,
                                  allow_synthetic=synthetic, max_age_hours=72)
    require(checked["indexed_filing_count"] == view["indexed_filing_count"], "SHARED_READBACK")
    return {"manifest_sha256": sha256(raw), "bytes": sum(map(len, objects.values())),
            "file_count": len(objects), "consumer": checked}


def read_shared_capture(root: Path, *, expected_manifest_sha256: str, as_of: str,
                        top_n: int = 5, allow_synthetic: bool = False,
                        max_age_hours: int = 72) -> dict:
    require(type(top_n) is int and 0 <= top_n <= 5, "SHARED_TOP_LIMIT")
    require(type(max_age_hours) is int and 1 <= max_age_hours <= 720, "SHARED_FRESHNESS_POLICY")
    require(type(allow_synthetic) is bool, "SHARED_SYNTHETIC_POLICY")
    require(type(expected_manifest_sha256) is str and HEX64.fullmatch(expected_manifest_sha256), "SHARED_MANIFEST_PIN")
    root = Path(root)
    raw = _read(root, "manifest.json")
    require(sha256(raw) == expected_manifest_sha256, "SHARED_MANIFEST_HASH")
    manifest = json_load(raw)
    require(manifest.get("schema_version") == SCHEMA, "SHARED_SCHEMA")
    require(manifest.get("record_role") == "CAPTURE_EXCHANGE_NOT_ACCEPTED_MODEL_STATE", "SHARED_ROLE")
    require(manifest.get("research_only") is True and manifest.get("selector_eligible") is False and
            manifest.get("model_training_eligible") is False, "SHARED_AUTHORITY")
    require(type(manifest.get("synthetic")) is bool, "SHARED_SYNTHETIC_TYPE")
    require(not manifest["synthetic"] or allow_synthetic, "SHARED_SYNTHETIC_BLOCKED")
    age = utc(as_of) - utc(manifest["generated_at"])
    require(timedelta(0) <= age <= timedelta(hours=max_age_hours), "SHARED_STALE_OR_FUTURE")
    require(utc(manifest["data_cutoff"]) <= utc(manifest["generated_at"]), "SHARED_CUTOFF")
    fs = manifest.get("files")
    require(type(fs) is list and 2 <= len(fs) <= MAX_FILES, "SHARED_FILE_COUNT")
    seen, total = set(), 0
    for entry in fs:
        rel = safe_rel(entry["path"])
        require(rel == REPORT_NAME or rel.startswith("source_export/"), "SHARED_PATH_ROLE")
        require(rel not in seen, "SHARED_DUPLICATE_PATH"); seen.add(rel)
        data = _read(root, rel); total += len(data)
        require(type(entry["bytes"]) is int and entry["bytes"] == len(data)
                and entry["sha256"] == sha256(data), "SHARED_FILE_HASH")
        require(total <= MAX_BYTES, "SHARED_BUDGET")
    actual = set()
    for p in root.rglob("*"):
        require(not reparse_point(p), "SHARED_REPARSE_POINT")
        if p.is_file(): actual.add(p.relative_to(root).as_posix())
    require(actual == seen | {"manifest.json"}, "SHARED_UNDECLARED_OR_MISSING_FILE")
    view = _capture_view(root, as_of=as_of, top_n=top_n)
    require(view["source_commit"] == manifest["source_commit"] and
            view["generated_at"] == manifest["generated_at"] and
            view["data_cutoff"] == manifest["data_cutoff"], "SHARED_PROVENANCE")
    report = json_load(_read(root, REPORT_NAME))
    require(report["attempt_id"] == manifest["attempt_id"], "SHARED_REPORT_ATTEMPT")
    view.update({"manifest_sha256": expected_manifest_sha256, "synthetic": manifest["synthetic"],
                 "manifest_integrity_verified": True, "reader_version": SCHEMA})
    return view


def read_capture_attempt(root: Path, *, as_of: str, top_n: int = 5,
                         allow_synthetic: bool = False) -> dict:
    """Read an explicitly selected run. A missing/failed terminal never falls back."""
    root = Path(root)
    start_raw = _read(root, "STARTED.json")
    start = json_load(start_raw)
    terminal = json_load(_read(root, "TERMINAL.json"))
    require(start.get("schema") == "news-capture-attempt-v1" and
            terminal.get("schema") == "news-capture-terminal-v1", "SHARED_ATTEMPT_SCHEMA")
    require(terminal.get("status") in {"SOURCE_CAPTURE_REVIEW_REQUIRED", "PARTIAL_SOURCE_CAPTURE"}
            and terminal.get("consumer_readback_verified") is True, "SHARED_ATTEMPT_NOT_COMPLETED")
    require(start["run_key"] == terminal["run_key"] and
            sha256(start_raw) == terminal["started_sha256"], "SHARED_ATTEMPT_LINK")
    require(utc(start["started_at"]) <= utc(terminal["finished_at"]) <= utc(as_of), "SHARED_ATTEMPT_CLOCK")
    require(start.get("selector_eligible") is False and terminal.get("selector_eligible") is False
            and terminal.get("model_training_eligible") is False, "SHARED_ATTEMPT_AUTHORITY")
    view = read_shared_capture(root / "bundle", expected_manifest_sha256=terminal["manifest_sha256"],
                               as_of=as_of, top_n=top_n, allow_synthetic=allow_synthetic)
    require(start["source_commit"] == terminal["source_commit"] == view["source_commit"], "SHARED_ATTEMPT_SOURCE")
    require(terminal["captured_primary_count"] == view["captured_primary_count"] and
            terminal["status"] == view["status"], "SHARED_ATTEMPT_RESULT")
    view.update({"run_key": terminal["run_key"], "selection_mode": "PINNED_RUN_NOT_AUTO_LATEST"})
    return view
