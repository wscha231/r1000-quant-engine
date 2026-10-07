#!/usr/bin/env python3
"""Deterministic B5 product-analytics aggregation for consented v1 events.

This module is deliberately offline: it does not collect events, call a network,
or create persistent browser identifiers. It validates already-captured event
fixtures/exports against the frozen B6 privacy contract and produces only
session/day aggregates. D1/D7/D30 user retention remains NOT_AVAILABLE in v1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "data_static" / "product_analytics_event_contract_v1.json"
KST = ZoneInfo("Asia/Seoul")
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
ENTITY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MAX_EVENT_INPUT_BYTES = 16 * 1024 * 1024
MAX_CONTRACT_BYTES = 256 * 1024
MAX_EVENTS = 100_000
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 2_000_000

FROZEN_CONTRACT_KEYS = {
    "schema_version", "status", "event_schema_version", "event_version",
    "collector_endpoint", "transmission_enabled", "consent", "identity",
    "retention", "allowed_event_names", "required_fields", "optional_fields",
    "forbidden_fields", "allowed_pages", "allowed_surfaces",
    "allowed_entity_types", "allowed_markets", "allowed_data_states",
    "qualified_value_session", "primary_kpi", "privacy",
}
FROZEN_REQUIRED_FIELDS = {
    "schema_version", "event_name", "event_version", "event_id",
    "occurred_at_utc", "received_at_utc", "session_id", "consent_status",
    "consent_version", "page", "surface", "data_state",
    "public_artifact_version", "is_internal", "is_bot",
}
FROZEN_OPTIONAL_FIELDS = {"entity_type", "entity_id", "market"}
FROZEN_FORBIDDEN_FIELDS = {
    "anonymous_id", "user_id", "email", "phone", "name", "ip", "ip_address",
    "user_agent", "referrer", "referrer_url", "search_query", "free_text",
    "broker_id", "account_id", "account_value", "position_quantity", "pnl",
    "clipboard", "keystrokes", "mouse_path", "session_replay",
}


class ContractError(ValueError):
    pass


def _read_bounded_utf8(path: Path, byte_limit: int, label: str) -> str:
    with path.open("rb") as handle:
        raw = handle.read(byte_limit + 1)
    if len(raw) > byte_limit:
        raise ContractError(f"{label}_byte_limit")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{label}_invalid_utf8") from exc


def _validate_json_shape(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ContractError("json_node_limit")
        if depth > MAX_JSON_DEPTH:
            raise ContractError("json_depth_limit")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _string_set(value: Any, reason: str) -> set[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ContractError(reason)
    return set(value)


def strict_json_loads(raw: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ContractError(f"duplicate_json_key:{key}")
            out[key] = value
        return out

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ContractError(f"invalid_json_constant:{value}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid_json:{exc.msg}") from exc
    except RecursionError as exc:
        raise ContractError("json_depth_limit") from exc
    _validate_json_shape(value)
    return value


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError(f"{field}_must_be_utc_z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ContractError(f"{field}_must_be_utc")
    return parsed.astimezone(timezone.utc)


def load_contract(path: Path) -> dict[str, Any]:
    payload = strict_json_loads(
        _read_bounded_utf8(path, MAX_CONTRACT_BYTES, "contract")
    )
    if not isinstance(payload, dict):
        raise ContractError("contract_not_object")
    if set(payload) != FROZEN_CONTRACT_KEYS:
        raise ContractError("contract_fields_mismatch")
    if payload.get("schema_version") != "b5-product-analytics-contract-v1":
        raise ContractError("unexpected_contract_schema")
    if payload.get("status") != "PREPARED_NOT_TRANSMITTING":
        raise ContractError("unexpected_contract_status")
    if payload.get("event_schema_version") != "b5-product-analytics-event-v1":
        raise ContractError("event_schema_contract_mismatch")
    if (
        payload.get("event_version") != 1
        or isinstance(payload.get("event_version"), bool)
    ):
        raise ContractError("event_version_contract_mismatch")
    if (
        payload.get("transmission_enabled") is not False
        or payload.get("collector_endpoint") is not None
    ):
        raise ContractError("v1_transmission_must_remain_disabled")
    consent = payload.get("consent")
    if consent != {"required": True, "required_status": "ACTIVE", "consent_version": "b6-analytics-consent-v1"}:
        raise ContractError("consent_contract_mismatch")
    identity = payload.get("identity")
    if identity != {"persistent_anonymous_id_allowed": False, "preauth_session_id_only": True, "session_timeout_seconds": 1800, "user_id_allowed": False}:
        if isinstance(identity, dict) and identity.get("user_id_allowed") is not False:
            raise ContractError("user_id_must_remain_disabled")
        raise ContractError("identity_contract_mismatch")
    if payload.get("retention") != {"raw_event_days_max": 90, "identifier_free_aggregate_months_max": 13}:
        raise ContractError("retention_contract_mismatch")
    if _string_set(payload.get("required_fields"), "required_field_contract_mismatch") != FROZEN_REQUIRED_FIELDS:
        raise ContractError("required_field_contract_mismatch")
    if _string_set(payload.get("optional_fields"), "optional_field_contract_mismatch") != FROZEN_OPTIONAL_FIELDS:
        raise ContractError("optional_field_contract_mismatch")
    forbidden = _string_set(payload.get("forbidden_fields"), "forbidden_field_contract_mismatch")
    if not FROZEN_FORBIDDEN_FIELDS.issubset(forbidden):
        raise ContractError("forbidden_field_contract_mismatch")
    if _string_set(payload.get("allowed_event_names"), "event_name_contract_mismatch") != {"site_viewed", "research_search_succeeded", "research_source_opened", "trade_ledger_opened"}:
        raise ContractError("event_name_contract_mismatch")
    if _string_set(payload.get("allowed_pages"), "page_contract_mismatch") != {"home"}:
        raise ContractError("page_contract_mismatch")
    if _string_set(payload.get("allowed_surfaces"), "surface_contract_mismatch") != {"site", "research_results", "research_source", "trade_ledger"}:
        raise ContractError("surface_contract_mismatch")
    if _string_set(payload.get("allowed_entity_types"), "entity_type_contract_mismatch") != {"ticker", "source", "portfolio"}:
        raise ContractError("entity_type_contract_mismatch")
    if _string_set(payload.get("allowed_markets"), "market_contract_mismatch") != {"US", "KR", "MULTI"}:
        raise ContractError("market_contract_mismatch")
    if _string_set(payload.get("allowed_data_states"), "data_state_contract_mismatch") != {"USABLE", "STALE_PORTFOLIO", "RESEARCH_DEGRADED", "DATA_INCOMPLETE", "BLOCKED"}:
        raise ContractError("data_state_contract_mismatch")
    if payload.get("qualified_value_session") != {"required_data_state": "USABLE", "requires_all": ["research_search_succeeded"], "requires_any": ["research_source_opened", "trade_ledger_opened"]}:
        raise ContractError("qualified_value_contract_mismatch")
    if payload.get("primary_kpi") != {"name": "activated_user_d7_qualified_retention", "status": "NOT_AVAILABLE", "reason": "NO_PERSISTENT_USER_ID_OR_SIGNUP_IN_V1"}:
        raise ContractError("primary_kpi_contract_mismatch")
    if payload.get("privacy") != {"autocapture": False, "session_replay": False, "ad_tracking": False, "cross_site_tracking": False, "raw_ip_storage": False, "public_github_raw_events": False}:
        raise ContractError("privacy_contract_mismatch")
    return payload


def read_events(path: Path) -> list[dict[str, Any]]:
    raw = _read_bounded_utf8(path, MAX_EVENT_INPUT_BYTES, "events")
    stripped = raw.lstrip()
    if not stripped:
        return []
    if stripped.startswith("["):
        payload = strict_json_loads(raw)
        if not isinstance(payload, list):
            raise ContractError("events_not_list")
        rows = payload
    else:
        rows = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            item = strict_json_loads(line)
            if not isinstance(item, dict):
                raise ContractError(f"event_line_not_object:{number}")
            rows.append(item)
            if len(rows) > MAX_EVENTS:
                raise ContractError("event_count_limit")
    if len(rows) > MAX_EVENTS:
        raise ContractError("event_count_limit")
    if not all(isinstance(row, dict) for row in rows):
        raise ContractError("event_not_object")
    return rows


def canonical_bytes(event: dict[str, Any]) -> bytes:
    return json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_event(
    event: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    required = set(contract["required_fields"])
    optional = set(contract["optional_fields"])
    allowed = required | optional
    keys = set(event)
    missing = sorted(required - keys)
    unknown = sorted(keys - allowed)
    if missing:
        raise ContractError("missing_fields:" + ",".join(missing))
    if unknown:
        raise ContractError("unknown_fields:" + ",".join(unknown))
    forbidden = sorted(keys & set(contract["forbidden_fields"]))
    if forbidden:
        raise ContractError("forbidden_fields:" + ",".join(forbidden))

    if event["schema_version"] != contract["event_schema_version"]:
        raise ContractError("event_schema_mismatch")
    if (
        event["event_version"] != contract["event_version"]
        or isinstance(event["event_version"], bool)
    ):
        raise ContractError("event_version_mismatch")
    if event["event_name"] not in contract["allowed_event_names"]:
        raise ContractError("event_name_not_allowed")
    if (
        not isinstance(event["event_id"], str)
        or not ID_RE.fullmatch(event["event_id"])
    ):
        raise ContractError("invalid_event_id")
    if (
        not isinstance(event["session_id"], str)
        or not ID_RE.fullmatch(event["session_id"])
    ):
        raise ContractError("invalid_session_id")
    if event["consent_status"] != contract["consent"]["required_status"]:
        raise ContractError("analytics_consent_not_active")
    if event["consent_version"] != contract["consent"]["consent_version"]:
        raise ContractError("consent_version_mismatch")
    if event["page"] not in contract["allowed_pages"]:
        raise ContractError("page_not_allowed")
    if event["surface"] not in contract["allowed_surfaces"]:
        raise ContractError("surface_not_allowed")
    if event["data_state"] not in contract["allowed_data_states"]:
        raise ContractError("data_state_not_allowed")
    if (
        not isinstance(event["public_artifact_version"], str)
        or not ID_RE.fullmatch(event["public_artifact_version"])
    ):
        raise ContractError("invalid_public_artifact_version")
    if not isinstance(event["is_internal"], bool) or not isinstance(
        event["is_bot"], bool
    ):
        raise ContractError("traffic_flags_must_be_boolean")

    entity_type = event.get("entity_type")
    entity_id = event.get("entity_id")
    market = event.get("market")
    if entity_type is None and entity_id is not None:
        raise ContractError("entity_id_without_type")
    if (
        entity_type is not None
        and entity_type not in contract["allowed_entity_types"]
    ):
        raise ContractError("entity_type_not_allowed")
    if entity_id is not None and (
        not isinstance(entity_id, str)
        or not ENTITY_RE.fullmatch(entity_id)
    ):
        raise ContractError("invalid_entity_id")
    if market is not None and market not in contract["allowed_markets"]:
        raise ContractError("market_not_allowed")

    occurred = parse_utc(event["occurred_at_utc"], "occurred_at_utc")
    received = parse_utc(event["received_at_utc"], "received_at_utc")
    if received < occurred:
        raise ContractError("received_before_occurred")

    normalized = dict(event)
    normalized["_occurred"] = occurred
    normalized["_received"] = received
    return normalized


def dedupe_events(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    by_id: dict[str, tuple[bytes, dict[str, Any]]] = {}
    duplicate_count = 0
    for event in events:
        public = {
            key: value
            for key, value in event.items()
            if not key.startswith("_")
        }
        digest = canonical_bytes(public)
        prior = by_id.get(event["event_id"])
        if prior is None:
            by_id[event["event_id"]] = (digest, event)
            continue
        if prior[0] != digest:
            raise ContractError(
                f"conflicting_duplicate_event_id:{event['event_id']}"
            )
        duplicate_count += 1
    rows = [value[1] for value in by_id.values()]
    rows.sort(
        key=lambda row: (
            row["_occurred"],
            row["_received"],
            row["event_id"],
        )
    )
    return rows, duplicate_count


def segment_sessions(
    events: list[dict[str, Any]],
    timeout_seconds: int,
) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(event["session_id"], []).append(event)
    result: list[tuple[str, list[dict[str, Any]]]] = []
    timeout = timedelta(seconds=timeout_seconds)
    for session_id in sorted(grouped):
        rows = sorted(
            grouped[session_id],
            key=lambda row: (row["_occurred"], row["event_id"]),
        )
        segment: list[dict[str, Any]] = []
        segment_index = 0
        previous: datetime | None = None
        for row in rows:
            if (
                previous is not None
                and row["_occurred"] - previous > timeout
            ):
                result.append(
                    (f"{session_id}:{segment_index}", segment)
                )
                segment_index += 1
                segment = []
            segment.append(row)
            previous = row["_occurred"]
        if segment:
            result.append((f"{session_id}:{segment_index}", segment))
    result.sort(key=lambda item: (item[1][0]["_occurred"], item[0]))
    return result


def session_day(rows: list[dict[str, Any]]) -> str:
    return rows[0]["_occurred"].astimezone(KST).date().isoformat()


def qualified_value(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
) -> bool:
    rule = contract["qualified_value_session"]
    if any(row["data_state"] != rule["required_data_state"] for row in rows):
        return False
    names = {row["event_name"] for row in rows}
    return all(name in names for name in rule["requires_all"]) and any(
        name in names for name in rule["requires_any"]
    )


def aggregate(
    events: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    validated = [validate_event(row, contract) for row in events]
    deduped, duplicate_count = dedupe_events(validated)
    excluded_internal = sum(
        1 for row in deduped if row["is_internal"]
    )
    excluded_bot = sum(
        1
        for row in deduped
        if row["is_bot"] and not row["is_internal"]
    )
    eligible_events = [
        row
        for row in deduped
        if not row["is_internal"] and not row["is_bot"]
    ]
    segments = segment_sessions(
        eligible_events,
        int(contract["identity"]["session_timeout_seconds"]),
    )

    by_day: dict[str, dict[str, int]] = {}
    for _key, rows in segments:
        day = session_day(rows)
        stats = by_day.setdefault(
            day,
            {
                "sessions": 0,
                "usable_sessions": 0,
                "degraded_sessions": 0,
                "qualified_value_sessions": 0,
            },
        )
        stats["sessions"] += 1
        states = {row["data_state"] for row in rows}
        if states == {"USABLE"}:
            stats["usable_sessions"] += 1
        else:
            stats["degraded_sessions"] += 1
        if qualified_value(rows, contract):
            stats["qualified_value_sessions"] += 1

    daily = []
    for day in sorted(by_day):
        stats = by_day[day]
        denominator = stats["usable_sessions"]
        rate = (
            stats["qualified_value_sessions"] / denominator
            if denominator
            else None
        )
        daily.append(
            {
                "date_kst": day,
                **stats,
                "anonymous_qualified_value_session_rate": rate,
            }
        )

    source_digest = hashlib.sha256(
        b"\n".join(
            canonical_bytes(
                {
                    key: value
                    for key, value in row.items()
                    if not key.startswith("_")
                }
            )
            for row in deduped
        )
    ).hexdigest()
    return {
        "schema_version": "b5-product-analytics-daily-v1",
        "contract_schema_version": contract["schema_version"],
        "status": "NO_EVENTS" if not deduped else "AGGREGATED_OFFLINE",
        "transmission_enabled": False,
        "source_event_count": len(events),
        "unique_event_count": len(deduped),
        "duplicate_event_count": duplicate_count,
        "excluded_internal_event_count": excluded_internal,
        "excluded_bot_event_count": excluded_bot,
        "eligible_event_count": len(eligible_events),
        "session_count": len(segments),
        "source_event_digest_sha256": source_digest,
        "primary_kpi": contract["primary_kpi"],
        "retention": {
            "d1_qualified_retention": {
                "status": "NOT_AVAILABLE",
                "reason": "NO_PERSISTENT_USER_ID_OR_SIGNUP_IN_V1",
            },
            "d7_qualified_retention": {
                "status": "NOT_AVAILABLE",
                "reason": "NO_PERSISTENT_USER_ID_OR_SIGNUP_IN_V1",
            },
            "d30_qualified_retention": {
                "status": "NOT_AVAILABLE",
                "reason": "NO_PERSISTENT_USER_ID_OR_SIGNUP_IN_V1",
            },
        },
        "daily": daily,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    contract = load_contract(args.contract)
    result = aggregate(read_events(args.events), contract)
    encoded = (
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
