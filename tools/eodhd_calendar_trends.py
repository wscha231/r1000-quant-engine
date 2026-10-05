"""Calendar Trends -> existing H1 observations, without collection or admission.

Only explicit estimate fields are consensus. Embedded lookbacks are observations
of a provider response, never backdated snapshots or independently verified
analyst breadth. Importing this module performs no I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from tools import earnings_consensus_h1 as h1

PROVIDER = "eodhd_calendar"
ENDPOINT = "https://eodhd.com/api/calendar/trends"
MAX_BYTES = 4_000_000
MAX_SYMBOLS = 24
MAX_RECORDS_PER_SYMBOL = 256
MAX_NODES = 200_000
MAX_DEPTH = 24
PERIOD_TYPES = {"0q": "QUARTERLY", "+1q": "QUARTERLY",
                "0y": "ANNUAL", "+1y": "ANNUAL"}
IDENTITY_KEYS = ("issuer_id", "security_id", "accounting_basis", "currency",
                 "share_or_ADR_unit", "provider_version", "provider_published_at")
LOOKBACK_FIELDS = ("epsTrendCurrent", "epsTrend7daysAgo", "epsTrend30daysAgo",
                   "epsTrend60daysAgo", "epsTrend90daysAgo")
REVISION_COUNT_FIELDS = ("epsRevisionsUpLast7days", "epsRevisionsUpLast30days",
                         "epsRevisionsDownLast30days")
ESTIMATE_FIELDS = tuple(name + suffix for name in ("earnings", "revenue")
                       for suffix in ("EstimateAvg", "EstimateLow", "EstimateHigh",
                                      "EstimateNumberOfAnalysts"))
AUXILIARY_FIELDS = ("growth", "earningsEstimateGrowth", "revenueEstimateGrowth",
                    "earningsEstimateYearAgoEps", "revenueEstimateYearAgoEps")


class CalendarError(ValueError):
    """Fixed local error codes only; never include untrusted payload text."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise CalendarError(code)


def _tree_check(payload: Any) -> None:
    stack = [(payload, 0)]
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        _need(visited <= MAX_NODES and depth <= MAX_DEPTH, "CALENDAR_JSON_LIMIT")
        if type(value) is dict:
            _need(all(type(k) is str for k in value), "CALENDAR_INVALID_JSON")
            stack.extend((v, depth + 1) for v in value.values())
        elif type(value) is list:
            stack.extend((v, depth + 1) for v in value)
        elif type(value) is float:
            _need(math.isfinite(value), "CALENDAR_NONFINITE_JSON")
        else:
            _need(value is None or type(value) in (str, int, bool), "CALENDAR_INVALID_JSON")


def strict_json_loads(raw: bytes) -> Any:
    """Decode bounded JSON once, refusing duplicate keys and nonfinite literals."""
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "CALENDAR_RESPONSE_SIZE")

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result, "CALENDAR_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid_constant(_):
        raise CalendarError("CALENDAR_NONFINITE_JSON")

    def strict_float(text):
        _need(len(text) <= 128, "CALENDAR_JSON_NUMBER_LIMIT")
        number = float(text)
        _need(math.isfinite(number), "CALENDAR_NONFINITE_JSON")
        _need(number != 0 or Decimal(text) == 0, "CALENDAR_NUMERIC_UNDERFLOW")
        return number

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                            parse_constant=invalid_constant, parse_float=strict_float)
    except CalendarError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        raise CalendarError("CALENDAR_INVALID_JSON") from None
    _tree_check(result)
    return result


def symbols_checked(symbols: Any) -> tuple[str, ...]:
    _need(type(symbols) in (tuple, list) and 1 <= len(symbols) <= MAX_SYMBOLS,
          "CALENDAR_EXPLICIT_SYMBOLS_REQUIRED")
    _need(all(type(s) is str and re.fullmatch(r"[A-Z]{1,8}\.US", s) for s in symbols),
          "CALENDAR_EXPLICIT_US_MAPPING_REQUIRED")
    _need(len(set(symbols)) == len(symbols), "CALENDAR_DUPLICATE_SYMBOL")
    return tuple(symbols)


