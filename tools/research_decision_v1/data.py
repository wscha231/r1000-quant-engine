"""Explicit, deterministic current-research data admission (not PIT certification).

Consumes existing provider/cache material with supplied provenance. Never calls a
network, fills a missing value with zero, or imports a production selector.
"""
from __future__ import annotations
import copy
import base64
import binascii
import hashlib
import ipaddress
import json
import math
import re
import unicodedata
from importlib import resources
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from functools import lru_cache
from urllib.parse import urlsplit, unquote

STATUSES = {"available", "stale", "missing", "provider_error", "no_event", "not_applicable", "unverified"}
MARKETS = {"US": ("USD", "NYSE"), "KR": ("KRW", "XKRX")}
CORE = ("price", "financials", "thesis", "risk")
CALENDAR_VERSION = "5.4.0"
TZDATA_VERSION = "2026.3"
REPORTING_TIMEZONES = {"US": "America/New_York", "KR": "Asia/Seoul"}
# Captured on import; the verified KR/H2 loaders import their checked snapshot.
_ADMISSION_SOURCE_HASH = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


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


def metadata_key(value):
    key = re.sub(r"([a-z])([A-Z])", r"\1_\2", unicodedata.normalize("NFKC", value)).lower()
    return re.sub(r"[\W_]+", "_", key).strip("_")


def reject_diagnostic_scores(value):
    if isinstance(value, dict):
        for k, v in value.items():
            key = metadata_key(k)
            if ("score" in key or "nonranking" in key or
                re.search(r"(?:^|_)(?:rank|ranking|rankable|readiness)(?:$|_)", key)):
                raise ValueError("NONRANKING_or_legacy_score_forbidden")
            reject_diagnostic_scores(v)
    elif isinstance(value, list):
        for v in value: reject_diagnostic_scores(v)
    elif isinstance(value, str) and ("NONRANKING" in value.upper() or
            metadata_key(value) in {"ranking_ready", "ranking_eligible", "rank_eligible", "rankable"}):
        raise ValueError("NONRANKING_or_legacy_score_forbidden")


