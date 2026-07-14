#!/usr/bin/env python3
"""Collect an isolated accepted-time SEC delta for recent Run287 sessions.

The collector uses one EDGAR daily master index request per requested date to
discover relevant universe CIKs, then refreshes submissions JSON only for those
CIKs. It never mutates the canonical SEC index, scores a security, or runs a
selector, backtest, fullrun, production, or trading path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_submissions_collector import filings_from_submissions  # noqa: E402


SCHEMA_VERSION = "run287-recent-sec-accepted-delta-v1"
DEFAULT_FORMS = "8-K,8-K/A,10-Q,10-Q/A,10-K,10-K/A,6-K,6-K/A,20-F,20-F/A,40-F,40-F/A"
DAILY_INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/master.{date}.idx"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cik10(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits.zfill(10) if digits else ""


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def parse_forms(value: str) -> list[str]:
    return sorted({part.strip().upper() for part in value.replace(";", ",").split(",") if part.strip()})


def parse_dates(value: str) -> list[str]:
    dates = []
    for part in value.replace(";", ",").split(","):
        parsed = pd.to_datetime(part.strip(), errors="coerce")
        if pd.isna(parsed):
            continue
        dates.append(pd.Timestamp(parsed).strftime("%Y%m%d"))
    return sorted(set(dates))


def load_universe_tickers(path: Path) -> set[str]:
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path, columns=["ticker"])
    else:
        frame = pd.read_csv(path, usecols=["ticker"], low_memory=False)
    return {clean_ticker(value) for value in frame["ticker"].dropna() if clean_ticker(value)}


def load_identity_map(
    universe: set[str], company_tickers_path: Path, identity_index_path: Path
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    mapping: dict[str, set[str]] = {}
    company = json.loads(company_tickers_path.read_text(encoding="utf-8"))
    for item in company.values() if isinstance(company, dict) else []:
        ticker = clean_ticker(item.get("ticker"))
        cik = cik10(item.get("cik_str"))
        if ticker in universe and cik:
            mapping.setdefault(cik, set()).add(ticker)
    if identity_index_path.is_file():
        identity = pd.read_parquet(identity_index_path, columns=["ticker", "cik10"])
        for row in identity.drop_duplicates(["ticker", "cik10"]).itertuples(index=False):
            ticker = clean_ticker(row.ticker)
            cik = cik10(row.cik10)
            if ticker in universe and cik:
                mapping.setdefault(cik, set()).add(ticker)
    output = {key: sorted(value) for key, value in mapping.items()}
    mapped = {ticker for values in output.values() for ticker in values}
    return output, {
        "universe_count": len(universe),
        "mapped_ticker_count": len(mapped),
        "mapped_cik_count": len(output),
        "unmapped_tickers": sorted(universe - mapped),
    }


def parse_master_index(raw: bytes, date: str) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for line in raw.decode("latin-1").splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue
        filename = parts[4].strip()
        rows.append(
            {
                "index_date": date,
                "cik10": cik10(parts[0]),
                "company_name": parts[1].strip(),
                "form": parts[2].strip().upper(),
                "filing_date": parts[3].strip(),
                "filename": filename,
                "accession_number": Path(filename).stem,
            }
        )
    return pd.DataFrame(rows)


def default_fetcher(url: str, user_agent: str) -> bytes:
    host = "www.sec.gov" if "www.sec.gov" in url else "data.sec.gov"
    response = requests.get(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": host,
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
    universe_path = repo_path(args.universe_file)
    company_path = repo_path(args.company_tickers)
    identity_path = repo_path(args.identity_index)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    raw_index_dir = output_dir / "inputs" / "daily_index"
    raw_submissions_dir = output_dir / "inputs" / "submissions"
    raw_index_dir.mkdir(parents=True)
    raw_submissions_dir.mkdir(parents=True)

    user_agent = str(args.user_agent or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not user_agent or "@" not in user_agent or "contact@example.com" in user_agent:
        raise ValueError("a real SEC research contact user-agent is required")
    forms = parse_forms(args.forms)
    dates = parse_dates(args.dates)
    if not dates:
        raise ValueError("at least one SEC daily-index date is required")
    decision_time = pd.to_datetime(args.decision_time_utc, errors="coerce", utc=True)
    if pd.isna(decision_time):
        raise ValueError("decision_time_utc is required")
    budget = int(args.max_network_requests)
    if len(dates) > budget:
        raise ValueError("daily-index requests exceed network budget")

    universe = load_universe_tickers(universe_path)
    identity_map, identity_coverage = load_identity_map(
        universe, company_path, identity_path
    )
    index_frames: list[pd.DataFrame] = []
    raw_index_records: list[dict[str, Any]] = []
    requests_used = 0
    for date in dates:
        year = int(date[:4])
        quarter = (int(date[4:6]) - 1) // 3 + 1
        url = DAILY_INDEX_URL.format(year=year, quarter=quarter, date=date)
        raw = fetcher(url, user_agent)
        requests_used += 1
        raw_path = raw_index_dir / f"master.{date}.idx"
        raw_path.write_bytes(raw)
        raw_index_records.append({"date": date, "url": url, **fingerprint(raw_path)})
        index_frames.append(parse_master_index(raw, date))
    master = pd.concat(index_frames, ignore_index=True) if index_frames else pd.DataFrame()
    candidates = master[
        master["cik10"].isin(identity_map) & master["form"].isin(forms)
    ].copy()
    candidates["ticker"] = candidates["cik10"].map(
        lambda value: identity_map.get(str(value), [""])[0]
    )
    candidates = candidates.sort_values(
        ["index_date", "ticker", "accession_number"]
    ).drop_duplicates(["cik10", "accession_number"], keep="last")
    candidate_ciks = sorted(set(candidates["cik10"]))
    if requests_used + len(candidate_ciks) > budget:
        raise RuntimeError(
            f"candidate submissions requests exceed budget: {requests_used}+{len(candidate_ciks)}>{budget}"
        )

    submission_rows: list[pd.DataFrame] = []
    submissions_hashes: dict[str, str] = {}
    item_by_accession: dict[tuple[str, str], str] = {}
    for cik in candidate_ciks:
        raw = fetcher(SUBMISSIONS_URL.format(cik10=cik), user_agent)
        requests_used += 1
        if float(args.sleep) > 0:
            time.sleep(float(args.sleep))
        raw_path = raw_submissions_dir / f"CIK{cik}.json"
        raw_path.write_bytes(raw)
        submissions_hashes[cik] = sha256_bytes(raw)
        payload = json.loads(raw.decode("utf-8"))
        ticker = identity_map[cik][0]
        frame = filings_from_submissions(
            ticker,
            cik,
            payload,
            forms=forms,
            source="sec_submissions_recent_delta",
        )
        submission_rows.append(frame)
        recent = (payload.get("filings") or {}).get("recent") or {}
        accessions = recent.get("accessionNumber") or []
        items = recent.get("items") or []
        for index, accession in enumerate(accessions):
            item_by_accession[(cik, str(accession))] = str(
                items[index] if index < len(items) else ""
            )
    submissions = (
        pd.concat(submission_rows, ignore_index=True, sort=False)
        if submission_rows
        else pd.DataFrame()
    )
    exact = candidates.merge(
        submissions,
        on=["ticker", "cik10", "accession_number"],
        how="left",
        suffixes=("_master", ""),
        validate="one_to_one",
    )
    accepted = pd.to_datetime(exact.get("accepted_at"), errors="coerce", utc=True)
    exact["exact_acceptance"] = accepted.notna()
    exact["future_available"] = accepted.gt(decision_time)
    exact["raw_items"] = [
        item_by_accession.get((str(cik), str(accession)), "")
        for cik, accession in zip(exact["cik10"], exact["accession_number"])
    ]
    exact["item_2_02_reported_results"] = exact["raw_items"].str.replace(";", ",").str.split(",").map(
        lambda values: "2.02" in {str(value).strip() for value in values}
    )
    exact["actual_source_inputs_changed"] = False
    exact["frozen_schema_action"] = "metadata_only_no_value_change"
    exact["decision_ranking_allowed"] = False
    exact["source_hashes"] = [
        json.dumps(
            {
                "daily_index_sha256": next(
                    record["sha256"] for record in raw_index_records if record["date"] == date
                ),
                "submissions_sha256": submissions_hashes.get(str(cik), ""),
            },
            sort_keys=True,
        )
        for date, cik in zip(exact["index_date"], exact["cik10"])
    ]
    exact["pit_caveats"] = "current identity snapshot; exact acceptance; historical membership not clean"

    blockers: list[str] = []
    missing_exact = int((~exact["exact_acceptance"]).sum())
    future_rows = int(exact["future_available"].sum())
    if missing_exact:
        blockers.append(f"missing_exact_acceptance:{missing_exact}")
    if future_rows:
        blockers.append(f"future_available_rows:{future_rows}")
    expected_accessions = set(candidates["accession_number"])
    matched_accessions = set(exact.loc[exact["exact_acceptance"], "accession_number"])
    if expected_accessions != matched_accessions:
        blockers.append("daily_index_submissions_accession_mismatch")

    candidates_path = output_dir / "candidate_filings.csv"
    exact_path = output_dir / "accepted_time_delta.parquet"
    event_path = output_dir / "event_actual_audit.csv"
    fundamental_path = output_dir / "fundamental_refresh_candidates.csv"
    candidates.to_csv(candidates_path, index=False)
    exact.to_parquet(exact_path, index=False)
    event_rows = exact[exact["form"].str.match(r"^(8-K|6-K)(/A)?$")].copy()
    event_rows.to_csv(event_path, index=False)
    fundamental_rows = exact[exact["form"].str.match(r"^(10-Q|10-K|20-F|40-F)(/A)?$")].copy()
    fundamental_rows.to_csv(fundamental_path, index=False)

    status = "READY_RECENT_SEC_ACCEPTED_DELTA" if not blockers else "BLOCKED_RECENT_SEC_ACCEPTED_DELTA"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": blockers,
        "dates": dates,
        "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
        "valuation_price_cutoff_date": str(args.valuation_close_date),
        "pit_universe_label_clean": False,
        "missing_evidence_policy": "neutral",
        "research_only": True,
        "current_decision_only": True,
        "event_actual_refresh_gate_resolved": not blockers,
        "actual_feature_value_change_count": 0,
        "decision_ranking_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "network_request_budget": budget,
        "network_requests_executed": requests_used,
        "identity_coverage": identity_coverage,
        "coverage": {
            "candidate_filing_count": int(len(candidates)),
            "candidate_cik_count": int(len(candidate_ciks)),
            "exact_acceptance_count": int(exact["exact_acceptance"].sum()),
            "event_metadata_count": int(len(event_rows)),
            "fundamental_refresh_candidate_count": int(len(fundamental_rows)),
            "future_available_row_count": future_rows,
        },
        "source_inputs": {
            "universe": fingerprint(universe_path),
            "company_tickers": fingerprint(company_path),
            "identity_index": fingerprint(identity_path),
            "daily_indexes": raw_index_records,
        },
        "outputs": {
            "candidate_filings": fingerprint(candidates_path),
            "accepted_time_delta": fingerprint(exact_path),
            "event_actual_audit": fingerprint(event_path),
            "fundamental_refresh_candidates": fingerprint(fundamental_path),
        },
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-file", required=True)
    parser.add_argument("--company-tickers", default="data_raw/free/sec/company_tickers.json")
    parser.add_argument("--identity-index", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument("--dates", required=True, help="Comma-separated SEC daily-index dates.")
    parser.add_argument("--forms", default=DEFAULT_FORMS)
    parser.add_argument("--valuation-close-date", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--max-network-requests", type=int, default=64)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "READY_RECENT_SEC_ACCEPTED_DELTA" else 2


if __name__ == "__main__":
    raise SystemExit(main())
