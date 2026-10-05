"""#576: report-only A4 context joining #388 and #450; no network or policy.

Reuse #388 CSV normalizers and Free Market Context V1/C1. The strict wrapper
preserves null rows dropped by legacy normalizers. Raw observations, current-
vintage context, vendor lookbacks and portfolio authority stay separate.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from tools import free_market_context as f

SCHEMA = "chameleon-market-context-v2"
SAFETY = {**f.SAFETY, "report_only": True, "regime_authorized": False,
          "orders_generated": False, "automatic_dispatch_allowed": False}
# key: (logical ID, unit, max observation age in calendar days, evidence family)
# Age limits are research freshness policy, not risk or trading thresholds.
SERIES = {
    "fred:VIXCLS": ("vix_30d", "index", 5, "OPTION_VARIANCE"),
    "fred:VXVCLS": ("vix_3m", "index", 5, "OPTION_VARIANCE"),
    "cboe:VIX": ("vix_30d", "index", 5, "OPTION_VARIANCE"),
    "cboe:VIX3M": ("vix_3m", "index", 5, "OPTION_VARIANCE"),
    "cboe:VIX9D": ("vix_9d", "index", 5, "OPTION_VARIANCE"),
    "cboe:VVIX": ("vvix", "index", 5, "OPTION_VARIANCE"),
    "cboe:SKEW": ("skew_index", "index", 5, "OPTION_TAIL_PRICE"),
    "fred:BAMLH0A0HYM2": ("hy_oas", "percent", 5, "CREDIT"),
    "fred:NFCI": ("nfci", "index", 14, "FINANCIAL_CONDITIONS_COMPOSITE"),
    "fred:DGS2": ("yield_2y", "percent", 5, "RATES"),
    "fred:DGS10": ("yield_10y", "percent", 5, "RATES"),
    "fred:DFII10": ("real_yield_10y", "percent", 5, "RATES"),
    "fred:SOFR": ("sofr", "percent", 5, "FUNDING"),
    "fred:IORB": ("iorb", "percent", 5, "FUNDING"),
    "fred:WALCL": ("fed_assets", "millions_usd", 14, "LIQUIDITY"),
    "fred:WTREGEN": ("tga_weekly_average", "millions_usd", 14, "LIQUIDITY"),
    "fred:RRPONTSYD": ("rrp_daily", "billions_usd", 5, "LIQUIDITY"),
    "fred:ICSA": ("initial_claims", "persons", 14, "LABOR"),
    "fred:DTWEXBGS": ("broad_usd", "index", 7, "FX"),
}


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def encoded(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
        f.strict_json(raw)  # common bounds/duplicate/nonfinite/type checks
        return raw
    except (TypeError, ValueError, RecursionError):
        raise f.ContextError("CONTEXT_NOT_BOUNDED_JSON") from None


def no_authority(value: dict) -> None:
    f.require(type(value) is dict and all(value.get(k) is False for k in f.SAFETY),
              "INPUT_AUTHORITY_CONFLICT")


def macro_source_rows(raw: bytes, *, source_id: str, collected_at: str, cutoff: str) -> list[dict]:
    """Use #388 normalizers, retaining all original null observations.

    Source is supplied by a reviewed manifest, not inferred from a filename.
    The function does not fetch data, certify a license or infer original release
    time. All returned observations become available only at collection.
    """
    f.require(source_id in SERIES, "UNREGISTERED_MACRO_SOURCE")
    provider, symbol = source_id.split(":")
    logical, unit, age, family = SERIES[source_id]
    meta = f.provenance(raw, provider=provider.upper(), dataset="CURRENT_VINTAGE_INDEX_OR_MACRO",
                        collected_at=collected_at, cutoff=cutoff)
    original = f.csv_records(raw)
    f.require(bool(original), "EMPTY_MACRO_SOURCE")
    normalized, expected, seen = [], {}, set()
    for row in original:
        keys = {k.strip().lower(): k for k in row}
        f.require(len(keys) == len(row), "MACRO_HEADER_COLLISION")
        dates = [keys[k] for k in ("date", "observation_date") if k in keys]
        candidates = [keys[k] for k in ({symbol.lower()} if provider == "fred" else {symbol.lower(), "close"}) if k in keys]
        f.require(len(dates) == 1 and len(candidates) == 1, "MACRO_COLUMN_IDENTITY")
        label = row[dates[0]]
        try:
            observed = f.iso_date(label).isoformat()
        except f.ContextError:
            f.require(provider == "cboe" and re.fullmatch(r"\d{2}/\d{2}/\d{4}", label) is not None,
                      "MACRO_DATE_FORMAT")
            try:
                observed = datetime.strptime(label, "%m/%d/%Y").date().isoformat()
            except ValueError:
                raise f.ContextError("MACRO_DATE_FORMAT") from None
        f.require(observed not in seen, "DUPLICATE_MACRO_DATE"); seen.add(observed)
        text = row[candidates[0]]
        value = None if text in ("", ".", "NA", "N/A") else f.number(text)
        # A volatility index level cannot be zero or negative. Null is distinct.
        if logical in {"vix_9d", "vix_30d", "vix_3m", "vvix", "skew_index"}:
            f.require(value is None or value > 0, "NONPOSITIVE_VOLATILITY_INDEX")
        normalized.append(f.record(meta, logical, observed, "level", value, unit,
                          source_id=source_id, family=family, max_age_days=age,
                          truth_class="FREE_PROXY_CURRENT_VINTAGE"))
        if value is not None:
            expected[observed] = value
    # Native import in production. Packaged tests use clearly labeled source-function
    # fixtures from the pinned source; those fixtures must never replace native code.
    from tools import build_run287_chameleon_macro_inputs as old
    frame = old.normalize_fred(raw, symbol) if provider == "fred" else old.normalize_cboe(raw, symbol)
    daycol = "observation_date" if provider == "fred" else "date"
    actual = {str(row[daycol].date()): float(row["value"]) for _, row in frame.iterrows()}
    f.require(actual == expected, "PR388_NORMALIZATION_PARITY")
    return sorted(normalized, key=lambda r: r["observation_date"])


def macro_panel(rows: list[dict], *, cutoff: str) -> dict:
    """Source-specific visible vintages; missing latest never resurrects old data."""
    f.require(type(rows) is list and len(rows) <= f.MAX_ROWS, "MACRO_ROW_BUDGET")
    decision = f.utc(cutoff)
    by_series, provider_for = defaultdict(dict), {}
    for row in rows:
        no_authority(row)
        source = row.get("source_id")
        f.require(source in SERIES, "MACRO_ROW_SOURCE")
        logical, unit, age, family = SERIES[source]
        f.require(row.get("provider") == source.split(":")[0].upper()
                  and row.get("dataset") == "CURRENT_VINTAGE_INDEX_OR_MACRO", "MACRO_PROVIDER_BINDING")
        f.require(row.get("entity_id") == logical and row.get("unit") == unit
                  and row.get("metric") == "level" and row.get("family") == family
                  and row.get("max_age_days") == age, "MACRO_ROW_SEMANTICS")
        available, collected = f.utc(row["available_at"]), f.utc(row["collected_at"])
        day = f.iso_date(row["observation_date"])
        f.require(available >= collected and day <= collected.date(), "MACRO_ROW_CLOCK")
        f.require(re.fullmatch(r"[a-f0-9]{64}", row.get("source_sha256", "")) is not None,
                  "MACRO_ROW_HASH")
        if available > decision:
            continue
        value = f.number(row["value"])
        if logical in {"vix_9d", "vix_30d", "vix_3m", "vvix", "skew_index"}:
            f.require(value is None or value > 0, "NONPOSITIVE_VOLATILITY_INDEX")
        prior_provider = provider_for.setdefault(logical, source)
        f.require(prior_provider == source, "CHOOSE_ONE_PROVIDER_PER_LOGICAL_SERIES")
        old = by_series[source].get(day)
        if old is not None and f.utc(old["available_at"]) == available:
            f.require(old == row, "CONFLICTING_MACRO_VINTAGE")
        if old is None or f.utc(old["available_at"]) < available:
            by_series[source][day] = row
    panel = {}
    for source, dated in sorted(by_series.items()):
        logical, _, age, _ = SERIES[source]
        ordered = [dated[d] for d in sorted(dated)]
        ctx = f.trailing_context(ordered, cutoff=cutoff, max_age_days=age, lookback=252, minimum=20)[0]
        prev = ordered[-2] if len(ordered) >= 2 else None
        previous = None if prev is None else f.number(prev["value"])
        # Delta uses consecutive visible observations, not an assumed trading day.
        previous_fresh = prev is not None and (decision.date()-f.iso_date(prev["observation_date"])).days <= age
        current = ctx["current_value"]
        change = None if previous is None or current is None or not previous_fresh else current-previous
        f.require(change is None or math.isfinite(change), "MACRO_DELTA_OVERFLOW")
        panel[logical] = {"source_id": source, "family": SERIES[source][3], "status": ctx["status"],
            "value": current, "unit": ctx["unit"], "observation_date": ctx["observation_date"],
            "available_at": ctx["available_at"], "source_sha256": ctx["source_sha256"],
            "previous_observation_date": None if prev is None else prev["observation_date"],
            "change_from_previous_observation": change, "trailing_midrank": ctx["trailing_midrank"],
            "history_count": ctx["history_count"], "truth_class": "FREE_PROXY_CURRENT_VINTAGE"}
    return panel


def derived_macro(panel: dict) -> dict:
    """Only exact-observation-date matches; never align by convenient old values."""
    definitions = {
        "vix30_to_vix3m": ("vix_30d", "vix_3m", "ratio", "ratio"),
        "vix9d_to_vix30": ("vix_9d", "vix_30d", "ratio", "ratio"),
        "sofr_minus_iorb": ("sofr", "iorb", "difference", "percentage_points"),
        "yield10y_minus_2y": ("yield_10y", "yield_2y", "difference", "percentage_points"),
    }
    result = {}
    for name, (left, right, op, unit) in definitions.items():
        a, b = panel.get(left), panel.get(right)
        reason = ("MISSING_INPUT" if a is None or b is None else
                  "INPUT_NOT_OBSERVED" if a["status"] != "OBSERVED" or b["status"] != "OBSERVED" else
                  "OBSERVATION_DATE_MISMATCH" if a["observation_date"] != b["observation_date"] else
                  "UNIT_MISMATCH" if a["unit"] != b["unit"] else
                  "ZERO_DENOMINATOR" if op == "ratio" and b["value"] == 0 else None)
        value = None
        if reason is None:
            value = a["value"] / b["value"] if op == "ratio" else a["value"]-b["value"]
            if not math.isfinite(value):
                reason, value = "NONFINITE_DERIVATION", None
        result[name] = {"value": value, "unit": unit, "status": reason or "OBSERVED",
            "observation_date": None if reason else a["observation_date"],
            "input_keys": [left, right],
            "available_at": None if reason else max(f.utc(a["available_at"]), f.utc(b["available_at"])).isoformat()}
    return result


def normalize_public_row(row: dict) -> dict:
    """Copy the four existing parser contracts; do not attest their producers."""
    no_authority(row)
    provider = row.get("provider")
    f.require(type(provider) is str and provider in {"CFTC", "FINRA", "CBOE", "AAII"}, "PUBLIC_SOURCE_UNSUPPORTED")
    dataset, entity = row.get("dataset"), row.get("entity_id")
    metric, unit = row.get("metric"), row.get("unit")
    f.require(all(type(x) is str for x in (dataset, metric, unit)), "PUBLIC_IDENTITY_DOMAIN")
    f.require(type(entity) is str, "PUBLIC_ENTITY_DOMAIN")
    f.require("value" in row, "PUBLIC_VALUE_REQUIRED")
    value = f.number(row.get("value"), integral=provider == "CFTC" and metric == "net_contracts")
    normalized = {**row, "value": value}
    if provider == "AAII":
        f.require(dataset == "AUTHORIZED_SURVEY_EXPORT" and entity == "RESPONDENTS"
                  and metric == "bull_minus_bear" and unit == "fraction", "PUBLIC_AAII_DOMAIN")
        f.require(value is None or -1 <= value <= 1, "PUBLIC_AAII_RANGE")
    elif provider == "FINRA":
        f.require(dataset == "CNMS_SHORT_VOLUME" and metric == "short_volume_fraction"
                  and unit == "fraction" and re.fullmatch(r"[A-Za-z0-9.\-/]{1,14}", entity) is not None,
                  "PUBLIC_FINRA_DOMAIN")
        f.require(value is None or 0 <= value <= 1, "PUBLIC_FINRA_RANGE")
    elif provider == "CBOE":
        f.require(entity in {"EQUITY", "INDEX", "TOTAL"} and dataset == "PUT_CALL_" + entity
                  and metric == "put_call_volume_ratio" and unit == "ratio", "PUBLIC_CBOE_DOMAIN")
        f.require(value is None or value >= 0, "PUBLIC_CBOE_RANGE")
    else:
        groups = ({"DEALER", "ASSET_MANAGER", "LEVERAGED_MONEY", "OTHER_REPORTABLE", "NONREPORTABLE"}
                  if dataset == "TFF_FUTURES" else
                  {"PRODUCER_MERCHANT", "SWAP_DEALER", "MANAGED_MONEY", "OTHER_REPORTABLE", "NONREPORTABLE"})
        parts = entity.split(":")
        f.require(dataset in {"TFF_FUTURES", "DISAGG_FUTURES"} and len(parts) == 2
                  and re.fullmatch(r"[A-Za-z0-9]{6}", parts[0]) is not None
                  and parts[1] in groups and row.get("group") == parts[1]
                  and (metric, unit) in {("net_contracts", "contracts"), ("net_fraction_oi", "fraction")},
                  "PUBLIC_CFTC_DOMAIN")
        oi = f.number(row.get("open_interest"), integral=True, nonnegative=True)
        long = f.number(row.get("long_contracts"), integral=True, nonnegative=True)
        short = f.number(row.get("short_contracts"), integral=True, nonnegative=True)
        f.require(oi is not None and (long is None or long <= oi) and (short is None or short <= oi),
                  "PUBLIC_CFTC_OPEN_INTEREST")
        if value is not None:
            f.require(long is not None and short is not None, "PUBLIC_CFTC_NET_MISSING_INPUT")
            net = long - short
            expected = net if metric == "net_contracts" else (None if oi == 0 else net / oi)
            f.require(expected is not None and value == expected, "PUBLIC_CFTC_NET_VALUE")
        normalized.update(open_interest=oi, long_contracts=long, short_contracts=short)
    return normalized


def public_panel(rows: list[dict], *, cutoff: str) -> list[dict]:
    """CFTC is positioning; FINRA is venue-limited activity; surveys aren't trades."""
    f.require(type(rows) is list and len(rows) <= f.MAX_ROWS, "PUBLIC_ROW_BUDGET")
    groups = defaultdict(list)
    for row in rows:
        normalized = normalize_public_row(row)
        groups[normalized["provider"]].append(normalized)
    ages = {"CFTC": 14, "FINRA": 5, "CBOE": 5, "AAII": 14}
    result = []
    for provider in sorted(groups):
        result.extend(f.trailing_context(groups[provider], cutoff=cutoff, max_age_days=ages[provider]))
    return sorted(result, key=lambda r: (r["provider"], r["dataset"], r["entity_id"], r["metric"], r["unit"]))


