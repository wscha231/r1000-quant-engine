"""Original-bound funding, bank balance and macro context; no risk policy.

Amounts are balance changes, not identified transfers between asset markets.
All observations retain their actual collection/availability and null values.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math

from tools import free_market_context as f
from tools import a4_macro_bridge as bridge
from tools.macro_history_sources import digest, encoded

HORIZONS = (1, 5, 10, 21, 63, 126, 252)
TARGETS = ("SPY", "QQQ", "IWM", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
# logical ID, unit, frequency, measurement basis, seasonal basis, family, max age
SERIES = {
    "SOFR": ("sofr", "percent", "daily", "TRANSACTION_WEIGHTED_MEDIAN", "NSA", "FUNDING", 5),
    "TGCR": ("tgcr", "percent", "daily", "TRANSACTION_WEIGHTED_MEDIAN", "NSA", "FUNDING", 5),
    "IORB": ("iorb", "percent", "daily", "ADMINISTERED_RATE", "NSA", "FUNDING", 5),
    "DFF": ("effr", "percent", "daily", "EFFECTIVE_RATE", "NSA", "FUNDING", 5),
    "EFFR": ("effr", "percent", "daily", "EFFECTIVE_RATE", "NSA", "FUNDING", 5),
    "WALCL": ("fed_assets", "millions_usd", "weekly", "WEDNESDAY_LEVEL", "NSA", "LIQUIDITY", 14),
    "WRESBAL": ("reserves_week_average", "millions_usd", "weekly", "WEEK_AVERAGE", "NSA", "LIQUIDITY", 14),
    "WTREGEN": ("tga_week_average", "millions_usd", "weekly", "WEEK_AVERAGE", "NSA", "LIQUIDITY", 14),
    "WDTGAL": ("tga_wednesday", "millions_usd", "weekly", "WEDNESDAY_LEVEL", "NSA", "LIQUIDITY", 14),
    "RRPONTSYD": ("overnight_rrp", "billions_usd", "daily", "OVERNIGHT_OPERATION_AMOUNT", "NSA", "LIQUIDITY", 5),
    "RRPTSYD": ("total_rrp", "billions_usd", "daily", "OPERATION_AMOUNT", "NSA", "LIQUIDITY", 5),
    "DPSACBW027SBOG": ("deposits_all", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "DPSDCBW027SBOG": ("deposits_domestic", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "DPSLCBW027SBOG": ("deposits_large", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "DPSSCBW027SBOG": ("deposits_small", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "TOTLL": ("loans_all", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "TOTCI": ("commercial_industrial_loans", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "CASACBW027SBOG": ("cash_assets_all", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
    "TLAACBW027SBOG": ("bank_assets_all", "billions_usd", "weekly", "WEDNESDAY_LEVEL", "SA", "BANK_CREDIT", 16),
}
for _sid, _logical, _unit, _freq, _family in (
    ("UNRATE", "unemployment", "percent", "monthly", "GROWTH"),
    ("PAYEMS", "payrolls", "thousands_persons", "monthly", "GROWTH"),
    ("ICSA", "initial_claims", "persons", "weekly", "GROWTH"),
    ("RSAFS", "retail_sales_nominal", "millions_usd", "monthly", "GROWTH"),
    ("DSPIC96", "real_disposable_income", "billions_chained_usd", "monthly", "GROWTH"),
    ("CPIAUCSL", "cpi", "index", "monthly", "INFLATION"),
    ("CPILFESL", "core_cpi", "index", "monthly", "INFLATION"),
    ("PCEPILFE", "core_pce", "index", "monthly", "INFLATION"),
    ("DGS2", "yield_2y", "percent", "daily", "RATES"),
    ("DGS10", "yield_10y", "percent", "daily", "RATES"),
    ("DFII10", "real_yield_10y", "percent", "daily", "RATES"),
    ("BAMLH0A0HYM2", "hy_oas", "percent", "daily", "CREDIT"),
    ("BAMLC0A0CM", "ig_oas", "percent", "daily", "CREDIT"),
    ("DTWEXBGS", "broad_usd", "index", "daily", "FX"),
):
    SERIES[_sid] = (_logical, _unit, _freq, "PERIOD_OBSERVATION", "SOURCE_DEFINED", _family, 90 if _freq == "monthly" else 14 if _freq == "weekly" else 7)

SPREADS = {"sofr_minus_iorb": ("sofr", "iorb"), "tgcr_minus_iorb": ("tgcr", "iorb"),
           "sofr_minus_tgcr": ("sofr", "tgcr"), "effr_minus_iorb": ("effr", "iorb")}


def parse_original(raw, spec):
    source_id = spec.get("source_id", "")
    provider, _, sid = source_id.partition(":")
    f.require(sid in SERIES and provider in {"fred", "nyfed"}, "A4_UNREGISTERED_SOURCE")
    f.require(provider != "nyfed" or sid in {"SOFR", "TGCR", "EFFR"}, "A4_NYFED_RATE_TYPE")
    collected = f.utc(spec["collected_at"])
    logical, unit, frequency, basis, seasonal, family, age = SERIES[sid]
    data = []
    if provider == "nyfed":
        document = f.strict_json(raw)
        f.require(type(document) is dict, "A4_NYFED_DOCUMENT")
        values = document.get("refRates")
        f.require(type(values) is list and 0 < len(values) <= 10000, "A4_NYFED_ROWS")
        for item in values:
            f.require(type(item) is dict and item.get("type") == sid, "A4_NYFED_IDENTITY")
            extras = {"transaction_volume_billions_usd": f.number(item.get("volumeInBillions"))}
            for percentile in (1, 25, 75, 99):
                extras["rate_percentile_"+str(percentile)] = f.number(item.get("percentPercentile"+str(percentile)))
            points = [extras["rate_percentile_"+str(p)] for p in (1, 25, 75, 99)]
            observed = [v for v in points if v is not None]
            f.require(observed == sorted(observed) and (extras["transaction_volume_billions_usd"] is None
                      or extras["transaction_volume_billions_usd"] >= 0), "A4_NYFED_DISTRIBUTION")
            data.append(dict(observation_date=item.get("effectiveDate"), value=f.number(item.get("percentRate")), **extras))
    else:
        csv_raw = raw
        if raw.lstrip().startswith(b"{"):
            normalization = spec.get("normalization")
            f.require(type(normalization) is dict and normalization.get("series_id") == sid
                      and f.utc(normalization["collected_at"]) == collected, "A4_JSON_BINDING_REQUIRED")
            csv_raw, manifest = bridge.normalize_current(raw, series_id=sid,
                start=normalization["requested_start"], through=normalization["requested_through"],
                collected_at=spec["collected_at"])
            f.require(manifest == normalization, "A4_JSON_NORMALIZATION_MISMATCH")
        records = f.csv_records(csv_raw)
        f.require(bool(records), "A4_EMPTY_SOURCE")
        for item in records:
            f.require(set(item) in ({"observation_date", sid}, {"DATE", sid}), "A4_CSV_IDENTITY")
            text = item[sid]
            data.append(dict(observation_date=item.get("observation_date", item.get("DATE")),
                             value=None if text in {".", "", "NA", "N/A"} else f.number(text)))
    seen = set()
    for item in data:
        day = f.iso_date(item["observation_date"])
        f.require(day <= collected.date() and day not in seen, "A4_DUPLICATE_OR_FUTURE_OBSERVATION")
        seen.add(day)
        if family in {"BANK_CREDIT", "LIQUIDITY"}:
            f.require(item["value"] is None or item["value"] >= 0, "A4_NEGATIVE_BALANCE")
    normalized_hash = digest(encoded(sorted(data, key=lambda r: r["observation_date"])))
    return [dict(item, source_id=source_id, logical_id=logical, unit=unit, frequency=frequency,
        measurement_basis=basis, seasonal_basis=seasonal, family=family, max_age_days=age,
        collected_at=spec["collected_at"], available_at=spec["collected_at"], published_at=None,
        original_sha256=digest(raw), normalized_sha256=normalized_hash,
        truth_class="FREE_PROXY_CURRENT_VINTAGE", historical_pit_certified=False)
        for item in sorted(data, key=lambda r: r["observation_date"])]


def visible_histories(rows, cutoff):
    decision, grouped, providers = f.utc(cutoff), defaultdict(dict), {}
    f.require(type(rows) is list and len(rows) <= 150000, "A4_OBSERVATION_BUDGET")
    for r in rows:
        if f.utc(r["available_at"]) > decision:
            continue
        logical = r["logical_id"]
        f.require(providers.setdefault(logical, r["source_id"]) == r["source_id"], "A4_CHOOSE_ONE_PROVIDER")
        key, old = r["observation_date"], grouped[logical].get(r["observation_date"])
        if old and old["available_at"] == r["available_at"]:
            f.require(old == r, "A4_CONFLICTING_VERSION")
        if old is None or f.utc(old["available_at"]) < f.utc(r["available_at"]):
            grouped[logical][key] = r
    return {key: [dated[d] for d in sorted(dated)] for key, dated in grouped.items()}


def summarize(history, cutoff):
    last = history[-1]
    status = "MISSING" if last["value"] is None else "STALE" if (
        f.utc(cutoff).date()-f.iso_date(last["observation_date"])).days > last["max_age_days"] else "OBSERVED"
    result = {**last, "status": status, "value": last["value"] if status == "OBSERVED" else None,
              "changes": {}, "interpretation": "BALANCE_CHANGE_NOT_IDENTIFIED_FLOW" if last["family"] == "BANK_CREDIT" else "OBSERVATION_CHANGE"}
    periods = (1, 4, 13) if last["frequency"] == "weekly" else (1, 5, 21) if last["frequency"] == "daily" else (1, 3, 12)
    dated = {r["observation_date"]: r for r in history}
    for n in periods:
        previous = None
        if last["frequency"] == "weekly":
            wanted = (f.iso_date(last["observation_date"])-timedelta(weeks=n)).isoformat()
            needed = [(f.iso_date(last["observation_date"])-timedelta(weeks=k)).isoformat() for k in range(n+1)]
            if all(d in dated and dated[d]["value"] is not None for d in needed): previous = dated[wanted]
        elif last["frequency"] == "monthly":
            day = f.iso_date(last["observation_date"])
            month = day.year*12+day.month-1
            indexed = {f.iso_date(r["observation_date"]).year*12+f.iso_date(r["observation_date"]).month-1: r for r in history}
            if all(month-k in indexed and indexed[month-k]["value"] is not None for k in range(n+1)):
                previous = indexed[month-n]
        elif len(history) > n:
            previous = history[-1-n]
        delta = None if result["value"] is None or previous is None or previous["value"] is None else result["value"]-previous["value"]
        percentage = None if delta is None or previous["value"] == 0 else delta/abs(previous["value"])
        f.require(all(v is None or math.isfinite(v) for v in (delta, percentage)), "A4_NONFINITE_CHANGE")
        result["changes"][str(n)] = dict(value=delta, fraction=percentage, unit=last["unit"],
            period="weeks" if last["frequency"] == "weekly" else "observations",
            previous_observation_date=None if previous is None else previous["observation_date"])
    return result


def funding_spreads(histories, panel):
    result = {}
    for name, (left, right) in SPREADS.items():
        a, b = panel.get(left), panel.get(right)
        reason = "MISSING_INPUT" if a is None or b is None else "INPUT_NOT_OBSERVED" if (
            a["status"] != "OBSERVED" or b["status"] != "OBSERVED") else "OBSERVATION_DATE_MISMATCH" if (
            a["observation_date"] != b["observation_date"]) else None
        history = []
        if reason is None:
            other = {r["observation_date"]: r for r in histories[right]}
            for row in histories[left]:
                peer = other.get(row["observation_date"])
                value = None if peer is None or row["value"] is None or peer["value"] is None else (row["value"]-peer["value"])*100
                history.append(dict(observation_date=row["observation_date"], value=value))
        latest = history[-1]["value"] if history else None
        persistence = 0
        for row in reversed(history):
            if row["value"] is None or row["value"] <= 0: break
            persistence += 1
        changes = {str(n): None if latest is None or len(history) <= n or history[-1-n]["value"] is None else
                   latest-history[-1-n]["value"] for n in (1, 5, 21)}
        f.require(all(v is None or math.isfinite(v) for v in [latest, *changes.values()]), "A4_SPREAD_OVERFLOW")
        result[name] = dict(value=latest, unit="basis_points", status=reason or "OBSERVED",
            observation_date=None if reason else a["observation_date"], changes_bp=changes,
            positive_observation_streak=persistence, input_keys=[left, right],
            original_sha256=[] if reason else [a["original_sha256"], b["original_sha256"]],
            evidence_family="FUNDING_SHARED_INPUTS", independent_vote=False)
    return result


def bank_comparison(panel):
    required = ("deposits_all", "deposits_domestic", "deposits_large", "deposits_small", "loans_all",
                "commercial_industrial_loans", "cash_assets_all", "bank_assets_all")
    absent = [key for key in required if panel.get(key, {}).get("status") != "OBSERVED"]
    ratio, reconciliation = None, "MISSING_INPUT"
    if not absent:
        same = len({panel[k]["observation_date"] for k in required}) == 1
        if same:
            deposit = panel["deposits_all"]["value"]
            ratio = panel["loans_all"]["value"]/deposit if deposit else None
            error = panel["deposits_large"]["value"]+panel["deposits_small"]["value"]-panel["deposits_domestic"]["value"]
            reconciliation = "MATCH_WITHIN_ROUNDING" if abs(error) <= .2 else "DOMESTIC_RECONCILIATION_MISMATCH"
        else:
            absent.append("OBSERVATION_DATE_MISMATCH")
    ready = not absent and ratio is not None and reconciliation == "MATCH_WITHIN_ROUNDING"
    return dict(status="OBSERVED" if ready else "PARTIAL", blockers=absent + ([] if ready or absent else [reconciliation]),
        series={k: panel.get(k) for k in required}, loans_to_deposits=ratio,
        domestic_reconciliation=reconciliation, deposit_change_is_identified_transfer=False,
        large_bank_definition="TOP_25_DOMESTIC_BANKS_AT_H8_BENCHMARK", small_bank_definition="OTHER_DOMESTIC_BANKS",
        foreign_related_institutions_in_all_banks=True,
        structural_adjustments="SOURCE_H8_ADJUSTMENTS_RETAINED_NOT_RECONSTRUCTED")


def enrich(report, originals):
    rows = []
    for raw, spec in originals: rows.extend(parse_original(raw, spec))
    histories = visible_histories(rows, report["cutoff"])
    panel = {k: summarize(v, report["cutoff"]) for k, v in histories.items()}
    spreads = funding_spreads(histories, panel)
    funding_ready = all(r["status"] == "OBSERVED" for r in spreads.values())
    liquid = {k: v for k, v in panel.items() if v["family"] == "LIQUIDITY"}
    liquidity_ready = all(panel.get(k, {}).get("status") == "OBSERVED" for k in ("fed_assets", "reserves_week_average")) and any(
        panel.get(k, {}).get("status") == "OBSERVED" for k in ("tga_week_average", "tga_wednesday")) and any(
        panel.get(k, {}).get("status") == "OBSERVED" for k in ("overnight_rrp", "total_rrp"))
    bank = bank_comparison(panel)
    macro = {k: v for k, v in panel.items() if v["family"] in {"GROWTH", "INFLATION", "RATES", "CREDIT", "FX"}}
    macro_ready = all(any(r["family"] == family and r["status"] == "OBSERVED" for r in macro.values())
                      for family in ("GROWTH", "INFLATION", "RATES", "CREDIT", "FX"))
    report.update(schema="market-analysis-report-v2",
        funding=dict(status="OBSERVED" if funding_ready else "PARTIAL", spreads=spreads,
                     series={k: v for k, v in panel.items() if v["family"] == "FUNDING"}),
        liquidity=dict(status="OBSERVED" if liquidity_ready else "PARTIAL", series=liquid,
                       fixed_reserve_threshold_used=False, net_liquidity_shortcut_used=False),
        bank_credit=bank, macro_direction_inputs=macro,
        enhanced_readiness=dict(funding=funding_ready, liquidity=liquidity_ready,
                               bank_credit=bank["status"] == "OBSERVED", macro=macro_ready),
        horizon_outlook=[dict(horizon_sessions=h, direction="INSUFFICIENT_EVIDENCE",
            blockers=["REVIEWED_HISTORICAL_RELATIONSHIP_RELEASE_REQUIRED"], evidence=[], contrary_evidence=[]) for h in HORIZONS],
        historical_evidence=dict(status="NOT_CONNECTED", causal_effect_identified=False),
        learning_provenance=dict(status="NOT_CONNECTED", automatic_model_promotion_allowed=False),
        a4_observation_provenance=[dict({k: history[-1][k] for k in ("source_id", "observation_date", "available_at", "collected_at",
            "published_at", "original_sha256", "normalized_sha256", "measurement_basis", "seasonal_basis")},
            observation_count=len(history), first_observation_date=history[0]["observation_date"])
            for history in histories.values()])
    report["known_overlap"].append("Funding spreads share rate inputs; their differences are not independent risk votes")
    return report
