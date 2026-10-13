"""R1000 actual-first valuation provenance audit, RESEARCH_ONLY.

A read-only diagnostic for legacy scored/portfolio CSVs. It does NOT grant
source admission, infer fiscal-year estimates, change ranking or estimate ER.
This script distinguishes existence of a numeric metric from verification of
its economic identity, accounting basis and publication-time provenance.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
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


def _has(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() not in _INVALID_TOKENS


def classify(row: dict[str, str]) -> dict[str, Any]:
    """Conservative assessment of supplied observations; no synthetic fallback."""
    ticker = str(row.get("ticker") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,15}", ticker):
        raise AuditInputError("INVALID_TICKER")
    peg, pe, roi, fcf = (number(row.get(field)) for field in
                           ("peg_final", "forward_pe_final", "roic_approx", "fcf_ttm"))
    peg_status = ("MISSING" if peg is None else
                  "NONPOSITIVE_UNUSABLE" if peg <= 0 else
                  "LEGACY_PRESENT_UNVERIFIED")
    source = str(row.get("forward_pe_source") or "").strip().lower()
    pe_status = ("MISSING" if pe is None else "NONPOSITIVE_UNUSABLE" if pe <= 0 else
                 "TRAILING_MISLABELED_FORWARD" if source in ("ep_ttm", "ttm", "trailing") else
                 "PROVIDER_ONLY_UNVERIFIED" if source else
                 "ORIGIN_UNKNOWN_UNVERIFIED")
    fy1, fy2 = number(row.get("eps_est_fy1")), number(row.get("eps_est_fy2"))
    if fy1 is None or fy2 is None:
        forward_status = "FY1_FY2_ESTIMATES_MISSING"
    elif fy1 <= 0 or fy2 <= fy1:
        forward_status = "FY1_FY2_NOT_POSITIVE_GROWTH"
    else:
        # Floats alone cannot attest same identity, GAAP basis, vintage, ADR unit.
        forward_status = "VALUES_PRESENT_NATIVE_IDENTITY_AND_PIT_UNVERIFIED"
    roi_status = "MISSING" if roi is None else "PROXY_NOT_ACTUAL_ROIC"
    return {
        "ticker": ticker,
        "observation_date": row.get("rebalance_date") or None,
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
        "fundamental_source": row.get("fund_source") or None,
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
    reader = csv.DictReader(io.StringIO(data, newline=""), strict=True)
    try:
        fields = reader.fieldnames or []
    except csv.Error as exc:
        raise AuditInputError("CSV_PARSING_FAILURE") from exc
    if not fields or len(fields) != len(set(fields)) or any(not s or not s.strip() for s in fields):
        raise AuditInputError("INVALID_OR_DUPLICATE_HEADERS")
    if "ticker" not in fields:
        raise AuditInputError("TICKER_COLUMN_REQUIRED")
    if decision_cutoff is not None:
        try:
            if datetime.strptime(decision_cutoff, "%Y-%m-%d").date().isoformat() != decision_cutoff:
                raise ValueError("format")
        except ValueError as exc:
            raise AuditInputError("BAD_DECISION_CUTOFF_DATE") from exc
    observations = []
    excluded_non_equity = 0
    seen: set[tuple[str, str]] = set()
    try:
        for row in reader:
            if len(observations) >= _MAX_ROWS:
                raise AuditInputError("ROW_BUDGET_EXCEEDED")
            if None in row:
                raise AuditInputError("MALFORMED_CSV_EXTRA_FIELD")
            if any(v is None for v in row.values()):
                raise AuditInputError("MALFORMED_CSV_SHORT_ROW")
            if str(row.get("ticker") or "").strip().upper() == "CASH":
                excluded_non_equity += 1
                continue
            item = classify(row)
            key = (item["ticker"], item["observation_date"] or "")
            if key in seen:
                raise AuditInputError("DUPLICATE_SECURITY_DATE")
            seen.add(key)
            if decision_cutoff is not None and item["observation_date"]:
                try:
                    d = datetime.strptime(item["observation_date"], "%Y-%m-%d").date()
                    cutoff = datetime.strptime(decision_cutoff, "%Y-%m-%d").date()
                except ValueError as exc:
                    raise AuditInputError("BAD_DECISION_CUTOFF_DATE") from exc
                if d > cutoff:
                    raise AuditInputError("FUTURE_ARCHIVED_OBSERVATION")
            observations.append(item)
    except (csv.Error, UnicodeError) as exc:
        raise AuditInputError("CSV_PARSING_FAILURE") from exc
    if not observations:
        raise AuditInputError("NO_CANDIDATES")
    summary: dict[str, int] = {}
    for key in ("peg_status", "pe_status", "forward_peg_v2_status", "roic_status", "fcf_status"):
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
            for k in ("legacy_peg", "forward_pe", "roic_approx", "fcf_ttm")
        },
        "status_counts": dict(sorted(summary.items())),
        "results": observations,
        "source_scope": "ARCHIVED_RESEARCH_CSV_DIAGNOSTIC_ONLY",
        "authority": dict(SHADOW_AUTHORITY),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--cutoff-date")
    args = parser.parse_args(argv)
    try:
        raw = args.input_csv.read_bytes()
        data = audit_bytes(raw, expected_sha256=args.expected_sha256,
                           source_name=args.input_csv.name, decision_cutoff=args.cutoff_date)
    except (OSError, AuditInputError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": str(exc),
                          "authority": SHADOW_AUTHORITY}, sort_keys=True))
        return 2
    print(json.dumps(data, sort_keys=True, allow_nan=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
