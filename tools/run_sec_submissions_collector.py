#!/usr/bin/env python3
"""Collect SEC submissions index rows for a ticker universe.

This is a filing-event collector, separate from the existing companyfacts
fundamental pipeline. It writes point-in-time metadata keyed by accepted_at /
available_from so downstream evidence features can avoid lookahead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_helpers import normalize_cik10  # noqa: E402

DEFAULT_FORMS = "4,4/A,SC 13D,SC 13D/A,SC 13G,SC 13G/A,8-K,13F-HR,13F-HR/A,144"
DEFAULT_OUTPUT_DIR = "data_pit/sec"
DEFAULT_RAW_DIR = "data_raw/sec"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"


def cik10(value: Any) -> str:
    return normalize_cik10(value) or ""


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def sec_user_agent(explicit: str | None = None) -> str:
    ua = (explicit or os.environ.get("SEC_USER_AGENT") or "").strip()
    if ua:
        return ua
    return "R1000QuantEngine research contact@example.com"


def sec_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": sec_user_agent(user_agent),
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


def sec_get_json(url: str, *, user_agent: str | None = None, sleep_s: float = 0.12) -> dict[str, Any]:
    if sleep_s > 0:
        time.sleep(float(sleep_s))
    headers = sec_headers(user_agent)
    if "www.sec.gov" in url:
        headers["Host"] = "www.sec.gov"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_sec_datetime(value: Any) -> pd.Timestamp:
    if value is None:
        return pd.NaT
    text = str(value).strip()
    if not text:
        return pd.NaT
    if "T" in text:
        return pd.to_datetime(text, errors="coerce", utc=True)
    return pd.to_datetime(text, errors="coerce", utc=True)


def available_from(value: Any, *, safety_delay_hours: float = 0.0) -> str:
    ts = parse_sec_datetime(value)
    if pd.isna(ts):
        return ""
    if safety_delay_hours:
        ts = ts + timedelta(hours=float(safety_delay_hours))
    return ts.isoformat()


def load_company_tickers(raw_dir: Path, *, user_agent: str | None = None, refresh: bool = False) -> pd.DataFrame:
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache = raw_dir / "company_tickers.json"
    if refresh or not cache.exists():
        data = sec_get_json(COMPANY_TICKERS_URL, user_agent=user_agent)
        cache.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    else:
        data = json.loads(cache.read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    for item in data.values() if isinstance(data, dict) else []:
        ticker = str(item.get("ticker") or "").upper().strip()
        cik = cik10(item.get("cik_str"))
        if ticker and cik:
            rows.append({"ticker": ticker, "cik10": cik, "name": item.get("title", "")})
    return pd.DataFrame(rows).drop_duplicates("ticker", keep="first")


def tickers_from_inputs(tickers: str, universe_file: str | Path | None) -> list[str]:
    out: list[str] = []
    if tickers:
        out.extend([x.strip().upper() for x in tickers.replace(";", ",").split(",") if x.strip()])
    if universe_file:
        path = repo_path(universe_file)
        if path.exists():
            frame = pd.read_csv(path, low_memory=False)
            if "ticker" in frame.columns:
                out.extend(frame["ticker"].astype(str).str.upper().str.strip().tolist())
    return sorted({t for t in out if t and t != "NAN"})


def fetch_submissions(
    cik: str,
    raw_dir: Path,
    *,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
) -> dict[str, Any]:
    norm = cik10(cik)
    if not norm:
        return {}
    out_dir = raw_dir / "submissions"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / f"CIK{norm}.json"
    if refresh or not cache.exists():
        payload = sec_get_json(SUBMISSIONS_URL.format(cik10=norm), user_agent=user_agent, sleep_s=sleep_s)
        cache.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _recent_value(recent: dict[str, list[Any]], key: str, idx: int) -> Any:
    values = recent.get(key) or []
    if idx >= len(values):
        return ""
    return values[idx]


def filing_archive_url(cik: str, accession: str, primary_document: str = "") -> str:
    norm = cik10(cik)
    if not norm or not accession:
        return ""
    cik_int = str(int(norm))
    acc_no_dash = str(accession).replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no_dash}"
    return f"{base}/{primary_document}" if primary_document else base


def filings_from_submissions(
    ticker: str,
    cik: str,
    payload: dict[str, Any],
    *,
    forms: Iterable[str] | None = None,
    safety_delay_hours: float = 0.0,
) -> pd.DataFrame:
    wanted = {str(f).upper().strip() for f in forms or [] if str(f).strip()}
    recent = (payload.get("filings") or {}).get("recent") or {}
    form_values = recent.get("form") or []
    rows: list[dict[str, Any]] = []
    norm_cik = cik10(cik)
    for idx, form in enumerate(form_values):
        form_type = str(form or "").upper().strip()
        if wanted and form_type not in wanted:
            continue
        accession = str(_recent_value(recent, "accessionNumber", idx) or "").strip()
        primary_doc = str(_recent_value(recent, "primaryDocument", idx) or "").strip()
        accepted = _recent_value(recent, "acceptanceDateTime", idx)
        filing_date = _recent_value(recent, "filingDate", idx)
        period = _recent_value(recent, "reportDate", idx)
        rows.append(
            {
                "ticker": str(ticker).upper().strip(),
                "cik10": norm_cik,
                "accession_number": accession,
                "form_type": form_type,
                "filing_date": str(filing_date or ""),
                "accepted_at": parse_sec_datetime(accepted).isoformat() if pd.notna(parse_sec_datetime(accepted)) else "",
                "available_from": available_from(accepted, safety_delay_hours=safety_delay_hours),
                "period_of_report": str(period or ""),
                "primary_document": primary_doc,
                "filing_url": filing_archive_url(norm_cik, accession, primary_doc),
                "source": "sec_submissions_recent",
                "download_status": "indexed",
                "parse_status": "pending",
            }
        )
    return pd.DataFrame(rows)


def collect_filings_index(
    *,
    tickers: list[str],
    raw_dir: Path,
    forms: Iterable[str],
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
    safety_delay_hours: float = 0.0,
    max_tickers: int = 0,
) -> pd.DataFrame:
    ticker_map = load_company_tickers(raw_dir, user_agent=user_agent, refresh=refresh)
    if tickers:
        ticker_map = ticker_map[ticker_map["ticker"].isin(set(tickers))].copy()
    if max_tickers and max_tickers > 0:
        ticker_map = ticker_map.head(int(max_tickers)).copy()

    frames: list[pd.DataFrame] = []
    for _, row in ticker_map.iterrows():
        payload = fetch_submissions(
            str(row["cik10"]),
            raw_dir,
            user_agent=user_agent,
            refresh=refresh,
            sleep_s=sleep_s,
        )
        frame = filings_from_submissions(
            str(row["ticker"]),
            str(row["cik10"]),
            payload,
            forms=forms,
            safety_delay_hours=safety_delay_hours,
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(
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
    out = pd.concat(frames, ignore_index=True)
    out["cik10"] = out["cik10"].map(cik10)
    out = out.sort_values(["ticker", "accepted_at", "accession_number"]).drop_duplicates(
        ["ticker", "accession_number"], keep="last"
    )
    return out


def write_outputs(frame: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "sec_filings_index.parquet"
    csv_path = output_dir / "sec_filings_index.csv"
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False)
    summary = {
        "row_count": int(len(frame)),
        "ticker_count": int(frame["ticker"].nunique()) if "ticker" in frame else 0,
        "form_counts": frame["form_type"].value_counts().to_dict() if "form_type" in frame else {},
        "parquet": str(parquet_path),
        "csv": str(csv_path),
    }
    summary_path = output_dir / "sec_filings_index_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"parquet": str(parquet_path), "csv": str(csv_path), "summary": str(summary_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="", help="Comma-separated ticker list. Empty uses --universe-file.")
    parser.add_argument("--universe-file", default="outputs/scored_latest.csv")
    parser.add_argument("--forms", default=DEFAULT_FORMS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument("--safety-delay-hours", type=float, default=0.0)
    args = parser.parse_args()

    forms = [x.strip().upper() for x in args.forms.split(",") if x.strip()]
    tickers = tickers_from_inputs(args.tickers, args.universe_file)
    frame = collect_filings_index(
        tickers=tickers,
        raw_dir=repo_path(args.raw_dir),
        forms=forms,
        user_agent=args.user_agent,
        refresh=bool(args.refresh),
        sleep_s=float(args.sleep),
        safety_delay_hours=float(args.safety_delay_hours),
        max_tickers=int(args.max_tickers),
    )
    paths = write_outputs(frame, repo_path(args.output_dir))
    print(json.dumps({"status": "ok", "rows": int(len(frame)), **paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
