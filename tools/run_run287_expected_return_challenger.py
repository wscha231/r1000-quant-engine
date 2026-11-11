#!/usr/bin/env python3
"""Train a PIT-purged, proposal-only Run287 expected-return challenger.

The real historical path is fail-closed behind canonical U0-v3 acceptance.
This program never writes target books, creates orders, changes cash, mutates an
operating ledger, promotes a challenger, or runs a full rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-expected-return-challenger-v1"
READY_STATUS = "READY_EXPECTED_RETURN_FORWARD_REVIEW_ONLY"
BLOCKED_STATUS = "BLOCKED_EXPECTED_RETURN_CHALLENGER"
TARGET_KINDS = ("absolute", "benchmark_excess", "sector_neutral")
HORIZONS = (21, 63, 126)
EXPECTED_CONTRACT_SHA256 = (
    "ef61acafc2c42b86d75d85becea816a4bca8e05fbbc392e77fa92b075c728b63"
)
FORBIDDEN_FEATURE_RE = re.compile(
    r"(^|_)(future|forward|label|target|outcome)(_|$)|"
    r"^r_(1m|3m|6m|12m|24m|36m)$|^bench_(r|ret)_",
    re.IGNORECASE,
)
NYSE = mcal.get_calendar("NYSE")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = "wscha231/r1000-quant-engine"
PRE_FIT_BINDING_SCHEMA = "run287-stock-leader-pre-fit-binding-v1"
PRE_FIT_MAX_FILE = 64 * 1024 * 1024
PRE_FIT_MAX_TOTAL = 128 * 1024 * 1024
PRE_FIT_MAX_FEATURE_STORE = 32 * 1024 * 1024
PRE_FIT_MAX_DECODED = 128 * 1024 * 1024
PRE_FIT_MAX_ROWS = 100000
PRE_FIT_ROLES = {"universe", "decisions", "features", "labels", "reader_requests", "experiment"}
PRE_FIT_DATASETS = {"prices": "ds.us.prices.daily", "financial": "ds.us.financials.sec.companyfacts"}
EX_POST_FEATURE_RE = re.compile(r"(^|_)(onset|peak|phase_offset|event_selected|hold_18m)(_|$)", re.I)


def _binding_need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("pre_fit_binding:" + reason)


def _binding_stamp(value: Any) -> pd.Timestamp:
    _binding_need(type(value) is str, "clock_required")
    result = pd.Timestamp(value)
    _binding_need(not pd.isna(result) and result.tzinfo is not None, "aware_clock_required")
    return result.tz_convert("UTC")


def _binding_json(raw: bytes):
    def invalid(value):
        raise ValueError("pre_fit_binding:nonfinite_json_constant")
    return json.loads(raw, object_pairs_hook=reject_duplicate_json_keys, parse_constant=invalid)


def _binding_key(row: Mapping[str, Any]) -> tuple[str, str]:
    _binding_need(type(row) is dict, "row_object")
    ticker = row.get("ticker")
    _binding_need(type(ticker) is str and bool(ticker.strip()), "ticker_required")
    return (pd.Timestamp(row["feature_date"]).date().isoformat(),
            ticker.strip().upper().replace(".", "-"))


def _binding_features(row: Mapping[str, Any], names: list[str]) -> str:
    # The V1's optional 21-session timing columns may be absent. Hash that
    # absence explicitly; required 63/126 inputs still pass prepare_frame.
    return canonical_sha256({name: json_clean(row.get(name)) for name in names})


def validate_pre_fit_binding(frame: pd.DataFrame, binding: Mapping[str, Any],
                             contract: Mapping[str, Any], *, feature_store_sha256: str,
                             artifact_resolver) -> dict[str, Any]:
    """Offline input integrity, NOT Source authentication or training permission.

    Keep the full as-of denominator, including unselected/blocked/UNKNOWN rows.
    No report timestamp or retrospective winner/event cohort can replace it.
    Actual training additionally replays the existing public Reader in training
    mode and then the unchanged live canonical U0 and V1 model gates.
    """
    validate_contract(contract)  # Immutable V1 bytes/digest and feature roles.
    fields = {"schema", "decision_time", "feature_store_sha256", "contract_sha256", "code_sha", "refs"}
    _binding_need(type(binding) is dict and set(binding) == fields and
                  binding["schema"] == PRE_FIT_BINDING_SCHEMA, "schema")
    _binding_need(binding["feature_store_sha256"] == feature_store_sha256 and
                  SHA256_RE.fullmatch(feature_store_sha256) is not None, "feature_store_hash")
    _binding_need(binding["contract_sha256"] == EXPECTED_CONTRACT_SHA256 and
                  FULL_SHA_RE.fullmatch(binding["code_sha"]) is not None, "code_contract_identity")
    decision = _binding_stamp(binding["decision_time"])
    _binding_need(decision <= pd.Timestamp.now(tz="UTC"), "future_decision")
    _binding_need(type(binding["refs"]) is dict and set(binding["refs"]) == PRE_FIT_ROLES, "reference_roles")
    values, charged, reference_hashes = {}, 0, {}
    for role, ref in binding["refs"].items():
        _binding_need(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}, "reference_fields")
        _binding_need(type(ref["bytes"]) is int and 0 < ref["bytes"] <= PRE_FIT_MAX_FILE and
                      type(ref["sha256"]) is str and SHA256_RE.fullmatch(ref["sha256"]) is not None,
                      "reference_budget_or_hash")
        raw = artifact_resolver(ref)
        _binding_need(type(raw) is bytes, "reference_bytes:" + role)
        charged += len(raw)
        _binding_need(type(raw) is bytes and len(raw) == ref["bytes"] and
                      charged <= PRE_FIT_MAX_TOTAL and
                      hashlib.sha256(raw).hexdigest() == ref["sha256"], "reference_bytes:" + role)
        values[role] = _binding_json(raw)
        _binding_need(type(values[role]) is dict, "reference_object:" + role)
        reference_hashes[role] = ref["sha256"]
    features = sorted({name for names in contract["features"].values() for name in names})
    _binding_need(not any(FORBIDDEN_FEATURE_RE.search(name) or EX_POST_FEATURE_RE.search(name)
                          for name in features), "ex_post_feature")
    dates = pd.to_datetime(frame["feature_date"], errors="coerce")
    _binding_need(not dates.isna().any(), "feature_date")
    completed = _v2_h1_last_completed_nyse_session(decision)
    asof_frame = frame.loc[dates.dt.normalize() <= completed].copy()
    prepared = prepare_frame(asof_frame, contract)  # Original rules; retain unlabelled latest rows.
    records = {_binding_key(row): row for row in asof_frame.to_dict("records")}
    _binding_need(len(records) == len(asof_frame) and bool(records), "frame_identity")
    _binding_need(any(key[0] == completed.date().isoformat() for key in records), "latest_prediction_rows_missing")
    def rows_by_key(role):
        rows = values[role].get("rows")
        _binding_need(type(rows) is list, "rows:" + role)
        result = {_binding_key(row): row for row in rows}
        _binding_need(len(result) == len(rows) and set(result) == set(records), "full_denominator:" + role)
        return result
    universe, actions, clocks = (rows_by_key(role) for role in ("universe", "decisions", "features"))
    statuses = {"SELECTED", "UNSELECTED", "BLOCKED", "UNKNOWN"}
    actions_allowed = {"ENTRY", "ADD", "HOLD", "TRIM", "EXIT", "NO_ENTRY", "UNSELECTED", "BLOCKED", "UNKNOWN"}
    counts = {status: 0 for status in sorted(statuses)}
    completed_cache = {}
    for key, row in records.items():
        member, action, clock = universe[key], actions[key], clocks[key]
        _binding_need(member.get("selection_status") in statuses and
                      type(member.get("issuer_id")) is str and bool(member["issuer_id"]) and
                      type(member.get("reader_instrument_ids")) is dict and
                      set(member["reader_instrument_ids"]) == {"prices", "financial"} and
                      all(type(value) is str and bool(value) for value in member["reader_instrument_ids"].values()),
                      "universe_identity")
        counts[member["selection_status"]] += 1
        _binding_need(action.get("selection_status") == member["selection_status"] and
                      action.get("action") in actions_allowed and
                      type(action.get("original_decision_sha256")) is str and
                      SHA256_RE.fullmatch(action["original_decision_sha256"]) is not None, "decision_original")
        if action["action"] == "EXIT":
            _binding_need(action.get("exit_reason") in {"THESIS", "RISK", "REPLACEMENT", "LIFECYCLE"}, "exit_taxonomy")
        original_cutoff = _binding_stamp(clock.get("decision_at"))
        if original_cutoff not in completed_cache:
            completed_cache[original_cutoff] = _v2_h1_last_completed_nyse_session(original_cutoff)
        _binding_need(_binding_stamp(clock.get("available_at")) <= original_cutoff <= decision and
                      completed_cache[original_cutoff] == pd.Timestamp(key[0]),
                      "feature_availability")
        _binding_need(clock.get("feature_sha256") == _binding_features(row, features), "feature_row_hash")
    requests = values["reader_requests"].get("requests")
    _binding_need(type(requests) is list and 1 <= len(requests) <= 8, "reader_requests")
    row_sets, source_roles = {}, set()
    for request in requests:
        _binding_need(type(request) is dict, "reader_request_object")
        role = request.get("role")
        _binding_need(role in {"prices", "financial"} and role not in source_roles, "reader_component_roles")
        _binding_need(request.get("dataset_id") == PRE_FIT_DATASETS[role], "reader_role_dataset_identity")
        source_roles.add(role)
        for name in ("data_generation_id", "expected_row_set_sha256"):
            _binding_need(type(request.get(name)) is str and SHA256_RE.fullmatch(request[name]) is not None,
                          "reader_original_hash")
        _binding_need(type(request.get("instrument_ids")) is list and bool(request["instrument_ids"]) and
                      len(request["instrument_ids"]) == len(set(request["instrument_ids"])) and
                      type(request.get("required_sessions")) is list and bool(request["required_sessions"]),
                      "reader_identity_sessions")
        _binding_need(set(member["reader_instrument_ids"][role] for member in universe.values()) <= set(request["instrument_ids"]),
                      "reader_denominator_identity")
        row_sets[role] = request["expected_row_set_sha256"]
    _binding_need(source_roles == {"prices", "financial"}, "financial_and_price_origins_required")
    for clock in clocks.values():
        _binding_need(clock.get("source_row_sets") == row_sets, "feature_source_join")
    label_rows = values["labels"].get("rows")
    _binding_need(type(label_rows) is list, "label_rows")
    labels = {(_binding_key(row), row.get("horizon")): row for row in label_rows}
    _binding_need(len(labels) == len(label_rows) and set(labels) ==
                  {(key, horizon) for key in records for horizon in HORIZONS}, "label_denominator")
    mature = {h: [] for h in HORIZONS}
    label_statuses, training_examples = [], []
    decision_day = completed
    embargo = nyse_embargo_cutoffs([decision_day], contract["purge_and_windows"]["embargo_nyse_sessions"])[decision_day]
    label_closes = {}
    for (key, horizon), label in labels.items():
        row, spec = records[key], contract["horizons"][str(horizon)]
        _binding_need(label.get("benchmark_identity") == contract["data_policy"]["canonical_benchmark"] and
                      label.get("benchmark_source") == contract["data_policy"]["canonical_benchmark_source"] and
                      label.get("source_row_sets") == row_sets, "label_provider_or_source_join")
        required = ("stock_return", "benchmark_return", "stock_label_end", "benchmark_label_end")
        original = {name: json_clean(row[spec[name]]) for name in required}
        _binding_need(all(json_clean(label.get(name)) == original[name] for name in required), "label_original")
        if all(value is not None for value in original.values()):
            available = _binding_stamp(label.get("available_at"))
            end = pd.Timestamp(original["stock_label_end"]).normalize()
            if end not in label_closes:
                schedule = NYSE.schedule(start_date=end, end_date=end)
                _binding_need(not schedule.empty,"label_end_session")
                label_closes[end] = pd.Timestamp(schedule.iloc[0]["market_close"])
            _binding_need(label_closes[end] <= available,
                          "label_availability")
            status = "MATURE" if available < decision else "IMMATURE"
        else:
            _binding_need(label.get("available_at") is None, "unknown_label_not_mature")
            status = "UNKNOWN"
        label_statuses.append(dict(feature_date=key[0],ticker=key[1],horizon=horizon,
                                   status=status,training_eligible=False,
                                   available_at=label.get("available_at")))
    # Sector-neutral targets consume peers' returns. Preserve each original
    # clock above, but use the complete date/horizon's latest clock for training
    # just as V1 already does for the exact outcome-session maturity.
    cohort_clocks = {}
    for item in label_statuses:
        if item["available_at"] is not None:
            group = (item["feature_date"], item["horizon"])
            available = _binding_stamp(item["available_at"])
            cohort_clocks[group] = max(cohort_clocks.get(group, available), available)
    for item in label_statuses:
        key, horizon = (item["feature_date"], item["ticker"]), item["horizon"]
        available = cohort_clocks.get((key[0], horizon))
        item["training_available_at"] = available.isoformat() if available is not None else None
        eligible = (item["status"] == "MATURE" and available.tz_localize(None) < decision_day
                    and embargo is not None and pd.Timestamp(key[0]) <= embargo)
        item["training_eligible"] = eligible
        if eligible:
            mature[horizon].append(key[0])
            spec, row = contract["horizons"][str(horizon)], records[key]
            training_examples.append(dict(feature_date=key[0],ticker=key[1],horizon=horizon,
                feature_sha256=clocks[key]["feature_sha256"],
                **{name: json_clean(row[spec[name]]) for name in
                   ("stock_return", "benchmark_return", "stock_label_end", "benchmark_label_end")},
                available_at=item["available_at"], training_available_at=item["training_available_at"]))
    for horizon in (63, 126):
        _binding_need(len(mature[horizon]) >= contract["model"]["minimum_training_rows"] and
                      len(set(mature[horizon])) >= contract["model"]["minimum_training_decision_dates"],
                      "insufficient_mature_training_cohort")
    experiment = values["experiment"]
    _binding_need(type(experiment.get("candidate_id")) is str and bool(experiment["candidate_id"]) and
                  all(type(experiment.get(name)) is str and SHA256_RE.fullmatch(experiment[name]) is not None
                      for name in ("experiment_ledger_sha256", "do_not_repeat_sha256")), "experiment_original_refs")
    return {"schema": PRE_FIT_BINDING_SCHEMA, "status": "PRE_FIT_METADATA_BOUND_NOT_TRAINING_ADMISSION",
            "binding_sha256": canonical_sha256(binding), "decision_time": binding["decision_time"],
            "denominator_rows": len(asof_frame), "outside_decision_prefix_rows": len(frame)-len(asof_frame),
            "selection_counts": counts, "prepared_rows": len(prepared), "labels":label_statuses,
            "training_cohort_sha256":canonical_sha256(sorted(training_examples,key=lambda r:(r["feature_date"],r["ticker"],r["horizon"]))),
            "prediction_keys":[list(key) for key in sorted(records) if key[0]==max(k[0] for k in records)],
            "completed_decision_session":completed.date().isoformat(),
            "training_label_cutoff_exclusive": completed.isoformat(),
            "mature_rows": {str(h): len(mature[h]) for h in HORIZONS},
            "reference_sha256": reference_hashes, "reader_requests": requests,
            "source_authentication": "NOT_REPLAYED", "source_admission_granted": False,
            "selection_source_authentication": "HASH_REFERENCES_NOT_REPLAYED",
            "local_bounds": {"per_reference_bytes": PRE_FIT_MAX_FILE,
                             "reference_total_bytes": PRE_FIT_MAX_TOTAL,
                             "feature_encoded_bytes": PRE_FIT_MAX_FEATURE_STORE,
                             "feature_projected_decoded_bytes": PRE_FIT_MAX_DECODED,
                             "feature_max_rows": PRE_FIT_MAX_ROWS},
            "universe_completeness_certified": False,
            "model_fit": False, "learning_eligible": False, "long_hold_252_audit_only": True}


def _binding_local_file(root: Path, relative: str, limit: int) -> Path:
    _binding_need(type(relative) is str and relative and "\\" not in relative and ":" not in relative,
                  "local_reference_path")
    parts = Path(relative)
    _binding_need(not parts.is_absolute() and all(p not in {".", ".."} for p in parts.parts), "local_reference_path")
    path = root / parts
    _binding_need(not any(p.is_symlink() for p in (path, *path.parents)) and
                  path.resolve(strict=True).is_relative_to(root.resolve(strict=True)) and
                  path.is_file() and 0 < path.stat().st_size <= limit, "local_reference_bounds")
    return path


def load_pre_fit_binding(args: argparse.Namespace, contract: Mapping[str, Any]):
    """Only explicit local inputs; validate limits/hashes before decoding."""
    path = repo_path(args.input_binding)
    expected = getattr(args, "expected_input_binding_sha256", None)
    _binding_need(type(expected) is str and SHA256_RE.fullmatch(expected) is not None, "expected_binding_hash_required")
    _binding_need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)) and
                  0 < path.stat().st_size <= PRE_FIT_MAX_FILE, "binding_file_bounds")
    raw = path.read_bytes()
    _binding_need(hashlib.sha256(raw).hexdigest() == expected, "binding_hash")
    binding = _binding_json(raw)
    root = repo_path(getattr(args, "input_binding_root", None) or path.parent)
    _binding_need(root.is_dir() and not root.is_symlink(), "binding_root")
    feature = repo_path(args.feature_store)
    _binding_need(feature.is_file() and not any(p.is_symlink() for p in (feature, *feature.parents)) and
                  0 < feature.stat().st_size <= PRE_FIT_MAX_FEATURE_STORE, "feature_store_bounds")
    # Check every declared path/budget before reading any referenced body.
    _binding_need(type(binding.get("refs")) is dict and set(binding["refs"]) == PRE_FIT_ROLES, "reference_roles")
    _binding_need(all(type(ref) is dict and type(ref.get("bytes")) is int and
                      0 < ref["bytes"] <= PRE_FIT_MAX_FILE for ref in binding["refs"].values()) and
                  sum(ref["bytes"] for ref in binding["refs"].values()) <= PRE_FIT_MAX_TOTAL, "reference_total_budget")
    paths = {role: _binding_local_file(root, ref["path"], PRE_FIT_MAX_FILE)
             for role, ref in binding["refs"].items()}
    cache = {}
    for role, local in paths.items():
        with local.open("rb") as stream:
            raw = stream.read(PRE_FIT_MAX_FILE + 1)
        _binding_need(len(raw) == binding["refs"][role]["bytes"], "reference_bytes:" + role)
        cache[role] = raw
    resolver = lambda ref: cache[next(role for role, value in binding["refs"].items() if value == ref)]
    # Compressed length does not bound decoded allocation. Inspect the existing
    # Parquet footer and project only the immutable V1 inputs before reading.
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    with feature.open("rb") as stream:
        feature_raw = stream.read(PRE_FIT_MAX_FEATURE_STORE + 1)
    _binding_need(0 < len(feature_raw) <= PRE_FIT_MAX_FEATURE_STORE and
                  hashlib.sha256(feature_raw).hexdigest() == binding["feature_store_sha256"],
                  "feature_store_hash")
    # Decode exactly the bounded buffer whose hash was checked, not a second
    # mutable pathname read after the footer/row verification.
    parquet = pq.ParquetFile(io.BytesIO(feature_raw))
    try:
        schema, meta = parquet.schema_arrow, parquet.metadata
        wanted = set(required_columns(contract)) | {name for names in contract["features"].values() for name in names} | {spec[name] for spec in contract["horizons"].values()
            for name in ("stock_return", "benchmark_return", "stock_label_end", "benchmark_label_end")}
        columns = sorted(wanted & set(schema.names))
        text_columns = []
        for name in columns:
            kind = schema.field(name).type
            if pa.types.is_dictionary(kind):
                kind = kind.value_type
            if pa.types.is_string(kind) or pa.types.is_large_string(kind):
                text_columns.append(name)
            else:
                _binding_need(pa.types.is_null(kind) or pa.types.is_boolean(kind) or
                    pa.types.is_integer(kind) or pa.types.is_floating(kind) or
                    pa.types.is_date(kind) or pa.types.is_timestamp(kind), "unsupported_feature_store_type")
        projected = {schema.names.index(name) for name in columns}
        uncompressed = sum(meta.row_group(r).column(c).total_uncompressed_size
            for r in range(meta.num_row_groups) for c in projected)
        strings = sum(str(schema.field(name).type) in {"string", "large_string"} for name in columns)
        _binding_need(0 < meta.num_rows <= PRE_FIT_MAX_ROWS and len(columns) <= 128 and
            uncompressed + meta.num_rows * (len(columns)*16 + strings*64) <= PRE_FIT_MAX_DECODED,
            "decoded_feature_store_budget")
        # Dictionary/RLE page sizes do not bound expanded repeated strings.
        # Keep them encoded while checking exact value lengths and the maximum
        # row expansion; do not expand into pandas objects first.
        parquet.close()
        parquet = pq.ParquetFile(io.BytesIO(feature_raw), read_dictionary=text_columns)
        table = parquet.read(columns=columns)
        _binding_need(table.nbytes <= PRE_FIT_MAX_DECODED, "decoded_feature_store_budget")
        expanded = meta.num_rows * (len(columns) - len(text_columns)) * 16
        for name in text_columns:
            longest = 0
            for chunk in table.column(name).chunks:
                _binding_need(pa.types.is_dictionary(chunk.type), "dictionary_feature_store_required")
                length = pc.max(pc.binary_length(chunk.dictionary)).as_py() or 0
                _binding_need(length <= 256, "feature_store_text_value_budget")
                longest = max(longest, length)
            expanded += meta.num_rows * (longest + 64)
        _binding_need(table.nbytes + expanded <= PRE_FIT_MAX_DECODED, "expanded_feature_store_budget")
        frame = table.to_pandas()
    finally:
        parquet.close()
    result = validate_pre_fit_binding(frame, binding, contract,
        feature_store_sha256=hashlib.sha256(feature_raw).hexdigest(), artifact_resolver=resolver)
    _binding_need(binding["code_sha"] == git_head() and
                  Path(__file__).read_bytes() == git_blob_bytes(binding["code_sha"],
                      "tools/run_run287_expected_return_challenger.py"), "consumer_code_identity")
    completed = pd.Timestamp(result["completed_decision_session"])
    prefix = frame.loc[pd.to_datetime(frame["feature_date"]).dt.normalize() <= completed].copy()
    keys = pd.Series([_binding_key(row) for row in prefix.to_dict("records")],index=prefix.index)
    for label in result["labels"]:
        if label["status"] == "IMMATURE":
            mask = keys.map(lambda key: key == (label["feature_date"],label["ticker"]))
            spec = contract["horizons"][str(label["horizon"])]
            for name in ("stock_return", "benchmark_return", "stock_label_end", "benchmark_label_end"):
                prefix.loc[mask,spec[name]] = pd.NaT if name.endswith("label_end") else np.nan
    return prefix, result


def apply_pre_fit_label_clocks(prepared: pd.DataFrame, readiness: Mapping[str, Any]) -> None:
    """Preserve actual availability at EVERY historical V1 decision, in place."""
    keys = pd.Series([_binding_key(row) for row in prepared.to_dict("records")],index=prepared.index)
    for label in readiness["labels"]:
        mask = keys.map(lambda key:key == (label["feature_date"],label["ticker"]))
        value = (_binding_stamp(label["training_available_at"]).tz_localize(None)
                 if label["status"] in {"MATURE", "IMMATURE"} else pd.NaT)
        prepared.loc[mask,f"label_available_at_{label['horizon']}d"] = value


def replay_pre_fit_price_source(request: Mapping[str, Any], *, decision_time: str,
                                root: str | Path) -> dict:
    """Reuse the public Reader's actual training admission; never trust a DTO flag.

    No restore, new generation, provider or collector. Research-only financial
    LITE receipts cannot satisfy this call. Source/feature/model/economic scope
    remains distinct even after genuine qualified byte replay succeeds.
    """
    from tools import research_data_access as access
    from tools.macro_research_checkpoint import LocalTransport
    root = Path(root)
    _binding_need(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), "reader_root")
    fields = {"role", "dataset_id", "data_generation_id", "instrument_ids", "required_start", "required_end",
              "minimum_rows", "required_sessions", "consumer_id", "expected_row_set_sha256"}
    _binding_need(set(request) == fields and request["role"] == "prices" and
                  request["dataset_id"] == PRE_FIT_DATASETS["prices"], "reader_role_dataset_identity")
    reader = access.ResearchDataReader(LocalTransport(root))
    result = reader.read(request["dataset_id"], request["data_generation_id"],
            decision_time=decision_time, purpose="training",
            instrument_ids=request["instrument_ids"], required_start=request["required_start"],
            required_end=request["required_end"], minimum_rows=request["minimum_rows"],
            required_sessions=request["required_sessions"], consumer_id=request["consumer_id"], restore_to=None)
    receipt = result.receipt
    _binding_need(receipt["data_generation_id"] == receipt["manifest_sha256"] == request["data_generation_id"] and
                      receipt["row_set_sha256"] == request["expected_row_set_sha256"] and
                      list(receipt["instrument_ids"]) == sorted(request["instrument_ids"]) and
                      receipt["purpose"] == "training" and receipt["classification"] == "REAL_SOURCE" and
                      receipt["pit_status"] == "VERIFIED" and receipt["requested_session_coverage_verified"] is True and
                      receipt["required_sessions_sha256"] == access.digest(access.encoded(request["required_sessions"])),
                      "training_reader_original_join")
    return dict(role=request["role"], generation=receipt["data_generation_id"],
            row_set_sha256=receipt["row_set_sha256"], receipt_sha256=hashlib.sha256(result.receipt_bytes).hexdigest(),
            consumer_id=receipt["consumer_id"], scope="PUBLIC_READER_TRAINING_BYTES_ONLY")


def replay_pre_fit_training_sources(readiness: Mapping[str, Any], root: str | Path) -> list[dict]:
    for request in readiness["reader_requests"]:
        _binding_need(request.get("role") in PRE_FIT_DATASETS and
                      request.get("dataset_id") == PRE_FIT_DATASETS[request["role"]], "reader_role_dataset_identity")
    # The genuine financial component API is research-only. A price receipt or
    # a caller's flag cannot fill this missing historical financial authority.
    _binding_need(not any(r["role"] == "financial" for r in readiness["reader_requests"]),
                  "FINANCIAL_TRAINING_ADMISSION_UNSUPPORTED")
    return [replay_pre_fit_price_source(r,decision_time=readiness["decision_time"],root=root)
            for r in readiness["reader_requests"]]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key:{key}")
        out[key] = value
    return out


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


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


def git_blob_bytes(commit_sha: str, path: str) -> bytes:
    commit_sha = str(commit_sha or "").lower()
    if not FULL_SHA_RE.fullmatch(commit_sha):
        raise ValueError("Git JSON blob commit identity is invalid")
    if not path or path.startswith(("/", "\\")) or ".." in Path(path).parts:
        raise ValueError("Git JSON blob path is invalid")
    return subprocess.check_output(
        ["git", "show", f"{commit_sha}:{path}"],
        cwd=REPO_ROOT,
        timeout=30,
        stderr=subprocess.DEVNULL,
    )


def git_blob_sha256(commit_sha: str, path: str) -> str:
    return hashlib.sha256(git_blob_bytes(commit_sha, path)).hexdigest()


def git_json_blob_canonical_sha256(commit_sha: str, path: str) -> str:
    raw = git_blob_bytes(commit_sha, path)
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys
    )
    return canonical_sha256(value)


def repository_namespace_payload(
    branches: Any,
    pull_requests: Any,
    *,
    live_api_shape: bool,
) -> dict[str, Any]:
    if not isinstance(branches, list) or not isinstance(pull_requests, list):
        raise ValueError("repository namespace collections are missing")
    branch_rows: list[dict[str, Any]] = []
    branch_names: set[str] = set()
    for row in branches:
        if not isinstance(row, dict):
            raise ValueError("repository branch namespace row is malformed")
        name = str(row.get("name") or "")
        head_sha = str(
            ((row.get("commit") or {}).get("sha"))
            if live_api_shape and isinstance(row.get("commit"), dict)
            else row.get("head_sha") or ""
        ).lower()
        if not name or name in branch_names or not FULL_SHA_RE.fullmatch(head_sha):
            raise ValueError("repository branch namespace identity is invalid")
        branch_names.add(name)
        branch_rows.append({"name": name, "head_sha": head_sha})
    pr_rows: list[dict[str, Any]] = []
    pr_numbers: set[int] = set()
    for row in pull_requests:
        if not isinstance(row, dict):
            raise ValueError("repository pull-request namespace row is malformed")
        number = row.get("number")
        if live_api_shape:
            head = row.get("head") if isinstance(row.get("head"), dict) else {}
            base = row.get("base") if isinstance(row.get("base"), dict) else {}
            head_branch = str(head.get("ref") or "")
            head_sha = str(head.get("sha") or "").lower()
            base_sha = str(base.get("sha") or "").lower()
            updated_at = str(row.get("updated_at") or "")
        else:
            head_branch = str(row.get("head_branch") or "")
            head_sha = str(row.get("head_sha") or "").lower()
            base_sha = str(row.get("base_sha") or "").lower()
            updated_at = str(row.get("updated_at") or "")
        if (
            type(number) is not int
            or number <= 0
            or number in pr_numbers
            or not FULL_SHA_RE.fullmatch(head_sha)
            or not FULL_SHA_RE.fullmatch(base_sha)
            or not head_branch
            or not updated_at
        ):
            raise ValueError("repository pull-request namespace identity is invalid")
        pr_numbers.add(number)
        pr_rows.append(
            {
                "number": number,
                "head_branch": head_branch,
                "head_sha": head_sha,
                "base_sha": base_sha,
                "updated_at": updated_at,
            }
        )
    return {
        "branches": sorted(branch_rows, key=lambda row: row["name"]),
        "pull_requests": sorted(pr_rows, key=lambda row: row["number"]),
    }


def source_repository_namespace(source_census: Mapping[str, Any]) -> dict[str, Any]:
    return repository_namespace_payload(
        source_census.get("branches"),
        source_census.get("pull_requests"),
        live_api_shape=False,
    )


def gh_paginated_collection(endpoint: str) -> list[dict[str, Any]]:
    raw = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", endpoint],
        cwd=REPO_ROOT,
        timeout=60,
    )
    payload = json.loads(
        raw.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys
    )
    if not isinstance(payload, list):
        raise ValueError("GitHub namespace response is not a list")
    pages = payload if all(isinstance(item, list) for item in payload) else [payload]
    rows = [item for page in pages for item in page]
    if any(not isinstance(item, dict) for item in rows):
        raise ValueError("GitHub namespace response contains a malformed row")
    return rows


def load_live_repository_namespace() -> dict[str, Any]:
    branches = gh_paginated_collection(
        f"repos/{REPOSITORY}/branches?per_page=100"
    )
    pull_requests = gh_paginated_collection(
        f"repos/{REPOSITORY}/pulls?state=all&per_page=100"
    )
    return repository_namespace_payload(
        branches, pull_requests, live_api_shape=True
    )


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    if not FULL_SHA_RE.fullmatch(ancestor) or not FULL_SHA_RE.fullmatch(descendant):
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=REPO_ROOT,
            timeout=10,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return result.returncode == 0


def git_default_branch_sha() -> str:
    event_path = Path(str(os.environ.get("GITHUB_EVENT_PATH") or ""))
    if event_path.is_file():
        try:
            event = read_json(event_path)
            repository = ((event.get("repository") or {}).get("full_name"))
            pull_request = event.get("pull_request") or {}
            base = pull_request.get("base") or {}
            sha = str(base.get("sha") or "").lower()
            if (
                repository == REPOSITORY
                and base.get("ref") == "master"
                and FULL_SHA_RE.fullmatch(sha)
            ):
                return sha
        except Exception:
            pass
    for ref in ("refs/remotes/origin/master", "refs/heads/master"):
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "--verify", ref],
                cwd=REPO_ROOT,
                text=True,
                timeout=10,
                stderr=subprocess.DEVNULL,
            ).strip().lower()
        except Exception:
            continue
        if FULL_SHA_RE.fullmatch(sha):
            return sha
    return ""


def load_canonical_u0_artifact(
    artifact_id: int,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("invalid U0 accepted artifact id")
    gate = contract["historical_gate"]
    artifact_raw = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}",
        ],
        cwd=REPO_ROOT,
        timeout=30,
    )
    artifact = json.loads(
        artifact_raw.decode("utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )
    workflow_run = artifact.get("workflow_run") or {}
    run_id = workflow_run.get("id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("U0 artifact lacks workflow run identity")
    if (
        artifact.get("name") != gate["accepted_artifact_name"]
        or artifact.get("expired") is not False
    ):
        raise ValueError("U0 artifact identity is not accepted")
    run_raw = subprocess.check_output(
        ["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}"],
        cwd=REPO_ROOT,
        timeout=30,
    )
    run = json.loads(
        run_raw.decode("utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )
    if (
        run.get("id") != run_id
        or run.get("path") != gate["accepted_workflow_path"]
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != gate["default_branch"]
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise ValueError("U0 artifact workflow run is not canonical")
    zip_bytes = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
        ],
        cwd=REPO_ROOT,
        timeout=60,
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        source_census_name = gate["accepted_artifact_source_census_file"]
        census_name = gate["accepted_artifact_census_file"]
        evidence_name = gate["accepted_artifact_evidence_file"]
        if (
            names.count(source_census_name) != 1
            or names.count(census_name) != 1
            or names.count(evidence_name) != 1
        ):
            raise ValueError("U0 artifact canonical files are missing or duplicated")
        source_census = json.loads(
            archive.read(source_census_name).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
        census = json.loads(
            archive.read(census_name).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
        evidence = json.loads(
            archive.read(evidence_name).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    audit_sha = str(census.get("audit_default_branch_sha") or "").lower()
    if (
        str(run.get("head_sha") or "").lower() != audit_sha
        or str(workflow_run.get("head_sha") or "").lower() != audit_sha
        or workflow_run.get("head_branch") != gate["default_branch"]
    ):
        raise ValueError("U0 artifact is not bound to its audited master head")
    source_observed_at = str(source_census.get("generated_at_utc") or "")
    try:
        observed_at = datetime.fromisoformat(
            source_observed_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("U0 source census observation time is invalid") from exc
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("U0 source census observation time lacks a timezone")
    expected_namespace_sha256 = canonical_sha256(
        source_repository_namespace(source_census)
    )
    if (
        evidence.get("source_observed_at_utc") != source_observed_at
        or evidence.get("repository_namespace_sha256")
        != expected_namespace_sha256
    ):
        raise ValueError("U0 acceptance does not attest its source observation")
    live_namespace_sha256 = canonical_sha256(load_live_repository_namespace())
    if live_namespace_sha256 != expected_namespace_sha256:
        raise ValueError("U0 source census is stale for the live repository namespace")
    return {
        "verified": True,
        "artifact_id": artifact_id,
        "workflow_run_id": run_id,
        "workflow_path": run["path"],
        "head_sha": audit_sha,
        "artifact_digest": artifact.get("digest"),
        "source_observed_at_utc": source_observed_at,
        "repository_namespace_sha256": expected_namespace_sha256,
        "live_repository_namespace_sha256": live_namespace_sha256,
        "source_census": source_census,
        "census": census,
        "accepted_evidence": evidence,
    }


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
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if value is pd.NaT:
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            json_clean(value), indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("expected-return contract must be an object")
    if contract.get("schema_version") != (
        "run287-expected-return-challenger-contract-v1"
    ):
        raise ValueError("expected-return contract schema mismatch")
    if contract.get("family_id") != (
        "future_expected_excess_return_multihorizon_v1"
    ):
        raise ValueError("expected-return family identity mismatch")
    horizons = contract.get("horizons")
    features = contract.get("features")
    if not isinstance(horizons, dict) or set(horizons) != {
        "21",
        "63",
        "126",
    }:
        raise ValueError("expected-return horizons must be exactly 21/63/126")
    if not isinstance(features, dict) or set(features) != set(horizons):
        raise ValueError("expected-return feature groups mismatch")
    score_weight = 0.0
    for horizon in HORIZONS:
        spec = horizons[str(horizon)]
        names = features[str(horizon)]
        if not isinstance(spec, dict) or not isinstance(names, list) or not names:
            raise ValueError(f"invalid horizon contract:{horizon}")
        if len(names) != len(set(names)) or any(
            not isinstance(name, str) or not name for name in names
        ):
            raise ValueError(f"invalid feature whitelist:{horizon}")
        forbidden = sorted(name for name in names if FORBIDDEN_FEATURE_RE.search(name))
        if forbidden:
            raise ValueError("future/label columns in feature whitelist:" + ",".join(forbidden))
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        ):
            if not isinstance(spec.get(key), str) or not spec[key]:
                raise ValueError(f"missing horizon label contract:{horizon}:{key}")
        score_weight += float(spec.get("score_weight") or 0.0)
    if abs(score_weight - 1.0) > 1e-12:
        raise ValueError("horizon score weights must sum to one")
    fixed_score_weights = {"21": 0.0, "63": 0.65, "126": 0.35}
    for horizon, expected_weight in fixed_score_weights.items():
        actual_weight = float(horizons[horizon].get("score_weight") or 0.0)
        if not math.isclose(actual_weight, expected_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"fixed horizon score weight mismatch:{horizon}:"
                f"expected={expected_weight}:actual={actual_weight}"
            )
    purge_and_windows = contract.get("purge_and_windows") or {}
    embargo_sessions = purge_and_windows.get("embargo_nyse_sessions")
    if type(embargo_sessions) is not int or embargo_sessions != 126:
        raise ValueError("fixed NYSE-session embargo must equal 126")
    alpha_mix = (contract.get("target_contract") or {}).get(
        "benchmark_sector_mix"
    ) or {}
    for key, expected_weight in {
        "benchmark_excess": 0.7,
        "sector_neutral": 0.3,
    }.items():
        actual_weight = float(alpha_mix.get(key) or 0.0)
        if not math.isclose(actual_weight, expected_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"fixed alpha target mix mismatch:{key}:"
                f"expected={expected_weight}:actual={actual_weight}"
            )
    model = contract.get("model") or {}
    if (
        model.get("parameter_tuning_allowed") is not False
        or float(model.get("long_history_weight") or 0.0)
        + float(model.get("recent_history_weight") or 0.0)
        != 1.0
    ):
        raise ValueError("fixed model blend contract mismatch")
    safety = contract.get("safety") or {}
    if safety.get("research_only") is not True or any(
        safety.get(key) is not False
        for key in (
            "automatic_promotion_allowed",
            "champion_change_allowed",
            "portfolio_mutation_allowed",
            "target_books_written",
            "orders_generated",
            "operating_ledger_mutated",
            "production_or_live_trading_enabled",
        )
    ):
        raise ValueError("expected-return safety contract mismatch")
    historical_gate = contract.get("historical_gate") or {}
    if (
        historical_gate.get("source_inventory_path")
        != "docs/run287_u0_experiment_inventory.json"
        or historical_gate.get("live_repository_namespace_match_required") is not True
    ):
        raise ValueError("expected-return U0 freshness contract mismatch")
    actual_contract_sha256 = canonical_sha256(contract)
    if actual_contract_sha256 != EXPECTED_CONTRACT_SHA256:
        raise ValueError(
            "expected-return contract hash mismatch:"
            f"expected={EXPECTED_CONTRACT_SHA256}:actual={actual_contract_sha256}"
        )
    return contract


def u0_gate(
    census: Any,
    accepted_evidence: Any,
    canonical_artifact: Any,
    contract: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    gate = contract["historical_gate"]
    if not isinstance(census, dict):
        return ["u0_census_not_an_object"]
    if census.get("schema_version") != gate["u0_schema_version"]:
        blockers.append("u0_census_schema_mismatch")
    if census.get("repository") != gate["repository"]:
        blockers.append("u0_census_repository_mismatch")
    if census.get("audit_default_branch") != gate["default_branch"]:
        blockers.append("u0_census_default_branch_mismatch")
    if not isinstance(canonical_artifact, dict) or (
        canonical_artifact.get("verified") is not True
    ):
        canonical_artifact = {}
        blockers.append("u0_canonical_artifact_not_verified")
    if canonical_sha256(census) != canonical_sha256(
        canonical_artifact.get("census")
    ):
        blockers.append("u0_census_not_exact_canonical_artifact")
    if canonical_sha256(accepted_evidence) != canonical_sha256(
        canonical_artifact.get("accepted_evidence")
    ):
        blockers.append("u0_evidence_not_exact_canonical_artifact")
    canonical_source = canonical_artifact.get("source_census")
    if not isinstance(canonical_source, dict):
        canonical_source = {}
        blockers.append("u0_canonical_source_census_missing")
    if not isinstance(accepted_evidence, dict):
        accepted_evidence = {}
        blockers.append("u0_accepted_evidence_not_an_object")
    source_observed_at = str(canonical_source.get("generated_at_utc") or "")
    try:
        parsed_observed_at = datetime.fromisoformat(
            source_observed_at.replace("Z", "+00:00")
        )
        if parsed_observed_at.tzinfo is None or parsed_observed_at.utcoffset() is None:
            raise ValueError("timezone missing")
    except ValueError:
        blockers.append("u0_source_census_observation_time_invalid")
    try:
        repository_namespace_sha256 = canonical_sha256(
            source_repository_namespace(canonical_source)
        )
    except Exception:
        repository_namespace_sha256 = ""
        blockers.append("u0_source_census_repository_namespace_invalid")
    if accepted_evidence.get("source_observed_at_utc") != source_observed_at:
        blockers.append("u0_source_observation_not_exact_accepted_artifact")
    if accepted_evidence.get("repository_namespace_sha256") != (
        repository_namespace_sha256
    ):
        blockers.append("u0_repository_namespace_not_exact_accepted_artifact")
    if census.get("source_observed_at_utc") != source_observed_at:
        blockers.append("u0_recovery_source_observation_mismatch")
    if census.get("repository_namespace_sha256") != repository_namespace_sha256:
        blockers.append("u0_recovery_repository_namespace_mismatch")
    if (
        canonical_artifact.get("source_observed_at_utc") != source_observed_at
        or canonical_artifact.get("repository_namespace_sha256")
        != repository_namespace_sha256
        or canonical_artifact.get("live_repository_namespace_sha256")
        != repository_namespace_sha256
    ):
        blockers.append("u0_live_repository_namespace_not_current")
    if (
        accepted_evidence.get("schema_version")
        != gate["accepted_evidence_schema_version"]
    ):
        blockers.append("u0_accepted_evidence_schema_mismatch")
    if accepted_evidence.get("repository") != gate["repository"]:
        blockers.append("u0_accepted_evidence_repository_mismatch")
    if accepted_evidence.get("audit_default_branch") != gate["default_branch"]:
        blockers.append("u0_accepted_evidence_default_branch_mismatch")
    if (
        accepted_evidence.get("workflow_identity")
        != gate["accepted_evidence_workflow_identity"]
    ):
        blockers.append("u0_accepted_evidence_workflow_mismatch")
    if str(accepted_evidence.get("recovery_census_sha256") or "").lower() != (
        canonical_sha256(census)
    ):
        blockers.append("u0_census_not_exact_accepted_artifact")
    source_sha256 = canonical_sha256(canonical_source)
    if str(accepted_evidence.get("source_census_sha256") or "").lower() != (
        source_sha256
    ):
        blockers.append("u0_source_census_not_exact_accepted_artifact")
    if str(census.get("source_census_sha256") or "").lower() != source_sha256:
        blockers.append("u0_recovery_source_census_hash_mismatch")
    for evidence_key, gate_key in (
        ("recovery_contract_sha256", "accepted_u0_recovery_contract_sha256"),
        ("acceptance_contract_sha256", "accepted_u0_acceptance_contract_sha256"),
    ):
        if str(accepted_evidence.get(evidence_key) or "").lower() != str(
            gate.get(gate_key) or ""
        ).lower():
            blockers.append(f"u0_{evidence_key}_mismatch")
    if str(census.get("recovery_contract_sha256") or "").lower() != str(
        gate.get("accepted_u0_recovery_contract_sha256") or ""
    ).lower():
        blockers.append("u0_recovery_contract_hash_mismatch")
    if str(census.get("source_inventory_sha256") or "").lower() != str(
        accepted_evidence.get("source_inventory_sha256") or ""
    ).lower():
        blockers.append("u0_source_inventory_hash_mismatch")
    for key, value in (
        ("source_inventory_sha256", census.get("source_inventory_sha256")),
        ("source_census_sha256", census.get("source_census_sha256")),
        ("recovery_contract_sha256", census.get("recovery_contract_sha256")),
    ):
        if not SHA256_RE.fullmatch(str(value or "").lower()):
            blockers.append(f"u0_recovery_hash_invalid:{key}")
    audit_sha = str(census.get("audit_default_branch_sha") or "").lower()
    if str(accepted_evidence.get("audit_default_branch_sha") or "").lower() != audit_sha:
        blockers.append("u0_accepted_evidence_audit_sha_mismatch")
    current_sha = git_head().lower()
    accepted_default_sha = git_default_branch_sha()
    try:
        current_inventory_sha256 = git_json_blob_canonical_sha256(
            current_sha, gate["source_inventory_path"]
        )
        accepted_inventory_git_blob_sha256 = git_blob_sha256(
            audit_sha, gate["source_inventory_path"]
        )
        current_inventory_git_blob_sha256 = git_blob_sha256(
            current_sha, gate["source_inventory_path"]
        )
    except Exception:
        current_inventory_sha256 = ""
        accepted_inventory_git_blob_sha256 = ""
        current_inventory_git_blob_sha256 = ""
        blockers.append("u0_current_runner_inventory_git_blob_unreadable")
    accepted_inventory_sha256 = str(
        accepted_evidence.get("source_inventory_sha256") or ""
    ).lower()
    if (
        current_inventory_sha256 != accepted_inventory_sha256
        or str(census.get("source_inventory_sha256") or "").lower()
        != current_inventory_sha256
    ):
        blockers.append("u0_source_inventory_not_current_runner_git_blob")
    if current_inventory_git_blob_sha256 != accepted_inventory_git_blob_sha256:
        blockers.append("u0_source_inventory_git_blob_changed_since_acceptance")
    if not FULL_SHA_RE.fullmatch(audit_sha):
        blockers.append("u0_census_audit_sha_invalid")
    else:
        if audit_sha != accepted_default_sha:
            blockers.append("u0_census_audit_sha_not_current_default_branch")
        if not git_is_ancestor(audit_sha, current_sha):
            blockers.append("u0_census_audit_sha_not_ancestor_of_runner")
    if str(canonical_source.get("audit_default_branch_sha") or "").lower() != (
        audit_sha
    ):
        blockers.append("u0_source_census_audit_sha_mismatch")
    if canonical_source.get("schema_version") != "run287-u0-v2-github-census-v1":
        blockers.append("u0_source_census_schema_mismatch")
    source = canonical_source.get("source_contract")
    if not isinstance(source, dict):
        source = {}
        blockers.append("u0_source_census_contract_missing")
    for key in (
        "branch_payload_sha256",
        "pull_request_payload_sha256",
        "normalized_branch_rows_sha256",
        "normalized_pull_request_rows_sha256",
    ):
        if not SHA256_RE.fullmatch(str(source.get(key) or "").lower()):
            blockers.append(f"u0_source_census_hash_invalid:{key}")
    if (
        source.get("metadata_only") is not True
        or source.get("fullrun_executed") is not False
        or source.get("production_or_live_mutated") is not False
        or source.get("champion_changed") is not False
    ):
        blockers.append("u0_source_census_safety_mismatch")
    branches = canonical_source.get("branches")
    pull_requests = canonical_source.get("pull_requests")
    if not isinstance(branches, list) or not isinstance(pull_requests, list):
        blockers.append("u0_source_census_normalized_records_missing")
        branches = []
        pull_requests = []
    if canonical_sha256(branches) != source.get("normalized_branch_rows_sha256"):
        blockers.append("u0_source_census_normalized_branch_hash_mismatch")
    if canonical_sha256(pull_requests) != source.get(
        "normalized_pull_request_rows_sha256"
    ):
        blockers.append("u0_source_census_normalized_pr_hash_mismatch")
    master_rows = [
        row
        for row in branches
        if isinstance(row, dict) and row.get("name") == gate["default_branch"]
    ]
    if (
        len(master_rows) != 1
        or str(master_rows[0].get("head_sha") or "").lower() != audit_sha
        or master_rows[0].get("ancestry") != "IDENTICAL_TO_AUDIT_HEAD"
    ):
        blockers.append("u0_source_census_default_branch_record_mismatch")
    recovery_safety = census.get("safety")
    required_recovery_safety = {
        "metadata_only": True,
        "fullrun_allowed": False,
        "target_order_ledger_mutation_allowed": False,
        "production_or_live_trading_allowed": False,
        "automatic_promotion_allowed": False,
        "acceptance_gate_migration_allowed_by_this_contract": False,
    }
    if recovery_safety != required_recovery_safety:
        blockers.append("u0_recovery_safety_mismatch")
    summary = census.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        blockers.append("u0_census_summary_missing")
    if summary.get("historical_experiment_census_complete") is not True:
        blockers.append("u0_historical_experiment_census_incomplete")
    if summary.get("historical_challenger_preregistration_ready") is not True:
        blockers.append("u0_historical_challenger_preregistration_not_ready")
    if summary.get("historical_challenger_allowed") is not False:
        blockers.append("u0_recovery_prematurely_authorized_challenger")
    if census.get("census_completion_blockers") != []:
        blockers.append("u0_census_completion_blockers_not_empty")
    if sorted(census.get("acceptance_migration_blockers") or []) != sorted(
        gate["required_recovery_migration_blockers"]
    ):
        blockers.append("u0_recovery_migration_blockers_mismatch")
    trial_floor = summary.get("conservative_historical_trial_count_lower_bound")
    if (
        type(trial_floor) is not int
        or trial_floor
        < gate["minimum_conservative_historical_trial_count_lower_bound"]
        or accepted_evidence.get(
            "conservative_historical_trial_count_lower_bound"
        )
        != trial_floor
    ):
        blockers.append("u0_conservative_historical_trial_floor_invalid")
    if (
        accepted_evidence.get("historical_experiment_census_complete") is not True
        or accepted_evidence.get(
            "historical_challenger_preregistration_ready"
        )
        is not True
        or accepted_evidence.get(
            "historical_challenger_research_fit_allowed"
        )
        is not True
        or accepted_evidence.get("historical_broker_backtest_allowed") is not False
        or accepted_evidence.get("legacy_result_promotion_allowed") is not False
        or accepted_evidence.get("promotion_blockers") != []
        or accepted_evidence.get("target_order_ledger_mutation_allowed") is not False
        or accepted_evidence.get("production_or_live_trading_allowed") is not False
        or accepted_evidence.get("automatic_promotion_allowed") is not False
        or accepted_evidence.get("fullrun_allowed") is not False
    ):
        blockers.append("u0_accepted_evidence_not_approved")
    return sorted(set(blockers))


def required_columns(contract: Mapping[str, Any]) -> list[str]:
    required = set(contract["data_policy"]["required_identity_columns"])
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) > 0.0:
            required.update(contract["features"][str(horizon)])
            required.update(
                spec[key]
                for key in (
                    "stock_return",
                    "benchmark_return",
                    "stock_label_end",
                    "benchmark_label_end",
                )
            )
    return sorted(required)


def input_readiness(frame: pd.DataFrame, contract: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    missing = sorted(set(required_columns(contract)) - set(frame.columns))
    if missing:
        blockers.append("feature_store_missing_required_columns:" + ",".join(missing))
    if frame.empty:
        return ["feature_store_empty"]
    feature_dates = (
        pd.to_datetime(frame["feature_date"], errors="coerce")
        if "feature_date" in frame.columns
        else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    )
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) <= 0.0:
            continue
        for feature in contract["features"][str(horizon)]:
            if feature in frame.columns:
                numeric = pd.to_numeric(frame[feature], errors="coerce").replace(
                    [np.inf, -np.inf], np.nan
                )
                if numeric.notna().sum() == 0:
                    blockers.append(
                        f"selection_feature_unusable:{horizon}:{feature}"
                    )
                elif (
                    numeric.notna()
                    .groupby(feature_dates)
                    .sum()
                    .eq(0)
                    .any()
                ):
                    blockers.append(
                        f"selection_feature_unusable_on_decision_date:"
                        f"{horizon}:{feature}"
                    )
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        ):
            column = spec[key]
            if column in frame.columns and frame[column].notna().sum() == 0:
                blockers.append(f"label_provenance_empty:{column}")
    return sorted(set(blockers))


def _rank_group(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() < 2 or numeric.nunique(dropna=True) < 2:
        return pd.Series(0.5, index=values.index, dtype=float)
    return numeric.rank(pct=True, method="average").fillna(0.5).clip(0.0, 1.0)


def expected_nyse_label_ends(
    feature_dates: pd.Series, horizon: int
) -> pd.Series:
    dates = pd.to_datetime(feature_dates, errors="coerce").dt.normalize()
    out = pd.Series(pd.NaT, index=feature_dates.index, dtype="datetime64[ns]")
    valid_dates = dates.dropna().drop_duplicates().sort_values()
    if valid_dates.empty:
        return out
    sessions = NYSE.valid_days(
        start_date=valid_dates.min() - pd.Timedelta(days=7),
        end_date=valid_dates.max() + pd.Timedelta(days=max(60, horizon * 3)),
    ).tz_localize(None).normalize()
    mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    for decision in valid_dates:
        future = sessions[sessions > decision]
        if len(future) > horizon:
            # Canonical labels enter on the first session after the decision
            # and measure `horizon` price intervals, ending at future[horizon].
            mapping[pd.Timestamp(decision)] = pd.Timestamp(future[horizon])
    return dates.map(mapping)


def prepare_frame(frame: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    blockers = input_readiness(frame, contract)
    if blockers:
        raise ValueError(";".join(blockers))
    out = frame.copy()
    out["feature_date"] = pd.to_datetime(out["feature_date"], errors="coerce").dt.normalize()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    if out[["feature_date", "rebalance_date"]].isna().any().any():
        raise ValueError("invalid feature or rebalance date")
    if not out["feature_date"].eq(out["rebalance_date"]).all():
        raise ValueError("feature_date and rebalance_date identity mismatch")
    if out["ticker"].isna().any():
        raise ValueError("null ticker in feature store")
    if out["sector"].isna().any():
        raise ValueError("null sector in feature store")
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
    out["sector"] = out["sector"].astype(str).str.strip()
    if out["ticker"].eq("").any():
        raise ValueError("empty ticker in feature store")
    if out["sector"].eq("").any():
        raise ValueError("empty sector in feature store")
    benchmark_identity = out["benchmark_identity"].astype(str).str.strip().str.upper()
    benchmark_source = out["benchmark_source"].astype(str).str.strip().str.upper()
    expected_benchmark = str(contract["data_policy"]["canonical_benchmark"]).upper()
    expected_source = str(
        contract["data_policy"]["canonical_benchmark_source"]
    ).upper()
    if not benchmark_identity.eq(expected_benchmark).all():
        raise ValueError("benchmark identity provenance mismatch")
    if not benchmark_source.eq(expected_source).all():
        raise ValueError("benchmark source provenance mismatch")
    out["benchmark_identity"] = benchmark_identity
    out["benchmark_source"] = benchmark_source
    if out.duplicated(["feature_date", "ticker"]).any():
        raise ValueError("duplicate feature_date/ticker rows")

    all_features = sorted(
        name
        for name in {
            feature
            for horizon in HORIZONS
            for feature in contract["features"][str(horizon)]
        }
        if name in out.columns
        and pd.to_numeric(out[name], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .notna()
        .any()
    )
    for name in all_features:
        out[f"xrank__{name}"] = out.groupby("feature_date", group_keys=False)[name].transform(_rank_group)
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) <= 0.0:
            for key in ("stock_return", "benchmark_return"):
                if spec[key] not in out.columns:
                    out[spec[key]] = np.nan
            for key in ("stock_label_end", "benchmark_label_end"):
                if spec[key] not in out.columns:
                    out[spec[key]] = pd.NaT
        stock = pd.to_numeric(out[spec["stock_return"]], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        benchmark = pd.to_numeric(
            out[spec["benchmark_return"]], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
        stock_end = pd.to_datetime(out[spec["stock_label_end"]], errors="coerce").dt.normalize()
        benchmark_end = pd.to_datetime(out[spec["benchmark_label_end"]], errors="coerce").dt.normalize()
        if float(spec["score_weight"]) > 0.0:
            raw_columns = [
                out[spec["stock_return"]],
                out[spec["benchmark_return"]],
                out[spec["stock_label_end"]],
                out[spec["benchmark_label_end"]],
            ]
            raw_present = [
                column.notna() & column.astype(str).str.strip().ne("")
                for column in raw_columns
            ]
            parsed_present = [
                stock.notna(),
                benchmark.notna(),
                stock_end.notna(),
                benchmark_end.notna(),
            ]
            if any(
                raw.ne(parsed).any()
                for raw, parsed in zip(raw_present, parsed_present)
            ):
                raise ValueError(f"unparseable required label provenance:{horizon}")
            present_count = sum(mask.astype(int) for mask in parsed_present)
            if present_count.between(1, 3).any():
                raise ValueError(f"partial required label provenance:{horizon}")
        if benchmark.groupby(out["feature_date"]).nunique(dropna=True).gt(1).any():
            raise ValueError(f"benchmark return is not unique by decision:{horizon}")
        if benchmark_end.groupby(out["feature_date"]).nunique(dropna=True).gt(1).any():
            raise ValueError(f"benchmark label end is not unique by decision:{horizon}")
        complete = stock.notna() & benchmark.notna() & stock_end.notna() & benchmark_end.notna()
        if stock_end.loc[complete].ne(benchmark_end.loc[complete]).any():
            raise ValueError(f"stock/benchmark label end mismatch:{horizon}")
        if (
            stock_end.where(complete)
            .groupby(out["feature_date"])
            .nunique(dropna=True)
            .gt(1)
            .any()
        ):
            raise ValueError(f"mixed cross-sectional label end dates:{horizon}")
        expected_end = expected_nyse_label_ends(out["feature_date"], horizon)
        if stock_end.loc[complete].ne(expected_end.loc[complete]).any():
            raise ValueError(f"label end is not exact NYSE horizon:{horizon}")
        row_available = pd.concat([stock_end, benchmark_end], axis=1).max(axis=1).where(complete)
        # All cross-sectional targets for one decision mature together.
        available = row_available.groupby(out["feature_date"]).transform("max").where(complete)
        absolute = stock.where(complete)
        excess = (stock - benchmark).where(complete)
        sector_size = absolute.groupby(
            [out["feature_date"], out["sector"]]
        ).transform("count")
        sector_mean = absolute.groupby([out["feature_date"], out["sector"]]).transform("mean")
        sector_neutral = (absolute - sector_mean).where(
            complete
            & sector_size.ge(int(contract["target_contract"]["minimum_sector_cross_section"]))
        )
        out[f"label_available_at_{horizon}d"] = available
        out[f"y_absolute_{horizon}d"] = absolute
        out[f"y_benchmark_excess_{horizon}d"] = excess
        out[f"y_sector_neutral_{horizon}d"] = sector_neutral
        out[f"y_downside_{horizon}d"] = absolute.le(0.0).where(complete)
        feature_names = contract["features"][str(horizon)]
        available_features = [name for name in feature_names if name in out.columns]
        out[f"feature_coverage_{horizon}d"] = (
            out[available_features].notna().mean(axis=1)
            if len(available_features) == len(feature_names)
            else 0.0
        )
    return out.sort_values(["feature_date", "ticker"]).reset_index(drop=True)


def nyse_embargo_cutoffs(
    decision_dates: list[pd.Timestamp], embargo_sessions: int
) -> dict[pd.Timestamp, pd.Timestamp | None]:
    if not decision_dates:
        return {}
    start = min(decision_dates) - pd.Timedelta(days=max(730, embargo_sessions * 3))
    end = max(decision_dates) + pd.Timedelta(days=7)
    sessions = NYSE.valid_days(start_date=start, end_date=end).tz_localize(None).normalize()
    out: dict[pd.Timestamp, pd.Timestamp | None] = {}
    for raw_date in decision_dates:
        decision = pd.Timestamp(raw_date).normalize()
        prior = sessions[sessions < decision]
        out[decision] = (
            pd.Timestamp(prior[-embargo_sessions]).normalize()
            if len(prior) >= embargo_sessions
            else None
        )
    return out


def _standardize_fit(
    train_x: np.ndarray, test_x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, StandardScaler]:
    scaler = StandardScaler()
    scaled_train = scaler.fit_transform(train_x)
    scaled_test = scaler.transform(test_x)
    return scaled_train, scaled_test, scaler


def fit_regression_pair(
    train: pd.DataFrame,
    recent: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    contract: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    minimum_rows = int(contract["model"]["minimum_training_rows"])
    minimum_dates = int(contract["model"]["minimum_training_decision_dates"])
    train = train.dropna(subset=[target_column])
    recent = recent.dropna(subset=[target_column])
    if (
        len(train) < minimum_rows
        or len(recent) < minimum_rows
        or train["feature_date"].nunique() < minimum_dates
        or recent["feature_date"].nunique() < minimum_dates
    ):
        return None

    def one_fit(source: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
        x = source[feature_columns].to_numpy(dtype=float)
        test_x = test[feature_columns].to_numpy(dtype=float)
        scaled_x, scaled_test, scaler = _standardize_fit(x, test_x)
        model = Ridge(
            alpha=float(contract["model"]["ridge_alpha"]),
            fit_intercept=True,
        )
        model.fit(scaled_x, source[target_column].to_numpy(dtype=float))
        return model.predict(scaled_test), {
            "intercept": float(model.intercept_),
            "coefficients": {
                feature_columns[index]: float(model.coef_[index])
                for index in range(len(feature_columns))
            },
            "scaler_mean": {
                feature_columns[index]: float(scaler.mean_[index])
                for index in range(len(feature_columns))
            },
            "scaler_scale": {
                feature_columns[index]: float(scaler.scale_[index])
                for index in range(len(feature_columns))
            },
            "training_rows": len(source),
            "training_dates": int(source["feature_date"].nunique()),
        }

    long_prediction, long_model = one_fit(train)
    recent_prediction, recent_model = one_fit(recent)
    long_weight = float(contract["model"]["long_history_weight"])
    recent_weight = float(contract["model"]["recent_history_weight"])
    blended = long_weight * long_prediction + recent_weight * recent_prediction
    return blended, np.abs(long_prediction - recent_prediction), {
        "long_history": long_model,
        "recent_36_month": recent_model,
    }


def fit_classifier_pair(
    train: pd.DataFrame,
    recent: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    contract: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    minimum_rows = int(contract["model"]["minimum_training_rows"])
    minimum_dates = int(contract["model"]["minimum_training_decision_dates"])
    train = train.dropna(subset=[target_column]).copy()
    recent = recent.dropna(subset=[target_column]).copy()
    if (
        len(train) < minimum_rows
        or len(recent) < minimum_rows
        or train["feature_date"].nunique() < minimum_dates
        or recent["feature_date"].nunique() < minimum_dates
        or train[target_column].nunique() != 2
        or recent[target_column].nunique() != 2
    ):
        return None

    def one_fit(source: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
        x = source[feature_columns].to_numpy(dtype=float)
        test_x = test[feature_columns].to_numpy(dtype=float)
        scaled_x, scaled_test, scaler = _standardize_fit(x, test_x)
        model = LogisticRegression(
            C=float(contract["model"]["logistic_c"]),
            class_weight="balanced",
            max_iter=1200,
            random_state=int(contract["model"]["random_seed"]),
        )
        model.fit(scaled_x, source[target_column].astype(int).to_numpy())
        return model.predict_proba(scaled_test)[:, 1], {
            "intercept": float(model.intercept_[0]),
            "coefficients": {
                feature_columns[index]: float(model.coef_[0, index])
                for index in range(len(feature_columns))
            },
            "scaler_mean": {
                feature_columns[index]: float(scaler.mean_[index])
                for index in range(len(feature_columns))
            },
            "scaler_scale": {
                feature_columns[index]: float(scaler.scale_[index])
                for index in range(len(feature_columns))
            },
            "training_rows": len(source),
            "training_dates": int(source["feature_date"].nunique()),
        }

    long_prediction, long_model = one_fit(train)
    recent_prediction, recent_model = one_fit(recent)
    long_weight = float(contract["model"]["long_history_weight"])
    recent_weight = float(contract["model"]["recent_history_weight"])
    blended = long_weight * long_prediction + recent_weight * recent_prediction
    return blended, np.abs(long_prediction - recent_prediction), {
        "long_history": long_model,
        "recent_36_month": recent_model,
    }


def walk_forward_predictions(
    prepared: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    full_start = pd.Timestamp(contract["purge_and_windows"]["full_start"])
    dates = [
        pd.Timestamp(value).normalize()
        for value in sorted(prepared["feature_date"].dropna().unique())
        if pd.Timestamp(value) >= full_start
    ]
    embargo_sessions = int(contract["purge_and_windows"]["embargo_nyse_sessions"])
    cutoffs = nyse_embargo_cutoffs(dates, embargo_sessions)
    prediction_parts: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    latest_models: dict[str, Any] = {}
    latest_date = max(dates) if dates else None

    for decision in dates:
        test = prepared[prepared["feature_date"].eq(decision)].copy()
        cutoff = cutoffs.get(decision)
        if cutoff is None:
            for horizon in HORIZONS:
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": "BLOCKED_EMBARGO_HISTORY",
                        "embargo_cutoff": None,
                        "training_rows": 0,
                    }
                )
            continue
        date_output = test[["feature_date", "rebalance_date", "ticker", "sector"]].copy()
        selection_horizons_ready = True
        selection_candidate_eligible = pd.Series(True, index=test.index, dtype=bool)
        decision_models: dict[str, Any] = {}
        for horizon in HORIZONS:
            selection_required = float(
                contract["horizons"][str(horizon)]["score_weight"]
            ) > 0.0
            scoring_sector_eligible = test.groupby("sector")["ticker"].transform(
                "size"
            ).ge(int(contract["target_contract"]["minimum_sector_cross_section"]))
            if selection_required:
                selection_candidate_eligible &= scoring_sector_eligible
            feature_columns = [
                f"xrank__{name}" for name in contract["features"][str(horizon)]
            ]
            available_col = f"label_available_at_{horizon}d"
            missing_feature_columns = [
                column for column in feature_columns if column not in prepared.columns
            ]
            if missing_feature_columns:
                if selection_required:
                    raise RuntimeError(
                        "required selection rank features missing:"
                        + ",".join(missing_feature_columns)
                    )
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": "UNAVAILABLE_TIMING_ONLY_MISSING_FEATURES",
                        "embargo_cutoff": cutoff,
                        "training_rows": 0,
                        "missing_feature_columns": missing_feature_columns,
                        "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                        "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                    }
                )
                for column in (
                    "expected_absolute",
                    "expected_benchmark_excess",
                    "expected_sector_neutral",
                    "expected_alpha",
                    "downside_probability",
                    "model_disagreement",
                ):
                    date_output[f"{column}_{horizon}d"] = np.nan
                date_output[f"feature_coverage_{horizon}d"] = test[
                    f"feature_coverage_{horizon}d"
                ].to_numpy()
                for target_kind in TARGET_KINDS:
                    date_output[f"realized_{target_kind}_{horizon}d"] = test[
                        f"y_{target_kind}_{horizon}d"
                    ].to_numpy()
                date_output[f"realized_downside_{horizon}d"] = test[
                    f"y_downside_{horizon}d"
                ].to_numpy()
                date_output[f"label_available_at_{horizon}d"] = test[
                    available_col
                ].to_numpy()
                decision_models[str(horizon)] = {
                    "status": "UNAVAILABLE_TIMING_ONLY_MISSING_FEATURES",
                    "missing_feature_columns": missing_feature_columns,
                }
                continue
            eligible = prepared[
                prepared["feature_date"].le(cutoff)
                & prepared[available_col].notna()
                & prepared[available_col].lt(decision)
            ].copy()
            recent_start = decision - pd.DateOffset(
                months=int(contract["model"]["recent_history_months"])
            )
            recent = eligible[eligible["feature_date"].ge(recent_start)].copy()
            models: dict[str, Any] = {}
            target_results: dict[str, tuple[np.ndarray, np.ndarray, dict[str, Any]]] = {}
            horizon_ready = True
            for target_kind in TARGET_KINDS:
                target_column = f"y_{target_kind}_{horizon}d"
                fitted = fit_regression_pair(
                    eligible,
                    recent,
                    test,
                    feature_columns,
                    target_column,
                    contract,
                )
                if fitted is None:
                    horizon_ready = False
                    break
                target_results[target_kind] = fitted
                models[target_kind] = fitted[2]
            classifier = None
            if horizon_ready:
                classifier = fit_classifier_pair(
                    eligible,
                    recent,
                    test,
                    feature_columns,
                    f"y_downside_{horizon}d",
                    contract,
                )
                if classifier is None:
                    horizon_ready = False
            if not horizon_ready or classifier is None:
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": (
                            "BLOCKED_INSUFFICIENT_TRAINING"
                            if selection_required
                            else "UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING"
                        ),
                        "embargo_cutoff": cutoff,
                        "training_rows": len(eligible),
                        "training_dates": int(eligible["feature_date"].nunique()),
                        "recent_training_rows": len(recent),
                        "max_training_feature_date": eligible["feature_date"].max() if not eligible.empty else None,
                        "max_label_available_at": eligible[available_col].max() if not eligible.empty else None,
                        "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                        "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                    }
                )
                if selection_required:
                    selection_horizons_ready = False
                    break
                for column in (
                    "expected_absolute",
                    "expected_benchmark_excess",
                    "expected_sector_neutral",
                    "expected_alpha",
                    "downside_probability",
                    "model_disagreement",
                ):
                    date_output[f"{column}_{horizon}d"] = np.nan
                date_output[f"feature_coverage_{horizon}d"] = test[
                    f"feature_coverage_{horizon}d"
                ].to_numpy()
                for target_kind in TARGET_KINDS:
                    date_output[f"realized_{target_kind}_{horizon}d"] = test[
                        f"y_{target_kind}_{horizon}d"
                    ].to_numpy()
                date_output[f"realized_downside_{horizon}d"] = test[
                    f"y_downside_{horizon}d"
                ].to_numpy()
                date_output[f"label_available_at_{horizon}d"] = test[
                    available_col
                ].to_numpy()
                decision_models[str(horizon)] = {
                    "status": "UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING",
                    "features": [
                        name.removeprefix("xrank__") for name in feature_columns
                    ],
                }
                continue
            benchmark_mix = float(
                contract["target_contract"]["benchmark_sector_mix"]["benchmark_excess"]
            )
            sector_mix = float(
                contract["target_contract"]["benchmark_sector_mix"]["sector_neutral"]
            )
            expected_alpha = (
                benchmark_mix * target_results["benchmark_excess"][0]
                + sector_mix * target_results["sector_neutral"][0]
            )
            disagreement = (
                benchmark_mix * target_results["benchmark_excess"][1]
                + sector_mix * target_results["sector_neutral"][1]
            )
            downside_probability = classifier[0]
            date_output[f"expected_absolute_{horizon}d"] = target_results["absolute"][0]
            date_output[f"expected_benchmark_excess_{horizon}d"] = target_results["benchmark_excess"][0]
            date_output[f"expected_sector_neutral_{horizon}d"] = target_results["sector_neutral"][0]
            date_output[f"expected_alpha_{horizon}d"] = expected_alpha
            date_output[f"downside_probability_{horizon}d"] = downside_probability
            date_output[f"model_disagreement_{horizon}d"] = disagreement
            date_output[f"feature_coverage_{horizon}d"] = test[f"feature_coverage_{horizon}d"].to_numpy()
            for target_kind in TARGET_KINDS:
                date_output[f"realized_{target_kind}_{horizon}d"] = test[f"y_{target_kind}_{horizon}d"].to_numpy()
            date_output[f"realized_downside_{horizon}d"] = test[f"y_downside_{horizon}d"].to_numpy()
            date_output[f"label_available_at_{horizon}d"] = test[available_col].to_numpy()
            models["downside"] = classifier[2]
            models["features"] = [
                name.removeprefix("xrank__") for name in feature_columns
            ]
            decision_models[str(horizon)] = models
            audit_rows.append(
                {
                    "decision_date": decision,
                    "horizon": horizon,
                    "status": "FIT_PIT_PURGED",
                    "embargo_cutoff": cutoff,
                    "training_rows": len(eligible),
                    "training_dates": int(eligible["feature_date"].nunique()),
                    "recent_training_rows": len(recent),
                    "recent_training_dates": int(recent["feature_date"].nunique()),
                    "max_training_feature_date": eligible["feature_date"].max(),
                    "max_label_available_at": eligible[available_col].max(),
                    "label_strictly_before_decision": bool(eligible[available_col].max() < decision),
                    "training_feature_on_or_before_embargo": bool(eligible["feature_date"].max() <= cutoff),
                    "feature_set_sha256": canonical_sha256(models["features"]),
                    "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                    "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                }
            )
        if not selection_horizons_ready:
            continue
        date_output = date_output.loc[selection_candidate_eligible].copy()
        if date_output.empty:
            audit_rows.append(
                {
                    "decision_date": decision,
                    "horizon": "selection",
                    "status": "BLOCKED_NO_SECTOR_NEUTRAL_ELIGIBLE_CANDIDATES",
                    "training_rows": 0,
                }
            )
            continue
        selection_horizons = [
            horizon
            for horizon in HORIZONS
            if float(contract["horizons"][str(horizon)]["score_weight"]) > 0.0
        ]
        horizon_alpha = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"expected_alpha_{horizon}d"]
            for horizon in selection_horizons
        )
        downside = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"downside_probability_{horizon}d"]
            for horizon in selection_horizons
        )
        disagreement = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"model_disagreement_{horizon}d"]
            for horizon in selection_horizons
        )
        date_output["expected_alpha_gross"] = horizon_alpha
        date_output["weighted_downside_probability"] = downside
        date_output["weighted_model_disagreement"] = disagreement
        date_output["entry_timing_score"] = (
            date_output["expected_alpha_21d"]
            - float(contract["score"]["downside_probability_penalty"])
            * date_output["downside_probability_21d"]
            - float(contract["score"]["long_recent_disagreement_penalty"])
            * date_output["model_disagreement_21d"]
        )
        date_output["expected_return_score"] = (
            horizon_alpha
            - float(contract["score"]["downside_probability_penalty"]) * downside
            - float(contract["score"]["long_recent_disagreement_penalty"]) * disagreement
        )
        date_output["expected_return_rank"] = date_output["expected_return_score"].rank(
            ascending=False, method="first"
        )
        date_output["research_only"] = True
        prediction_parts.append(date_output)
        if latest_date is not None and decision == latest_date:
            latest_models = {
                "decision_date": decision,
                "horizons": decision_models,
            }
    predictions = (
        pd.concat(prediction_parts, ignore_index=True)
        if prediction_parts
        else pd.DataFrame()
    )
    return predictions, pd.DataFrame(audit_rows), latest_models


def _metric_block(
    frame: pd.DataFrame,
    prediction_column: str,
    realized_column: str,
) -> dict[str, Any]:
    valid = frame.dropna(subset=[prediction_column, realized_column]).copy()
    if valid.empty:
        return {
            "rows": 0,
            "decision_dates": 0,
            "mean_monthly_spearman_ic": None,
            "positive_ic_share": None,
            "top_bottom_realized_spread": None,
            "rmse": None,
            "sign_hit_rate": None,
        }
    monthly_ic: list[float] = []
    spreads: list[float] = []
    for _, group in valid.groupby("feature_date"):
        if len(group) < 10 or group[prediction_column].nunique() < 2:
            continue
        ic = group[prediction_column].corr(group[realized_column], method="spearman")
        if pd.notna(ic):
            monthly_ic.append(float(ic))
        ranks = group[prediction_column].rank(pct=True, method="average")
        top = group.loc[ranks.ge(0.8), realized_column]
        bottom = group.loc[ranks.le(0.2), realized_column]
        if not top.empty and not bottom.empty:
            spreads.append(float(top.mean() - bottom.mean()))
    error = valid[prediction_column] - valid[realized_column]
    return {
        "rows": len(valid),
        "decision_dates": int(valid["feature_date"].nunique()),
        "mean_monthly_spearman_ic": float(np.mean(monthly_ic)) if monthly_ic else None,
        "positive_ic_share": float(np.mean(np.asarray(monthly_ic) > 0.0)) if monthly_ic else None,
        "top_bottom_realized_spread": float(np.mean(spreads)) if spreads else None,
        "rmse": float(np.sqrt(np.mean(np.square(error)))) if len(error) else None,
        "sign_hit_rate": float(
            np.mean(
                np.sign(valid[prediction_column].to_numpy())
                == np.sign(valid[realized_column].to_numpy())
            )
        ),
    }


def evaluate_predictions(
    predictions: pd.DataFrame, contract: Mapping[str, Any]
) -> dict[str, Any]:
    windows = {
        "full": (
            pd.Timestamp(contract["purge_and_windows"]["full_start"]),
            None,
        ),
        "oos2": (
            pd.Timestamp(contract["purge_and_windows"]["oos2_start"]),
            pd.Timestamp(contract["purge_and_windows"]["oos2_end"]),
        ),
        "oos": (
            pd.Timestamp(contract["purge_and_windows"]["oos_start"]),
            None,
        ),
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "metric_semantics": "cross_sectional_expected_return_diagnostics_not_portfolio_performance",
        "windows": {},
    }
    for name, (start, end) in windows.items():
        scoped = predictions[predictions["feature_date"].ge(start)].copy()
        if end is not None:
            scoped = scoped[scoped["feature_date"].le(end)].copy()
        horizon_rows: dict[str, Any] = {}
        for horizon in HORIZONS:
            horizon_rows[str(horizon)] = {
                target_kind: _metric_block(
                    scoped,
                    f"expected_{target_kind}_{horizon}d",
                    f"realized_{target_kind}_{horizon}d",
                )
                for target_kind in TARGET_KINDS
            }
            downside_valid = scoped.dropna(
                subset=[
                    f"downside_probability_{horizon}d",
                    f"realized_downside_{horizon}d",
                ]
            )
            horizon_rows[str(horizon)]["downside"] = {
                "rows": len(downside_valid),
                "brier_score": (
                    float(
                        np.mean(
                            np.square(
                                downside_valid[f"downside_probability_{horizon}d"].to_numpy(dtype=float)
                                - downside_valid[f"realized_downside_{horizon}d"].to_numpy(dtype=float)
                            )
                        )
                    )
                    if not downside_valid.empty
                    else None
                ),
            }
        result["windows"][name] = {
            "start": start,
            "end": end,
            "prediction_rows": len(scoped),
            "prediction_dates": int(scoped["feature_date"].nunique()),
            "horizons": horizon_rows,
            "composite_vs_realized_63d_benchmark_excess": _metric_block(
                scoped,
                "expected_return_score",
                "realized_benchmark_excess_63d",
            ),
        }
    return result


def public_latest_proposal(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(
            columns=[
                "feature_date",
                "ticker",
                "sector",
                "expected_return_score",
                "expected_return_rank",
                "expected_alpha_gross",
                "weighted_downside_probability",
                "weighted_model_disagreement",
                "research_only",
            ]
        )
    latest = predictions["feature_date"].max()
    forbidden = re.compile(r"^realized_|^label_available_at_|^y_")
    columns = [column for column in predictions.columns if not forbidden.search(column)]
    proposal = predictions.loc[predictions["feature_date"].eq(latest), columns].copy()
    return proposal.sort_values(
        ["expected_return_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def blocked_artifacts(
    output_dir: Path,
    *,
    blockers: list[str],
    contract: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    empty_predictions = pd.DataFrame()
    empty_predictions.to_csv(output_dir / "expected_return_predictions.csv", index=False)
    pd.DataFrame().to_csv(output_dir / "training_audit.csv", index=False)
    public_latest_proposal(empty_predictions).to_csv(
        output_dir / "latest_expected_return_proposal.csv", index=False
    )
    write_json(output_dir / "model_coefficients.json", {"status": BLOCKED_STATUS})
    write_json(
        output_dir / "expected_return_metrics.json",
        {
            "status": BLOCKED_STATUS,
            "metric_semantics": "not_computed",
            "blockers": blockers,
        },
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "family_id": contract["family_id"],
        "blockers": blockers,
        "historical_model_fit_executed": False,
        "historical_backtest_executed": False,
        "fullrun_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "portfolio_or_ledger_mutated": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        "# Run287 expected-return challenger\n\n"
        f"Status: `{BLOCKED_STATUS}`\n\n"
        "Historical fit and backtest were not executed.\n\n"
        "## Blockers\n\n"
        + "\n".join(f"- `{item}`" for item in blockers)
        + "\n",
        encoding="utf-8",
    )
    write_json(
        output_dir / "source_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_head(),
            "contract_sha256": canonical_sha256(contract),
            "inputs": inputs,
            "status": BLOCKED_STATUS,
            "historical_fit_executed": False,
        },
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = repo_path(args.contract)
    feature_store_path = repo_path(args.feature_store)
    contract = validate_contract(read_json(contract_path))
    bound_frame, binding_readiness = None, None
    binding_path = getattr(args, "input_binding", None)
    stock_family = getattr(args, "stock_leader_family", False)
    pre_fit_only = getattr(args, "pre_fit_only", False)
    if binding_path or stock_family or pre_fit_only:
        try:
            _binding_need(bool(binding_path), "stock_family_binding_required")
            bound_frame, binding_readiness = load_pre_fit_binding(args, contract)
            if pre_fit_only:
                # No GH namespace/U0 lookup, Reader, scaler, fit or predictions.
                write_json(output_dir / "pre_fit_readiness.json", binding_readiness)
                return binding_readiness
            _binding_need(bool(getattr(args, "reader_root", None)), "explicit_training_reader_root_required")
            binding_readiness["training_reader_replay"] = replay_pre_fit_training_sources(
                binding_readiness, args.reader_root)
        except (OSError, ValueError, KeyError, TypeError, ImportError, RecursionError, OverflowError) as exc:
            return blocked_artifacts(output_dir, blockers=["pre_fit_input_binding_blocked:" +
                re.sub(r"[^A-Za-z0-9_.:,=-]+", "_", str(exc))[:240]],
                contract=contract, inputs={"input_binding_scope": "METADATA_OR_TRAINING_REPLAY_REFUSED"})
    census_path = repo_path(args.u0_census)
    accepted_evidence_path = repo_path(getattr(args, "u0_accepted_evidence", ""))
    inputs = {
        "contract": fingerprint(contract_path),
        "u0_census": fingerprint(census_path),
        "u0_accepted_evidence": fingerprint(accepted_evidence_path),
        "feature_store": fingerprint(feature_store_path),
    }
    if binding_readiness is not None:
        inputs["pre_fit_input_binding"] = binding_readiness
    blockers: list[str] = []
    census: Any = None
    accepted_evidence: Any = None
    canonical_artifact: Any = None
    if not census_path.is_file():
        blockers.append("u0_census_missing")
    else:
        try:
            census = read_json(census_path)
        except Exception as exc:
            blockers.append(f"u0_census_unreadable:{type(exc).__name__}")
    if not accepted_evidence_path.is_file():
        blockers.append("u0_accepted_evidence_missing")
    else:
        try:
            accepted_evidence = read_json(accepted_evidence_path)
        except Exception as exc:
            blockers.append(
                f"u0_accepted_evidence_unreadable:{type(exc).__name__}"
            )
    artifact_id = getattr(args, "u0_accepted_artifact_id", None)
    if type(artifact_id) is not int or artifact_id <= 0:
        blockers.append("u0_accepted_artifact_id_missing_or_invalid")
    else:
        try:
            canonical_artifact = load_canonical_u0_artifact(
                artifact_id, contract
            )
            inputs["u0_canonical_artifact"] = {
                key: canonical_artifact.get(key)
                for key in (
                    "artifact_id",
                    "workflow_run_id",
                    "workflow_path",
                    "head_sha",
                    "artifact_digest",
                )
            }
        except Exception as exc:
            blockers.append(
                f"u0_canonical_artifact_unverified:{type(exc).__name__}"
            )
    if census is not None and accepted_evidence is not None:
        blockers.extend(
            u0_gate(census, accepted_evidence, canonical_artifact, contract)
        )
    trial_floor = (
        (census.get("summary") or {}).get(
            "conservative_historical_trial_count_lower_bound"
        )
        if isinstance(census, dict)
        else None
    )
    inputs["u0_conservative_historical_trial_count_lower_bound"] = trial_floor
    frame = pd.DataFrame() if bound_frame is None else bound_frame
    if bound_frame is not None:
        blockers.extend(input_readiness(frame, contract))
    elif not feature_store_path.is_file():
        blockers.append("feature_store_missing")
    else:
        try:
            frame = pd.read_parquet(feature_store_path)
            blockers.extend(input_readiness(frame, contract))
        except Exception as exc:
            blockers.append(f"feature_store_unreadable:{type(exc).__name__}")
    blockers = sorted(set(blockers))
    if blockers:
        return blocked_artifacts(
            output_dir,
            blockers=blockers,
            contract=contract,
            inputs=inputs,
        )

    try:
        prepared = prepare_frame(frame, contract)
        if binding_readiness is not None:
            # Use actual original availability, not merely the outcome session's
            # date, in the unchanged purge/embargo comparisons. Never restamp.
            apply_pre_fit_label_clocks(prepared, binding_readiness)
    except Exception as exc:
        detail = re.sub(r"[^A-Za-z0-9_.:,=-]+", "_", str(exc)).strip("_")
        return blocked_artifacts(
            output_dir,
            blockers=[
                f"feature_store_semantic_validation_failed:{type(exc).__name__}:"
                f"{detail[:240]}"
            ],
            contract=contract,
            inputs=inputs,
        )
    predictions, audit, latest_models = walk_forward_predictions(prepared, contract)
    if predictions.empty:
        return blocked_artifacts(
            output_dir,
            blockers=["no_pit_purged_walk_forward_predictions"],
            contract=contract,
            inputs=inputs,
        )
    latest_input_date = pd.Timestamp(prepared["feature_date"].max()).normalize()
    latest_scored_date = pd.Timestamp(predictions["feature_date"].max()).normalize()
    if latest_scored_date != latest_input_date:
        return blocked_artifacts(
            output_dir,
            blockers=[
                "latest_input_decision_not_scored:"
                f"input={latest_input_date.date()}:scored={latest_scored_date.date()}"
            ],
            contract=contract,
            inputs=inputs,
        )
    metrics = evaluate_predictions(predictions, contract)
    metrics["multiple_testing_context"] = {
        "conservative_historical_trial_count_lower_bound": trial_floor,
        "source": "canonical_u0_v3_accepted_evidence",
        "used_for_model_or_parameter_tuning": False,
        "required_for_later_dsr_pbo_spa_gate": True,
    }
    proposal = public_latest_proposal(predictions)
    predictions.to_csv(output_dir / "expected_return_predictions.csv", index=False)
    audit.to_csv(output_dir / "training_audit.csv", index=False)
    proposal.to_csv(output_dir / "latest_expected_return_proposal.csv", index=False)
    write_json(output_dir / "expected_return_metrics.json", metrics)
    write_json(output_dir / "model_coefficients.json", latest_models)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "family_id": contract["family_id"],
        "latest_decision_date": proposal["feature_date"].max() if not proposal.empty else None,
        "prediction_rows": len(predictions),
        "prediction_dates": int(predictions["feature_date"].nunique()),
        "latest_candidate_count": len(proposal),
        "conservative_historical_trial_count_lower_bound": trial_floor,
        "historical_model_fit_executed": True,
        "historical_backtest_executed": False,
        "broker_ledger_metrics_available": False,
        "fullrun_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "portfolio_or_ledger_mutated": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        "# Run287 expected-return challenger\n\n"
        f"Status: `{READY_STATUS}`\n\n"
        f"Predictions: {len(predictions):,} rows across "
        f"{int(predictions['feature_date'].nunique())} decisions.\n\n"
        "These are cross-sectional research diagnostics, not after-cost portfolio performance. "
        "No target book, order, cash change, ledger mutation, fullrun, or promotion occurred.\n",
        encoding="utf-8",
    )
    output_fingerprints = {
        name: fingerprint(output_dir / name)
        for name in contract["outputs"]
        if name != "source_manifest.json" and (output_dir / name).is_file()
    }
    write_json(
        output_dir / "source_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_head(),
            "contract_sha256": canonical_sha256(contract),
            "inputs": inputs,
            "outputs": output_fingerprints,
            "status": READY_STATUS,
            "conservative_historical_trial_count_lower_bound": trial_floor,
            "historical_fit_executed": True,
            "historical_backtest_executed": False,
        },
    )
    return summary


# ER-H1 V2 is a separate opt-in label precheck; the historical V1 model and
# HORIZONS=(21,63,126) remain byte/behavior-compatible by default.
V2_H1_252_CONTRACT_SHA256 = "1937849e03af1c2e2fd4fda42d65dbb1cab657b1d8c41d01980ebd03631250dd"
V2_H1_MAX_ROWS = 10000
V2_H1_ALLOWED_BASES = frozenset(("TOTAL_RETURN", "PROVIDER_ADJUSTED_CLOSE_PROXY"))
V2_H1_TIMESTAMP_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
V2_H1_DAY_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
# Match the existing A3 Candidate Registry identifier grammar; do not trim
# or invent a new security identity from caller-supplied text.
V2_H1_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}\Z")


def validate_v2_h1_252_contract(contract: Any) -> dict[str, Any]:
    """Read-only V2 H1 specification. It cannot be passed to V1 model fit."""
    if not isinstance(contract, dict) or contract.get("schema_version") != (
        "run287-er-v2-h1-252-label-only-v1"
    ):
        raise ValueError("v2_h1_contract_schema")
    if canonical_sha256(contract) != V2_H1_252_CONTRACT_SHA256:
        raise ValueError("v2_h1_contract_hash_mismatch")
    if (contract["family_id"] != "future_expected_excess_return_multihorizon_v1"
        or contract["v1_contract_sha256"] != EXPECTED_CONTRACT_SHA256
        or contract["horizons_nyse_sessions"] != [21, 63, 126, 252]
        or contract["purge_and_windows"]["embargo_nyse_sessions"] != 252
        or contract["safety"]["model_fit_allowed"] is not False
        or contract["safety"]["validated_er_allowed"] is not False
        or contract["safety"]["A5_eligible_input"] is not False):
        raise ValueError("v2_h1_contract_invariant")
    return contract


def _v2_h1_aware_stamp(value: Any) -> pd.Timestamp:
    """Explicit aware timestamps only; never infer a publication clock."""
    if not isinstance(value, str) or V2_H1_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError("timestamp_precise_timezone_required")
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("invalid_timestamp")
        return stamp.tz_convert("UTC")
    except (ValueError, OverflowError, TypeError) as exc:
        raise ValueError("invalid_timestamp") from exc


def _v2_h1_nyse_day(value: Any) -> pd.Timestamp:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None or value != value.normalize():
            raise ValueError("not_nyse_day")
        value = value.strftime("%Y-%m-%d")
    if not isinstance(value, str) or V2_H1_DAY_RE.fullmatch(value) is None:
        raise ValueError("not_nyse_day")
    try:
        stamp = pd.Timestamp(value)
        if stamp.strftime("%Y-%m-%d") != value:
            raise ValueError("not_nyse_day")
        sessions = NYSE.valid_days(start_date=stamp, end_date=stamp)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("not_nyse_day") from exc
    if len(sessions) != 1:
        raise ValueError("not_nyse_day")
    return stamp.normalize()


def _v2_h1_last_completed_nyse_session(decision: pd.Timestamp) -> pd.Timestamp:
    """Anchor to the last *completed* U.S. session, not a UTC calendar date.

    UTC midnight, daylight-saving changes, holidays and intraday analysis can
    otherwise select a future U.S. session and weaken the embargo.
    """
    if not isinstance(decision, pd.Timestamp) or decision.tzinfo is None:
        raise ValueError("v2_h1_aware_decision_required")
    try:
        local_date = decision.tz_convert("America/New_York").date()
        last = pd.Timestamp(local_date)
        first = last - pd.Timedelta(days=14)
        session_closes = NYSE.schedule(
            start_date=first.strftime("%Y-%m-%d"),
            end_date=last.strftime("%Y-%m-%d"),
        )["market_close"]
        completed = session_closes[
            pd.DatetimeIndex(session_closes).tz_convert("UTC") <= decision
        ]
        if completed.empty:
            raise ValueError("v2_h1_no_completed_nyse_session")
        session = pd.Timestamp(completed.index[-1])
        if session.tzinfo is not None:
            session = session.tz_localize(None)
        return _v2_h1_nyse_day(session.normalize())
    except (ValueError, TypeError, IndexError, KeyError, OverflowError) as exc:
        raise ValueError("v2_h1_completed_session_unavailable") from exc


def _v2_h1_return(value: Any) -> float:
    """Do not coerce missing, bool, string or nonfinite returns to zero."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise ValueError("return_not_numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("return_not_finite") from exc
    if not math.isfinite(result) or result < -1.0:
        raise ValueError("return_not_finite_or_below_minus_one")
    return result