def source_url(value):
    if not isinstance(value, str): raise ValueError("source_required")
    p = urlsplit(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("invalid_source_url")
    try:
        port = p.port
        if port is not None and not 1 <= port <= 65535: raise ValueError("invalid_port")
    except ValueError: raise ValueError("invalid_source_url") from None
    # Store a public document URL, never a provider request/signed download URL.
    # Query/fragment rejection is intentionally stronger than a credential-name denylist.
    if p.query or p.fragment or re.search(r"(?:key|token|secret|signature|credential|pass\w*|pwd|pswd|psw|pword|auth)[=_/:.-]", unquote(p.path), re.I):
        raise ValueError("credential_bearing_source")
    if re.search(r"[A-Za-z0-9_]{48,}", unquote(p.path)):
        raise ValueError("opaque_source_path_forbidden")


def contains_basic_credential(value):
    for token in re.findall(r"(?i:\bbasic)\s+([A-Za-z0-9+/]+={0,2})", value):
        try:
            if b":" in base64.b64decode(token + "=" * (-len(token) % 4), validate=True): return True
        except (ValueError, binascii.Error): pass
    return False


def validate_persistable_sources(value, *, real=False):
    """Reject unsafe input before retaining even a blocked input snapshot."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = metadata_key(key)
            # Deny the entire pass* token family, including pass_word/user_pass;
            # financial/thesis schemas have no persistable password-like field.
            if re.search(r"(?:^|[_\W])(?:token\w*|secret\w*|pass\w*|pwd\w*|pswd\w*|psw\w*|pword\w*|credential\w*|auth\w*|cookie\w*|api_?key\w*|private_?key\w*|access_?key\w*|client_?key\w*|signing_?key\w*|key\w*|bearer\w*|jwt\w*|oauth\w*|session_?(?:id|uuid|guid|key|token|secret|cookie|credential|auth)\w*|sid)(?:$|[_\W])", normalized_key):
                raise ValueError("credential_field_forbidden")
            if normalized_key == "session" and (not isinstance(child, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", child)):
                raise ValueError("credential_field_forbidden")
            if real and key == "feed" and isinstance(child, str) and re.match(r"(?i)^(synthetic|fixture|mock|test|demo)(?:$|[_ :.-])", child):
                raise ValueError("synthetic_feed_in_real_input")
            validate_persistable_sources(child, real=real)
    elif isinstance(value, list):
        for child in value: validate_persistable_sources(child, real=real)
    elif isinstance(value, str) and (contains_basic_credential(value) or re.search(r"(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?i:bearer)\s+[A-Za-z0-9._~+/-]{8,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", value)):
        raise ValueError("credential_value_forbidden")
    elif isinstance(value, str) and "://" in value:
        # A URL embedded in prose is checked too, before original text is serialized.
        for url in re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+", value, flags=re.I):
            source_url(url)
            if real: validate_public_source_host(urlsplit(url).hostname)


def validate_public_source_host(host):
    # Public evidence uses canonical DNS names, never IP literals or resolver-
    # dependent legacy IPv4 spellings. Normalize IDNA before this admission check.
    try: host = unquote(host).encode("idna").decode("ascii").lower().rstrip(".")
    except (UnicodeError, ValueError): raise ValueError("non_public_source_host") from None
    if any(host == x or host.endswith("."+x) for x in ("example.org", "example.com", "example.net", "localhost")):
        raise ValueError("synthetic_source_in_real_input")
    try: ipaddress.ip_address(host)
    except ValueError: pass
    else: raise ValueError("non_public_source_host")
    labels = host.split(".")
    if (len(labels) < 2 or len(host) > 253 or
        any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels) or
        re.fullmatch(r"[0-9]+|0x[0-9a-f]+", labels[-1]) or
        host.endswith((".local", ".internal", ".test", ".invalid", ".example", ".arpa", ".onion", ".alt", ".home", ".lan", ".corp", ".mail"))):
        raise ValueError("non_public_source_host")


def reporting_zone(name):
    """Read the pinned package bytes; host TZPATH and ZoneInfo cache are unused."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", name):
        raise ValueError("invalid_reporting_timezone")
    try:
        import tzdata
        if tzdata.__version__ != TZDATA_VERSION: raise ValueError("timezone_database_version_mismatch")
        with resources.files("tzdata.zoneinfo").joinpath(*name.split("/")).open("rb") as handle:
            return ZoneInfo.from_file(handle, key=name)
    except (ImportError, OSError, ZoneInfoNotFoundError): raise ValueError("timezone_database_unavailable") from None



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


