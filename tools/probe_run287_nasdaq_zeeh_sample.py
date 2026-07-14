#!/usr/bin/env python3
"""Probe at most 50 Nasdaq Data Link ZACKS/EEH rows, research-only.

This is a procurement/schema preflight.  It never joins returns, changes a
portfolio, authorizes a purchase, or treats a date-only observation as an
exact point-in-time timestamp.  The API key is read from an environment
variable and is never accepted as a command-line value.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-nasdaq-zeeh-sample-probe-v1"
METADATA_URL = "https://data.nasdaq.com/api/v3/datatables/ZACKS/EEH/metadata.json"
DATA_URL = "https://data.nasdaq.com/api/v3/datatables/ZACKS/EEH.json"
DEFAULT_OUTPUT_ROOT = "outputs/run287_nasdaq_zeeh_sample"
DEFAULT_API_KEY_ENV = "NASDAQ_DATA_LINK_API_KEY"
MAX_ROWS = 50
PRIMARY_KEY = ["m_ticker", "per_end_date", "obs_date", "per_type"]
FORBIDDEN_RETURN_COLUMNS = {
    "adj_close",
    "close",
    "close_price",
    "forward_return",
    "future_return",
    "price",
    "total_return",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sanitize_error_message(value: Any, api_key: str = "") -> str:
    text = str(value)
    text = re.sub(r"(?i)([?&](?:api_key|apikey|token)=)[^&\s]+", r"\1***", text)
    text = re.sub(r"(?i)((?:api[_ -]?key|token)\s*[:=]\s*)[A-Za-z0-9._-]+", r"\1***", text)
    if api_key:
        text = text.replace(api_key, "***")
    return text[:400]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_immutable(path: Path, payload: bytes) -> str:
    """Write an evidence file once; allow an idempotent byte-identical rerun."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return "existing_same" if path.read_bytes() == payload else "collision"
    path.write_bytes(payload)
    return "written"


def response_payload(response: Any) -> tuple[dict[str, Any] | None, bytes, str]:
    raw = bytes(getattr(response, "content", b"") or b"")
    try:
        payload = response.json()
    except Exception as exc:
        return None, raw, sanitize_error_message(exc)
    if not raw:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if not isinstance(payload, dict):
        return None, raw, "response_root_not_object"
    return payload, raw, ""


def table_from_payload(payload: dict[str, Any]) -> tuple[list[str], list[list[Any]], dict[str, Any]]:
    table = payload.get("datatable")
    if not isinstance(table, dict):
        return [], [], {}
    columns_raw = table.get("columns", [])
    columns = [str(item.get("name", "")).strip() for item in columns_raw if isinstance(item, dict)]
    rows_raw = table.get("data", [])
    rows = [list(row) for row in rows_raw if isinstance(row, list)] if isinstance(rows_raw, list) else []
    meta = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
    return columns, rows, meta


def metadata_identity(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("datatable") or payload.get("datatable_metadata") or payload
    if not isinstance(data, dict):
        data = {}
    return {
        "vendor_code": str(data.get("vendor_code", "")),
        "datatable_code": str(data.get("datatable_code", "")),
        "name": str(data.get("name", "")),
        "premium": bool(data.get("premium", False)),
        "primary_key": [str(value) for value in data.get("primary_key", [])]
        if isinstance(data.get("primary_key"), list)
        else [],
    }


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_exact_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.search(r"T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$", text))


def rows_to_dicts(columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows if len(row) == len(columns)]


