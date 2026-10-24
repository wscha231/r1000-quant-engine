#!/usr/bin/env python3
"""Parse SEC Form 4 XML documents into normalized PIT transactions."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
    sec_headers,
    atomic_json, content_hash, file_hash, utc_now,
)

DEFAULT_INDEX = "data_pit/sec/sec_filings_index.parquet"
DEFAULT_OUTPUT_DIR = "data_pit/sec"
DEFAULT_RAW_DIR = "data_raw/sec"


FORM4_COLUMNS = [
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
    "filing_url",
    "form_type", "row_kind", "transaction_id", "document_sha256",
    "reporting_owners_json", "reporting_owner_count", "footnotes_json", "footnote_ids_json",
    "raw_row_xml", "original_submission_date", "underlying_security_title",
    "underlying_security_shares", "conversion_or_exercise_price", "exercise_date", "expiration_date",
    "market_execution_verified", "parser_schema_version", "owner_attribution_status",
]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def first(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    for child in node.iter():
        if local_name(child.tag) == name:
            return child
    return None


def first_text(node: ET.Element | None, name: str, default: str = "") -> str:
    child = first(node, name)
    if child is None or child.text is None:
        return default
    return str(child.text).strip()


def first_value(node: ET.Element | None, name: str, default: str = "") -> str:
    child = first(node, name)
    if child is None:
        return default
    value = first_text(child, "value", default="")
    return value if value != "" else (str(child.text).strip() if child.text else default)


def nodes(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in root.iter() if local_name(node.tag) == name]


def as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        text = str(value).replace(",", "").strip()
        out = float(text)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def parse_owner(root: ET.Element) -> dict[str, Any]:
    owner = root if local_name(root.tag) == "reportingOwner" else first(root, "reportingOwner")
    rel = first(owner, "reportingOwnerRelationship") if owner is not None else None
    return {
        "reporting_owner_cik": cik10(first_text(owner, "rptOwnerCik")),
        "reporting_owner_name": first_text(owner, "rptOwnerName"),
        "officer_title": first_text(rel, "officerTitle"),
        "is_director": as_bool(first_text(rel, "isDirector")),
        "is_officer": as_bool(first_text(rel, "isOfficer")),
        "is_ten_percent_owner": as_bool(first_text(rel, "isTenPercentOwner")),
    }


def parse_form4_xml(xml_text: str, accession_number: str = "", filing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Preserve Form 3 holdings and Form 4/5 transactions, owners and raw notes.

    One table row remains one row: joint owners are retained as a JSON array so
    the same economic trade is not multiplied by its owner count. Code P alone
    establishes a purchase code, not an independently verified trading venue.
    """
    filing = filing or {}
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    issuer_ticker = first_text(root, "issuerTradingSymbol").upper()
    issuer_cik = cik10(first_text(root, "issuerCik"))
    expected_cik = cik10(filing.get("cik10"))
    if expected_cik and expected_cik != issuer_cik:
        raise ValueError("OWNERSHIP_ISSUER_CIK_CONFLICT")
    expected_ticker = str(filing.get("ticker") or "").upper().strip()
    if expected_ticker and expected_ticker != issuer_ticker:
        raise ValueError("OWNERSHIP_ISSUER_SYMBOL_CONFLICT")
    owner = parse_owner(root)
    owners = [parse_owner(node) for node in nodes(root, "reportingOwner")]
    owner_status = "UNAMBIGUOUS" if len(owners) == 1 else "AMBIGUOUS" if owners else "MISSING"
    if len(owners) != 1:
        owner = {key: (None if key.startswith("is_") else "") for key in owner}
    accession = accession_number or str(filing.get("accession_number") or "")
    form = first_text(root, "documentType") or str(filing.get("form_type") or "4")
    if form not in {"3", "3/A", "4", "4/A", "5", "5/A"}:
        raise ValueError("UNSUPPORTED_OWNERSHIP_FORM")
    if filing.get("form_type") and filing["form_type"] != form:
        raise ValueError("OWNERSHIP_FORM_CONFLICT")
    raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    document_hash = hashlib.sha256(raw).hexdigest()
    notes = {n.attrib.get("id", ""): " ".join(n.itertext()).strip() for n in nodes(root, "footnote")}

    rows: list[dict[str, Any]] = []
    entries = [(tag, ordinal, node) for tag in ("nonDerivativeTransaction", "derivativeTransaction", "nonDerivativeHolding", "derivativeHolding") for ordinal, node in enumerate(nodes(root, tag))]
    for tag, ordinal, tx in entries:
        shares = as_float(first_value(tx, "transactionShares"))
        price = as_float(first_value(tx, "transactionPricePerShare"))
        owned_after = as_float(first_value(tx, "sharesOwnedFollowingTransaction"))
        row = {
            "issuer_ticker": issuer_ticker,
            "issuer_cik10": issuer_cik,
            **owner,
            "transaction_date": first_value(tx, "transactionDate"),
            "filing_date": str(filing.get("filing_date") or ""),
            "accepted_at": str(filing.get("accepted_at") or ""),
            "available_from": str(filing.get("available_from") or filing.get("accepted_at") or ""),
            "transaction_code": first_text(tx, "transactionCode").upper(),
            "transaction_shares": shares,
            "transaction_price": price,
            "transaction_value": shares * price if tag == "nonDerivativeTransaction" and shares is not None and price is not None else None,
            "ownership_nature": first_text(tx, "natureOfOwnership"),
            "direct_or_indirect": first_value(tx, "directOrIndirectOwnership"),
            "shares_owned_after": owned_after,
            "is_derivative": tag.startswith("derivative"),
            "security_title": first_value(tx, "securityTitle"),
            "accession_number": accession,
            "filing_url": str(filing.get("filing_url") or ""),
            "form_type": form, "row_kind": "HOLDING" if tag.endswith("Holding") else "TRANSACTION",
            "transaction_id": f"{tag}:{ordinal}", "document_sha256": document_hash,
            "reporting_owners_json": json.dumps(owners, sort_keys=True, separators=(",", ":")),
            "reporting_owner_count": len(owners),
            "owner_attribution_status": owner_status,
            "footnotes_json": json.dumps(notes, sort_keys=True, separators=(",", ":")),
            "footnote_ids_json": json.dumps(sorted({n.attrib["id"] for n in tx.iter() if local_name(n.tag) == "footnoteId" and "id" in n.attrib})),
            "raw_row_xml": ET.tostring(tx, encoding="unicode"),
            "original_submission_date": first_text(root, "dateOfOriginalSubmission"),
            "underlying_security_title": first_value(tx, "underlyingSecurityTitle"),
            "underlying_security_shares": as_float(first_value(tx, "underlyingSecurityShares")),
            "conversion_or_exercise_price": as_float(first_value(tx, "conversionOrExercisePrice")),
            "exercise_date": first_value(tx, "exerciseDate"), "expiration_date": first_value(tx, "expirationDate"),
            "market_execution_verified": None, "parser_schema_version": "sec-ownership-345-v2",
        }
        rows.append(row)
    return rows


