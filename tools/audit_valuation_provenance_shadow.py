"""R1000 actual-first valuation provenance audit, RESEARCH_ONLY.

A read-only diagnostic for legacy scored/portfolio CSVs. It does NOT grant
source admission, infer fiscal-year estimates, change ranking or estimate ER.
This script distinguishes existence of a numeric metric from verification of
its economic identity, accounting basis and publication-time provenance.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

SCHEMA = "r1000-valuation-provenance-shadow-v1"
SHADOW_AUTHORITY = {
    "research_only": True,
    "source_authenticated": False,
    "source_admitted": False,
    "historical_pit_certified": False,
    "valuation_accepted": False,
    "er_calculated": False,
    "ranking_allowed": False,
    "portfolio_weight_effect": 0,
    "orders_allowed": False,
    "backtest_acceptance_allowed": False,
}
_COLUMNS = (
    "ticker", "rebalance_date", "fund_source", "fund_effective_period",
    "forward_pe_final", "forward_pe_source", "peg_final", "eps_est_fy1",
    "eps_est_fy2", "roic_approx", "fcf_ttm", "fcfy_ttm",
)
_INVALID_TOKENS = {"", "none", "null", "nan", "na", "n/a", "<na>", "--", "unknown"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 20_000_000
_MAX_ROWS = 5000
_MAX_RECORD_CHARS = 65_536
_MAX_COLUMNS = 512
_PE_SOURCE_LABELS = {"ep_ttm", "ttm", "trailing", "finnhub", "legacy", "alpha_vantage"}
_FUND_SOURCE_LABELS = {"companyfacts", "sec", "sec_companyfacts", "alpha_vantage",
                       "finnhub", "legacy", "yfinance", "yahoo"}


class AuditInputError(ValueError):
    pass


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in _INVALID_TOKENS:
            return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


def _source_label(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    label = value.strip().lower()
    return label if label in allowed else None


class _RecordLines:
    """Bound each logical CSV record before csv.reader creates cell objects."""
    def __init__(self, data: str):
        self.stream = io.StringIO(data, newline="")
        self.used = 0

    def __iter__(self):
        return self

    def __next__(self) -> str:
        line = self.stream.readline(_MAX_RECORD_CHARS + 1 - self.used)
        if not line:
            raise StopIteration
        self.used += len(line)
        if self.used > _MAX_RECORD_CHARS:
            raise AuditInputError("CSV_RECORD_CHARACTER_BUDGET_EXCEEDED")
        return line


def _parse_date(value: str, reason: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        if parsed.isoformat() != value:
            raise ValueError("format")
        return parsed
    except ValueError as exc:
        raise AuditInputError(reason) from exc


def classify(row: dict[str, str]) -> dict[str, Any]:
    """Conservative assessment of supplied observations; no synthetic fallback."""
    ticker = str(row.get("ticker") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,15}", ticker):
        raise AuditInputError("INVALID_TICKER")
    peg, pe, roi, fcf, fcfy = (number(row.get(field)) for field in
                           ("peg_final", "forward_pe_final", "roic_approx", "fcf_ttm", "fcfy_ttm"))
    peg_status = ("MISSING" if peg is None else
                  "NONPOSITIVE_UNUSABLE" if peg <= 0 else
                  "LEGACY_PRESENT_UNVERIFIED")
    source = _source_label(row.get("forward_pe_source"), _PE_SOURCE_LABELS)
    pe_status = ("MISSING" if pe is None else "NONPOSITIVE_UNUSABLE" if pe <= 0 else
                 "TRAILING_MISLABELED_FORWARD" if source in ("ep_ttm", "ttm", "trailing", "finnhub") else
                 "PROVIDER_ONLY_UNVERIFIED" if source else
                 "ORIGIN_UNKNOWN_UNVERIFIED")
    fy1, fy2 = number(row.get("eps_est_fy1")), number(row.get("eps_est_fy2"))
    if fy1 is None or fy2 is None:
        forward_status = "FY1_FY2_ESTIMATES_MISSING"
    elif fy1 <= 0 or fy2 <= fy1:
        forward_status = "FY1_FY2_NOT_POSITIVE_GROWTH"
    elif pe is None:
        forward_status = "FORWARD_PE_MISSING"
    elif pe <= 0:
        forward_status = "FORWARD_PE_NONPOSITIVE_UNUSABLE"
    else:
        # Floats alone cannot attest same identity, GAAP basis, vintage, ADR unit.
        forward_status = "VALUES_PRESENT_NATIVE_IDENTITY_AND_PIT_UNVERIFIED"
    roi_status = "MISSING" if roi is None else "PROXY_NOT_ACTUAL_ROIC"
    observation_date = row.get("rebalance_date") or None
    if observation_date is not None:
        _parse_date(observation_date, "BAD_OBSERVATION_DATE")
    return {
        "ticker": ticker,
        "observation_date": observation_date,
        "legacy_peg": peg,
        "peg_status": peg_status,
        "forward_pe": pe,
        "pe_status": pe_status,
        "forward_pe_source": source or None,
        "forward_peg_v2": None,
        "forward_peg_v2_status": forward_status,
        "roic_approx": roi,
        "roic_status": roi_status,
        "fcf_ttm": fcf,
        "fcf_status": "PRESENT_SOURCE_PROOF_UNVERIFIED" if fcf is not None else "MISSING",
        "fcfy_ttm": fcfy,
        "fcfy_status": "PRESENT_SOURCE_PROOF_UNVERIFIED" if fcfy is not None else "MISSING",
        "fundamental_source": _source_label(row.get("fund_source"), _FUND_SOURCE_LABELS),
        "fundamental_publication_proof": "NOT_ESTABLISHED_BY_SCORE_CSV",
        "current_valuation_comparison_allowed": False,
        "ranking_effect_allowed": False,
    }


def audit_bytes(raw: bytes, *, expected_sha256: str | None = None,
                source_name: str = "source.csv", decision_cutoff: str | None = None) -> dict[str, Any]:
    if not raw or len(raw) > _MAX_BYTES:
        raise AuditInputError("INPUT_BYTE_BUDGET_OR_EMPTY")
    src_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if not _SHA.fullmatch(expected_sha256) or src_sha != expected_sha256:
            raise AuditInputError("SOURCE_BYTES_HASH_MISMATCH")
    try:
        data = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AuditInputError("CSV_NOT_UTF8") from exc
    lines = _RecordLines(data)
    reader = csv.reader(lines, strict=True)
    try:
        fields = next(reader, [])
    except csv.Error as exc:
        raise AuditInputError("CSV_PARSING_FAILURE") from exc
    if len(fields) > _MAX_COLUMNS:
        raise AuditInputError("CSV_COLUMN_BUDGET_EXCEEDED")
    if not fields or len(fields) != len(set(fields)) or any(not s or not s.strip() for s in fields):
        raise AuditInputError("INVALID_OR_DUPLICATE_HEADERS")
    if "ticker" not in fields:
        raise AuditInputError("TICKER_COLUMN_REQUIRED")
    cutoff = (_parse_date(decision_cutoff, "BAD_DECISION_CUTOFF_DATE")
              if decision_cutoff is not None else None)
    observations = []
    excluded_non_equity = 0
    seen: set[tuple[str, str]] = set()
    try:
        parsed_rows = 0
        while True:
            lines.used = 0
            values = next(reader, None)
            if values is None:
                break
            parsed_rows += 1
            if parsed_rows > _MAX_ROWS:
                raise AuditInputError("ROW_BUDGET_EXCEEDED")
            if not values:
                continue
            if len(values) > len(fields):
                raise AuditInputError("MALFORMED_CSV_EXTRA_FIELD")
            if len(values) < len(fields):
                raise AuditInputError("MALFORMED_CSV_SHORT_ROW")
            row = dict(zip(fields, values))
            if str(row.get("ticker") or "").strip().upper() == "CASH":
                excluded_non_equity += 1
                continue
            item = classify(row)
            key = (item["ticker"], item["observation_date"] or "")
            if key in seen:
                raise AuditInputError("DUPLICATE_SECURITY_DATE")
            seen.add(key)
            if cutoff is not None and item["observation_date"]:
                if _parse_date(item["observation_date"], "BAD_OBSERVATION_DATE") > cutoff:
                    raise AuditInputError("FUTURE_ARCHIVED_OBSERVATION")
            observations.append(item)
    except (csv.Error, UnicodeError) as exc:
        raise AuditInputError("CSV_PARSING_FAILURE") from exc
    if not observations:
        raise AuditInputError("NO_CANDIDATES")
    summary: dict[str, int] = {}
    for key in ("peg_status", "pe_status", "forward_peg_v2_status", "roic_status", "fcf_status", "fcfy_status"):
        for row in observations:
            k = f"{key}:{row[key]}"
            summary[k] = summary.get(k, 0) + 1
    return {
        "schema": SCHEMA,
        "source_name": Path(source_name).name,
        "source_sha256": src_sha,
        "source_bytes": len(raw),
        "row_count": len(observations),
        "excluded_non_equity_rows": excluded_non_equity,
        "observation_dates": sorted({r["observation_date"] for r in observations if r["observation_date"]}),
        "observed_field_presence": {
            k: sum(r[k] is not None for r in observations)
            for k in ("legacy_peg", "forward_pe", "roic_approx", "fcf_ttm", "fcfy_ttm")
        },
        "status_counts": dict(sorted(summary.items())),
        "results": observations,
        "source_scope": "ARCHIVED_RESEARCH_CSV_DIAGNOSTIC_ONLY",
        "authority": dict(SHADOW_AUTHORITY),
    }


def _read_input(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        # Windows can refuse directory opens before descriptor validation.
        # This secondary probe only classifies an already refused input;
        # it never authorizes a read or replaces the successful-open fstat.
        try:
            is_directory = stat.S_ISDIR(os.stat(path).st_mode)
        except OSError:
            is_directory = False
        if is_directory:
            raise AuditInputError("INPUT_NOT_REGULAR_FILE") from None
        raise
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise AuditInputError("INPUT_NOT_REGULAR_FILE")
        if info.st_size > _MAX_BYTES:
            raise AuditInputError("INPUT_BYTE_BUDGET_OR_EMPTY")
        stream = os.fdopen(descriptor, "rb")
        descriptor = None  # The stream owns the descriptor from this point.
        # Bound allocation even if the file grows or its size is unavailable.
        with stream as opened:
            raw = opened.read(_MAX_BYTES + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not raw or len(raw) > _MAX_BYTES:
        raise AuditInputError("INPUT_BYTE_BUDGET_OR_EMPTY")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--cutoff-date")
    args = parser.parse_args(argv)
    try:
        raw = _read_input(args.input_csv)
        data = audit_bytes(raw, expected_sha256=args.expected_sha256,
                           source_name=args.input_csv.name, decision_cutoff=args.cutoff_date)
    except (OSError, AuditInputError) as exc:
        reason = "INPUT_READ_FAILURE" if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": reason,
                          "authority": SHADOW_AUTHORITY}, sort_keys=True))
        return 2
    print(json.dumps(data, sort_keys=True, allow_nan=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
