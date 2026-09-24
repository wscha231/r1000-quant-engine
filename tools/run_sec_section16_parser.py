#!/usr/bin/env python3
"""Parse SEC Section 16 Forms 3/4/5 into normalized PIT ownership evidence.

This is a data-foundation layer only.  It does not score securities, mutate
target books, or create portfolio decisions.  The legacy Form 4 parser remains
the compatibility producer for form4_transactions.* while this module preserves
the broader Section 16 record, including Forms 3/5, derivative rows, holdings,
and multi-owner filing identity.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_form4_parser import (  # noqa: E402
    as_bool,
    as_float,
    cache_name,
    cik10,
    first_text,
    first_value,
    form4_url_candidates,
    local_name,
    nodes,
    read_filings_index,
    repo_path,
    sec_get_text,
)

DEFAULT_INDEX = "data_pit/sec/sec_filings_index.parquet"
DEFAULT_OUTPUT_DIR = "data_pit/sec"
DEFAULT_RAW_DIR = "data_raw/sec"

SECTION16_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A"}

SECTION16_ERROR_COLUMNS = [
    "form_type",
    "accession_number",
    "ticker",
    "cik10",
    "accepted_at",
    "available_from",
    "error",
]

OWNER_FIELDS = [
    "reporting_owner_cik",
    "reporting_owner_name",
    "officer_title",
    "is_director",
    "is_officer",
    "is_ten_percent_owner",
    "is_other",
    "reporting_owner_country",
    "reporting_owner_non_us_address",
    "reporting_owner_non_us_state_territory",
]

SECTION16_TRANSACTION_COLUMNS = [
    "issuer_ticker",
    "issuer_foreign_trading_symbol",
    "issuer_cik10",
    *OWNER_FIELDS,
    "reporting_owner_count",
    "reporting_owners_json",
    "form_type",
    "period_of_report",
    "filing_date",
    "accepted_at",
    "available_from",
    "not_subject_to_section16",
    "aff10b5_one",
    "remarks",
    "footnotes_json",
    "record_footnote_ids",
    "transaction_date",
    "deemed_execution_date",
    "transaction_timeliness",
    "transaction_code",
    "acquired_disposed_code",
    "transaction_shares",
    "transaction_price",
    "transaction_value",
    "ownership_nature",
    "direct_or_indirect",
    "shares_owned_after",
    "is_derivative",
    "security_title",
    "underlying_security_title",
    "underlying_shares",
    "conversion_or_exercise_price",
    "exercise_date",
    "expiration_date",
    "equity_swap_involved",
    "accession_number",
    "filing_url",
]

SECTION16_HOLDING_COLUMNS = [
    "issuer_ticker",
    "issuer_foreign_trading_symbol",
    "issuer_cik10",
    *OWNER_FIELDS,
    "reporting_owner_count",
    "reporting_owners_json",
    "form_type",
    "period_of_report",
    "filing_date",
    "accepted_at",
    "available_from",
    "not_subject_to_section16",
    "aff10b5_one",
    "remarks",
    "footnotes_json",
    "record_footnote_ids",
    "ownership_nature",
    "direct_or_indirect",
    "shares_owned",
    "is_derivative",
    "security_title",
    "underlying_security_title",
    "underlying_shares",
    "conversion_or_exercise_price",
    "exercise_date",
    "expiration_date",
    "accession_number",
    "filing_url",
]

OWNERSHIP_STATE_COLUMNS = [
    "issuer_ticker",
    "issuer_foreign_trading_symbol",
    "issuer_cik10",
    *OWNER_FIELDS,
    "form_type",
    "period_of_report",
    "filing_date",
    "accepted_at",
    "available_from",
    "state_effective_date",
    "ownership_nature",
    "direct_or_indirect",
    "shares_owned",
    "is_derivative",
    "security_title",
    "underlying_security_title",
    "underlying_shares",
    "conversion_or_exercise_price",
    "accession_number",
    "filing_url",
    "state_source",
]


def _owner_record(owner: Any) -> dict[str, Any]:
    rel = None
    for child in owner.iter():
        if child.tag.rsplit("}", 1)[-1] == "reportingOwnerRelationship":
            rel = child
            break
    return {
        "reporting_owner_cik": cik10(first_text(owner, "rptOwnerCik")),
        "reporting_owner_name": first_text(owner, "rptOwnerName"),
        "officer_title": first_text(rel, "officerTitle"),
        "is_director": as_bool(first_text(rel, "isDirector")),
        "is_officer": as_bool(first_text(rel, "isOfficer")),
        "is_ten_percent_owner": as_bool(first_text(rel, "isTenPercentOwner")),
        "is_other": as_bool(first_text(rel, "isOther")),
        "reporting_owner_country": first_text(owner, "rptOwnerCountry"),
        "reporting_owner_non_us_address": as_bool(first_text(owner, "rptOwnerNonUSAddressFlag")),
        "reporting_owner_non_us_state_territory": first_text(owner, "rptOwnerNonUSStateTerritory"),
    }


def parse_owners(root: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for owner in nodes(root, "reportingOwner"):
        record = _owner_record(owner)
        if record["reporting_owner_cik"] or record["reporting_owner_name"]:
            out.append(record)
    return out


def _owner_bundle(owners: list[dict[str, Any]]) -> dict[str, Any]:
    primary = owners[0] if owners else {field: "" for field in OWNER_FIELDS}
    return {
        **primary,
        "reporting_owner_count": int(len(owners)),
        "reporting_owners_json": json.dumps(owners, sort_keys=True, ensure_ascii=False),
    }


def _optional_bool(node: Any, name: str) -> bool | None:
    value = first_text(node, name)
    return None if value == "" else as_bool(value)


def _footnote_map(root: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for footnote in nodes(root, "footnote"):
        ident = str(footnote.attrib.get("id") or "").strip().upper()
        if not ident:
            continue
        text = " ".join("".join(footnote.itertext()).split())
        out[ident] = text
    return out


def _footnote_ids(node: Any) -> list[str]:
    ids: list[str] = []
    for child in node.iter():
        if local_name(child.tag) != "footnoteId":
            continue
        ident = str(child.attrib.get("id") or "").strip().upper()
        if ident and ident not in ids:
            ids.append(ident)
    return ids


def _filing_meta(root: Any, filing: dict[str, Any]) -> dict[str, Any]:
    form_type = str(filing.get("form_type") or first_text(root, "documentType")).upper().strip()
    footnotes = _footnote_map(root)
    return {
        "issuer_ticker": first_text(root, "issuerTradingSymbol").upper().strip(),
        "issuer_foreign_trading_symbol": first_text(root, "issuerForeignTradingSymbol").upper().strip(),
        "issuer_cik10": cik10(first_text(root, "issuerCik")),
        "form_type": form_type,
        "period_of_report": first_text(root, "periodOfReport"),
        "filing_date": str(filing.get("filing_date") or ""),
        "accepted_at": str(filing.get("accepted_at") or ""),
        "available_from": str(filing.get("available_from") or filing.get("accepted_at") or ""),
        "not_subject_to_section16": _optional_bool(root, "notSubjectToSection16"),
        "aff10b5_one": _optional_bool(root, "aff10b5One"),
        "remarks": first_text(root, "remarks"),
        "footnotes_json": json.dumps(footnotes, sort_keys=True, ensure_ascii=False),
        "accession_number": str(filing.get("accession_number") or ""),
        "filing_url": str(filing.get("filing_url") or ""),
    }


def _transaction_row(
    root: Any,
    tx: Any,
    filing: dict[str, Any],
    owners: list[dict[str, Any]],
    *,
    is_derivative: bool,
) -> dict[str, Any]:
    shares = as_float(first_value(tx, "transactionShares")) or 0.0
    price = as_float(first_value(tx, "transactionPricePerShare")) or 0.0
    owned_after = as_float(first_value(tx, "sharesOwnedFollowingTransaction"))
    underlying_shares = as_float(first_value(tx, "underlyingSecurityShares"))
    conversion = as_float(first_value(tx, "conversionOrExercisePrice"))
    return {
        **_filing_meta(root, filing),
        **_owner_bundle(owners),
        "transaction_date": first_value(tx, "transactionDate"),
        "deemed_execution_date": first_value(tx, "deemedExecutionDate"),
        "transaction_timeliness": first_value(tx, "transactionTimeliness"),
        "record_footnote_ids": json.dumps(_footnote_ids(tx)),
        "transaction_code": first_text(tx, "transactionCode").upper().strip(),
        "acquired_disposed_code": first_value(tx, "transactionAcquiredDisposedCode").upper().strip(),
        "transaction_shares": float(shares),
        "transaction_price": float(price),
        "transaction_value": None if is_derivative else float(shares * price),
        "ownership_nature": first_value(tx, "natureOfOwnership"),
        "direct_or_indirect": first_value(tx, "directOrIndirectOwnership"),
        "shares_owned_after": owned_after,
        "is_derivative": bool(is_derivative),
        "security_title": first_value(tx, "securityTitle"),
        "underlying_security_title": first_value(tx, "underlyingSecurityTitle"),
        "underlying_shares": underlying_shares,
        "conversion_or_exercise_price": conversion,
        "exercise_date": first_value(tx, "exerciseDate"),
        "expiration_date": first_value(tx, "expirationDate"),
        "equity_swap_involved": as_bool(first_text(tx, "equitySwapInvolved")),
    }


def _holding_row(
    root: Any,
    holding: Any,
    filing: dict[str, Any],
    owners: list[dict[str, Any]],
    *,
    is_derivative: bool,
) -> dict[str, Any]:
    return {
        **_filing_meta(root, filing),
        **_owner_bundle(owners),
        "record_footnote_ids": json.dumps(_footnote_ids(holding)),
        "ownership_nature": first_value(holding, "natureOfOwnership"),
        "direct_or_indirect": first_value(holding, "directOrIndirectOwnership"),
        "shares_owned": as_float(first_value(holding, "sharesOwnedFollowingTransaction")),
        "is_derivative": bool(is_derivative),
        "security_title": first_value(holding, "securityTitle"),
        "underlying_security_title": first_value(holding, "underlyingSecurityTitle"),
        "underlying_shares": as_float(first_value(holding, "underlyingSecurityShares")),
        "conversion_or_exercise_price": as_float(first_value(holding, "conversionOrExercisePrice")),
        "exercise_date": first_value(holding, "exerciseDate"),
        "expiration_date": first_value(holding, "expirationDate"),
    }


def parse_section16_xml(
    xml_text: str,
    *,
    filing: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import xml.etree.ElementTree as ET

    filing = filing or {}
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    owners = parse_owners(root)
    transactions: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []

    for tx in nodes(root, "nonDerivativeTransaction"):
        transactions.append(_transaction_row(root, tx, filing, owners, is_derivative=False))
    for tx in nodes(root, "derivativeTransaction"):
        transactions.append(_transaction_row(root, tx, filing, owners, is_derivative=True))
    for holding in nodes(root, "nonDerivativeHolding"):
        holdings.append(_holding_row(root, holding, filing, owners, is_derivative=False))
    for holding in nodes(root, "derivativeHolding"):
        holdings.append(_holding_row(root, holding, filing, owners, is_derivative=True))

    return transactions, holdings


def cache_section16_document(
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

    out_dir = raw_dir / "filings" / "section16"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / cache_name(accession, primary_doc)
    if refresh or not cache.exists():
        errors: list[str] = []
        text = ""
        for url in form4_url_candidates(
            cik,
            accession,
            primary_doc,
            str(filing.get("filing_url") or ""),
        ):
            try:
                candidate = sec_get_text(url, user_agent=user_agent, sleep_s=sleep_s)
                if "<ownershipDocument" in candidate or "<?xml" in candidate[:200]:
                    text = candidate
                    break
                errors.append(f"{url}: non-xml response")
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        if not text:
            raise RuntimeError("; ".join(errors)[:500] or "no Section 16 document URL candidates")
        tmp = out_dir / f".{cache.name}.{os.getpid()}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, cache)
    return cache, cache.read_text(encoding="utf-8")


def _normalize_index(index: pd.DataFrame) -> pd.DataFrame:
    if index.empty:
        return pd.DataFrame()
    d = index.copy()
    d["form_type"] = d.get("form_type", "").astype(str).str.upper().str.strip()
    d = d[d["form_type"].isin(SECTION16_FORMS)].copy()
    if "accession_number" in d.columns:
        d["accession_number"] = d["accession_number"].astype(str).str.strip()
        d = d.drop_duplicates(["accession_number", "form_type"], keep="last")
    return d.reset_index(drop=True)


def parse_section16_index(
    index: pd.DataFrame,
    *,
    raw_dir: Path,
    user_agent: str | None = None,
    refresh: bool = False,
    sleep_s: float = 0.12,
    max_filings: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    filings = _normalize_index(index)
    if max_filings and max_filings > 0:
        filings = filings.head(int(max_filings)).copy()

    transactions: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for _, item in filings.iterrows():
        filing = item.to_dict()
        try:
            _, xml_text = cache_section16_document(
                filing,
                raw_dir,
                user_agent=user_agent,
                refresh=refresh,
                sleep_s=sleep_s,
            )
            if not xml_text:
                continue
            tx_rows, holding_rows = parse_section16_xml(xml_text, filing=filing)
            transactions.extend(tx_rows)
            holdings.extend(holding_rows)
        except Exception as exc:
            errors.append(
                {
                    "form_type": str(filing.get("form_type") or ""),
                    "accession_number": str(filing.get("accession_number") or ""),
                    "ticker": str(filing.get("ticker") or ""),
                    "cik10": cik10(filing.get("cik10")),
                    "accepted_at": str(filing.get("accepted_at") or ""),
                    "available_from": str(filing.get("available_from") or ""),
                    "error": str(exc)[:500],
                }
            )

    tx = pd.DataFrame(transactions)
    h = pd.DataFrame(holdings)
    for col in SECTION16_TRANSACTION_COLUMNS:
        if col not in tx.columns:
            tx[col] = pd.NA
    for col in SECTION16_HOLDING_COLUMNS:
        if col not in h.columns:
            h[col] = pd.NA
    return (
        filings,
        tx[SECTION16_TRANSACTION_COLUMNS].copy(),
        h[SECTION16_HOLDING_COLUMNS].copy(),
        pd.DataFrame(errors, columns=SECTION16_ERROR_COLUMNS),
    )


def _owner_variants(row: pd.Series) -> list[dict[str, Any]]:
    raw = str(row.get("reporting_owners_json") or "").strip()
    owners: list[dict[str, Any]] = []
    if raw and raw.lower() not in {"nan", "none"}:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                owners = [item for item in parsed if isinstance(item, dict)]
        except Exception:
            owners = []
    if owners:
        return owners
    return [{field: row.get(field, "") for field in OWNER_FIELDS}]


def _single_owner_or_none(row: pd.Series) -> dict[str, Any] | None:
    owners = _owner_variants(row)
    if len(owners) != 1:
        return None
    return owners[0]


def build_ownership_state(transactions: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if not holdings.empty:
        for _, row in holdings.iterrows():
            owner = _single_owner_or_none(row)
            if owner is None:
                continue
            rows.append(
                {
                    **{col: row.get(col, pd.NA) for col in SECTION16_HOLDING_COLUMNS if col not in OWNER_FIELDS and col != "reporting_owner_count" and col != "reporting_owners_json"},
                    **{field: owner.get(field, "") for field in OWNER_FIELDS},
                    "state_effective_date": row.get("period_of_report") or row.get("filing_date", ""),
                    "state_source": "holding",
                }
            )

    if not transactions.empty:
        tx = transactions[pd.to_numeric(transactions.get("shares_owned_after"), errors="coerce").notna()].copy()
        for _, row in tx.iterrows():
            owner = _single_owner_or_none(row)
            if owner is None:
                continue
            rows.append(
                {
                    "issuer_ticker": row.get("issuer_ticker", ""),
                    "issuer_cik10": row.get("issuer_cik10", ""),
                    **{field: owner.get(field, "") for field in OWNER_FIELDS},
                    "form_type": row.get("form_type", ""),
                    "period_of_report": row.get("period_of_report", ""),
                    "filing_date": row.get("filing_date", ""),
                    "accepted_at": row.get("accepted_at", ""),
                    "available_from": row.get("available_from", ""),
                    "state_effective_date": row.get("transaction_date") or row.get("period_of_report") or row.get("filing_date", ""),
                    "ownership_nature": row.get("ownership_nature", ""),
                    "direct_or_indirect": row.get("direct_or_indirect", ""),
                    "shares_owned": row.get("shares_owned_after"),
                    "is_derivative": row.get("is_derivative", False),
                    "security_title": row.get("security_title", ""),
                    "underlying_security_title": row.get("underlying_security_title", ""),
                    "underlying_shares": row.get("underlying_shares"),
                    "conversion_or_exercise_price": row.get("conversion_or_exercise_price"),
                    "accession_number": row.get("accession_number", ""),
                    "filing_url": row.get("filing_url", ""),
                    "state_source": "transaction",
                }
            )

    if not rows:
        return pd.DataFrame(columns=OWNERSHIP_STATE_COLUMNS)

    state = pd.DataFrame(rows)
    for col in ["issuer_cik10", "reporting_owner_cik"]:
        state[col] = state[col].map(cik10)
    state["issuer_ticker"] = state["issuer_ticker"].fillna("").astype(str).str.upper().str.strip()
    state["security_title"] = state["security_title"].fillna("").astype(str).str.strip()
    state["direct_or_indirect"] = state["direct_or_indirect"].fillna("").astype(str).str.upper().str.strip()
    state["available_from_ts"] = pd.to_datetime(state["available_from"], errors="coerce", utc=True)
    state["state_effective_ts"] = pd.to_datetime(state["state_effective_date"], errors="coerce", utc=True)
    state = state[state["available_from_ts"].notna() & state["state_effective_ts"].notna()].copy()
    # A late Form 5 can disclose an older transaction.  Current ownership state
    # follows the latest effective ownership event, while available_from is kept
    # as the PIT knowledge boundary and amendment/tie-break timestamp.
    state = state.sort_values(
        ["state_effective_ts", "available_from_ts", "accession_number", "state_source"]
    )

    keys = [
        "issuer_cik10",
        "reporting_owner_cik",
        "security_title",
        "is_derivative",
        "direct_or_indirect",
    ]
    state = state.drop_duplicates(keys, keep="last").drop(columns=["available_from_ts", "state_effective_ts"])
    for col in OWNERSHIP_STATE_COLUMNS:
        if col not in state.columns:
            state[col] = pd.NA
    return state[OWNERSHIP_STATE_COLUMNS].reset_index(drop=True)


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(tmp, index=False)
    else:
        frame.to_csv(tmp, index=False)
    os.replace(tmp, path)


def write_outputs(
    filings: pd.DataFrame,
    transactions: pd.DataFrame,
    holdings: pd.DataFrame,
    errors: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    state = build_ownership_state(transactions, holdings)

    paths = {
        "filings": output_dir / "section16_filings.parquet",
        "transactions": output_dir / "section16_transactions.parquet",
        "holdings": output_dir / "section16_holdings.parquet",
        "ownership_state": output_dir / "section16_ownership_state.parquet",
        "errors": output_dir / "section16_parse_errors.csv",
    }
    _write_table(filings, paths["filings"])
    _write_table(transactions, paths["transactions"])
    _write_table(holdings, paths["holdings"])
    _write_table(state, paths["ownership_state"])
    _write_table(errors, paths["errors"])

    by_form = (
        filings["form_type"].value_counts().sort_index().to_dict()
        if not filings.empty and "form_type" in filings.columns
        else {}
    )
    summary = {
        "schema_version": "sec-section16-pit-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "forms": sorted(SECTION16_FORMS),
        "filing_rows": int(len(filings)),
        "transaction_rows": int(len(transactions)),
        "holding_rows": int(len(holdings)),
        "ownership_state_rows": int(len(state)),
        "parse_error_rows": int(len(errors)),
        "filings_by_form": {str(k): int(v) for k, v in by_form.items()},
        "outputs": {name: str(path) for name, path in paths.items()},
    }
    summary_path = output_dir / "section16_summary.json"
    summary["outputs"]["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings-index", default=DEFAULT_INDEX)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--max-filings", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = read_filings_index(repo_path(args.filings_index))
    filings, transactions, holdings, errors = parse_section16_index(
        index,
        raw_dir=repo_path(args.raw_dir),
        user_agent=args.user_agent,
        refresh=bool(args.refresh),
        sleep_s=float(args.sleep),
        max_filings=int(args.max_filings),
    )
    summary = write_outputs(
        filings,
        transactions,
        holdings,
        errors,
        repo_path(args.output_dir),
    )
    print(json.dumps({"status": "ok", **summary}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
