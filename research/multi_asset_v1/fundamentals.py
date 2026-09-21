"""Current commodity/network observations, never price-derived fundamentals.

Provider histories are revised snapshots. Availability is actual retrieval;
neither period labels nor a release date certify a historical PIT vintage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from tools.macro_history_sources import exclusive, request_bytes
from .contracts import ContractError, day, load_json, number, require, stamp

EIA_URL = "https://ir.eia.gov/ngs/wngsr.json"
NETWORK = {
    "BTC": {"HashRate": ("hashrate", "HASH_PER_SECOND", 1e12),
            "CapMVRVCur": ("mvrv", "RATIO", 1),
            "FeeTotNtv": ("fees", "TOKEN", 1)},
    "ETH": {"FeeTotNtv": ("fees", "TOKEN", 1),
            "AdrActCnt": ("active_addresses", "COUNT", 1),
            "TxCnt": ("transactions", "COUNT", 1),
            "SplyCur": ("circulating_supply", "TOKEN", 1)},
}


def receipt_blockers(metrics, receipts):
    """A claimed capture must contain the entire fixed request/observation set.

    Generic reviewed metric inputs predate this producer and remain supported;
    once either its rows or receipts appear, partial producer evidence cannot
    authorize an evaluator even if a caller separately reviewed sparse inputs.
    """
    sources = {"EIA_STORAGE", "COINMETRICS_COMMUNITY"}
    observations = [r for r in metrics if r.get("source") in sources]
    collected = [r for r in receipts if r.get("source") in sources]
    if not observations and not collected:
        return []
    expected = {("EIA_STORAGE", "NATURAL_GAS", "WNGSR"):
                {"inventory": "BCF", "inventory_5y_average": "BCF",
                 "inventory_weekly_change": "BCF", "inventory_vs_5y_average": "FRACTION"}}
    for subject, specs in NETWORK.items():
        for series, (metric, unit, _) in specs.items():
            expected[("COINMETRICS_COMMUNITY", subject, series)] = {metric: unit}
    try:
        keys = [(r.get("source"), r.get("subject_id"), r.get("series")) for r in collected]
        require(len(keys) == len(set(keys)), "fundamental_receipt_duplicate")
        require(set(keys) == set(expected), "fundamental_receipt_set")
        used = set()
        for receipt, key in zip(collected, keys):
            require(receipt.get("status") == "CAPTURED_CURRENT_ONLY", "fundamental_receipt_status")
            spec = expected[key]
            matching = [(i, r) for i, r in enumerate(observations)
                        if r.get("source") == key[0] and r.get("subject_id") == key[1]
                        and (key[0] == "EIA_STORAGE" or r.get("source_metric") == key[2])]
            require(type(receipt.get("rows")) is int
                    and receipt["rows"] == len(matching) == len(spec), "fundamental_receipt_count")
            require({r.get("metric") for _, r in matching} == set(spec), "fundamental_receipt_metrics")
            for i, row in matching:
                require(row.get("admission") == "OBSERVED"
                        and row.get("unit") == spec[row["metric"]]
                        and row.get("raw_sha256") == receipt.get("raw_sha256"),
                        "fundamental_receipt_evidence")
                used.add(i)
        require(len(used) == len(observations), "fundamental_unclaimed_metric")
    except (ContractError, TypeError, KeyError) as exc:
        return [str(exc) if isinstance(exc, ContractError) else "fundamental_receipt_schema"]
    return []


def eia_url(url):
    part = urlsplit(url)
    require(part.scheme == "https" and part.netloc == "ir.eia.gov"
            and part.path in {"/ngs/wngsr.json", "/secure/ngs/wngsr.json"}
            and not part.fragment, "eia_redirect_target")
    return url


class EiaRedirect(HTTPRedirectHandler):
    """EIA publicly redirects this one document to its signed same-host URL."""
    def __init__(self):
        super().__init__()
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        require(self.count <= 2, "eia_redirect_limit")
        eia_url(req.full_url)
        eia_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_eia(url):
    # Never accept a caller-selected endpoint or persist signed redirect URLs.
    require(url == EIA_URL, "eia_endpoint")
    with build_opener(EiaRedirect()).open(Request(url, headers={
            "User-Agent": "macro-evidence-research/1.0",
            "Accept": "application/json"}), timeout=20) as response:
        eia_url(response.geturl())
        require(response.status == 200, "eia_status")
        raw = response.read(1_048_577)
    require(0 < len(raw) <= 1_048_576, "eia_response_size")
    return raw


def observation(raw, subject, metric, value, unit, observed, collected, source, **extra):
    return dict(subject_id=subject, metric=metric, value=value, unit=unit,
                observed_at=observed, available_at=collected, collected_at=collected,
                source=source, data_quality="OBSERVED" if value is not None else "MISSING",
                evidence_kind="FORWARD_CAPTURE", raw_sha256=hashlib.sha256(raw).hexdigest(),
                **extra)


def gas_storage(raw, collected):
    data = load_json(raw)
    require(data["release_name"] == "Weekly Natural Gas Storage Report"
            and data["fuel_type"] == "natural gas" and data["process"] == "storage"
            and data["periodicity"] == "weekly", "eia_identity")
    current, previous = day(data["current_week"]), day(data["week_ago"])
    release = datetime.strptime(data["release_date"], "%Y-%b-%d %H:%M:%S").date()
    require((current-previous).days == 7 and current.weekday() == 4
            and current <= release <= stamp(collected).date(), "eia_periods")
    # Do not infer 10:30 ET from this source's midnight date label.
    require((stamp(collected).date()-release).days <= 8, "eia_stale_release")
    candidates = [s for s in data["series"] if s["series_id"] == "png.nw2_epg0_swo_r48_bcf.w"]
    require(len(candidates) == 1, "eia_total_series")
    series = candidates[0]
    require(series["units"] == "billion cubic feet" and series["unitsshort"] == "bcf"
            and series["source"] == "U.S. Energy Information Administration", "eia_units_source")
    values = {}
    for date_value, value in series["data"]:
        day(date_value)
        require(date_value not in values, "eia_duplicate_period")
        values[date_value] = number(value, 0)
    inventory = values[current.isoformat()]
    prior = values[previous.isoformat()]
    calc = series["calculated"]
    average = number(calc["5yr-avg"], 0)
    require(average > 0, "eia_zero_average")
    change = number(calc["net_change"])
    require(abs(inventory-prior-change) <= 1, "eia_inconsistent_change")
    # Persist revision metadata verbatim; revised current observations are not PIT.
    details = dict(observation_date=current.isoformat(), release_date=release.isoformat(),
                   observation_precision="DATE_LABEL_NOT_PUBLICATION_TIME",
                   currency=None, comparison_window=data["5yr_avg"],
                   source_revision_flags=series.get("revision_flag"),
                   source_reclassification_flags=series.get("reclassification_flag"))
    return [observation(raw, "NATURAL_GAS", metric, value, unit,
                        current.isoformat()+"T00:00:00Z", collected, "EIA_STORAGE", **details)
            for metric, value, unit in (
                ("inventory", inventory, "BCF"),
                ("inventory_5y_average", average, "BCF"),
                ("inventory_weekly_change", change, "BCF"),
                ("inventory_vs_5y_average", inventory/average-1, "FRACTION"))]


def network_metrics(raw, subject, metric_id, collected, start, end):
    metric, unit, scale = NETWORK[subject][metric_id]
    data = load_json(raw)
    require(not data.get("next_page_token") and not data.get("next_page_url"), "network_incomplete_page")
    rows = data.get("data")
    require(isinstance(rows, list) and 0 < len(rows) <= 100, "network_rows")
    seen = set()
    parsed = []
    for row in rows:
        require(row.get("asset") == subject.lower(), "network_asset")
        instant = stamp(row["time"])
        require(instant.hour == instant.minute == instant.second == instant.microsecond == 0,
                "network_daily_grid")
        date_value = instant.date()
        require(day(start) <= date_value <= day(end) and date_value not in seen, "network_date_bounds")
        seen.add(date_value)
        observed = instant + timedelta(days=1)
        require(observed <= stamp(collected), "network_unfinished_day")
        source_value = row.get(metric_id)
        value = None
        if source_value not in (None, ""):
            require(isinstance(source_value, str) and bool(re.fullmatch(
                r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", source_value)), "network_number")
            value = number(float(source_value)*scale, 0)
            require(unit != "COUNT" or value.is_integer(), "network_count")
        parsed.append(observation(raw, subject, metric, value, unit, observed.isoformat(),
                      collected, "COINMETRICS_COMMUNITY", observation_date=date_value.isoformat(),
                      observation_precision="UTC_DAILY_INTERVAL_END", currency=subject if unit == "TOKEN" else None,
                      source_metric=metric_id, source_value=source_value, unit_multiplier=scale))
    # The latest returned period controls missingness. Never backfill a missing
    # current metric from an older nonmissing row.
    return [max(parsed, key=lambda r:r["observed_at"])]


def capture_fundamentals(attempt, fetcher=request_bytes, eia_fetcher=request_eia, now=None):
    rows, receipts = [], []
    clock = now or (lambda: datetime.now(timezone.utc))
    tasks = [("NATURAL_GAS", "WNGSR", EIA_URL, eia_fetcher, gas_storage)]
    end = (clock().date()-timedelta(days=1)).isoformat()
    start = (day(end)-timedelta(days=6)).isoformat()
    for subject, metrics in NETWORK.items():
        for metric_id in metrics:
            # Separate requests: an unlicensed metric must not hide available ones.
            url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?" + urlencode(dict(
                assets=subject.lower(), metrics=metric_id, frequency="1d",
                start_time=start, end_time=end, page_size=100))
            tasks.append((subject, metric_id, url, fetcher, None))
    for subject, metric_id, url, getter, parser in tasks:
        receipt = dict(subject_id=subject, series=metric_id,
                       source="EIA_STORAGE" if parser else "COINMETRICS_COMMUNITY")
        try:
            raw = getter(url)
            collected = clock().isoformat()
            raw_hash = hashlib.sha256(raw).hexdigest()
            exclusive(attempt/"raw"/raw_hash, raw)
            receipt["raw_sha256"] = raw_hash
            parsed = parser(raw, collected) if parser else network_metrics(
                raw, subject, metric_id, collected, start, end)
            rows.extend(parsed)
            receipt.update(status="CAPTURED_CURRENT_ONLY" if all(r["value"] is not None for r in parsed)
                           else "PARTIAL_MISSING", rows=len(parsed))
        except Exception:
            receipt.update(status="BLOCKED", reason="provider_unavailable_or_schema")
        receipts.append(receipt)
    return rows, receipts
