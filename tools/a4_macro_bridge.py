"""Replay verified Lake current originals into the incumbent CSV contract.

No collection, permission grant, historical PIT inference or accepted write.
The JSON original and the consumed CSV have separate, reproducible identities.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import re
from pathlib import Path

from tools import macro_history_sources as source

SCHEMA = "a4-macro-normalization-v1"
MAX_SERIES = 40
MAX_TOTAL_BYTES = 64 * 1024**2


def normalize_current(raw, *, series_id, start, through, collected_at):
    source.require(type(series_id) is str and re.fullmatch(r"[A-Z][A-Z0-9]{0,39}", series_id),
                   "a4_series_identity")
    source.require(type(raw) is bytes and 0 < len(raw) <= source.MAX_BYTES, "a4_raw_bounds")
    records, missing = source.parse_current([raw], series_id, start, through, collected_at)
    values = {r["observation_date"]: r["value"] for r in records}
    source.require(not set(values).intersection(missing), "a4_null_conflict")
    values.update({day: None for day in missing})
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["observation_date", series_id])
    writer.writerows((day, "." if value is None else repr(value)) for day, value in sorted(values.items()))
    normalized = stream.getvalue().encode("utf-8")
    manifest = dict(schema=SCHEMA, source_id="fred:"+series_id,
        series_id=series_id, requested_start=start, requested_through=through,
        collected_at=collected_at, available_at=collected_at, published_at=None,
        original_format="FRED_CURRENT_API_JSON" if source._is_current_api_object(raw) else "FRED_GRAPH_CSV",
        original_sha256=source.digest(raw), normalized_sha256=source.digest(normalized),
        observation_count=len(values), missing_observation_dates=sorted(missing),
        truth_class="FREE_PROXY_CURRENT_VINTAGE", historical_pit_certified=False,
        source_admission_allowed=False, learning_permission_granted=False)
    return normalized, manifest


def verify_normalization(original, normalized, manifest):
    source.require(type(manifest) is dict and manifest.get("schema") == SCHEMA, "a4_normalization_schema")
    actual, expected = normalize_current(original, series_id=manifest.get("series_id"),
        start=manifest.get("requested_start"), through=manifest.get("requested_through"),
        collected_at=manifest.get("collected_at"))
    # Extra caller flags cannot grant rights, clocks or admission.
    source.require(manifest == expected and actual == normalized, "a4_normalization_mismatch")
    return expected


def lake_current_inputs(lake, *, series_ids, commit_sha256, catalog_sha256,
                        execution_sha256, cutoff):
    """Use a caller's already configured Lake, including its native full restore.

    Expected identities come from the reviewed request, never a latest fallback.
    A storage-only generation or an incomplete study is refused before row reads.
    """
    source.require(type(series_ids) is list and 0 < len(series_ids) <= MAX_SERIES
                   and len(set(series_ids)) == len(series_ids), "a4_series_scope")
    for pin in (commit_sha256, catalog_sha256, execution_sha256):
        source.require(type(pin) is str and re.fullmatch(r"[a-f0-9]{64}", pin), "a4_lake_pin")
    source.require(lake.parent == commit_sha256 and not lake.pending and lake.catalog == lake.before,
                   "a4_lake_not_clean_or_current")
    commit = json.loads(lake.read_hash("commits", commit_sha256))
    source.require(commit["catalog"] == catalog_sha256, "a4_catalog_pin")
    receipt = lake.verified_execution()
    source.require(receipt["execution_receipt_sha256"] == execution_sha256
                   and receipt.get("study_recomputed_from_drive") is True, "a4_execution_incomplete")
    decision = source.stamp(cutoff)
    entries = []
    for sid in series_ids:
        source.require(type(sid) is str and re.fullmatch(r"[A-Z][A-Z0-9]{0,39}", sid), "a4_series_identity")
        entry = lake.catalog["datasets"].get("current/"+sid, {})
        source.require(entry.get("status") in {"COLLECTED", "UNCHANGED"}
                       and entry.get("evidence") == "current_only" and entry.get("series") == sid,
                       "a4_dataset_unavailable")
        source.require(source.stamp(entry["retrieved_at"]) <= decision, "a4_source_after_cutoff")
        source.require(len(entry.get("raw_objects", [])) == 1
                       and not entry.get("retained_source_objects"), "a4_original_scope")
        entries.append((sid, entry))
    result, used = [], 0
    for sid, entry in entries:
        packed = lake.get_bytes(entry["raw_objects"][0])
        source.require(source.digest(packed) == entry["raw_objects"][0], "a4_original_object_hash")
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as handle:
            original = handle.read(min(source.MAX_BYTES, MAX_TOTAL_BYTES-used)+1)
        source.require(len(original) <= min(source.MAX_BYTES, MAX_TOTAL_BYTES-used), "a4_raw_bounds")
        normalized, manifest = normalize_current(original, series_id=sid,
            start=entry["requested_start"], through=entry["requested_through"],
            collected_at=entry["retrieved_at"])
        used += len(original) + len(normalized)
        source.require(used <= MAX_TOTAL_BYTES, "a4_bundle_byte_budget")
        rows = lake.get_records("current/"+sid)
        parsed, _ = source.parse_current([original], sid, entry["requested_start"],
                                         entry["requested_through"], entry["retrieved_at"])
        projection = lambda rs: [(r["series"], r["observation_date"], r["value"],
                                  r.get("published_at"), r.get("vintage_date"), r["evidence"])
                                 for r in rs]
        source.require(projection(rows) == projection(parsed), "a4_original_normalized_parity")
        result.append(dict(original=original, normalized=normalized, manifest=manifest,
            lake_raw_object_sha256=entry["raw_objects"][0],
            lake_normalized_object_sha256=entry["normalized"], status=entry["status"]))
    source.require(lake.restore_catalog()[0] == commit_sha256, "a4_lake_head_changed")
    return dict(schema="a4-lake-inputs-v1", commit_sha256=commit_sha256,
        catalog_sha256=catalog_sha256, execution_receipt_sha256=execution_sha256,
        cutoff=cutoff, sources=result, network_collection_executed=False,
        source_admission_allowed=False, historical_pit_certified=False)


def store_bundle(bundle, root):
    """Create-only local preparation, never a durable accepted publication."""
    root = Path(root)
    source.require(not root.is_symlink(), "a4_output_symlink")
    for parent in root.parents:
        source.require(not parent.is_symlink(), "a4_output_symlink")
    files, entries = {}, []
    for item in bundle["sources"]:
        manifest = item["manifest"]
        verify_normalization(item["original"], item["normalized"], manifest)
        sid = manifest["series_id"]
        original_path, csv_path = "originals/"+sid+".raw", "fred/"+sid+".csv"
        files[original_path], files[csv_path] = item["original"], item["normalized"]
        entries.append(dict(manifest=manifest, original_path=original_path, normalized_path=csv_path,
            lake_raw_object_sha256=item["lake_raw_object_sha256"],
            lake_normalized_object_sha256=item["lake_normalized_object_sha256"], status=item["status"]))
    receipt = {k: v for k, v in bundle.items() if k != "sources"}
    receipt.update(sources=entries, durable_publication_verified=False)
    files["normalization.json"] = source.encoded(receipt)
    # Preflight every existing destination before any write; partial attempts
    # are resumable only with identical bytes, and never replace accepted data.
    for name, raw in files.items():
        path = root / name
        source.require(not any(p.is_symlink() for p in (path, *path.parents)), "a4_output_symlink")
        source.require(not path.exists() or path.read_bytes() == raw, "a4_output_conflict")
    for name, raw in files.items():
        path = root / name
        if not path.exists():
            source.exclusive(path, raw)
        source.require(path.read_bytes() == raw, "a4_output_readback")
    return receipt
