#!/usr/bin/env python3
"""Offline supplemental survey diagnostics. No source admission or trading power.

Actual input is refused until the existing Source owner binds authorized archives
and receipt lineage. Synthetic fixtures exercise the arithmetic without asserting
rights, PIT, current market state, economic results or portfolio permission.
"""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macro_history_sources import digest, encoded, exclusive, require, stamp
from tools import free_market_context as free_context

CONTRACT = ROOT / "docs/macro_survey_research_contract.json"
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_JSON_DEPTH = 24
MAX_JSON_NODES = 300_000
MODE = "SYNTHETIC_FIXTURE"
EXPORT_REVIEW_MODE = "LOCAL_EXPORT_REVIEW_ONLY"
SAFETY = dict(source_authenticated=False, supplier_rights_verified=False,
              historical_pit_verified=False, current_market_regime=None,
              eligible_for_selector=False, economic_authority=False,
              orders_generated=False, target_books_mutated=False,
              automatic_collection_enabled=False, control_changed=False)


def _now():
    return datetime.now(timezone.utc)


def _reject_constant(value):
    raise ValueError("nonstandard_json_number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def read_json(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_INPUT_BYTES, "input_size")
    try:
        payload = json.loads(raw, parse_constant=_reject_constant,
                             object_pairs_hook=_unique_object)
    except RecursionError:
        raise ValueError("json_complexity") from None
    stack, count = [(payload, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        require(depth <= MAX_JSON_DEPTH and count <= MAX_JSON_NODES, "json_complexity")
        if type(value) in (dict, list):
            children = value.values() if type(value) is dict else value
            stack.extend((child, depth + 1) for child in children)
    return payload


def _contract():
    raw = CONTRACT.read_bytes()
    payload = read_json(raw)
    require(payload["schema"] == "r1000-macro-survey-research-v1", "contract_schema")
    require(payload["default_collection_enabled"] is False and
            payload["economic_authority"] is False, "contract_authority")
    return raw, payload


def _period(value, frequency):
    require(isinstance(value, str), "reference_period")
    if frequency == "monthly":
        require(re.fullmatch(r"\d{4}-\d{2}", value) is not None, "reference_period")
        year, month = map(int, value.split("-"))
        return date(year, month, calendar.monthrange(year, month)[1])
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None, "reference_period")
    return date.fromisoformat(value)


def _consecutive(old, new, frequency):
    if frequency == "monthly":
        return new.year * 12 + new.month == old.year * 12 + old.month + 1
    return (new - old).days == 7


def _aaii_csv(period, values):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["date", "bullish", "neutral", "bearish"])
    writer.writerow([period, values["bullish"], values["neutral"], values["bearish"]])
    return buffer.getvalue().encode("utf-8")


def inspect_aaii_export(raw, *, expected_sha256, collected_at, decision_at, unit):
    """Reuse the existing authorized-file parser for an UNADMITTED local review.

    A matching supplied digest proves byte consistency only. It authenticates
    neither publisher, license nor historic public availability. This distinct
    review schema cannot be a current macro snapshot or investment approval.
    """
    require(type(raw) is bytes and 0 < len(raw) <= MAX_INPUT_BYTES, "input_size")
    require(type(expected_sha256) is str and
            re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
            "expected_input_hash_required")
    require(digest(raw) == expected_sha256, "input_hash_mismatch")
    require(type(collected_at) is str and type(decision_at) is str, "review_clock_type")
    decision, collected = stamp(decision_at), stamp(collected_at)
    require(collected <= decision <= _now(), "review_clock_order")
    try:
        rows = free_context.aaii_observations(raw, collected_at=collected_at,
                                             cutoff=decision_at, unit=unit)
    except csv.Error:
        raise ValueError("aaii_csv_parse_error") from None
    require(bool(rows) and len(rows) <= MAX_RECORDS, "record_scope")
    contract_raw, contract = _contract()
    policy = next(s for s in contract["sources"] if s["id"] == "AAII")
    contexts = free_context.trailing_context(rows, cutoff=decision_at,
        max_age_days=policy["max_publication_age_days"], lookback=52, minimum=20)
    require(len(contexts) == 1, "aaii_review_scope")
    context = contexts[0]
    value = context["current_value"]
    return dict(schema="r1000-aaii-local-export-review-v1",
        status="BLOCKED_STALE" if context["status"] == "STALE" else "UNADMITTED_RESEARCH_CONTEXT",
        evidence_mode=EXPORT_REVIEW_MODE, decision_at=decision.isoformat(),
        reference_period=context["observation_date"], published_at=None,
        available_at=collected.isoformat(), collected_at=collected.isoformat(),
        availability_evidence="COLLECTION_TIME_ONLY_NO_HISTORICAL_PIT",
        input_sha256=digest(raw), input_bytes_verified=True,
        original_publisher_bytes_verified=False,
        parser="tools.free_market_context.aaii_observations",
        parser_sha256=digest(Path(free_context.__file__).read_bytes()),
        code_sha256=digest(Path(__file__).read_bytes()), contract_sha256=digest(contract_raw),
        bull_bear_spread_pp=value * 100 if value is not None else None,
        independent_reference_periods=len({r["observation_date"] for r in rows}),
        reasons=["LOCAL_EXPORT_REVIEW_NOT_SOURCE_ADMISSION", "ORIGINAL_PUBLICATION_CLOCK_UNKNOWN"],
        **SAFETY)


def build_context(raw, decision_at, evidence_mode="ACTUAL"):
    """Always refuse ACTUAL; compute only explicitly marked synthetic diagnostics.

    A caller's 'VERIFIED' or supplier_rights_verified boolean is never an
    authentication path. Future Source integration requires its own reviewed
    adapter to the existing archive/receipt/rights authority, not a mode toggle.
    """
    decision = stamp(decision_at)
    require(decision <= _now(), "future_decision")
    contract_raw, contract = _contract()
    result = dict(schema="r1000-macro-survey-context-v1",
                  status="BLOCKED_SOURCE_ADMISSION",
                  decision_at=decision.isoformat(), evidence_mode=evidence_mode,
                  contract_sha256=digest(contract_raw),
                  code_sha256=digest(Path(__file__).read_bytes()),
                  input_sha256=None, sources={}, missing_sources=[],
                  reasons=["AUTHORIZED_SOURCE_ARCHIVE_AND_RECEIPT_BINDING_REQUIRED"],
                  **SAFETY)
    if evidence_mode != MODE:
        return result
    payload = read_json(raw)
    require(isinstance(payload, dict) and payload.get("evidence_mode") == MODE,
            "fixture_label_required")
    records = payload.get("records")
    require(isinstance(records, list) and len(records) <= MAX_RECORDS, "record_scope")
    specs = {item["id"]: item for item in contract["sources"]}
    groups, identities, release_clocks = {}, set(), {}
    required = {"source", "component", "reference_period", "release_id", "revision",
                "published_at", "available_at", "collected_at", "value", "unit",
                "raw_sha256"}
    for row in records:
        require(isinstance(row, dict) and required <= set(row), "record_schema")
        source, component = row["source"], row["component"]
        require(isinstance(source, str) and source in specs, "unknown_source")
        spec = specs[source]
        require(isinstance(component, str) and component in spec["components"],
                "unknown_component")
        require(row["unit"] == spec["unit"], "unit_mismatch")
        value = row["value"]
        require(type(value) in (int, float) and math.isfinite(value) and
                0 <= value <= 100, "invalid_numeric_value")
        require(type(row["revision"]) is int and row["revision"] >= 0, "revision")
        require(isinstance(row["release_id"], str) and
                re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", row["release_id"]) is not None,
                "release_identity")
        require(isinstance(row["raw_sha256"], str) and
                re.fullmatch(r"[0-9a-f]{64}", row["raw_sha256"]) is not None,
                "raw_identity")
        period_end = _period(row["reference_period"], spec["frequency"])
        require(all(isinstance(row[field], str) for field in
                    ("published_at", "available_at", "collected_at")), "clock_type")
        published = stamp(row["published_at"])
        available = stamp(row["available_at"])
        collected = stamp(row["collected_at"])
        require(period_end <= published.date(), "observation_after_publication")
        require(published <= available <= collected <= _now(), "clock_order")
        key = (source, row["reference_period"], row["release_id"], row["revision"])
        identity = (*key, component)
        require(identity not in identities, "duplicate_component")
        identities.add(identity)
        clock_identity = (published, available, collected, row["raw_sha256"])
        require(key not in release_clocks or release_clocks[key] == clock_identity,
                "mixed_release_provenance")
        release_clocks[key] = clock_identity
        groups.setdefault(source, {}).setdefault(row["reference_period"], {}).setdefault(
            (row["release_id"], row["revision"]), []).append(row)
    for source, spec in specs.items():
        periods, malformed = {}, False
        for period, revisions in groups.get(source, {}).items():
            eligible = []
            for rows in revisions.values():
                if stamp(rows[0]["available_at"]) <= decision and stamp(rows[0]["collected_at"]) <= decision:
                    eligible.append(rows)
            if not eligible:
                continue
            # A tie of distinct source releases cannot be silently resolved by input order.
            top_time = max(stamp(rows[0]["available_at"]) for rows in eligible)
            top = [rows for rows in eligible if stamp(rows[0]["available_at"]) == top_time]
            if len(top) != 1:
                malformed = True
                continue
            selected = top[0]
            if {r["component"] for r in selected} != set(spec["components"]):
                malformed = True
                continue
            values = {r["component"]: float(r["value"]) for r in selected}
            if source == "AAII":
                try:
                    # Preserve the existing percent/fraction, total and provenance guards.
                    parsed = free_context.aaii_observations(
                        _aaii_csv(period, values), collected_at=selected[0]["collected_at"],
                        cutoff=decision_at, unit="percent")
                except free_context.ContextError:
                    malformed = True
                    continue
                require(len(parsed) == 1, "aaii_release_scope")
                spread_pp = parsed[0]["value"] * 100
            else:
                spread_pp = None
            periods[period] = dict(rows=selected, values=values, spread_pp=spread_pp)
        if malformed:
            result["sources"][source] = dict(status="BLOCKED", reason="INCOMPLETE_OR_CONFLICTING_RELEASE", values=None)
            continue
        if not periods:
            result["missing_sources"].append(source)
            result["sources"][source] = dict(status="BLOCKED", reason="NO_AVAILABLE_RELEASE", values=None)
            continue
        ordered = sorted(periods)
        latest = periods[ordered[-1]]
        row = latest["rows"][0]
        # Reference age and release age both matter; a republished old survey is not current.
        fresh = (decision.date() - _period(ordered[-1], spec["frequency"])).days <= spec["max_publication_age_days"] and decision - stamp(row["published_at"]) <= timedelta(days=spec["max_publication_age_days"])
        if not fresh:
            result["sources"][source] = dict(status="STALE", reason="SURVEY_REFERENCE_OR_RELEASE_TOO_OLD", values=None)
            continue
        deltas = None
        if len(ordered) >= 2 and _consecutive(_period(ordered[-2], spec["frequency"]),
                                             _period(ordered[-1], spec["frequency"]), spec["frequency"]):
            deltas = {key: latest["values"][key] - periods[ordered[-2]]["values"][key]
                      for key in spec["components"]}
        spread = latest["spread_pp"]
        result["sources"][source] = dict(status="SYNTHETIC_DIAGNOSTIC_ONLY",
            reference_period=ordered[-1], release_id=row["release_id"],
            revision=row["revision"], values=latest["values"], changes_pp=deltas,
            bull_bear_spread_pp=spread, independent_reference_periods=len(periods),
            published_at=row["published_at"], available_at=row["available_at"],
            collected_at=row["collected_at"], claimed_raw_sha256=row["raw_sha256"],
            raw_bytes_verified=False)
    valid = sum(v["status"] == "SYNTHETIC_DIAGNOSTIC_ONLY" for v in result["sources"].values())
    result.update(input_sha256=digest(raw),
                  status="SYNTHETIC_DIAGNOSTIC_ONLY" if valid == len(specs) else
                         "PARTIAL_SYNTHETIC_DIAGNOSTIC" if valid else "BLOCKED_INPUT",
                  reasons=["SYNTHETIC_ONLY_NO_SOURCE_PIT_ECONOMIC_ADMISSION"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input")
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--evidence-mode", choices=["ACTUAL", MODE, EXPORT_REVIEW_MODE], default="ACTUAL")
    parser.add_argument("--expected-input-sha256")
    parser.add_argument("--collected-at")
    parser.add_argument("--unit", choices=["percent", "fraction"])
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    # Actual mode stops before reading or archiving potentially unauthorized data.
    try:
        raw = b""
        if args.evidence_mode in (MODE, EXPORT_REVIEW_MODE):
            require(args.input is not None, "input_required")
            path = Path(args.input)
            require(path.stat().st_size <= MAX_INPUT_BYTES, "input_size")
            raw = path.read_bytes()
        if args.evidence_mode == EXPORT_REVIEW_MODE:
            result = inspect_aaii_export(raw, expected_sha256=args.expected_input_sha256,
                collected_at=args.collected_at, decision_at=args.decision_at, unit=args.unit)
        else:
            result = build_context(raw, args.decision_at, args.evidence_mode)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        result = dict(schema="r1000-macro-survey-context-v1", status="BLOCKED_INPUT",
                      reasons=["SURVEY_INPUT_REJECTED"], sources={}, **SAFETY)
    exclusive(args.report, encoded(result))
    print(json.dumps(dict(status=result["status"], economic_authority=False), allow_nan=False))
    return 0 if result["status"] == "SYNTHETIC_DIAGNOSTIC_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
