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
    sec_get_json,
    write_json,
    write_table,
)

DEFAULT_DATA_RAW = "data_raw/sec"
DEFAULT_DATA_PIT = "data_pit/sec"


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


def filings_from_submissions(
    *,
    ticker: str,
    cik10: str,
    payload: dict[str, Any],
    forms: set[str],
    safety_delay_hours: float,
    max_filings_per_ticker: int,
) -> pd.DataFrame:
    recent = payload.get("filings", {}).get("recent", {}) or {}
    form_values = recent.get("form", []) or []
    rows: list[dict[str, Any]] = []
    limit = max(0, int(max_filings_per_ticker)) or len(form_values)
    for idx, form_type in enumerate(form_values[:limit]):
        form = str(form_type or "").upper().strip()
        if forms and form not in forms:
            continue
        accession = str((recent.get("accessionNumber", []) or [""] * len(form_values))[idx] or "").strip()
        accepted = (recent.get("acceptanceDateTime", []) or [""] * len(form_values))[idx]
        filing_date = (recent.get("filingDate", []) or [""] * len(form_values))[idx]
        report_date = (recent.get("reportDate", []) or [""] * len(form_values))[idx]
        primary_doc = str((recent.get("primaryDocument", []) or [""] * len(form_values))[idx] or "").strip()
        if not accession:
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
                "source": "sec_submissions_recent",
                "download_status": "metadata_only",
                "parse_status": "pending",
            }
        )
    return pd.DataFrame(rows)


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
        requested = ticker_map["ticker"].head(int(args.max_tickers)).tolist()
    if args.max_tickers:
        requested = requested[: int(args.max_tickers)]

    rows: list[pd.DataFrame] = []
    missing: list[str] = []
    by_ticker = ticker_map.set_index("ticker")
    submissions_dir = raw_root / "submissions"
    submissions_dir.mkdir(parents=True, exist_ok=True)
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
            )
            if not frame.empty:
                rows.append(frame)
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
    write_table(index, pit_root / "sec_filings_index.parquet")
    manifest = {
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_tickers": len(requested),
        "filing_rows": int(len(index)),
        "forms": sorted(forms),
        "missing_or_failed": missing[:200],
        "sec_user_agent": user_agent,
        "safety_delay_hours": float(args.safety_delay_hours),
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