def read_filings_index(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def sec_get_text(url: str, *, user_agent: str | None = None, sleep_s: float = 0.12) -> str:
    if sleep_s > 0:
        time.sleep(float(sleep_s))
    headers = sec_headers(user_agent)
    if "www.sec.gov" in url:
        headers["Host"] = "www.sec.gov"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def raw_form4_primary_document(primary_doc: str) -> str:
    """Return the raw XML document name from SEC's XSL-rendered path.

    SEC submissions often report Form 4 primary documents as
    ``xslF345X06/doc.xml``. That URL returns an HTML-rendered page. The raw XML
    sits next to the accession directory as ``doc.xml``.
    """
    text = str(primary_doc or "").strip().replace("\\", "/")
    if "/" in text and text.lower().startswith("xslf345"):
        return text.rsplit("/", 1)[-1]
    return text


def cache_name(accession: str, primary_doc: str) -> str:
    raw_doc = raw_form4_primary_document(primary_doc)
    safe_doc = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_doc).strip("_") or "form4.xml"
    return f"{accession.replace('-', '')}_{safe_doc}"


def form4_url_candidates(cik: str, accession: str, primary_doc: str, filing_url: str = "") -> list[str]:
    raw_doc = raw_form4_primary_document(primary_doc)
    candidates: list[str] = []
    if raw_doc and raw_doc != str(primary_doc or "").strip():
        candidates.append(filing_archive_url(cik, accession, raw_doc))
    if filing_url:
        candidates.append(str(filing_url))
    if primary_doc:
        candidates.append(filing_archive_url(cik, accession, str(primary_doc)))
    if raw_doc:
        candidates.append(filing_archive_url(cik, accession, raw_doc))
    out: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url and url not in seen:
            out.append(url)
            seen.add(url)
    return out


