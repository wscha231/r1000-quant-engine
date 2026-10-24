#!/usr/bin/env python3
"""Parse SEC 13F information-table XML into normalized PIT holdings.

This parser is a filing-event sidecar. It does not change production scores or
target books. 13F is delayed institutional ownership evidence, so downstream
usage must be point-in-time by `accepted_at` / `available_from`, not by the
quarter `report_period`.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import time
from datetime import date, timedelta
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
    atomic_json, content_hash, exact_utc, file_hash, utc_now,
    filings_from_submissions, validate_submissions,
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
    "form_type",
    "amendment_type",
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


def as_float(value: Any) -> float | None:
    try:
        text = ("" if value is None else str(value)).replace(",", "").strip()
        if not text:
            return None
        out = float(text)
    except Exception:
        return None
    return out if math.isfinite(out) else None


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
    return float(raw * multiplier) if raw is not None else None


def selected_restore_paths(index: pd.DataFrame, *, as_of: str, max_filings: int) -> list[str]:
    """Use accession keys to restore only the XML the existing parser will use."""
    cutoff = exact_utc(as_of)
    d = index[index["form_type"].isin(FORM_13F_TYPES)].copy()
    available = pd.to_datetime(d["available_from"], utc=True, errors="coerce")
    d = d[available.notna() & (available <= cutoff)].copy()
    d["_accepted_sort"] = pd.to_datetime(d["accepted_at"], utc=True, errors="coerce")
    d["_filing_sort"] = pd.to_datetime(d["filing_date"], utc=True, errors="coerce")
    d = d.sort_values(["_accepted_sort", "_filing_sort", "cik10", "accession_number"], ascending=[False, False, True, False])
    if max_filings > 0:
        d = d.head(max_filings)
    result = set()
    for _, row in d.iterrows():
        accession = str(row["accession_number"])
        if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
            raise ValueError("13F_RESTORE_ACCESSION")
        name = cache_name(accession, str(row["primary_document"]) or "information_table.xml")
        result.add("filings/13f/" + name)
        result.add("parsed/13f/" + name + ".json")
        if str(row["form_type"]) == "13F-HR/A":
            result.add("filings/13f_cover/" + name)
    return sorted(result)


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
    frame = (
        pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
        if path.suffix.lower() != ".parquet"
        else pd.read_parquet(path)
    )
    return cusip_map_from_frame(frame)


def cusip_map_from_frame(frame: pd.DataFrame) -> dict[str, str]:
    """The same exact-map rules for files and immutable stored bytes."""
    cols = {c.lower(): c for c in frame.columns}
    cusip_col = cols.get("cusip")
    ticker_col = cols.get("ticker") or cols.get("ticker_mapped")
    if not cusip_col or not ticker_col:
        return {}
    out: dict[str, str] = {}
    for _, row in frame.iterrows():
        raw_cusip, raw_ticker = row.get(cusip_col), row.get(ticker_col)
        cusip = "" if pd.isna(raw_cusip) else normalize_cusip(raw_cusip)
        ticker = "" if pd.isna(raw_ticker) else str(raw_ticker or "").upper().strip()
        if cusip and ticker:
            if cusip in out and out[cusip] != ticker:
                raise ValueError("13F_CUSIP_MAPPING_CONFLICT")
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


def cache_13f_amendment_type(
    filing: dict[str, Any],
    raw_dir: Path,
    *,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
) -> str:
    form_type = str(filing.get("form_type") or "").upper().strip()
    if form_type == "13F-HR":
        return "ORIGINAL"
    if form_type != "13F-HR/A":
        return ""
    cik = cik10(filing.get("cik10") or filing.get("manager_cik"))
    accession = str(filing.get("accession_number") or "").strip()
    primary_doc = str(filing.get("primary_document") or "").strip()
    if not cik or not accession or not primary_doc:
        raise RuntimeError("13F amendment is missing CIK, accession, or primary document")
    out_dir = raw_dir / "filings" / "13f_cover"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / cache_name(accession, primary_doc)
    if refresh or not cache.exists():
        text = sec_get_text(
            filing_archive_url(cik, accession, primary_doc),
            user_agent=user_agent,
            sleep_s=sleep_s,
        )
        cache.write_text(text, encoding="utf-8")
    return amendment_type_from_text(cache.read_text(encoding="utf-8"))


def amendment_type_from_text(text: str) -> str:
    match = re.search(
        r"<(?:[A-Za-z0-9_]+:)?amendmentType[^>]*>\s*([^<]+?)\s*</",
        text,
        flags=re.IGNORECASE,
    )
    amendment_type = re.sub(r"[_-]+", " ", match.group(1) if match else "").upper().strip()
    if amendment_type not in {"RESTATEMENT", "NEW HOLDINGS"}:
        raise RuntimeError(f"unrecognized 13F amendment type: {amendment_type or 'missing'}")
    return amendment_type


def parse_13f_xml(
    xml_text: str,
    filing: dict[str, Any] | None = None,
    *,
    cusip_map: dict[str, str] | None = None,
    exact_cusip_only: bool = False,
) -> list[dict[str, Any]]:
    filing = filing or {}
    cusip_map = cusip_map or {}
    root = ET.fromstring(extract_information_table_xml(xml_text).encode("utf-8"))
    rows: list[dict[str, Any]] = []
    manager_cik = cik10(filing.get("cik10") or filing.get("manager_cik"))
    manager_name = str(filing.get("manager_name") or filing.get("ticker") or "").strip()
    for info in [node for node in root.iter() if local_name(node.tag).lower() == "infotable"]:
        cusip = normalize_cusip(first_text(info, "cusip"))
        embedded_ticker = first_text(info, "ticker").upper().strip()
        explicit_ticker = str(cusip_map.get(cusip, "")).upper().strip()
        if exact_cusip_only and embedded_ticker and explicit_ticker and embedded_ticker != explicit_ticker:
            raise ValueError("13F_CUSIP_MAPPING_CONFLICT")
        ticker = explicit_ticker if exact_cusip_only else (embedded_ticker or explicit_ticker)
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
                "form_type": str(filing.get("form_type") or "").upper().strip(),
                "amendment_type": str(filing.get("amendment_type") or "").upper().strip(),
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
    exact_cusip_only: bool = False,
    as_of: str = "",
) -> pd.DataFrame:
    if index.empty:
        return pd.DataFrame(columns=FORM13F_COLUMNS)
    d = index.copy()
    d["form_type"] = d.get("form_type", "").astype(str).str.upper().str.strip()
    d = d[d["form_type"].isin(FORM_13F_TYPES)].copy()
    if as_of:
        cutoff = pd.to_datetime(as_of, errors="coerce", utc=True)
        if pd.isna(cutoff):
            raise ValueError(f"invalid 13F parser as-of timestamp: {as_of}")
        available_source = d["available_from"] if "available_from" in d.columns else pd.Series("", index=d.index)
        available = pd.to_datetime(available_source, errors="coerce", utc=True)
        d = d[available.notna() & (available <= cutoff)].copy()
    if max_filings and max_filings > 0:
        d["_accepted_sort"] = pd.to_datetime(d.get("accepted_at"), errors="coerce", utc=True)
        d["_filing_sort"] = pd.to_datetime(d.get("filing_date"), errors="coerce", utc=True)
        d = d.sort_values(
            ["_accepted_sort", "_filing_sort", "cik10", "accession_number"],
            ascending=[False, False, True, False],
        )
        d = d.head(int(max_filings)).copy()
        d = d.drop(columns=[c for c in ["_accepted_sort", "_filing_sort"] if c in d.columns])

    rows: list[dict[str, Any]] = []
    receipts = []
    for _, item in d.iterrows():
        filing = item.to_dict()
        try:
            filing["amendment_type"] = cache_13f_amendment_type(
                filing,
                raw_dir,
                user_agent=user_agent,
                refresh=refresh,
                sleep_s=sleep_s,
            )
            _, xml_text = cache_13f_document(
                filing,
                raw_dir,
                user_agent=user_agent,
                refresh=refresh,
                sleep_s=sleep_s,
            )
            checkpoint = raw_dir / "parsed" / "13f" / (cache_name(str(filing["accession_number"]), str(filing.get("primary_document") or "information_table.xml")) + ".json")
            input_identity = {"raw_sha256": hashlib.sha256(xml_text.encode()).hexdigest(), "filing": filing,
                "cusip_map_sha256": content_hash(cusip_map or {}), "schema_version": "sec-13f-parser-checkpoint-v2",
                "mapping_policy": "EXPLICIT_CUSIP_ONLY" if exact_cusip_only else "LEGACY_EMBEDDED_OR_MAP",
                "parser_code_sha256": file_hash(Path(__file__))}
            cached = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
            if cached is not None and cached.get("input_identity") == input_identity:
                if cached.get("rows_sha256") != content_hash(cached.get("rows")):
                    raise ValueError("13F_PARSER_CHECKPOINT_HASH_CONFLICT")
                parsed = cached["rows"]
            else:
                parsed = parse_13f_xml(xml_text, filing, cusip_map=cusip_map, exact_cusip_only=exact_cusip_only)
                atomic_json(checkpoint, {"input_identity": input_identity, "rows": parsed, "rows_sha256": content_hash(parsed)})
            rows.extend(parsed)
            receipts.append({"manager_cik": cik10(filing.get("cik10")), "report_period": filing.get("period_of_report"),
                "accession": filing.get("accession_number"), "accepted_at": filing.get("accepted_at"),
                "amendment_type": filing["amendment_type"] or "ORIGINAL", "status": "PARSED" if parsed else "PARSED_EMPTY",
                "row_count": len(parsed), "mapped_rows": sum(bool(r["ticker_mapped"]) for r in parsed),
                "raw_sha256": hashlib.sha256(xml_text.encode()).hexdigest(),
                "mapping_policy": input_identity["mapping_policy"]})
        except Exception as exc:
            receipts.append({"manager_cik": cik10(filing.get("cik10")), "report_period": filing.get("period_of_report"),
                "accession": filing.get("accession_number"), "accepted_at": filing.get("accepted_at"),
                "status": "PARSE_FAILED", "error_type": type(exc).__name__, "row_count": None, "mapped_rows": None})
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
                    "form_type": str(filing.get("form_type") or "").upper().strip(),
                    "amendment_type": str(filing.get("amendment_type") or "").upper().strip(),
                    "filing_url": str(filing.get("filing_url") or ""),
                    "issuer_name": f"PARSE_ERROR: {str(exc)[:180]}",
                }
            )
    out = pd.DataFrame(rows)
    for col in FORM13F_COLUMNS:
        if col not in out.columns:
            out[col] = None if col in FORM13F_NUMERIC_COLUMNS else ""
    out["manager_cik"] = out["manager_cik"].map(cik10)
    result = out[FORM13F_COLUMNS].copy()
    result.attrs["filing_receipts"] = receipts
    return result


def write_outputs(frame: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    receipts = frame.attrs.get("filing_receipts", [])
    frame = frame.copy()
    for col in FORM13F_COLUMNS:
        if col not in frame.columns:
            frame[col] = None if col in FORM13F_NUMERIC_COLUMNS else ""
    for col in FORM13F_NUMERIC_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    for col in [c for c in FORM13F_COLUMNS if c not in FORM13F_NUMERIC_COLUMNS]:
        frame[col] = frame[col].fillna("").astype(str)
    frame = frame[FORM13F_COLUMNS].copy()
    parquet_path = output_dir / "institutional_13f_holdings.parquet"
    csv_path = output_dir / "institutional_13f_holdings.csv"
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False)
    summary = {
        "schema_version": "sec-13f-parser-receipt-v2", "generated_at": utc_now(),
        "source_parse_status": "PARSED" if receipts and all(r["status"] in {"PARSED", "PARSED_EMPTY"} for r in receipts) else "PARTIAL_OR_UNCHECKED",
        "filing_receipts": receipts,
        "row_count": int(len(frame)),
        "manager_count": int(frame["manager_cik"].nunique()) if "manager_cik" in frame else 0,
        "mapped_ticker_count": int(frame["ticker_mapped"].replace("", pd.NA).nunique(dropna=True))
        if "ticker_mapped" in frame
        else 0,
        "parquet": str(parquet_path),
        "csv": str(csv_path),
        "output_sha256": {"parquet": file_hash(parquet_path), "csv": file_hash(csv_path)},
    }
    summary_path = output_dir / "institutional_13f_holdings_summary.json"
    atomic_json(summary_path, summary)
    return {"parquet": str(parquet_path), "csv": str(csv_path), "summary": str(summary_path)}


# Offline validation used by the standalone disclosure path. These are bounded
# supplied bytes, never Source/Reader/canonical or economic admission.
DISCLOSURE_FILE_LIMIT = 16 * 1024 * 1024
DISCLOSURE_BUNDLE_LIMIT = 64 * 1024 * 1024


def disclosure_need(ok, reason):
    if not ok:
        raise ValueError(reason)


def disclosure_json(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            disclosure_need(key not in out, "13F_DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    result = json.loads(raw, object_pairs_hook=unique,
                        parse_constant=lambda _: disclosure_need(False, "13F_NONFINITE_JSON"))
    disclosure_need(type(result) is dict, "13F_JSON_OBJECT_REQUIRED")
    return result


def disclosure_read(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        disclosure_need(not part.is_symlink() and
                        not getattr(part, "is_junction", lambda: False)(),
                        "13F_SOURCE_PATH_ALIAS")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        disclosure_need(stat.S_ISREG(before.st_mode) and before.st_size <= DISCLOSURE_FILE_LIMIT,
                        "13F_SOURCE_FILE_BUDGET_OR_TYPE")
        raw = stream.read(DISCLOSURE_FILE_LIMIT + 1)
        after = os.fstat(stream.fileno())
    disclosure_need(len(raw) <= DISCLOSURE_FILE_LIMIT and
                    (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                    "13F_SOURCE_CHANGED_OR_OVERSIZE")
    return raw


def disclosure_records(value):
    records = value.to_dict("records") if isinstance(value, pd.DataFrame) else value
    result = []
    for row in records:
        item = {}
        disclosure_need(all(c in row for c in FORM13F_COLUMNS), "13F_HOLDINGS_COLUMNS")
        for col in FORM13F_COLUMNS:
            v = row[col]
            missing = v is None or (not isinstance(v, (dict, list)) and pd.isna(v))
            if col in FORM13F_NUMERIC_COLUMNS:
                if missing or v == "":
                    item[col] = None
                else:
                    disclosure_need(not isinstance(v, bool), "13F_BOOLEAN_POSITION")
                    n = float(v)
                    disclosure_need(math.isfinite(n), "13F_NONFINITE_POSITION")
                    item[col] = n
            else:
                item[col] = "" if missing else str(v)
        result.append(item)
    return result


def _disclosure_table(raw, parquet=False, holdings=False):
    if parquet:
        import pyarrow.parquet as pq
        metadata = pq.ParquetFile(io.BytesIO(raw)).metadata
        disclosure_need(metadata.num_rows <= 100000 and
                        sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups)) <=
                        128 * 1024 * 1024,
                        "13F_TABLE_ROW_BUDGET")
        return pd.read_parquet(io.BytesIO(raw))
    frame = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, low_memory=False, nrows=100001)
    disclosure_need(len(frame) <= 100000, "13F_TABLE_ROW_BUDGET")
    return frame


def disclosure_scope(manager_ciks):
    disclosure_need(type(manager_ciks) is list and 0 < len(manager_ciks) <= 100 and
                    all(type(m) is str and re.fullmatch(r"[0-9]{10}", m) for m in manager_ciks) and
                    len(manager_ciks) == len(set(manager_ciks)), "13F_MANAGER_SCOPE")
    return sorted(manager_ciks)


def disclosure_amendment_cover(raw, filing):
    """Bind amendment interpretation to its filer, period and submission form."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("13F_MALFORMED_AMENDMENT_COVER") from error
    def values(name):
        return [(node.text or "").strip() for node in root.iter() if local_name(node.tag) == name]
    credentials = [n for n in root.iter() if local_name(n.tag) == "credentials"]
    filers = [cik10(n.text) for cred in credentials for n in cred.iter() if local_name(n.tag) == "cik"]
    periods = values("periodOfReport")
    disclosure_need(filers == [cik10(filing["cik10"])] and len(periods) == 1,
                    "13F_AMENDMENT_COVER_IDENTITY")
    try:
        period = date.fromisoformat(periods[0]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", periods[0]) else datetime.strptime(periods[0], "%m-%d-%Y").date()
    except ValueError as error:
        raise ValueError("13F_AMENDMENT_COVER_PERIOD") from error
    disclosure_need(period.isoformat() == filing["period_of_report"] and
                    values("submissionType") == ["13F-HR/A"] and
                    values("isAmendment") in (["true"], ["1"]), "13F_AMENDMENT_COVER_IDENTITY")
    try:
        kind = amendment_type_from_text(raw.decode("utf-8"))
    except RuntimeError as error:
        raise ValueError("13F_UNKNOWN_AMENDMENT_TYPE") from error
    disclosure_need(len(values("amendmentType")) == 1, "13F_AMENDMENT_COVER_TYPE")
    return kind


def load_disclosure_source_inputs(*, holdings, filings_index, raw_dir, cusip_map, manager_ciks):
    """Read only the named parser/index bundle and selected cached accessions."""
    manager_ciks = disclosure_scope(manager_ciks)
    hp, ip, rr, mp = map(Path, (holdings, filings_index, raw_dir, cusip_map))
    paths = {
        "holdings.csv": hp.parent / "institutional_13f_holdings.csv",
        "holdings.parquet": hp.parent / "institutional_13f_holdings.parquet",
        "parser_summary.json": hp.parent / "institutional_13f_holdings_summary.json",
        "index.csv": ip.parent / "sec_filings_index.csv",
        "index.parquet": ip.parent / "sec_filings_index.parquet",
        "source_summary.json": ip.parent / "sec_filings_index_summary.json",
        "cusip_map" + (".parquet" if mp.suffix.lower() == ".parquet" else ".csv"): mp,
    }
    # The filenames, not a caller-provided table, identify the paired generation.
    disclosure_need(hp.name in {"institutional_13f_holdings.csv", "institutional_13f_holdings.parquet"} and
                    ip.name in {"sec_filings_index.csv", "sec_filings_index.parquet"},
                    "13F_INPUT_PAIR_NAME")
    inputs = {role: disclosure_read(path) for role, path in paths.items()}
    index = _disclosure_table(inputs["index.csv"])
    disclosure_need("cik10" in index and "form_type" in index, "13F_INDEX_COLUMNS")
    selected = index[index["cik10"].map(cik10).isin(manager_ciks) &
                     index["form_type"].isin(FORM_13F_TYPES)]
    for manager in manager_ciks:
        paths["submissions/CIK" + manager + ".json"] = rr / "submissions" / ("CIK" + manager + ".json")
    for filing in selected.to_dict("records"):
        disclosure_need(re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", filing["accession_number"]) is not None and
                        bool(re.fullmatch(r"[A-Za-z0-9_./-]+", filing["primary_document"])) and
                        not filing["primary_document"].startswith("/") and
                        ".." not in filing["primary_document"].split("/"), "13F_SOURCE_PATH_IDENTITY")
        name = cache_name(filing["accession_number"], filing.get("primary_document") or "information_table.xml")
        paths["filings/13f/" + name] = rr / "filings/13f" / name
        paths["checkpoints/" + name + ".json"] = rr / "parsed/13f" / (name + ".json")
        if filing["form_type"] == "13F-HR/A":
            paths["filings/13f_cover/" + name] = rr / "filings/13f_cover" / name
    disclosure_need(len(paths) <= 1600, "13F_SOURCE_FILE_COUNT")
    for role, path in paths.items():
        if role not in inputs:
            inputs[role] = disclosure_read(path)
            disclosure_need(sum(map(len, inputs.values())) <= DISCLOSURE_BUNDLE_LIMIT, "13F_SOURCE_BUNDLE_BUDGET")
    disclosure_need(sum(map(len, inputs.values())) <= DISCLOSURE_BUNDLE_LIMIT, "13F_SOURCE_BUNDLE_BUDGET")
    return inputs


def verify_disclosure_source_inputs(inputs, *, manager_ciks, decision_at):
    """Recompute parser semantics and selected-manager freshness from bytes.

    No network, checkpoint writes, guessed mapping, or caller completeness flag.
    The returned flags certify this bounded disclosure derivation only.
    """
    managers = disclosure_scope(manager_ciks)
    disclosure_need(type(inputs) is dict and len(inputs) <= 1600 and
                    all(type(v) is bytes and len(v) <= DISCLOSURE_FILE_LIMIT for v in inputs.values()) and
                    sum(map(len, inputs.values())) <= DISCLOSURE_BUNDLE_LIMIT, "13F_SOURCE_BUNDLE_BUDGET")
    decision = exact_utc(decision_at)
    source = disclosure_json(inputs["source_summary.json"])
    summary = disclosure_json(inputs["parser_summary.json"])
    disclosure_need(source.get("schema_version") == "sec-submissions-source-check-v2" and
                    summary.get("schema_version") == "sec-13f-parser-receipt-v2",
                    "13F_SOURCE_SCHEMA")
    all_checks = source.get("source_checks", [])
    disclosure_need(type(all_checks) is list and all(type(c) is dict for c in all_checks) and
                    type(source.get("collection")) is dict and
                    source.get("collection", {}).get("source_checks") == all_checks,
                    "13F_SOURCE_RECEIPT_CONFLICT")
    good_checks = [c for c in all_checks if str(c.get("status", "")).startswith("CHECKED_")]
    expected_coverage = dict(requested=len(all_checks), checked=len(good_checks),
        checked_ciks=len({c.get("cik10") for c in good_checks}),
        complete=bool(all_checks) and len(good_checks) == len(all_checks))
    disclosure_need(json.dumps(source.get("source_coverage"), sort_keys=True) ==
                    json.dumps(expected_coverage, sort_keys=True), "13F_SOURCE_COVERAGE_BINDING")
    expected_status = "CHECKED" if expected_coverage["complete"] else "SOURCE_CHECK_INCOMPLETE"
    expected_last = min((c["checked_at"] for c in good_checks), default=None) if expected_coverage["complete"] else None
    disclosure_need(source.get("status") == expected_status and
                    source.get("last_successful_source_check") == expected_last,
                    "13F_SOURCE_CURRENT_STATE_BINDING")
    for prefix, receipt in (("index", source), ("holdings", summary)):
        for kind in ("csv", "parquet"):
            disclosure_need(hashlib.sha256(inputs[prefix + "." + kind]).hexdigest() ==
                            receipt["output_sha256"][kind], "13F_SOURCE_FORMAT_HASH")
    index = _disclosure_table(inputs["index.csv"])
    other_index = _disclosure_table(inputs["index.parquet"], True).fillna("").astype(str)
    disclosure_need(list(index.columns) == list(other_index.columns) and
                    index.to_dict("records") == other_index.to_dict("records") and
                    type(source.get("row_count")) is int and len(index) == source["row_count"],
                    "13F_INDEX_PARITY")
    rows = disclosure_records(_disclosure_table(inputs["holdings.csv"]))
    other_rows = disclosure_records(_disclosure_table(inputs["holdings.parquet"], True))
    disclosure_need(rows == other_rows and type(summary.get("row_count")) is int and
                    len(rows) == summary["row_count"], "13F_HOLDINGS_PARITY")
    mapping_keys = [k for k in inputs if k in {"cusip_map.csv", "cusip_map.parquet"}]
    disclosure_need(len(mapping_keys) == 1, "13F_EXACT_MAP_REQUIRED")
    mk = mapping_keys[0]
    mapping = cusip_map_from_frame(_disclosure_table(inputs[mk], mk.endswith(".parquet")))
    generated = exact_utc(source["generated_at"])
    parser_generated = exact_utc(summary["generated_at"])
    disclosure_need(generated <= decision and parser_generated <= decision, "13F_GENERATION_CLOCK")
    checks, checked_times, submitted = {}, [], {}
    for manager in managers:
        selected_checks = [c for c in source.get("source_checks", []) if c.get("cik10") == manager]
        disclosure_need(bool(selected_checks), "13F_MANAGER_NOT_CHECKED")
        values = [{k: c.get(k) for k in ("status", "checked_at", "payload_sha256")} for c in selected_checks]
        disclosure_need(all(v == values[0] for v in values), "13F_MANAGER_CHECK_CONFLICT")
        check = values[0]
        status = check["status"]
        disclosure_need(status in {"CHECKED_NEW_FILINGS", "CHECKED_NO_NEW_FILINGS"},
                        "SOURCE_UNAVAILABLE" if status == "SOURCE_UNAVAILABLE" else "13F_CACHED_OR_UNCHECKED")
        disclosure_need(all(type(c.get("new_accession_count")) is int and
            (c["new_accession_count"] > 0 if status == "CHECKED_NEW_FILINGS" else c["new_accession_count"] == 0)
            for c in selected_checks), "13F_SOURCE_NEW_COUNT")
        checked = exact_utc(check["checked_at"])
        disclosure_need(checked <= generated <= decision, "13F_SOURCE_CHECK_CLOCK")
        disclosure_need(decision - checked < timedelta(hours=36), "STALE")
        payload = disclosure_json(inputs["submissions/CIK" + manager + ".json"])
        validate_submissions(payload, manager)
        disclosure_need(content_hash(payload) == check["payload_sha256"], "13F_SUBMISSIONS_HASH")
        submitted[manager] = filings_from_submissions(
            "", manager, payload, forms=FORM_13F_TYPES, safety_delay_hours=0).to_dict("records")
        checks[manager] = check
        checked_times.append(checked)
    selected = index[index["cik10"].map(cik10).isin(managers) &
                     index["form_type"].isin(FORM_13F_TYPES)].to_dict("records")
    disclosure_need(len(selected) <= 500, "13F_FILING_BUDGET")
    identities, original_filings = {}, {}
    for filing in selected:
        accession, manager = filing["accession_number"], cik10(filing["cik10"])
        disclosure_need(re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) is not None and
                        accession not in identities, "13F_ACCESSION_CONFLICT")
        primary = filing["primary_document"]
        disclosure_need(bool(re.fullmatch(r"[A-Za-z0-9_./-]+", primary)) and
                        not primary.startswith("/") and ".." not in primary.split("/"),
                        "13F_PRIMARY_DOCUMENT_PATH")
        period = date.fromisoformat(filing["period_of_report"])
        disclosure_need(period.month in {3, 6, 9, 12} and
                        (period + timedelta(days=1)).day == 1, "13F_REPORT_PERIOD")
        accepted, available = exact_utc(filing["accepted_at"]), exact_utc(filing["available_from"])
        disclosure_need(accepted <= available <= decision and accepted <= exact_utc(checks[manager]["checked_at"]),
                        "13F_FILING_CLOCK")
        witnesses = [r for r in submitted[manager] if r["accession_number"] == accession]
        disclosure_need(len(witnesses) == 1, "13F_RECENT_SUBMISSION_BINDING_REQUIRED")
        witness = witnesses[0]
        for key in ("form_type", "filing_date", "period_of_report", "primary_document", "filing_url"):
            disclosure_need(filing[key] == witness[key], "13F_SUBMISSION_IDENTITY")
        disclosure_need(accepted == exact_utc(witness["accepted_at"]), "13F_SUBMISSION_ACCEPTED_CLOCK")
        identities[accession] = filing
        if filing["form_type"] == "13F-HR":
            key = (manager, filing["period_of_report"])
            disclosure_need(key not in original_filings, "13F_AMBIGUOUS_ORIGINAL")
            original_filings[key] = accession
    for manager in managers:
        eligible = [r for r in submitted[manager] if exact_utc(r["accepted_at"]) <= decision]
        if eligible:
            manager_accessions = {a for a, f in identities.items() if cik10(f["cik10"]) == manager}
            latest = max(eligible, key=lambda r: (exact_utc(r["accepted_at"]), r["accession_number"]))
            disclosure_need(latest["accession_number"] in manager_accessions, "13F_LATEST_FILING_NOT_INDEXED")
            # A paired index/parser omission can pass parity and the committed
            # prefix on its first run. Bind the entire observed comparison
            # interval, including revisions between the selected reports.
            lower = min(exact_utc(f["accepted_at"]) for f in identities.values()
                        if cik10(f["cik10"]) == manager)
            disclosure_need(all(r["accession_number"] in manager_accessions for r in eligible
                                if exact_utc(r["accepted_at"]) >= lower),
                            "13F_OBSERVED_COMPARISON_TIMELINE_GAP")
    disclosure_need(type(summary.get("filing_receipts")) is list and
                    all(type(r) is dict for r in summary["filing_receipts"]), "13F_PARSER_RECEIPT_SHAPE")
    parser_receipts = {}
    for r in summary.get("filing_receipts", []):
        if str(r.get("manager_cik")) not in managers:
            continue
        accession = r.get("accession")
        disclosure_need(accession not in parser_receipts, "13F_DUPLICATE_PARSER_RECEIPT")
        parser_receipts[accession] = r
    disclosure_need(set(parser_receipts) == set(identities), "13F_PARSE_SCOPE")
    scoped_rows = [r for r in rows if r["manager_cik"] in managers]
    disclosure_need(all(r["source_accession"] in identities for r in scoped_rows), "13F_ROW_SCOPE")
    validated, full_rows = {}, []
    for accession, filing in sorted(identities.items(), key=lambda kv: (exact_utc(kv[1]["accepted_at"]), kv[0])):
        name = cache_name(accession, filing.get("primary_document") or "information_table.xml")
        role = "filings/13f/" + name
        physical = inputs[role]
        # Match TextIOWrapper universal-newline decoding used by the old parser.
        text = physical.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        physical_hash = hashlib.sha256(physical).hexdigest()
        cover = inputs["filings/13f_cover/" + name] if filing["form_type"] == "13F-HR/A" else None
        amendment = disclosure_amendment_cover(cover, filing) if cover is not None else "ORIGINAL"
        original = original_filings.get((cik10(filing["cik10"]), filing["period_of_report"]))
        if filing["form_type"] == "13F-HR/A":
            disclosure_need(original is not None and
                            exact_utc(identities[original]["accepted_at"]) < exact_utc(filing["accepted_at"]),
                            "13F_AMENDMENT_LINEAGE")
        current_filing = {**filing, "amendment_type": amendment}
        try:
            parsed = disclosure_records(parse_13f_xml(text, current_filing, cusip_map=mapping, exact_cusip_only=True))
        except ET.ParseError as error:
            raise ValueError("13F_MALFORMED_ORIGINAL_XML") from error
        observed = [r for r in scoped_rows if r["source_accession"] == accession]
        disclosure_need(parsed == observed, "13F_RAW_PARSE_SEMANTICS")
        receipt = parser_receipts[accession]
        expected_status = "PARSED" if parsed else "PARSED_EMPTY"
        disclosure_need(receipt.get("status") == expected_status and
                        receipt.get("mapping_policy") == "EXPLICIT_CUSIP_ONLY" and
                        receipt.get("raw_sha256") == text_hash and
                        type(receipt.get("row_count")) is int and receipt["row_count"] == len(parsed) and
                        type(receipt.get("mapped_rows")) is int and
                        receipt["mapped_rows"] == sum(bool(r["ticker_mapped"]) for r in parsed),
                        "13F_PARSER_RECEIPT_BINDING")
        for key, expected in (("manager_cik", cik10(filing["cik10"])),
                              ("report_period", filing["period_of_report"]), ("amendment_type", amendment)):
            disclosure_need(receipt.get(key) == expected, "13F_PARSER_RECEIPT_IDENTITY")
        disclosure_need(exact_utc(receipt["accepted_at"]) == exact_utc(filing["accepted_at"]),
                        "13F_PARSER_RECEIPT_CLOCK")
        checkpoint = disclosure_json(inputs["checkpoints/" + name + ".json"])
        ci = checkpoint["input_identity"]
        disclosure_need(ci.get("schema_version") == "sec-13f-parser-checkpoint-v2" and
                        ci.get("mapping_policy") == "EXPLICIT_CUSIP_ONLY" and
                        ci.get("raw_sha256") == text_hash and
                        ci.get("cusip_map_sha256") == content_hash(mapping) and
                        checkpoint.get("rows_sha256") == content_hash(checkpoint["rows"]) and
                        disclosure_records(checkpoint["rows"]) == parsed,
                        "13F_CHECKPOINT_BINDING")
        for key in ("cik10", "accession_number", "form_type", "period_of_report", "primary_document", "amendment_type"):
            disclosure_need(ci["filing"].get(key) == current_filing.get(key), "13F_CHECKPOINT_IDENTITY")
        for key in ("accepted_at", "available_from"):
            disclosure_need(exact_utc(ci["filing"][key]) == exact_utc(filing[key]), "13F_CHECKPOINT_CLOCK")
        if not parsed:
            root = ET.fromstring(extract_information_table_xml(text))
            disclosure_need(local_name(root.tag).lower() == "informationtable" and not list(root),
                            "13F_UNVERIFIED_EMPTY_DOCUMENT")
        validated[accession] = dict(
            parsing_status=expected_status, document_sha256=physical_hash,
            parser_text_sha256=text_hash, raw_role=role,
            cover_document_sha256=hashlib.sha256(cover).hexdigest() if cover is not None else None,
            complete=True, mapping_complete=all(bool(r["ticker_mapped"]) for r in parsed),
            original_accession=original if amendment != "ORIGINAL" else None,
            manager_cik=cik10(filing["cik10"]), report_period=filing["period_of_report"],
            form_type=filing["form_type"], accepted_at=filing["accepted_at"],
            available_from=filing["available_from"], amendment_type=amendment,
            row_count=len(parsed), checkpoint_parser_code_sha256=ci.get("parser_code_sha256"))
        full_rows.extend(parsed)
    return dict(holdings=pd.DataFrame(full_rows, columns=FORM13F_COLUMNS), filing_receipts=validated,
                manager_scope=managers, source_checks=checks,
                last_successful_source_check=min(checked_times).isoformat(),
                latest_accepted_at=max((exact_utc(r["accepted_at"]) for r in selected), default=None),
                source_status=("CHECKED_NO_NEW_FILINGS" if all(c["status"] == "CHECKED_NO_NEW_FILINGS" for c in checks.values())
                               else "CHECKED_NEW_FILINGS"),
                source_coverage=dict(requested_managers=len(managers), checked_managers=len(checks),
                                     indexed_filings=len(selected), parsed_rows=len(full_rows),
                                     mapped_rows=sum(bool(r["ticker_mapped"]) for r in full_rows)),
                current_source_eligible=True, aggregate_analysis_admitted=False,
                due_quarter_coverage="NOT_EVALUATED_SEPARATE_EXISTING_FRESHNESS_GATE")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings-index", default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--cusip-map", default="")
    parser.add_argument("--exact-cusip-only", action="store_true",
                        help="Map only explicit CUSIPs; refuse conflicting embedded tickers and leave unknown CUSIPs unmapped.")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--max-filings", type=int, default=0)
    parser.add_argument("--as-of", default="", help="Only parse filings whose available_from is at or before this timestamp.")
    parser.add_argument("--write-restore-list", default="")
    parser.add_argument("--write-submissions-filter", default="")
    parser.add_argument("--manager-ciks-file", default="")
    args = parser.parse_args()
    if args.write_submissions_filter:
        ciks = set()
        for token in repo_path(args.manager_ciks_file).read_text().strip().split(","):
            norm = cik10(token.rsplit(":", 1)[-1])
            if not norm:
                raise ValueError("13F_RESTORE_MANAGER_CIK")
            ciks.add(norm)
        rules = ["+ /company_tickers.json", "+ /submissions/"] + ["+ /submissions/CIK" + cik + "*.json" for cik in sorted(ciks)] + ["- **"]
        target = repo_path(args.write_submissions_filter)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(rules) + "\n")
        return 0
    if args.write_restore_list:
        paths = selected_restore_paths(read_filings_index(repo_path(args.filings_index)), as_of=args.as_of, max_filings=args.max_filings)
        target = repo_path(args.write_restore_list)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(paths) + "\n")
        return 0

    cusip_map = read_cusip_map(repo_path(args.cusip_map)) if args.cusip_map else {}
    frame = parse_13f_index(
        read_filings_index(repo_path(args.filings_index)),
        raw_dir=repo_path(args.raw_dir),
        user_agent=args.user_agent,
        refresh=bool(args.refresh),
        sleep_s=float(args.sleep),
        max_filings=int(args.max_filings),
        cusip_map=cusip_map,
        exact_cusip_only=bool(args.exact_cusip_only),
        as_of=str(args.as_of or ""),
    )
    paths = write_outputs(frame, repo_path(args.output_dir))
    print(json.dumps({"status": "ok", "rows": int(len(frame)), **paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
