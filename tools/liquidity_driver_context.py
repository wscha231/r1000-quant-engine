"""Six-axis, evidence-only liquidity context. Never a second trading governor.

All thresholds below are preregistered RESEARCH baselines, not optimized alpha.
Current FRED histories are forward-only; archived vintages retain availability.
No orders, target weights, canonical regime changes or promotion are produced.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA = "liquidity-driver-context-v1"
INPUT_SCHEMA = "liquidity-driver-input-v1"

# unit, frequency, maximum observation age (calendar days), scale to USD bn
# Source metadata was checked on 2026-09-14. See dated implementation report.
SOURCES = {
    "WALCL": ("USD_MILLIONS", "weekly", 21, .001),
    "WRESBAL": ("USD_MILLIONS", "weekly", 21, .001),
    "WTREGEN": ("USD_MILLIONS", "weekly", 21, .001),
    "RRPONTSYD": ("USD_BILLIONS", "daily", 7, 1.),
    "WLCFLPCL": ("USD_MILLIONS", "weekly", 21, .001),
    "SOFR": ("PERCENT", "daily", 7, 1.),
    "IORB": ("PERCENT", "daily", 7, 1.),
    "TOTCI": ("USD_BILLIONS", "weekly", 21, 1.),
    "DPSACBW027SBOG": ("USD_BILLIONS", "weekly", 21, 1.),
    "DRTSCILM": ("PERCENT", "quarterly", 170, 1.),
    "DRSDCILM": ("PERCENT", "quarterly", 170, 1.),
    "BAMLH0A0HYM2": ("PERCENT", "daily", 7, 1.),
    "CPIAUCSL": ("INDEX_1982_84_100", "monthly", 80, 1.),
    "DGS10": ("PERCENT", "daily", 7, 1.),
    "T10YIE": ("PERCENT", "daily", 7, 1.),
    "M2SL": ("USD_BILLIONS", "monthly", 100, 1.),
    # Computed by the existing PIT universe/price pipeline, not a FRED series.
    "BREADTH_ABOVE_200D": ("PERCENT", "daily", 7, 1.),
}
CRITICAL = ("SOFR", "IORB", "WLCFLPCL", "BAMLH0A0HYM2", "BREADTH_ABOVE_200D")
SHA256 = re.compile(r"[0-9a-f]{64}")


class ContractError(ValueError):
    """Controlled error codes only; never echo source payloads or credentials."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ContractError(reason)


def encoded(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def stamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "TIMEZONE_REQUIRED")
        return result.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError):
        raise ContractError("INVALID_TIMESTAMP") from None


def number(value: Any) -> float | None:
    if value is None:
        return None
    require(type(value) in (int, float) and math.isfinite(value), "NONFINITE_VALUE")
    return float(value)


@dataclass(frozen=True)
class ResearchConfig:
    version: str = "liquidity-research-baseline-20260914"
    funding_stress_bp: float = 25.
    funding_severe_bp: float = 75.
    primary_credit_increase_bn: float = 25.
    primary_credit_level_bn: float = 50.
    hy_stress_pct: float = 5.
    hy_widening_pp: float = 1.
    hy_stable_pct: float = 4.
    tightening_pct: float = 20.
    inflation_hot_pct: float = 3.
    breakeven_rise_pp: float = .25
    nominal_yield_rise_pp: float = .5
    breadth_recovery_pct: float = 55.
    breadth_improvement_pp: float = 5.
    breadth_damage_pct: float = 35.
    reentry_confirmations: int = 2
    reentry_max_gap_days: int = 7

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if key != "version":
                require(number(value) is not None and value > 0, "INVALID_CONFIG")
        require(0 < self.hy_stable_pct < self.hy_stress_pct, "INVALID_CONFIG")
        require(self.funding_stress_bp < self.funding_severe_bp, "INVALID_CONFIG")
        require(self.breadth_damage_pct < self.breadth_recovery_pct <= 100, "INVALID_CONFIG")
        require(isinstance(self.version, str) and bool(self.version), "INVALID_CONFIG")
        require(type(self.reentry_max_gap_days) is int, "INVALID_CONFIG")
        require(type(self.reentry_confirmations) is int and self.reentry_confirmations >= 2,
                "INVALID_CONFIG")


