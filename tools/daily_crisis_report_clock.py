"""Bounded, report-only adapter for existing Chameleon artifacts.

This module does not run a risk model, fetch data, send a message, or write a
canonical history. Caller-supplied immutable pins authorize reads, not PIT or
economic promotion. The Monitor writes only a candidate dry-run receipt.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from tools import build_run287_chameleon_macro_risk as risk

ROOT = Path(__file__).resolve().parents[1]
UTC, NY = timezone.utc, ZoneInfo("America/New_York")
HASH = re.compile(r"[0-9a-f]{64}")
SLOTS = ("INTRADAY", "AFTER_CLOSE")
SAFETY = dict(report_only=True, notification_enabled=False,
              order_generation_allowed=False, ledger_mutation_allowed=False,
              source_promotion_allowed=False, pit_promotion_allowed=False,
              target_book_write_allowed=False, fullrun_allowed=False)


class Blocked(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise Blocked(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    need(isinstance(value, str) and HASH.fullmatch(value), "HASH_REQUIRED")
    return value


def stamp(value):
    need(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value),
        "EXACT_SOURCE_CLOCK_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        need(parsed.utcoffset() is not None, "EXACT_SOURCE_CLOCK_REQUIRED")
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise Blocked("INVALID_CLOCK") from None


def bounded(path, limit=8 * 1024**2):
    path = Path(path)
    need(not path.is_symlink(), "INPUT_NOT_REGULAR")
    if os.name == "nt":
        need(":" not in path.name and path.stem.upper() not in
             {"CON", "PRN", "AUX", "NUL", *("COM"+str(n) for n in range(1,10)),
              *("LPT"+str(n) for n in range(1,10))}, "INPUT_NOT_REGULAR")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) |
                         getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        before = os.fstat(descriptor)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "INPUT_SIZE_OR_TYPE")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        current = path.lstat()
        need(len(raw) <= limit and len(raw) == before.st_size == after.st_size
             and (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)
             and (current.st_ino, current.st_mtime_ns, current.st_size) ==
                 (after.st_ino, after.st_mtime_ns, after.st_size), "INPUT_CHANGED")
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)


def decode(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            need(key not in out, "DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Blocked("NONFINITE_JSON")))
    except (ValueError, UnicodeError, RecursionError):
        raise Blocked("INVALID_JSON") from None


def table(raw):
    # Bound logical records/cells BEFORE csv/pandas can allocate field objects.
    text = raw.decode("utf-8-sig")
    quoted, closed, started = False, False, False
    fields, total, records, length, i = 1, 0, 0, 0, 0
    while i < len(text):
        char = text[i]; length += 1
        need(length <= 16384, "CSV_RECORD_LIMIT")
        if quoted:
            if char == '"':
                if i + 1 < len(text) and text[i+1] == '"':
                    i += 1; length += 1
                else:
                    quoted, closed = False, True
        elif char == '"':
            need(not started and not closed, "CSV_QUOTING")
            quoted, started = True, True
        elif char in ",\n":
            if char == ',':
                fields += 1; need(fields <= 64, "CSV_COLUMN_LIMIT")
            else:
                records += 1; total += fields
                need(records <= 150001 and total <= 3_000_000, "CSV_CELL_LIMIT")
                fields, length = 1, 0
            started, closed = False, False
        elif char == '\r':
            need(i+1 < len(text) and text[i+1] == '\n', "CSV_QUOTING")
        else:
            need(not closed, "CSV_QUOTING")
            started = True
        i += 1
    need(not quoted, "CSV_QUOTING")
    need(records <= 150000 and total + fields <= 3_000_000, "CSV_CELL_LIMIT")
    rows = list(csv.reader(io.StringIO(text), strict=True))
    need(rows and len(rows[0]) == len(set(rows[0])) and len(rows[0]) <= 64, "CSV_HEADER")
    need(all(len(row) == len(rows[0]) for row in rows), "CSV_SHAPE")
    return pd.DataFrame(rows[1:], columns=rows[0])


def read_ref(root, reference, limit=32*1024**2):
    need(isinstance(reference, dict), "ARTIFACT_REFERENCE")
    expected = sha(reference.get("sha256"))
    name = reference.get("path")
    need(isinstance(name, str) and 0 < len(name) < 1024, "ARTIFACT_REFERENCE")
    path = Path(name)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve()
    need(resolved.is_relative_to(root.resolve()), "INPUT_OUTSIDE_APPROVED_ROOT")
    raw = bounded(path, limit)
    need(digest(raw) == expected, "ARTIFACT_HASH_MISMATCH")
    if "size_bytes" in reference:
        need(type(reference["size_bytes"]) is int and len(raw) == reference["size_bytes"], "ARTIFACT_SIZE_MISMATCH")
    return raw


def context_table(raw):
    table(raw)  # Bound bytes/records/shape before using the producer's parser.
    return pd.read_csv(io.BytesIO(raw))


def session_times(session):
    need(isinstance(session, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", session), "SESSION_DATE")
    schedule = mcal.get_calendar("NYSE").schedule(start_date=session, end_date=session)
    if schedule.empty:
        return None
    row = schedule.iloc[0]
    opening, closing = row.market_open.to_pydatetime(), row.market_close.to_pydatetime()
    normal = datetime.fromisoformat(session).replace(hour=13, tzinfo=NY).astimezone(UTC)
    return dict(open=opening, close=closing,
                INTRADAY=min(normal, closing-timedelta(hours=1)),
                AFTER_CLOSE=closing+timedelta(hours=1))


def trusted_now():
    return datetime.now(UTC)


def known_label(value):
    return (isinstance(value,str) and 0 < len(value) <= 96 and value == value.strip() and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/ -]*",value) is not None and
            value.upper() not in {"UNKNOWN","NONE","NULL","UNVERIFIED","MISSING","UNDEFINED","N/A","NA","NOT_VERIFIED"})


def load_expectations(path, expected_sha, producer):
    need(path is not None, "ACTUAL_EXPECTATIONS_REQUIRED")
    raw = bounded(path, 1024**2)
    need(digest(raw) == sha(expected_sha), "EXPECTATIONS_PIN_MISMATCH")
    value = decode(raw)
    need(value.get("schema") == "daily-crisis-expectations-v1" and
         value.get("purpose") == "US_MACRO_REPORT" and value.get("producer_sha256") == producer and
         value.get("risk_contract_semantic_sha256") == risk.CANONICAL_CONTRACT_SEMANTIC_SHA256 and
         isinstance(value.get("sources"), dict) and isinstance(value.get("components"), dict) and
         isinstance(value.get("context_fields"), dict) and isinstance(value.get("inputs"),dict), "EXPECTATIONS_CONTRACT")
    for name in ("metrics","calendar"):
        sha(value["inputs"].get(name))
    if value["inputs"].get("context") is not None:
        sha(value["inputs"]["context"])
    for key, source in value["sources"].items():
        sha(key)
        need(isinstance(source,dict) and known_label(source.get("source_id")) and
             known_label(source.get("source_kind")), "EXPECTATIONS_IDENTITY_REQUIRED")
        sha(source.get("clock_sha256"))
    for scope in ("components","context_fields"):
        for name, spec in value[scope].items():
            need(known_label(name) and isinstance(spec,dict) and known_label(spec.get("unit")) and
                 known_label(spec.get("seasonal_basis")) and isinstance(spec.get("source_ids"),list) and
                 0 < len(spec["source_ids"]) <= 128 and all(known_label(s) for s in spec["source_ids"]),
                 "EXPECTATIONS_UNIT_OR_IDENTITY_REQUIRED")
    return value, digest(raw)


def expected_units(row, item, key, expectations, context_fields):
    source = expectations["sources"].get(key)
    need(isinstance(source, dict) and known_label(source.get("source_id")) and
         source.get("source_id") == item.get("source_id") and
         source.get("source_kind") == row.source_kind, "EXPECTED_SOURCE_IDENTITY_MISMATCH")
    component = getattr(row, "component", None)
    fields = [component] if component else [name for name in context_fields
        if hasattr(row, name) and str(getattr(row, name)) not in ("", "None", "nan")]
    wanted = expectations["components"] if component else expectations["context_fields"]
    for name in fields:
        spec, observed = wanted.get(name), item.get("units", {}).get(name)
        need(isinstance(spec, dict) and isinstance(observed, dict) and
             isinstance(spec.get("source_ids"), list) and "*" not in spec["source_ids"] and
             source["source_id"] in spec["source_ids"] and spec.get("unit") and
             spec.get("seasonal_basis") and spec["unit"] == observed.get("unit") and
             spec["seasonal_basis"] == observed.get("seasonal_basis"), "COMPONENT_UNIT_CONTRACT_MISMATCH")
        if component:
            need(spec.get("axis") == row.axis, "COMPONENT_AXIS_CONTRACT_MISMATCH")


def clock_check(records, metrics, cutoff, now, input_kind, expectations=None, context_fields=()):
    need(isinstance(records, list) and len(records) <= 5000, "CLOCK_MANIFEST")
    indexed, facts, issues = {}, [], []
    for item in records:
        try:
            key = sha(item.get("source_sha256"))
            need(key not in indexed, "DUPLICATE_SOURCE_CLOCK")
            if input_kind == "ACTUAL":
                approved_source = expectations["sources"].get(key)
                need(isinstance(approved_source, dict) and approved_source.get("source_id") == item.get("source_id"),
                     "EXPECTED_SOURCE_IDENTITY_MISMATCH")
                need(approved_source.get("clock_sha256") == digest(canonical(item)), "EXPECTED_SOURCE_CLOCK_MISMATCH")
            indexed[key] = item
            need(item.get("precision") in ("SECOND", "MICROSECOND"), "DATE_ONLY_PUBLICATION_UNKNOWN")
            published, available = stamp(item.get("published_at")), stamp(item.get("available_at"))
            collected, expiry = stamp(item.get("collected_at")), stamp(item.get("expiry"))
            need(published <= available <= collected <= now < expiry and available <= cutoff < expiry, "SOURCE_CLOCK_OUT_OF_RANGE")
            need(item.get("purpose") == "US_MACRO_REPORT" and item.get("purpose_eligible") is True,
                 "PURPOSE_NOT_ELIGIBLE")
            need(item.get("rights") == "PRIVATE_RESEARCH_ALLOWED" and item.get("identity_verified") is True,
                 "SOURCE_RIGHTS_OR_IDENTITY_UNKNOWN")
            need(item.get("availability_evidence_verified") is True and
                 isinstance(item.get("availability_evidence_ref"), str) and item["availability_evidence_ref"],
                 "AVAILABILITY_PROOF_MISSING")
            need(item.get("unit") and item.get("unit") == item.get("expected_unit") and
                 item.get("seasonal_basis") and item.get("seasonal_basis") == item.get("expected_seasonal_basis"),
                 "UNIT_OR_SEASONAL_BASIS_MISMATCH")
            need(item.get("input_kind") == input_kind, "FIXTURE_ACTUAL_MIX")
            need(item.get("revision") in ("ORIGINAL", "AS_KNOWN_VINTAGE"), "REVISION_PROOF_MISSING")
            indexed[key] = (item, available)
            # Source metadata is untrusted; retain only registered display labels.
            source_id = item.get("source_id")
            source_id = source_id if source_id in {"ALPACA_SIP", "FRED", "ALFRED", "SEC", "ISSUER_IR",
                                                   "CBOE", "ICE", "MARKET_BREADTH", "SYNTHETIC_a", "SYNTHETIC_b"} else "REDACTED"
            unit = item["unit"] if item["unit"] in {"PERCENT", "BASIS_POINTS", "USD", "INDEX", "RATIO", "COUNT", "LEVEL", "fixture-unit"} else "UNREGISTERED"
            basis = item["seasonal_basis"] if item["seasonal_basis"] in {"SA", "NSA", "SAAR", "NOT_APPLICABLE", "fixture"} else "UNREGISTERED"
            facts.append(dict(source_sha256=key, source_id=source_id, unit=unit,
                              seasonal_basis=basis, available_at=available.isoformat(),
                              collected_at=collected.isoformat(), expiry=expiry.isoformat(),
                              source_ref_sha256=digest(str(item.get("source_ref", "")).encode())))
        except (Blocked, TypeError, AttributeError) as exc:
            issues.append(str(exc) if isinstance(exc, Blocked) else "CLOCK_MANIFEST")
    for row in metrics.itertuples(index=False):
        try:
            entry = indexed.get(row.source_sha256)
            need(isinstance(entry, tuple), "SOURCE_CLOCK_MISSING")
            item, available = entry
            if input_kind == "ACTUAL":
                expected_units(row, item, row.source_sha256, expectations, context_fields)
            # Original clocks govern each historical decision, never latest_date.
            decision = row.decision_time_utc
            available_from = row.available_from
            decision = decision.isoformat() if isinstance(decision, (pd.Timestamp,datetime)) else str(decision)
            available_from = available_from.isoformat() if isinstance(available_from, (pd.Timestamp,datetime)) else str(available_from)
            need(available <= stamp(decision) <= cutoff, "HISTORICAL_AVAILABILITY_VIOLATION")
            need(stamp(available_from) >= available, "FABRICATED_METRIC_AVAILABILITY")
            if getattr(row, "axis", None) == "market_breadth":
                need(type(item.get("eligible_breadth_symbols")) is int and item["eligible_breadth_symbols"] >= 500
                     and item.get("breadth_denominator_verified") is True, "BREADTH_DENOMINATOR_UNVERIFIED")
        except (Blocked, AttributeError) as exc:
            issues.append(str(exc) if isinstance(exc, Blocked) else "METRIC_CLOCK_COLUMNS")
    used_sources = set(metrics.source_sha256)
    return [fact for fact in facts if fact["source_sha256"] in used_sources], sorted(set(issues))


def frame_bytes(frame):
    output = frame.copy()
    for column in output:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].map(lambda v: v.isoformat() if not pd.isna(v) else "")
    return output.to_csv(index=False, lineterminator="\n").encode()


@lru_cache(maxsize=2)
def verified_derivation(metrics_raw, context_raw, calendar_raw, contract_raw, producer, verifier_code_sha, as_of_session):
    """Bounded process-local verification cache; no canonical calculation/write."""
    contract = decode(contract_raw)
    calendar = risk.validate_calendar(table(calendar_raw), digest(calendar_raw))
    raw_metrics = table(metrics_raw)
    as_of = pd.Timestamp(as_of_session)
    metrics = risk.validate_metrics(raw_metrics, contract, as_of, calendar)
    decisions = {date:g.decision_time_utc.iloc[0] for date,g in metrics.groupby("decision_date")}
    sessions = {date:(int(g.nyse_session_ordinal.iloc[0]),str(g.calendar_source_sha256.iloc[0]))
                for date,g in metrics.groupby("decision_date")}
    context = risk.validate_context(context_table(context_raw) if context_raw else None,
                                    contract, as_of, decisions, sessions, calendar)
    components = risk.compute_component_percentiles(metrics, contract)
    axes = risk.aggregate_axes(components, contract)
    history = risk.build_daily_risk(axes, context, contract)
    return frame_bytes(axes), frame_bytes(history)


def prefix_digest(source, through):
    values = []
    consumed = set()
    for name in ("metrics", "context", "axes_frame", "history"):
        frame = source[name].copy()
        frame["decision_date"] = pd.to_datetime(frame.decision_date).dt.strftime("%Y-%m-%d")
        frame = frame[frame.decision_date <= through].drop(columns=["calendar_source_sha256"], errors="ignore")
        if name in ("metrics", "context") and "source_sha256" in frame:
            consumed.update(frame.source_sha256)
        frame = frame.sort_values([c for c in ("decision_date", "axis", "component") if c in frame])
        values.append((name, digest(frame_bytes(frame))))
    values.append(("source_clocks", digest(canonical(sorted(
        (item for item in source["source_clocks"] if item["source_sha256"] in consumed),
        key=lambda item: item["source_sha256"])))))
    if source["expectations"] is not None:
        cfg = source["expectations"]
        # Bind the already-consumed Source/unit contracts; appending new source
        # identities to the separately approved config must not rewrite them.
        used = []
        for scope, frame in (("components", source["metrics"]), ("context_fields", source["context"])):
            if frame.empty:
                continue
            frame = frame[frame.decision_date.dt.date.astype(str) <= through]
            for row in frame.itertuples(index=False):
                fields = [row.component] if scope == "components" else [f for f in source["context_fields"]
                    if hasattr(row,f) and not pd.isna(getattr(row,f))]
                for field in fields:
                    used.append(canonical([scope,field,row.source_sha256,cfg["sources"][row.source_sha256],cfg[scope][field]]).decode())
        values.append(("expectations", digest(canonical(sorted(set(used))))))
    return digest(canonical(values))


def load_source(path, expected_sha, source_root, cutoff, now, *, session=None, slot=None,
                expectations_path=None, expected_expectations_sha=None):
    raw = bounded(path, 4*1024**2)
    need(digest(raw) == sha(expected_sha), "SOURCE_VIEW_PIN_MISMATCH")
    view = decode(raw)
    need(view.get("schema") == "daily-crisis-source-view-v1" and
         view.get("input_kind") in ("FIXTURE", "ACTUAL"), "SOURCE_VIEW_SCHEMA")
    root = Path(source_root).resolve()
    manifest_raw = read_ref(root, view.get("chameleon_manifest"), 512*1024)
    manifest = decode(manifest_raw)
    need(manifest.get("status") in ("READY_CHAMELEON_MACRO_RISK_REPORT_ONLY",
         "READY_CHAMELEON_MACRO_RISK_REPORT_ONLY_DATA_INSUFFICIENT") and
         manifest.get("blockers") == [], "CHAMELEON_PRODUCER_NOT_READY")
    need(manifest.get("schema_version") == risk.SCHEMA_VERSION and
         manifest.get("source_inputs_unchanged") is True and manifest.get("report_only") is True,
         "CHAMELEON_MANIFEST")
    for flag in ("selector_executed", "target_books_mutated", "orders_generated", "ledger_mutated", "fullrun_executed"):
        need(manifest.get(flag) is False, "UPSTREAM_ECONOMIC_AUTHORITY")
    producer = manifest.get("code", {}).get("builder", {}).get("sha256")
    current = bounded(Path(risk.__file__), 256*1024)
    need(producer in (digest(current), digest(current.replace(b'\r\n', b'\n'))), "UNREVIEWED_CHAMELEON_PRODUCER")
    contract_ref = manifest["inputs"]["contract"]
    need(Path(contract_ref["path"]).resolve() == risk.DEFAULT_CONTRACT.resolve(), "NONCANONICAL_CONTRACT_PATH")
    contract_raw = bounded(risk.DEFAULT_CONTRACT, 128*1024)
    need(digest(contract_raw) == sha(contract_ref["sha256"]), "ARTIFACT_HASH_MISMATCH")
    need(risk.sha256_json(decode(contract_raw)) == risk.CANONICAL_CONTRACT_SEMANTIC_SHA256,
         "RISK_CONTRACT_CHANGED")
    calendar_raw = read_ref(root, manifest["inputs"]["calendar"])
    calendar = risk.validate_calendar(table(calendar_raw), digest(calendar_raw))
    metrics_raw = read_ref(root, manifest["inputs"]["metrics"])
    metrics = table(metrics_raw)
    need(set(("source_sha256", "decision_time_utc", "available_from", "axis")) <= set(metrics), "METRIC_CLOCK_COLUMNS")
    contract = decode(contract_raw)
    for key, wanted in risk._safety_payload(contract).items():
        need(key in manifest and canonical(manifest[key]) == canonical(wanted), "UPSTREAM_SAFETY_ENVELOPE")
    need(manifest.get("network_requests_executed") == 0, "UPSTREAM_SAFETY_ENVELOPE")
    as_of = pd.Timestamp(manifest["decision_date"])
    validated = risk.validate_metrics(metrics, contract, as_of, calendar)
    metrics = validated
    decisions = {date: group.decision_time_utc.iloc[0] for date, group in validated.groupby("decision_date")}
    sessions = {date: (int(group.nyse_session_ordinal.iloc[0]), str(group.calendar_source_sha256.iloc[0]))
                for date, group in validated.groupby("decision_date")}
    context, context_raw = None, b""
    if manifest["inputs"].get("context") is not None:
        context_raw = read_ref(root, manifest["inputs"]["context"])
        context = context_table(context_raw)
    validated_context = risk.validate_context(context, contract, as_of, decisions, sessions, calendar)
    if context is not None:
        context = validated_context
    expectations, expectations_sha = None, None
    if view["input_kind"] == "ACTUAL":
        for frame in (metrics, context):
            if frame is not None:
                kinds = frame.source_kind.str.upper()
                need(not kinds.str.contains("SYNTHETIC|FIXTURE|TEST", regex=True).any(), "FIXTURE_ACTUAL_MIX")
                need(not kinds.str.contains("CURRENT_VINTAGE|LATEST_SNAPSHOT", regex=True).any(),
                     "AS_KNOWN_SOURCE_REQUIRED")
        execution = trusted_now()
        need(abs((now-execution).total_seconds()) <= 60, "ACTUAL_CLOCK_NOT_CURRENT")
        need(execution.astimezone(NY).date().isoformat() == session, "LATE_SESSION_NOT_RETROACTIVE")
        times = session_times(session)
        need(execution >= cutoff and (slot != "INTRADAY" or execution < times["close"]), "ACTUAL_SLOT_NOT_CURRENT")
        now = execution
        expectations, expectations_sha = load_expectations(expectations_path, expected_expectations_sha, producer)
        for name, raw_input in (("metrics",metrics_raw),("calendar",calendar_raw),("context",context_raw)):
            need(expectations["inputs"].get(name) == (digest(raw_input) if raw_input else None), "EXPECTED_INPUT_PIN_MISMATCH")
    snapshot_raw = read_ref(root, manifest["outputs"]["macro_risk_snapshot"], 128*1024)
    snapshot = decode(snapshot_raw)
    history_raw = read_ref(root, manifest["outputs"]["market_state_history"])
    history = table(history_raw)
    needed = {"decision_date", "nyse_session_ordinal", "calendar_source_sha256", "risk_score", "effective_state",
              "entry_confirmation_count", "release_confirmation_count", "state_change_allowed"}
    need(needed <= set(history) and not history.empty and len(history) <= 2520, "HISTORY_UNAVAILABLE")
    need(history.decision_date.map(lambda s: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T00:00:00)?", s))).all(),
         "HISTORY_SESSION_DATE")
    history["decision_date"] = history.decision_date.str[:10]
    metric_dates = set(validated.decision_date.dt.date.astype(str))
    need(set(history.decision_date) == metric_dates, "HISTORY_INPUT_COVERAGE_MISMATCH")
    need(not history["decision_date"].duplicated().any(), "DUPLICATE_COMPLETED_SESSION")
    indexed = calendar.set_index(calendar.decision_date.dt.date.astype(str))
    for row in history.itertuples(index=False):
        need(row.decision_date in indexed.index and str(row.calendar_source_sha256) == digest(calendar_raw), "HISTORY_CALENDAR_MISMATCH")
        need(int(row.nyse_session_ordinal) == int(indexed.loc[row.decision_date, "nyse_session_ordinal"]), "HISTORY_SESSION_MISMATCH")
        need(row.effective_state in ("DATA_INSUFFICIENT", "NORMAL", "RISK_ALERT", "RISK_DEFENSE", "EXTREME_FEAR"), "HISTORY_STATE")
        need(0 <= int(row.entry_confirmation_count) <= 10000 and
             0 <= int(row.release_confirmation_count) <= 10000, "HISTORY_CONFIRMATION")
    history = history.sort_values("decision_date")
    ordinals = history.nyse_session_ordinal.astype(int).tolist()
    need(all(b == a+1 for a, b in zip(ordinals, ordinals[1:])), "HISTORY_SESSION_GAP")
    need({"observed_state", "portfolio_fragility"} <= set(history), "HISTORY_UNAVAILABLE")
    replay_input = history.copy()
    for column in ("state_change_allowed", "portfolio_fragility"):
        need(set(replay_input[column]) <= {"True", "False"}, "HISTORY_BOOLEAN")
        replay_input[column] = replay_input[column].eq("True")
    replay = risk.apply_state_hysteresis(replay_input, contract)
    for column in ("effective_state", "entry_confirmation_count", "release_confirmation_count"):
        need(history[column].astype(str).tolist() == replay[column].astype(str).tolist(), "HISTORY_REPLAY_MISMATCH")
    latest = history.iloc[-1]
    need(snapshot.get("schema_version") == "MacroRiskSnapshot-v1" and snapshot.get("report_only") is True
         and snapshot.get("decision_date") == latest.decision_date == manifest.get("decision_date"), "SNAPSHOT_HISTORY_MISMATCH")
    context_fields = contract["context_columns"].get("optional_numeric", []) + contract["context_columns"].get("optional_boolean", [])
    records = view.get("source_clocks")
    need(isinstance(records, list) and 0 < len(records) <= 5000 and
         all(isinstance(item, dict) for item in records), "CLOCK_MANIFEST")
    consumed = set(metrics.source_sha256)
    if context is not None:
        consumed.update(context.source_sha256)
    records = [item for item in records if item.get("source_sha256") in consumed]
    facts, issues = clock_check(records, metrics, cutoff, now, view["input_kind"], expectations)
    if context is not None:
        context_facts, context_issues = clock_check(records, context, cutoff, now, view["input_kind"], expectations, context_fields)
        facts = list({f["source_sha256"]:f for f in facts+context_facts}.values())
        issues = sorted(set(issues + context_issues))
    axes = snapshot.get("axes")
    need(isinstance(axes, list) and len(axes) == 10 and {a.get("axis") for a in axes} == set(contract["axes"]), "TEN_AXIS_IDENTITY")
    ready = {a["axis"] for a in axes if a.get("axis_ready") is True}
    latest_metrics = validated[validated.decision_date == as_of]
    percentile = contract["percentile"]
    window = validated[validated.decision_date >= as_of-pd.DateOffset(years=percentile["window_years"])]
    observations = window.groupby("component").size().clip(upper=percentile["maximum_sessions"])
    for axis in ready:
        present = set(latest_metrics.loc[latest_metrics.axis == axis, "component"])
        spec = contract["axes"][axis]
        need(len(present & set(spec["components"])) >= spec["minimum_ready_components"],
             "READY_AXIS_COMPONENTS_MISSING")
        historically_ready = {component for component in present & set(spec["components"])
                              if observations.get(component, 0) >= percentile["minimum_observations"]}
        need(len(historically_ready) >= spec["minimum_ready_components"], "READY_AXIS_HISTORY_INSUFFICIENT")
    # Consume the producer's pinned axis artifact, rather than recalculate risk
    # for a second report in the same session.
    axes_raw = read_ref(root, manifest["outputs"]["macro_risk_axes"])
    axes_frame = table(axes_raw)
    latest_axes = axes_frame[axes_frame.decision_date.str[:10] == latest.decision_date]
    need(len(latest_axes) == 10 and not latest_axes.axis.duplicated().any(), "AXIS_ARTIFACT_IDENTITY")
    for axis in axes:
        match = latest_axes[latest_axes.axis == axis["axis"]]
        need(len(match) == 1 and match.iloc[0].axis_ready in ("True", "False") and
             (match.iloc[0].axis_ready == "True") == axis["axis_ready"], "AXIS_ARTIFACT_READINESS")
        need(float(match.iloc[0].weight) == float(contract["axes"][axis["axis"]]["weight"]), "AXIS_WEIGHT_CHANGED")
        need(match.iloc[0].red_domain == contract["axes"][axis["axis"]]["red_domain"], "AXIS_DOMAIN_CHANGED")
        if axis["axis_ready"]:
            score = float(match.iloc[0].axis_score) if match.iloc[0].axis_score else math.nan
            need(math.isfinite(score) and 0 <= score <= 100, "READY_AXIS_SCORE_INVALID")
            value = axis.get("axis_score")
            need(type(value) in (int, float) and math.isfinite(value) and abs(score-value) < 1e-8,
                 "SNAPSHOT_AXIS_SCORE_MISMATCH")
        else:
            need(axis.get("axis_score") is None and match.iloc[0].axis_score == "", "UNREADY_AXIS_SCORE_NOT_NULL")
    # Verify the latest consumed summary with the existing engine's one-session
    # reducer. This does not rerun historical percentiles or advance history.
    checked_axes = latest_axes.copy()
    checked_axes["decision_date"] = pd.to_datetime(checked_axes.decision_date)
    for column in ("axis_ready", "red_axis"):
        need(set(checked_axes[column]) <= {"True", "False"}, "AXIS_BOOLEAN")
        checked_axes[column] = checked_axes[column].eq("True")
    for column in ("weight", "axis_score"):
        checked_axes[column] = pd.to_numeric(checked_axes[column], errors="coerce")
    red = checked_axes.axis_ready & checked_axes.axis_score.ge(contract["percentile"]["red_percentile"])
    need(red.tolist() == checked_axes.red_axis.tolist(), "AXIS_RED_SCORE_MISMATCH")
    checked = risk.build_daily_risk(checked_axes, validated_context, contract).iloc[-1]
    need(checked.observed_state == latest.observed_state, "OBSERVED_STATE_AXIS_MISMATCH")
    minimum = contract["readiness"]["minimum_ready_axes"]
    required = set(contract["readiness"]["required_axes"])
    ready_ok = len(ready) >= minimum and required <= ready
    need(snapshot.get("ready_axis_count") == len(ready) and snapshot.get("required_axes_ready") == (required <= ready), "READINESS_MISMATCH")
    need(snapshot.get("state_change_allowed") == ready_ok, "READINESS_MISMATCH")
    if ready_ok:
        value = snapshot.get("risk_score")
        need(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100
             and abs(float(latest.risk_score)-value) < 1e-8
             and abs(float(checked.risk_score)-value) < 1e-8, "SCORE_HISTORY_MISMATCH")
    else:
        need(snapshot.get("risk_score") is None, "INSUFFICIENT_SCORE_NOT_NULL")
    if not issues:
        expected_axes, expected_history = verified_derivation(metrics_raw, context_raw, calendar_raw, contract_raw,
            producer, digest(bounded(Path(__file__), 256*1024)), as_of.date().isoformat())
        need(digest(axes_raw) == digest(expected_axes) and digest(history_raw) == digest(expected_history),
             "FULL_DERIVED_HISTORY_MISMATCH")
    return dict(input_kind=view["input_kind"], manifest_sha256=digest(manifest_raw),
                source_view_sha256=digest(raw), snapshot=snapshot, history=history,
                facts=facts, issues=issues, ready=ready_ok, latest=latest,
                history_sha256=digest(history_raw), producer_sha256=producer, expectations=expectations,
                expectations_sha256=expectations_sha, metrics=validated, context=validated_context,
                axes_frame=axes_frame, context_fields=context_fields, execution_time_utc=now.isoformat(),
                source_clocks=records,
                expiry_min=min((stamp(c["expiry"]) for c in records), default=now) if not issues else None)


def load_previous(raw, expected_sha, expected_parent, recipient, input_kind):
    need(raw is not None, "HISTORY_UNAVAILABLE")
    need(len(raw) <= 65536 and digest(raw) == sha(expected_sha), "PREVIOUS_HISTORY_PIN_MISMATCH")
    value = decode(raw)
    need(value.get("schema") == "daily-crisis-report-history-v1" and value.get("recipient") == recipient
         and value.get("input_kind") == input_kind, "PREVIOUS_HISTORY_SCOPE")
    content = dict(value); actual = content.pop("content_sha256", None)
    need(actual == digest(canonical(content)), "PREVIOUS_HISTORY_HASH_MISMATCH")
    need(value.get("parent_sha256") == expected_parent, "PREVIOUS_HISTORY_PARENT_MISMATCH")
    if expected_parent is not None: sha(expected_parent)
    need(type(value.get("completed_session_count")) is int and 0 <= value["completed_session_count"] <= 10000,
         "PREVIOUS_HISTORY_COUNT")
    need(isinstance(value.get("slots"), list) and len(value["slots"]) <= 512
         and all(isinstance(s, str) and HASH.fullmatch(s) for s in value["slots"])
         and len(set(value["slots"])) == len(value["slots"]), "PREVIOUS_HISTORY_SLOTS")
    last = value.get("last_counted_completed_session")
    need((last is None and value["completed_session_count"] == 0) or
         (isinstance(last, str) and session_times(last) is not None and
          value["completed_session_count"] > 0), "PREVIOUS_HISTORY_COUNT")
    need(value["completed_session_count"] == 0 or bool(value["slots"]), "COMPLETED_HISTORY_SLOTS_REQUIRED")
    if last is not None:
        need(digest(canonical([recipient,last,"AFTER_CLOSE"])) in value["slots"], "COMPLETED_SLOT_KEY_REQUIRED")
    if value["slots"]:
        sha(value.get("source_prefix_sha256"))
        need(isinstance(value.get("source_prefix_date"), str), "SOURCE_HISTORY_PREFIX_REQUIRED")
        need(session_times(value["source_prefix_date"]) is not None and
             (last is None or value["source_prefix_date"] >= last), "SOURCE_PREFIX_DOES_NOT_COVER_COMPLETED_SESSION")
    return value


def report_cycle(*, source_view=None, expected_source_sha=None, source_root=None,
                 session, slot, recipient, now, previous_raw=None,
                 expected_previous_sha=None, expected_parent_sha=None, code_sha,
                 expectations_path=None, expected_expectations_sha=None):
    need(slot in SLOTS and isinstance(recipient, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", recipient), "REPORT_SCOPE")
    sha(code_sha)
    now = stamp(now)
    times = session_times(session)
    delivery_key = digest(canonical([recipient, session, slot]))
    result = dict(schema_version="daily-crisis-twice-report-v1", input_kind="UNKNOWN",
                  session=session, logical_slot=slot, recipient=recipient,
                  delivery_key=delivery_key, delivery_dry_run=True,
                  current_report_status="BLOCKED", data_health="DATA_BLOCKED",
                  report_kind="INTRADAY_PROVISIONAL" if slot == "INTRADAY" else "AFTER_CLOSE_EVALUATED",
                  risk_score=None, market_state=None, legacy_crisis_state=None, project_a4_regime=None,
                  enum_mapping_status="NOT_APPROVED", confirmation=None,
                  completed_session_increment=0, history_status="HISTORY_UNAVAILABLE",
                  source_facts=[], blockers=[], next_history=None,
                  delivery_candidate=False, quantitative_action_status="BLOCKED_BOOK_ER_DOWNSIDE_COST",
                  target_weights=None, company_relation_status="WAIT_VERIFIED_RELATIONS",
                  company_impacts=[], **SAFETY)
    if times is None:
        result.update(current_report_status="NO_TRADING_SESSION", blockers=["US_HOLIDAY_OR_WEEKEND"])
        return result
    cutoff = times[slot]
    result.update(decision_cutoff_utc=cutoff.isoformat(), session_close_utc=times["close"].isoformat())
    if now < cutoff or (slot == "INTRADAY" and now >= times["close"]):
        result["blockers"] = ["SLOT_NOT_DUE" if now < cutoff else "LATE_INTRADAY_NOT_RETROACTIVE"]
        return result
    try:
        need(source_view is not None, "REAL_INPUT_WAIT")
        source = load_source(source_view, expected_source_sha, source_root, cutoff, now,
                             session=session, slot=slot, expectations_path=expectations_path,
                             expected_expectations_sha=expected_expectations_sha)
        result.update(input_kind=source["input_kind"], source_facts=source["facts"],
                      source_manifest_sha256=source["manifest_sha256"],
                      source_history_sha256=source["history_sha256"],
                      producer_sha256=source["producer_sha256"],
                      execution_time_utc=source["execution_time_utc"],
                      expectations_sha256=source["expectations_sha256"],
                      risk_as_of_session=source["snapshot"]["decision_date"])
        result["analysis_artifact_key"] = digest(canonical(dict(source=source["source_view_sha256"],
            cutoff=cutoff.isoformat(), code_sha256=code_sha, expectations=source["expectations_sha256"],
            contract=risk.CANONICAL_CONTRACT_SEMANTIC_SHA256)))
        if source["issues"]:
            result["blockers"].extend(source["issues"])
            raise Blocked("SOURCE_PROOF_INCOMPLETE")
        prior = load_previous(previous_raw, expected_previous_sha, expected_parent_sha, recipient, source["input_kind"])
        if prior["slots"]:
            through = prior["source_prefix_date"]
            need(through <= source["snapshot"]["decision_date"] and
                 prefix_digest(source, through) == prior["source_prefix_sha256"], "SOURCE_HISTORY_PREFIX_CHANGED")
        result["history_status"] = "VERIFIED_RESTORED"
        if source["input_kind"] == "ACTUAL":
            need(now.astimezone(NY).date().isoformat() == session, "LATE_SESSION_NOT_RETROACTIVE")
        latest_date = source["snapshot"]["decision_date"]
        need(latest_date <= session, "FUTURE_SOURCE_SESSION")
        if slot == "AFTER_CLOSE":
            need(latest_date == session, "STALE_SUCCESS_NOT_CURRENT_REPORT")
        else:
            need(latest_date < session, "INTRADAY_DAILY_SNAPSHOT_NOT_COMPLETED")
            end = datetime.fromisoformat(session)-timedelta(days=1)
            schedule = mcal.get_calendar("NYSE").schedule(start_date=end-timedelta(days=30), end_date=end)
            previous_session = schedule.index[-1].date().isoformat()
            need(latest_date == previous_session, "STALE_INTRADAY_SOURCE_SESSION")
        last = prior.get("last_counted_completed_session")
        need(last is None or (isinstance(last, str) and last <= session), "HISTORY_TIME_REGRESSION")
        candidate = delivery_key not in prior["slots"]
        slots = (prior["slots"] + ([delivery_key] if candidate else []))[-512:]
        increment = int(candidate and slot == "AFTER_CLOSE" and source["ready"] and last != session)
        if increment and last is None:
            # Opaque prior keys cannot prove that earlier partial sessions were
            # completed. Only this session's provisional slot may precede genesis.
            intraday_key = digest(canonical([recipient, session, "INTRADAY"]))
            need(all(key == intraday_key for key in prior["slots"]),
                 "INITIAL_COMPLETION_REQUIRES_A0_RECOVERY")
        if increment and last is not None:
            start = datetime.fromisoformat(last)+timedelta(days=1)
            following = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=session)
            need(not following.empty and following.index[0].date().isoformat() == session,
                 "COMPLETED_SESSION_GAP")
        next_completed = session if increment else last
        if next_completed is not None:
            completed_key = digest(canonical([recipient,next_completed,"AFTER_CLOSE"]))
            if completed_key not in slots:
                slots = [completed_key]+slots[-511:]
        next_prefix = prefix_digest(source, latest_date)
        if source["input_kind"] == "ACTUAL":
            execution = trusted_now()
            need(execution.astimezone(NY).date().isoformat() == session and execution >= cutoff and
                 (slot != "INTRADAY" or execution < times["close"]), "ACTUAL_SLOT_NOT_CURRENT")
            need(execution < source["expiry_min"], "SOURCE_EXPIRED_DURING_VERIFICATION")
            result["execution_time_utc"] = execution.isoformat()
        history = dict(schema="daily-crisis-report-history-v1", recipient=recipient,
                       input_kind=source["input_kind"], parent_sha256=expected_previous_sha,
                       last_counted_completed_session=session if increment else last,
                       completed_session_count=prior["completed_session_count"]+increment,
                       slots=slots, source_history_sha256=source["history_sha256"],
                       source_manifest_sha256=source["manifest_sha256"],
                       source_prefix_date=latest_date, source_prefix_sha256=next_prefix)
        history["content_sha256"] = digest(canonical(history))
        result.update(next_history=history, delivery_candidate=candidate,
                      completed_session_increment=increment,
                      current_report_status=("READY_DRY_RUN" if source["ready"] else "PARTIAL_DRY_RUN")
                      if candidate else "ALREADY_PREPARED_SAME_SLOT",
                      data_health="DATA_READY" if source["ready"] else "DATA_PARTIAL")
        if not source["ready"]:
            result["blockers"].append("TEN_AXIS_READINESS_INSUFFICIENT")
        elif slot == "AFTER_CLOSE":
            result.update(risk_score=source["snapshot"]["risk_score"], market_state=source["latest"].effective_state,
                          confirmation=dict(entry_sessions=int(source["latest"].entry_confirmation_count),
                                            release_sessions=int(source["latest"].release_confirmation_count)))
        else:
            result.update(last_completed_risk_score=source["snapshot"]["risk_score"],
                          last_completed_market_state=source["latest"].effective_state)
    except (Blocked, risk.ContractError) as exc:
        result.update(next_history=None, delivery_candidate=False, completed_session_increment=0,
                      current_report_status="BLOCKED", risk_score=None, market_state=None)
        result["blockers"].append("CHAMELEON_INPUT_CONTRACT" if isinstance(exc, risk.ContractError) else str(exc))
        result["data_health"] = "DATA_PARTIAL" if result["source_facts"] else "DATA_BLOCKED"
    except (OSError, ValueError, TypeError, KeyError, AttributeError, csv.Error, RecursionError):
        result.update(next_history=None, delivery_candidate=False, completed_session_increment=0,
                      current_report_status="BLOCKED", risk_score=None, market_state=None)
        result["blockers"].append("INPUT_UNREADABLE_OR_INVALID")
    return result


def render_report(payload):
    lines = ["# US Macro Report — Dry Run", "", f"- Session: {payload['session']} / {payload['logical_slot']}",
             f"- Report: {payload['report_kind']} / {payload['current_report_status']}",
             f"- Data: {payload['data_health']} / {payload['input_kind']}",
             f"- Risk score: {payload['risk_score']}", f"- Market state: {payload['market_state']}",
             "- Notification / orders / book writes: OFF", "", "## Confirmed source facts"]
    lines += [f"- {item.get('source_id')}: {item['available_at']} ({item['unit']}, {item['seasonal_basis']})"
              for item in payload["source_facts"]]
    if payload["logical_slot"] == "INTRADAY" and "last_completed_risk_score" in payload:
        lines += ["", "## Verified prior completed session (provisional intraday report)",
                  f"- Prior session: {payload['risk_as_of_session']}",
                  f"- Prior-session risk score: {payload['last_completed_risk_score']}",
                  f"- Prior-session market state: {payload['last_completed_market_state']}"]
    lines += ["", "## Missing evidence"] + ["- "+item for item in payload["blockers"]]
    lines += ["", "## Action review", "- Verify thesis and independent risk evidence before considering a change.",
              "- Preserve healthy winners; assess costs, reentry risk and superior alternatives.",
              "- Quantitative action blocked until book, net ER, downside and costs are verified."]
    return "\n".join(lines)+"\n"
