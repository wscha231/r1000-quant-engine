#!/usr/bin/env python3
"""Build shadow SEC ownership/evidence signals from parsed EDGAR filings."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.sec_edgar_common import read_table, write_json, write_table

DEFAULT_TRANSACTIONS = "data_pit/sec/form4_transactions.parquet"
DEFAULT_PIT_OUTPUT = "data_pit/sec/sec_ownership_signals.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_ownership_signals"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def role_weight(row: pd.Series) -> float:
    title = str(row.get("officer_title") or "")
    weight = 1.0
    if bool(row.get("is_director")):
        weight += 0.25
    if bool(row.get("is_officer")):
        weight += 0.50
    if bool(row.get("is_ten_percent_owner")):
        weight += 0.25
    if "CEO" in title.upper() or "CHIEF EXECUTIVE" in title.upper():
        weight += 1.00
    if "CFO" in title.upper() or "CHIEF FINANCIAL" in title.upper():
        weight += 0.75
    return weight


def value_score(value: float, scale_usd: float) -> float:
    value = max(0.0, safe_float(value))
    if value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(scale_usd))


def prepare_transactions(frame: pd.DataFrame, as_of: pd.Timestamp | None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["issuer_ticker"] = d["issuer_ticker"].astype(str).str.upper().str.strip()
    d["transaction_code"] = d["transaction_code"].astype(str).str.upper().str.strip()
    d["available_from_dt"] = pd.to_datetime(d["available_from"], errors="coerce", utc=True)
    d["accepted_at_dt"] = pd.to_datetime(d["accepted_at"], errors="coerce", utc=True)
    d["transaction_date_dt"] = pd.to_datetime(d["transaction_date"], errors="coerce")
    for col in ["transaction_value", "transaction_shares", "transaction_price"]:
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
    d = d[d["issuer_ticker"].ne("") & d["available_from_dt"].notna()].copy()
    if as_of is not None:
        as_of_utc = pd.Timestamp(as_of)
        if as_of_utc.tzinfo is None:
            as_of_utc = as_of_utc.tz_localize("UTC")
        d = d[d["available_from_dt"].le(as_of_utc)].copy()
    return d


def build_form4_signals(frame: pd.DataFrame, *, as_of: pd.Timestamp | None = None, window_days: int = 90) -> pd.DataFrame:
    d = prepare_transactions(frame, as_of)
    if d.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "as_of_date",
                "sec_form4_open_market_buy_score",
                "sec_form4_cluster_buy_score",
                "sec_form4_ceo_cfo_buy_score",
                "sec_form4_sale_pressure_score",
                "early_evidence_score",
                "evidence_confidence_score",
            ]
        )
    effective_as_of = pd.Timestamp(as_of) if as_of is not None else d["available_from_dt"].max()
    if effective_as_of.tzinfo is None:
        effective_as_of = effective_as_of.tz_localize("UTC")
    start = effective_as_of - pd.Timedelta(days=int(window_days))
    recent = d[d["available_from_dt"].between(start, effective_as_of)].copy()
    recent["is_open_market_buy"] = recent["transaction_code"].eq("P")
    recent["is_sale"] = recent["transaction_code"].eq("S")
    recent["role_weight"] = recent.apply(role_weight, axis=1)
    recent["weighted_buy_value"] = recent["transaction_value"].where(recent["is_open_market_buy"], 0.0) * recent["role_weight"]
    recent["sale_value"] = recent["transaction_value"].where(recent["is_sale"], 0.0)
    recent["ceo_cfo_buy"] = (
        recent["is_open_market_buy"]
        & recent["officer_title"].astype(str).str.contains("CEO|Chief Executive|CFO|Chief Financial", case=False, na=False)
    )
    rows: list[dict[str, Any]] = []
    for ticker, group in recent.groupby("issuer_ticker", sort=False):
        buy_count = int(group["is_open_market_buy"].sum())
        sale_count = int(group["is_sale"].sum())
        buy_value = float(group["weighted_buy_value"].sum())
        sale_value = float(group["sale_value"].sum())
        ceo_cfo_count = int(group["ceo_cfo_buy"].sum())
        open_market_score = value_score(buy_value, 5_000_000)
        cluster_score = min(1.0, (buy_count / 3.0) * 0.55 + value_score(buy_value, 3_000_000) * 0.45)
        ceo_cfo_score = min(1.0, ceo_cfo_count / 2.0)
        sale_pressure = min(1.0, (sale_count / 5.0) * 0.35 + value_score(sale_value, 10_000_000) * 0.65)
        early_evidence = max(0.0, min(1.0, 0.45 * cluster_score + 0.30 * open_market_score + 0.20 * ceo_cfo_score - 0.15 * sale_pressure))
        source_count = int((buy_count > 0)) + int((ceo_cfo_count > 0)) + int((sale_count > 0))
        confidence = min(1.0, source_count / 3.0 + min(0.35, len(group) / 20.0))
        rows.append(
            {
                "ticker": ticker,
                "as_of_date": effective_as_of.date().isoformat(),
                "available_from": group["available_from_dt"].max().isoformat(),
                "form4_window_days": int(window_days),
                "form4_open_market_buy_count": buy_count,
                "form4_sale_count": sale_count,
                "form4_open_market_buy_value": buy_value,
                "form4_sale_value": sale_value,
                "sec_form4_open_market_buy_score": open_market_score,
                "sec_form4_cluster_buy_score": cluster_score,
                "sec_form4_ceo_cfo_buy_score": ceo_cfo_score,
                "sec_form4_sale_pressure_score": sale_pressure,
                "early_evidence_score": early_evidence,
                "evidence_confidence_score": confidence,
            }
        )
    return pd.DataFrame(rows).sort_values("early_evidence_score", ascending=False)


def load_as_of_dates(path: Path, column: str) -> list[pd.Timestamp]:
    if not path.exists():
        return []
    try:
        frame = read_table(path)
    except Exception:
        return []
    if frame.empty or column not in frame.columns:
        return []
    dates = pd.to_datetime(frame[column], errors="coerce", utc=True).dropna()
    if dates.empty:
        return []
    return [pd.Timestamp(dt).normalize() for dt in sorted(dates.unique())]


def run(args: argparse.Namespace) -> dict[str, Any]:
    tx = read_table(repo_path(args.transactions))
    as_of = pd.to_datetime(args.as_of_date, errors="coerce", utc=True) if args.as_of_date else None
    if as_of is not None and pd.isna(as_of):
        as_of = None
    as_of_dates = load_as_of_dates(repo_path(args.as_of_dates_csv), args.as_of_date_column) if args.as_of_dates_csv else []
    if as_of_dates:
        parts = [build_form4_signals(tx, as_of=dt, window_days=args.window_days) for dt in as_of_dates]
        parts = [part for part in parts if not part.empty]
        signals = pd.concat(parts, ignore_index=True) if parts else build_form4_signals(tx.iloc[0:0], as_of=as_of, window_days=args.window_days)
    else:
        signals = build_form4_signals(tx, as_of=as_of, window_days=args.window_days)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pit_output = repo_path(args.pit_output)
    write_table(signals, pit_output)
    signals.to_csv(output_dir / "form4_latest.csv", index=False)
    top = signals.head(30).copy()
    top.to_csv(output_dir / "ownership_signal_top30.csv", index=False)
    summary = {
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transaction_rows": int(len(tx)),
        "signal_rows": int(len(signals)),
        "historical_as_of_dates": int(len(as_of_dates)),
        "as_of_date": str(signals["as_of_date"].iloc[0]) if not signals.empty and "as_of_date" in signals.columns else "",
        "top_tickers": signals["ticker"].head(10).tolist() if not signals.empty else [],
        "outputs": {
            "pit_signals": str(pit_output),
            "form4_latest": str(output_dir / "form4_latest.csv"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "ownership_signal_summary.json", summary)
    report = [
        "# SEC Ownership Signals",
        "",
        f"- status: {summary['status']}",
        f"- transaction_rows: {summary['transaction_rows']}",
        f"- signal_rows: {summary['signal_rows']}",
        f"- as_of_date: {summary['as_of_date']}",
        "",
        "This is a shadow evidence layer. Scores are not wired into production selection.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transactions", default=DEFAULT_TRANSACTIONS)
    parser.add_argument("--pit-output", default=DEFAULT_PIT_OUTPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-date", default="", help="UTC timestamp/date. Features only use rows with available_from <= this.")
    parser.add_argument("--as-of-dates-csv", default="", help="Optional CSV/parquet with PIT evaluation dates, e.g. candidate_replay_book.csv.")
    parser.add_argument("--as-of-date-column", default="rebalance_date")
    parser.add_argument("--window-days", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