def validate_prices(rows: list[dict], *, cutoff: str, expected_session: str) -> list[dict]:
    f.require(type(rows) is list and len(rows) <= 10001, "PRICE_CONTEXT_BUDGET")
    decision = f.utc(cutoff); session = f.iso_date(expected_session)
    f.require(session <= decision.date(), "FUTURE_EXPECTED_SESSION")
    names, cleaned = set(), []
    for row in rows:
        no_authority(row)
        f.require(row["cohort"] not in names, "DUPLICATE_PRICE_COHORT"); names.add(row["cohort"])
        f.require(f.utc(row["available_at"]) >= f.utc(row["collected_at"])
                  and f.utc(row["available_at"]) <= decision
                  and f.utc(row["mapping_available_at"]) <= f.utc(row["available_at"]), "PRICE_CLOCK")
        f.require(f.iso_date(row["session"]) <= f.utc(row["collected_at"]).date(), "FUTURE_PRICE_SESSION")
        members = row["members"]
        f.require(type(members) is list and 0 < len(members) <= 10000 and len(set(members)) == len(members)
                  and all(type(x) is str and x for x in members), "PRICE_MEMBERSHIP")
        f.require(re.fullmatch(r"[a-f0-9]{64}", row.get("source_sha256", "")) is not None, "PRICE_SOURCE_HASH")
        counts = [f.number(row[x], integral=True, nonnegative=True) for x in
                  ("advancers", "decliners", "unchanged", "missing_return_count")]
        f.require(all(x is not None for x in counts) and sum(counts) == len(members), "BREADTH_DENOMINATOR")
        median = f.number(row["median_return_1d"])
        f.require(median is None or median > -1, "MEDIAN_PRICE_RETURN")
        f.require(type(row["metrics"]) is dict and len(row["metrics"]) <= 100, "PRICE_METRIC_BUDGET")
        normalized_metrics = {}
        for name, spec in row["metrics"].items():
            eligible = f.number(spec["eligible_count"], integral=True, nonnegative=True)
            expected = f.number(spec["expected_count"], integral=True, nonnegative=True)
            value = f.number(spec["value"])
            f.require(eligible is not None and expected == len(members) and eligible <= expected,
                      "METRIC_COVERAGE")
            f.require(value is None or eligible > 0, "VALUE_WITHOUT_ELIGIBLE_MEMBERS")
            if name.startswith("pct_above_ma"):
                f.require(value is None or 0 <= value <= 1, "BREADTH_FRACTION_RANGE")
            normalized_metrics[name] = {**spec, "eligible_count": eligible, "expected_count": expected, "value": value}
        cleaned.append({**row, **dict(zip(("advancers", "decliners", "unchanged", "missing_return_count"), counts)),
                        "median_return_1d": median, "metrics": normalized_metrics,
                        "context_status": "OBSERVED" if row["session"] == expected_session else "WAIT_EXPECTED_SESSION"})
    return f.strict_json(encoded(sorted(cleaned, key=lambda r: r["cohort"])))