@lru_cache(maxsize=128)
def session_close(market, session):
    import pandas_market_calendars as mcal
    schedule = mcal.get_calendar(MARKETS[market][1]).schedule(start_date=session, end_date=session)
    if len(schedule) != 1: raise ValueError("invalid_session")
    return schedule.iloc[0].market_close.to_pydatetime()


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
        archive = block.get('evidence_mode') == 'ARCHIVE_RECONSTRUCTION'
        if block.get('evidence_mode') not in (None,'CONTEMPORANEOUS','ARCHIVE_RECONSTRUCTION'):
            errors.append('evidence_mode_invalid')
        if archive:
            # Later retrieval is not later public availability. This exception
            # is limited to versioned factual price/financial observations;
            # today's company judgments or forecasts cannot be backdated.
            if block.get('unit') not in ('currency_per_share','currency_and_shares'):
                errors.append('archive_judgment_not_allowed')
            version=block.get('archive_version',{})
            if version.get('kind') not in ('ORIGINAL_FILING','HISTORICAL_MARKET_RECORD'):
                errors.append('archive_version_kind')
            if not re.fullmatch('[0-9a-f]{64}',str(version.get('raw_sha256',''))):errors.append('archive_version_hash')
            source_url(version.get('source'))
            if version.get('public_available_at')!=block.get('public_available_at'):
                errors.append('archive_availability_binding')
            if version.get('retrieved_at')!=block.get('first_seen_at'):errors.append('archive_retrieval_binding')
        for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"):
            if field not in block: errors.append(field + "_undeclared"); continue
            if block[field] is None:
                if field in ("public_available_at", "first_seen_at", "ingested_at"): errors.append(field + "_unknown")
            elif timestamp(block[field]) > (datetime.now(timezone.utc) if archive and field in ('first_seen_at','ingested_at') else cut):
                errors.append(field + "_after_cutoff")
        if timestamp(block["first_seen_at"]) > timestamp(block["ingested_at"]): errors.append("observation_order")
        if block.get("public_available_at") and timestamp(block["public_available_at"]) > timestamp(block["first_seen_at"]):
            errors.append("availability_after_observation")
        if block.get("published_at") and block.get("public_available_at") and timestamp(block["published_at"]) > timestamp(block["public_available_at"]):
            errors.append("publication_after_public_availability")
        if block.get("published_at") and timestamp(block["published_at"]) > timestamp(block["first_seen_at"]):
            errors.append("publication_after_observation")
        if block.get("data_hash") != digest(block.get("payload")): errors.append("data_hash_mismatch")
        period = block.get("report_period")
        if not isinstance(period, dict) or set(period) != {"start", "end"}: errors.append("report_period_missing")
        else:
            if not all(isinstance(period[k], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period[k]) for k in ("start", "end")):
                raise ValueError("report_period_date_format")
            start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
            if start > end: errors.append("report_period_reversed")
            for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"):
                if block.get("accounting_basis") != "RESEARCH_ASSUMPTION" and block.get(field) and end > timestamp(block[field]).date():
                    errors.append("period_after_" + field)
            if block.get("accounting_basis") in {"US_GAAP", "K_IFRS_CONSOLIDATED"}:
                # A date denotes the complete reporting day in the issuer's
                # explicit reporting timezone, not 00:00 UTC on that date.
                if not block.get("reporting_timezone"): errors.append("reporting_timezone_required")
                elif block["reporting_timezone"] != REPORTING_TIMEZONES.get(security["market"]):
                    errors.append("reporting_timezone_market_mismatch")
                else:
                    complete = datetime.combine(end + timedelta(days=1), time.min, tzinfo=reporting_zone(block["reporting_timezone"]))
                    for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"):
                        if block.get(field) and timestamp(block[field]) < complete:
                            errors.append("period_incomplete_at_" + field)
    except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError): errors.append("invalid_provenance")
    return sorted(set(errors))


def total_return_series(bars, basis):
    if basis not in {"raw_unadjusted", "split_adjusted"}: raise ValueError("price_basis_unverified")
    # Dividends arrive on the ex-date share basis. Split-adjusted closes are on
    # the final share basis, so prior dividends need the same subsequent splits.
    subsequent_splits = [1.] * len(bars)
    if basis == "split_adjusted":
        for i in range(len(bars)-1, 0, -1):
            subsequent_splits[i-1] = number(subsequent_splits[i] * number(bars[i]["split_ratio"], positive=True), positive=True)
    series = [1.]
    for i, (old, new) in enumerate(zip(bars, bars[1:]), 1):
        split = number(new["split_ratio"], positive=True)
        dividend = number(new["dividend"], nonnegative=True) / subsequent_splits[i]
        factor = split if basis == "raw_unadjusted" else 1.
        series.append(series[-1] * (number(new["close"], positive=True) + dividend) * factor / number(old["close"], positive=True))
    return series


