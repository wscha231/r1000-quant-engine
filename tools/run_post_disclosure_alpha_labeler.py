#!/usr/bin/env python3
"""Label post-disclosure alpha events with next-close forward returns.

This D1 tool is research-only. It consumes PIT event rows such as 13F position
events and labels what happened after the event became available. Availability
is always `available_from` / `accepted_at`; `report_period` is never used as an
entry date.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, price_on_or_after  # noqa: E402

DEFAULT_EVENTS = "data_pit/sec/13f_position_events.parquet"
DEFAULT_PRICE_CACHE = "cache_prices"
DEFAULT_OUTPUT_DIR = "outputs/post_disclosure_alpha"
DEFAULT_PIT_OUTPUT = "data_pit/sec/post_disclosure_alpha_labels.parquet"
DEFAULT_BENCHMARK = "SPY"
DEFAULT_HORIZONS = "1,5,21,42,63,126"

BASE_COLUMNS = [
    "event_id",
    "source_type",
    "manager_cik",
    "manager_name",
    "ticker",
    "event_type",
    "available_from",
    "entry_date",
    "entry_price",
    "benchmark_ticker",
    "benchmark_entry_date",
    "benchmark_entry_price",
    "max_dd_63d",
    "hit_21d",
    "hit_63d",
    "explosive_hit_63d",
    "label_status",
    "label_reason",
    "research_only",
    "production_activation_allowed",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def parse_horizons(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value <= 0:
            raise ValueError(f"horizon must be positive: {value}")
        out.append(value)
    return sorted(set(out))


def normalize_events(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    if "available_from" not in d.columns and "accepted_at" in d.columns:
        d["available_from"] = d["accepted_at"]
    d["ticker"] = d.get("ticker", "").fillna("").astype(str).str.upper().str.strip()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d = d[d["ticker"].ne("") & d["available_from_ts"].notna()].copy()
    if "event_id" not in d.columns:
        d["event_id"] = [f"event:{i}" for i in range(len(d))]
    return d.sort_values(["available_from_ts", "ticker", "event_id"]).reset_index(drop=True)


def first_close_after_available(px: pd.DataFrame, available_from: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    # Conservative rule: do not use the same calendar day's close. Many filings
    # arrive after market close, and accepted_at timestamps vary by source.
    search_start = pd.Timestamp(available_from).normalize() + pd.Timedelta(days=1)
    return price_on_or_after(px, search_start, "close")


def price_at_trading_offset(px: pd.DataFrame, entry_date: pd.Timestamp, horizon: int) -> tuple[pd.Timestamp | None, float | None]:
    if px.empty or "close" not in px.columns:
        return None, None
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(pd.Timestamp(entry_date), side="left"))
    if pos >= len(idx) or pd.Timestamp(idx[pos]).normalize() != pd.Timestamp(entry_date).normalize():
        return None, None
    target = pos + int(horizon)
    if target >= len(idx):
        return None, None
    value = float(px["close"].iloc[target])
    if not np.isfinite(value) or value <= 0:
        return None, None
    return pd.Timestamp(idx[target]), value


def forward_return(px: pd.DataFrame, entry_date: pd.Timestamp, entry_price: float, horizon: int) -> tuple[float, pd.Timestamp | None, float | None]:
    target_date, target_price = price_at_trading_offset(px, entry_date, horizon)
    if target_date is None or target_price is None or not np.isfinite(entry_price) or entry_price <= 0:
        return np.nan, target_date, target_price
    return float(target_price / entry_price - 1.0), target_date, target_price


def benchmark_return(
    benchmark_px: pd.DataFrame,
    entry_date: pd.Timestamp,
    target_date: pd.Timestamp | None,
) -> tuple[float, pd.Timestamp | None, float | None]:
    if target_date is None or benchmark_px.empty:
        return np.nan, None, None
    bench_entry_date, bench_entry = price_on_or_after(benchmark_px, entry_date, "close")
    bench_target_date, bench_target = price_on_or_after(benchmark_px, target_date, "close")
    if bench_entry_date is None or bench_target_date is None or bench_entry is None or bench_target is None:
        return np.nan, bench_entry_date, bench_entry
    return float(bench_target / bench_entry - 1.0), bench_entry_date, bench_entry


def max_drawdown_after_entry(px: pd.DataFrame, entry_date: pd.Timestamp, entry_price: float, horizon: int) -> float:
    if px.empty or "close" not in px.columns or not np.isfinite(entry_price) or entry_price <= 0:
        return np.nan
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(pd.Timestamp(entry_date), side="left"))
    if pos >= len(idx):
        return np.nan
    end = min(len(idx), pos + int(horizon) + 1)
    window = pd.to_numeric(px["close"].iloc[pos:end], errors="coerce").dropna()
    if window.empty:
        return np.nan
    return float((window / entry_price - 1.0).min())


def label_events(events: pd.DataFrame, price_cache: Path, benchmark_ticker: str, horizons: list[int]) -> pd.DataFrame:
    d = normalize_events(events)
    if d.empty:
        return pd.DataFrame(columns=BASE_COLUMNS)
    price_series: dict[str, pd.DataFrame] = {}
    for ticker in sorted(set(d["ticker"].astype(str).str.upper()) | {benchmark_ticker.upper()}):
        price_series[ticker] = load_price_series(price_cache, ticker)
    benchmark_px = price_series.get(benchmark_ticker.upper(), pd.DataFrame())

    rows: list[dict[str, Any]] = []
    for _, event in d.iterrows():
        ticker = str(event.get("ticker", "")).upper().strip()
        available = pd.Timestamp(event.get("available_from_ts"))
        px = price_series.get(ticker, pd.DataFrame())
        entry_date, entry_price = first_close_after_available(px, available)
        row: dict[str, Any] = {
            "event_id": str(event.get("event_id", "")),
            "source_type": str(event.get("source_type", "")),
            "manager_cik": str(event.get("manager_cik", "")),
            "manager_name": str(event.get("manager_name", "")),
            "ticker": ticker,
            "event_type": str(event.get("event_type", "")),
            "available_from": str(event.get("available_from", "")),
            "entry_date": entry_date.date().isoformat() if entry_date is not None else "",
            "entry_price": float(entry_price) if entry_price is not None else np.nan,
            "benchmark_ticker": benchmark_ticker.upper(),
            "benchmark_entry_date": "",
            "benchmark_entry_price": np.nan,
            "research_only": True,
            "production_activation_allowed": False,
        }
        if entry_date is None or entry_price is None:
            row.update(
                {
                    "max_dd_63d": np.nan,
                    "hit_21d": False,
                    "hit_63d": False,
                    "explosive_hit_63d": False,
                    "label_status": "missing_entry_price",
                    "label_reason": "missing ticker price on first close after available_from",
                }
            )
            for horizon in horizons:
                row[f"ret_{horizon}d"] = np.nan
                row[f"target_date_{horizon}d"] = ""
                row[f"target_price_{horizon}d"] = np.nan
                row[f"benchmark_ret_{horizon}d"] = np.nan
                row[f"excess_spy_{horizon}d"] = np.nan
            rows.append(row)
            continue

        label_status = "completed"
        label_reason = ""
        for horizon in horizons:
            ret, target_date, target_price = forward_return(px, entry_date, float(entry_price), horizon)
            bench_ret, bench_entry_date, bench_entry = benchmark_return(benchmark_px, entry_date, target_date)
            if bench_entry_date is not None:
                row["benchmark_entry_date"] = bench_entry_date.date().isoformat()
            if bench_entry is not None:
                row["benchmark_entry_price"] = float(bench_entry)
            row[f"ret_{horizon}d"] = ret
            row[f"target_date_{horizon}d"] = target_date.date().isoformat() if target_date is not None else ""
            row[f"target_price_{horizon}d"] = float(target_price) if target_price is not None else np.nan
            row[f"benchmark_ret_{horizon}d"] = bench_ret
            row[f"excess_spy_{horizon}d"] = float(ret - bench_ret) if np.isfinite(ret) and np.isfinite(bench_ret) else np.nan
            if not np.isfinite(ret):
                label_status = "partial"
                label_reason = "insufficient future price history for at least one horizon"

        ret21 = float(row.get("ret_21d", np.nan))
        ret63 = float(row.get("ret_63d", np.nan))
        excess63 = float(row.get("excess_spy_63d", np.nan))
        row["max_dd_63d"] = max_drawdown_after_entry(px, entry_date, float(entry_price), 63)
        row["hit_21d"] = bool(np.isfinite(ret21) and ret21 > 0.0)
        row["hit_63d"] = bool(np.isfinite(ret63) and ret63 > 0.0)
        row["explosive_hit_63d"] = bool(np.isfinite(ret63) and ret63 >= 0.30 and (not np.isfinite(excess63) or excess63 >= 0.15))
        row["label_status"] = label_status
        row["label_reason"] = label_reason
        rows.append(row)

    out = pd.DataFrame(rows)
    ordered = BASE_COLUMNS.copy()
    for horizon in horizons:
        ordered.extend(
            [
                f"ret_{horizon}d",
                f"target_date_{horizon}d",
                f"target_price_{horizon}d",
                f"benchmark_ret_{horizon}d",
                f"excess_spy_{horizon}d",
            ]
        )
    for col in ordered:
        if col not in out.columns:
            out[col] = ""
    return out[ordered].sort_values(["available_from", "ticker", "event_id"]).reset_index(drop=True)


def render_report(summary: dict[str, Any], labels: pd.DataFrame, horizons: list[int]) -> str:
    lines = [
        "# Post-Disclosure Alpha Labels",
        "",
        "Research-only forward return labels measured after SEC event availability.",
        "",
        f"- status: `{summary.get('status', '')}`",
        f"- label rows: {summary.get('label_rows', 0)}",
        f"- completed rows: {summary.get('completed_rows', 0)}",
        f"- ticker count: {summary.get('ticker_count', 0)}",
        f"- benchmark: `{summary.get('benchmark_ticker', '')}`",
        "",
        "## Horizon Summary",
        "",
        "| horizon | avg return | avg excess SPY | hit rate | rows |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in horizons:
        ret = pd.to_numeric(labels.get(f"ret_{horizon}d"), errors="coerce") if not labels.empty else pd.Series(dtype=float)
        excess = pd.to_numeric(labels.get(f"excess_spy_{horizon}d"), errors="coerce") if not labels.empty else pd.Series(dtype=float)
        valid = ret.dropna()
        hit = float((valid > 0.0).mean()) if len(valid) else 0.0
        lines.append(
            f"| {horizon} | {float(valid.mean()) if len(valid) else 0.0:.2%} | "
            f"{float(excess.dropna().mean()) if excess.notna().any() else 0.0:.2%} | {hit:.2%} | {int(len(valid))} |"
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    events_path = repo_path(args.events)
    price_cache = repo_path(args.price_cache)
    pit_output = repo_path(args.pit_output)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    horizons = parse_horizons(args.horizons)

    events = read_table(events_path)
    labels = label_events(events, price_cache, args.benchmark_ticker, horizons)
    write_table(labels, pit_output)
    write_table(labels, output_dir / "post_disclosure_alpha_labels.csv")

    completed = labels[labels.get("label_status").eq("completed")] if not labels.empty else pd.DataFrame()
    partial = labels[labels.get("label_status").eq("partial")] if not labels.empty else pd.DataFrame()
    summary = {
        "status": "completed" if not labels.empty and not completed.empty else ("partial" if not labels.empty else "blocked"),
        "reason": "" if not labels.empty else "missing events with available_from and tickers",
        "schema_version": "post-disclosure-alpha-labels-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "events": str(events_path),
        "price_cache": str(price_cache),
        "pit_output": str(pit_output),
        "benchmark_ticker": str(args.benchmark_ticker).upper(),
        "horizons": horizons,
        "event_rows": int(len(events)),
        "label_rows": int(len(labels)),
        "completed_rows": int(len(completed)),
        "partial_rows": int(len(partial)),
        "missing_entry_price_rows": int((labels.get("label_status") == "missing_entry_price").sum()) if not labels.empty else 0,
        "ticker_count": int(labels["ticker"].nunique()) if not labels.empty else 0,
        "latest_available_from": str(labels["available_from"].max()) if not labels.empty and "available_from" in labels else "",
        "outputs": {
            "pit_output": str(pit_output),
            "labels_csv": str(output_dir / "post_disclosure_alpha_labels.csv"),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, labels, horizons), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "label_rows": summary["label_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default=DEFAULT_EVENTS)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--pit-output", default=DEFAULT_PIT_OUTPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--benchmark-ticker", default=DEFAULT_BENCHMARK)
    parser.add_argument("--horizons", default=DEFAULT_HORIZONS)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