def build_context(*, macro_rows: list[dict], public_rows: list[dict], price_rows: list[dict],
                  calendar_result: dict | None, security_map: dict | None,
                  security_map_available_at: str | None, cutoff: str, expected_session: str) -> dict:
    """No scores, portfolio weights, new risk regime, or economic promotion.

    The CLI binds input bytes. This function checks semantics, not external
    producer authenticity. H1 diagnostics retain closed downstream authority.
    """
    f.utc(cutoff); f.iso_date(expected_session)
    macro = macro_panel(macro_rows, cutoff=cutoff)
    derivatives = derived_macro(macro)
    public = public_panel(public_rows, cutoff=cutoff)
    prices = validate_prices(price_rows, cutoff=cutoff, expected_session=expected_session)
    paired = []
    security_map_binding = None
    calendar_theme_map_binding = None
    if calendar_result is not None:
        theme_hash = calendar_result.get("mapping_sha256")
        f.require(type(theme_hash) is str and re.fullmatch(r"[a-f0-9]{64}", theme_hash) is not None,
                  "CALENDAR_THEME_MAPPING_HASH")
        theme_clock = f.utc(calendar_result.get("mapping_available_at"))
        f.require(theme_clock <= f.utc(cutoff), "FUTURE_CALENDAR_CONTEXT")
        source = calendar_result["source"]
        f.require(f.utc(source["collected_at"]) <= f.utc(source["available_at"]) <= f.utc(cutoff),
                  "CALENDAR_SOURCE_CLOCK")
        f.require(re.fullmatch(r"[a-f0-9]{64}", source.get("source_sha256", "")) is not None,
                  "CALENDAR_SOURCE_HASH")
        bundle = f.compose_research_context(prices, calendar_result, [], security_map=security_map,
                    security_map_available_at=security_map_available_at, cutoff=cutoff, expected_session=expected_session)
        calendar_theme_map_binding = {"mapping_sha256": theme_hash,
                                      "mapping_available_at": theme_clock.isoformat()}
        security_map_binding = {
            "mapping_sha256": bundle["section_sha256"]["explicit_security_map"],
            "mapping_available_at": f.utc(security_map_available_at).isoformat(),
            "identity_binding": bundle["identity_binding"],
        }
        for pair in bundle["paired_themes"]:
            cal = pair["calendar_context"]
            expected = f.number(cal["expected_symbol_count"], integral=True, nonnegative=True)
            computable = f.number(cal["computable_symbol_count"], integral=True, nonnegative=True)
            missing = f.number(cal["missing_symbol_count"], integral=True, nonnegative=True)
            fraction = f.number(cal["vendor_positive_change_fraction"])
            f.require(expected is not None and expected > 0 and computable is not None and missing is not None
                      and expected == len(cal["requested_symbols"]) and computable+missing == expected,
                      "CALENDAR_COVERAGE_DENOMINATOR")
            f.require(f.number(cal["coverage_fraction"]) == computable/expected
                      and (fraction is None if computable == 0 else fraction is not None and 0 <= fraction <= 1),
                      "CALENDAR_COVERAGE_FRACTION")
            age = (f.utc(cutoff)-f.utc(calendar_result["source"]["collected_at"])).total_seconds()/86400
            status = pair["status"] if age <= 4 else "STALE_CALENDAR_CONTEXT"
            px = pair["price_context"]
            paired.append({"theme": pair["theme"], "relative_horizon": pair["relative_horizon"],
                "status": status, "price_return_window": "1_SESSION", "estimate_window": "VENDOR_30_CALENDAR_DAYS",
                "median_price_return": None if px is None or status != "PAIRED_DIAGNOSTICS_NOT_ALPHA" else px["median_return_1d"],
                "positive_vendor_revision_fraction": fraction if status == "PAIRED_DIAGNOSTICS_NOT_ALPHA" else None,
                "estimate_coverage": computable/expected, "price_return_coverage": None if px is None else
                    1-px["missing_return_count"]/len(px["members"]),
                "basis": cal["basis"], "sector_rank": None, "independent_alpha_votes": None,
                "source_refs": {"price_sha256": None if px is None else px["source_sha256"],
                                "calendar_sha256": source["source_sha256"]}})
    # Descriptions only. Not calibrated distress probabilities or contrarian signals.
    diagnostics = []
    term = derivatives["vix30_to_vix3m"]
    if term["status"] == "OBSERVED":
        diagnostics.append({"code": "FRONT_IV_ABOVE_3M" if term["value"] > 1 else
                            "FRONT_IV_NOT_ABOVE_3M", "families": ["OPTION_VARIANCE"],
                            "inputs": ["vix30_to_vix3m"]})
    market = next((p for p in prices if p["cohort"] == "__MARKET__" and p["context_status"] == "OBSERVED"), None)
    credit = macro.get("hy_oas")
    if market is not None and market["missing_return_count"] == 0 and credit is not None:
        change = credit["change_from_previous_observation"]
        # Opposite direction observations only when their latest dates are equal.
        if change is not None and credit["observation_date"] == expected_session:
            median = market["median_return_1d"]
            if median is not None and median < 0 and change > 0:
                diagnostics.append({"code": "MEDIAN_PRICE_DOWN_CREDIT_SPREAD_UP", "families": ["MARKET_PRICE", "CREDIT"],
                                    "inputs": ["median_return_1d", "hy_oas_change"]})
    # Cross-family/paired observations, not a fitted entry/exit rule. No missing
    # participant is silently removed. Price and vendor lookback windows differ.
    for pair in paired:
        if (pair["status"] == "PAIRED_DIAGNOSTICS_NOT_ALPHA"
                and pair["estimate_coverage"] == 1 and pair["price_return_coverage"] == 1
                and pair["median_price_return"] is not None):
            positive = pair["positive_vendor_revision_fraction"]
            move = pair["median_price_return"]
            code = ("PRICE_UP_VENDOR_REVISIONS_MAJORITY_POSITIVE" if move > 0 and positive > .5 else
                    "PRICE_DOWN_VENDOR_REVISIONS_MAJORITY_POSITIVE" if move < 0 and positive > .5 else
                    "PRICE_UP_WITHOUT_POSITIVE_REVISION_MAJORITY" if move > 0 and positive <= .5 else None)
            if code:
                diagnostics.append({"code":code,"theme":pair["theme"],
                    "relative_horizon":pair["relative_horizon"],
                    "families":["THEME_PRICE","VENDOR_EARNINGS_LOOKBACK"],
                    "window_caveat":"1_SESSION_PRICE_VS_30_CALENDAR_DAY_VENDOR_LOOKBACK",
                    "inputs":pair["source_refs"]})
    if market is not None and market["missing_return_count"] == 0:
        median = market["median_return_1d"]
        if median is not None and median > 0 and term["status"] == "OBSERVED" and term["value"] > 1:
            if term["observation_date"] == expected_session:
                diagnostics.append({"code":"PRICE_UP_WITH_FRONT_IV_INVERSION",
                    "families":["MARKET_PRICE","OPTION_VARIANCE"],
                    "inputs":["median_return_1d","vix30_to_vix3m"]})
        bullish_surveys=[v for v in public if v["provider"]=="AAII" and v["metric"]=="bull_minus_bear"
                         and v["status"]=="OBSERVED" and v["current_value"]>0]
        if median is not None and median < 0 and bullish_surveys:
            diagnostics.append({"code":"BULLISH_SURVEY_WITH_PRICE_DECLINE",
                "families":["SURVEY_OPINION","MARKET_PRICE"],
                "window_caveat":"WEEKLY_SURVEY_VS_1_SESSION_PRICE_NOT_A_CONTRARIAN_BUY",
                "inputs":["AAII_bull_minus_bear","median_return_1d"]})
    usable_breadth = market is not None and (
        market["missing_return_count"] < len(market["members"])
        or any(spec["value"] is not None and spec["eligible_count"] > 0
               for spec in market["metrics"].values()))
    family_presence = {
        "macro": sorted({v["family"] for v in macro.values() if v["status"] == "OBSERVED" and not v["family"].startswith("OPTION_")}),
        "options": sorted({v["family"] for v in macro.values() if v["status"] == "OBSERVED" and v["family"].startswith("OPTION_")}),
        "breadth": ["MARKET_PRICE"] if usable_breadth else [],
        "positioning": sorted({r["provider"] for r in public if r["status"] == "OBSERVED" and r["provider"] == "CFTC"}),
        "short_sale_activity": sorted({r["provider"] for r in public if r["status"] == "OBSERVED" and r["provider"] == "FINRA"}),
        "survey_or_put_call": sorted({r["provider"] for r in public if r["status"] == "OBSERVED" and r["provider"] in {"AAII", "CBOE"}}),
    }
    # FINRA venue activity is an optional diagnostic, not futures positioning.
    missing = [k for k in ("macro", "options", "breadth", "positioning", "survey_or_put_call")
               if not family_presence[k]]
    result = {"schema": SCHEMA, "status": "PARTIAL_RESEARCH_CONTEXT" if missing else "RESEARCH_CONTEXT_COMPOSED",
        "cutoff": cutoff, "expected_price_session": expected_session, "macro": macro,
        "derived_macro": derivatives, "public": public, "price": prices, "paired_themes": paired,
        "security_map_binding": security_map_binding,
        "calendar_theme_map_binding": calendar_theme_map_binding,
        "diagnostics": diagnostics, "family_presence": family_presence, "missing_families": missing,
        "regime": None, "input_producer_authenticated": False, "independent_alpha_votes": None,
        "known_overlap": ["VIX/VIX3M/VIX9D/VVIX share option-variance family",
                          "NFCI overlaps credit/rates; not another independent vote",
                          "theme returns and market breadth share underlying prices"], **SAFETY}
    result["content_sha256"] = digest(result)
    return result


