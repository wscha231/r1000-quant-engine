#!/usr/bin/env python3
"""Collect SEC submissions metadata with point-in-time availability fields.

This is a free EDGAR evidence-layer collector. It writes filing metadata only;
form-specific parsing is handled by downstream tools such as
`run_sec_form4_parser.py`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_edgar_common import (
    DEFAULT_SEC_USER_AGENT,
    SEC_COMPANY_TICKERS_URL,
    SEC_SUBMISSIONS_URL,
    available_from,
    archive_document_url,
    normalize_cik10,
    normalize_ticker,
    read_table,
    sec_get_json,
    write_json,
    write_table,
)

DEFAULT_DATA_RAW = "data_raw/sec"
DEFAULT_DATA_PIT = "data_pit/sec"
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_company_tickers(*, user_agent: str, throttle_seconds: float) -> pd.DataFrame:
    payload = sec_get_json(SEC_COMPANY_TICKERS_URL, user_agent=user_agent, throttle_seconds=throttle_seconds)
    rows: list[dict[str, Any]] = []
    for item in payload.values():
        rows.append(
            {
                "ticker": normalize_ticker(item.get("ticker")),
                "name": str(item.get("title") or "").strip(),
                "cik10": normalize_cik10(item.get("cik_str")),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["ticker", "name", "cik10"])
    return frame[frame["ticker"].ne("") & frame["cik10"].ne("")].drop_duplicates("ticker", keep="first")


def tickers_from_args(args: argparse.Namespace) -> list[str]:
    tickers: list[str] = []
    for part in str(args.tickers or "").split(","):
        t = normalize_ticker(part)
        if t:
            tickers.append(t)
    if args.universe_csv:
        path = repo_path(args.universe_csv)
        if path.exists():
            frame = pd.read_csv(path, low_memory=False)
            col = next((c for c in ["ticker", "symbol", "Ticker"] if c in frame.columns), "")
            if col:
                tickers.extend(normalize_ticker(x) for x in frame[col].dropna().tolist())
    out = []
    seen: set[str] = set()
    for t in tickers:
        if t and t not in seen:
            out.append(t)
            seen.add(t)
    return out


def parse_date_bound(value: Any) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        return pd.NaT
    return pd.to_datetime(value, errors="coerce", utc=True)


def filing_date_in_range(value: Any, start_date: pd.Timestamp, end_date: pd.Timestamp) -> bool:
    dt = parse_date_bound(value)
    if pd.isna(dt):
        return True
    if pd.notna(start_date) and dt < start_date:
        return False
    if pd.notna(end_date) and dt > end_date:
        return False
    return True


def archive_file_overlaps(file_meta: dict[str, Any], start_date: pd.Timestamp, end_date: pd.Timestamp) -> bool:
    filing_from = parse_date_bound(file_meta.get("filingFrom"))
    filing_to = parse_date_bound(file_meta.get("filingTo"))
    if pd.notna(start_date) and pd.notna(filing_to) and filing_to < start_date:
        return False
    if pd.notna(end_date) and pd.notna(filing_from) and filing_from > end_date:
        return False
    return True


def filings_from_recent_dict(
    *,
    ticker: str,
    cik10: str,
    recent: dict[str, Any],
    forms: set[str],
    safety_delay_hours: float,
    source: str,
    start_date: pd.Timestamp = pd.NaT,
    end_date: pd.Timestamp = pd.NaT,
) -> pd.DataFrame:
    form_values = recent.get("form", []) or []
    rows: list[dict[str, Any]] = []
    for idx, form_type in enumerate(form_values):
        form = str(form_type or "").upper().strip()
        if forms and form not in forms:
            continue
        accession = str((recent.get("accessionNumber", []) or [""] * len(form_values))[idx] or "").strip()
        accepted = (recent.get("acceptanceDateTime", []) or [""] * len(form_values))[idx]
        filing_date = (recent.get("filingDate", []) or [""] * len(form_values))[idx]
        report_date = (recent.get("reportDate", []) or [""] * len(form_values))[idx]
        primary_doc = str((recent.get("primaryDocument", []) or [""] * len(form_values))[idx] or "").strip()
        if not accession or not filing_date_in_range(filing_date, start_date, end_date):
            continue
        avail = available_from(accepted, safety_delay_hours=safety_delay_hours)
        rows.append(
            {
                "ticker": ticker,
                "cik10": normalize_cik10(cik10),
                "accession_number": accession,
                "form_type": form,
                "filing_date": filing_date,
                "accepted_at": accepted,
                "available_from": avail.isoformat() if pd.notna(avail) else "",
                "period_of_report": report_date,
                "primary_document": primary_doc,
                "filing_url": archive_document_url(cik10, accession, primary_doc) if primary_doc else "",
                "source": source,
                "download_status": "metadata_only",
                "parse_status": "pending",
            }
        )
    return pd.DataFrame(rows)


def filings_from_submissions(
    *,
    ticker: str,
    cik10: str,
    payload: dict[str, Any],
    forms: set[str],
    safety_delay_hours: float,
    max_filings_per_ticker: int,
    start_date: pd.Timestamp = pd.NaT,
    end_date: pd.Timestamp = pd.NaT,
    source: str = "sec_submissions_recent",
) -> pd.DataFrame:
    recent = payload.get("filings", {}).get("recent", {}) or {}
    frame = filings_from_recent_dict(
        ticker=ticker,
        cik10=cik10,
        recent=recent,
        forms=forms,
        safety_delay_hours=safety_delay_hours,
        source=source,
        start_date=start_date,
        end_date=end_date,
    )
    if max_filings_per_ticker and max_filings_per_ticker > 0 and len(frame) > max_filings_per_ticker:
        frame = frame.sort_values(["filing_date", "accepted_at"], ascending=False).head(int(max_filings_per_ticker)).copy()
    return frame


def filings_from_archive_payload(
    *,
    ticker: str,
    cik10: str,
    payload: dict[str, Any],
    forms: set[str],
    safety_delay_hours: float,
    source: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    recent = payload.get("filings", {}).get("recent", payload)
    return filings_from_recent_dict(
        ticker=ticker,
        cik10=cik10,
        recent=recent,
        forms=forms,
        safety_delay_hours=safety_delay_hours,
        source=source,
        start_date=start_date,
        end_date=end_date,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = repo_path(args.raw_root)
    pit_root = repo_path(args.pit_root)
    user_agent = args.sec_user_agent or DEFAULT_SEC_USER_AGENT
    forms = {x.strip().upper() for x in str(args.forms or "").split(",") if x.strip()}
    raw_root.mkdir(parents=True, exist_ok=True)
    pit_root.mkdir(parents=True, exist_ok=True)

    ticker_map = load_company_tickers(user_agent=user_agent, throttle_seconds=args.throttle_seconds)
    write_json(raw_root / "company_tickers.json", ticker_map.to_dict("records"))
    write_table(ticker_map, pit_root / "ticker_cik_map.parquet")

    requested = tickers_from_args(args)
    if not requested:
        if args.all_sec_tickers or int(args.max_tickers) <= 0:
            requested = ticker_map["ticker"].tolist()
        else:
            requested = ticker_map["ticker"].head(int(args.max_tickers)).tolist()
    if args.max_tickers and int(args.max_tickers) > 0:
        requested = requested[: int(args.max_tickers)]
    if args.shard_count and int(args.shard_count) > 1:
        shard_count = max(1, int(args.shard_count))
        shard_index = max(0, int(args.shard_index)) % shard_count
        requested = [ticker for idx, ticker in enumerate(requested) if idx % shard_count == shard_index]

    rows: list[pd.DataFrame] = []
    missing: list[str] = []
    archived_files_requested = 0
    archived_files_loaded = 0
    by_ticker = ticker_map.set_index("ticker")
    submissions_dir = raw_root / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)
    start_date = parse_date_bound(args.start_date)
    end_date = parse_date_bound(args.end_date)
    for ticker in requested:
        if ticker not in by_ticker.index:
            missing.append(ticker)
            continue
        cik10 = str(by_ticker.loc[ticker, "cik10"])
        url = SEC_SUBMISSIONS_URL.format(cik10=cik10)
        try:
            payload = sec_get_json(url, user_agent=user_agent, throttle_seconds=args.throttle_seconds)
            write_json(submissions_dir / f"CIK{cik10}.json", payload)
            frame = filings_from_submissions(
                ticker=ticker,
                cik10=cik10,
                payload=payload,
                forms=forms,
                safety_delay_hours=args.safety_delay_hours,
                max_filings_per_ticker=args.max_filings_per_ticker,
                start_date=start_date,
                end_date=end_date,
            )
            ticker_frames = [frame] if not frame.empty else []
            if args.include_archive_files:
                for file_meta in (payload.get("filings", {}) or {}).get("files", []) or []:
                    name = str(file_meta.get("name") or "").strip()
                    if not name or not archive_file_overlaps(file_meta, start_date, end_date):
                        continue
                    archived_files_requested += 1
                    try:
                        archive_payload = sec_get_json(
                            SEC_SUBMISSIONS_FILE_URL.format(name=name),
                            user_agent=user_agent,
                            throttle_seconds=args.throttle_seconds,
                        )
                        write_json(submissions_dir / name, archive_payload)
                        archive_frame = filings_from_archive_payload(
                            ticker=ticker,
                            cik10=cik10,
                            payload=archive_payload,
                            forms=forms,
                            safety_delay_hours=args.safety_delay_hours,
                            source=f"sec_submissions_file:{name}",
                            start_date=start_date,
                            end_date=end_date,
                        )
                        archived_files_loaded += 1
                        if not archive_frame.empty:
                            ticker_frames.append(archive_frame)
                    except Exception as exc:
                        missing.append(f"{ticker}:{name}:{type(exc).__name__}")
            if ticker_frames:
                ticker_index = pd.concat(ticker_frames, ignore_index=True)
                if args.max_filings_per_ticker and int(args.max_filings_per_ticker) > 0:
                    ticker_index = (
                        ticker_index.sort_values(["filing_date", "accepted_at"], ascending=False)
                        .head(int(args.max_filings_per_ticker))
                        .copy()
                    )
                rows.append(ticker_index)
        except Exception as exc:
            missing.append(f"{ticker}:{type(exc).__name__}")

    index = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=[
            "ticker",
            "cik10",
            "accession_number",
            "form_type",
            "filing_date",
            "accepted_at",
            "available_from",
            "period_of_report",
            "primary_document",
            "filing_url",
            "source",
            "download_status",
            "parse_status",
        ]
    )
    if not index.empty:
        index["cik10"] = index["cik10"].map(normalize_cik10)
        index = index.drop_duplicates(["cik10", "accession_number", "form_type"], keep="first")
    existing_rows = 0
    if args.append_existing:
        existing = read_table(pit_root / "sec_filings_index.parquet")
        existing_rows = int(len(existing))
        if not existing.empty:
            existing["cik10"] = existing["cik10"].map(normalize_cik10)
            index = pd.concat([existing, index], ignore_index=True)
            index = index.drop_duplicates(["cik10", "accession_number", "form_type"], keep="last")
    if not index.empty:
        index = index.sort_values(["ticker", "filing_date", "accession_number"], ascending=[True, False, False]).reset_index(drop=True)
    write_table(index, pit_root / "sec_filings_index.parquet")
    manifest = {
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_tickers": len(requested),
        "filing_rows": int(len(index)),
        "new_filing_rows_before_merge": int(sum(len(frame) for frame in rows)),
        "existing_filing_rows_before_merge": existing_rows,
        "archive_files_requested": archived_files_requested,
        "archive_files_loaded": archived_files_loaded,
        "forms": sorted(forms),
        "missing_or_failed": missing[:200],
        "sec_user_agent": user_agent,
        "safety_delay_hours": float(args.safety_delay_hours),
        "start_date": str(args.start_date or ""),
        "end_date": str(args.end_date or ""),
        "include_archive_files": bool(args.include_archive_files),
        "all_sec_tickers": bool(args.all_sec_tickers),
        "shard_index": int(args.shard_index),
        "shard_count": int(args.shard_count),
        "outputs": {
            "ticker_cik_map": str(pit_root / "ticker_cik_map.parquet"),
            "sec_filings_index": str(pit_root / "sec_filings_index.parquet"),
        },
    }
    write_json(pit_root / "sec_submissions_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="", help="Comma-separated tickers. If empty, uses --universe-csv or first --max-tickers from SEC map.")
    parser.add_argument("--universe-csv", default="", help="Optional CSV with ticker/symbol column.")
    parser.add_argument("--forms", default="4", help="Comma-separated SEC form types to index.")
    parser.add_argument("--raw-root", default=DEFAULT_DATA_RAW)
    parser.add_argument("--pit-root", default=DEFAULT_DATA_PIT)
    parser.add_argument("--sec-user-agent", default=DEFAULT_SEC_USER_AGENT)
    parser.add_argument("--safety-delay-hours", type=float, default=12.0)
    parser.add_argument("--throttle-seconds", type=float, default=0.12)
    parser.add_argument("--max-tickers", type=int, default=250)
    parser.add_argument("--max-filings-per-ticker", type=int, default=80)
    parser.add_argument("--start-date", default="", help="Inclusive filingDate lower bound, e.g. 2018-05-18.")
    parser.add_argument("--end-date", default="", help="Inclusive filingDate upper bound.")
    parser.add_argument("--include-archive-files", action="store_true", help="Fetch older submissions file shards listed under filings.files.")
    parser.add_argument("--append-existing", action="store_true", help="Merge with existing data_pit/sec/sec_filings_index.parquet instead of replacing it.")
    parser.add_argument("--all-sec-tickers", action="store_true", help="Poll the entire SEC ticker map when no explicit ticker/universe list is provided.")
    parser.add_argument("--shard-index", type=int, default=0, help="Zero-based shard index for large EDGAR backfills.")
    parser.add_argument("--shard-count", type=int, default=1, help="Total shard count for large EDGAR backfills.")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json_dumps(payload))
    return 0


def json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
