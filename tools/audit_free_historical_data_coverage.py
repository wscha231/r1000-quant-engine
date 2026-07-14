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
SCHEMA_VERSION = "free-historical-data-coverage-v2"
NON_EQUITY_PLACEHOLDERS = {"CASH", "__CASH__"}


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
        frame = pd.read_csv(path, low_memory=False, dtype=str)
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
    text = str(value).strip()
    integer_like = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    digits = integer_like.group(1) if integer_like else re.sub(r"\D", "", text)
    return digits.zfill(10) if digits else ""


def load_universe(args: argparse.Namespace) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if args.universe_file:
        path = repo_path(args.universe_file)
        frame = read_tickers_from_frame(path, ["ticker", "symbol"])
        if not frame.empty:
            frame["universe_source"] = path.as_posix()
            frames.append(frame)

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


def read_reference_table(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False, dtype=str)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return pd.DataFrame()
    items = payload.values() if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    rows = []
    for item in items:
        if isinstance(item, dict):
            rows.append(
                {
                    "ticker": item.get("ticker", ""),
                    "cik10": item.get("cik10", item.get("cik_str", item.get("cik", ""))),
                    "company_name": item.get("company_name", item.get("title", "")),
                }
            )
    return pd.DataFrame(rows)


def load_sec_ticker_map(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    reference = read_reference_table(path)
    if reference.empty or "ticker" not in reference.columns:
        return pd.DataFrame(columns=["ticker", "reference_cik10", "cik_candidate_count"]), {
            "status": "missing",
            "reference_path": path.as_posix(),
        }
    cik_col = next((c for c in ["cik10", "cik_str", "cik"] if c in reference.columns), None)
    if cik_col is None:
        return pd.DataFrame(columns=["ticker", "reference_cik10", "cik_candidate_count"]), {
            "status": "missing_cik_column",
            "reference_path": path.as_posix(),
        }
    d = reference.copy()
    d["ticker"] = d["ticker"].map(normalize_ticker)
    d["reference_cik10"] = d[cik_col].map(normalize_cik)
    d = d[d["ticker"].ne("") & d["reference_cik10"].ne("")].drop_duplicates(
        ["ticker", "reference_cik10"], keep="first"
    )
    counts = d.groupby("ticker")["reference_cik10"].nunique().rename("cik_candidate_count")
    unique = d.merge(counts, on="ticker", how="left")
    unique = unique[unique["cik_candidate_count"].eq(1)].drop_duplicates("ticker", keep="first")
    mapping = unique[["ticker", "reference_cik10", "cik_candidate_count"]]
    source_url = next((str(x) for x in d.get("source_url", pd.Series(dtype=str)).dropna().unique() if str(x)), "")
    source_sha256 = next((str(x) for x in d.get("source_sha256", pd.Series(dtype=str)).dropna().unique() if str(x)), "")
    available_from = next((str(x) for x in d.get("available_from", pd.Series(dtype=str)).dropna().unique() if str(x)), "")
    ingested_at_utc = next((str(x) for x in d.get("ingested_at_utc", pd.Series(dtype=str)).dropna().unique() if str(x)), "")
    metadata = {
        "status": "available",
        "reference_path": path.as_posix(),
        "row_count": int(len(d)),
        "unique_ticker_count": int(d["ticker"].nunique()),
        "ambiguous_ticker_count": int(counts.gt(1).sum()),
        "source_url": source_url,
        "source_sha256": source_sha256,
        "available_from": available_from,
        "ingested_at_utc": ingested_at_utc,
        "pit_usage_label": "reference_identity_snapshot_not_index_membership",
    }
    ambiguous = counts[counts.gt(1)].reset_index()
    if not ambiguous.empty:
        metadata["ambiguous_tickers"] = ambiguous["ticker"].astype(str).tolist()
    mapping = pd.concat(
        [
            mapping,
            ambiguous.assign(reference_cik10="")[["ticker", "reference_cik10", "cik_candidate_count"]],
        ],
        ignore_index=True,
    )
    return mapping.sort_values("ticker").reset_index(drop=True), metadata


def apply_sec_ticker_map(
    universe: pd.DataFrame,
    mapping: pd.DataFrame,
    reference_metadata: dict[str, Any],
) -> pd.DataFrame:
    out = universe.copy()
    out["input_cik10"] = out["cik10"].map(normalize_cik)
    if mapping.empty:
        out["reference_cik10"] = ""
        out["cik_candidate_count"] = 0
    else:
        out = out.merge(mapping, on="ticker", how="left")
        out["reference_cik10"] = out["reference_cik10"].fillna("").map(normalize_cik)
        out["cik_candidate_count"] = pd.to_numeric(out["cik_candidate_count"], errors="coerce").fillna(0).astype(int)
    out["is_equity_issuer"] = ~out["ticker"].isin(NON_EQUITY_PLACEHOLDERS)
    has_input = out["input_cik10"].ne("")
    has_unique_reference = out["cik_candidate_count"].eq(1) & out["reference_cik10"].ne("")
    conflict = has_input & has_unique_reference & out["input_cik10"].ne(out["reference_cik10"])
    out["cik10"] = out["input_cik10"]
    fill = (~has_input) & has_unique_reference & out["is_equity_issuer"]
    out.loc[fill, "cik10"] = out.loc[fill, "reference_cik10"]
    out["cik_mapping_status"] = "ticker_not_in_sec_reference"
    out.loc[out["cik_candidate_count"].gt(1), "cik_mapping_status"] = "ambiguous_sec_ticker_reference"
    out.loc[fill, "cik_mapping_status"] = "resolved_sec_company_tickers"
    out.loc[has_input, "cik_mapping_status"] = "existing_universe_cik"
    out.loc[conflict, "cik_mapping_status"] = "existing_cik_conflict_sec_reference_preserved"
    out.loc[~out["is_equity_issuer"], "cik_mapping_status"] = "non_equity_placeholder"
    if reference_metadata.get("status") != "available":
        out.loc[(~has_input) & out["is_equity_issuer"], "cik_mapping_status"] = "sec_ticker_reference_unavailable"
    out["cik_mapping_source"] = ""
    out.loc[fill, "cik_mapping_source"] = "sec_company_tickers"
    out.loc[has_input, "cik_mapping_source"] = "universe_input"
    return out


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
    cik = summary.get("sec_cik_mapping", {})
    lines += [
        "",
        "## SEC Ticker/CIK Mapping",
        "",
        f"- Input CIK coverage: `{cik.get('before_mapped_ticker_count', 0)}/{summary.get('universe_ticker_count', 0)}`",
        f"- Filled from SEC reference: `{cik.get('filled_from_reference_count', 0)}`",
        f"- Final CIK coverage: `{cik.get('after_mapped_ticker_count', 0)}/{summary.get('universe_ticker_count', 0)}`",
        f"- Eligible equity issuers: `{cik.get('eligible_equity_issuer_count', 0)}`",
        f"- Unresolved equity mappings: `{cik.get('unresolved_equity_ticker_count', 0)}`",
        f"- Existing CIK conflicts preserved: `{cik.get('existing_cik_conflict_count', 0)}`",
        f"- Mapping report: `{cik.get('mapping_report', '')}`",
        f"- Unresolved rows: `{cik.get('unresolved_csv', '')}`",
    ]
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


def write_cik_mapping_report(
    path: Path,
    summary: dict[str, Any],
    unresolved: pd.DataFrame,
    conflicts: pd.DataFrame,
) -> None:
    cik = summary.get("sec_cik_mapping", {})
    reference = summary.get("sec_ticker_reference", {})
    lines = [
        "# SEC Ticker/CIK Mapping Coverage",
        "",
        f"Generated UTC: `{summary.get('generated_at_utc')}`",
        f"Universe rows: `{summary.get('universe_ticker_count', 0)}`",
        f"Eligible equity issuers: `{cik.get('eligible_equity_issuer_count', 0)}`",
        "",
        "## Before / After",
        "",
        f"- Before mapped: `{cik.get('before_mapped_ticker_count', 0)}`",
        f"- Missing before: `{cik.get('before_missing_ticker_count', 0)}`",
        f"- Filled from SEC reference: `{cik.get('filled_from_reference_count', 0)}`",
        f"- After mapped: `{cik.get('after_mapped_ticker_count', 0)}`",
        f"- Missing after: `{cik.get('after_missing_ticker_count', 0)}`",
        f"- Existing input/reference conflicts preserved: `{cik.get('existing_cik_conflict_count', 0)}`",
        "",
        "## Reference Provenance",
        "",
        f"- Status: `{reference.get('status', '')}`",
        f"- Source URL: `{reference.get('source_url', '')}`",
        f"- Source SHA-256: `{reference.get('source_sha256', '')}`",
        f"- Available from: `{reference.get('available_from', '')}`",
        f"- Ingested UTC: `{reference.get('ingested_at_utc', '')}`",
        "",
        "The SEC reference is a current identity snapshot, not historical Russell 1000 membership.",
        "Existing non-empty CIK values are never overwritten; conflicts are reported for review.",
        "Non-equity placeholders are excluded from automatic issuer mapping.",
        "",
        "## Preserved Input/Reference Conflicts",
        "",
    ]
    if conflicts.empty:
        lines.append("_None._")
    else:
        lines += [
            "| ticker | input CIK | current SEC reference CIK | action |",
            "| --- | --- | --- | --- |",
        ]
        for row in conflicts.to_dict("records"):
            lines.append(
                f"| {row.get('ticker', '')} | {row.get('input_cik10', '')} | "
                f"{row.get('reference_cik10', '')} | preserve input and report only |"
            )
    lines += [
        "",
        "## Unresolved Rows",
        "",
    ]
    if unresolved.empty:
        lines.append("_None._")
    else:
        lines += [
            "| ticker | mapping status | final CIK | companyfacts reason |",
            "| --- | --- | --- | --- |",
        ]
        for row in unresolved.to_dict("records"):
            lines.append(
                "| {ticker} | {status} | {cik} | {reason} |".format(
                    ticker=row.get("ticker", ""),
                    status=row.get("cik_mapping_status", ""),
                    cik=row.get("cik10", ""),
                    reason=row.get("sec_companyfacts_missing_reason", ""),
                )
            )
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
    sec_ticker_map, sec_ticker_reference = load_sec_ticker_map(repo_path(args.sec_ticker_map))
    universe = apply_sec_ticker_map(universe, sec_ticker_map, sec_ticker_reference)
    listing = load_parquet_tickers(repo_path(args.listing_status), "symbol")
    earnings_calendar = load_parquet_tickers(repo_path(args.earnings_calendar), "ticker")
    estimate_seen, estimate_has, estimate_file_count = load_forward_estimate_tickers(repo_path(args.estimate_snapshot_dir))

    rows: list[dict[str, Any]] = []
    for row in universe.to_dict("records"):
        ticker = normalize_ticker(row.get("ticker"))
        cik10 = normalize_cik(row.get("cik10"))
        input_cik10 = normalize_cik(row.get("input_cik10"))
        is_equity_issuer = bool(row.get("is_equity_issuer", True))
        mapping_status = str(row.get("cik_mapping_status") or "")
        sec_present_before_mapping = bool(input_cik10 and input_cik10 in sec_members)
        sec_present = bool(cik10 and cik10 in sec_members)
        if sec_present:
            sec_missing_reason = ""
        elif not is_equity_issuer:
            sec_missing_reason = "non_equity_placeholder"
        elif not cik10:
            sec_missing_reason = mapping_status or "missing_cik10_mapping"
        else:
            sec_missing_reason = "cik_not_in_companyfacts_zip"
        rows.append(
            {
                "ticker": ticker,
                "input_cik10": input_cik10,
                "cik10": cik10,
                "reference_cik10": normalize_cik(row.get("reference_cik10")),
                "cik_candidate_count": int(row.get("cik_candidate_count") or 0),
                "cik_mapping_status": mapping_status,
                "cik_mapping_source": row.get("cik_mapping_source", ""),
                "is_equity_issuer": is_equity_issuer,
                "universe_source": row.get("universe_source", ""),
                "sec_companyfacts_present_before_mapping": sec_present_before_mapping,
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
    eligible = coverage_frame[coverage_frame["is_equity_issuer"].astype(bool)].copy()
    unresolved = coverage_frame[~coverage_frame["sec_companyfacts_present"].astype(bool)].copy()
    conflict_rows = coverage_frame[
        coverage_frame["cik_mapping_status"].eq("existing_cik_conflict_sec_reference_preserved")
    ].copy()
    unresolved_csv = output_dir / "sec_cik_mapping_unresolved.csv"
    unresolved.to_csv(unresolved_csv, index=False)
    mapping_report = output_dir / "sec_cik_mapping_report.md"

    def coverage_item(column: str, *, label: str, pit_usage_label: str) -> dict[str, Any]:
        covered = int(coverage_frame[column].astype(bool).sum()) if column in coverage_frame.columns else 0
        return {
            "label": label,
            "pit_usage_label": pit_usage_label,
            "covered_ticker_count": covered,
            "missing_ticker_count": total - covered,
            "coverage_ratio": pct(covered, total),
        }

    before_mapped = int(coverage_frame["input_cik10"].ne("").sum())
    after_mapped = int(coverage_frame["cik10"].ne("").sum())
    filled = int(coverage_frame["cik_mapping_status"].eq("resolved_sec_company_tickers").sum())
    conflicts = int(coverage_frame["cik_mapping_status"].eq("existing_cik_conflict_sec_reference_preserved").sum())
    unresolved_equity = int((eligible["cik10"].eq("")).sum())
    sec_after_eligible = int(eligible["sec_companyfacts_present"].astype(bool).sum())
    generated_at_utc = utc_now()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "status": "ok",
        "production_promotion_allowed": False,
        "pit_universe_label_clean": False,
        "universe_ticker_count": total,
        "coverage_csv": coverage_csv.as_posix(),
        "estimate_snapshot_file_count": estimate_file_count,
        "sec_ticker_reference": sec_ticker_reference,
        "sec_cik_mapping": {
            "before_mapped_ticker_count": before_mapped,
            "before_missing_ticker_count": total - before_mapped,
            "filled_from_reference_count": filled,
            "after_mapped_ticker_count": after_mapped,
            "after_missing_ticker_count": total - after_mapped,
            "eligible_equity_issuer_count": int(len(eligible)),
            "non_equity_placeholder_count": total - int(len(eligible)),
            "unresolved_equity_ticker_count": unresolved_equity,
            "existing_cik_conflict_count": conflicts,
            "existing_cik_conflict_tickers": conflict_rows["ticker"].astype(str).tolist(),
            "mapping_status_counts": coverage_frame["cik_mapping_status"].value_counts(dropna=False).to_dict(),
            "mapping_report": mapping_report.as_posix(),
            "unresolved_csv": unresolved_csv.as_posix(),
        },
        "sec_companyfacts_missing_reason_counts": (
            coverage_frame.loc[~coverage_frame["sec_companyfacts_present"].astype(bool), "sec_companyfacts_missing_reason"]
            .value_counts(dropna=False)
            .to_dict()
        ),
        "coverage": {
            "sec_companyfacts_before_cik_mapping": coverage_item(
                "sec_companyfacts_present_before_mapping",
                label="SEC actual filings before ticker/CIK reference repair",
                pit_usage_label="actual_filings_require_accepted_timestamp",
            ),
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
    summary["coverage"]["sec_companyfacts"]["eligible_equity_issuer_count"] = int(len(eligible))
    summary["coverage"]["sec_companyfacts"]["eligible_covered_ticker_count"] = sec_after_eligible
    summary["coverage"]["sec_companyfacts"]["eligible_missing_ticker_count"] = int(len(eligible)) - sec_after_eligible
    summary["coverage"]["sec_companyfacts"]["eligible_coverage_ratio"] = pct(sec_after_eligible, int(len(eligible)))
    write_cik_mapping_report(mapping_report, summary, unresolved, conflict_rows)
    write_json(output_dir / "summary.json", summary)
    write_report(output_dir / "report.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-file", default="")
    parser.add_argument("--latest-run", default="cloud_results/full_rebuild/latest_global_alpha_universe")
    parser.add_argument("--companyfacts-zip", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--sec-ticker-map", default="data_pit/free/sec_company_tickers.parquet")
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
