#!/usr/bin/env python3
"""Parse SEC 13F information-table XML into normalized PIT holdings.

This parser is a filing-event sidecar. It does not change production scores or
target books. 13F is delayed institutional ownership evidence, so downstream
usage must be point-in-time by `accepted_at` / `available_from`, not by the
quarter `report_period`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_submissions_collector import (  # noqa: E402
    cik10,
    filing_archive_url,
    repo_path,
    sec_get_json,
    sec_headers,
)

DEFAULT_INDEX = "data_pit/sec/sec_filings_index.parquet"
DEFAULT_OUTPUT_DIR = "data_pit/sec"
DEFAULT_RAW_DIR = "data_raw/sec"

FORM_13F_TYPES = {"13F-HR", "13F-HR/A"}
FORM13F_DOLLAR_VALUE_EFFECTIVE_DATE = pd.Timestamp("2023-01-03")

FORM13F_COLUMNS = [
    "manager_cik",
    "manager_name",
    "report_period",
    "filing_date",
    "accepted_at",
    "available_from",
    "cusip",
    "issuer_name",
    "title_of_class",
    "ticker_mapped",
    "shares",
    "share_type",
    "market_value_usd",
    "put_call",
    "investment_discretion",
    "other_manager",
    "voting_authority_sole",
    "voting_authority_shared",
    "voting_authority_none",
    "source_accession",
    "filing_url",
]
FORM13F_NUMERIC_COLUMNS = {
    "shares",
    "market_value_usd",
    "voting_authority_sole",
    "voting_authority_shared",
    "voting_authority_none",
}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def first(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    wanted = name.lower()
    for child in node.iter():
        if local_name(child.tag).lower() == wanted:
            return child
    return None


def first_text(node: ET.Element | None, name: str, default: str = "") -> str:
    child = first(node, name)
    if child is None or child.text is None:
        return default
    return str(child.text).strip()


def as_float(value: Any) -> float:
    try:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0.0
        out = float(text)
    except Exception:
        return 0.0
    return out if pd.notna(out) else 0.0


def market_value_usd(value: Any, filing_date: Any = "") -> float:
    """Normalize 13F value to dollars.

    Modern Form 13F XML uses dollar values. Legacy pre-2023 filings commonly
    reported values in thousands. The filing date keeps the conversion
    deterministic for historical backfills.
    """
    raw = as_float(value)
    dt = pd.to_datetime(filing_date, errors="coerce")
    if pd.notna(dt) and getattr(dt, "tzinfo", None) is not None:
        dt = dt.tz_convert(None)
    multiplier = 1000.0 if pd.notna(dt) and dt.normalize() < FORM13F_DOLLAR_VALUE_EFFECTIVE_DATE else 1.0
    return float(raw * multiplier)


def normalize_cusip(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def read_filings_index(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def read_cusip_map(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    frame = pd.read_csv(path, low_memory=False) if path.suffix.lower() != ".parquet" else pd.read_parquet(path)
    cols = {c.lower(): c for c in frame.columns}
    cusip_col = cols.get("cusip")
    ticker_col = cols.get("ticker") or cols.get("ticker_mapped")
    if not cusip_col or not ticker_col:
        return {}
    out: dict[str, str] = {}
    for _, row in frame.iterrows():
        cusip = normalize_cusip(row.get(cusip_col))
        ticker = str(row.get(ticker_col) or "").upper().strip()
        if cusip and ticker:
            out[cusip] = ticker
    return out


def sec_get_text(url: str, *, user_agent: str | None = None, sleep_s: float = 0.12) -> str:
    if sleep_s > 0:
        time.sleep(float(sleep_s))
    headers = sec_headers(user_agent)
    if "www.sec.gov" in url:
        headers["Host"] = "www.sec.gov"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def filing_directory_index_url(cik: str, accession: str) -> str:
    norm = cik10(cik)
    if not norm or not accession:
        return ""
    return f"https://www.sec.gov/Archives/edgar/data/{int(norm)}/{str(accession).replace('-', '')}/index.json"


def list_filing_documents(cik: str, accession: str, *, user_agent: str | None = None, sleep_s: float = 0.12) -> list[str]:
    url = filing_directory_index_url(cik, accession)
    if not url:
        return []
    try:
        payload = sec_get_json(url, user_agent=user_agent, sleep_s=sleep_s)
    except Exception:
        return []
    items = ((payload.get("directory") or {}).get("item") or []) if isinstance(payload, dict) else []
    docs = [str(item.get("name") or "").strip() for item in items if str(item.get("name") or "").strip()]
    return docs


def is_info_table_name(name: str) -> bool:
    text = str(name or "").lower()
    if not text.endswith(".xml"):
        return False
    if text.endswith("primary_doc.xml"):
        return False
    return any(token in text for token in ["infotable", "informationtable", "form13finfo", "13finfo", "primary_doc"])


def cache_name(accession: str, doc_name: str) -> str:
    safe_doc = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(doc_name or "")).strip("_") or "information_table.xml"
    return f"{str(accession).replace('-', '')}_{safe_doc}"


def form13f_url_candidates(
    filing: dict[str, Any],
    *,
    raw_dir: Path | None = None,
    user_agent: str | None = None,
    sleep_s: float = 0.12,
) -> list[str]:
    cik = cik10(filing.get("cik10") or filing.get("manager_cik"))
    accession = str(filing.get("accession_number") or filing.get("source_accession") or "").strip()
    primary_doc = str(filing.get("primary_document") or "").strip()
    filing_url = str(filing.get("filing_url") or "").strip()
    candidates: list[str] = []
    if primary_doc and primary_doc.lower().endswith(".xml"):
        candidates.append(filing_archive_url(cik, accession, primary_doc))
    if filing_url and filing_url.lower().endswith(".xml"):
        candidates.append(filing_url)
    docs = list_filing_documents(cik, accession, user_agent=user_agent, sleep_s=sleep_s)
    for doc in docs:
        if is_info_table_name(doc):
            candidates.append(filing_archive_url(cik, accession, doc))
    for doc in docs:
        text = str(doc or "").lower()
        if text.endswith(".xml") and text != str(primary_doc or "").lower() and not text.endswith("primary_doc.xml"):
            candidates.append(filing_archive_url(cik, accession, doc))
    if primary_doc:
        candidates.append(filing_archive_url(cik, accession, primary_doc))
    if filing_url:
        candidates.append(filing_url)
    out: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url and url not in seen:
            out.append(url)
            seen.add(url)
    return out


def extract_information_table_xml(text: str) -> str:
    """Return an XML payload containing the 13F information table."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if "<informationTable" in raw or ":informationTable" in raw:
        return raw
    match = re.search(r"<XML>(.*?)</XML>", raw, flags=re.IGNORECASE | re.DOTALL)
    if match:
        payload = match.group(1).strip()
        if "infoTable" in payload or "informationTable" in payload:
            return payload
    return raw


