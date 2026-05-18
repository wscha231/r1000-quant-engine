#!/usr/bin/env python3
"""Parse SEC Form 4 XML filings into PIT insider transaction parquet."""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_edgar_common import (
    DEFAULT_SEC_USER_AGENT,
    archive_document_url,
    normalize_cik10,
    read_table,
    sec_get_text,
    write_json,
    write_table,
)

DEFAULT_FILINGS_INDEX = "data_pit/sec/sec_filings_index.parquet"
DEFAULT_DATA_RAW = "data_raw/sec"
DEFAULT_OUTPUT = "data_pit/sec/form4_transactions.parquet"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def text_at(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def float_at(node: ET.Element | None, path: str) -> float | None:
    value = text_at(node, path)
    if value == "":
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def bool_text(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def parse_form4_xml(xml_text: str, accession_number: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    issuer_ticker = text_at(root, ".//issuer/issuerTradingSymbol").upper()
    issuer_cik10 = normalize_cik10(text_at(root, ".//issuer/issuerCik"))
    owner = root.find(".//reportingOwner")
    owner_name = text_at(owner, ".//reportingOwnerId/rptOwnerName")
    owner_cik = normalize_cik10(text_at(owner, ".//reportingOwnerId/rptOwnerCik"))
    relationship = owner.find(".//reportingOwnerRelationship") if owner is not None else None
    is_director = bool_text(text_at(relationship, "isDirector"))
    is_officer = bool_text(text_at(relationship, "isOfficer"))
    is_ten_percent = bool_text(text_at(relationship, "isTenPercentOwner"))
    officer_title = text_at(relationship, "officerTitle")

    rows: list[dict[str, Any]] = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        shares = float_at(tx, ".//transactionAmounts/transactionShares/value") or 0.0
        price = float_at(tx, ".//transactionAmounts/transactionPricePerShare/value") or 0.0
        owned_after = float_at(tx, ".//postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        code = text_at(tx, ".//transactionCoding/transactionCode").upper()
        rows.append(
            {
                "issuer_ticker": issuer_ticker,
                "issuer_cik10": issuer_cik10,
                "reporting_owner_cik": owner_cik,
                "reporting_owner_name": owner_name,
                "officer_title": officer_title,
                "is_director": is_director,
                "is_officer": is_officer,
                "is_ten_percent_owner": is_ten_percent,
                "transaction_date": text_at(tx, ".//transactionDate/value"),
                "transaction_code": code,
                "transaction_shares": shares,
                "transaction_price": price,
                "transaction_value": shares * price,
                "ownership_nature": text_at(tx, ".//ownershipNature/directOrIndirectOwnership/value"),
                "direct_or_indirect": text_at(tx, ".//ownershipNature/directOrIndirectOwnership/value"),
                "shares_owned_after": owned_after,
                "is_derivative": False,
                "security_title": text_at(tx, ".//securityTitle/value"),
                "accession_number": accession_number,
            }
        )
    return rows


def parse_number(text: Any) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", str(text or ""))
    if cleaned in {"", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_form4_html(html_text: str, accession_number: str) -> list[dict[str, Any]]:
    """Parse SEC's rendered HTML Form 4 when the primary document is not XML."""
    soup = BeautifulSoup(html_text, "html.parser")
    full_text = soup.get_text(" ", strip=True)
    tickers = re.findall(r"\[\s*([A-Z][A-Z0-9.\-]{0,12})\s*\]", full_text)
    issuer_ticker = tickers[-1].upper() if tickers else ""
    ciks = re.findall(r"CIK=([0-9]{1,10})", html_text, flags=re.IGNORECASE)
    issuer_cik10 = normalize_cik10(ciks[1] if len(ciks) > 1 else (ciks[0] if ciks else ""))
    owner_cik = normalize_cik10(ciks[0] if ciks else "")
    owner_name = ""
    first_company_link = soup.find("a", href=re.compile("browse-edgar.*CIK=", re.I))
    if first_company_link is not None:
        owner_name = first_company_link.get_text(" ", strip=True)
    is_director = "Director" in full_text
    is_officer = "Officer" in full_text
    is_ten_percent = "10% Owner" in full_text

    rows: list[dict[str, Any]] = []
    tables = soup.find_all("table")
    table_i = None
    for table in tables:
        text = table.get_text(" ", strip=True)
        if "Table I" in text and "Non-Derivative" in text:
            table_i = table
            break
    if table_i is None:
        return rows
    for tr in table_i.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 10:
            continue
        code = cells[3].upper().strip()
        if not re.fullmatch(r"[A-Z]", code or ""):
            continue
        shares = parse_number(cells[5]) or 0.0
        price = parse_number(cells[7]) or 0.0
        rows.append(
            {
                "issuer_ticker": issuer_ticker,
                "issuer_cik10": issuer_cik10,
                "reporting_owner_cik": owner_cik,
                "reporting_owner_name": owner_name,
                "officer_title": "",
                "is_director": is_director,
                "is_officer": is_officer,
                "is_ten_percent_owner": is_ten_percent,
                "transaction_date": cells[1],
                "transaction_code": code,
                "transaction_shares": shares,
                "transaction_price": price,
                "transaction_value": shares * price,
                "ownership_nature": cells[9],
                "direct_or_indirect": cells[9],
                "shares_owned_after": parse_number(cells[8]),
                "is_derivative": False,
                "security_title": cells[0],
                "accession_number": accession_number,
            }
        )
    return rows


def parse_form4_document(document_text: str, accession_number: str) -> list[dict[str, Any]]:
    try:
        return parse_form4_xml(document_text, accession_number)
    except ET.ParseError:
        if "<html" in document_text[:500].lower() or "<!doctype html" in document_text[:500].lower():
            return parse_form4_html(document_text, accession_number)
        raise


def local_doc_path(raw_root: Path, cik10: str, accession_number: str, primary_document: str) -> Path:
    clean_doc = primary_document.replace("/", "_")
    return raw_root / "filings" / "form4" / f"{normalize_cik10(cik10)}_{accession_number.replace('-', '')}_{clean_doc}"


def run(args: argparse.Namespace) -> dict[str, Any]:
    filings_index = read_table(repo_path(args.filings_index))
    raw_root = repo_path(args.raw_root)
    output = repo_path(args.output)
    user_agent = args.sec_user_agent or DEFAULT_SEC_USER_AGENT
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not filings_index.empty:
        d = filings_index.copy()
        d["form_type"] = d["form_type"].astype(str).str.upper().str.strip()
        d = d[d["form_type"].isin({"4", "4/A"})].copy()
        if args.limit:
            d = d.head(int(args.limit)).copy()
        for filing in d.to_dict("records"):
            cik10 = normalize_cik10(filing.get("cik10"))
            accession = str(filing.get("accession_number") or "")
            primary = str(filing.get("primary_document") or "")
            if not cik10 or not accession or not primary:
                failures.append({"accession_number": accession, "reason": "missing_doc_metadata"})
                continue
            path = local_doc_path(raw_root, cik10, accession, primary)
            try:
                if path.exists():
                    xml_text = path.read_text(encoding="utf-8", errors="replace")
                else:
                    if args.no_download:
                        failures.append({"accession_number": accession, "reason": "missing_local_doc"})
                        continue
                    url = str(filing.get("filing_url") or "") or archive_document_url(cik10, accession, primary)
                    xml_text = sec_get_text(url, user_agent=user_agent, throttle_seconds=args.throttle_seconds)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(xml_text, encoding="utf-8")
                parsed = parse_form4_document(xml_text, accession)
                for row in parsed:
                    row.update(
                        {
                            "filing_date": filing.get("filing_date", ""),
                            "accepted_at": filing.get("accepted_at", ""),
                            "available_from": filing.get("available_from", ""),
                            "period_of_report": filing.get("period_of_report", ""),
                            "primary_document": primary,
                            "filing_url": filing.get("filing_url", ""),
                        }
                    )
                rows.extend(parsed)
            except Exception as exc:
                failures.append({"accession_number": accession, "reason": type(exc).__name__, "message": str(exc)[:200]})
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(
            columns=[
                "issuer_ticker",
                "issuer_cik10",
                "reporting_owner_cik",
                "reporting_owner_name",
                "officer_title",
                "is_director",
                "is_officer",
                "is_ten_percent_owner",
                "transaction_date",
                "filing_date",
                "accepted_at",
                "available_from",
                "transaction_code",
                "transaction_shares",
                "transaction_price",
                "transaction_value",
                "ownership_nature",
                "direct_or_indirect",
                "shares_owned_after",
                "is_derivative",
                "security_title",
                "accession_number",
                "primary_document",
                "filing_url",
            ]
        )
    else:
        frame["issuer_cik10"] = frame["issuer_cik10"].map(normalize_cik10)
        frame["reporting_owner_cik"] = frame["reporting_owner_cik"].map(normalize_cik10)
        for col in ["transaction_shares", "transaction_price", "transaction_value", "shares_owned_after"]:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    write_table(frame, output)
    manifest = {
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transaction_rows": int(len(frame)),
        "failed_filings": failures[:200],
        "output": str(output),
    }
    write_json(output.with_suffix(".manifest.json"), manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings-index", default=DEFAULT_FILINGS_INDEX)
    parser.add_argument("--raw-root", default=DEFAULT_DATA_RAW)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--sec-user-agent", default=DEFAULT_SEC_USER_AGENT)
    parser.add_argument("--throttle-seconds", type=float, default=0.12)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-download", action="store_true", help="Parse only already downloaded local XML docs.")
    return parser.parse_args()


def main() -> int:
    import json

    print(json.dumps(run(parse_args()), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
