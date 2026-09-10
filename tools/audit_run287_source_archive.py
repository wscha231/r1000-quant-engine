#!/usr/bin/env python3
"""Read-only audit of the frozen source ZIP. No archive code or ledger writer runs."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

REPOSITORY = "wscha231/r1000-quant-engine"
ARTIFACT_ID = 8088582521
RUN_ID = 28725350727
SOURCE_SHA = "15176b588d5bb0792bce1df6367758d795a8a33a"
ARCHIVE_BYTES = 369243166
ARCHIVE_SHA256 = "ebdbbe7e764b735ca129f662c42ec80b68659f4e3196b5a364cf32c506c4c818"
MAX_MEMBERS, MAX_EXPANDED_BYTES = 50000, 8_000_000_000
DATE_FIELDS = ("rebalance_date", "date", "session", "valuation_price_cutoff_date", "feature_available_from")
CSV_NAMES = {"candidate_replay_book.csv", "candidate_replay_book_sec_enriched.csv",
    "operating_main_target_book.csv", "operating_concentrated_target_book.csv",
    "official_main_target_book.csv", "official_concentrated_target_book.csv"}
CACHE_PARTS = {"cache_prices", "price_cache", "replay_price_cache", "cache_ohlcv"}
EXPECTED = {
    "raw_candidate_replay_book": ("outputs/reports/candidate_replay_book.csv", "2b4bc9db22e573f07e91bcdd94db51c6ce4381dacc7e4268618b189d09eaaafc"),
    "candidate_replay_book": ("outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv", "7ffa0b27382d303008ffca55878b259ccf7f11beaee28be6f1e4653c30e97989"),
    "selector_metadata": ("outputs/alphaops_vnext/summary.json", "dff267f66964c499ad8095f456949648aae29d8111de66f4d5c3a85a620b644a"),
    "target_generation_input_manifest": ("outputs/alphaops_vnext/target_generation_input_manifest.json", "7451166d8132c7e3fbd3eb75f7ecdd095e86e482b9202c2e0e0a2b1189ba6ff7"),
    "long_crisis_features": ("data_pit/macro/long_crisis_daily_features.parquet", "0059b029d0f304c5030b78c5673cc430d4307904e06e6fb425b7ce6c27fe3ffc"),
    "long_crisis_thresholds": ("outputs/long_crisis_learning/best_thresholds.json", "d108c017e301f6929e1441827d5a19c02beb0d89727dbbff40f94f3e504d2da2"),
}


def sha256(stream):
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(block)
    return result.hexdigest()


def safe_members(archive):
    members = archive.infolist()
    if len(members) > MAX_MEMBERS or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
        raise ValueError("archive_size_bound")
    names = set()
    for member in members:
        name = member.filename
        p = PurePosixPath(name)
        if (not name or len(name) > 512 or p.is_absolute() or ".." in p.parts or
                "\\" in name or ":" in name or any(ord(c) < 32 for c in name) or
                str(p).casefold() in names or stat.S_ISLNK(member.external_attr >> 16) or
                member.flag_bits & 1):
            raise ValueError("unsafe_or_duplicate_archive_member")
        names.add(str(p).casefold())
    return [m for m in members if not m.is_dir()]


def iso_day(value):
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[ T])", text):
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def csv_coverage(stream):
    reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
    fields = set(reader.fieldnames or [])
    selected = [key for key in DATE_FIELDS if key in fields]
    ranges = {key: {"first": None, "last": None, "invalid_or_missing": 0} for key in selected}
    rows, tickers, decision_days, late_features, later_prices = 0, set(), set(), 0, 0
    for row in reader:
        rows += 1
        if rows > 10_000_000:
            raise ValueError("csv_row_bound")
        if row.get("ticker"):
            tickers.add(row["ticker"])
        observed = {}
        for key in selected:
            day = iso_day(row.get(key)); observed[key] = day
            r = ranges[key]
            if day is None:
                r["invalid_or_missing"] += 1
            else:
                r["first"] = min(r["first"] or day, day)
                r["last"] = max(r["last"] or day, day)
        decision = observed.get("rebalance_date")
        if decision:
            decision_days.add(decision)
            late_features += bool(observed.get("feature_available_from") and observed["feature_available_from"] > decision)
            later_prices += bool(observed.get("valuation_price_cutoff_date") and observed["valuation_price_cutoff_date"] > decision)
    return {"rows": rows, "unique_tickers": len(tickers), "dates": ranges,
        "decision_sessions": len(decision_days), "has_2019_05_31_decision": "2019-05-31" in decision_days,
        "features_after_decision_day_rows": late_features, "prices_after_decision_day_rows": later_prices,
        "intraday_pit_verified": False, "required_provenance_columns_present":
        all(k in fields for k in ("valuation_price_cutoff_date", "feature_available_from"))}


def parquet_coverage(archive, member):
    import pyarrow.parquet as pq
    if member.file_size > 1_000_000_000:
        raise ValueError("parquet_file_bound")
    with tempfile.TemporaryFile() as tmp:
        with archive.open(member) as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                tmp.write(block)
        tmp.seek(0)
        parquet = pq.ParquetFile(tmp)
        columns = parquet.schema_arrow.names
        selected = next((c for c in ("date", "Date", "session", "timestamp", "Datetime", "__index_level_0__") if c in columns), None)
        first, last, invalid, observations = None, None, 0, 0
        if selected:
            for batch in parquet.iter_batches(columns=[selected]):
                for value in batch.column(0).to_pylist():
                    observations += 1; day = iso_day(value)
                    if day is None: invalid += 1
                    else: first, last = min(first or day, day), max(last or day, day)
        return {"rows": parquet.metadata.num_rows, "date_observations": observations,
            "first": first, "last": last, "invalid_dates": invalid, "date_column_found": selected is not None,
            "has_close_column": any(c.lower() in {"close", "adj close", "adj_close"} for c in columns)}


def metric_summary(value):
    """Only known scalar diagnostics; never dump account/provider/config bodies."""
    allowed = {"cagr", "max_drawdown", "mdd", "sharpe", "sortino", "calmar", "trading_days", "observations",
               "start_date", "end_date", "current_survivors_only", "delisting_coverage_claimed", "pit_universe_label_clean"}
    result = {}
    if isinstance(value, dict):
        for key in allowed & value.keys():
            v = value[key]
            if isinstance(v, bool) or (type(v) in (int, float) and math.isfinite(v)):
                result[key] = v
            elif key in {"start_date", "end_date"} and iso_day(v):
                result[key] = iso_day(v)
    return result


def audit_archive(path, *, expected_hash=ARCHIVE_SHA256, expected_bytes=ARCHIVE_BYTES):
    path = Path(path)
    with path.open("rb") as source: actual_hash = sha256(source)
    matches = actual_hash == expected_hash and path.stat().st_size == expected_bytes
    official = expected_hash == ARCHIVE_SHA256 and expected_bytes == ARCHIVE_BYTES
    result = {"schema_version": "run287-source-archive-audit-v1", "artifact_id": ARTIFACT_ID,
        "source_run_id": RUN_ID, "source_run_head": SOURCE_SHA,
        "archive_bytes": path.stat().st_size, "archive_sha256": actual_hash,
        "data_kind": "REAL" if official else "SYNTHETIC_TEST_ONLY",
        "archive_matches_expected": matches, "artifact_identity_verified": matches and official,
        "historical_pit_certified": False, "research_replay_ready": False,
        "orders_allowed": False, "accepted_state_modified": False, "performance_recomputed": False}
    if not matches:
        return dict(result, status="SOURCE_IDENTITY_FAILED")
    with zipfile.ZipFile(path) as archive:
        members = safe_members(archive)
        result.update(member_count=len(members), expanded_bytes=sum(m.file_size for m in members))
        anchors = {}
        for key, (suffix, expected) in EXPECTED.items():
            matches = [m for m in members if m.filename == suffix or m.filename.endswith("/" + suffix)]
            entry = {"match_count": len(matches), "hash_verified": False}
            if len(matches) == 1:
                with archive.open(matches[0]) as source: entry["sha256"] = sha256(source)
                entry["hash_verified"] = entry["sha256"] == expected
            anchors[key] = entry
        result["contract_files"] = anchors
        result["books"], result["reported_metric_files"] = [], []
        prices = []
        other_parquet = 0
        for member in members:
            name = PurePosixPath(member.filename).name
            identity = hashlib.sha256(member.filename.encode()).hexdigest()
            if name in CSV_NAMES:
                with archive.open(member) as source: info = csv_coverage(source)
                result["books"].append(dict(info, name=name, member_id=identity))
            elif name == "simulated_fill_metrics.json" and member.file_size <= 2_000_000:
                with archive.open(member) as source: value = json.load(source)
                result["reported_metric_files"].append({"member_id": identity, "reported_only": True,
                                                       "metrics": metric_summary(value)})
            elif name.endswith(".parquet"):
                if CACHE_PARTS & set(PurePosixPath(member.filename).parts):
                    prices.append(dict(parquet_coverage(archive, member), member_id=identity))
                else: other_parquet += 1
        covered = [p for p in prices if p["first"] and p["last"]]
        result["price_cache"] = {"parquet_files": len(prices), "other_parquet_files": other_parquet,
            "date_scanned_files": len(covered), "total_rows": sum(p["rows"] for p in prices),
            "earliest_date": min((p["first"] for p in covered), default=None),
            "latest_date": max((p["last"] for p in covered), default=None),
            "common_start": max((p["first"] for p in covered), default=None),
            "common_end": min((p["last"] for p in covered), default=None),
            "all_files_dated": bool(prices) and len(covered) == len(prices) and all(p["invalid_dates"] == 0 for p in prices),
            "file_observations_hash": hashlib.sha256(json.dumps(prices,sort_keys=True).encode()).hexdigest(),
            "missing_session_and_lifecycle_checks_completed": False}
        result["status"] = "AUDIT_COMPLETED"
        result["next_gate"] = "source_only_and_post_book_preflight_with_verified_price_lifecycle_and_pit_inputs"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--download", action="store_true", help="Fetch only the fixed official artifact via existing gh authentication.")
    args = parser.parse_args()
    path = Path(args.zip)
    try:
        if args.download:
            if path.exists(): raise ValueError("download_destination_exists")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as target:
                p = subprocess.run(["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}/zip"],
                                   stdout=target, stderr=subprocess.DEVNULL, timeout=300, check=False)
            if p.returncode: raise ValueError("source_download_failed")
        report = audit_archive(path)
    except Exception as exc:
        safe = {"archive_size_bound", "unsafe_or_duplicate_archive_member", "csv_row_bound", "parquet_file_bound",
                "download_destination_exists", "source_download_failed"}
        report = {"status": "AUDIT_FAILED", "reason": str(exc) if str(exc) in safe else type(exc).__name__,
                  "orders_allowed": False, "accepted_state_modified": False, "performance_recomputed": False}
    source_sha = os.environ.get("AUDIT_SOURCE_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", source_sha): report["audit_source_commit"] = source_sha
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        target.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("SOURCE_AUDIT_JSON=" + json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "AUDIT_COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
