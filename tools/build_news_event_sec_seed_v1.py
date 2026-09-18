#!/usr/bin/env python3
"""Build official SEC historical event seeds for News Event Alpha V1.

Input is the PIT SEC filings index produced by run_sec_submissions_collector.py
with accepted_at/available_from and item codes preserved. This adapter is
research-only. It does not infer contract value, theme membership, or a new
business relationship from filing text.

Only events with independently supplied, event-date-valid US COMMON/ADR
eligibility are emitted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.news_event_alpha_v1.runtime import canonical_bytes, digest  # noqa: E402


ITEM_EVENT_PRIORITY = (
    ("4.02", "FINANCIAL_NONRELIANCE"),
    ("3.01", "LISTING_COMPLIANCE"),
    ("2.06", "MATERIAL_IMPAIRMENT"),
    ("2.05", "RESTRUCTURING_EXIT_PLAN"),
    ("1.02", "MATERIAL_AGREEMENT_TERMINATION"),
    ("3.02", "SECURITIES_ISSUANCE"),
    ("2.03", "DEBT_OBLIGATION"),
    ("2.01", "ACQUISITION_OR_DISPOSITION"),
    ("1.01", "MATERIAL_DEFINITIVE_AGREEMENT"),
    ("2.02", "RESULTS_OF_OPERATIONS"),
)
ELIGIBLE_INSTRUMENTS = {"COMMON", "ADR"}
ELIGIBLE_EXCHANGES = {"XNYS", "XNAS", "XASE"}


def load_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def parse_items(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return []
    return sorted(set(re.findall(r"(?<!\d)(\d+\.\d+)(?!\d)", text)))


def classify_items(items: list[str]) -> tuple[str | None, str | None]:
    item_set = set(items)
    for item, event_type in ITEM_EVENT_PRIORITY:
        if item in item_set:
            return item, event_type
    return None, None


def parse_date(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, errors="coerce", utc=True)


def normalize_eligibility(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "security_id" not in out.columns:
        if "ticker" in out.columns:
            out["security_id"] = out["ticker"]
        else:
            raise ValueError("eligibility requires security_id or ticker")
    required = {"security_id", "instrument", "exchange", "listing_country"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"eligibility missing columns: {sorted(missing)}")
    out["security_id"] = out["security_id"].astype(str).str.upper().str.strip()
    out["instrument"] = out["instrument"].astype(str).str.upper().str.strip()
    out["exchange"] = out["exchange"].astype(str).str.upper().str.strip()
    out["listing_country"] = out["listing_country"].astype(str).str.upper().str.strip()
    out["eligible_from"] = pd.to_datetime(
        out["eligible_from"] if "eligible_from" in out.columns else "1900-01-01",
        errors="coerce",
        utc=True,
    )
    out["eligible_to"] = pd.to_datetime(
        out["eligible_to"] if "eligible_to" in out.columns else "2100-12-31",
        errors="coerce",
        utc=True,
    )
    if "verified_asof" in out.columns:
        out["verified_asof"] = out["verified_asof"].map(
            lambda value: (
                value
                if isinstance(value, bool)
                else str(value).strip().lower() in {"1", "true", "yes", "y"}
            )
        )
    else:
        out["verified_asof"] = False
    return out


def eligibility_at(
    eligibility: pd.DataFrame,
    security_id: str,
    timestamp: pd.Timestamp,
) -> dict[str, Any] | None:
    subset = eligibility[
        (eligibility["security_id"] == security_id)
        & eligibility["eligible_from"].notna()
        & eligibility["eligible_to"].notna()
        & (eligibility["eligible_from"] <= timestamp)
        & (eligibility["eligible_to"] >= timestamp)
        & eligibility["verified_asof"]
    ]
    if subset.empty:
        return None
    subset = subset.sort_values("eligible_from", ascending=False)
    row = subset.iloc[0]
    instrument = str(row["instrument"])
    exchange = str(row["exchange"])
    country = str(row["listing_country"])
    if (
        instrument not in ELIGIBLE_INSTRUMENTS
        or exchange not in ELIGIBLE_EXCHANGES
        or country != "US"
    ):
        return None
    return {
        "instrument": instrument,
        "exchange": exchange,
        "listing_country": country,
        "eligibility_verified_asof": True,
    }


def build_events(
    filings: pd.DataFrame,
    eligibility: pd.DataFrame,
    *,
    history_start: str = "",
    history_end: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    start = parse_date(history_start) if history_start else pd.NaT
    end = parse_date(history_end) if history_end else pd.NaT

    for _, row in filings.iterrows():
        ticker = str(row.get("ticker") or "").upper().strip()
        accession = str(row.get("accession_number") or "").strip()
        form_type = str(row.get("form_type") or "").upper().strip()
        available = parse_date(row.get("available_from") or row.get("accepted_at"))
        items = parse_items(row.get("items"))
        primary_item, event_type = classify_items(items)

        reason = ""
        if not ticker or not accession:
            reason = "MISSING_IDENTITY"
        elif form_type != "8-K":
            reason = "UNSUPPORTED_FORM"
        elif pd.isna(available):
            reason = "MISSING_AVAILABLE_FROM"
        elif pd.notna(start) and available < start:
            reason = "BEFORE_HISTORY_START"
        elif pd.notna(end) and available > end:
            reason = "AFTER_HISTORY_END"
        elif event_type is None:
            reason = "NO_SUPPORTED_8K_ITEM"

        eligibility_row = None
        if not reason:
            eligibility_row = eligibility_at(eligibility, ticker, available)
            if eligibility_row is None:
                reason = "NO_VERIFIED_US_COMMON_ADR_ELIGIBILITY"

        if reason:
            rejected.append(
                {
                    "ticker": ticker,
                    "accession_number": accession,
                    "form_type": form_type,
                    "available_from": (
                        available.isoformat() if pd.notna(available) else ""
                    ),
                    "items": items,
                    "reason": reason,
                }
            )
            continue

        cik = str(row.get("cik10") or "").strip()
        event_id = f"sec:{cik or ticker}:{accession}"
        event = {
            "event_id": event_id,
            "economic_event_id": event_id,
            "security_id": ticker,
            "issuer_id": cik or ticker,
            **eligibility_row,
            "available_at": available.isoformat(),
            "event_type": event_type,
            "event_tags": [f"SEC_8K_ITEM_{x}" for x in items],
            "role": "DIRECT",
            "source_tier": "OFFICIAL",
            "official_evidence": True,
            "business_relation_new": False,
            "material_agreement_confirmed": primary_item == "1.01",
            "economic_value_confirmed": False,
            "economic_amount_usd": None,
            "economic_amount_kind": "UNKNOWN",
            "theme_id": "UNASSIGNED",
            "theme_peer_ids": [],
            "independent_source_groups": ["SEC_EDGAR"],
            "source_family": "SEC_EDGAR",
            "story_id": accession,
            "sample_origin": "HISTORICAL_BACKFILL",
            "dilution_risk": None,
            "cashflow_risk": None,
            "balance_sheet_risk": None,
            "sec_form_type": form_type,
            "sec_primary_item": primary_item,
            "sec_items": items,
            "source_url": str(row.get("filing_url") or ""),
            "filing_url": str(row.get("filing_url") or ""),
        }
        events.append(event)

    events.sort(key=lambda x: (x["available_at"], x["economic_event_id"]))
    rejected.sort(
        key=lambda x: (x["available_from"], x["ticker"], x["accession_number"])
    )
    return events, rejected


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filings-index", required=True)
    parser.add_argument("--eligibility", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--history-start", default="")
    parser.add_argument("--history-end", default="")
    args = parser.parse_args()

    filings_path = Path(args.filings_index)
    eligibility_path = Path(args.eligibility)
    out = Path(args.output_dir)

    filings = load_frame(filings_path)
    eligibility = normalize_eligibility(load_frame(eligibility_path))
    events, rejected = build_events(
        filings,
        eligibility,
        history_start=args.history_start,
        history_end=args.history_end,
    )

    out.mkdir(parents=True, exist_ok=True)
    event_path = out / "sec_8k_event_seeds.jsonl"
    rejected_path = out / "sec_8k_event_rejections.jsonl"
    manifest_path = out / "sec_8k_event_seed_manifest.json"
    write_jsonl(event_path, events)
    write_jsonl(rejected_path, rejected)

    manifest = {
        "schema": "news-event-alpha-sec-seed-manifest-v1",
        "research_only": True,
        "source": "SEC_EDGAR",
        "event_count": len(events),
        "rejected_count": len(rejected),
        "event_type_counts": (
            pd.Series([x["event_type"] for x in events]).value_counts().to_dict()
            if events
            else {}
        ),
        "first_available_at": events[0]["available_at"] if events else None,
        "last_available_at": events[-1]["available_at"] if events else None,
        "inputs": {
            "filings_index": str(filings_path),
            "eligibility": str(eligibility_path),
        },
        "outputs": {
            "events": str(event_path),
            "rejections": str(rejected_path),
        },
        "notes": [
            "Item 1.01 is material_agreement_confirmed but no contract amount is inferred.",
            "business_relation_new remains false without filing-text review.",
            "theme_peer_ids remain empty; historical theme breadth is not invented.",
            "Unsupported or unverified rows are rejected, not silently promoted.",
        ],
    }
    manifest["manifest_sha256"] = digest(manifest)
    manifest_path.write_bytes(canonical_bytes(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