def cache_form4_document(
    filing: dict[str, Any],
    raw_dir: Path,
    *,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
) -> tuple[Path | None, str]:
    cik = cik10(filing.get("cik10"))
    accession = str(filing.get("accession_number") or "").strip()
    primary_doc = str(filing.get("primary_document") or "").strip()
    if not cik or not accession or not primary_doc:
        return None, ""
    out_dir = raw_dir / "filings" / "form4"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / cache_name(accession, primary_doc)
    if refresh or not cache.exists():
        errors: list[str] = []
        text = ""
        for url in form4_url_candidates(cik, accession, primary_doc, str(filing.get("filing_url") or "")):
            try:
                candidate = sec_get_text(url, user_agent=user_agent, sleep_s=sleep_s)
                if "<ownershipDocument" in candidate or "<?xml" in candidate[:200]:
                    text = candidate
                    break
                errors.append(f"{url}: non-xml response")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        if not text:
            raise RuntimeError("; ".join(errors)[:500] or "no Form 4 document URL candidates")
        cache.write_bytes(text.encode("utf-8"))
    return cache, cache.read_bytes().decode("utf-8")


def parse_form4_index(
    index: pd.DataFrame,
    *,
    raw_dir: Path,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
    max_filings: int = 0,
    completed: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if index.empty:
        result = pd.DataFrame(columns=FORM4_COLUMNS)
        result.attrs["parse_receipt"] = {
            "schema_version": "sec-ownership-parser-receipt-v2",
            "completed": dict(completed or {}), "pending_before": 0,
            "selected_filings": 0, "backlog_filings": 0,
            "selected_issuer_count": 0, "parse_error_rows": 0,
        }
        return result
    d = index.copy()
    d["form_type"] = d.get("form_type", "").astype(str).str.upper().str.strip()
    d = d[d["form_type"].isin({"3", "3/A", "4", "4/A", "5", "5/A"})].copy()
    d["_key"] = d.apply(lambda r: ":".join([cik10(r.get("cik10")), str(r.get("accession_number", "")), str(r.get("form_type", ""))]), axis=1)
    d = d.drop_duplicates("_key", keep="last")
    # Same accession can have corrected SEC metadata on a later source check.
    # Reuse immutable XML, but never retain parsed rows carrying obsolete clocks.
    parser_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    identity_fields = ("cik10", "ticker", "accession_number", "form_type", "accepted_at", "available_from", "primary_document")
    identities = {str(r["_key"]): dict(parser_sha256=parser_sha,
        filing={k: str(r.get(k) or "") for k in identity_fields}) for r in d.to_dict("records")}
    done = {k: v for k, v in dict(completed or {}).items()
            if k in identities and v.get("source_identity") == identities[k]}
    d = d[~d["_key"].isin(done)]
    d["_accepted"] = pd.to_datetime(d["accepted_at"], utc=True, errors="coerce")
    d = d.sort_values(["_accepted", "_key"], ascending=[False, True], kind="stable")
    # One newest filing per issuer before a second filing from any issuer.
    d["_issuer_round"] = d.groupby("cik10").cumcount()
    d = d.sort_values(["_issuer_round", "_accepted", "_key"], ascending=[True, False, True], kind="stable")
    pending = len(d)
    if max_filings and max_filings > 0:
        d = d.head(int(max_filings)).copy()

    rows: list[dict[str, Any]] = []
    for _, item in d.iterrows():
        filing = item.to_dict()
        try:
            _, xml_text = cache_form4_document(
                filing,
                raw_dir,
                user_agent=user_agent,
                refresh=refresh,
                sleep_s=sleep_s,
            )
            if not xml_text:
                raise ValueError("OWNERSHIP_XML_UNAVAILABLE")
            parsed = parse_form4_xml(xml_text, str(filing.get("accession_number") or ""), filing)
            rows.extend(parsed)
            done[str(filing["_key"])] = {"status": "PARSED" if parsed else "PARSED_EMPTY", "row_count": len(parsed),
                "document_sha256": hashlib.sha256(xml_text.encode()).hexdigest(), "parsed_at": utc_now(),
                "source_identity": identities[str(filing["_key"])]}
        except Exception as exc:
            rows.append(
                {
                    **{col: "" for col in FORM4_COLUMNS},
                    "issuer_ticker": str(filing.get("ticker") or ""),
                    "issuer_cik10": cik10(filing.get("cik10")),
                    "filing_date": str(filing.get("filing_date") or ""),
                    "accepted_at": str(filing.get("accepted_at") or ""),
                    "available_from": str(filing.get("available_from") or ""),
                    "accession_number": str(filing.get("accession_number") or ""),
                    "filing_url": str(filing.get("filing_url") or ""),
                    "transaction_code": "PARSE_ERROR", "form_type": filing.get("form_type", ""),
                    "parser_schema_version": "sec-ownership-345-v2",
                    "ownership_nature": str(exc)[:240],
                    "transaction_shares": None, "transaction_price": None,
                    "transaction_value": None, "shares_owned_after": None,
                }
            )
    out = pd.DataFrame(rows, columns=FORM4_COLUMNS)
    for col in FORM4_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col not in {"transaction_shares", "transaction_price", "transaction_value", "shares_owned_after"} else None
    out["issuer_cik10"] = out["issuer_cik10"].map(cik10)
    out["reporting_owner_cik"] = out["reporting_owner_cik"].map(cik10)
    result = out[FORM4_COLUMNS].copy()
    result.attrs["parse_receipt"] = {"schema_version": "sec-ownership-parser-receipt-v2", "completed": done,
        "attempted_keys": d["_key"].tolist(),
        "pending_before": pending, "selected_filings": len(d), "backlog_filings": pending - len(d),
        "selected_issuer_count": int(d["cik10"].nunique()), "parse_error_rows": int(result["transaction_code"].eq("PARSE_ERROR").sum())}
    return result


def write_outputs(frame: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "form4_transactions.parquet"
    csv_path = output_dir / "form4_transactions.csv"
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False)
    summary = {
        **frame.attrs.get("parse_receipt", {}),
        "row_count": int(len(frame)),
        "issuer_count": int(frame["issuer_ticker"].nunique()) if "issuer_ticker" in frame else 0,
        "open_market_purchase_rows": int(frame["transaction_code"].astype(str).str.upper().eq("P").sum())
        if "transaction_code" in frame
        else 0,
        "parquet": str(parquet_path),
        "csv": str(csv_path),
        "output_sha256": {"parquet": file_hash(parquet_path), "csv": file_hash(csv_path)},
        "p_code_semantics": "PURCHASE_CODE_ONLY_MARKET_VENUE_UNVERIFIED",
    }
    summary_path = output_dir / "form4_transactions_summary.json"
    atomic_json(summary_path, summary)
    return {"parquet": str(parquet_path), "csv": str(csv_path), "summary": str(summary_path)}


def replace_reparsed_rows(prior: pd.DataFrame, current: pd.DataFrame, receipt: dict) -> pd.DataFrame:
    """A reparse replaces an accession, even when it now has fewer/zero rows."""
    if not prior.empty:
        prior = prior[~prior["transaction_code"].eq("PARSE_ERROR")]
        attempted = set(receipt.get("attempted_keys", []))
        keys = prior.apply(lambda r: ":".join([cik10(r.get("issuer_cik10")),
            str(r.get("accession_number", "")), str(r.get("form_type", ""))]), axis=1)
        prior = prior[~keys.isin(attempted)]
        current = pd.concat([prior, current], ignore_index=True)
        current = current.drop_duplicates(["accession_number", "issuer_cik10", "form_type", "transaction_id"], keep="last")
    current.attrs["parse_receipt"] = receipt
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings-index", default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--max-filings", type=int, default=0)
    parser.add_argument("--resume-existing", action="store_true")
    args = parser.parse_args()

    index = read_filings_index(repo_path(args.filings_index))
    output = repo_path(args.output_dir)
    prior = pd.DataFrame()
    completed: dict[str, Any] = {}
    manifest = output / "form4_transactions_summary.json"
    if args.resume_existing and manifest.exists() and (output / "form4_transactions.parquet").exists():
        previous = json.loads(manifest.read_text())
        if previous.get("schema_version") == "sec-ownership-parser-receipt-v2":
            if previous.get("output_sha256", {}).get("parquet") != file_hash(output / "form4_transactions.parquet"):
                raise ValueError("OWNERSHIP_RESUME_HASH_CONFLICT")
            prior = pd.read_parquet(output / "form4_transactions.parquet")
            completed = previous.get("completed", {})
    frame = parse_form4_index(
        index,
        raw_dir=repo_path(args.raw_dir),
        user_agent=args.user_agent,
        refresh=bool(args.refresh),
        sleep_s=float(args.sleep),
        max_filings=int(args.max_filings),
        completed=completed,
    )
    receipt = frame.attrs.get("parse_receipt", {})
    frame = replace_reparsed_rows(prior, frame, receipt)
    paths = write_outputs(frame, repo_path(args.output_dir))
    print(json.dumps({"status": "ok", "rows": int(len(frame)), **paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