def verify_context(value: dict) -> None:
    f.require(type(value) is dict and value.get("schema") == SCHEMA, "CONTEXT_SCHEMA")
    f.require(all(value.get(k) == v and type(value.get(k)) is type(v) for k,v in SAFETY.items()), "CONTEXT_AUTHORITY")
    f.require(value.get("regime") is None and value.get("input_producer_authenticated") is False, "CONTEXT_AUTHORITY")
    f.require(value.get("content_sha256") == digest({k:v for k,v in value.items() if k != "content_sha256"}), "CONTEXT_HASH")


def context_delta(previous: dict | None, current: dict) -> dict:
    """Suppress unchanged analysis, never expiry. Suggestions only, no dispatcher."""
    verify_context(current)
    if previous is not None:
        verify_context(previous)
        f.require(f.utc(previous["cutoff"]) <= f.utc(current["cutoff"]), "CONTEXT_TIME_REGRESSION")
    def fingerprint(value):
        if value is None:
            return None
        # Remove collection transport identity only; retain date, status, coverage,
        # values and known limitations. Freshness changes are therefore visible.
        omit = {"cutoff", "available_at", "collected_at", "source_sha256", "content_sha256",
                "price_sha256", "calendar_sha256"}
        def clean(obj):
            if type(obj) is dict:
                return {k:clean(v) for k,v in obj.items() if k not in omit}
            if type(obj) is list:
                return [clean(x) for x in obj]
            return obj
        return digest(clean(value))
    unchanged = fingerprint(previous) == fingerprint(current)
    return {"status": "SKIP_UNCHANGED_CONTEXT" if unchanged else "CONTEXT_CHANGED_REVIEW_ONLY",
            "previous_sha256": None if previous is None else previous["content_sha256"],
            "current_sha256": current["content_sha256"],
            "suggested_consumers": [] if unchanged else ["A4_CONTEXT_REVIEW", "A2_A3_PAIRED_CONTEXT_REVIEW"], **SAFETY}