def price_analysis(payload, market, cutoff, listing_board=None):
    latest = sessions(market, (timestamp(cutoff) - timedelta(days=20)).date().isoformat(), cutoff)[-1]
    if not payload.get("feed") or payload.get("quote_type") != "official_close": raise ValueError("close_feed_required")
    if payload.get("corporate_actions_status") not in {"available", "no_event"}: raise ValueError("corporate_actions_unverified")
    if payload.get("corporate_actions_through") != latest: raise ValueError("corporate_actions_stale")
    if payload.get("benchmark_actions_status") not in {"available", "no_event"}: raise ValueError("benchmark_actions_unverified")
    if payload.get("benchmark_actions_through") != latest: raise ValueError("benchmark_actions_stale")
    if payload.get("volume_unit") != "shares": raise ValueError("volume_unit_unverified")
    if payload.get("dividend_share_basis") != "ex_date": raise ValueError("dividend_share_basis_unverified")
    if payload.get("volume_basis") != payload.get("price_basis"): raise ValueError("price_volume_adjustment_mismatch")
    expected_benchmark = "SPY" if market == "US" else {"KOSPI": "KOSPI200", "KOSDAQ": "KOSDAQ150"}.get(listing_board)
    if expected_benchmark is None: raise ValueError("listing_board_unverified")
    if payload.get("benchmark_id") != expected_benchmark: raise ValueError("benchmark_identity_mismatch")
    expected_return_kind = "PRICE_AND_DISTRIBUTIONS" if market == "US" else "TOTAL_RETURN_INDEX"
    if payload.get("benchmark_return_kind") != expected_return_kind: raise ValueError("benchmark_return_kind_mismatch")
    bars, benchmark = payload["bars"], payload["benchmark_bars"]
    if expected_return_kind == "TOTAL_RETURN_INDEX" and any(b["dividend"] != 0 or b["split_ratio"] != 1 for b in benchmark):
        raise ValueError("total_return_index_action_double_count")
    if not bars or not benchmark: raise ValueError("price_missing")
    for rows, action_status in ((bars, payload["corporate_actions_status"]), (benchmark, payload["benchmark_actions_status"])):
        ds = [b["session"] for b in rows]
        if ds != sorted(set(ds)): raise ValueError("price_duplicate_or_unsorted")
        if ds[-1] != latest: raise ValueError("stale_or_future_price")
        if tuple(ds) != sessions(market, ds[0], cutoff): raise ValueError("calendar_gap_or_non_session")
        for b in rows:
            number(b["close"], positive=True)
            if rows is bars: number(b["volume"], nonnegative=True)
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


def financial_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("financial_date_only_required")
    return date.fromisoformat(value)