def csv_bytes(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def base_summary(output_dir: Path, *, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "provider": "Nasdaq Data Link",
        "dataset": "ZACKS/EEH",
        "output_dir": str(output_dir),
        "status": "BLOCKED_UNINITIALIZED",
        "reason": "not_started",
        "research_only": True,
        "purchase_authorized": False,
        "return_join_allowed": False,
        "portfolio_ab_allowed": False,
        "fullrun_allowed": False,
        "production_allowed": False,
        "max_rows": MAX_ROWS,
        "request_count": 0,
        "source_gate_status": "BLOCKED_NOT_AUDITED",
        "source_gate_blockers": [],
    }


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Run287 Nasdaq ZACKS/EEH bounded sample probe",
        "",
        f"- Status: `{summary['status']}`",
        f"- Reason: `{summary['reason']}`",
        f"- Rows: `{summary.get('row_count', 0)}` / max `{MAX_ROWS}`",
        f"- Requests: `{summary.get('request_count', 0)}` / max `2`",
        f"- Source gate: `{summary.get('source_gate_status', 'BLOCKED_NOT_AUDITED')}`",
        f"- Exact timestamp ratio: `{summary.get('exact_timestamp_ratio', 0.0)}`",
        "- Return join, portfolio A/B, purchase, fullrun, and production use remain prohibited.",
    ]
    blockers = summary.get("source_gate_blockers", [])
    if blockers:
        lines.extend(["", "## Source-gate blockers", ""] + [f"- `{item}`" for item in blockers])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize(output_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    write_json(output_dir / "summary.json", summary)
    write_report(output_dir, summary)
    return summary


def probe(
    *,
    api_key: str,
    output_dir: Path,
    as_of_date: date,
    session: Any | None = None,
    generated_at: str | None = None,
    api_key_env_name: str = DEFAULT_API_KEY_ENV,
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    summary = base_summary(output_dir, generated_at=generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not api_key:
        summary.update(status="BLOCKED_CREDENTIAL_MISSING", reason=f"missing_env:{api_key_env_name}")
        return finalize(output_dir, summary)

    client = session or requests.Session()
    responses: list[tuple[str, Any]] = []
    try:
        metadata_response = client.get(METADATA_URL, timeout=20)
        summary["request_count"] += 1
        responses.append(("metadata", metadata_response))
        metadata_status = int(getattr(metadata_response, "status_code", 0))
        if metadata_status != 200:
            reason = "provider_entitlement" if metadata_status in {401, 402, 403} else "metadata_http_error"
            summary.update(
                status="BLOCKED_PROVIDER_ENTITLEMENT" if reason == "provider_entitlement" else "BLOCKED_PROVIDER_HTTP",
                reason=f"{reason}:{metadata_status}",
                http_status=metadata_status,
                error=sanitize_error_message(getattr(metadata_response, "text", ""), api_key),
            )
            return finalize(output_dir, summary)

        metadata, metadata_raw, metadata_error = response_payload(metadata_response)
        if metadata is None:
            summary.update(status="BLOCKED_SCHEMA", reason=f"invalid_metadata_json:{metadata_error}")
            return finalize(output_dir, summary)
        metadata_write = write_immutable(output_dir / "raw" / "metadata.json", metadata_raw)
        if metadata_write == "collision":
            summary.update(status="BLOCKED_IMMUTABLE_COLLISION", reason="metadata_raw_collision")
            return finalize(output_dir, summary)
        summary["metadata_sha256"] = sha256_bytes(metadata_raw)
        summary["metadata_write"] = metadata_write
        identity = metadata_identity(metadata)
        summary["metadata_identity"] = identity
        if identity["vendor_code"] != "ZACKS" or identity["datatable_code"] != "EEH":
            summary.update(status="BLOCKED_SCHEMA", reason="metadata_dataset_identity_mismatch")
            return finalize(output_dir, summary)

        data_response = client.get(
            DATA_URL,
            params={"qopts.per_page": MAX_ROWS, "api_key": api_key},
            timeout=20,
        )
        summary["request_count"] += 1
        responses.append(("data", data_response))
        data_status = int(getattr(data_response, "status_code", 0))
        if data_status != 200:
            reason = "provider_entitlement" if data_status in {401, 402, 403} else "data_http_error"
            summary.update(
                status="BLOCKED_PROVIDER_ENTITLEMENT" if reason == "provider_entitlement" else "BLOCKED_PROVIDER_HTTP",
                reason=f"{reason}:{data_status}",
                http_status=data_status,
                error=sanitize_error_message(getattr(data_response, "text", ""), api_key),
            )
            return finalize(output_dir, summary)

        payload, raw, payload_error = response_payload(data_response)
        if payload is None:
            summary.update(status="BLOCKED_SCHEMA", reason=f"invalid_data_json:{payload_error}")
            return finalize(output_dir, summary)
        raw_write = write_immutable(output_dir / "raw" / "sample.json", raw)
        if raw_write == "collision":
            summary.update(status="BLOCKED_IMMUTABLE_COLLISION", reason="sample_raw_collision")
            return finalize(output_dir, summary)
        summary["sample_sha256"] = sha256_bytes(raw)
        summary["sample_write"] = raw_write

        columns, raw_rows, response_meta = table_from_payload(payload)
        rows = rows_to_dicts(columns, raw_rows)
        summary["columns"] = columns
        summary["row_count"] = len(raw_rows)
        summary["decoded_row_count"] = len(rows)
        summary["response_has_next_cursor"] = bool(response_meta.get("next_cursor_id"))
        summary["primary_key_present"] = all(value in columns for value in PRIMARY_KEY)
        summary["estimate_columns"] = [value for value in columns if "est" in value.lower()]
        summary["forbidden_return_columns"] = sorted(FORBIDDEN_RETURN_COLUMNS & set(columns))

        blockers: list[str] = []
        if len(raw_rows) > MAX_ROWS:
            blockers.append(f"row_limit_exceeded:{len(raw_rows)}>{MAX_ROWS}")
        if len(raw_rows) < MAX_ROWS:
            blockers.append(f"sample_rows_below_requested:{len(raw_rows)}<{MAX_ROWS}")
        if len(rows) != len(raw_rows):
            blockers.append("row_width_mismatch")
        missing_primary = [value for value in PRIMARY_KEY if value not in columns]
        if missing_primary:
            blockers.append("missing_primary_key:" + ",".join(missing_primary))
        if not summary["estimate_columns"]:
            blockers.append("missing_estimate_columns")
        if summary["forbidden_return_columns"]:
            blockers.append("unexpected_return_or_price_columns")

        obs_values = [row.get("obs_date") for row in rows]
        obs_dates = [parse_date(value) for value in obs_values]
        invalid_obs = sum(value is None for value in obs_dates)
        future_obs = sum(value is not None and value > as_of_date for value in obs_dates)
        exact_count = sum(is_exact_timestamp(value) for value in obs_values)
        exact_ratio = exact_count / len(rows) if rows else 0.0
        summary["invalid_obs_date_rows"] = invalid_obs
        summary["future_obs_date_rows"] = future_obs
        summary["exact_timestamp_ratio"] = exact_ratio
        if invalid_obs:
            blockers.append(f"invalid_obs_date_rows:{invalid_obs}")
        if future_obs:
            blockers.append(f"future_obs_date_rows:{future_obs}")

        duplicate_keys = 0
        if not missing_primary and rows:
            keys = [tuple(str(row.get(value, "")) for value in PRIMARY_KEY) for row in rows]
            duplicate_keys = len(keys) - len(set(keys))
            if duplicate_keys:
                blockers.append(f"duplicate_primary_keys:{duplicate_keys}")
        summary["duplicate_primary_keys"] = duplicate_keys
        summary["distinct_m_tickers"] = len({str(row.get("m_ticker", "")) for row in rows if row.get("m_ticker")})

        source_gate_blockers: list[str] = []
        if exact_ratio < 1.0:
            source_gate_blockers.append("date_only_obs_date_not_exact_timestamp")
        if not any(value in columns for value in ["security_id", "cusip", "isin"]):
            source_gate_blockers.append("stable_security_id_not_observed")
        if "is_delisted" not in columns:
            source_gate_blockers.append("delisted_flag_not_observed")
        if not any(value in columns for value in ["is_adr", "is_adr_global_listing", "listing_country"]):
            source_gate_blockers.append("adr_identity_not_observed")
        summary["source_gate_blockers"] = source_gate_blockers
        summary["source_gate_status"] = "PASS_SCHEMA_ONLY" if not source_gate_blockers else "BLOCKED_PIT_IDENTITY_GAPS"

        csv_write = write_immutable(output_dir / "sample_rows.csv", csv_bytes(columns, rows))
        if csv_write == "collision":
            blockers.append("sample_csv_collision")
        summary["sample_csv_write"] = csv_write

        if blockers:
            summary["schema_blockers"] = blockers
            if all(item.startswith("sample_rows_below_requested") for item in blockers):
                summary.update(status="UNDERPOWERED_SAMPLE", reason=blockers[0])
            else:
                summary.update(status="BLOCKED_SCHEMA", reason=blockers[0])
        else:
            summary.update(status="READY_50_ROW_SCHEMA_REVIEW", reason="bounded_schema_sample_captured")
        return finalize(output_dir, summary)
    except Exception as exc:
        summary.update(status="BLOCKED_PROVIDER_ERROR", reason="request_or_parse_exception", error=sanitize_error_message(exc, api_key))
        return finalize(output_dir, summary)
    finally:
        if session is None and hasattr(client, "close"):
            client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--as-of-date", default=datetime.now(timezone.utc).date().isoformat())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        as_of = date.fromisoformat(args.as_of_date)
    except ValueError:
        raise SystemExit("--as-of-date must be YYYY-MM-DD")
    output_dir = repo_path(args.output_root) / args.run_id
    result = probe(
        api_key=os.environ.get(args.api_key_env, ""),
        output_dir=output_dir,
        as_of_date=as_of,
        api_key_env_name=args.api_key_env,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "READY_50_ROW_SCHEMA_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