def select_series(dataset: dict[str, Any], series: str, cutoff: datetime) -> dict[str, Any]:
    """Latest known vintage for each economic period, including withdrawals.

    A later revision is not visible at an earlier cutoff. Identical downloads do
    not create new release confirmations. Age uses the observation, not fetch.
    """
    unit, frequency, max_age, scale = SOURCES[series]
    require(dataset.get("unit") == unit, "UNIT_MISMATCH")
    require(dataset.get("frequency") == frequency, "FREQUENCY_MISMATCH")
    require(dataset.get("status") in {"COLLECTED", "UNCHANGED"}, "DATASET_BLOCKED")
    hashes = dataset.get("raw_sha256", [])
    require(isinstance(hashes, list) and bool(hashes) and
            all(isinstance(h, str) and SHA256.fullmatch(h) for h in hashes), "RAW_HASH_REQUIRED")
    versions: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[str, str], bytes] = {}
    intervals: dict[str, set[tuple[date, date]]] = {}
    require(isinstance(dataset.get("rows"), list), "ROWS_REQUIRED")
    for raw in dataset["rows"]:
        require(isinstance(raw, dict), "ROW_REQUIRED")
        require(raw.get("series") == series, "SERIES_MISMATCH")
        available = stamp(raw["available_at"])
        retrieved = stamp(raw["retrieved_at"])
        obs = date.fromisoformat(raw["observation_date"])
        evidence = raw.get("evidence")
        value = number(raw.get("value"))
        if value is not None:
            require(not unit.startswith("USD_") or value >= 0, "NEGATIVE_MONEY_STOCK")
            require(series != "CPIAUCSL" or value > 0, "INVALID_PRICE_INDEX")
            require(series != "BREADTH_ABOVE_200D" or 0 <= value <= 100, "BREADTH_RANGE")
        require(obs <= retrieved.date(), "FUTURE_OBSERVATION")
        require(evidence in {"current_only", "alfred_date_archive", "published_snapshot"},
                "EVIDENCE_REQUIRED")
        if evidence == "current_only":
            require(available >= retrieved, "CURRENT_HISTORY_BACKDATED")
        elif evidence == "alfred_date_archive":
            vintage = date.fromisoformat(raw["vintage_date"])
            end = date.fromisoformat(raw["realtime_end"])
            require(obs <= vintage <= end and vintage <= retrieved.date(), "INVALID_VINTAGE")
            key = obs.isoformat()
            for lo, hi in intervals.get(key, set()):
                require((lo, hi) == (vintage, end) or end < lo or vintage > hi, "OVERLAPPING_VINTAGES")
            intervals.setdefault(key, set()).add((vintage, end))
            earliest = datetime.combine(vintage + timedelta(days=1), time(),
                                        ZoneInfo("America/New_York"))
            require(available >= earliest, "VINTAGE_INTRADAY_INVENTED")
        else:
            published = stamp(raw["published_at"])
            require(published <= available and published <= retrieved,
                    "PUBLICATION_ORDER")
            require(available >= retrieved, "SNAPSHOT_BACKDATED")
        require(type(raw.get("structural_break", False)) is bool, "BREAK_FLAG_TYPE")
        if available > cutoff or obs > cutoff.date():
            continue
        # Once the archive says a vintage expired, never retain its numeric
        # value when a successor is missing. Admission uses the same end-of-NY-
        # day convention as vintage_start; unknown successor remains withdrawn.
        if evidence == "alfred_date_archive" and end < date.max:
            expires = datetime.combine(end + timedelta(days=1), time(),
                                       ZoneInfo("America/New_York"))
            if cutoff >= expires:
                value = None
        row = dict(raw, value=None if value is None else value * scale)
        identity = (obs.isoformat(), available.isoformat())
        # Exclude transport time from semantic equality, not value/vintage/break.
        signature = encoded([value, raw.get("vintage_date"), raw.get("realtime_end"),
                             evidence, raw.get("structural_break", False)])
        require(identity not in identities or identities[identity] == signature,
                "CONFLICTING_VINTAGE")
        identities[identity] = signature
        previous = versions.get(obs.isoformat())
        if previous is None or stamp(previous["available_at"]) < available:
            versions[obs.isoformat()] = row
    rows = sorted(versions.values(), key=lambda r: r["observation_date"])
    if not rows:
        return {"status": "NOT_AVAILABLE_AS_OF", "rows": []}
    latest = rows[-1]
    if latest["value"] is None:
        status = "WITHDRAWN"
    elif (cutoff.date() - date.fromisoformat(latest["observation_date"])).days > max_age:
        status = "STALE"
    else:
        status = "OK"
    return {"status": status, "rows": rows, "unit": unit, "frequency": frequency,
            "observation_date": latest["observation_date"],
            "available_at": latest["available_at"], "evidence": latest["evidence"],
            "raw_sha256": sorted(hashes)}