def cache_13f_document(
    filing: dict[str, Any],
    raw_dir: Path,
    *,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
) -> tuple[Path | None, str]:
    accession = str(filing.get("accession_number") or "").strip()
    primary_doc = str(filing.get("primary_document") or "information_table.xml").strip()
    if not accession:
        return None, ""
    out_dir = raw_dir / "filings" / "13f"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / cache_name(accession, primary_doc)
    if refresh or not cache.exists():
        errors: list[str] = []
        text = ""
        for url in form13f_url_candidates(filing, raw_dir=raw_dir, user_agent=user_agent, sleep_s=sleep_s):
            try:
                candidate = sec_get_text(url, user_agent=user_agent, sleep_s=sleep_s)
                payload = extract_information_table_xml(candidate)
                if "<infoTable" in payload or ":infoTable" in payload:
                    text = payload
                    break
                errors.append(f"{url}: no infoTable")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        if not text:
            raise RuntimeError("; ".join(errors)[:500] or "no 13F information table URL candidates")
        cache.write_text(text, encoding="utf-8")
    return cache, cache.read_text(encoding="utf-8")


def parse_13f_xml(
    xml_text: str,
    filing: dict[str, Any] | None = None,
    *,
    cusip_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    filing = filing or {}
    cusip_map = cusip_map or {}
    root = ET.fromstring(extract_information_table_xml(xml_text).encode("utf-8"))
    rows: list[dict[str, Any]] = []
    manager_cik = cik10(filing.get("cik10") or filing.get("manager_cik"))
    manager_name = str(filing.get("manager_name") or filing.get("ticker") or "").strip()
    for info in [node for node in root.iter() if local_name(node.tag).lower() == "infotable"]:
        cusip = normalize_cusip(first_text(info, "cusip"))
        ticker = str(first_text(info, "ticker") or cusip_map.get(cusip, "")).upper().strip()
        value_raw = first_text(info, "value")
        rows.append(
            {
                "manager_cik": manager_cik,
                "manager_name": manager_name,
                "report_period": str(filing.get("period_of_report") or filing.get("report_period") or ""),
                "filing_date": str(filing.get("filing_date") or ""),
                "accepted_at": str(filing.get("accepted_at") or ""),
                "available_from": str(filing.get("available_from") or filing.get("accepted_at") or ""),
                "cusip": cusip,
                "issuer_name": first_text(info, "nameOfIssuer"),
                "title_of_class": first_text(info, "titleOfClass"),
                "ticker_mapped": ticker,
                "shares": as_float(first_text(info, "sshPrnamt")),
                "share_type": first_text(info, "sshPrnamtType"),
                "market_value_usd": market_value_usd(value_raw, filing.get("filing_date") or filing.get("accepted_at")),
                "put_call": first_text(info, "putCall"),
                "investment_discretion": first_text(info, "investmentDiscretion"),
                "other_manager": first_text(info, "otherManager"),
                "voting_authority_sole": as_float(first_text(first(info, "votingAuthority"), "Sole")),
                "voting_authority_shared": as_float(first_text(first(info, "votingAuthority"), "Shared")),
                "voting_authority_none": as_float(first_text(first(info, "votingAuthority"), "None")),
                "source_accession": str(filing.get("accession_number") or filing.get("source_accession") or ""),
                "filing_url": str(filing.get("filing_url") or ""),
            }
        )
    return rows


def parse_13f_index(
    index: pd.DataFrame,
    *,
    raw_dir: Path,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
    max_filings: int = 0,
    cusip_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    if index.empty:
        return pd.DataFrame(columns=FORM13F_COLUMNS)
    d = index.copy()
    d["form_type"] = d.get("form_type", "").astype(str).str.upper().str.strip()
    d = d[d["form_type"].isin(FORM_13F_TYPES)].copy()
    if max_filings and max_filings > 0:
        d = d.head(int(max_filings)).copy()

    rows: list[dict[str, Any]] = []
    for _, item in d.iterrows():
        filing = item.to_dict()
        try:
            _, xml_text = cache_13f_document(
                filing,
                raw_dir,
                user_agent=user_agent,
                refresh=refresh,
                sleep_s=sleep_s,
            )
            rows.extend(parse_13f_xml(xml_text, filing, cusip_map=cusip_map))
        except Exception as exc:
            rows.append(
                {
                    **{col: "" for col in FORM13F_COLUMNS},
                    "manager_cik": cik10(filing.get("cik10")),
                    "manager_name": str(filing.get("ticker") or ""),
                    "report_period": str(filing.get("period_of_report") or ""),
                    "filing_date": str(filing.get("filing_date") or ""),
                    "accepted_at": str(filing.get("accepted_at") or ""),
                    "available_from": str(filing.get("available_from") or ""),
                    "source_accession": str(filing.get("accession_number") or ""),
                    "filing_url": str(filing.get("filing_url") or ""),
                    "issuer_name": f"PARSE_ERROR: {str(exc)[:180]}",
                }
            )
    out = pd.DataFrame(rows)
    for col in FORM13F_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0 if col in {"shares", "market_value_usd", "voting_authority_sole", "voting_authority_shared", "voting_authority_none"} else ""
    out["manager_cik"] = out["manager_cik"].map(cik10)
    return out[FORM13F_COLUMNS].copy()


def write_outputs(frame: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = sanitize_13f_frame(frame)
    parquet_path = output_dir / "institutional_13f_holdings.parquet"
    csv_path = output_dir / "institutional_13f_holdings.csv"
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False)
    summary = {
        "row_count": int(len(frame)),
        "manager_count": int(frame["manager_cik"].nunique()) if "manager_cik" in frame else 0,
        "mapped_ticker_count": int(frame["ticker_mapped"].replace("", pd.NA).nunique(dropna=True))
        if "ticker_mapped" in frame
        else 0,
        "parquet": str(parquet_path),
        "csv": str(csv_path),
    }
    summary_path = output_dir / "institutional_13f_holdings_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {"parquet": str(parquet_path), "csv": str(csv_path), "summary": str(summary_path)}


def sanitize_13f_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Stabilize 13F schema before parquet export.

    Broader manager shards can include parse-error rows or option rows with
    blank share fields. Pandas may then keep numeric columns as object dtype,
    which makes pyarrow fail at write time. The PIT row is still useful for
    diagnostics, so coerce numeric fields to zero and keep identifiers as
    strings.
    """
    out = frame.copy() if not frame.empty else pd.DataFrame(columns=FORM13F_COLUMNS)
    for col in FORM13F_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0 if col in FORM13F_NUMERIC_COLUMNS else ""
    out["manager_cik"] = out["manager_cik"].map(cik10)
    for col in FORM13F_NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype(float)
    for col in FORM13F_COLUMNS:
        if col not in FORM13F_NUMERIC_COLUMNS:
            out[col] = out[col].fillna("").astype(str)
    return out[FORM13F_COLUMNS].copy()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings-index", default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--cusip-map", default="")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--max-filings", type=int, default=0)
    args = parser.parse_args()

    cusip_map = read_cusip_map(repo_path(args.cusip_map)) if args.cusip_map else {}
    frame = parse_13f_index(
        read_filings_index(repo_path(args.filings_index)),
        raw_dir=repo_path(args.raw_dir),
        user_agent=args.user_agent,
        refresh=bool(args.refresh),
        sleep_s=float(args.sleep),
        max_filings=int(args.max_filings),
        cusip_map=cusip_map,
    )
    paths = write_outputs(frame, repo_path(args.output_dir))
    print(json.dumps({"status": "ok", "rows": int(len(frame)), **paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
