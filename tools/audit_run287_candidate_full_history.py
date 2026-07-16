#!/usr/bin/env python3
"""Freeze price, accepted-time SEC and Companyfacts coverage for candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def cik10(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    text = text.split(".")[0]
    return text.zfill(10) if text.isdigit() else ""


def fact_shape(path: Path) -> tuple[int, int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    concepts = 0
    rows = 0
    accessions: set[str] = set()
    for namespace in (payload.get("facts") or {}).values():
        concepts += len(namespace or {})
        for concept in (namespace or {}).values():
            for values in (concept.get("units") or {}).values():
                rows += len(values or [])
                accessions.update(
                    str(row.get("accn"))
                    for row in (values or [])
                    if row.get("accn")
                )
    return concepts, rows, len(accessions)


def build(args: argparse.Namespace) -> dict[str, Any]:
    audit_path = repo_path(args.candidate_audit)
    price_manifest_path = repo_path(args.price_manifest)
    companyfacts_zip = repo_path(args.companyfacts_zip)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    audit = pd.read_csv(audit_path, low_memory=False)
    price_manifest = json.loads(price_manifest_path.read_text(encoding="utf-8"))
    if price_manifest.get("status") != "completed" or price_manifest.get("failed_count"):
        raise ValueError("price full-history manifest is not complete")

    targeted: dict[str, dict[str, Any]] = {}
    companyfacts_manifest_paths = [repo_path(value) for value in args.companyfacts_manifest]
    for manifest_path in companyfacts_manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "READY_RESEARCH_ONLY_COMPANYFACTS_HISTORY":
            raise ValueError(f"Companyfacts manifest is not ready: {manifest_path}")
        for record in manifest.get("companyfacts_files") or []:
            path = Path(record["path"])
            concepts, rows, accessions = fact_shape(path)
            targeted[cik10(record.get("cik10"))] = {
                "companyfacts_path": str(path.resolve()),
                "companyfacts_sha256": str(record.get("sha256") or ""),
                "companyfacts_concept_count": concepts,
                "companyfacts_fact_row_count": rows,
                "companyfacts_accession_count": accessions,
            }

    with zipfile.ZipFile(companyfacts_zip) as archive:
        bulk_ciks = {
            Path(name).stem.replace("CIK", "")
            for name in archive.namelist()
            if name.endswith(".json") and Path(name).stem.startswith("CIK")
        }

    sec_paths = [repo_path(value) for value in args.sec_index]
    sec = pd.concat([pd.read_parquet(path) for path in sec_paths], ignore_index=True)
    sec["ticker"] = sec["ticker"].astype(str).str.upper().str.strip()
    sec["accepted_at"] = pd.to_datetime(sec["accepted_at"], errors="coerce", utc=True)
    sec = sec.drop_duplicates(["ticker", "accession_number"], keep="last")

    rows: list[dict[str, Any]] = []
    for record in audit.to_dict("records"):
        ticker = str(record.get("ticker") or "").upper().strip()
        direct_cik = cik10(record.get("identity_cik10")) or cik10(record.get("universe_cik10"))
        proxy = str(record.get("issuer_sec_proxy_ticker") or "").upper().strip()
        if proxy == "NAN":
            proxy = ""
        sec_group = sec.loc[sec["ticker"].eq(ticker)]
        if direct_cik in targeted:
            cf_source = "TARGETED_SEC_COMPANYFACTS_FULL_JSON"
            cf = targeted[direct_cik]
            cf_backfill = False
        elif direct_cik and direct_cik in bulk_ciks:
            cf_source = "CANONICAL_SEC_COMPANYFACTS_BULK"
            cf = {
                "companyfacts_path": str(companyfacts_zip.resolve()),
                "companyfacts_sha256": "",
                "companyfacts_concept_count": pd.NA,
                "companyfacts_fact_row_count": pd.NA,
                "companyfacts_accession_count": pd.NA,
            }
            cf_backfill = False
        elif proxy:
            cf_source = "ISSUER_SEC_PROXY_ONLY_NOT_HOME_LISTING_SPECIFIC"
            cf = {
                "companyfacts_path": "",
                "companyfacts_sha256": "",
                "companyfacts_concept_count": pd.NA,
                "companyfacts_fact_row_count": pd.NA,
                "companyfacts_accession_count": pd.NA,
            }
            cf_backfill = True
        else:
            cf_source = "MISSING_COMPANYFACTS"
            cf = {
                "companyfacts_path": "",
                "companyfacts_sha256": "",
                "companyfacts_concept_count": pd.NA,
                "companyfacts_fact_row_count": pd.NA,
                "companyfacts_accession_count": pd.NA,
            }
            cf_backfill = True
        exact = int(sec_group["accepted_at"].notna().sum())
        rows.append(
            {
                "ticker": ticker,
                "issuer_key": record.get("issuer_key", ""),
                "in_frozen_universe": bool(record.get("in_frozen_universe")),
                "resolved_cik10": direct_cik,
                "price_history_status": record.get("price_history_status", ""),
                "price_history_start": record.get("price_history_start", ""),
                "price_history_end": record.get("price_history_end", ""),
                "price_history_rows": int(record.get("price_history_rows") or 0),
                "full_available_price_history_fetched": bool(record.get("price_history_authoritative_full_fetch")),
                "canonical_7y_price_eligible": bool(record.get("canonical_7y_price_eligible")),
                "sec_accepted_rows": int(len(sec_group)),
                "sec_exact_acceptance_rows": exact,
                "sec_exact_acceptance_ratio": float(exact / len(sec_group)) if len(sec_group) else 0.0,
                "sec_route_status": record.get("sec_route_status", ""),
                "issuer_sec_proxy_ticker": proxy,
                "home_market_filing_backfill_required": bool(record.get("home_market_filing_backfill_required")),
                "companyfacts_source": cf_source,
                **cf,
                "companyfacts_backfill_required": cf_backfill,
                "research_context_onboarding_required": not bool(record.get("in_frozen_universe")),
                "historical_portfolio_evaluation_allowed": False,
                "production_activation_allowed": False,
            }
        )

    coverage = pd.DataFrame(rows).sort_values("ticker")
    coverage_path = output_dir / "candidate_full_history_coverage.csv"
    coverage.to_csv(coverage_path, index=False)
    summary = {
        "schema_version": "run287-candidate-full-history-v1",
        "status": "READY_RESEARCH_ONLY_WITH_EXPLICIT_GAPS",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": int(len(coverage)),
        "full_available_price_history_count": int(coverage["full_available_price_history_fetched"].sum()),
        "canonical_7y_price_eligible_count": int(coverage["canonical_7y_price_eligible"].sum()),
        "short_listing_history_count": int(coverage["price_history_status"].eq("FULL_AVAILABLE_HISTORY_SHORT_LISTING").sum()),
        "exact_sec_accepted_ticker_count": int(coverage["sec_exact_acceptance_ratio"].eq(1.0).sum()),
        "sec_or_home_market_gap_count": int(coverage["home_market_filing_backfill_required"].sum()),
        "companyfacts_available_ticker_count": int((~coverage["companyfacts_backfill_required"]).sum()),
        "companyfacts_gap_count": int(coverage["companyfacts_backfill_required"].sum()),
        "research_context_onboarding_count": int(coverage["research_context_onboarding_required"].sum()),
        "inputs": {
            "candidate_audit": fingerprint(audit_path),
            "price_manifest": fingerprint(price_manifest_path),
            "sec_indexes": [fingerprint(path) for path in sec_paths],
            "companyfacts_zip": fingerprint(companyfacts_zip),
            "companyfacts_manifests": [fingerprint(path) for path in companyfacts_manifest_paths],
        },
        "outputs": {"candidate_full_history_coverage": fingerprint(coverage_path)},
        "fullrun_executed": False,
        "backtest_executed": False,
        "orders_generated": False,
        "universe_mutated": False,
        "portfolio_weights_mutated": False,
        "pit_universe_label_clean": False,
        "production_activation_allowed": False,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    gaps = coverage.loc[
        coverage["home_market_filing_backfill_required"]
        | coverage["companyfacts_backfill_required"]
        | ~coverage["canonical_7y_price_eligible"]
    ]
    lines = [
        "# Run287 candidate full-history coverage",
        "",
        f"Status: `{summary['status']}`.",
        "",
        f"- candidates with full available price history fetched: `{summary['full_available_price_history_count']}/{summary['candidate_count']}`",
        f"- canonical 7-year price eligible: `{summary['canonical_7y_price_eligible_count']}/{summary['candidate_count']}`",
        f"- exact accepted-time SEC coverage: `{summary['exact_sec_accepted_ticker_count']}/{summary['candidate_count']}`",
        f"- Companyfacts available: `{summary['companyfacts_available_ticker_count']}/{summary['candidate_count']}`",
        f"- research-context onboarding still required: `{summary['research_context_onboarding_count']}`",
        "",
        "## Structural gaps",
        "",
        "| ticker | price | SEC | Companyfacts |",
        "|---|---|---|---|",
    ]
    for row in gaps.to_dict("records"):
        lines.append(
            f"| {row['ticker']} | `{row['price_history_status']}` | "
            f"`{row['sec_route_status']}` | `{row['companyfacts_source']}` |"
        )
    lines.extend(
        [
            "",
            "Full available history does not fabricate pre-listing bars. Short-listed names remain ineligible for the canonical seven-year comparison.",
            "The current universe is not PIT historical membership and has no delisted-return repair, so this package cannot authorize a historical portfolio test or operating-universe change.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-audit", required=True)
    parser.add_argument("--price-manifest", required=True)
    parser.add_argument("--sec-index", nargs="+", required=True)
    parser.add_argument("--companyfacts-zip", required=True)
    parser.add_argument("--companyfacts-manifest", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(build(parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
