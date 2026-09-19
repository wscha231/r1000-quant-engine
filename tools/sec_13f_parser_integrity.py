"""Strict integrity adapter for SEC 13F information-table parser output.

This module validates raw XML-to-row transport before downstream deduplication or
signal logic. It does not certify filing scope, economic ownership, dollar-unit
semantics, corporate actions, alpha, portfolio weights, or trade decisions.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

VERSION = "13f-parser-integrity-v1"


class IntegrityError(ValueError):
    """Raw filing evidence and parsed rows are missing, ambiguous, or inconsistent."""


def digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def instant(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError("timestamp_missing")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityError("timestamp_invalid") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise IntegrityError("timezone_required")
    return dt.astimezone(timezone.utc)


def required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f"missing:{key}")
    return value.strip()


def number(value: Any, *, nonnegative: bool = True) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise IntegrityError("number_missing_or_boolean")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise IntegrityError("number_invalid") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise IntegrityError("number_not_finite_or_negative")
    if not math.isfinite(float(result)):
        raise IntegrityError("number_out_of_range")
    return result


def _other_managers(value: Any) -> tuple[str, ...]:
    if value is None:
        raise IntegrityError("other_manager_missing_not_explicit_empty")
    if isinstance(value, str):
        values = re.split(r"[\s,;]+", value.strip()) if value.strip() else []
    elif isinstance(value, list) and all(isinstance(x, str) for x in value):
        values = value
    else:
        raise IntegrityError("other_manager_invalid")
    return tuple(sorted(set(x.strip() for x in values if x.strip())))


def security_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    cusip = required_text(row, "cusip").upper()
    if not re.fullmatch(r"[A-Z0-9*@#]{9}", cusip):
        raise IntegrityError("exact_cusip_required")
    cls = " ".join(required_text(row, "title_of_class").upper().split())
    if "put_call" not in row or not isinstance(row["put_call"], str):
        raise IntegrityError("put_call_missing_not_explicit_cash")
    option = row["put_call"].strip().upper()
    if option not in ("", "CALL", "PUT"):
        raise IntegrityError("put_call_invalid")
    share_type = required_text(row, "share_type").upper()
    if share_type not in ("SH", "PRN"):
        raise IntegrityError("share_type_invalid")
    return cusip, cls, option, share_type


def row_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return security_key(row) + (
        required_text(row, "investment_discretion").upper(),
        _other_managers(row.get("other_manager")),
    )


def adapt_legacy_parser_rows(
    raw_information_table: bytes,
    parsed_rows: Iterable[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    classifications: Mapping[str, Mapping[str, Any]],
    *,
    cutoff: str,
) -> dict[str, Any]:
    """Verify parsed 13F rows against raw XML before any lossy downstream step.

    The adapter checks row count, security/reporting context, quantities and the
    parser's explicit legacy value multiplier. It preserves cash/CALL/PUT/share
    class distinctions and repeated other-manager identifiers. Unknown asset
    classification remains UNKNOWN. Corporate-action adjustment is applied only
    when the manifest explicitly attests the basis and per-security factor.
    """
    if not isinstance(raw_information_table, bytes):
        raise IntegrityError("raw_xml_bytes_required")
    if len(raw_information_table) > 32 * 1024 * 1024:
        raise IntegrityError("information_table_exceeds_bounded_adapter_limit")
    upper = raw_information_table.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise IntegrityError("xml_entities_not_allowed")
    try:
        root = ET.fromstring(raw_information_table)
    except ET.ParseError as exc:
        raise IntegrityError("information_table_xml_invalid") from exc

    raw_hash = hashlib.sha256(raw_information_table).hexdigest()
    if raw_hash != manifest.get("raw_sha256"):
        raise IntegrityError("raw_xml_hash_mismatch")

    parsed = [dict(row) for row in parsed_rows]
    nodes = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() == "infotable"
    ]
    if len(nodes) != len(parsed) or len(nodes) != manifest.get("expected_row_count"):
        raise IntegrityError("parser_or_cover_collapsed_raw_rows")

    multiplier = number(manifest.get("parser_value_multiplier"))
    if multiplier not in (Decimal(1), Decimal(1000)):
        raise IntegrityError("explicit_legacy_parser_value_multiplier_required")

    filing = dict(manifest)
    accession = required_text(filing, "source_accession")
    rows: list[dict[str, Any]] = []
    for ordinal, (node, original) in enumerate(zip(nodes, parsed), 1):
        def text(name: str) -> str:
            parts = [
                str(item.text or "").strip()
                for item in node.iter()
                if item.tag.rsplit("}", 1)[-1].lower() == name.lower()
            ]
            if name == "otherManager":
                return ",".join(parts)
            if len(parts) > 1:
                raise IntegrityError("multiple_raw_values_for_single_field")
            return parts[0] if parts else ""

        raw_key = {
            "cusip": text("cusip"),
            "title_of_class": text("titleOfClass"),
            "put_call": text("putCall"),
            "share_type": text("sshPrnamtType"),
            "investment_discretion": text("investmentDiscretion"),
            "other_manager": text("otherManager"),
        }
        if row_key(raw_key) != row_key(original):
            raise IntegrityError("raw_parser_security_or_reporting_context_mismatch")
        if original.get("source_accession") != accession:
            raise IntegrityError("raw_parser_accession_mismatch")

        raw_shares = number(text("sshPrnamt"))
        raw_value = number(text("value"))
        if number(original.get("shares")) != raw_shares:
            raise IntegrityError("raw_parser_quantity_mismatch")
        expected_value = raw_value * multiplier
        parsed_value = number(original.get("market_value_usd"))
        tolerance = max(Decimal("0.000001"), abs(expected_value) * Decimal("1e-12"))
        if abs(parsed_value - expected_value) > tolerance:
            raise IntegrityError("raw_parser_value_mismatch")

        row = dict(original)
        row["source_row_id"] = str(ordinal)
        row["raw_reported_shares"] = str(raw_shares)
        row["raw_reported_value"] = str(raw_value)
        asset = classifications.get(security_key(row)[0])
        row["asset_type"] = "UNKNOWN"
        if asset is not None:
            required_text(asset, "evidence_id")
            if instant(required_text(asset, "available_at")) <= instant(cutoff):
                row["asset_type"] = required_text(asset, "asset_type").upper()

        if filing.get("corporate_actions_verified") is True:
            required_text(filing, "corporate_action_evidence_id")
            required_text(filing, "corporate_action_basis_id")
            factors = filing.get("share_adjustment_factors", {})
            key = "|".join(security_key(row))
            if key not in factors or number(factors[key]) <= 0:
                raise IntegrityError("explicit_share_adjustment_factor_required")
            row["shares"] = float(raw_shares * number(factors[key]))
        rows.append(row)

    filing["rows"] = rows
    filing["raw_numeric_verified"] = True
    filing["adapter_evidence_id"] = digest(
        {
            "raw_sha256": raw_hash,
            "parsed_rows": parsed,
            "cutoff": cutoff,
            "classifications": dict(classifications),
            "manifest": dict(manifest),
            "adapter_version": VERSION,
        }
    )
    return filing
