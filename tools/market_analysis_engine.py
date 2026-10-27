"""Unified US market research: native ten-axis risk + free context, offline.

Only this request's pinned inputs are consumed. No implicit latest cache, network,
portfolio effects, or historical PIT promotion. Current vintage is descriptive.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from datetime import timedelta

import pandas as pd

from tools import free_market_context as free
from tools import chameleon_market_context_v2 as context
from tools import build_run287_chameleon_macro_risk as risk
from tools import daily_crisis_report_clock as clock

SCHEMA = "market-analysis-report-v1"
REQUEST_SCHEMA = "market-analysis-request-v1"
CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs/market_analysis_contract_v1.json"
SAFETY = {**context.SAFETY, "source_admission_allowed": False,
          "portfolio_overlay_allowed": False, "policy_handoff_implemented": False,
          "notification_enabled": False, "ledger_mutation_allowed": False,
          "order_generation_allowed": False, "target_book_write_allowed": False}
MAX_TOTAL_BYTES = 32 * 1024**2
MAX_FILE_BYTES = 8 * 1024**2
MAX_INPUTS = 40


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def need(condition, code):
    free.require(condition, code)


def safe_path(name):
    need(type(name) is str and 0 < len(name) <= 200 and "\\" not in name,
         "INPUT_PATH")
    p = PurePosixPath(name)
    need(not p.is_absolute() and all(x not in {"", ".", ".."} for x in name.split("/"))
         and all(re.fullmatch(r"[A-Za-z0-9_.-]+", x) for x in p.parts)
         and all(x.split(".")[0].upper() not in
                 {"CON", "PRN", "AUX", "NUL", *("COM"+str(n) for n in range(1,10)),
                  *("LPT"+str(n) for n in range(1,10))} for x in p.parts), "INPUT_PATH")
    return p


def bounded(path, limit):
    # Reject special files before opening: a FIFO may otherwise block forever.
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_size <= limit,
         "INPUT_TYPE_OR_SIZE")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "INPUT_TYPE_OR_SIZE")
        raw = handle.read(limit+1)
        after = os.fstat(handle.fileno())
    current = path.lstat()
    key = lambda s: (s.st_ino, s.st_size, s.st_mtime_ns)
    need(len(raw) <= limit and len(raw) == before.st_size and key(info) == key(before) == key(after) == key(current),
         "INPUT_CHANGED")
    return raw


def current_session(cutoff):
    # Reuse the actual XNYS close calendar, including DST and early closes.
    now = clock.stamp(cutoff)
    schedule = clock.mcal.get_calendar("NYSE").schedule(
        start_date=(now.date()-timedelta(days=14)).isoformat(), end_date=now.date().isoformat())
    eligible = schedule[schedule["market_close"] + pd.Timedelta(minutes=15) <= pd.Timestamp(now)]
    need(not eligible.empty, "COMPLETED_SESSION_REQUIRED")
    return eligible.index[-1].date().isoformat()


def verify_request(raw, expected_sha, cutoff, session):
    need(type(expected_sha) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha)
         and sha(raw) == expected_sha, "REQUEST_HASH_REQUIRED")
    need(len(raw) <= 256*1024, "REQUEST_SIZE")
    request = free.strict_json(raw)
    need(type(request) is dict and request.get("schema") == REQUEST_SCHEMA
         and request.get("market") == "US", "REQUEST_SCHEMA_OR_MARKET")
    now = clock.stamp(cutoff)
    available, expires = clock.stamp(request.get("available_at")), clock.stamp(request.get("expires_at"))
    need(available <= now < expires and available < expires
         and expires-available <= timedelta(days=4), "REQUEST_CLOCK_OR_EXPIRY")
    need(request.get("session") == session == current_session(cutoff), "REQUEST_SESSION_NOT_CURRENT")
    entries = request.get("inputs")
    need(type(entries) is list and len(entries) <= MAX_INPUTS, "INPUT_COUNT")
    names, roles = set(), set()
    for spec in entries:
        need(type(spec) is dict, "INPUT_SPEC")
        kind = spec.get("kind")
        need(kind in {"macro", "cot_tff", "price_context", "sce_export",
                      "risk_metrics", "risk_calendar", "risk_context"}, "INPUT_KIND")
        role = (kind, spec.get("source_id") if kind == "macro" else None)
        need(role not in roles, "DUPLICATE_INPUT_ROLE"); roles.add(role)
        path = spec.get("path"); safe_path(path)
        need(path not in names, "DUPLICATE_INPUT_PATH"); names.add(path)
        need(type(spec.get("sha256")) is str and re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]), "INPUT_HASH_REQUIRED")
        need(spec.get("status") in {"COLLECTED", "UNCHANGED"}, "SOURCE_NOT_CONSUMABLE")
        collected = clock.stamp(spec.get("collected_at"))
        need(collected <= available, "SOURCE_AFTER_REQUEST")
    return request


def sce_rows(raw, collected_at, cutoff):
    """Explicit standardized export. Does not claim native workbook conversion.

    Values are means of subjective probabilities, not AAII bullish fractions.
    Native original/conversion verification is a separate Source dependency.
    """
    records = free.csv_records(raw)
    need(bool(records) and len(records) <= 1000, "SCE_ROW_COUNT")
    need(set(records[0]) == {"month", "mean_probability_stock_prices_higher_12m_percent"}, "SCE_COLUMNS")
    meta = free.provenance(raw, provider="NYFED_SCE", dataset="STANDARDIZED_EXPORT_NOT_NATIVE_WORKBOOK",
                           collected_at=collected_at, cutoff=cutoff)
    result, seen = [], set()
    for r in records:
        month = r["month"]
        need(type(month) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}", month), "SCE_MONTH")
        day = free.iso_date(month+"-01").isoformat()
        need(month not in seen, "SCE_DUPLICATE_MONTH"); seen.add(month)
        text = r["mean_probability_stock_prices_higher_12m_percent"]
        value = None if text in {"", ".", "NA", "N/A"} else free.number(text)
        need(value is None or 0 <= value <= 100, "SCE_PROBABILITY_RANGE")
        result.append(free.record(meta, "US_HOUSEHOLD_HEADS", day,
            "mean_probability_stock_prices_higher_12m", None if value is None else value/100,
            "fraction", original_workbook_verified=False, conversion_verified=False))
    return result


def native_risk(blobs, session, cutoff):
    """Compute with the incumbent contract; no new risk model or thresholds."""
    if "risk_metrics" not in blobs or "risk_calendar" not in blobs:
        return {"status": "DATA_BLOCKED", "blockers": ["NATIVE_RISK_METRICS_AND_CALENDAR_REQUIRED"],
                "state": None, "risk_score": None, "axes": [], "ready_axis_count": 0,
                "required_axes_ready": False, "fear_recovery_stage": None}
    cfg = risk.load_contract()
    calendar_raw = blobs["risk_calendar"]
    calendar = risk.validate_calendar(clock.table(calendar_raw), sha(calendar_raw))
    metrics = risk.validate_metrics(clock.table(blobs["risk_metrics"]), cfg, pd.Timestamp(session), calendar)
    need(not metrics.empty and metrics["decision_date"].max().date().isoformat() == session,
         "NATIVE_RISK_SESSION_MISMATCH")
    need(metrics["decision_time_utc"].max() <= pd.Timestamp(clock.stamp(cutoff)), "NATIVE_RISK_FUTURE_DECISION")
    decisions = {d: g["decision_time_utc"].iloc[0] for d,g in metrics.groupby("decision_date")}
    sessions = {d: (int(g["nyse_session_ordinal"].iloc[0]), str(g["calendar_source_sha256"].iloc[0]))
                for d,g in metrics.groupby("decision_date")}
    raw_context = clock.table(blobs["risk_context"]) if "risk_context" in blobs else None
    ctx = risk.validate_context(raw_context, cfg, pd.Timestamp(session), decisions, sessions, calendar)
    components = risk.compute_component_percentiles(metrics, cfg)
    axes = risk.aggregate_axes(components, cfg)
    daily = risk.build_daily_risk(axes, ctx, cfg)
    sentiment = risk.build_sentiment_history(daily, components, ctx, cfg)
    latest = daily.iloc[-1]
    ready = bool(latest["state_change_allowed"])
    latest_axes = axes[axes["decision_date"] == pd.Timestamp(session)].to_dict(orient="records")
    # A previously effective state is never advertised as a fresh current state
    # while the incumbent readiness gate is closed.
    return risk.json_safe({"status": "READY_RESEARCH_ONLY" if ready else "DATA_BLOCKED",
        "blockers": [] if ready else ["INCUMBENT_TEN_AXIS_READINESS_NOT_MET"],
        "state": latest["effective_state"] if ready else None,
        "observed_state": latest["observed_state"] if ready else None,
        "risk_score": latest["risk_score"] if ready else None,
        "ready_axis_count": int(latest["ready_axis_count"]),
        "required_axes_ready": bool(latest["required_axes_ready"]), "axes": latest_axes,
        "fear_recovery_stage": sentiment.iloc[-1]["fear_recovery_stage"] if ready else None,
        "declared_input_truth_class": risk._worst_truth(list(metrics["truth_class"]), cfg),
        "contract_sha256": sha(risk.DEFAULT_CONTRACT.read_bytes()),
        "calibration_or_economic_approval": False})


def analyze(raw_request, supplied, *, expected_sha, cutoff, session):
    req = verify_request(raw_request, expected_sha, cutoff, session)
    need(type(supplied) is dict and set(supplied) == {s["path"] for s in req["inputs"]}, "INPUT_SET")
    macro, public, prices, surveys, native, receipts = [], [], [], [], {}, []
    need(all(type(x) is bytes for x in supplied.values()), "INPUT_BYTES_TYPE")
    need(sum(len(x) for x in supplied.values()) <= MAX_TOTAL_BYTES, "TOTAL_INPUT_BUDGET")
    for spec in req["inputs"]:
        raw = supplied[spec["path"]]
        need(type(raw) is bytes and 0 < len(raw) <= MAX_FILE_BYTES and sha(raw) == spec["sha256"], "INPUT_BYTES_HASH")
        kind, collected = spec["kind"], spec["collected_at"]
        receipts.append({k: spec[k] for k in ("kind", "path", "sha256", "status", "collected_at")})
        if kind == "macro":
            macro.extend(context.macro_source_rows(raw, source_id=spec.get("source_id"), collected_at=collected, cutoff=cutoff))
        elif kind == "cot_tff":
            public.extend(free.cot_observations(raw, report_kind="TFF_FUTURES", collected_at=collected, cutoff=cutoff))
        elif kind == "price_context":
            prices = free.strict_json(raw)
            need(type(prices) is list, "PRICE_CONTEXT_TYPE")
            for row in prices:
                need(type(row) is dict, "PRICE_CONTEXT_ROW_TYPE")
                need(clock.stamp(row.get("collected_at")) <= clock.stamp(collected), "PRICE_AFTER_SOURCE")
        elif kind == "sce_export":
            surveys = sce_rows(raw, collected, cutoff)
        else:
            native[kind] = raw
    composed = context.build_context(macro_rows=macro, public_rows=public, price_rows=prices,
        calendar_result=None, security_map=None, security_map_available_at=None,
        cutoff=cutoff, expected_session=session)
    survey_panel = free.trailing_context(surveys, cutoff=cutoff, max_age_days=75, lookback=120, minimum=24)
    model = native_risk(native, session, cutoff)
    reassessment = reassessment_snapshot(composed, survey_panel, cutoff=cutoff, expires_at=req["expires_at"])
    result = {"schema": SCHEMA, "status": model["status"], "market": "US", "session": session,
        "cutoff": cutoff, "request_sha256": expected_sha,
        "market_assessment": model, "existing_market_context": composed,
        "household_expectations": survey_panel,
        "candidate_reassessment_snapshot": reassessment,
        "source_receipts": receipts, "network_requests_executed": 0,
        "input_producer_authenticated": False,
        "source_and_pit_admission": False,
        "missing_optional_sources": (["NYFED_SCE_NATIVE_WORKBOOK_AND_CONVERSION"] if
            not survey_panel else ["SCE_EXPORT_ORIGINAL_AND_CONVERSION_UNVERIFIED"]) +
            (["CFTC_TFF"] if not public else []),
        "consumer_handoff": {"A4": "MARKET_RESEARCH_CONTEXT", "A2_A3": "THESIS_CONTEXT_ONLY",
            "A5": "RESEARCH_CONTEXT_ONLY_NO_PORTFOLIO_EFFECT", "A8": "FORWARD_OBSERVATION_ONLY"},
        "known_overlap": composed["known_overlap"] + [
            "Survey beliefs, futures positions, financial conditions and prices are different measurements",
            "SCE 12-month mean probability cannot be spliced into AAII bullish share",
            "TFF net position is not a one-way market bet; retain market code and participant class"],
        **SAFETY}
    result["content_sha256"] = context.digest(result)
    return result


def blocked(code, *, cutoff, session):
    result = {"schema": SCHEMA, "status": "DATA_BLOCKED", "market": "US", "session": session,
              "cutoff": cutoff, "blockers": [code], "market_assessment": {
                  "state": None, "risk_score": None}, "network_requests_executed": 0, **SAFETY}
    result["content_sha256"] = context.digest(result)
    return result


def reassessment_snapshot(composed, survey_panel, *, cutoff, expires_at):
    # Use the existing typed candidate-review consumer without Registry writes.
    from tools import candidate_reassessment_bridge as bridge
    rows = bridge.macro_rows_from_context(composed, observed_at=cutoff)
    for r in [*composed["public"], *survey_panel]:
        rows.append(dict(family="POSITIONING" if r["provider"] == "CFTC" else "SENTIMENT",
            provider=r["provider"], entity_kind="MARKET", entity_id=r["entity_id"],
            metric=r["metric"], fiscal_period=None, observation_period=r["observation_date"],
            identity={"unit":r["unit"], "dataset":r["dataset"]}, values={"value":r["current_value"]},
            status=r["status"], available_at=r["available_at"], collected_at=r["collected_at"],
            revision_id="market-context-observation", source_sha256=r["source_sha256"], causal_event_id=None))
    snapshot = bridge.snapshot(rows, scope_id="US_MARKET_CONTEXT", cutoff=cutoff, expires_at=expires_at)
    # The native observation snapshot only asserts source_authenticated=false.
    # This consumer also records the closed review-plan authority explicitly.
    body = {k:v for k,v in snapshot.items() if k != "content_sha256"}
    return bridge.seal({**body, **bridge.CLOSED})


def implementation_identity():
    paths = [Path(__file__), Path(context.__file__), Path(free.__file__), Path(risk.__file__),
             Path(clock.__file__), risk.DEFAULT_CONTRACT, CONTRACT_PATH]
    from tools import build_run287_chameleon_macro_inputs as normalizer
    from tools import candidate_reassessment_bridge as bridge
    paths.extend([Path(normalizer.__file__), Path(bridge.__file__)])
    return {p.name: sha(bounded(p, MAX_FILE_BYTES)) for p in paths}


def load_report(request_path, source_root, expected_sha, *, cutoff, session=None):
    """A pinned request and each original are read once, bounded and in-root.

    Failure replaces this invocation's assessment, with no last-good fallback.
    """
    try:
        session = session or current_session(cutoff)
        need(request_path is not None and source_root is not None, "REQUEST_NOT_CONNECTED")
        root = Path(source_root).resolve(strict=True)
        raw = bounded(Path(request_path), 256*1024)
        req = verify_request(raw, expected_sha, cutoff, session)
        supplied = {}
        remaining = MAX_TOTAL_BYTES
        identity = implementation_identity()
        for spec in req["inputs"]:
            relative = safe_path(spec["path"])
            path = root.joinpath(*relative.parts)
            need(path.resolve(strict=True).is_relative_to(root), "INPUT_OUTSIDE_ROOT")
            for parent in [path, *path.parents]:
                if parent == root: break
                need(not parent.is_symlink(), "INPUT_SYMLINK")
            supplied[spec["path"]] = bounded(path, min(MAX_FILE_BYTES, remaining))
            remaining -= len(supplied[spec["path"]])
        result = analyze(raw, supplied, expected_sha=expected_sha, cutoff=cutoff, session=session)
        need(identity == implementation_identity(), "IMPLEMENTATION_CHANGED")
        result.pop("content_sha256")
        result["implementation"] = identity
        result["content_sha256"] = context.digest(result)
        return result
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RecursionError, csv.Error):
        # Never expose untrusted filenames, original payloads or upstream errors.
        return blocked("MARKET_INPUT_UNAVAILABLE_INVALID_OR_EXPIRED", cutoff=cutoff, session=session)


def render_report(value):
    model = value["market_assessment"]
    lines = ["# Unified Market Analysis", "", f"Status: {value['status']}",
             f"US session: {value['session']}", f"Decision cutoff: {value['cutoff']}", "",
             f"Market risk state: {model.get('state')}", f"Risk score: {model.get('risk_score')}",
             f"Ready risk axes: {model.get('ready_axis_count', 0)}/10", "",
             "Research context only; Source/PIT, portfolio and trading authority remain closed.", "",
             "| Risk axis | Ready | Score |", "| --- | --- | --- |"]
    for a in model.get("axes", []):
        lines.append(f"| {a.get('axis')} | {a.get('axis_ready')} | {a.get('axis_score')} |")
    ctx = value.get("existing_market_context", {})
    lines += ["", "| Source measurement | Observation | Value | Status |", "| --- | --- | --- | --- |"]
    for key, record in ctx.get("macro", {}).items():
        lines.append(f"| {key} | {record['observation_date']} | {record['value']} | {record['status']} |")
    for r in [*ctx.get("public", []), *value.get("household_expectations", [])]:
        lines.append(f"| {r['provider']} / {r['entity_id']} / {r['metric']} | {r['observation_date']} | {r['current_value']} | {r['status']} |")
    lines += ["", "Missing optional: " + ", ".join(value.get("missing_optional_sources", [])),
              "Blockers: " + ", ".join(value.get("blockers", model.get("blockers", []))), ""]
    return "\n".join(lines)
