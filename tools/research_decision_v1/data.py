"""Explicit, deterministic current-research data admission (not PIT certification).

Consumes existing provider/cache material with supplied provenance. Never calls a
network, fills a missing value with zero, or imports a production selector.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlsplit, parse_qsl

STATUSES = {"available", "stale", "missing", "provider_error", "no_event", "not_applicable", "unverified"}
MARKETS = {"US": ("USD", "NYSE"), "KR": ("KRW", "XKRX")}
CORE = ("price", "financials", "thesis", "risk")
CALENDAR_VERSION = "5.4.0"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value):
    if not isinstance(value, str) or value != value.strip(): raise ValueError("invalid_timestamp")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None: raise ValueError("timezone_required")
    return t.astimezone(timezone.utc)


def number(value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite_number_required")
    if positive and value <= 0: raise ValueError("positive_number_required")
    if nonnegative and value < 0: raise ValueError("nonnegative_number_required")
    return float(value)


def reject_diagnostic_scores(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if any(x in k.lower() for x in ("nonranking", "alphaops_score", "raw_score", "ranking_ready")):
                raise ValueError("NONRANKING_or_legacy_score_forbidden")
            reject_diagnostic_scores(v)
    elif isinstance(value, list):
        for v in value: reject_diagnostic_scores(v)


def source_url(value):
    if not isinstance(value, str): raise ValueError("source_required")
    p = urlsplit(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("invalid_source_url")
    if any(re.search(r"key|token|secret|signature|credential", k, re.I) for k, _ in parse_qsl(p.query)):
        raise ValueError("credential_bearing_source")


@lru_cache(maxsize=128)
def sessions(market, start, cutoff):
    import pandas as pd
    import pandas_market_calendars as mcal
    if mcal.__version__ != CALENDAR_VERSION: raise ValueError("calendar_version_mismatch")
    if market not in MARKETS: raise ValueError("unsupported_market")
    end = timestamp(cutoff)
    schedule = mcal.get_calendar(MARKETS[market][1]).schedule(start_date=start, end_date=end.date())
    schedule = schedule[schedule.market_close <= pd.Timestamp(end)]
    return tuple(x.date().isoformat() for x in schedule.index)


def envelope_errors(block, security, cutoff):
    errors = []
    if not isinstance(block, dict): return ["missing"]
    status = block.get("status")
    if status not in STATUSES: return ["invalid_status"]
    if status != "available": return [status]
    try:
        source_url(block.get("source"))
        if block.get("security_id") != security["security_id"]: errors.append("security_id_mismatch")
        if block.get("currency") != security["currency"]: errors.append("currency_mismatch")
        if block.get("decision_cutoff") != cutoff: errors.append("cutoff_mismatch")
        if not block.get("unit") or not block.get("accounting_basis"): errors.append("unit_or_basis_missing")
        cut = timestamp(cutoff)
        for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"):
            if field not in block: errors.append(field + "_undeclared"); continue
            if block[field] is None:
                if field in ("first_seen_at", "ingested_at"): errors.append(field + "_unknown")
            elif timestamp(block[field]) > cut: errors.append(field + "_after_cutoff")
        if timestamp(block["first_seen_at"]) > timestamp(block["ingested_at"]): errors.append("observation_order")
        if block.get("public_available_at") and timestamp(block["public_available_at"]) > timestamp(block["first_seen_at"]):
            errors.append("availability_after_observation")
        if block.get("data_hash") != digest(block.get("payload")): errors.append("data_hash_mismatch")
        period = block.get("report_period")
        if not isinstance(period, dict) or set(period) != {"start", "end"}: errors.append("report_period_missing")
        elif period["start"] > period["end"]: errors.append("report_period_reversed")
    except (ValueError, TypeError, KeyError): errors.append("invalid_provenance")
    return sorted(set(errors))


def total_return_series(bars, basis):
    if basis not in {"raw_unadjusted", "split_adjusted"}: raise ValueError("price_basis_unverified")
    series = [1.]
    for old, new in zip(bars, bars[1:]):
        split = number(new["split_ratio"], positive=True)
        dividend = number(new["dividend"], nonnegative=True)
        factor = split if basis == "raw_unadjusted" else 1.
        series.append(series[-1] * (number(new["close"], positive=True) + dividend) * factor / number(old["close"], positive=True))
    return series


def price_analysis(payload, market, cutoff):
    latest = sessions(market, (timestamp(cutoff) - timedelta(days=20)).date().isoformat(), cutoff)[-1]
    if not payload.get("feed") or payload.get("quote_type") != "official_close": raise ValueError("close_feed_required")
    if payload.get("corporate_actions_status") not in {"available", "no_event"}: raise ValueError("corporate_actions_unverified")
    if payload.get("corporate_actions_through") != latest: raise ValueError("corporate_actions_stale")
    if payload.get("benchmark_actions_status") not in {"available", "no_event"}: raise ValueError("benchmark_actions_unverified")
    if payload.get("volume_basis") != payload.get("price_basis"): raise ValueError("price_volume_adjustment_mismatch")
    if not payload.get("benchmark_id"): raise ValueError("benchmark_missing")
    bars, benchmark = payload["bars"], payload["benchmark_bars"]
    if not bars or not benchmark: raise ValueError("price_missing")
    for rows, action_status in ((bars, payload["corporate_actions_status"]), (benchmark, payload["benchmark_actions_status"])):
        ds = [b["session"] for b in rows]
        if ds != sorted(set(ds)): raise ValueError("price_duplicate_or_unsorted")
        if ds[-1] != latest: raise ValueError("stale_or_future_price")
        if tuple(ds) != sessions(market, ds[0], cutoff): raise ValueError("calendar_gap_or_non_session")
        for b in rows:
            number(b["close"], positive=True); number(b["volume"], nonnegative=True)
            number(b["split_ratio"], positive=True); number(b["dividend"], nonnegative=True)
            if action_status == "no_event" and (b["split_ratio"] != 1 or b["dividend"] != 0):
                raise ValueError("no_event_conflicts_with_corporate_action")
    if len(bars) < 21: raise ValueError("liquidity_history_missing")
    tr, br = total_return_series(bars, payload["price_basis"]), total_return_series(benchmark, payload["benchmark_price_basis"])
    rs = {}
    for h in (20, 60, 120, 240):
        enough = min(len(tr), len(br)) >= h + 1
        same = enough and bars[-h-1]["session"] == benchmark[-h-1]["session"]
        rs[str(h)] = {"status": "available" if same else "missing", "reason": None if same else "insufficient_aligned_sessions",
                      "value": math.log(tr[-1]/tr[-h-1]) - math.log(br[-1]/br[-h-1]) if same else None}
    return {"required_session": latest, "price": bars[-1]["close"], "return_basis": "TOTAL_RETURN_LOCAL_CURRENCY",
            "history_sessions": len(bars), "rs": rs,
            "adv20_local": sum(b["close"] * b["volume"] for b in bars[-20:]) / 20}


def financial_errors(block, market, cutoff):
    errors = []
    try:
        f = block["payload"]; p = f["period"]
        start, end = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])
        if not 350 <= (end-start).days <= 380: errors.append("ttm_period_invalid")
        age = (timestamp(cutoff).date() - end.date()).days
        if age < 0 or age > 210: errors.append("financials_future_or_stale")
        expected_basis = "US_GAAP" if market == "US" else "K_IFRS_CONSOLIDATED"
        if block["accounting_basis"] != expected_basis: errors.append("accounting_basis_unverified")
        if block["unit"] != "currency_and_shares": errors.append("financial_unit_mismatch")
        metrics = f["ttm"]
        for k in ("revenue", "ebitda", "net_income", "operating_cash_flow", "capex", "fcf", "sbc", "net_debt", "diluted_shares"):
            number(metrics[k], positive=k in {"revenue", "diluted_shares"}, nonnegative=k in {"capex", "sbc"})
        if not math.isclose(metrics["fcf"], metrics["operating_cash_flow"] - metrics["capex"], rel_tol=1e-6, abs_tol=.01): errors.append("fcf_identity_mismatch")
        if p != block.get("report_period"): errors.append("financial_report_period_mismatch")
        for field, bounds in (("recent_quarters", (70, 110)), ("recent_annual", (350, 380))):
            if not f.get(field): errors.append(field + "_missing")
            ends = [row["end"] for row in f.get(field, [])]
            if len(ends) != len(set(ends)): errors.append(field + "_duplicate")
            for row in f.get(field, []):
                s, e = datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"])
                if not bounds[0] <= (e-s).days <= bounds[1] or e > end: errors.append(field + "_period_invalid")
                number(row["revenue"], nonnegative=True)
    except (KeyError, ValueError, TypeError): errors.append("financials_invalid_or_missing")
    return sorted(set(errors))


def thesis_risk_errors(blocks):
    errors = []
    try:
        t, r = blocks["thesis"]["payload"], blocks["risk"]["payload"]
        for k in ("id", "business", "segments", "customers", "bottleneck", "competition", "catalyst", "strongest_bear_case", "invalidation_condition", "valuation_rationale"):
            if not isinstance(t.get(k), str) or not t[k].strip(): errors.append("thesis_" + k + "_missing")
        if not isinstance(t.get("intact"), bool) or not isinstance(t.get("strengthened"), bool): errors.append("thesis_status_invalid")
        if t.get("company_quality") not in {"pass", "fail", "uncertain"}: errors.append("company_assessment_missing")
        if not 0 <= number(t["confidence"]) <= 1: errors.append("confidence_invalid")
        if not t.get("source_evidence"): errors.append("thesis_evidence_missing")
        for e in t.get("source_evidence", []):
            source_url(e["source"])
            if not e.get("claim"): errors.append("evidence_claim_missing")
        if r.get("complete_assessment") is not True or not r.get("exposures"): errors.append("risk_coverage_incomplete")
        for k, v in r.get("exposures", {}).items():
            if not re.fullmatch(r"(industry|theme|customer):.+", k) or not 0 <= number(v) <= 1: errors.append("exposure_invalid")
        if not all(any(k.startswith(prefix+":") for k in r.get("exposures", {})) for prefix in ("industry", "theme", "customer")): errors.append("risk_group_missing")
        for k in ("stress_loss", "uncertainty"):
            if not 0 <= number(r[k]) <= 1: errors.append(k + "_invalid")
        for k in ("liquidity_restriction", "integrity_alert"):
            if not isinstance(r.get(k), bool): errors.append(k + "_invalid")
    except (KeyError, ValueError, TypeError): errors.append("thesis_or_risk_invalid")
    return sorted(set(errors))


def export_market(bundle, expected_market):
    reject_diagnostic_scores(bundle)
    if bundle.get("schema_version") != "research-input-v1": raise ValueError("input_schema_mismatch")
    market = bundle.get("market")
    if market != expected_market or market not in MARKETS: raise ValueError("market_jurisdiction_mismatch")
    if bundle.get("data_kind") not in {"REAL", "SYNTHETIC"}: raise ValueError("data_kind_required")
    cutoff = bundle["decision_cutoff"]; timestamp(cutoff)
    rows, seen = [], set()
    for security in bundle["securities"]:
        s = copy.deepcopy(security); sid = s.get("security_id"); errors = []
        if sid in seen: raise ValueError("duplicate_security_id")
        seen.add(sid)
        if sid != f'{market}:{s.get("ticker")}' or s.get("market") != market: errors.append("security_identity_mismatch")
        ticker_pattern = r"[A-Z][A-Z0-9.\-]{0,9}" if market == "US" else r"[0-9]{6}"
        if not re.fullmatch(ticker_pattern, str(s.get("ticker", ""))): errors.append("ticker_invalid")
        if s.get("currency") != MARKETS[market][0]: errors.append("market_currency_mismatch")
        blocks = s.get("blocks", {})
        coverage = {k: envelope_errors(blocks.get(k), s, cutoff) for k in CORE}
        for k, reasons in coverage.items(): errors += [k + ":" + e for e in reasons]
        discovery = None
        if not coverage["price"]:
            try: discovery = price_analysis(blocks["price"]["payload"], market, cutoff)
            except (ValueError, KeyError, TypeError, IndexError) as exc: errors.append("price:" + str(exc))
        if not coverage["financials"]: errors += financial_errors(blocks["financials"], market, cutoff)
        if not coverage["thesis"] and not coverage["risk"]: errors += thesis_risk_errors(blocks)
        optional = copy.deepcopy(s.get("optional", {}))
        for key, block in optional.items():
            if block.get("status") not in STATUSES: raise ValueError("optional_status_invalid")
            if block.get("status") == "available":
                es = envelope_errors(block, s, cutoff)
                if es: optional[key] = {"status": "unverified", "reasons": es}
        s.update(data_quality_pass=not errors, blockers=sorted(set(errors)), coverage=coverage,
                 discovery=discovery, required_session=discovery["required_session"] if discovery else None,
                 optional=optional, historical_pit_verified=False, consensus_revision=None)
        rows.append(s)
    result = {"schema_version": "research-market-export-v1", "market": market,
              "data_kind": bundle["data_kind"], "decision_cutoff": cutoff,
              "calendar_engine": {"name": "pandas_market_calendars", "version": CALENDAR_VERSION},
              "source_input_hash": digest(bundle), "input_snapshot": copy.deepcopy(bundle),
              "securities": sorted(rows, key=lambda s: str(s["security_id"])),
              "orders_allowed": False}
    result["export_hash"] = digest(result)
    return result
