#!/usr/bin/env python3
"""Shared helpers for SEC EDGAR point-in-time collectors."""
from __future__ import annotations

import json
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

DEFAULT_SEC_USER_AGENT = "r1000-quant-engine contact: andrewcha231@gmail.com"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def normalize_cik10(value: Any) -> str:
    """Return a 10-character SEC CIK string with leading zeros preserved."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    return digits.zfill(10) if digits else ""


def normalize_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def sec_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": user_agent or DEFAULT_SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def data_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": user_agent or DEFAULT_SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


def sec_get_json(url: str, *, user_agent: str | None = None, throttle_seconds: float = 0.12) -> dict[str, Any]:
    time.sleep(max(0.0, float(throttle_seconds)))
    headers = data_headers(user_agent) if "data.sec.gov" in url else sec_headers(user_agent)
    resp = requests.get(url, headers=headers, timeout=45)
    resp.raise_for_status()
    return resp.json()


def sec_get_text(url: str, *, user_agent: str | None = None, throttle_seconds: float = 0.12) -> str:
    time.sleep(max(0.0, float(throttle_seconds)))
    headers = data_headers(user_agent) if "data.sec.gov" in url else sec_headers(user_agent)
    resp = requests.get(url, headers=headers, timeout=45)
    resp.raise_for_status()
    return resp.text


def parse_sec_datetime(value: Any) -> pd.Timestamp:
    """Parse SEC accepted/filing timestamps as UTC timestamps."""
    if value is None or value == "":
        return pd.NaT
    dt = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(dt):
        return pd.NaT
    return pd.Timestamp(dt)


def available_from(accepted_at: Any, *, safety_delay_hours: float = 12.0) -> pd.Timestamp:
    accepted = parse_sec_datetime(accepted_at)
    if pd.isna(accepted):
        return pd.NaT
    return accepted + pd.Timedelta(timedelta(hours=float(safety_delay_hours)))


def archive_document_url(cik10: str, accession_number: str, primary_document: str) -> str:
    cik_int = str(int(normalize_cik10(cik10)))
    accession_clean = str(accession_number).replace("-", "")
    return f"{SEC_ARCHIVES_BASE}/{cik_int}/{accession_clean}/{primary_document}"


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

