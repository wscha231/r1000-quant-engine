"""Research-only interest-rate and bank-credit context.

This module is intentionally narrower than the full liquidity/crisis engine. It
implements the first merge slice: matched funding rates, discount-window stress,
bank business-credit/deposit growth, and SLOOS supply/demand. It has no target,
order, broker, champion, or canonical-regime mutation authority.
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

SCHEMA = "liquidity-rates-banks-context-v1"
INPUT_SCHEMA = "liquidity-rates-banks-input-v1"
SHA256 = re.compile(r"[0-9a-f]{64}")

SOURCES = {
    "SOFR": ("PERCENT", "daily", 7, 1.0),
    "IORB": ("PERCENT", "daily_7day", 7, 1.0),
    "WLCFLPCL": ("USD_MILLIONS", "weekly", 21, 0.001),
    "TOTCI": ("USD_BILLIONS", "weekly", 21, 1.0),
    "DPSACBW027SBOG": ("USD_BILLIONS", "weekly", 21, 1.0),
    "DRTSCILM": ("PERCENT", "quarterly", 170, 1.0),
    "DRSDCILM": ("PERCENT", "quarterly", 170, 1.0),
}
CRITICAL = tuple(SOURCES)


class ContractError(ValueError):
    pass


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
class Config:
    version: str = "rates-banks-h1-20260916"
    funding_stress_bp: float = 25.0
    funding_severe_bp: float = 75.0
    primary_credit_increase_bn: float = 25.0
    primary_credit_level_bn: float = 50.0
    tightening_pct: float = 20.0
    loan_growth_days: int = 91
    balance_change_days: int = 28

    def validate(self) -> None:
        require(self.version and isinstance(self.version, str), "INVALID_CONFIG")
        require(0 < self.funding_stress_bp < self.funding_severe_bp, "INVALID_CONFIG")
        for name, value in asdict(self).items():
            if name == "version":
                continue
            require(type(value) in (int, float) and value > 0, "INVALID_CONFIG")


def verified_non_session(dataset: dict[str, Any], row: dict[str, Any], series: str,
                         cutoff: datetime) -> bool:
    state = row.get("observation_status")
    allowed = {None, "OBSERVED", "NON_SESSION", "NOT_RELEASED", "MISSING", "WITHDRAWN"}
    require(state in allowed, "OBSERVATION_STATE")
    if state != "NON_SESSION":
        require(state not in {"NOT_RELEASED", "MISSING", "WITHDRAWN"} or row.get("value") is None,
                "NONVALUE_STATE_HAS_VALUE")
        require(state != "OBSERVED" or row.get("value") is not None, "OBSERVED_WITHOUT_VALUE")
        return False
    require(row.get("value") is None, "NON_SESSION_HAS_VALUE")
    matches = [e for e in dataset.get("calendar_evidence", [])
               if e.get("series") == series
               and e.get("observation_date") == row.get("observation_date")
               and e.get("state") == "NON_SESSION"]
    require(len(matches) == 1, "NON_SESSION_CALENDAR_REQUIRED")
    e = matches[0]
    require(isinstance(e.get("calendar_id"), str) and e["calendar_id"], "CALENDAR_ID")
    require(e.get("raw_sha256") in dataset.get("raw_sha256", []), "CALENDAR_RAW_HASH_UNBOUND")
    require(str(e.get("source_uri", "")).startswith("https://"), "CALENDAR_SOURCE")
    available = stamp(e["available_at"])
    require(stamp(e["published_at"]) <= available <= cutoff, "CALENDAR_NOT_AVAILABLE")
    return True


def select_series(dataset: dict[str, Any], series: str, cutoff: datetime) -> dict[str, Any]:
    unit, frequency, max_age, scale = SOURCES[series]
    require(dataset.get("unit") == unit, "UNIT_MISMATCH")
    require(dataset.get("frequency") == frequency, "FREQUENCY_MISMATCH")
    require(dataset.get("status") in {"COLLECTED", "UNCHANGED"}, "DATASET_BLOCKED")
    hashes = dataset.get("raw_sha256", [])
    require(isinstance(hashes, list) and hashes and
            all(isinstance(h, str) and SHA256.fullmatch(h) for h in hashes), "RAW_HASH_REQUIRED")
    require(isinstance(dataset.get("rows"), list), "ROWS_REQUIRED")
    versions: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[str, str], bytes] = {}
    intervals: dict[str, set[tuple[date, date]]] = {}
    for raw in dataset["rows"]:
        require(isinstance(raw, dict) and raw.get("series") == series, "SERIES_MISMATCH")
        available = stamp(raw["available_at"])
        retrieved = stamp(raw["retrieved_at"])
        obs = date.fromisoformat(raw["observation_date"])
        value = number(raw.get("value"))
        evidence = raw.get("evidence")
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
                require((lo, hi) == (vintage, end) or end < lo or vintage > hi,
                        "OVERLAPPING_VINTAGES")
            intervals.setdefault(key, set()).add((vintage, end))
            earliest = datetime.combine(vintage + timedelta(days=1), time(),
                                        ZoneInfo("America/New_York"))
            require(available >= earliest, "VINTAGE_INTRADAY_INVENTED")
        else:
            published = stamp(raw["published_at"])
            require(published <= available and published <= retrieved, "PUBLICATION_ORDER")
        require(type(raw.get("structural_break", False)) is bool, "BREAK_FLAG_TYPE")
        if available > cutoff or obs > cutoff.date():
            continue
        if verified_non_session(dataset, raw, series, cutoff):
            require(not any(r.get("value") is not None
                            and r.get("observation_date") == raw["observation_date"]
                            and stamp(r["available_at"]) <= cutoff
                            for r in dataset["rows"]), "CALENDAR_CONFLICTS_WITH_OBSERVATION")
            continue
        if evidence == "alfred_date_archive" and end < date.max:
            expires = datetime.combine(end + timedelta(days=2), time(),
                                       ZoneInfo("America/New_York"))
            if cutoff >= expires:
                value = None
        scaled = None if value is None else value * scale
        row = dict(raw, value=scaled)
        identity = (obs.isoformat(), available.isoformat())
        signature = encoded([scaled, raw.get("vintage_date"), raw.get("realtime_end"),
                             evidence, raw.get("structural_break", False), raw.get("observation_status")])
        require(identity not in identities or identities[identity] == signature,
                "CONFLICTING_VINTAGE")
        identities[identity] = signature
        prior = versions.get(obs.isoformat())
        if prior is None or stamp(prior["available_at"]) < available:
            versions[obs.isoformat()] = row
    rows = sorted(versions.values(), key=lambda r: r["observation_date"])
    if not rows:
        return {"status": "NOT_AVAILABLE_AS_OF", "rows": []}
    latest = rows[-1]
    if latest["value"] is None:
        status = {"MISSING": "MISSING_OBSERVATION", "NOT_RELEASED": "NOT_RELEASED"}.get(
            latest.get("observation_status"), "WITHDRAWN")
    elif (cutoff.date() - date.fromisoformat(latest["observation_date"])).days > max_age:
        status = "STALE"
    else:
        status = "OK"
    return {"status": status, "rows": rows, "observation_date": latest["observation_date"],
            "available_at": latest["available_at"], "unit": unit, "frequency": frequency,
            "raw_sha256": sorted(hashes)}


def feature_view(packet: dict[str, Any], as_of: str) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    require(packet.get("schema") == INPUT_SCHEMA, "INPUT_SCHEMA")
    require(isinstance(packet.get("datasets"), dict), "DATASETS_REQUIRED")
    cutoff = stamp(as_of)
    selected: dict[str, list[dict]] = {}
    audit: dict[str, dict] = {}
    for sid in SOURCES:
        try:
            ds = packet["datasets"].get(sid)
            result = select_series(ds, sid, cutoff) if ds else {"status": "MISSING", "rows": []}
        except (ContractError, TypeError, KeyError, ValueError):
            result = {"status": "INVALID_SOURCE", "rows": []}
        audit[sid] = {k: v for k, v in result.items() if k != "rows"}
        selected[sid] = result["rows"] if result["status"] == "OK" else []
    return selected, audit


def latest(series: dict[str, list[dict]], sid: str) -> float | None:
    return series[sid][-1]["value"] if series[sid] else None


def change(series: dict[str, list[dict]], sid: str, days: int, *, percent: bool = False) -> float | None:
    rows = series[sid]
    if not rows:
        return None
    last = rows[-1]
    anchor = date.fromisoformat(last["observation_date"]) - timedelta(days=days)
    prior = [r for r in rows if date.fromisoformat(r["observation_date"]) <= anchor]
    if not prior:
        return None
    first = prior[-1]
    tolerance = {"daily": 7, "daily_7day": 7, "weekly": 14, "quarterly": 100}[SOURCES[sid][1]]
    if (anchor - date.fromisoformat(first["observation_date"])).days > tolerance:
        return None
    window = [r for r in rows if r["observation_date"] >= first["observation_date"]]
    if any((date.fromisoformat(b["observation_date"]) - date.fromisoformat(a["observation_date"])).days > tolerance
           for a, b in zip(window, window[1:])):
        return None
    if any(r["value"] is None or r.get("structural_break", False) for r in window):
        return None
    a, b = first["value"], last["value"]
    if percent:
        return 100 * (b / a - 1) if a and a > 0 else None
    return b - a


def evaluate(packet: dict[str, Any], *, as_of: str, source_commit: str,
             config: Config | None = None, prior: dict | None = None) -> dict[str, Any]:
    cfg = config or Config(); cfg.validate()
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source_commit)), "COMMIT_REQUIRED")
    s, audit = feature_view(packet, as_of)
    sofr = {r["observation_date"]: r["value"] for r in s["SOFR"]}
    iorb = {r["observation_date"]: r["value"] for r in s["IORB"]}
    common = sorted(set(sofr) & set(iorb))
    pair_day = common[-1] if common else None
    fresh_pair = bool(pair_day and (stamp(as_of).date() - date.fromisoformat(pair_day)).days <= 7)
    latest_pair_confirmed = bool(fresh_pair and pair_day == audit["SOFR"].get("observation_date"))
    pair_rows = {sid: next((r for r in reversed(s[sid]) if r["observation_date"] == pair_day), None)
                 for sid in ("SOFR", "IORB")}
    spread = None
    if fresh_pair and pair_day and sofr[pair_day] is not None and iorb[pair_day] is not None:
        spread = 100 * (sofr[pair_day] - iorb[pair_day])
    primary_level = latest(s, "WLCFLPCL")
    primary_change = change(s, "WLCFLPCL", cfg.balance_change_days)
    ci_growth = change(s, "TOTCI", cfg.loan_growth_days, percent=True)
    deposit_growth = change(s, "DPSACBW027SBOG", cfg.loan_growth_days, percent=True)
    tightening = latest(s, "DRTSCILM")
    demand = latest(s, "DRSDCILM")

    stress_reasons: list[str] = []
    if spread is not None and spread >= cfg.funding_stress_bp:
        stress_reasons.append("SOFR_IORB_SPREAD")
    if primary_change is not None and primary_change >= cfg.primary_credit_increase_bn:
        stress_reasons.append("PRIMARY_CREDIT_INCREASE")
    if primary_level is not None and primary_level >= cfg.primary_credit_level_bn:
        stress_reasons.append("PRIMARY_CREDIT_LEVEL")
    if stress_reasons:
        funding_state = "STRESS"
    elif latest_pair_confirmed and None not in (spread, primary_change, primary_level):
        funding_state = "STABLE"
    else:
        funding_state = "UNKNOWN"

    bank_state = "UNKNOWN"
    if None not in (ci_growth, deposit_growth, tightening, demand):
        if ci_growth > 0 and deposit_growth >= 0 and demand > 0 and tightening <= 0:
            bank_state = "EXPANSION_EVIDENCE"
        elif ci_growth < 0 and (demand < 0 or tightening >= cfg.tightening_pct):
            bank_state = "CONTRACTION_EVIDENCE"
        else:
            bank_state = "MIXED"

    missing = [sid for sid in CRITICAL if audit[sid]["status"] != "OK"]
    if not latest_pair_confirmed:
        missing.append("LATEST_FUNDING_PAIR_UNCONFIRMED")
    quality = "DEGRADED" if missing else "COMPLETE_INPUT"
    pair = dict(observation_date=pair_day, latest_pair_confirmed=latest_pair_confirmed,
                sofr_latest_date=audit["SOFR"].get("observation_date"),
                iorb_latest_date=audit["IORB"].get("observation_date"),
                available_at={sid: row["available_at"] if row else None for sid, row in pair_rows.items()})
    signature = dict(funding_pair_date=pair_day,
        bank_dates={sid: audit[sid].get("observation_date") for sid in
                    ("TOTCI", "DPSACBW027SBOG", "DRTSCILM", "DRSDCILM")})
    new_confirmation = False
    if prior is not None:
        require(prior.get("schema") == SCHEMA and prior.get("source_commit") == source_commit,
                "PRIOR_CONTRACT")
        require(stamp(prior["as_of"]) <= stamp(as_of), "PRIOR_FROM_FUTURE")
        old = prior.get("confirmation_signature", {})
        new_confirmation = (funding_state == "STABLE" and bank_state in {"EXPANSION_EVIDENCE", "MIXED"}
                            and signature != old
                            and pair_day is not None
                            and pair_day != old.get("funding_pair_date"))
    result = dict(schema=SCHEMA, mode="RESEARCH_ONLY", as_of=as_of,
        source_commit=source_commit, config_hash=digest(asdict(cfg)), data_hash=digest(packet),
        eligible_for_selector=False, target_mutation_allowed=False, orders_allowed=False,
        canonical_regime_mutation_allowed=False,
        funding_state=funding_state, funding_stress_reasons=stress_reasons,
        bank_credit_state=bank_state, funding_pair=pair,
        features=dict(funding_spread_bp=spread, primary_credit_level_bn=primary_level,
                      primary_credit_change_bn=primary_change, ci_growth_13w_pct=ci_growth,
                      deposit_growth_13w_pct=deposit_growth, sloos_tightening_pct=tightening,
                      sloos_demand_pct=demand),
        source_quality=audit, missing_critical_sources=sorted(set(missing)),
        quality_status=quality, confirmation_signature=signature,
        new_rates_banks_confirmation=new_confirmation,
        review_flags=dict(funding_stress=bool(stress_reasons),
                          bank_credit_contraction=bank_state == "CONTRACTION_EVIDENCE",
                          bank_credit_expansion=bank_state == "EXPANSION_EVIDENCE"),
        note="Rates/banks evidence only; no market-timing, portfolio-weight or order authority.")
    return result


def attach_readonly(canonical: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    require(context.get("schema") == SCHEMA and context.get("mode") == "RESEARCH_ONLY",
            "CONTEXT_CONTRACT")
    for key in ("eligible_for_selector", "target_mutation_allowed", "orders_allowed",
                "canonical_regime_mutation_allowed"):
        require(context.get(key) is False, "CONTEXT_MUTATION_FORBIDDEN")
    require("rates_banks_context" not in canonical, "SIDECAR_ALREADY_EXISTS")
    out = copy.deepcopy(canonical)
    out["rates_banks_context"] = copy.deepcopy(context)
    return out
