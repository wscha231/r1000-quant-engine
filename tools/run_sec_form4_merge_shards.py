#!/usr/bin/env python3
"""Merge SEC Form 4 shard outputs into canonical PIT evidence files."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_ownership_signals import build_form4_signals, load_as_of_dates  # noqa: E402
from tools.sec_edgar_common import normalize_cik10, read_table, write_json, write_table  # noqa: E402

DEFAULT_PIT_ROOT = "data_pit/sec"
DEFAULT_OUTPUT_DIR = "outputs/sec_ownership_signals"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_many(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        if path.exists():
            frame = read_table(path)
            if not frame.empty:
                frame["_source_file"] = str(path)
                frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def normalize_filings(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    d = frame.copy()
    if "cik10" in d.columns:
        d["cik10"] = d["cik10"].map(normalize_cik10)
    for col in ["ticker", "form_type", "accession_number"]:
        if col in d.columns:
            d[col] = d[col].astype(str).str.upper().str.strip() if col != "accession_number" else d[col].astype(str).str.strip()
    keys = [c for c in ["cik10", "accession_number", "form_type"] if c in d.columns]
    if keys:
        d = d.drop_duplicates(keys, keep="last")
    sort_cols = [c for c in ["ticker", "filing_date", "accession_number"] if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols, ascending=[True, False, False][: len(sort_cols)])
    return d.reset_index(drop=True)


def normalize_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    d = frame.copy()
    for col in ["issuer_cik10", "reporting_owner_cik"]:
        if col in d.columns:
            d[col] = d[col].map(normalize_cik10)
    if "issuer_ticker" in d.columns:
        d["issuer_ticker"] = d["issuer_ticker"].astype(str).str.upper().str.strip()
    for col in ["transaction_shares", "transaction_price", "transaction_value", "shares_owned_after"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    keys = [
        col
        for col in [
            "accession_number",
            "reporting_owner_cik",
            "transaction_date",
            "transaction_code",
            "security_title",
            "transaction_shares",
            "transaction_price",
        ]
        if col in d.columns
    ]
    if keys:
        d = d.drop_duplicates(keys, keep="last")
    sort_cols = [c for c in ["issuer_ticker", "available_from", "accession_number"] if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols)
    return d.reset_index(drop=True)


def build_signals(tx: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    as_of_dates = load_as_of_dates(repo_path(args.as_of_dates_csv), args.as_of_date_column) if args.as_of_dates_csv else []
    if as_of_dates:
        parts = [build_form4_signals(tx, as_of=dt, window_days=args.window_days) for dt in as_of_dates]
        parts = [part for part in parts if not part.empty]
        return pd.concat(parts, ignore_index=True) if parts else build_form4_signals(tx.iloc[0:0], window_days=args.window_days)
    return build_form4_signals(tx, window_days=args.window_days)


def run(args: argparse.Namespace) -> dict[str, Any]:
    pit_root = repo_path(args.pit_root)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filing_paths = [pit_root / "sec_filings_index.parquet"] + sorted((pit_root / "shards").glob("**/sec_filings_index.parquet"))
    tx_paths = [pit_root / "form4_transactions.parquet"] + sorted((pit_root / "shards").glob("**/form4_transactions.parquet"))

    filings = normalize_filings(read_many(filing_paths))
    tx = normalize_transactions(read_many(tx_paths))
    signals = build_signals(tx, args)

    write_table(filings, pit_root / "sec_filings_index.parquet")
    write_table(tx, pit_root / "form4_transactions.parquet")
    write_table(signals, pit_root / "sec_ownership_signals.parquet")
    signals.to_csv(output_dir / "form4_latest.csv", index=False)
    signals.head(30).to_csv(output_dir / "ownership_signal_top30.csv", index=False)

    summary = {
        "status": "completed",
        "schema_version": "sec-form4-merge-shards-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "filing_source_files": len([p for p in filing_paths if p.exists()]),
        "transaction_source_files": len([p for p in tx_paths if p.exists()]),
        "filing_rows": int(len(filings)),
        "transaction_rows": int(len(tx)),
        "signal_rows": int(len(signals)),
        "historical_as_of_dates": int(signals["as_of_date"].nunique()) if not signals.empty and "as_of_date" in signals.columns else 0,
        "outputs": {
            "sec_filings_index": str(pit_root / "sec_filings_index.parquet"),
            "form4_transactions": str(pit_root / "form4_transactions.parquet"),
            "sec_ownership_signals": str(pit_root / "sec_ownership_signals.parquet"),
            "form4_latest": str(output_dir / "form4_latest.csv"),
        },
    }
    write_json(output_dir / "ownership_signal_summary.json", summary)
    write_json(pit_root / "sec_form4_merge_manifest.json", summary)
    report = [
        "# SEC Form 4 Shard Merge",
        "",
        f"- status: {summary['status']}",
        f"- filing_rows: {summary['filing_rows']}",
        f"- transaction_rows: {summary['transaction_rows']}",
        f"- signal_rows: {summary['signal_rows']}",
        f"- transaction_source_files: {summary['transaction_source_files']}",
        "",
        "Canonical outputs are point-in-time evidence files. They remain shadow research inputs until broker-ledger validation passes.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-root", default=DEFAULT_PIT_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-dates-csv", default="", help="Optional CSV/parquet with historical evaluation dates.")
    parser.add_argument("--as-of-date-column", default="rebalance_date")
    parser.add_argument("--window-days", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
