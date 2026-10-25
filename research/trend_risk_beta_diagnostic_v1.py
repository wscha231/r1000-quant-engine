"""Two-axis market trend/stress diagnostic, RESEARCH_ONLY.

A standalone companion to existing A4 Chameleon/current crisis context.
Inputs are pre-normalized independently sourced diagnostic observations.
This is NOT the source video's unreleased proprietary Beta formula; weights
and boundary are fixed illustrative research definitions only. It does not
call A5, change regime, produce cash percentages, or authorize a trade.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any, Callable

SCHEMA = "trend-risk-two-axis-diagnostic-v1"
RESULT_SCHEMA = "trend-risk-two-axis-diagnostic-result-v1"
TREND_NAMES = (
    "ma_21_trend", "ma_63_trend", "ma_126_trend", "drawdown_252_trend",
    "global_relative_trend", "breadth_trend",
)
RISK_NAMES = (
    "vix_stress", "realized_vol_stress", "down_volume_stress",
    "fx_shock_stress", "rate_shock_stress", "credit_stress",
)
ALL_NAMES = TREND_NAMES + RISK_NAMES
REQUIRED_TREND = frozenset(TREND_NAMES)
REQUIRED_RISK_FAMILIES = ("volatility", "distribution", "macro_shock", "credit")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_RAW = 1_048_576
_MAX_TOTAL = 8 * _MAX_RAW
RawResolver = Callable[[str, str], bytes]


class TwoAxisDiagnosticError(ValueError):
    """Invalid research metric or input provenance."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise TwoAxisDiagnosticError(reason)


def text(value: Any, code: str, length: int = 200) -> str:
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= length, code)
    return value.strip()


def ident(value: Any, code: str) -> str:
    value = text(value, code, 200)
    require(bool(_ID.fullmatch(value)), code)
    return value


def stamp(value: Any, code: str) -> datetime:
    value = text(value, code, 50)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise TwoAxisDiagnosticError(code) from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed.astimezone(timezone.utc)


def day(value: Any, code: str) -> date:
    value = text(value, code, 10)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise TwoAxisDiagnosticError(code) from exc
    require(parsed.isoformat() == value, code)
    return parsed


def score(value: Any, *, trend: bool) -> float:
    require(type(value) in (int, float), "normalized_score_type")
    v = float(value)
    require(math.isfinite(v) and (-1 <= v <= 1 if trend else 0 <= v <= 1),
            "normalized_score_range")
    return v