def financial_errors(block, market, cutoff):
    errors = []
    try:
        f = block["payload"]; p = f["period"]
        start, end = financial_date(p["start"]), financial_date(p["end"])
        if not 350 <= (end-start).days <= 380: errors.append("ttm_period_invalid")
        age = (timestamp(cutoff).date() - end).days
        if age < 0 or age > 210: errors.append("financials_future_or_stale")
        expected_basis = "US_GAAP" if market == "US" else "K_IFRS_CONSOLIDATED"
        if block["accounting_basis"] != expected_basis: errors.append("accounting_basis_unverified")
        if block["unit"] != "currency_and_shares": errors.append("financial_unit_mismatch")
        metrics = f["ttm"]
        for k in ("revenue", "ebitda", "net_income", "operating_cash_flow", "capex", "fcf", "sbc", "net_debt", "diluted_shares"):
            number(metrics[k], positive=k in {"revenue", "diluted_shares"}, nonnegative=k in {"capex", "sbc"})
        if not math.isclose(metrics["fcf"], metrics["operating_cash_flow"] - metrics["capex"], rel_tol=0., abs_tol=.01): errors.append("fcf_identity_mismatch")
        if p != block.get("report_period"): errors.append("financial_report_period_mismatch")
        for field, bounds in (("recent_quarters", (70, 110)), ("recent_annual", (350, 380))):
            if not f.get(field): errors.append(field + "_missing")
            ends = [row["end"] for row in f.get(field, [])]
            if len(ends) != len(set(ends)): errors.append(field + "_duplicate")
            if ends and field == "recent_quarters" and max(ends) != p["end"]: errors.append("recent_quarters_not_current")
            if ends and field == "recent_annual" and (end - financial_date(max(ends))).days > 370:
                errors.append("recent_annual_stale")
            ordered = sorted(f.get(field, []), key=lambda row: row["start"])
            for previous, current in zip(ordered, ordered[1:]):
                if financial_date(current["start"]) != financial_date(previous["end"]) + timedelta(days=1):
                    errors.append(field + "_gap_or_overlap")
            for row in f.get(field, []):
                s, e = financial_date(row["start"]), financial_date(row["end"])
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
    validate_persistable_sources(bundle, real=bundle.get("data_kind") == "REAL")
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
        for key, unit in {"price": "currency_per_share", "financials": "currency_and_shares", "thesis": "text", "risk": "fraction"}.items():
            if not coverage[key] and blocks[key].get("unit") != unit: coverage[key].append("unit_mismatch")
        for k, reasons in coverage.items(): errors += [k + ":" + e for e in reasons]
        discovery = None
        if not coverage["price"]:
            try:
                price = blocks["price"]
                discovery = price_analysis(price["payload"], market, cutoff, s.get("listing_board"))
                bars = price["payload"]["bars"]
                if price["report_period"] != {"start": bars[0]["session"], "end": bars[-1]["session"]}:
                    errors.append("price:report_period_bar_range_mismatch")
                close = session_close(market, discovery["required_session"])
                for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"):
                    if price.get(field) and timestamp(price[field]) < close:
                        errors.append("price:" + field + "_before_official_close")
            except (ValueError, KeyError, TypeError, IndexError) as exc: errors.append("price:" + str(exc))
        method_eligibility = None
        if not coverage["financials"]:
            financial_blockers = financial_errors(blocks["financials"], market, cutoff)
            errors += financial_blockers
            if not financial_blockers:
                ttm = blocks["financials"]["payload"]["ttm"]
                method_eligibility = {"PE": ttm["net_income"] > 0, "EV_EBITDA": ttm["ebitda"] > 0}
        if not coverage["thesis"] and not coverage["risk"]: errors += thesis_risk_errors(blocks)
        optional = copy.deepcopy(s.get("optional", {}))
        for key, block in optional.items():
            if block.get("status") not in STATUSES: raise ValueError("optional_status_invalid")
            if block.get("status") == "available":
                es = envelope_errors(block, s, cutoff)
                if es: optional[key] = {"status": "unverified", "reasons": es}
        s.update(data_quality_pass=not errors, blockers=sorted(set(errors)), coverage=coverage,
                 discovery=discovery, required_session=discovery["required_session"] if discovery else None,
                 optional=optional, valuation_method_eligibility=method_eligibility, historical_pit_verified=False, consensus_revision=None)
        rows.append(s)
    result = {"schema_version": "research-market-export-v1", "market": market,
              "data_kind": bundle["data_kind"], "decision_cutoff": cutoff,
              "calendar_engine": {"name": "pandas_market_calendars", "version": CALENDAR_VERSION},
              "reporting_timezone_database": {"name": "tzdata", "version": TZDATA_VERSION, "lookup": "package_bytes"},
              "admission_source": {"path": "tools/research_decision_v1/data.py", "sha256": _ADMISSION_SOURCE_HASH, "basis": "source_bytes_lf_captured_at_import"},
              "source_input_hash": digest(bundle), "input_snapshot": copy.deepcopy(bundle),
              "securities": sorted(rows, key=lambda s: str(s["security_id"])),
              "orders_allowed": False}
    result["export_hash"] = digest(result)
    return result
