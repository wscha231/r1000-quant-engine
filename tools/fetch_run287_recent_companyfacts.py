#!/usr/bin/env python3
"""Fetch Companyfacts only for exact recent statement candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def verify_output(manifest_path: Path, manifest: dict[str, Any], key: str) -> Path:
    record = (manifest.get("outputs") or {}).get(key) or {}
    path = Path(str(record.get("path") or ""))
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file() or sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"manifest output hash mismatch: {key}")
    return path


def default_fetcher(url: str, user_agent: str) -> bytes:
    response = requests.get(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def build(
    args: argparse.Namespace,
    *,
    fetcher: Callable[[str, str], bytes] = default_fetcher,
) -> dict[str, Any]:
    delta_manifest_path = repo_path(args.delta_manifest)
    canonical_index_path = repo_path(args.canonical_index)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    companyfacts_dir = output_dir / "companyfacts"
    companyfacts_dir.mkdir()
    delta_manifest = json.loads(delta_manifest_path.read_text(encoding="utf-8"))
    if delta_manifest.get("status") != "READY_RECENT_SEC_ACCEPTED_DELTA":
        raise ValueError("recent SEC delta is not ready")
    delta_path = verify_output(delta_manifest_path, delta_manifest, "accepted_time_delta")
    delta = pd.read_parquet(delta_path)
    statements = delta[
        delta["form"].astype(str).str.match(r"^(10-Q|10-K|20-F|40-F)(/A)?$")
        & delta["exact_acceptance"].astype(bool)
    ].copy()
    ciks = sorted(set(statements["cik10"].astype(str).str.zfill(10)))
    if len(ciks) > int(args.max_network_requests):
        raise RuntimeError("Companyfacts candidates exceed network request budget")
    user_agent = str(args.user_agent or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not user_agent or "@" not in user_agent or "contact@example.com" in user_agent:
        raise ValueError("a real SEC research contact user-agent is required")
    raw_records: list[dict[str, Any]] = []
    for cik in ciks:
        raw = fetcher(COMPANYFACTS_URL.format(cik10=cik), user_agent)
        payload = json.loads(raw.decode("utf-8"))
        returned_cik = str(payload.get("cik") or "").zfill(10)
        if returned_cik != cik:
            raise ValueError(f"Companyfacts CIK mismatch: {returned_cik}!={cik}")
        path = companyfacts_dir / f"CIK{cik}.json"
        path.write_bytes(raw)
        raw_records.append({"cik10": cik, "url": COMPANYFACTS_URL.format(cik10=cik), **fingerprint(path)})

    canonical = pd.read_parquet(canonical_index_path)
    delta_index = pd.DataFrame(
        {
            "ticker": statements["ticker"],
            "cik10": statements["cik10"],
            "accession_number": statements["accession_number"],
            "form_type": statements["form"],
            "filing_date": statements["filing_date"],
            "accepted_at": statements["accepted_at"],
            "available_from": statements["available_from"],
            "period_of_report": statements["period_of_report"],
            "primary_document": statements["primary_document"],
            "filing_url": statements["filing_url"],
            "source": "sec_daily_index_exact_delta",
            "download_status": "indexed",
            "parse_status": "pending",
        }
    )
    combined = pd.concat([canonical, delta_index], ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["ticker", "accepted_at", "accession_number"]
    ).drop_duplicates(["ticker", "accession_number"], keep="last")
    combined_path = output_dir / "combined_sec_filings_index.parquet"
    combined.to_parquet(combined_path, index=False)
    future = int(
        (
            pd.to_datetime(delta_index["available_from"], errors="coerce", utc=True)
            > pd.to_datetime(args.decision_time_utc, utc=True)
        ).sum()
    )
    blockers = [] if not future and len(raw_records) == len(ciks) else ["Companyfacts delta contract failed"]
    payload = {
        "status": "READY_RECENT_COMPANYFACTS_DELTA" if not blockers else "BLOCKED_RECENT_COMPANYFACTS_DELTA",
        "blockers": blockers,
        "decision_time_utc": str(args.decision_time_utc),
        "research_only": True,
        "current_decision_only": True,
        "pit_universe_label_clean": False,
        "network_request_budget": int(args.max_network_requests),
        "network_requests_executed": len(ciks),
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "coverage": {
            "statement_candidate_count": int(len(statements)),
            "companyfacts_cik_count": len(ciks),
            "future_available_row_count": future,
        },
        "source_inputs": {
            "delta_manifest": fingerprint(delta_manifest_path),
            "accepted_time_delta": fingerprint(delta_path),
            "canonical_index": fingerprint(canonical_index_path),
        },
        "outputs": {
            "companyfacts_dir": str(companyfacts_dir.resolve()),
            "companyfacts_files": raw_records,
            "combined_sec_filings_index": fingerprint(combined_path),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delta-manifest", required=True)
    parser.add_argument("--canonical-index", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--max-network-requests", type=int, default=8)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "READY_RECENT_COMPANYFACTS_DELTA" else 2


if __name__ == "__main__":
    raise SystemExit(main())