def feature_view(packet: dict[str, Any], as_of: str) -> tuple[dict, dict]:
    require(packet.get("schema") == INPUT_SCHEMA, "INPUT_SCHEMA")
    require(isinstance(packet.get("datasets"), dict), "DATASETS_REQUIRED")
    cutoff = stamp(as_of)
    selected, audit = {}, {}
    for sid in SOURCES:
        try:
            dataset = packet["datasets"].get(sid)
            result = select_series(dataset, sid, cutoff) if dataset is not None else {
                "status": "MISSING", "rows": []}
        except (ContractError, KeyError, TypeError, ValueError):
            result = {"status": "INVALID_SOURCE", "rows": []}
        audit[sid] = {k: v for k, v in result.items() if k != "rows"}
        selected[sid] = result["rows"] if result["status"] == "OK" else []
    return selected, audit


def latest(series: dict, sid: str) -> float | None:
    rows = series[sid]
    return rows[-1]["value"] if rows else None


def change(series: dict, sid: str, days: int, *, percent: bool = False) -> float | None:
    rows = series[sid]
    if not rows:
        return None
    last = rows[-1]
    anchor = date.fromisoformat(last["observation_date"]) - timedelta(days=days)
    prior = [r for r in rows if date.fromisoformat(r["observation_date"]) <= anchor]
    if not prior:
        return None
    first = prior[-1]
    tolerance = {"daily": 7, "weekly": 14, "monthly": 35, "quarterly": 100}[SOURCES[sid][1]]
    if (anchor - date.fromisoformat(first["observation_date"])).days > tolerance:
        return None
    window = [r for r in rows if r["observation_date"] >= first["observation_date"]]
    if any((date.fromisoformat(b["observation_date"]) -
            date.fromisoformat(a["observation_date"])).days > tolerance
           for a, b in zip(window, window[1:])):
        return None
    if any(r["value"] is None or r.get("structural_break", False) for r in window):
        return None
    a, b = first["value"], last["value"]
    if percent:
        return 100 * (b / a - 1) if a > 0 else None
    return b - a


def cpi_rates(rows: list[dict]) -> tuple[float | None, float | None]:
    """Exact monthly anchors; missing months do not become shorter windows."""
    if not rows:
        return None, None
    values = {int(r["observation_date"][:4]) * 12 + int(r["observation_date"][5:7]): r["value"]
              for r in rows}
    m = max(values)
    if any(values.get(m-i) is None or values[m-i] <= 0 for i in range(7)):
        return None, None
    return (100 * ((values[m] / values[m-3]) ** 4 - 1),
            100 * ((values[m-3] / values[m-6]) ** 4 - 1))


def policy_view(events: list[dict], as_of: str) -> list[dict]:
    cutoff = stamp(as_of)
    stages = {"OFFICIAL_DISCUSSION", "PROPOSED_RULE", "FINAL_RULE", "WITHDRAWN"}
    result = {}
    for event in events:
        require(event.get("stage") in stages, "POLICY_STAGE")
        require(isinstance(event.get("policy_id"), str) and event["policy_id"], "POLICY_ID")
        require(SHA256.fullmatch(str(event.get("raw_sha256", ""))) is not None, "POLICY_HASH")
        require(str(event.get("source_uri", "")).startswith("https://"), "POLICY_SOURCE")
        available, published = stamp(event["available_at"]), stamp(event["published_at"])
        require(published <= available, "POLICY_TIME_ORDER")
        if available > cutoff:
            continue
        effective = stamp(event["effective_at"]) if event.get("effective_at") else None
        stage = event["stage"]
        if stage == "FINAL_RULE":
            stage = "FINAL_EFFECTIVE_DATE_UNKNOWN" if effective is None else (
                "EFFECTIVE" if effective <= cutoff else "FINAL_NOT_EFFECTIVE")
        key = event["policy_id"]
        previous = result.get(key)
        require(previous is None or stamp(previous["available_at"]) != available or
                previous["event_hash"] == digest(event), "POLICY_CONFLICT")
        if previous is None or stamp(previous["available_at"]) < available:
            result[key] = dict(policy_id=key, stage=stage, available_at=event["available_at"],
                effective_at=event.get("effective_at"), source_uri=event["source_uri"],
                raw_sha256=event["raw_sha256"], event_hash=digest(event),
                actual_liquidity_amount=None, economic_effect="NOT_INFERRED")
    return sorted(result.values(), key=lambda r: r["policy_id"])