def _v2_h1_observed_at() -> pd.Timestamp:
    """One runtime UTC snapshot; never supplied by the label caller."""
    return pd.Timestamp(datetime.now(timezone.utc))


def audit_v2_h1_252_labels(
    frame: pd.DataFrame, contract: Mapping[str, Any], *, decision_at: str
) -> dict[str, Any]:
    """Supplied-input 252-session *realized-label* precheck; never ER.

    Not independent source/PIT authentication; no fit, prediction, publication
    or authority. Retains every security/feature-date row, even blocked ones.
    """
    observed_at = _v2_h1_observed_at()
    cfg = validate_v2_h1_252_contract(contract)
    decision = _v2_h1_aware_stamp(decision_at)
    if decision > observed_at:
        raise ValueError("v2_h1_future_decision")
    decision_day = _v2_h1_last_completed_nyse_session(decision)
    if type(frame) is not pd.DataFrame or len(frame) > V2_H1_MAX_ROWS:
        raise ValueError("v2_h1_invalid_or_excessive_input_rows")
    required_identity = ("asset_id", "issuer_id", "feature_date")
    missing = [name for name in required_identity if name not in frame.columns]
    if missing:
        raise ValueError("v2_h1_missing_identity:" + ",".join(missing))
    fields = cfg["fields"]
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    embargo_cutoff = nyse_embargo_cutoffs([decision_day], 252)[decision_day]
    if embargo_cutoff is None:
        raise ValueError("v2_h1_insufficient_embargo_calendar")

    # Validate identities and gather the whole supplied cohort before any
    # row can pass: a later conflicting SPY value invalidates earlier rows.
    prepared_rows = []
    benchmark_values: dict[pd.Timestamp, set[float]] = {}
    for _, item in frame.iterrows():
        asset = item.get("asset_id")
        issuer = item.get("issuer_id")
        if any(not isinstance(value, str) or value != value.strip()
               or V2_H1_ID_RE.fullmatch(value) is None
               for value in (asset, issuer)):
            raise ValueError("v2_h1_noncanonical_security_identity")
        feature_day = _v2_h1_nyse_day(item["feature_date"])
        identity = (asset, feature_day.strftime("%Y-%m-%d"))
        if identity in seen:
            raise ValueError("v2_h1_duplicate_asset_decision")
        seen.add(identity)
        prepared_rows.append((item, asset, issuer, feature_day))
        try:
            benchmark_value = _v2_h1_return(item.get(fields["benchmark_return"]))
        except ValueError:
            pass  # The row retains its existing invalid-return blocker.
        else:
            benchmark_values.setdefault(feature_day, set()).add(benchmark_value)

    for item, asset, issuer, feature_day in prepared_rows:
        reasons: list[str] = []
        if len(benchmark_values.get(feature_day, set())) > 1:
            reasons.append("BENCHMARK_RETURN_CONFLICT_FOR_FEATURE_DATE")
        expected_end = expected_nyse_label_ends(
            pd.Series([feature_day], dtype="datetime64[ns]"), 252
        ).iloc[0]
        # NYSE controls the exact entry/end sessions. Never replace with an
        # available later bar, 365 calendar days or 2x a 126-session label.
        if pd.isna(expected_end):
            reasons.append("EXACT_252_END_NOT_RESOLVED")
        for which in ("stock_label_end", "benchmark_label_end"):
            value = item.get(fields[which])
            if value is None or (isinstance(value, (float, np.floating))
                                 and math.isnan(float(value))):
                reasons.append(which.upper() + "_MISSING")
                continue
            if not isinstance(value, (str, pd.Timestamp)):
                reasons.append(which.upper() + "_INVALID")
                continue
            try:
                day = _v2_h1_nyse_day(value)
                if pd.isna(expected_end) or day != expected_end:
                    reasons.append(which.upper() + "_NOT_EXACT_252")
            except (TypeError, ValueError):
                reasons.append(which.upper() + "_INVALID")
        if item.get(fields["benchmark_identity"]) != cfg["benchmark"]["identity"]:
            reasons.append("BENCHMARK_IDENTITY_MISMATCH")
        if item.get(fields["benchmark_source"]) != cfg["benchmark"]["source"]:
            reasons.append("BENCHMARK_SOURCE_MISMATCH")
        basis1, basis2 = (item.get(fields["stock_return_basis"]),
                           item.get(fields["benchmark_return_basis"]))
        if (not isinstance(basis1, str) or not isinstance(basis2, str)
            or basis1 not in V2_H1_ALLOWED_BASES or basis1 != basis2):
            reasons.append("RETURN_BASIS_MISMATCH_OR_UNKNOWN")

        values: dict[str, float] = {}
        for which in ("stock_return", "benchmark_return"):
            try:
                values[which] = _v2_h1_return(item.get(fields[which]))
            except ValueError:
                reasons.append(which.upper() + "_INVALID_OR_MISSING")

        try:
            available = _v2_h1_aware_stamp(item.get(fields["label_available_at"]))
            if pd.notna(expected_end):
                close = NYSE.schedule(
                    start_date=expected_end, end_date=expected_end
                )["market_close"].iloc[0]
                if available < pd.Timestamp(close).tz_convert("UTC"):
                    reasons.append("LABEL_AVAILABLE_BEFORE_ACTUAL_NYSE_CLOSE")
            if available >= decision:
                reasons.append("LABEL_NOT_MATURE_STRICTLY_BEFORE_DECISION")
        except (ValueError, TypeError, KeyError, IndexError):
            reasons.append("LABEL_AVAILABILITY_MISSING_OR_UNVERIFIED_CLOCK")
        if feature_day > embargo_cutoff:
            reasons.append("FEATURE_WITHIN_252_SESSION_EMBARGO")

        lifecycle = item.get(fields["security_lifecycle_status"])
        if not isinstance(lifecycle, str) or lifecycle not in cfg["lifecycle"]["values"]:
            reasons.append("LIFECYCLE_UNKNOWN")
        elif lifecycle != "ACTIVE":
            # Even a supplied receipt SHA is not independently authenticated
            # terminal cash proceeds. Retain the row and block this H1 gate.
            reasons.append("TERMINAL_PROCEEDS_A1_ADMISSION_REQUIRED")

        passed = not reasons
        rows.append({
            "asset_id": asset,
            "issuer_id": issuer,
            "feature_date": feature_day.strftime("%Y-%m-%d"),
            "expected_exact_label_end": (None if pd.isna(expected_end)
                                         else expected_end.strftime("%Y-%m-%d")),
            "precheck_status": ("SUPPLIED_LABEL_CONSISTENT_RESEARCH_ONLY" if passed
                                else "BLOCKED_LABEL_EVIDENCE"),
            "blockers": reasons,
            "observed_stock_return": values.get("stock_return") if passed else None,
            "observed_spy_return": values.get("benchmark_return") if passed else None,
            "observed_excess_return": (values["stock_return"] - values["benchmark_return"]
                                       if passed else None),
            "source_pit_authenticated": False,
            "training_authorized": False,
            "gross_expected_return_12m": None,
            "net_expected_return_12m": None,
            "downside_probability": None,
            "expected_drawdown": None,
            "A5_eligible_input": False,
        })
    return {
        "schema_version": cfg["schema_version"],
        "contract_sha256": V2_H1_252_CONTRACT_SHA256,
        "scope": "SUPPLIED_LABEL_PREFLIGHT_NOT_SOURCE_OR_ECONOMIC_ADMISSION",
        "decision_at": decision.isoformat(),
        "observed_at": observed_at.isoformat(),
        "decision_completed_nyse_session": decision_day.strftime("%Y-%m-%d"),
        "embargo_cutoff_nyse_session": embargo_cutoff.strftime("%Y-%m-%d"),
        "cohort_denominator": len(rows),
        "precheck_consistent_rows": sum(
            row["precheck_status"] == "SUPPLIED_LABEL_CONSISTENT_RESEARCH_ONLY"
            for row in rows
        ),
        "model_fit_allowed": False,
        "validated_er_available": False,
        "A5_eligible_input": False,
        "records": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        default="docs/run287_expected_return_challenger_contract.json",
    )
    parser.add_argument("--u0-census")
    parser.add_argument("--u0-accepted-evidence")
    parser.add_argument("--u0-accepted-artifact-id", type=int)
    parser.add_argument("--feature-store", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input-binding", help="Exact local stock-leader input binding; no source self-approval")
    parser.add_argument("--expected-input-binding-sha256")
    parser.add_argument("--input-binding-root", help="Explicit bounded local metadata directory")
    parser.add_argument("--reader-root", help="Existing local immutable Source transport; training replay only")
    parser.add_argument("--stock-leader-family", action="store_true", help="Require binding/hash before the existing V1 gates")
    parser.add_argument("--pre-fit-only", action="store_true", help="Offline metadata binding only: no GH/Reader/fit")
    args = parser.parse_args()
    if (args.stock_leader_family or args.pre_fit_only or args.input_binding) and not (
            args.input_binding and args.expected_input_binding_sha256):
        parser.error("stock-leader inputs require --input-binding and --expected-input-binding-sha256")
    if not args.pre_fit_only and not all((args.u0_census,args.u0_accepted_evidence,args.u0_accepted_artifact_id)):
        parser.error("normal fitting requires all original canonical U0 arguments")
    return args


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(json_clean(summary), sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
