#!/usr/bin/env python3
"""Audit per-ticker coverage across the durable free historical data lake.

This tool is read-only. It answers: for the current/proxy universe, which
tickers have SEC actuals, listing lifecycle reference rows, earnings-calendar
history, and forward estimate snapshots? It does not fetch data and does not
promote any proxy source to production.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "free-historical-data-coverage-v1"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = text.replace(".", "-")
    text = re.sub(r"[^A-Z0-9-]", "", text)
    return text


def read_ticker_csv(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        field = "ticker" if "ticker" in (reader.fieldnames or []) else (reader.fieldnames or [""])[0]
        return [t for t in (normalize_ticker(row.get(field)) for row in reader) if t]


def read_tickers_from_frame(path: Path, candidates: list[str]) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path, low_memory=False)
    cols = {str(c).lower(): c for c in frame.columns}
    ticker_col = next((cols[c] for c in candidates if c in cols), None)
    if ticker_col is None:
        return pd.DataFrame()
    out = pd.DataFrame({"ticker": frame[ticker_col].map(normalize_ticker)})
    for cik_name in ["cik10", "cik", "cik_str"]:
        if cik_name in cols:
            out["cik10"] = frame[cols[cik_name]].map(normalize_cik)
            break
    return out[out["ticker"].ne("")]


def normalize_cik(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = re.sub(r"\D", "", str(value))
    return text.zfill(10) if text else ""


def load_universe(args: argparse.Namespace) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if args.universe_file:
        path = repo_path(args.universe_file)
        tickers = read_ticker_csv(path)
        frames.append(pd.DataFrame({"ticker": tickers, "universe_source": path.as_posix()}))

    latest = repo_path(args.latest_run)
    for rel in [
        "scored_latest.csv",
        "reports/main_monthly_weights.csv",
        "reports/concentrated_strategy_holdings.csv",
        "reports/candidate_replay_book.csv",
    ]:
        frame = read_tickers_from_frame(latest / rel, ["ticker", "symbol"])
        if not frame.empty:
            frame["universe_source"] = (latest / rel).as_posix()
            frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["ticker", "cik10", "universe_source"])
    out = pd.concat(frames, ignore_index=True)
    if "cik10" not in out.columns:
        out["cik10"] = ""
    out["cik10"] = out["cik10"].fillna("").map(normalize_cik)
    out = out.sort_values(["ticker", "cik10"]).drop_duplicates("ticker", keep="last")
    return out[["ticker", "cik10", "universe_source"]]


def load_parquet_tickers(path: Path, ticker_col: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return set()
    if ticker_col not in frame.columns:
        return set()
    return {normalize_ticker(x) for x in frame[ticker_col].dropna().tolist() if normalize_ticker(x)}


def load_forward_estimate_tickers(snapshot_dir: Path) -> tuple[set[str], set[str], int]:
    all_seen: set[str] = set()
    has_estimate: set[str] = set()
    files = sorted(snapshot_dir.glob("estimates_*.parquet")) if snapshot_dir.exists() else []
    for path in files:
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if "ticker" not in frame.columns:
            continue
        tickers = {normalize_ticker(x) for x in frame["ticker"].dropna().tolist() if normalize_ticker(x)}
        all_seen.update(tickers)
        if "has_forward_estimate" in frame.columns:
            flag = pd.to_numeric(frame["has_forward_estimate"], errors="coerce").fillna(0).gt(0)
            has_estimate.update({normalize_ticker(x) for x in frame.loc[flag, "ticker"].dropna().tolist() if normalize_ticker(x)})
    return all_seen, has_estimate, len(files)


def companyfacts_members(zip_path: Path) -> set[str]:
    if not zip_path.exists():
        return set()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.namelist()
    except Exception:
        return set()
    out: set[str] = set()
    for name in members:
        match = re.search(r"CIK(\d{10})\.json$", name)
        if match:
            out.add(match.group(1))
    return out


def pct(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Free Historical Data Coverage Audit",
        "",
        f"Generated UTC: `{summary['generated_at_utc']}`",
        f"Status: `{summary['status']}`",
        f"Universe tickers: `{summary['universe_ticker_count']}`",
        "",
        "## Coverage",
        "",
    ]
    for name, item in summary["coverage"].items():
        lines.append(f"- `{name}`: {item['covered_ticker_count']}/{summary['universe_ticker_count']} ({item['coverage_ratio']:.2%})")
    lines += [
        "",
        "## Usage Rules",
        "",
        "- SEC actuals require accepted/available timestamps when materialized into features.",
        "- Alpha Vantage listing status is lifecycle reference data, not PIT Russell 1000 membership.",
        "- FMP earnings calendar history is a vendor historical snapshot, not analyst revision history.",
        "- Forward estimate snapshots are usable only from their collection dates onward.",
        "- Missing coverage must remain missing or neutral; do not impute positive alpha.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(args: argparse.Namespace) -> dict[str, Any]:
    universe = load_universe(args)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if universe.empty:
        summary = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked_no_universe",
            "universe_ticker_count": 0,
            "coverage": {},
            "known_gaps": ["No universe file or latest-run ticker source was available."],
        }
        write_json(output_dir / "summary.json", summary)
        write_report(output_dir / "report.md", summary)
        return summary

    sec_members = companyfacts_members(repo_path(args.companyfacts_zip))
    listing = load_parquet_tickers(repo_path(args.listing_status), "symbol")
    earnings_calendar = load_parquet_tickers(repo_path(args.earnings_calendar), "ticker")
    estimate_seen, estimate_has, estimate_file_count = load_forward_estimate_tickers(repo_path(args.estimate_snapshot_dir))

    rows: list[dict[str, Any]] = []
    for row in universe.to_dict("records"):
        ticker = normalize_ticker(row.get("ticker"))
        cik10 = normalize_cik(row.get("cik10"))
        sec_present = bool(cik10 and cik10 in sec_members)
        if sec_present:
            sec_missing_reason = ""
        elif not cik10:
            sec_missing_reason = "missing_cik10_mapping"
        else:
            sec_missing_reason = "cik_not_in_companyfacts_zip"
        rows.append(
            {
                "ticker": ticker,
                "cik10": cik10,
                "universe_source": row.get("universe_source", ""),
                "sec_companyfacts_present": sec_present,
                "sec_companyfacts_missing_reason": sec_missing_reason,
                "av_listing_status_present": ticker in listing,
                "fmp_earnings_calendar_present": ticker in earnings_calendar,
                "forward_estimate_seen": ticker in estimate_seen,
                "forward_estimate_has_estimate": ticker in estimate_has,
            }
        )
    coverage_frame = pd.DataFrame(rows).sort_values("ticker")
    coverage_csv = output_dir / "universe_coverage.csv"
    coverage_frame.to_csv(coverage_csv, index=False)
    total = int(len(coverage_frame))

    def coverage_item(column: str, *, label: str, pit_usage_label: str) -> dict[str, Any]:
        covered = int(coverage_frame[column].astype(bool).sum()) if column in coverage_frame.columns else 0
        return {
            "label": label,
            "pit_usage_label": pit_usage_label,
            "covered_ticker_count": covered,
            "missing_ticker_count": total - covered,
            "coverage_ratio": pct(covered, total),
        }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "ok",
        "production_promotion_allowed": False,
        "pit_universe_label_clean": False,
        "universe_ticker_count": total,
        "coverage_csv": coverage_csv.as_posix(),
        "estimate_snapshot_file_count": estimate_file_count,
        "sec_companyfacts_missing_reason_counts": (
            coverage_frame.loc[~coverage_frame["sec_companyfacts_present"].astype(bool), "sec_companyfacts_missing_reason"]
            .value_counts(dropna=False)
            .to_dict()
        ),
        "coverage": {
            "sec_companyfacts": coverage_item(
                "sec_companyfacts_present",
                label="SEC actual filings by CIK",
                pit_usage_label="actual_filings_require_accepted_timestamp",
            ),
            "av_listing_status": coverage_item(
                "av_listing_status_present",
                label="active/delisted listing lifecycle",
                pit_usage_label="reference_lifecycle_proxy_not_index_membership",
            ),
            "fmp_earnings_calendar_history": coverage_item(
                "fmp_earnings_calendar_present",
                label="earnings calendar vendor history snapshot",
                pit_usage_label="vendor_historical_snapshot_not_revision_history",
            ),
            "forward_estimate_seen": coverage_item(
                "forward_estimate_seen",
                label="forward estimate archive attempted ticker",
                pit_usage_label="forward_only_snapshot",
            ),
            "forward_estimate_has_estimate": coverage_item(
                "forward_estimate_has_estimate",
                label="forward estimate archive true estimate coverage",
                pit_usage_label="forward_only_snapshot",
            ),
        },
        "known_gaps": [
            "Historical Russell 1000 membership remains proxy until PIT constituents are available.",
            "FMP earnings calendar history is not a PIT estimate revision feed.",
            "Forward estimates begin only when snapshots were collected.",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    write_report(output_dir / "report.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-file", default="")
    parser.add_argument("--latest-run", default="cloud_results/full_rebuild/latest_global_alpha_universe")
    parser.add_argument("--companyfacts-zip", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--listing-status", default="data_pit/free/av_listing_status.parquet")
    parser.add_argument("--earnings-calendar", default="data_pit/events/earnings_calendar_history.parquet")
    parser.add_argument("--estimate-snapshot-dir", default="data_pit/events/earnings_estimates")
    parser.add_argument("--output-dir", default="outputs/free_historical_data_coverage")
    return parser.parse_args()


def main() -> int:
    summary = audit(parse_args())
    return 0 if summary.get("status") in {"ok", "blocked_no_universe"} else 1


if __name__ == "__main__":
    sys.exit(main())