def measurement(value: Any, *, count: bool = False) -> dict:
    """Zero is an observation; invalid/missing values do not become neutral zero."""
    if value is None:
        return {"raw": None, "value": None, "status": "MISSING"}
    valid_type = type(value) in (int, float, str)
    if isinstance(value, str) and len(value) > 128:
        valid_type = False
    # Validate the exact decimal first. float("1e-999") is zero and
    # float("4.0000000000000001") is integral; neither may fabricate a count.
    try:
        exact = Decimal(str(value)) if valid_type else None
        number = float(exact) if exact is not None and exact.is_finite() else None
        if number is not None and (not math.isfinite(number) or
                (number == 0 and exact != 0) or
                (count and (exact < 0 or exact > 1_000_000 or
                            exact != exact.to_integral_value()))):
            number = None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        number = None
    if number is None:
        return {"raw": value, "value": None, "status": "INVALID"}
    number = int(number) if count else number
    return {"raw": value, "value": number,
            "status": "EXPLICIT_ZERO" if number == 0 else "OBSERVED"}


def normalize_payload(payload: Any, requested_symbols: Any) -> dict:
    """Bind nested groups to echoed symbols and each record's explicit code.

    The echoed order may differ from the requested order. Missing/extra/duplicate
    symbols, truncation, misplaced rows and duplicate fiscal periods fail closed.
    No issuer, GAAP/non-GAAP basis, currency or share/ADR unit is inferred.
    """
    requested = symbols_checked(requested_symbols)
    _tree_check(payload)
    _need(type(payload) is dict and payload.get("type") == "Trends", "CALENDAR_SCHEMA")
    _need(not any(k in payload for k in ("error", "Error", "errors")), "CALENDAR_ERROR_PAYLOAD")
    echoed = payload.get("symbols")
    _need(type(echoed) is str, "CALENDAR_SYMBOL_ECHO_REQUIRED")
    echoed = symbols_checked(echoed.split(","))
    _need(set(echoed) == set(requested), "CALENDAR_SYMBOL_SET_MISMATCH")
    groups = payload.get("trends")
    _need(type(groups) is list and len(groups) == len(echoed), "CALENDAR_GROUP_COUNT")
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                allow_nan=False).encode()
    _need(len(canonical_bytes) <= MAX_BYTES, "CALENDAR_RESPONSE_SIZE")
    by_symbol = {}
    for symbol, records in zip(echoed, groups):
        _need(type(records) is list and len(records) <= MAX_RECORDS_PER_SYMBOL,
              "CALENDAR_RECORDS_LIMIT_OR_TYPE")
        eps, revenue, diagnostics, seen = [], [], [], set()
        for item in records:
            _need(type(item) is dict, "CALENDAR_RECORD_TYPE")
            _need(item.get("code") == symbol, "CALENDAR_RECORD_SECURITY_MISMATCH")
            period = item.get("period")
            _need(type(period) is str and period in PERIOD_TYPES, "CALENDAR_PERIOD_UNSUPPORTED")
            fiscal = item.get("date")
            try:
                _need(type(fiscal) is str and date.fromisoformat(fiscal).isoformat() == fiscal,
                      "CALENDAR_FISCAL_DATE")
            except (ValueError, TypeError):
                raise CalendarError("CALENDAR_FISCAL_DATE") from None
            period_type = PERIOD_TYPES[period]
            # Redundant provider metadata must agree, never be silently discarded.
            for name in ("fiscal_period_end", "fiscalDateEnding"):
                _need(item.get(name) is None or item[name] == fiscal,
                      "CALENDAR_CONFLICTING_FISCAL_IDENTITY")
            _need(item.get("period_type") is None or item["period_type"] == period_type,
                  "CALENDAR_CONFLICTING_PERIOD_TYPE")
            _need("is_estimate" not in item or item["is_estimate"] is True,
                  "CALENDAR_NOT_ESTIMATE_RECORD")
            _need(str(item.get("type", "")).lower() not in {"actual", "history"},
                  "CALENDAR_NOT_ESTIMATE_RECORD")
            key = (fiscal, period_type)
            _need(key not in seen, "CALENDAR_DUPLICATE_FISCAL_PERIOD")
            seen.add(key)
            # Optional provider metadata is carried only as explicitly supplied.
            identity = {}
            for name in IDENTITY_KEYS:
                value = item.get(name)
                _need(value is None or (type(value) is str and len(value) <= 256),
                      "CALENDAR_IDENTITY_METADATA_TYPE")
                identity[name] = value
            fields = {name: measurement(item.get(name), count=(name in REVISION_COUNT_FIELDS
                       or name.endswith("NumberOfAnalysts")))
                      for name in ESTIMATE_FIELDS + LOOKBACK_FIELDS + REVISION_COUNT_FIELDS + AUXILIARY_FIELDS}
            for name, output in (("earnings", eps), ("revenue", revenue)):
                avg, low, high = (fields[name + suffix]["value"]
                                  for suffix in ("EstimateAvg", "EstimateLow", "EstimateHigh"))
                _need(low is None or high is None or low <= high, "CALENDAR_ESTIMATE_RANGE_CONFLICT")
                _need(avg is None or low is None or low <= avg, "CALENDAR_ESTIMATE_RANGE_CONFLICT")
                _need(avg is None or high is None or avg <= high, "CALENDAR_ESTIMATE_RANGE_CONFLICT")
                output.append({**identity, "period": fiscal, "period_type": period_type,
                               "avg": avg, "low": low, "high": high,
                               "numberAnalysts": fields[name + "EstimateNumberOfAnalysts"]["value"]})
            diagnostics.append({"code": symbol, "fiscal_period_end": fiscal,
                "period_type": period_type, "relative_horizon": period, "fields": fields,
                "row_sha256": h1.digest(item),
                "lookback_status": "PROVIDER_REPORTED_NOT_HISTORICAL_VINTAGES",
                "lookback_anchor_status": "UNVERIFIED_PROVIDER_ANCHOR",
                "breadth_status": "PROVIDER_COUNTS_NOT_ADMITTED_ANALYST_BREADTH"})
        by_symbol[symbol] = {"eps_payload": {"data": eps}, "revenue_payload": {"data": revenue},
                             "vendor_observations": diagnostics}
    return {"provider": PROVIDER, "symbols": list(requested), "by_symbol": by_symbol,
            "normalized_payload_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            "h2_eligible": False, "historical_pit_certified": False}


def build_h1_batch(payload: Any, requested_symbols: Any, *, observed_at: str,
                   collected_at: str) -> tuple[list[dict], dict]:
    """Build canonical H1 shape, preserving vendor observations separately in RAM.

    Extra vendor lookback columns must not be spliced into H1 snapshots: the
    existing persisted validator intentionally rejects unknown non-null fields.
    """
    observed, collected = h1.iso_utc(observed_at), h1.iso_utc(collected_at)
    _need(observed is not None and collected is not None, "CALENDAR_EXACT_CLOCKS_REQUIRED")
    _need(datetime.fromisoformat(observed) <= datetime.fromisoformat(collected),
          "CALENDAR_CLOCK_ORDER")
    batch = normalize_payload(payload, requested_symbols)
    publication = payload.get("provider_published_at")
    _need(publication is None or (type(publication) is str and len(publication) <= 256),
          "CALENDAR_IDENTITY_METADATA_TYPE")
    snapshots = []
    for symbol in batch["symbols"]:
        inputs = batch["by_symbol"][symbol]
        snapshot = h1.build_snapshot(symbol[:-3], eps_payload=inputs["eps_payload"],
            revenue_payload=inputs["revenue_payload"], recommendation_payload=None,
            observed_at=observed, first_seen_at=collected, collected_at=collected,
            fetch_source=PROVIDER, provider_published_at=publication)
        h1.validate_persisted_snapshot(snapshot)
        snapshots.append(snapshot)
        inputs["captured_at"] = collected
    return snapshots, batch
