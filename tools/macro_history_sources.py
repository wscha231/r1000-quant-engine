#!/usr/bin/env python3
"""Bounded FRED/ALFRED research collection; immutable raw objects, no trading state.

Graph history is current_only. ALFRED real-time dates are date-level archive
evidence, admitted only after that New York date ends, never as intraday news.
The collection receipt is not evidence of remote persistence or PIT prices.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/macro_indicator_registry.json"
MAX_BYTES = 16 * 1024 * 1024
MAX_PAGES = 20


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "timezone_required")
    return result.astimezone(timezone.utc)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def exclusive(path, raw):
    """Write once. Existing identical objects are idempotent; conflicts fail."""
    path = Path(path)
    require(not any(p.is_symlink() for p in [path, *path.parents]), "symlink_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        require(path.read_bytes() == raw, "immutable_path_conflict")


def registry():
    return json.loads(REGISTRY.read_bytes())


def number(value):
    if value in (".", "", None):
        return None
    result = float(value)
    require(math.isfinite(result), "nonfinite_value")
    return result


def parse_graph(raw, series, start, through, retrieved):
    first, last = date.fromisoformat(start), date.fromisoformat(through)
    require(first <= last <= stamp(retrieved).date(), "observation_window")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    require(reader.fieldnames in (["observation_date", series], ["DATE", series]), "graph_schema")
    seen, records, missing = set(), [], []
    for row in reader:
        require(set(row) == set(reader.fieldnames), "graph_row")
        day = date.fromisoformat(row[reader.fieldnames[0]])
        require(day not in seen and day <= last, "duplicate_or_future_observation")
        seen.add(day)
        # FRED may return a period anchor before cosd. It is not a release.
        if day < first:
            continue
        value = number(row[series])
        if value is None:
            missing.append(day.isoformat())
            continue
        records.append(dict(series=series, observation_date=day.isoformat(), value=value,
                            available_at=retrieved, published_at=None, vintage_date=None,
                            evidence="current_only", retrieved_at=retrieved))
    require(bool(records), "empty_series")
    return records, missing


def parse_alfred(pages, series, start, through, retrieved):
    """Parse complete output_type=1 pages; keep every revision and withdrawal."""
    first, last = date.fromisoformat(start), date.fromisoformat(through)
    require(first <= last <= stamp(retrieved).date(), "observation_window")
    seen, records, expected_offset, total = set(), [], 0, None
    for raw in pages:
        payload = json.loads(raw)
        require(payload.get("units") == "lin" and payload.get("output_type") == 1,
                "alfred_output_contract")
        require(payload.get("offset") == expected_offset, "alfred_page_offset")
        count = payload.get("count")
        require(isinstance(count, int) and 0 < count <= MAX_PAGES * 10000, "alfred_count")
        require(total is None or count == total, "alfred_count_changed")
        total = count
        rows = payload.get("observations", [])
        require(isinstance(rows, list) and bool(rows), "alfred_empty_page")
        for row in rows:
            day = date.fromisoformat(row["date"])
            vintage = date.fromisoformat(row["realtime_start"])
            end = date.fromisoformat(row["realtime_end"])
            identity = (day, vintage)
            require(first <= day <= last and day <= vintage <= last and end >= vintage,
                    "alfred_date_bounds")
            require(identity not in seen, "alfred_duplicate_vintage")
            seen.add(identity)
            # No release time is inferred from a month-start observation label.
            available = datetime.combine(vintage + timedelta(days=1), time(),
                                         ZoneInfo("America/New_York")).astimezone(timezone.utc)
            records.append(dict(series=series, observation_date=day.isoformat(),
                value=number(row["value"]), vintage_date=vintage.isoformat(),
                realtime_end=end.isoformat(), available_at=available.isoformat(),
                published_at=None, evidence="alfred_date_archive", retrieved_at=retrieved))
        expected_offset += len(rows)
    require(total == expected_offset, "alfred_incomplete_pagination")
    # Overlapping intervals would allow two values to be true at one decision.
    by_period = {}
    for record in sorted(records, key=lambda r: (r["observation_date"], r["vintage_date"])):
        previous = by_period.get(record["observation_date"])
        require(previous is None or previous < record["vintage_date"], "alfred_overlapping_vintages")
        by_period[record["observation_date"]] = record["realtime_end"]
    return records


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect_rejected")


def request_bytes(url, *, secret=None):
    with build_opener(NoRedirect()).open(Request(url, headers={
        "User-Agent": "macro-evidence-research/1.0", "Accept": "application/json,text/csv"}), timeout=20) as response:
        require(response.status == 200, "provider_status")
        raw = response.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, "response_size")
    require(not secret or secret.encode() not in raw, "credential_echo_rejected")
    return raw


def fetch(series, start, through, mode):
    if mode == "current":
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(
            dict(id=series, cosd=start, coed=through))
        return [request_bytes(url)], utc_now()
    key = os.environ.get("FRED_API_KEY")
    require(bool(key), "fred_key_unavailable")
    pages, offset = [], 0
    for _ in range(MAX_PAGES):
        url = "https://api.stlouisfed.org/fred/series/observations?" + urlencode(dict(
            series_id=series, api_key=key, file_type="json", units="lin", output_type=1,
            observation_start=start, observation_end=through, realtime_start="1776-07-04",
            realtime_end=through, limit=10000, offset=offset))
        raw = request_bytes(url, secret=key)
        data = json.loads(raw)
        pages.append(raw)
        rows = data.get("observations", [])
        require(bool(rows), "alfred_empty_page")
        offset += len(rows)
        if offset == data.get("count"):
            return pages, utc_now()
        require(offset < data.get("count", 0), "alfred_count")
    raise ValueError("alfred_page_limit")


def period_gaps(records, frequency):
    days = sorted({r["observation_date"] for r in records if r["value"] is not None})
    if frequency != "monthly":
        return None
    months = {int(d[:4])*12 + int(d[5:7]) - 1 for d in days}
    return [f"{n//12:04d}-{n%12+1:02d}" for n in range(min(months), max(months)+1) if n not in months] if months else []


def collect(store, series_ids, start, through, mode="current", fetcher=fetch):
    specs = {s["id"]: s for s in registry()["series"]}
    require(mode in ("current", "alfred") and 0 < len(series_ids) <= 40, "collection_scope")
    require(len(series_ids) == len(set(series_ids)) and set(series_ids) <= set(specs), "unknown_series")
    require(date.fromisoformat(start) <= date.fromisoformat(through) <= stamp(utc_now()).date(), "collection_window")
    store = Path(store)
    items = []
    for series in series_ids:
        try:
            pages, retrieved = fetcher(series, start, through, mode)
            require(0 < len(pages) <= MAX_PAGES and all(0 < len(p) <= MAX_BYTES for p in pages), "source_bounds")
            if mode == "current":
                require(len(pages) == 1, "graph_page_count")
                records, missing = parse_graph(pages[0], series, start, through, retrieved)
            else:
                records, missing = parse_alfred(pages, series, start, through, retrieved), []
            hashes = [digest(raw) for raw in pages]
            for raw, sha in zip(pages, hashes):
                exclusive(store / "objects" / sha, raw)
            data = encoded(records)
            data_hash = digest(data)
            exclusive(store / "objects" / data_hash, data)
            item = dict(series=series, status="COLLECTED", records_sha256=data_hash,
                raw_sha256=hashes, source_uri="https://fred.stlouisfed.org/series/"+series,
                rows=len(records), observation_periods=len({r["observation_date"] for r in records}),
                earliest=min(r["observation_date"] for r in records),
                latest=max(r["observation_date"] for r in records), retrieved_at=retrieved,
                evidence=records[0]["evidence"], missing_value_count=len(missing),
                internal_missing_months=period_gaps(records, specs[series]["frequency"]))
            items.append(item)
        except HTTPError as exc:
            items.append(dict(series=series, status="BLOCKED", reason="HTTP_"+str(exc.code)))
        except (URLError, TimeoutError, OSError):
            items.append(dict(series=series, status="BLOCKED", reason="TRANSPORT_OR_STORE_ERROR"))
        except (ValueError, TypeError, KeyError, UnicodeError, csv.Error):
            # Arbitrary exception messages and API URLs must not enter reports.
            items.append(dict(series=series, status="BLOCKED", reason="SOURCE_CONTRACT_OR_KEY"))
    receipt = dict(schema="macro-history-bundle-v1", mode=mode, requested_start=start,
        requested_through=through, created_at=utc_now(), registry_sha256=digest(REGISTRY.read_bytes()),
        sources=items, durable_remote_verified=False, historical_price_pit_verified=False)
    raw = encoded(receipt)
    path = store / "receipts" / (digest(raw)+".json")
    exclusive(path, raw)
    return receipt, path


def load_bundle(store, receipt_path):
    raw = Path(receipt_path).read_bytes()
    require(Path(receipt_path).stem == digest(raw), "receipt_hash")
    receipt = json.loads(raw)
    require(receipt["schema"] == "macro-history-bundle-v1", "receipt_schema")
    require(receipt["registry_sha256"] == digest(REGISTRY.read_bytes()), "registry_changed")
    records = {}
    for source in receipt["sources"]:
        if source["status"] != "COLLECTED":
            continue
        hashes = source["raw_sha256"] + [source["records_sha256"]]
        for sha in hashes:
            require(re.fullmatch("[0-9a-f]{64}", sha) is not None, "object_identity")
            data = (Path(store)/"objects"/sha).read_bytes()
            require(digest(data) == sha, "object_hash")
        records[source["series"]] = json.loads(data)
    return receipt, records


def update_plan(as_of, previous, release_events):
    """Actual supplied release instants drive due work; frequency is not a date."""
    cutoff = stamp(as_of)
    specs = registry()["series"]
    result = []
    for spec in specs:
        known = [stamp(e["release_at"]) for e in release_events if e["series"] == spec["id"]]
        last = previous.get(spec["id"])
        observed = stamp(last["retrieved_at"]) if last else None
        due = any(t <= cutoff and (observed is None or t > observed) for t in known)
        future = [t for t in known if t > cutoff]
        status = "BACKFILL_REQUIRED" if not last else (
            "RELEASE_DUE" if due else "WAIT_RELEASE" if future else "CALENDAR_REFRESH_REQUIRED")
        result.append(dict(series=spec["id"], status=status,
            next_release_at=min(future).isoformat() if future else None,
            last_observation_date=last.get("latest") if last else None,
            release_completeness="REQUIRES_SOURCE_COVERAGE_CHECK",
            calendar_url=spec["calendar_url"], revision_overlap=spec["revision_overlap"],
            reevaluation="after_data_change_and_mature_labels",
            model_replacement="reviewed_challenger_only"))
    return result


def fetch_calendar(series_ids, start, through):
    """Fetch official release calendars; date-only schedules get no invented time."""
    specs = {s["id"] for s in registry()["series"]}
    require(set(series_ids) <= specs and len(series_ids) <= 40, "calendar_scope")
    require(0 <= (date.fromisoformat(through)-date.fromisoformat(start)).days <= 400, "calendar_window")
    key = os.environ.get("FRED_API_KEY")
    require(bool(key), "fred_key_unavailable")
    events, releases = [], {}
    for series in series_ids:
        url = "https://api.stlouisfed.org/fred/series/release?" + urlencode(
            dict(series_id=series, api_key=key, file_type="json"))
        metadata = json.loads(request_bytes(url, secret=key))
        release_rows = metadata.get("releases", [])
        require(len(release_rows) == 1, "series_release_identity")
        release_id = release_rows[0]["id"]
        require(isinstance(release_id, int) and release_id > 0, "release_id")
        if release_id not in releases:
            url = "https://api.stlouisfed.org/fred/release/dates?" + urlencode(dict(
                release_id=release_id, api_key=key, file_type="json", realtime_start=start,
                realtime_end=through, include_release_dates_with_no_data="true", limit=1000))
            payload = json.loads(request_bytes(url, secret=key))
            release_dates = payload.get("release_dates", [])
            require(payload.get("count") == len(release_dates), "incomplete_calendar")
            releases[release_id] = release_dates
        for row in releases[release_id]:
            require(row["release_id"] == release_id, "calendar_identity")
            day = date.fromisoformat(row["date"])
            require(date.fromisoformat(start) <= day <= date.fromisoformat(through), "calendar_date")
            check = datetime.combine(day+timedelta(days=1),time(),ZoneInfo("America/New_York"))
            events.append(dict(series=series, release_date=day.isoformat(),
                release_at=check.astimezone(timezone.utc).isoformat(), time_precision="date_only_end_of_day_check",
                source_uri="https://fred.stlouisfed.org/release?rid="+str(release_id)))
    return dict(schema="macro-release-calendar-v1", retrieved_at=utc_now(), events=events)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action", choices=["collect", "calendar", "plan"], default="collect")
    p.add_argument("--store")
    p.add_argument("--start", default="2000-01-01")
    p.add_argument("--through", required=True)
    p.add_argument("--series", default="SP500,NASDAQCOM,DGS2,DGS10,UNRATE,PAYEMS,CPIAUCSL,WALCL,WTREGEN,RRPONTSYD,SOFR,M2SL")
    p.add_argument("--mode", choices=["current", "alfred"], default="current")
    p.add_argument("--report", required=True)
    p.add_argument("--release-events")
    p.add_argument("--previous-receipt")
    args = p.parse_args()
    if args.action == "calendar":
        exclusive(args.report, encoded(fetch_calendar(args.series.split(","), args.start, args.through)))
        return 0
    if args.action == "plan":
        require(args.release_events is not None, "release_calendar_required")
        calendar = json.loads(Path(args.release_events).read_bytes())
        previous = {}
        if args.previous_receipt:
            require(args.store is not None, "store_required")
            receipt, _ = load_bundle(args.store, args.previous_receipt)
            previous = {s["series"]:s for s in receipt["sources"] if s["status"] == "COLLECTED"}
        exclusive(args.report, encoded(dict(as_of=utc_now(), calendar_sha256=digest(encoded(calendar)),
            jobs=update_plan(utc_now(), previous, calendar["events"]), scheduled_service_installed=False)))
        return 0
    require(args.store is not None, "store_required")
    receipt, path = collect(args.store, args.series.split(","), args.start, args.through, args.mode)
    summary = dict(receipt=path.name, **receipt)
    exclusive(args.report, encoded(summary))
    print(json.dumps(dict(receipt=str(path), collected=sum(s["status"]=="COLLECTED" for s in receipt["sources"]),
                          requested=len(receipt["sources"]))))
    return 0 if all(s["status"]=="COLLECTED" for s in receipt["sources"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