def sha_object(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def normalize_raw_research_inputs(raw: dict[str, Any], scales: dict[str, Any]) -> dict[str, float]:
    """Pure candidate transformation; provenance/admission belongs to its caller.

    These are EXPLICIT, fixed, never fitted scales supplied by a study manifest.
    The caller must bind the resulting values to verified source and calculation
    receipts before building evaluate() observations. Omitted inputs stay omitted.
    No normalization here yields a current/approved investment signal.
    """
    require(type(raw) is dict and type(scales) is dict, "normalizer_input")
    require(set(scales) == {"ma_ratio_saturation", "drawdown_depth_fraction",
                             "global_rs_log_saturation"}, "normalizer_scales")
    for name in scales:
        val = scales[name]
        require(type(val) in (float, int) and math.isfinite(float(val)) and
                0 < float(val) <= 1, "normalizer_scale_range")
    def number_or_none(key: str) -> float | None:
        val = raw.get(key)
        if val is None:
            return None
        require(type(val) in (int, float) and math.isfinite(float(val)),
                "raw_normalizer_value")
        return float(val)
    def clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
        return float(max(lo, min(hi, value)))
    out: dict[str, float] = {}
    for window in (21, 63, 126):
        ratio = number_or_none(f"price_to_ma{window}_ratio")
        if ratio is not None:
            require(ratio > 0, "nonpositive_ma_ratio")
            out[f"ma_{window}_trend"] = clip((ratio - 1.0) / float(scales["ma_ratio_saturation"]))
    dd = number_or_none("drawdown_252_fraction")
    if dd is not None:
        require(-1 <= dd <= 0, "drawdown_fraction_range")
        out["drawdown_252_trend"] = clip(1.0 + 2.0 * dd / float(scales["drawdown_depth_fraction"]))
    rs = number_or_none("global_relative_log_return_63")
    if rs is not None:
        out["global_relative_trend"] = clip(rs / float(scales["global_rs_log_saturation"]))
    breadth = number_or_none("breadth_fraction_above_ma200")
    if breadth is not None:
        require(0 <= breadth <= 1, "breadth_fraction_range")
        out["breadth_trend"] = 2.0 * breadth - 1.0
    down = number_or_none("down_volume_fraction")
    if down is not None:
        require(0 <= down <= 1, "down_volume_fraction_range")
        out["down_volume_stress"] = clip(2.0 * (down - 0.5), 0.0, 1.0)
    mapping = {
        "vix_stress_percentile": "vix_stress",
        "realized_vol_stress_percentile": "realized_vol_stress",
        "fx_shock_stress_percentile": "fx_shock_stress",
        "rate_shock_stress_percentile": "rate_shock_stress",
        "credit_stress_percentile": "credit_stress",
    }
    for raw_name, out_name in mapping.items():
        v = number_or_none(raw_name)
        if v is not None:
            require(0 <= v <= 1, "percentile_range")
            out[out_name] = v
    return out


def evaluate(packet: dict[str, Any], cutoff: str, raw_resolver: RawResolver) -> dict[str, Any]:
    require(type(packet) is dict and callable(raw_resolver), "packet_or_resolver")
    require(packet.get("schema") == SCHEMA, "schema")
    require(packet.get("normalization_method") == "FIXED_PREREGISTERED_INPUT_SCORES",
            "normalization_method")
    norm_version = ident(packet.get("normalization_version"), "normalization_version")
    normalize_digest = packet.get("normalization_config_sha256")
    require(isinstance(normalize_digest, str) and bool(_HASH.fullmatch(normalize_digest)),
            "normalization_config_sha256")
    market = text(packet.get("market_id"), "market_id", 80)
    benchmark = ident(packet.get("benchmark_id"), "benchmark_id")
    as_of = stamp(packet.get("as_of"), "as_of")
    trusted_cutoff = stamp(cutoff, "trusted_cutoff")
    require(as_of <= trusted_cutoff, "future_packet")
    session = day(packet.get("session_date"), "session_date")
    require(session <= as_of.date(), "future_session")
    require(packet.get("review_status") == "RESEARCH_CONTEXT_REVIEWED", "review_status")
    obs = packet.get("observations")
    require(type(obs) is dict and set(obs).issubset(ALL_NAMES), "observation_names")

    cache: dict[tuple[str, str], bytes] = {}
    names_by_artifact: dict[str, str] = {}
    used = 0
    admitted: dict[str, float] = {}
    missing: list[str] = []
    source_groups: dict[str, str] = {}
    input_hashes: dict[str, str] = {}
    for name in ALL_NAMES:
        row = obs.get(name)
        if row is None:
            missing.append(name)
            continue
        require(type(row) is dict, "observation_object")
        val = score(row.get("normalized_value"), trend=name in TREND_NAMES)
        require(row.get("normalized_basis") == norm_version, "normalization_version_mismatch")
        require(row.get("metric_name") == name, "metric_name_mismatch")
        require(row.get("benchmark_id") == benchmark, "benchmark_identity_mismatch")
        require(row.get("market_id") == market, "market_identity_mismatch")
        observed = stamp(row.get("observed_at"), "observed_at")
        available = stamp(row.get("available_at"), "available_at")
        collected = stamp(row.get("collected_at"), "collected_at")
        valid_through = stamp(row.get("valid_through"), "valid_through")
        require(observed <= available <= collected <= as_of <= valid_through,
                "observation_clock_or_expiry")
        require(day(row.get("observation_date"), "observation_date") <= session,
                "future_observation_session")
        require(row.get("quality") == "REVIEWED_OBSERVED", "unreviewed_observation")
        family = ident(row.get("source_family"), "source_family")
        raw_id = ident(row.get("artifact_id"), "artifact_id")
        digest = row.get("sha256")
        require(isinstance(digest, str) and bool(_HASH.fullmatch(digest)), "observation_sha256")
        require(raw_id not in names_by_artifact or names_by_artifact[raw_id] == digest,
                "artifact_identity_conflict")
        names_by_artifact[raw_id] = digest
        key = (raw_id, digest)
        if key not in cache:
            try:
                data = raw_resolver(raw_id, digest)
            except Exception as exc:
                raise TwoAxisDiagnosticError("observation_raw_unavailable") from exc
            require(type(data) is bytes and 0 < len(data) <= _MAX_RAW,
                    "observation_raw_size")
            used += len(data)
            require(used <= _MAX_TOTAL, "raw_budget_exceeded")
            require(hashlib.sha256(data).hexdigest() == digest, "observation_raw_hash")
            cache[key] = data
        if name == "breadth_trend":
            denom = row.get("eligible_universe_count")
            valid = row.get("valid_member_count")
            require(type(denom) is int and type(valid) is int and
                    denom > 0 and 0 < valid <= denom, "breadth_denominator")
            require(row.get("cohort_coverage") == "COMPLETE_REVIEWED",
                    "breadth_scope_incomplete")
        admitted[name] = val
        source_groups[name] = family
        input_hashes[name] = digest

    trend_value: float | None = None
    risk_value: float | None = None
    risk_families: dict[str, float | None] = {}
    if REQUIRED_TREND.issubset(admitted):
        ma = sum(admitted[f"ma_{h}_trend"] for h in (21, 63, 126)) / 3.0
        trend_value = (ma + admitted["drawdown_252_trend"] +
                       admitted["global_relative_trend"] + admitted["breadth_trend"]) / 4.0
        trend_value = max(-1.0, min(1.0, trend_value))

    risk_families["volatility"] = max(
        (admitted[x] for x in ("vix_stress", "realized_vol_stress") if x in admitted),
        default=None,
    )
    risk_families["distribution"] = admitted.get("down_volume_stress")
    risk_families["macro_shock"] = max(
        (admitted[x] for x in ("fx_shock_stress", "rate_shock_stress") if x in admitted),
        default=None,
    )
    risk_families["credit"] = admitted.get("credit_stress")
    if all(risk_families[name] is not None for name in REQUIRED_RISK_FAMILIES):
        risk_value = sum(float(risk_families[name]) for name in REQUIRED_RISK_FAMILIES) / 4.0
        risk_value = max(0.0, min(1.0, risk_value))

    # Quadrants are descriptive only. Borderline values have NO forced classification.
    quadrant = "INSUFFICIENT_INPUT"
    if trend_value is not None and risk_value is not None:
        if abs(trend_value) <= 1e-12 or abs(risk_value - 0.5) <= 1e-12:
            quadrant = "BOUNDARY_REVIEW"
        elif trend_value > 0 and risk_value < 0.5:
            quadrant = "UPTREND_LOW_STRESS"
        elif trend_value > 0 and risk_value > 0.5:
            quadrant = "UPTREND_HIGH_STRESS"
        elif trend_value < 0 and risk_value < 0.5:
            quadrant = "DOWNTREND_LOW_STRESS"
        else:
            quadrant = "DOWNTREND_HIGH_STRESS"

    return {
        "schema": RESULT_SCHEMA,
        "status": "TWO_AXIS_RESEARCH_ONLY" if quadrant != "INSUFFICIENT_INPUT" else
                  "PARTIAL_RESEARCH_CONTEXT",
        "market_id": market, "benchmark_id": benchmark, "as_of": packet["as_of"],
        "session_date": packet["session_date"],
        "normalization_version": norm_version,
        "normalization_config_sha256": normalize_digest,
        "trend_score": trend_value,
        "risk_stress_score": risk_value,
        "risk_families": risk_families,
        "quadrant_diagnostic": quadrant,
        "missing_observations": missing,
        "component_values": admitted,
        "component_raw_hashes": input_hashes,
        "component_source_groups": source_groups,
        "packet_sha256": sha_object(packet),
        "source_raw_artifact_count": len(cache),
        "calibrated_drawdown_probability": None,
        "cash_weight_proposal": None,
        "gross_exposure_cap": None,
        "policy_action": None,
        "source_authenticated": False,
        "normalization_calibrated_oos": False,
        "historical_pit_certified": False,
        "regime_authorized": False,
        "selector_eligible": False,
        "portfolio_weight_effect": 0.0,
        "target_book_write_allowed": False,
        "orders_allowed": False,
        "production_authority": False,
        "research_only": True,
    }


def compare_snapshots(earlier: dict[str, Any], later: dict[str, Any]) -> dict[str, Any]:
    """Compare two already-reviewed local outputs; not an authenticated history."""
    require(type(earlier) is dict and type(later) is dict, "comparison_inputs")
    for row in (earlier, later):
        require(row.get("schema") == RESULT_SCHEMA and row.get("research_only") is True
                and row.get("policy_action") is None and row.get("regime_authorized") is False,
                "comparison_result_identity")
        require(isinstance(row.get("packet_sha256"), str) and
                bool(_HASH.fullmatch(row["packet_sha256"])), "comparison_packet_digest")
        require(type(row.get("trend_score")) in (int, float) and
                type(row.get("risk_stress_score")) in (int, float),
                "comparison_incomplete")
    require(earlier["market_id"] == later["market_id"] and
            earlier["benchmark_id"] == later["benchmark_id"] and
            earlier["normalization_version"] == later["normalization_version"] and
            earlier["normalization_config_sha256"] == later["normalization_config_sha256"],
            "comparison_context_drift")
    require(stamp(earlier.get("as_of"), "earlier_as_of") <
            stamp(later.get("as_of"), "later_as_of") and
            day(earlier.get("session_date"), "earlier_session") <
            day(later.get("session_date"), "later_session"), "comparison_time_order")
    tr0 = score(earlier["trend_score"], trend=True)
    tr1 = score(later["trend_score"], trend=True)
    r0 = score(earlier["risk_stress_score"], trend=False)
    r1 = score(later["risk_stress_score"], trend=False)
    return {
        "trend_change": tr1 - tr0,
        "risk_change": r1 - r0,
        "risk_acceleration": None,  # requires third authenticated, ordered observation
        "old_quadrant": earlier.get("quadrant_diagnostic"),
        "new_quadrant": later.get("quadrant_diagnostic"),
        "research_only": True,
        "regime_authorized": False,
        "source_authenticated": False,
    }
