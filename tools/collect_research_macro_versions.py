#!/usr/bin/env python3
"""Collect bounded public FRED current vintages into an independent research store.

No provider credentials, paper ledger, accepted head or old archive is needed.
Current graph values are forward evidence only; ALFRED vintage reconstruction
is a separate adapter. This command is a collection pilot, not a fund replay.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.research_lifecycle import Store, iso, require, safe_path, timestamp, utc_now

SERIES = ("DGS2", "DGS10", "UNRATE")
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect_rejected")


def parse_fred(raw, series, start, through, retrieved_at):
    require(series in SERIES, "series_not_allowlisted")
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, "response_size_bound")
    first, last = date.fromisoformat(start), date.fromisoformat(through)
    require(first <= last <= timestamp(retrieved_at).date(), "observation_window")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    require(reader.fieldnames in (["observation_date", series], ["DATE", series]), "fred_csv_schema")
    date_field = reader.fieldnames[0]
    rows, seen = [], set()
    for row in reader:
        require(set(row) == {date_field, series} and row[series] is not None, "fred_csv_row")
        day = date.fromisoformat(row[date_field])
        require(first <= day <= last and day not in seen, "duplicate_or_out_of_window_observation")
        seen.add(day)
        if row[series] in {"", "."}:
            continue
        value = float(row[series])
        # Store validation also rejects nonfinite numbers. Reject before any
        # raw-source publication to keep malformed batches all-or-nothing.
        require(-1000 < value < 1000, "macro_value_invalid")
        rows.append(dict(source="FRED_graph", kind="macro", entity=series, field="percent",
                         effective_at=day.isoformat()+"T00:00:00Z", available_at=iso(retrieved_at),
                         value=value, evidence="current_only"))
    require(bool(rows), "no_usable_observations")
    return rows


def fetch(series, start, through):
    require(series in SERIES, "series_not_allowlisted")
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + urlencode(dict(id=series, cosd=start, coed=through))
    # fredgraph.csv is the public graph export; source_uri in the receipt is the
    # stable public series page without a credential-bearing query.
    request = Request(url, headers={"User-Agent": "research-data-lifecycle/1.0", "Accept": "text/csv"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        require(response.status == 200, "provider_status")
        raw = response.read(MAX_BYTES+1)
    require(len(raw) <= MAX_BYTES, "response_size_bound")
    return raw, utc_now()


def collect(store, *, dataset, start, through, fetcher=fetch):
    require(date.fromisoformat(start) <= date.fromisoformat(through) <= timestamp(utc_now()).date(), "collection_window")
    initial_head = store.head(dataset)
    summaries = []
    for series in SERIES:
        try:
            raw, retrieved = fetcher(series, start, through)
            rows = parse_fred(raw, series, start, through, retrieved)
            batch = dict(dataset=dataset, data_kind="REAL", retrieved_at=retrieved,
                         source_uri="https://fred.stlouisfed.org/series/"+series,
                         raw_sha256=hashlib.sha256(raw).hexdigest(), records=rows)
            # Retain source bytes privately for parser reproduction. Neither
            # these bytes nor this store are uploaded by the PR workflow.
            raw_object = store.put(dict(type="public_source_bytes", encoding="base64",
                                        raw_sha256=batch["raw_sha256"], data=base64.b64encode(raw).decode("ascii")))
            result = store.ingest(batch, expected_head=store.head(dataset))
            # Replay the SAME received batch to demonstrate idempotency. This
            # is deliberately not described as a second live provider fetch.
            repeated = store.ingest(batch, expected_head=result["snapshot"])
            require(repeated["status"] == "UNCHANGED", "same_batch_not_idempotent")
            summaries.append(dict(series=series, status="COLLECTED", rows=len(rows),
                earliest_observation_date=min(r["effective_at"][:10] for r in rows),
                latest_observation_date=max(r["effective_at"][:10] for r in rows),
                retrieved_at=retrieved, raw_sha256=batch["raw_sha256"], raw_object=raw_object,
                snapshot=result["snapshot"], receipt=result["receipt"],
                changed_partitions=result["changed_partitions"], added_records=result["added_records"],
                repeated_same_batch_status=repeated["status"], evidence="current_only"))
        except HTTPError as exc:
            summaries.append(dict(series=series, status="BLOCKED", reason="HTTP_"+str(exc.code)))
        except (URLError, TimeoutError, OSError):
            summaries.append(dict(series=series, status="BLOCKED", reason="TRANSPORT_ERROR"))
        except (ValueError, UnicodeError, csv.Error, TypeError):
            summaries.append(dict(series=series, status="BLOCKED", reason="VALIDATION_ERROR"))
    head = store.head(dataset)
    archived_rows = len(store.as_of(head, through+"T23:59:59Z")) if head else 0
    succeeded = sum(s["status"] == "COLLECTED" for s in summaries)
    return dict(schema_version="research-macro-pilot-v1", data_kind="REAL", dataset=dataset,
        generated_at=utc_now(), start=start, through=through, initial_snapshot=initial_head,
        final_snapshot=head, status="COLLECTED" if succeeded == len(SERIES) else "PARTIAL" if succeeded else "BLOCKED",
        series=summaries, archival_mode_usable_rows=archived_rows, historical_replay_ready=False,
        full_fund_backtest_executed=False, returns_generated=False, orders_allowed=False,
        dependencies_used=["public_FRED_graph"], legacy_artifacts_required=False,
        durable_scheduler_installed=False,
        remaining_inputs=["historical_macro_vintages", "historical_universe_and_delistings",
                          "raw_prices_actions_and_fx", "SEC_publication_timed_fundamentals",
                          "chronological_candidate_selection", "verified_fund_engine_integration"])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--dataset", default="fresh_macro_observations_v1")
    parser.add_argument("--start", required=True)
    parser.add_argument("--through", required=True)
    parser.add_argument("--report", required=True)
    args=parser.parse_args()
    output=collect(Store(args.store), dataset=args.dataset, start=args.start, through=args.through)
    destination=safe_path(args.report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, sort_keys=True)+"\n")
    print(json.dumps(output, sort_keys=True))
    return 0 if output["status"] == "COLLECTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
