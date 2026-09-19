"""Pure research-only adapter from verified source envelopes to a candidate packet.

No network, selector, target, order, broker, paper-ledger, scheduler, or durable-state writes.
"""
from __future__ import annotations
import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA = "candidate-packet-source-bundle-v1"
PACKET_SCHEMA = "research-candidate-packet-v1"
ADMITTED_SOURCE_STATUS = {"VERIFIED"}
FORBIDDEN_KEYS = {
    "order", "orders", "order_qty", "broker_action", "live_order",
    "target_weight", "approved_target_weight", "trade_authority",
    "buy_signal", "sell_signal",
}
SECTIONS = {
    "universe": "universe",
    "industry": "industry",
    "leadership": "leadership",
    "fundamentals": "fundamentals",
    "thesis": "thesis",
    "valuation": "valuation",
    "expected_return": "expected_return",
    "information_evidence": "information_evidence",
    "macro": "macro",
    "commodity": "commodity",
}

class ContractError(ValueError):
    pass

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContractError(reason)

def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def timestamp(value: str) -> datetime:
    require(isinstance(value, str) and value == value.strip() and value, "TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError("INVALID_TIMESTAMP") from None
    require(dt.tzinfo is not None, "TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)

def assert_no_authority(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            norm = str(key).strip().lower()
            require(norm not in FORBIDDEN_KEYS, f"FORBIDDEN_AUTHORITY_FIELD:{path}.{key}")
            assert_no_authority(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            assert_no_authority(child, f"{path}[{idx}]")

def validate_identity(identity: dict[str, Any]) -> dict[str, Any]:
    required = ("security_id", "issuer_id", "ticker", "market", "currency", "security_type")
    require(isinstance(identity, dict), "IDENTITY_REQUIRED")
    for key in required:
        require(isinstance(identity.get(key), str) and identity[key].strip(), f"IDENTITY_{key.upper()}_REQUIRED")
    require(identity["market"] in {"US", "KR"}, "UNSUPPORTED_MARKET")
    require((identity["market"], identity["currency"]) in {("US", "USD"), ("KR", "KRW")},
            "MARKET_CURRENCY_MISMATCH")
    assert_no_authority(identity, "$.identity")
    return copy.deepcopy(identity)

def validate_source(name: str, source: dict[str, Any], cutoff: datetime) -> tuple[bool, str]:
    if not isinstance(source, dict):
        return False, "SOURCE_MISSING"
    status = source.get("status")
    if status not in ADMITTED_SOURCE_STATUS:
        return False, f"SOURCE_{status or 'MISSING'}"
    try:
        available = timestamp(source["available_at"])
        observed = timestamp(source["observed_at"])
        collected = timestamp(source["collected_at"])
    except (KeyError, ContractError):
        return False, "SOURCE_TIME_INVALID"
    if available > cutoff or observed > cutoff:
        return False, "SOURCE_FUTURE"
    if observed > collected:
        return False, "SOURCE_OBSERVED_AFTER_COLLECTION"
    payload = source.get("payload")
    if not isinstance(payload, dict):
        return False, "SOURCE_PAYLOAD_INVALID"
    expected = source.get("data_hash")
    if not isinstance(expected, str) or len(expected) != 64 or digest(payload) != expected:
        return False, "SOURCE_HASH_MISMATCH"
    try:
        assert_no_authority(payload, f"$.sources.{name}.payload")
    except ContractError as exc:
        return False, str(exc)
    return True, ""

def build_packet(bundle: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(bundle, dict) and bundle.get("schema_version") == SCHEMA, "BUNDLE_SCHEMA")
    cutoff = timestamp(bundle.get("decision_cutoff"))
    identity = validate_identity(bundle.get("identity"))
    sources = bundle.get("sources")
    require(isinstance(sources, dict), "SOURCES_REQUIRED")

    packet = {
        "schema_version": PACKET_SCHEMA,
        "identity": identity,
        "universe": {"membership_reasons": [], "candidate_status": "BLOCKED_SOURCE_EVIDENCE"},
        "industry": {},
        "leadership": {},
        "fundamentals": {},
        "thesis": {},
        "valuation": {},
        "expected_return": {
            "h1m": None, "h3m": None, "h6m": None, "h12m": None,
            "benchmark_excess": None, "downside_probability": None,
            "confidence": None, "status": "INCOMPLETE_SOURCE_EVIDENCE",
        },
        "information_evidence": {},
        "macro": {},
        "commodity": {"asset_sleeve": "equity"},
        "provenance": {
            "as_of": bundle["decision_cutoff"],
            "available_at": bundle["decision_cutoff"],
            "source_commit": bundle.get("source_commit") or "",
            "data_hash": "",
            "config_hash": bundle.get("config_hash") or "",
            "pit_status": "PARTIAL",
            "missing_reasons": [],
            "source_status": {},
        },
        "authority": {"research_only": True, "target_authority": False, "order_authority": False},
    }

    for source_name, target_section in SECTIONS.items():
        source = sources.get(source_name)
        ok, reason = validate_source(source_name, source, cutoff)
        packet["provenance"]["source_status"][source_name] = "VERIFIED" if ok else reason
        if not ok:
            packet["provenance"]["missing_reasons"].append(f"{source_name}:{reason}")
            continue
        payload = copy.deepcopy(source["payload"])
        if target_section == "expected_return":
            for key in ("h1m","h3m","h6m","h12m","benchmark_excess",
                        "downside_probability","confidence","status"):
                if key in payload:
                    packet[target_section][key] = payload[key]
        else:
            packet[target_section] = payload

    required_for_complete = ("universe", "fundamentals", "thesis", "valuation", "expected_return")
    complete = all(packet["provenance"]["source_status"].get(name) == "VERIFIED"
                   for name in required_for_complete)
    packet["provenance"]["pit_status"] = "VERIFIED_INPUT_SET" if complete else "PARTIAL"
    if packet["provenance"]["source_status"].get("universe") == "VERIFIED":
        packet["universe"].setdefault("membership_reasons", [])
        packet["universe"].setdefault("candidate_status", "WATCH")
    assert_no_authority(packet)
    semantic = copy.deepcopy(packet)
    semantic["provenance"]["data_hash"] = ""
    packet["provenance"]["data_hash"] = digest(semantic)
    packet["packet_hash"] = digest(packet)
    return packet
