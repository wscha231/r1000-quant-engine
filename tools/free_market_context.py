"""Free source observations and #450 context, never an investment authority.

No I/O at import. Network collection lives in the separate bounded capture CLI.
Current downloads are available only from collection, never their historical
observation dates. Unknowns, unavailable input and semantic mismatches fail shut.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_BYTES = 8_000_000
MAX_ROWS = 100_000
SCHEMA = "free-market-context-v1"
SAFETY = {"h2_eligible": False, "historical_pit_certified": False,
          "ranking_allowed": False, "portfolio_mutation_allowed": False,
          "production_activation_allowed": False}

class ContextError(ValueError):
    """Static error code only; do not expose untrusted payloads or credentials."""


def require(test, code):
    if not test:
        raise ContextError(code)


def utc(value):
    require(type(value) is str and len(value) <= 40, "EXACT_UTC_CLOCK_REQUIRED")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(t.tzinfo is not None and t.utcoffset() is not None, "EXACT_UTC_CLOCK_REQUIRED")
        return t.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ContextError("EXACT_UTC_CLOCK_REQUIRED") from None


def iso_date(value):
    require(type(value) is str, "EXACT_DATE_REQUIRED")
    try:
        d = date.fromisoformat(value)
        require(d.isoformat() == value, "EXACT_DATE_REQUIRED")
        return d
    except ValueError:
        raise ContextError("EXACT_DATE_REQUIRED") from None


def number(value, *, integral=False, nonnegative=False):
    if value is None or value == "":
        return None
    require(type(value) in (str, int, float), "INVALID_NUMBER_TYPE")
    require(len(str(value)) <= 100, "NUMBER_LIMIT")
    try:
        d = Decimal(str(value))
        require(d.is_finite(), "NONFINITE_NUMBER")
        require(not nonnegative or d >= 0, "NEGATIVE_COUNT")
        require(not integral or (d == d.to_integral_value() and abs(d) <= 10**15),
                "INVALID_INTEGER")
        f = float(d)
        require(math.isfinite(f) and (f != 0 or d == 0), "NUMBER_RANGE_OR_UNDERFLOW")
        return int(d) if integral else f
    except (InvalidOperation, ValueError, OverflowError):
        raise ContextError("INVALID_NUMBER") from None


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "RAW_SIZE")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError:
        raise ContextError("RAW_ENCODING") from None


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "DUPLICATE_JSON_KEY")
            result[k] = v
        return result
    def fail(_):
        raise ContextError("NONFINITE_JSON")
    try:
        out = json.loads(decode(raw), object_pairs_hook=pairs,
                         parse_float=number, parse_constant=fail)
    except (ValueError, RecursionError):
        raise ContextError("INVALID_JSON") from None
    stack = [(out, 0)]; count = 0
    while stack:
        value, depth = stack.pop(); count += 1
        require(depth <= 24 and count <= 300_000, "JSON_COMPLEXITY")
        if type(value) in (list, dict):
            stack.extend((v, depth + 1) for v in (value.values() if type(value) is dict else value))
    return out


def csv_records(raw):
    reader = csv.DictReader(io.StringIO(decode(raw)))
    fields = reader.fieldnames
    require(fields is not None and len(set(fields)) == len(fields), "CSV_HEADERS")
    rows = []
    for r in reader:
        require(None not in r and all(v is not None for v in r.values()), "CSV_TRUNCATED")
        rows.append(r)
        require(len(rows) <= MAX_ROWS, "ROW_LIMIT")
    return rows


def provenance(raw, *, provider, dataset, collected_at, cutoff):
    decode(raw)
    collected, decision = utc(collected_at), utc(cutoff)
    require(collected <= decision, "FUTURE_COLLECTION")
    return {"provider": provider, "dataset": dataset,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "collected_at": collected.isoformat(), "available_at": collected.isoformat(),
            "provider_published_at": None,
            "availability_basis": "COLLECTION_ONLY_NOT_ORIGINAL_PUBLICATION", **SAFETY}


def record(meta, entity, observed, metric, value, unit, **extra):
    require(type(entity) is str and 0 < len(entity) <= 128, "ENTITY_REQUIRED")
    require(iso_date(observed) <= utc(meta["collected_at"]).date(), "FUTURE_OBSERVATION")
    return {**meta, "entity_id": entity, "observation_date": observed,
            "metric": metric, "value": value, "unit": unit, **extra}


def pick(row, *names):
    values = [row[n] for n in names if n in row and row[n] not in (None, "")]
    require(len(set(map(str, values))) <= 1, "CONFLICTING_ALIASES")
    return values[0] if values else None


def cot_observations(raw, *, report_kind, collected_at, cutoff):
    """Socrata JSON/CSV (headered), futures-only. No assumed Friday timestamp.

    Report kind is part of identity. TFF leveraged funds are not all hedge funds;
    managed-money or dealer net positions are not one-way stock-market bets.
    """
    require(report_kind in {"TFF_FUTURES", "DISAGG_FUTURES"}, "COT_REPORT_KIND")
    decoded = decode(raw).lstrip()
    rows = strict_json(raw) if decoded.startswith("[") else csv_records(raw)
    require(type(rows) is list and len(rows) <= MAX_ROWS, "COT_ROWS")
    meta = provenance(raw, provider="CFTC", dataset=report_kind,
                      collected_at=collected_at, cutoff=cutoff)
    groups = ({"DEALER": "dealer", "ASSET_MANAGER": "asset_mgr",
               "LEVERAGED_MONEY": "lev_money", "OTHER_REPORTABLE": "other_rept",
               "NONREPORTABLE": "nonrept"} if report_kind == "TFF_FUTURES" else
              {"PRODUCER_MERCHANT": "prod_merc", "SWAP_DEALER": "swap",
               "MANAGED_MONEY": "m_money", "OTHER_REPORTABLE": "other_rept",
               "NONREPORTABLE": "nonrept"})
    result, seen = [], set()
    for original in rows:
        require(type(original) is dict, "COT_ROW_TYPE")
        r = {}
        for k, v in original.items():
            normalized = re.sub("_+", "_", k.strip().lower())
            require(normalized not in r, "COT_DUPLICATE_HEADER")
            r[normalized] = v
        code = r.get("cftc_contract_market_code")
        require(type(code) is str and re.fullmatch(r"[A-Za-z0-9]{6}", code), "COT_MARKET_ID")
        observed = pick(r, "report_date_as_yyyy_mm_dd", "as_of_date_form_yyyy_mm_dd")
        if observed is not None:
            require(type(observed) is str, "COT_DATE")
            if len(observed) > 10:
                require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00(?:\.000)?", observed), "COT_DATE")
                observed = observed[:10]  # Socrata floating date; NOT a publication timestamp.
        else:
            raw_date = r.get("report_date_as_mm_dd_yyyy")
            try:
                observed = datetime.strptime(raw_date, "%m/%d/%Y").date().isoformat()
            except (TypeError, ValueError):
                raise ContextError("COT_DATE") from None
        iso_date(observed)
        key = (code, observed)
        require(key not in seen, "COT_DUPLICATE_MARKET_DATE"); seen.add(key)
        classification = r.get("futonly_or_combined")
        require(classification in (None, "FutOnly", "Futures Only"), "COT_COMBINED_NOT_FUTURES")
        oi = number(r.get("open_interest_all"), integral=True, nonnegative=True)
        require(oi is not None, "COT_OI_MISSING")
        for group, prefix in groups.items():
            # Headered CFTC CSV uses *_all. Some PRE fields omit that suffix.
            # Conflicting aliases never silently select one representation.
            long = number(pick(r, prefix + "_positions_long_all", prefix + "_positions_long"),
                          integral=True, nonnegative=True)
            short = number(pick(r, prefix + "_positions_short_all", prefix + "_positions_short"),
                           integral=True, nonnegative=True)
            require((long is None or long <= oi) and (short is None or short <= oi), "COT_POSITION_GT_OI")
            net = None if long is None or short is None else long - short
            for metric, val, unit in (("net_contracts", net, "contracts"),
                ("net_fraction_oi", None if net is None or oi == 0 else net / oi, "fraction")):
                result.append(record(meta, code + ":" + group, observed, metric, val, unit,
                    group=group, open_interest=oi, long_contracts=long, short_contracts=short))
    return result


def finra_observations(raw, *, trade_date, collected_at, cutoff):
    """Consolidated CNMS only: ShortVolume already includes ShortExemptVolume.

    The denominator is the FINRA-reported facility volume, not consolidated U.S.
    exchange volume. Never mix the CNMS file with its component TRF files.
    """
    iso_date(trade_date)
    meta = provenance(raw, provider="FINRA", dataset="CNMS_SHORT_VOLUME",
                      collected_at=collected_at, cutoff=cutoff)
    lines = [x for x in decode(raw).splitlines() if x.strip()]
    require(len(lines) >= 2, "FINRA_TRUNCATED")
    header = [x.replace(" ", "") for x in lines[0].split("|")]
    require(header == ["Date", "Symbol", "ShortVolume", "ShortExemptVolume", "TotalVolume", "Market"],
            "FINRA_HEADER")
    require(re.fullmatch(r"[0-9]+", lines[-1]) is not None, "FINRA_TRAILER")
    require(int(lines[-1]) == len(lines) - 2 <= MAX_ROWS, "FINRA_TRAILER_COUNT")
    result, seen = [], set()
    for line in lines[1:-1]:
        parts = line.split("|"); require(len(parts) == 6, "FINRA_ROW")
        day, symbol, short, exempt, total, market = parts
        require(day == trade_date.replace("-", ""), "FINRA_WRONG_TRADE_DATE")
        require(re.fullmatch(r"[A-Za-z0-9.\-/]{1,14}", symbol) is not None, "FINRA_SYMBOL")
        require(symbol not in seen, "FINRA_DUPLICATE_SYMBOL"); seen.add(symbol)
        require(re.fullmatch(r"[NQBD,]+", market) is not None, "FINRA_WRONG_FACILITY")
        short, exempt, total = [number(x, integral=True, nonnegative=True) for x in (short, exempt, total)]
        require(None not in (short, exempt, total) and exempt <= short <= total, "FINRA_VOLUME_ORDER")
        result.append(record(meta, symbol, trade_date, "short_volume_fraction",
            None if total == 0 else short / total, "fraction", short_volume=short,
            short_exempt_volume=exempt, total_reported_volume=total, market=market,
            interpretation="REPORTED_TRADING_NOT_SHORT_INTEREST_NOT_INVESTOR_TYPE"))
    return result


def cboe_observations(raw, *, universe, collected_at, cutoff):
    """Official legacy CSV importer. Histories may stop in 2019: expose stale dates.

    No page scraping or claim of current endpoint entitlement is made here.
    """
    require(universe in {"EQUITY", "INDEX", "TOTAL"}, "CBOE_UNIVERSE")
    meta = provenance(raw, provider="CBOE", dataset="PUT_CALL_" + universe,
                      collected_at=collected_at, cutoff=cutoff)
    result, seen = [], set()
    for r in csv_records(raw):
        require({"DATE", "CALL", "PUT", "TOTAL", "P/C Ratio"} <= set(r), "CBOE_HEADER")
        try:
            day = datetime.strptime(r["DATE"], "%m/%d/%Y").date().isoformat()
        except ValueError:
            raise ContextError("CBOE_DATE") from None
        require(day not in seen, "CBOE_DUPLICATE_DATE"); seen.add(day)
        calls, puts, total = [number(r[k], integral=True, nonnegative=True) for k in ("CALL", "PUT", "TOTAL")]
        require(None not in (calls, puts, total) and calls + puts == total, "CBOE_TOTAL")
        ratio = None if calls == 0 else puts / calls
        reported = number(r["P/C Ratio"], nonnegative=True)
        require(ratio is None or reported is None or abs(ratio - reported) <= 0.015, "CBOE_RATIO_MISMATCH")
        result.append(record(meta, universe, day, "put_call_volume_ratio", ratio, "ratio"))
    return result


def aaii_observations(raw, *, collected_at, cutoff, unit):
    """User-authorized CSV export only. A web page being public is not API rights."""
    require(unit in {"percent", "fraction"}, "SURVEY_UNIT_REQUIRED")
    meta = provenance(raw, provider="AAII", dataset="AUTHORIZED_SURVEY_EXPORT",
                      collected_at=collected_at, cutoff=cutoff)
    result, seen = [], set()
    for r in csv_records(raw):
        require({"date", "bullish", "neutral", "bearish"} <= set(r), "AAII_HEADER")
        day = r["date"]; iso_date(day)
        require(day not in seen, "AAII_DUPLICATE_DATE"); seen.add(day)
        nums = [number(r[k], nonnegative=True) for k in ("bullish", "neutral", "bearish")]
        require(None not in nums, "AAII_MISSING")
        scale = 100 if unit == "percent" else 1
        require(all(n <= scale for n in nums) and abs(sum(nums) - scale) <= scale * .001,
                "AAII_UNIT_OR_SUM")
        result.append(record(meta, "RESPONDENTS", day, "bull_minus_bear", (nums[0] - nums[2])/scale,
                             "fraction", interpretation="SURVEY_NOT_ACTUAL_POSITIONS"))
    return result


def trailing_context(rows, *, cutoff, max_age_days, lookback=52, minimum=20):
    """Latest visible observation; null latest never falls back to a favorable past."""
    require(type(max_age_days) is int and max_age_days >= 0, "AGE_POLICY")
    require(type(lookback) is int and type(minimum) is int and 1 <= minimum <= lookback <= 1000,
            "HISTORY_POLICY")
    decision = utc(cutoff); groups = defaultdict(dict)
    for r in rows:
        observed = iso_date(r["observation_date"])
        available = utc(r["available_at"]); collected = utc(r["collected_at"])
        require(available >= collected and observed <= collected.date(), "ROW_CLOCK_ORDER")
        require(re.fullmatch(r"[0-9a-f]{64}", r.get("source_sha256", "")) is not None, "ROW_SOURCE_HASH")
        if available > decision:
            continue
        key = (r["provider"], r["dataset"], r["entity_id"], r["metric"], r["unit"])
        old = groups[key].get(observed)
        if old is not None and utc(old["available_at"]) == available:
            require(old == r, "AMBIGUOUS_SAME_TIME_OBSERVATION")
        if old is None or utc(old["available_at"]) < available:
            groups[key][observed] = r
    out = []
    for key in sorted(groups):
        vals = sorted(groups[key].items()); day, current = vals[-1]
        stale = (decision.date() - day).days > max_age_days
        value = number(current["value"])
        history = [number(r["value"]) for _, r in vals[-lookback:]]
        finite = [x for x in history if x is not None]
        pct = None if stale or value is None or len(finite) < minimum else (
            sum(v < value for v in finite) + .5 * sum(v == value for v in finite)) / len(finite)
        out.append({**current, "status": "STALE" if stale else ("MISSING" if value is None else "OBSERVED"),
                    "current_value": None if stale else value, "trailing_midrank": pct,
                    "history_count": len(finite), "max_age_days": max_age_days, **SAFETY})
    return out


def calendar_theme_context(raw, requested_symbols, theme_map, *, observed_at, collected_at,
                           cutoff, mapping_available_at):
    """Read #450 C1 in memory; vendor lookbacks never become own PIT vintages.

    A count of symbols with a positive vendor-reported change is NOT a count
    of independent analysts. Do not sum earnings-linked reactions as alpha votes.
    """
    require(utc(mapping_available_at) <= utc(cutoff), "FUTURE_THEME_MAPPING")
    require(type(theme_map) is dict and set(theme_map) == set(requested_symbols), "THEME_MAPPING_COVERAGE")
    for themes in theme_map.values():
        require(type(themes) is list and len(themes) <= 20 and len(set(themes)) == len(themes)
                and all(type(t) is str and 0 < len(t) <= 128 for t in themes), "THEME_MAPPING_INVALID")
    meta = provenance(raw, provider="EODHD_CALENDAR", dataset="PROVIDER_LOOKBACK_CONTEXT",
                      collected_at=collected_at, cutoff=cutoff)
    try:
        from tools import eodhd_calendar_trends as cal
    except ImportError:
        raise ContextError("WAIT_DEPENDENCY_CALENDAR_C1") from None
    snapshots, batch = cal.build_h1_batch(cal.strict_json_loads(raw), requested_symbols,
                                         observed_at=observed_at, collected_at=collected_at)
    groups = defaultdict(list)
    for symbol, entry in batch["by_symbol"].items():
        for r in entry["vendor_observations"]:
            # Old fiscal windows never become current expectation evidence.
            if iso_date(r["fiscal_period_end"]) < utc(collected_at).date():
                continue
            current = r["fields"]["epsTrendCurrent"]["value"]
            old = r["fields"]["epsTrend30daysAgo"]["value"]
            # Negative/zero denominators are not meaningful percentage growth.
            change = None if current is None or old is None or old <= 0 else current / old - 1
            if change is not None and not math.isfinite(change):
                change = None
            for theme in theme_map[symbol]:
                groups[(theme, r["relative_horizon"])].append((symbol, change))
    details = []
    for (theme, horizon), values in sorted(groups.items()):
        require(len({s for s, _ in values}) == len(values), "MULTIPLE_PERIODS_PER_HORIZON")
        eligible = [v for _, v in values if v is not None]
        expected = sum(theme in ts for ts in theme_map.values())
        details.append({"theme": theme, "relative_horizon": horizon,
            "requested_symbols": sorted(s for s, ts in theme_map.items() if theme in ts),
            "expected_symbol_count": expected, "observed_symbol_count": len(values),
            "computable_symbol_count": len(eligible), "missing_symbol_count": expected - len(eligible),
            "vendor_positive_change_fraction": None if not eligible else sum(v > 0 for v in eligible)/len(eligible),
            "coverage_fraction": len(eligible)/expected,
            "basis": "PROVIDER_REPORTED_SYMBOL_LOOKBACK_NOT_ANALYST_BREADTH",
            "strict_h1_revision": None, **SAFETY})
    return {"schema": SCHEMA, "source": meta, "snapshot_count": len(snapshots),
            "themes": details, "requested_symbols": sorted(requested_symbols),
            "mapping_available_at": mapping_available_at, "cutoff": cutoff,
            "mapping_sha256": hashlib.sha256(json.dumps(theme_map, sort_keys=True).encode()).hexdigest(),
            "status": "UNVERIFIED_PROVIDER_LOOKBACK_DIAGNOSTIC", **SAFETY}


def price_theme_context(close, volume, sessions, universe, themes, *, cutoff, collected_at,
                        membership_available_at, source_sha256, turnover_close=None):
    """Reuse #388's actual helper; no new market-regime or RS weighting model.

    Explicit complete session grid and security universe prevent silent missing
    session compression. This diagnostic is current-cohort only, never PIT members.
    """
    import numpy as np
    import pandas as pd
    from tools.build_run287_chameleon_macro_inputs import compute_universe_components
    require(utc(collected_at) <= utc(cutoff) and utc(membership_available_at) <= utc(cutoff), "FUTURE_PRICE_INPUT")
    require(re.fullmatch(r"[0-9a-f]{64}", source_sha256) is not None, "PRICE_HASH_REQUIRED")
    require(type(universe) is list and 1 <= len(universe) <= 10_000 and len(set(universe)) == len(universe)
            and all(type(s) is str and s for s in universe), "UNIVERSE_INVALID")
    require(type(themes) is dict and set(themes) <= set(universe), "THEME_UNIVERSE_MISMATCH")
    for members in themes.values():
        require(type(members) is list and len(set(members)) == len(members)
                and all(type(t) is str and t and t != "__MARKET__" for t in members), "THEME_MAPPING_INVALID")
    idx = pd.DatetimeIndex(sessions)
    require(0 < len(idx) <= 3000 and not idx.has_duplicates and idx.is_monotonic_increasing
            and idx.tz is None and (idx == idx.normalize()).all(), "SESSION_GRID")
    require(idx[-1].date() <= utc(collected_at).date(), "FUTURE_SESSION")
    require(close.index.equals(idx) and volume.index.equals(idx), "PRICE_GRID_MISMATCH")
    require(not close.columns.has_duplicates and not volume.columns.has_duplicates
            and set(close.columns) <= set(universe) and set(volume.columns) <= set(universe), "PRICE_SECURITY_MISMATCH")
    require(all(pd.api.types.is_numeric_dtype(t) and not pd.api.types.is_bool_dtype(t) for t in close.dtypes)
            and all(pd.api.types.is_numeric_dtype(t) and not pd.api.types.is_bool_dtype(t) for t in volume.dtypes), "PRICE_NUMERIC_TYPE")
    close, volume = close.reindex(columns=universe), volume.reindex(columns=universe)
    require(((np.isfinite(close) & (close > 0)) | close.isna()).all().all(), "PRICE_NONPOSITIVE_OR_NONFINITE")
    require(((np.isfinite(volume) & (volume >= 0)) | volume.isna()).all().all(), "VOLUME_INVALID")
    # Missing unadjusted turnover price means dollar-turnover measures unavailable.
    if turnover_close is None:
        turnover_close = close * np.nan
    else:
        require(turnover_close.index.equals(idx) and not turnover_close.columns.has_duplicates
                and set(turnover_close.columns) <= set(universe), "TURNOVER_GRID")
        turnover_close = turnover_close.reindex(columns=universe)
        require(all(pd.api.types.is_numeric_dtype(t) and not pd.api.types.is_bool_dtype(t) for t in turnover_close.dtypes)
                and ((np.isfinite(turnover_close) & (turnover_close > 0)) | turnover_close.isna()).all().all(), "TURNOVER_INVALID")
    cohorts = {"__MARKET__": universe}
    for s, names in themes.items():
        for name in names:
            cohorts.setdefault(name, []).append(s)
    output = []
    for name, members in sorted(cohorts.items()):
        px, vol, dollar = close[members], volume[members], turnover_close[members]
        metrics, counts = compute_universe_components(px, vol, 1, dollar)
        values = {}
        for k, series in metrics.items():
            val = series.iloc[-1]
            values[k] = {"value": float(val) if pd.notna(val) and math.isfinite(val) else None,
                         "eligible_count": int(counts[k].iloc[-1]), "expected_count": len(members)}
        ma20 = px.rolling(20, min_periods=20).mean().iloc[-1]
        valid = px.iloc[-1].notna() & ma20.notna()
        values["pct_above_ma20"] = {"value": None if not valid.any() else float((px.iloc[-1][valid] > ma20[valid]).mean()),
            "eligible_count": int(valid.sum()), "expected_count": len(members)}
        changes = px.pct_change(fill_method=None).iloc[-1]
        require(not np.isinf(changes.to_numpy(dtype=float)).any(), "PRICE_RETURN_OVERFLOW")
        changes = changes.dropna()
        output.append({"cohort": name, "members": sorted(members), "metrics": values,
            "available_at": max(utc(collected_at), utc(membership_available_at)).isoformat(),
            "collected_at": collected_at, "mapping_available_at": membership_available_at, "cutoff": cutoff,
            "advancers": int((changes > 0).sum()), "decliners": int((changes < 0).sum()),
            "unchanged": int((changes == 0).sum()), "missing_return_count": len(members)-len(changes),
            "median_return_1d": None if changes.empty else float(changes.median()),
            "session": idx[-1].date().isoformat(), "source_sha256": source_sha256,
            "truth_class": "CURRENT_COHORT_RESEARCH_NOT_HISTORICAL_PIT", **SAFETY})
    return output


def compose_research_context(price_rows, calendar_result, public_rows, *, security_map,
                             security_map_available_at, cutoff, expected_session):
    """Join diagnostics, not signals: explicit symbol mapping and matching cohorts.

    Produces no regime verdict, independent-vote count, rank, ER or trade intent.
    Hashes bind local section content only; they are not producer attestation.
    """
    decision = utc(cutoff)
    require(utc(security_map_available_at) <= decision, "FUTURE_SECURITY_MAPPING")
    iso_date(expected_session)
    require(type(price_rows) is list and type(public_rows) is list
            and len(price_rows) <= 10001 and len(public_rows) <= MAX_ROWS, "CONTEXT_ROWS")
    require(type(calendar_result) is dict and calendar_result.get("schema") == SCHEMA,
            "CALENDAR_CONTEXT_SCHEMA")
    require(type(security_map) is dict and set(security_map) == set(calendar_result["requested_symbols"])
            and all(type(v) is str and v for v in security_map.values())
            and len(set(security_map.values())) == len(security_map), "EXPLICIT_SECURITY_MAPPING")
    require(utc(calendar_result["source"]["available_at"]) <= decision
            and utc(calendar_result["mapping_available_at"]) <= decision, "FUTURE_CALENDAR_CONTEXT")
    # Consumers do not widen an input's authority, even when a forged flag is supplied.
    def no_authority(obj):
        require(type(obj) is dict and all(obj.get(k) is False for k in SAFETY), "INPUT_AUTHORITY_CONFLICT")
    no_authority(calendar_result)
    prices = {}
    for row in price_rows:
        no_authority(row)
        require(utc(row["available_at"]) <= decision and utc(row["collected_at"]) <= decision,
                "FUTURE_PRICE_CONTEXT")
        require(row["cohort"] not in prices, "DUPLICATE_PRICE_COHORT")
        require(type(row["members"]) is list and len(set(row["members"])) == len(row["members"]),
                "DUPLICATE_COHORT_MEMBER")
        prices[row["cohort"]] = row
    for row in public_rows:
        no_authority(row)
        require(utc(row["available_at"]) <= decision and utc(row["collected_at"]) <= decision,
                "FUTURE_PUBLIC_CONTEXT")
    paired, seen = [], set()
    for row in calendar_result["themes"]:
        no_authority(row)
        key = (row["theme"], row["relative_horizon"])
        require(key not in seen, "DUPLICATE_CALENDAR_COHORT"); seen.add(key)
        px = prices.get(row["theme"])
        expected = {security_map[s] for s in row["requested_symbols"]}
        status = ("NO_PRICE_COHORT" if px is None else
                  "WAIT_EXPECTED_PRICE_SESSION" if px["session"] != expected_session else
                  "COHORT_MISMATCH_SEPARATE_CONTEXTS" if set(px["members"]) != expected else
                  "PAIRED_DIAGNOSTICS_NOT_ALPHA")
        paired.append({"theme": row["theme"], "relative_horizon": row["relative_horizon"],
            "status": status, "calendar_context": row,
            "price_context": px if status == "PAIRED_DIAGNOSTICS_NOT_ALPHA" else None, **SAFETY})
    sections = {"price": price_rows, "calendar": calendar_result, "public": public_rows,
                "explicit_security_map": security_map}
    # Round trip seals caller-owned dictionaries, rejects NaN and bounds tree/bytes.
    sealed = strict_json(json.dumps(sections, sort_keys=True, allow_nan=False).encode())
    hashes = {k: hashlib.sha256(json.dumps(v, sort_keys=True, allow_nan=False).encode()).hexdigest()
              for k, v in sealed.items()}
    paired = strict_json(json.dumps(paired, sort_keys=True, allow_nan=False).encode())
    return {"schema": SCHEMA, "status": "LOCAL_CONTEXT_BUNDLE_NOT_ADMITTED",
            "cutoff": cutoff, "expected_price_session": expected_session,
            "paired_themes": paired, "sections": sealed, "section_sha256": hashes,
            "identity_binding": "CALLER_SUPPLIED_MAP_NOT_INDEPENDENT_IDENTITY_VERIFICATION", **SAFETY}
