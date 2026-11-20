#!/usr/bin/env python3
"""Mission v3 numeric precheck. No orders, writes, network or certification.

Input NAV must already be net of the declared costs. This module does NOT
reconstruct fills/costs or authenticate the supplied session grid/provenance.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from decimal import (Context, Decimal, DecimalException, DivisionByZero,
                     InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext)
from types import MappingProxyType
from typing import Any

SCHEMA = "mission-v3-metric-precheck-v1"
REFERENCE = MappingProxyType({
    "contract_id": "mission-v3-us-reference-research-v1",
    "state": "RESEARCH_DRAFT",
    "start": "2018-09-17",
    "end": "2026-09-16",
    "initial_nav": "100000",
    "currency": "USD",
    "main_min_cagr": "0.35",
    "main_max_mdd_loss": "0.20",
    "concentrated_min_cagr": "0.50",
    "concentrated_max_mdd_loss": "0.25",
})
META_KEYS = frozenset({
    "sleeve", "run_id", "source_commit", "kernel_sha256",
    "data_release_sha256", "execution_policy_sha256", "cost_policy_sha256",
    "portfolio_policy_sha256", "currency", "sampling", "nav_basis",
})
SHARED_KEYS = META_KEYS - {"sleeve", "portfolio_policy_sha256"}
UNVERIFIED = (
    "AUTHORITATIVE_CALENDAR_AND_DAILY_COVERAGE",
    "RAW_SOURCE_AND_DATA_RELEASE_BINDING",
    "HISTORICAL_UNIVERSE_AND_FINANCIAL_PIT",
    "FILL_COST_CORPORATE_ACTION_AND_CASH_RECONSTRUCTION",
    "ACTUAL_MODULE_EXECUTION_AND_REPLAY_FORWARD_PARITY",
    "EXPOSED_WINDOWS_WALK_FORWARD_AND_TRIAL_HISTORY",
    "INDEPENDENT_REVIEW_AND_PROSPECTIVE_EVIDENCE",
)
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OBSERVATIONS = 10000
NUMBER_TEXT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


class InputError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise InputError(reason)


def exact_keys(value: Any, keys: set[str], label: str) -> None:
    require(type(value) is dict and set(value) == keys, label + ":KEYS")


def number(value: Any, label: str) -> Decimal:
    """Bounded, ASCII/JSON-style numeric values; bool and implicit zero denied."""
    require(type(value) in (str, int, float, Decimal), label + ":NUMBER_TYPE")
    try:
        text = str(value)
    except ValueError:
        raise InputError(label + ":NUMBER_TEXT") from None
    require(0 < len(text) <= 120 and NUMBER_TEXT.fullmatch(text) is not None,
            label + ":NUMBER_TEXT")
    try:
        result = Decimal(text)
    except (DecimalException, ValueError):
        raise InputError(label + ":INVALID_NUMBER") from None
    require(result.is_finite(), label + ":NONFINITE")
    require(abs(result.as_tuple().exponent) <= 1000, label + ":EXPONENT_RANGE")
    return result


def day(value: Any) -> date:
    require(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)
            is not None, "DATE_FORMAT")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InputError("INVALID_CALENDAR_DATE") from None


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise InputError("NONSTANDARD_JSON_NUMBER:" + value)


def strict_json(text: str) -> Any:
    require(type(text) is str and len(text) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE_OR_TYPE")
    # Bound nesting before decoding, independently of interpreter recursion limits.
    depth = 0
    quoted = False
    escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            require(depth <= 64, "JSON_TOO_DEEP")
        elif char in "]}":
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=unique_pairs,
                          parse_float=lambda value: number(value, "json_number"),
                          parse_int=lambda value: int(number(value, "json_integer")),
                          parse_constant=invalid_constant)
    except json.JSONDecodeError:
        raise InputError("INVALID_JSON") from None
    except RecursionError:
        raise InputError("JSON_TOO_DEEP") from None


def fixed_context() -> Context:
    # Caller precision, rounding, traps and exponent limits cannot affect results.
    return Context(prec=80, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   traps=[InvalidOperation, DivisionByZero, Overflow])


def daily_metrics(rows: Any, sessions: Any, *, start: str, end: str,
                  initial_nav: Any) -> dict[str, Any]:
    """Check exact membership in the SUPPLIED grid; do not certify that grid."""
    require(type(sessions) is list and 2 <= len(sessions) <= MAX_OBSERVATIONS, "SESSION_GRID_REQUIRED")
    dates = [day(item) for item in sessions]
    require(all(a < b for a, b in zip(dates, dates[1:])),
            "SESSION_DUPLICATE_OR_ORDER")
    first, last = day(start), day(end)
    require(first < last, "WINDOW_ORDER")
    require(dates[0] == first and dates[-1] == last, "WINDOW_GRID_MISMATCH")
    require(type(rows) is list and len(rows) == len(sessions), "NAV_GRID_LENGTH")
    initial = number(initial_nav, "initial_nav")
    require(initial > 0, "INITIAL_NAV_NONPOSITIVE")
    values: list[Decimal] = []
    for i, row in enumerate(rows):
        exact_keys(row, {"date", "nav", "external_flow"}, "nav_row")
        require(row["date"] == sessions[i], "NAV_GRID_DATE_MISMATCH")
        value = number(row["nav"], "nav")
        require(0 <= value <= Decimal("1e30"), "NAV_OUT_OF_RANGE")
        require(number(row["external_flow"], "external_flow") == 0,
                "EXTERNAL_FLOW_REQUIRES_SEPARATE_TWR_ENGINE")
        require(not values or values[-1] != 0 or value == 0,
                "NAV_RESURRECTION_WITHOUT_FLOW")
        values.append(value)
    require(values[0] == initial, "INITIAL_NAV_MISMATCH")
    elapsed = (last - first).days
    with localcontext(fixed_context()):
        peak = initial
        mdd = Decimal(0)
        for value in values:
            peak = max(peak, value)
            mdd = max(mdd, Decimal(1) - value / peak)
        cagr = (Decimal(-1) if values[-1] == 0 else
                ((values[-1] / initial).ln()
                 * Decimal("365.2425") / Decimal(elapsed)).exp() - 1)
    return {
        "elapsed_calendar_days": elapsed,
        "observations_in_supplied_grid": len(values),
        "initial_nav": str(initial), "ending_nav": str(values[-1]),
        "cagr": str(cagr), "mdd_loss_on_supplied_grid": str(mdd),
        "initial_nav_included": True,
        "calendar_and_accounting_authenticated": False,
    }


def threshold_check(sleeve: str, metrics: dict[str, Any]) -> bool:
    require(type(sleeve) is str and sleeve in {"main", "concentrated"}, "UNKNOWN_SLEEVE")
    require(type(metrics) is dict, "METRIC_MAPPING_REQUIRED")
    cagr = number(metrics.get("cagr"), "cagr")
    mdd = number(metrics.get("mdd_loss_on_supplied_grid"), "mdd")
    require(cagr >= -1 and 0 <= mdd <= 1, "METRIC_DOMAIN")
    return (cagr >= Decimal(REFERENCE[sleeve + "_min_cagr"])
            and mdd <= Decimal(REFERENCE[sleeve + "_max_mdd_loss"]))


def validate_meta(meta: Any, sleeve: str) -> None:
    exact_keys(meta, META_KEYS, "metadata")
    require(meta["sleeve"] == sleeve, "SLEEVE_MISMATCH")
    require(meta["currency"] == "USD", "REFERENCE_CURRENCY")
    require(meta["sampling"] == "DAILY_EOD_LEDGER", "NOT_DAILY_LEDGER_DECLARATION")
    require(meta["nav_basis"] == "NET_WITHOUT_EXTERNAL_FLOWS", "NAV_BASIS")
    require(type(meta["run_id"]) is str and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", meta["run_id"]) is not None,
            "RUN_ID_REQUIRED")
    for key in sorted(META_KEYS):
        if key.endswith("sha256") or key == "source_commit":
            length = 40 if key == "source_commit" else 64
            require(type(meta[key]) is str and
                    re.fullmatch(r"[0-9a-f]{%d}" % length, meta[key]) is not None,
                    key + ":HASH_FORMAT_ONLY")


def assess_pair(bundle: Any) -> dict[str, Any]:
    exact_keys(bundle, {"contract", "sessions", "portfolios"}, "bundle")
    exact_keys(bundle["contract"], set(REFERENCE), "contract")
    require(all(type(value) is str for value in bundle["contract"].values()),
            "CONTRACT_VALUE_TYPES")
    require(bundle["contract"] == REFERENCE, "REFERENCE_CONTRACT_DRIFT")
    exact_keys(bundle["portfolios"], {"main", "concentrated"}, "portfolios")
    out: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for sleeve in ("main", "concentrated"):
        entry = bundle["portfolios"][sleeve]
        exact_keys(entry, {"metadata", "nav_rows"}, "portfolio")
        validate_meta(entry["metadata"], sleeve)
        metadata[sleeve] = entry["metadata"]
        metrics = daily_metrics(entry["nav_rows"], bundle["sessions"],
                                start=REFERENCE["start"], end=REFERENCE["end"],
                                initial_nav=REFERENCE["initial_nav"])
        out[sleeve] = {"metrics": metrics,
                       "numeric_thresholds_pass": threshold_check(sleeve, metrics)}
    for key in sorted(SHARED_KEYS):
        require(metadata["main"][key] == metadata["concentrated"][key],
                "PAIR_CONTRACT_MISMATCH:" + key)
    passed = all(out[s]["numeric_thresholds_pass"] for s in out)
    return {
        "schema_version": SCHEMA, "authority": "RESEARCH_ONLY",
        "numeric_status": "METRIC_PASS_UNVERIFIED" if passed else "METRIC_FAIL",
        "mission_status": "NOT_PROVEN", "portfolios": out,
        "declared_metadata": {s: dict(metadata[s]) for s in metadata},
        "unverified_domains": list(UNVERIFIED),
        "orders_allowed": False, "production_promotion_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="bounded JSON input; reads only")
    args = parser.parse_args(argv)
    try:
        with open(args.bundle, "rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        require(len(raw) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE")
        result = assess_pair(strict_json(raw.decode("utf-8")))
    except (InputError, OSError, UnicodeError, DecimalException) as exc:
        print(json.dumps({"schema_version": SCHEMA, "numeric_status": "INVALID_INPUT",
                          "mission_status": "NOT_PROVEN", "authority": "RESEARCH_ONLY",
                          "error": str(exc) if isinstance(exc, InputError) else type(exc).__name__,
                          "orders_allowed": False,
                          "production_promotion_allowed": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # A zero exit code is successful numeric processing, NOT certification.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