def evaluate(packet: dict[str, Any], *, as_of: str, source_commit: str,
             config: ResearchConfig | None = None, prior: dict | None = None) -> dict:
    cfg = config or ResearchConfig()
    cfg.validate()
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_commit)), "COMMIT_REQUIRED")
    s, audit = feature_view(packet, as_of)
    v = lambda sid: latest(s, sid)
    d = lambda sid, days=28: change(s, sid, days)
    f: dict[str, float | None] = {}
    # Funding rates must describe the SAME economic day.
    sofr = {r["observation_date"]: r["value"] for r in s["SOFR"]}
    iorb = {r["observation_date"]: r["value"] for r in s["IORB"]}
    common = sorted(set(sofr) & set(iorb))
    funding_day = common[-1] if common else None
    fresh_pair = funding_day and (stamp(as_of).date() - date.fromisoformat(funding_day)).days <= 7
    f["funding_spread_bp"] = 100 * (sofr[funding_day] - iorb[funding_day]) if (
        fresh_pair and sofr[funding_day] is not None and iorb[funding_day] is not None) else None
    f["fed_assets_change_bn"] = d("WALCL")
    f["primary_credit_change_bn"] = d("WLCFLPCL")
    f["primary_credit_level_bn"] = v("WLCFLPCL")
    f["reserves_bn"] = v("WRESBAL")
    f["tga_change_bn"] = d("WTREGEN")
    f["rrp_change_bn"] = d("RRPONTSYD")
    # No RRP pct_change, no Fed-RRP-TGA proxy blended back with its components.
    f["rrp_buffer_to_reserves"] = v("RRPONTSYD") / v("WRESBAL") if (
        v("RRPONTSYD") is not None and v("WRESBAL") is not None and v("WRESBAL") > 0) else None
    f["ci_growth_13w_pct"] = change(s, "TOTCI", 91, percent=True)
    f["deposit_growth_13w_pct"] = change(s, "DPSACBW027SBOG", 91, percent=True)
    f["sloos_tightening_pct"], f["sloos_demand_pct"] = v("DRTSCILM"), v("DRSDCILM")
    f["hy_spread_pct"], f["hy_change_pp"] = v("BAMLH0A0HYM2"), d("BAMLH0A0HYM2")
    f["cpi_3m_ann_pct"], f["cpi_prior_3m_ann_pct"] = cpi_rates(s["CPIAUCSL"])
    f["nominal_yield_change_pp"], f["breakeven_change_pp"] = d("DGS10"), d("T10YIE")
    f["breadth_pct"], f["breadth_change_pp"] = v("BREADTH_ABOVE_200D"), d("BREADTH_ABOVE_200D")
    f["m2_growth_pct"] = change(s, "M2SL", 91, percent=True)
    known = lambda *keys: all(f[k] is not None for k in keys)
    funding = "UNKNOWN"
    funding_stress = ((known("funding_spread_bp") and f["funding_spread_bp"] >= cfg.funding_stress_bp) or
        (known("primary_credit_change_bn") and f["primary_credit_change_bn"] >= cfg.primary_credit_increase_bn) or
        (known("primary_credit_level_bn") and f["primary_credit_level_bn"] >= cfg.primary_credit_level_bn))
    if funding_stress:
        funding = "STRESS"
    elif known("funding_spread_bp", "primary_credit_change_bn", "primary_credit_level_bn"):
        funding = "STABLE"
    emergency = (known("funding_spread_bp") and f["funding_spread_bp"] >= cfg.funding_severe_bp)
    # A loan jump with a flagged reclassification cannot be called organic growth.
    bank = "UNKNOWN"
    if known("ci_growth_13w_pct", "deposit_growth_13w_pct", "sloos_tightening_pct", "sloos_demand_pct"):
        if (f["ci_growth_13w_pct"] > 0 and f["deposit_growth_13w_pct"] >= 0 and
                f["sloos_demand_pct"] > 0 and f["sloos_tightening_pct"] <= 0):
            bank = "EXPANSION_EVIDENCE"
        elif f["ci_growth_13w_pct"] < 0 and (f["sloos_demand_pct"] < 0 or
                f["sloos_tightening_pct"] >= cfg.tightening_pct):
            bank = "CONTRACTION_EVIDENCE"
        else:
            bank = "MIXED"
    market = "UNKNOWN"
    if ((known("hy_spread_pct") and f["hy_spread_pct"] >= cfg.hy_stress_pct) or
            (known("hy_change_pp") and f["hy_change_pp"] >= cfg.hy_widening_pp)):
        market = "STRESS"
    elif known("hy_spread_pct", "hy_change_pp"):
        market = "STABLE" if f["hy_spread_pct"] < cfg.hy_stable_pct and f["hy_change_pp"] <= 0 else "MIXED"
    inflation = "UNKNOWN"
    if known("cpi_3m_ann_pct", "cpi_prior_3m_ann_pct", "nominal_yield_change_pp", "breakeven_change_pp"):
        hot = ((f["cpi_3m_ann_pct"] >= cfg.inflation_hot_pct and
                f["cpi_3m_ann_pct"] >= f["cpi_prior_3m_ann_pct"]) or
               f["breakeven_change_pp"] >= cfg.breakeven_rise_pp or
               f["nominal_yield_change_pp"] >= cfg.nominal_yield_rise_pp)
        inflation = "DURATION_RISK" if hot else ("DISINFLATION_EVIDENCE" if
            f["cpi_3m_ann_pct"] < f["cpi_prior_3m_ann_pct"] and
            f["breakeven_change_pp"] <= 0 and f["nominal_yield_change_pp"] <= 0 else "MIXED")
    if ((known("nominal_yield_change_pp") and f["nominal_yield_change_pp"] >= cfg.nominal_yield_rise_pp) or
        (known("breakeven_change_pp") and f["breakeven_change_pp"] >= cfg.breakeven_rise_pp)):
        inflation = "DURATION_RISK"
    treasury = "UNKNOWN"
    if known("tga_change_bn", "rrp_change_bn"):
        treasury = "TGA_DRAWDOWN" if f["tga_change_bn"] < 0 else (
            "TGA_BUILD" if f["tga_change_bn"] > 0 else "TGA_UNCHANGED")
    cash = []
    if funding == "STRESS" or emergency:
        cash.append("FUNDING_STRESS")
    if market == "STRESS":
        cash.append("CREDIT_MARKET_STRESS")
    if bank == "CONTRACTION_EVIDENCE":
        cash.append("BANK_CREDIT_CONTRACTION")
    if known("breadth_pct") and f["breadth_pct"] <= cfg.breadth_damage_pct:
        cash.append("MARKET_BREADTH_DAMAGE")
    cash_review = bool(emergency or len(cash) >= 2)
    critical_missing = [sid for sid in CRITICAL if audit[sid]["status"] != "OK"]
    if not known("funding_spread_bp", "primary_credit_change_bn", "hy_change_pp", "breadth_change_pp"):
        critical_missing.append("REQUIRED_FEATURE_HISTORY_OR_ALIGNMENT")
    recovery = (not critical_missing and not cash_review and funding == "STABLE" and
        market == "STABLE" and known("breadth_pct", "breadth_change_pp") and
        f["breadth_pct"] >= cfg.breadth_recovery_pct and
        f["breadth_change_pp"] >= cfg.breadth_improvement_pp)
    # Do not count a daily re-fetch of an unchanged H.8/SLOOS release as new.
    sessions = {sid: audit[sid].get("observation_date") for sid in
                ("SOFR", "BAMLH0A0HYM2", "BREADTH_ABOVE_200D")}
    config_hash = digest({"config": asdict(cfg), "sources": SOURCES})
    previous_count = 0
    new_confirmation = bool(recovery)
    if prior is not None:
        require(prior.get("schema") == SCHEMA and prior.get("config_hash") == config_hash,
                "PRIOR_CONTRACT")
        require(stamp(prior["as_of"]) <= stamp(as_of), "PRIOR_FROM_FUTURE")
        require(prior.get("mode") == "RESEARCH_ONLY", "PRIOR_MODE")
        require(prior.get("source_commit") == source_commit, "PRIOR_CODE_CHANGED")
        gap = (stamp(as_of) - stamp(prior["as_of"])).total_seconds() / 86400
        previous_count = prior.get("recovery_observation_count", 0)
        require(type(previous_count) is int and 0 <= previous_count <= cfg.reentry_confirmations,
                "PRIOR_COUNT")
        if gap > cfg.reentry_max_gap_days:
            previous_count = 0
        else:
            old = prior.get("confirmation_sessions", {})
            if recovery and any(not old.get(k) or sessions[k] < old[k] for k in sessions):
                recovery = False
            new_confirmation = bool(recovery and all(old.get(k) and sessions[k] > old[k] for k in sessions))
    count = min(cfg.reentry_confirmations, previous_count + int(new_confirmation)) if recovery else 0
    reentry = bool(recovery and count >= cfg.reentry_confirmations)
    if cash_review:
        driver = "STRESS_DOMINANT"
    elif bank == "EXPANSION_EVIDENCE" and funding == "STABLE":
        driver = "BANK_CREDIT_SUPPORTED"
    elif known("fed_assets_change_bn") and f["fed_assets_change_bn"] > 0:
        driver = "CENTRAL_BANK_BALANCE_SHEET_CHANGE_UNATTRIBUTED"
    else:
        driver = "MIXED_OR_INSUFFICIENT"
    policies = policy_view(packet.get("policy_events", []), as_of)
    result = dict(schema=SCHEMA, mode="RESEARCH_ONLY", computed=True, as_of=as_of,
        input_kind="SYNTHETIC_FIXTURE" if packet.get("fixture_only") is True else
            packet.get("input_evidence", "CALLER_PACKET_NOT_INDEPENDENTLY_VERIFIED"),
        historical_pit_certified=False,
        source_commit=source_commit, config_hash=config_hash, data_hash=digest(packet),
        thresholds_validated_oos=False, eligible_for_selector=False, orders_allowed=False,
        target_mutation_allowed=False, canonical_regime_mutation_allowed=False,
        dominant_driver_hypothesis=driver,
        axes=dict(central_bank_funding=funding, treasury=treasury, bank_credit=bank,
                  market_nonbank=market, inflation_duration=inflation,
                  policy=policies or "RULEMAKING_STATUS_UNVERIFIED"),
        features=f, source_quality=audit, missing_critical_sources=sorted(set(critical_missing)),
        quality_status="DEGRADED" if critical_missing else (
            "PARTIAL" if any(r["status"] != "OK" for r in audit.values()) else "COMPLETE_INPUT"),
        cash_defense_evidence=cash, cash_defense_review=bool(cash_review),
        duration_extension_review=bool(inflation == "DISINFLATION_EVIDENCE" and
            (bank == "CONTRACTION_EVIDENCE" or market == "STRESS")),
        duration_blocked=inflation in {"DURATION_RISK", "UNKNOWN"},
        equity_reentry_evidence=["FUNDING_STABLE", "HY_STABLE", "BREADTH_RECOVERING"] if recovery else [],
        equity_reentry_review=reentry, recovery_observation_count=count,
        confirmation_sessions=sessions, new_recovery_observation=new_confirmation,
        coverage_limits=["TREASURY_MATURITY_AND_SETTLEMENT_NOT_MODELED",
                         "NONBANK_AND_ISSUANCE_MEASURED_BY_CREDIT_MARKET_PROXY_ONLY",
                         "BANK_ORGANIC_GROWTH_NOT_CERTIFIED",
                         "POLICY_EVENTS_REQUIRE_SEPARATE_VERIFIED_INGESTION"],
        note="Evidence hypotheses, not causal dollar attribution or trade instructions.")
    return result


def attach_to_canonical(canonical: dict, context: dict) -> dict:
    """Read-only sidecar: original state, emergency flags and weights unchanged."""
    require(context.get("schema") == SCHEMA and context.get("mode") == "RESEARCH_ONLY",
            "CONTEXT_CONTRACT")
    require(context.get("orders_allowed") is False and context.get("eligible_for_selector") is False,
            "CONTEXT_PROMOTION_FORBIDDEN")
    require(context.get("target_mutation_allowed") is False and
            context.get("canonical_regime_mutation_allowed") is False, "CONTEXT_MUTATION_FORBIDDEN")
    require("liquidity_driver_context" not in canonical, "SIDECAR_ALREADY_EXISTS")
    result = copy.deepcopy(canonical)
    result["liquidity_driver_context"] = copy.deepcopy(context)
    return result
