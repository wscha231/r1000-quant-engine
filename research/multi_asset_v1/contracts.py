"""Typed, time-aware admission for externally normalized research observations.

Hashes bind bytes, not economic truth. Evaluations and risk decisions additionally
require pins in the separately reviewed policy, never in the input payload.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import re

from research.theme_etf_runtime_v1.strict import ContractError

CLASSES = frozenset("US_EQUITY COMMODITY PRECIOUS_METAL INDUSTRIAL_METAL CRITICAL_MINERAL ENERGY AGRICULTURE FERTILIZER CRYPTO ALTERNATIVE_ASSET COMMODITY_EQUITY CRYPTO_EQUITY ETF".split())
EVENTS = frozenset("DEMAND_POSITIVE DEMAND_NEGATIVE SUPPLY_POSITIVE SUPPLY_NEGATIVE CAPACITY_ADD CAPACITY_DELAY MINE_OUTAGE STRIKE SANCTION EXPORT_BAN EXPORT_QUOTA WAR_CONFLICT SHIPPING_DISRUPTION REGULATION TECH_SUBSTITUTION TECH_DEMAND_ACCELERATION EARNINGS GUIDANCE CONTRACT ORDER M_AND_A SECURITY_INCIDENT CRYPTO_PROTOCOL_EVENT ETF_FLOW MACRO".split())
HORIZONS = (20, 60, 120, 240)
ER_HORIZONS = ("1m", "3m", "6m", "12m")


def require(condition, reason):
    if not condition:
        raise ContractError(reason)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def load_json(raw):
    require(len(raw) <= 64 * 1024 * 1024, "input_size")
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, "duplicate_json_key")
            out[k] = v
        return out
    def invalid(_):
        raise ContractError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def stamp(value):
    require(isinstance(value, str) and value.strip() == value, "timestamp_type")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError("timestamp_format") from None
    require(dt.tzinfo is not None, "timestamp_timezone")
    return dt.astimezone(timezone.utc)


def day(value):
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), "date_format")
    return date.fromisoformat(value)


def number(value, lower=None, upper=None):
    require(type(value) in (int, float) and math.isfinite(value), "finite_number_required")
    require(lower is None or value >= lower, "number_below_bound")
    require(upper is None or value <= upper, "number_above_bound")
    return float(value)


def identifier(value):
    require(isinstance(value, str) and bool(re.fullmatch(r"[A-Z0-9][A-Z0-9:_.-]{0,79}", value)), "canonical_identity_required")
    return value


def unique(rows, key):
    out = {}
    for row in rows:
        ident = identifier(row.get(key))
        require(ident not in out, "duplicate_identity:" + ident)
        out[ident] = row
    return out


def metadata(row, cutoff, policy, kind, *, fresh=True):
    observed, available, collected = [stamp(row.get(k)) for k in
                                      ("observed_at", "available_at", "collected_at")]
    now = stamp(cutoff)
    require(observed <= available <= collected <= now, "future_or_conflicting_time")
    spec = policy["sources"].get(row.get("source"))
    require(spec is not None and kind in spec["kinds"], "unapproved_source")
    require(row.get("data_quality") == "OBSERVED", "invalid_data_quality")
    require(row.get("evidence_kind") in ("FORWARD_CAPTURE", "PIT_ARCHIVE"), "synthetic_or_unknown_evidence")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", row.get("raw_sha256", ""))), "raw_hash_required")
    if fresh:
        require((now-observed).total_seconds() <= spec["max_age_days"] * 86400, "stale_observation")
    return observed, available, collected


def registry_rows(registry):
    require(registry.get("schema") == "multi-asset-registry-v1", "registry_schema")
    underlyings = unique(registry["underlyings"], "underlying_id")
    assets = unique(registry["assets"], "asset_id")
    for row in assets.values():
        for key in ("symbol", "subclass", "vehicle_type", "exchange", "currency", "benchmark", "pricing_source", "fundamental_source"):
            require(isinstance(row.get(key), str) and bool(row[key]), "missing_metadata:"+key)
        require(row.get("asset_class") in CLASSES, "asset_class")
        require(row["currency"] == "USD", "v1_requires_usd")
        expected_unit="USD_PER_TOKEN" if row["vehicle_type"]=="SPOT" else "USD_PER_SHARE"
        require(row.get("price_unit")==expected_unit,"vehicle_price_unit")
        require(row["underlying"] is None or row["underlying"] in underlyings, "unknown_underlying")
        require(type(row.get("tradable")) is bool and type(row.get("research_only")) is bool, "boolean_metadata")
        require(type(row.get("identity_verified")) is bool and type(row.get("corporate_action_quarantine")) is bool,"boolean_identity_metadata")
        require(row["research_only"] is True, "research_only_required")
        for key in ("news_keywords", "theme_ids", "risk_group_ids"):
            require(isinstance(row.get(key), list) and all(isinstance(x, str) and x for x in row[key]), "list_metadata:"+key)
        require("liquidity" in row, "liquidity_metadata")
    return underlyings, assets


def pinned(row, policy, kind, cutoff):
    require(digest(row) in policy["reviewed_pins"].get(kind, []), "unreviewed_"+kind)
    metadata(row, cutoff, policy, kind)
    return row


def current_a3_profile(policy, binding, feature_hash, risk, cutoff, code_sha):
    """An opt-in, externally pinned policy authenticates the complete review.

    Omit only the profile from its policy identity to avoid a self-hash cycle.
    This does not certify historical PIT, Source admission or account authority.
    """
    profile=policy.get("current_a3_review_profile")
    fields={"schema","purpose","context_sha256","graph_sha256","binding_sha256","policy_base_sha256",
            "feature_sha256","risk_sha256","code_sha","available_at","expires_at","principals"}
    require(type(profile) is dict and set(profile)==fields,"a3_current_review_profile_required")
    require(profile["schema"]=="current-a3-review-profile-v1" and
            profile["purpose"]=="CURRENT_RESEARCH_FORWARD_ONLY","a3_current_review_purpose")
    require(type(binding) is dict and set(binding)=={"portfolio_context","review_graph"},
            "a3_current_review_binding")
    require(all(type(value) is dict for value in binding.values()),"a3_current_review_binding")
    for key in ("context_sha256","graph_sha256","binding_sha256","policy_base_sha256","feature_sha256","risk_sha256"):
        require(type(profile[key]) is str and re.fullmatch(r"[0-9a-f]{64}",profile[key]) is not None,
                "a3_current_review_hash")
    require(type(code_sha) is str and re.fullmatch(r"[0-9a-f]{40}",code_sha) is not None
            and profile["code_sha"]==code_sha,"a3_current_review_code")
    require(profile["policy_base_sha256"]==digest({k:v for k,v in policy.items()
            if k!="current_a3_review_profile"}),"a3_current_review_policy_changed")
    require(profile["context_sha256"]==binding["portfolio_context"].get("sha256") and
            profile["graph_sha256"]==binding["review_graph"].get("sha256") and
            profile["binding_sha256"]==digest(binding),"a3_current_review_pin")
    require(profile["feature_sha256"]==feature_hash and risk is not None and
            profile["risk_sha256"]==digest(risk),"a3_current_review_feature_or_risk")
    require(type(profile["available_at"]) is str and type(profile["expires_at"]) is str,
            "a3_current_review_clock_type")
    require(stamp(profile["available_at"])<=stamp(cutoff)<stamp(profile["expires_at"]),
            "a3_current_review_expired_or_future")
    principals=profile["principals"]
    require(type(principals) is dict and set(principals)=={"A0","A3","A6"},
            "a3_current_review_principals")
    for value in principals.values(): identifier(value)
    require(principals["A6"] not in {principals["A0"],principals["A3"]},
            "a3_current_review_not_independent")
    return profile
