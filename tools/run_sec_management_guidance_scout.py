#!/usr/bin/env python3
"""Run a bounded, no-email SEC management-guidance feasibility scout.

The scout locates likely numeric management-guidance passages in accepted-time
8-K/6-K submissions. It does not turn text into a signal, join returns, alter a
portfolio, or weaken the separate paid-provider consensus/guidance contract.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = "docs/run287_sec_management_guidance_scout_contract.json"
DEFAULT_SAMPLE = "outputs/run287_pit_estimate_guidance_sample_request_20260714_v2/sample_request.csv"
DEFAULT_INDEX = "data_pit/sec/sec_filings_index.csv"
DEFAULT_OUTPUT = "outputs/run287_sec_management_guidance_scout"
DEFAULT_CACHE = "data_raw/sec/guidance_scout"

GUIDANCE_PATTERN = re.compile(
    r"\b(?:guidance|outlook|we\s+(?:now\s+)?(?:expect|anticipate|forecast|project)|"
    r"(?:the\s+)?(?:company|management)\s+(?:now\s+)?(?:expects|anticipates|forecasts|projects))\b",
    re.IGNORECASE,
)
STRONG_GUIDANCE_PATTERN = re.compile(
    GUIDANCE_PATTERN.pattern,
    GUIDANCE_PATTERN.flags,
)
FUTURE_PERIOD_PATTERN = re.compile(
    r"\b(?:fiscal|fy\s*['’]?\d{2,4}|quarter|full[- ]year|year ending|next year|q[1-4]|20\d{2})\b",
    re.IGNORECASE,
)
METRIC_PATTERNS = {
    "eps": re.compile(r"\b(?:adjusted\s+)?(?:diluted\s+)?(?:eps|earnings per share)\b", re.IGNORECASE),
    "revenue": re.compile(r"\b(?:net\s+)?revenue(?:s)?\b", re.IGNORECASE),
    "sales": re.compile(r"\b(?:net\s+)?sales\b", re.IGNORECASE),
    "margin": re.compile(r"\b(?:gross|operating|ebitda|profit)\s+margin\b", re.IGNORECASE),
    "ebitda": re.compile(r"\b(?:adjusted\s+)?ebitda\b", re.IGNORECASE),
    "capex": re.compile(r"\b(?:capex|capital expenditures?)\b", re.IGNORECASE),
}
NUMBER_PATTERN = re.compile(
    r"(?:[$€£]\s*)?[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|million|billion|thousand|m|bn|b)?",
    re.IGNORECASE,
)
ALLOWED_COLUMNS = [
    "ticker",
    "cik10",
    "accession_number",
    "form_type",
    "accepted_at",
    "available_from",
    "document_type",
    "metrics",
    "candidate_id",
    "source_url",
    "source_sha256",
    "snippet",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def load_contract(path: str | Path) -> dict[str, Any]:
    return json.loads(repo_path(path).read_text(encoding="utf-8"))


def select_tickers(sample: pd.DataFrame, limit: int) -> pd.DataFrame:
    frame = sample.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["is_delisted_bool"] = frame.get("is_delisted", False).map(normalize_bool)
    frame["is_adr_bool"] = frame.get("is_adr_global_listing", False).map(normalize_bool)
    frame = frame[frame["ticker"].ne("") & frame["ticker"].ne("NAN") & ~frame["is_delisted_bool"]]
    frame = frame.drop_duplicates("ticker", keep="first")
    adr = frame[frame["is_adr_bool"]]
    domestic = frame[~frame["is_adr_bool"]]
    out = pd.concat([adr, domestic], ignore_index=True)
    if limit > 0:
        out = out.head(limit)
    return out


def load_filings(paths: Iterable[str | Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for value in paths:
        path = repo_path(value)
        if not path.exists():
            continue
        frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)
        frame["index_source_file"] = str(path)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    for column in ["ticker", "cik10", "accession_number", "form_type", "accepted_at", "filing_date"]:
        if column not in out:
            out[column] = ""
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["form_type"] = out["form_type"].astype(str).str.upper().str.strip()
    out["accession_number"] = out["accession_number"].astype(str).str.strip()
    out = out.drop_duplicates(["ticker", "accession_number"], keep="last")
    return out


def complete_submission_url(cik: Any, accession: str) -> str:
    digits = re.sub(r"\D", "", str(cik or ""))
    acc = str(accession or "").strip()
    if not digits or not acc:
        return ""
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(digits)}/"
        f"{acc.replace('-', '')}/{acc}.txt"
    )


def cache_file(cache_dir: Path, ticker: str, accession: str) -> Path:
    return cache_dir / ticker / f"{accession.replace('-', '')}.txt"


def fetch_submission(
    *,
    url: str,
    cache_path: Path,
    user_agent: str,
    offline: bool,
    sleep_s: float,
) -> tuple[bytes | None, str]:
    if cache_path.exists():
        return cache_path.read_bytes(), "cached"
    if offline:
        return None, "offline_cache_miss"
    if not user_agent.strip():
        return None, "blocked_missing_sec_user_agent"
    if sleep_s > 0:
        time.sleep(float(sleep_s))
    response = requests.get(
        url,
        headers={
            "User-Agent": user_agent.strip(),
            "Accept-Encoding": "gzip, deflate",
        },
        timeout=45,
    )
    if response.status_code != 200:
        return None, f"http_{response.status_code}"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(response.content)
    return response.content, "downloaded"


def sgml_documents(raw_text: str) -> list[tuple[str, str]]:
    blocks = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", raw_text, flags=re.IGNORECASE | re.DOTALL)
    if not blocks:
        return [("UNKNOWN", raw_text)]
    out: list[tuple[str, str]] = []
    for block in blocks:
        match = re.search(r"<TYPE>\s*([^\r\n<]+)", block, flags=re.IGNORECASE)
        doc_type = match.group(1).strip().upper() if match else "UNKNOWN"
        text_match = re.search(r"<TEXT>(.*)", block, flags=re.IGNORECASE | re.DOTALL)
        out.append((doc_type, text_match.group(1) if text_match else block))
    return out


def plain_text(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def guidance_candidates(text: str, *, max_candidates: int = 3) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for match in GUIDANCE_PATTERN.finditer(text):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 520)
        window = text[start:end]
        metrics = sorted(name for name, pattern in METRIC_PATTERNS.items() if pattern.search(window))
        if not metrics or not NUMBER_PATTERN.search(window) or not FUTURE_PERIOD_PATTERN.search(window):
            continue
        boilerplate = bool(re.search(r"forward-looking statements?", window, flags=re.IGNORECASE))
        if boilerplate and not STRONG_GUIDANCE_PATTERN.search(window):
            continue
        snippet = window.strip()[:900]
        candidates.append({"metrics": "|".join(metrics), "snippet": snippet})
        if len(candidates) >= max_candidates:
            break
    return candidates


def aggregate_candidate_filings(candidates: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "ticker",
        "cik10",
        "accession_number",
        "form_type",
        "accepted_at",
        "available_from",
        "document_types",
        "metrics",
        "candidate_row_count",
        "source_url",
        "source_sha256",
    ]
    if candidates.empty:
        return pd.DataFrame(columns=columns)

    def joined_tokens(values: pd.Series) -> str:
        tokens: set[str] = set()
        for value in values.dropna().astype(str):
            tokens.update(part for part in value.split("|") if part)
        return "|".join(sorted(tokens))

    grouped = candidates.groupby(["ticker", "accession_number"], sort=True, as_index=False).agg(
        cik10=("cik10", "first"),
        form_type=("form_type", "first"),
        accepted_at=("accepted_at", "first"),
        available_from=("available_from", "first"),
        document_types=("document_type", joined_tokens),
        metrics=("metrics", joined_tokens),
        candidate_row_count=("candidate_id", "size"),
        source_url=("source_url", "first"),
        source_sha256=("source_sha256", "first"),
    )
    return grouped[columns]


def prepare_scan_rows(
    filings: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    allowed_forms: set[str],
    start: str,
    end: str,
    max_filings_per_ticker: int,
) -> pd.DataFrame:
    if filings.empty:
        return filings.copy()
    out = filings[filings["ticker"].isin(set(selected["ticker"])) & filings["form_type"].isin(allowed_forms)].copy()
    out["accepted_ts"] = pd.to_datetime(out["accepted_at"], errors="coerce", utc=True)
    out["filing_ts"] = pd.to_datetime(out["filing_date"], errors="coerce", utc=True)
    effective = out["accepted_ts"].fillna(out["filing_ts"])
    start_ts = pd.to_datetime(start, utc=True)
    end_ts = pd.to_datetime(end, utc=True) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    out = out[effective.between(start_ts, end_ts, inclusive="both")]
    out = out.sort_values(["ticker", "accepted_ts", "accession_number"], ascending=[True, False, False])
    if max_filings_per_ticker > 0:
        out = out.groupby("ticker", sort=False, as_index=False).head(max_filings_per_ticker)
    return out.reset_index(drop=True)


def write_report(summary: dict[str, Any], coverage: pd.DataFrame, output_dir: Path) -> None:
    lines = [
        "# Run287 no-email SEC management-guidance scout",
        "",
        f"- Status: `{summary['status']}`",
        f"- Selected tickers: `{summary['selected_ticker_count']}`",
        f"- Indexed tickers: `{summary['indexed_ticker_count']}`",
        f"- Indexed ADR/global tickers: `{summary['indexed_adr_count']}`",
        f"- Filing downloads: `{summary['download_success_count']}/{summary['download_attempt_count']}`",
        f"- Exact acceptance ratio: `{summary['exact_acceptance_ratio']:.2%}`",
        f"- Guidance candidate filings: `{summary['candidate_filing_count']}` across `{summary['candidate_ticker_count']}` tickers",
        f"- Guidance candidate passage rows: `{summary['candidate_count']}`",
        "",
        "This is document discovery only. Candidate text still requires manual schema review; it is not an alpha signal.",
        "It does not replace historical analyst consensus, satisfy the existing consensus/guidance pair gate, join returns, or change a portfolio.",
        "",
        "## Coverage",
        "",
        "| Ticker | ADR/global | Indexed filings | Scanned | Downloads | Candidate filings | Candidate rows | State |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for _, row in coverage.iterrows():
        lines.append(
            f"| {row['ticker']} | {bool(row['is_adr_global_listing'])} | {int(row['indexed_filing_count'])} | "
            f"{int(row['scanned_filing_count'])} | {int(row['download_success_count'])} | "
            f"{int(row['candidate_filing_count'])} | {int(row['candidate_count'])} | {row['coverage_state']} |"
        )
    output_dir.joinpath("report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(args.contract)
    sample = pd.read_csv(repo_path(args.sample_request), low_memory=False)
    selected = select_tickers(sample, int(args.ticker_limit))
    filings = load_filings(args.filings_index)
    allowed_forms = {str(x).upper() for x in contract["source"]["allowed_forms"]}
    allowed_doc_types = {str(x).upper() for x in contract["source"]["allowed_document_types"]}
    scan_rows = prepare_scan_rows(
        filings,
        selected,
        allowed_forms=allowed_forms,
        start=args.history_start,
        end=args.history_end,
        max_filings_per_ticker=int(args.max_filings_per_ticker),
    )

    output_dir = repo_path(args.output_dir)
    cache_dir = repo_path(args.cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    user_agent = str(args.user_agent or os.environ.get("SEC_USER_AGENT") or "")
    candidate_rows: list[dict[str, Any]] = []
    download_rows: list[dict[str, Any]] = []

    for _, row in scan_rows.iterrows():
        ticker = str(row["ticker"])
        accession = str(row["accession_number"])
        url = complete_submission_url(row.get("cik10"), accession)
        raw, state = fetch_submission(
            url=url,
            cache_path=cache_file(cache_dir, ticker, accession),
            user_agent=user_agent,
            offline=bool(args.offline),
            sleep_s=float(args.sleep),
        )
        download_rows.append(
            {
                "ticker": ticker,
                "accession_number": accession,
                "accepted_at": row.get("accepted_at", ""),
                "source_url": url,
                "download_state": state,
                "download_success": raw is not None,
            }
        )
        if raw is None:
            continue
        raw_hash = sha256_bytes(raw)
        decoded = raw.decode("utf-8", errors="replace")
        for document_type, document in sgml_documents(decoded):
            if document_type not in allowed_doc_types:
                continue
            for item in guidance_candidates(plain_text(document)):
                candidate_key = "|".join([ticker, accession, document_type, item["metrics"], item["snippet"]])
                candidate_rows.append(
                    {
                        "ticker": ticker,
                        "cik10": str(row.get("cik10", "")),
                        "accession_number": accession,
                        "form_type": str(row.get("form_type", "")),
                        "accepted_at": str(row.get("accepted_at", "")),
                        "available_from": str(row.get("accepted_at", "")),
                        "document_type": document_type,
                        "metrics": item["metrics"],
                        "candidate_id": hashlib.sha256(candidate_key.encode("utf-8")).hexdigest(),
                        "source_url": url,
                        "source_sha256": raw_hash,
                        "snippet": item["snippet"],
                    }
                )

    candidates = pd.DataFrame(candidate_rows, columns=ALLOWED_COLUMNS).drop_duplicates("candidate_id")
    candidate_filings = aggregate_candidate_filings(candidates)
    downloads = pd.DataFrame(download_rows)
    selected_tickers = selected["ticker"].tolist()
    indexed = set(scan_rows["ticker"].tolist()) if not scan_rows.empty else set()
    candidate_counts = candidates.groupby("ticker").size().to_dict() if not candidates.empty else {}
    candidate_filing_counts = (
        candidate_filings.groupby("ticker").size().to_dict() if not candidate_filings.empty else {}
    )
    scan_counts = scan_rows.groupby("ticker").size().to_dict() if not scan_rows.empty else {}
    download_success_counts = (
        downloads[downloads["download_success"]].groupby("ticker").size().to_dict() if not downloads.empty else {}
    )
    coverage_rows: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        ticker = row["ticker"]
        indexed_count = int(scan_counts.get(ticker, 0))
        success_count = int(download_success_counts.get(ticker, 0))
        candidate_count = int(candidate_counts.get(ticker, 0))
        candidate_filing_count = int(candidate_filing_counts.get(ticker, 0))
        if indexed_count == 0:
            state = "NO_ELIGIBLE_SEC_INDEX"
        elif success_count == 0:
            state = "DOWNLOAD_BLOCKED"
        elif candidate_count == 0:
            state = "NO_NUMERIC_GUIDANCE_CANDIDATE"
        else:
            state = "CANDIDATE_REQUIRES_MANUAL_REVIEW"
        coverage_rows.append(
            {
                "ticker": ticker,
                "is_adr_global_listing": bool(row["is_adr_bool"]),
                "indexed_filing_count": indexed_count,
                "scanned_filing_count": indexed_count,
                "download_success_count": success_count,
                "candidate_count": candidate_count,
                "candidate_filing_count": candidate_filing_count,
                "coverage_state": state,
            }
        )
    coverage = pd.DataFrame(coverage_rows)

    attempted = int(len(downloads))
    succeeded = int(downloads["download_success"].sum()) if attempted else 0
    exact = int(scan_rows["accepted_ts"].notna().sum()) if not scan_rows.empty else 0
    exact_ratio = float(exact / len(scan_rows)) if len(scan_rows) else 0.0
    success_ratio = float(succeeded / attempted) if attempted else 0.0
    indexed_adr_count = int(coverage.loc[coverage["is_adr_global_listing"], "indexed_filing_count"].gt(0).sum())
    thresholds = contract["bounded_scout"]
    if len(scan_rows) and exact_ratio < float(thresholds["minimum_exact_acceptance_ratio"]):
        status = "BLOCKED_PIT"
    elif attempted and success_ratio < float(thresholds["minimum_download_success_ratio"]):
        status = "BLOCKED_DOWNLOAD"
    elif indexed_adr_count < int(thresholds["minimum_indexed_adr_count"]):
        status = "UNDER_COVERED_ADR"
    elif candidates.empty:
        status = "NO_GUIDANCE_CANDIDATES"
    else:
        status = "READY_FOR_MANUAL_SCHEMA_REVIEW"

    summary = {
        "schema_version": contract["schema_version"],
        "status": status,
        "research_key": contract["research_key"],
        "history_start": args.history_start,
        "history_end": args.history_end,
        "selected_ticker_count": int(len(selected)),
        "selected_tickers": selected_tickers,
        "indexed_ticker_count": int(len(indexed)),
        "indexed_adr_count": indexed_adr_count,
        "scan_filing_count": int(len(scan_rows)),
        "download_attempt_count": attempted,
        "download_success_count": succeeded,
        "download_success_ratio": success_ratio,
        "exact_acceptance_count": exact,
        "exact_acceptance_ratio": exact_ratio,
        "candidate_count": int(len(candidates)),
        "candidate_filing_count": int(len(candidate_filings)),
        "candidate_ticker_count": int(candidates["ticker"].nunique()) if not candidates.empty else 0,
        "candidate_tickers": sorted(candidates["ticker"].unique().tolist()) if not candidates.empty else [],
        "provider_email_required": False,
        "api_key_required": False,
        "manual_schema_review_required": True,
        "historical_consensus_requirement_satisfied": False,
        "existing_provider_gate_replaced": False,
        "return_join_allowed": False,
        "portfolio_ab_allowed": False,
        "portfolio_mutation_allowed": False,
        "fullrun_allowed": False,
        "production_allowed": False,
        "live_trading_allowed": False,
    }
    candidates.to_csv(output_dir / "guidance_candidates.csv", index=False)
    candidate_filings.to_csv(output_dir / "candidate_filings.csv", index=False)
    coverage.to_csv(output_dir / "coverage_by_ticker.csv", index=False)
    downloads.to_csv(output_dir / "download_log.csv", index=False)
    output_dir.joinpath("summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_report(summary, coverage, output_dir)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--sample-request", default=DEFAULT_SAMPLE)
    parser.add_argument("--filings-index", action="append", default=[])
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE)
    parser.add_argument("--ticker-limit", type=int, default=10)
    parser.add_argument("--max-filings-per-ticker", type=int, default=8)
    parser.add_argument("--history-start", default="2019-06-03")
    parser.add_argument("--history-end", default="2026-07-10")
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not args.filings_index:
        args.filings_index = [DEFAULT_INDEX]
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
