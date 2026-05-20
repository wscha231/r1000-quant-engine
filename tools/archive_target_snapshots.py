#!/usr/bin/env python3
"""Archive latest recommendation and operating target books as dated snapshots."""
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

from tools.build_operating_target_books import clean_ticker, latest_date_from_columns, latest_price_close_date


DATE_COLUMNS = ["rebalance_date", "feature_date", "as_of_date", "last_trade_date", "date", "Date"]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def infer_snapshot_date(
    *,
    explicit_date: str,
    price_cache: Path,
    main_target: pd.DataFrame,
    concentrated_target: pd.DataFrame,
) -> tuple[str, str]:
    if explicit_date:
        return date_text(explicit_date), "explicit"
    tickers: list[str] = []
    for frame in [main_target, concentrated_target]:
        if not frame.empty and "ticker" in frame.columns:
            tickers.extend(frame["ticker"].astype(str).map(clean_ticker).tolist())
    price_date = latest_price_close_date(price_cache, tickers) if tickers else None
    if price_date is not None:
        return date_text(price_date), "latest_common_price_close"
    dates: list[pd.Timestamp] = []
    for frame in [main_target, concentrated_target]:
        dt = latest_date_from_columns(frame, DATE_COLUMNS)
        if dt is not None:
            dates.append(pd.Timestamp(dt).normalize())
    if dates:
        return date_text(max(dates)), "latest_target_column"
    return datetime.now(timezone.utc).date().isoformat(), "generated_date_fallback"


def normalize_recommendation(frame: pd.DataFrame, portfolio: str, snapshot_date: str, source_path: Path) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    if "ticker" in out.columns:
        out["ticker"] = out["ticker"].map(clean_ticker)
    if "weight" in out.columns:
        out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    out["portfolio_kind"] = portfolio
    out["snapshot_date"] = snapshot_date
    out["snapshot_source_path"] = str(source_path)
    out["archived_at_utc"] = now_utc()
    return out


def file_summary(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    weight_sum = None
    if not frame.empty and "weight" in frame.columns:
        weight_sum = float(pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0).sum())
    max_date = ""
    if not frame.empty:
        dt = latest_date_from_columns(frame, DATE_COLUMNS)
        max_date = date_text(dt) if dt is not None else ""
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": int(len(frame)),
        "weight_sum": weight_sum,
        "max_date": max_date,
    }


def copy_csv(src: Path, dst: Path) -> dict[str, Any]:
    frame = read_csv(src)
    if frame.empty:
        return {"source": str(src), "path": str(dst), "exists": False, "row_count": 0}
    dst.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(dst, index=False)
    summary = file_summary(dst, frame)
    summary["source"] = str(src)
    return summary


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_root = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    main_path = latest_run / "portfolio_latest.csv"
    concentrated_path = latest_run / "concentrated_portfolio_latest.csv"
    main_target = read_csv(main_path)
    concentrated_target = read_csv(concentrated_path)
    snapshot_date, date_source = infer_snapshot_date(
        explicit_date=args.date,
        price_cache=price_cache,
        main_target=main_target,
        concentrated_target=concentrated_target,
    )
    snapshot_dir = output_root / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, dict[str, Any]] = {}
    main_norm = normalize_recommendation(main_target, "main", snapshot_date, main_path)
    concentrated_norm = normalize_recommendation(concentrated_target, "concentrated", snapshot_date, concentrated_path)
    if not main_norm.empty:
        out = snapshot_dir / "main_recommendation.csv"
        main_norm.to_csv(out, index=False)
        files["main_recommendation"] = file_summary(out, main_norm)
        files["main_recommendation"]["source"] = str(main_path)
    else:
        files["main_recommendation"] = {"source": str(main_path), "path": str(snapshot_dir / "main_recommendation.csv"), "exists": False, "row_count": 0}
    if not concentrated_norm.empty:
        out = snapshot_dir / "concentrated_recommendation.csv"
        concentrated_norm.to_csv(out, index=False)
        files["concentrated_recommendation"] = file_summary(out, concentrated_norm)
        files["concentrated_recommendation"]["source"] = str(concentrated_path)
    else:
        files["concentrated_recommendation"] = {
            "source": str(concentrated_path),
            "path": str(snapshot_dir / "concentrated_recommendation.csv"),
            "exists": False,
            "row_count": 0,
        }

    files["operating_main_target_book"] = copy_csv(
        latest_run / "reports" / "operating_main_target_book.csv",
        snapshot_dir / "operating_main_target_book.csv",
    )
    files["operating_concentrated_target_book"] = copy_csv(
        latest_run / "reports" / "operating_concentrated_target_book.csv",
        snapshot_dir / "operating_concentrated_target_book.csv",
    )
    files["operating_target_books_summary"] = {
        "source": str(latest_run / "reports" / "operating_target_books_summary.json"),
        "path": str(snapshot_dir / "operating_target_books_summary.json"),
        "exists": False,
        "row_count": 0,
    }
    src_summary = latest_run / "reports" / "operating_target_books_summary.json"
    if src_summary.exists():
        payload = json.loads(src_summary.read_text(encoding="utf-8"))
        write_json(snapshot_dir / "operating_target_books_summary.json", payload)
        files["operating_target_books_summary"]["exists"] = True

    missing_required = [
        name
        for name in ["main_recommendation", "concentrated_recommendation"]
        if int(files.get(name, {}).get("row_count") or 0) <= 0
    ]
    payload = {
        "schema_version": "target-snapshot-archive-v1",
        "generated_at_utc": now_utc(),
        "status": "blocked" if missing_required else "completed",
        "blocked_reason": "latest recommendation files are missing or empty" if missing_required else "",
        "missing_required": missing_required,
        "snapshot_date": snapshot_date,
        "snapshot_date_source": date_source,
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "snapshot_dir": str(snapshot_dir),
        "files": files,
    }
    write_json(snapshot_dir / "manifest.json", payload)
    write_json(output_root / "latest_manifest.json", payload)
    print(json.dumps(payload, indent=2, default=str))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/target_snapshots")
    parser.add_argument("--date", default="", help="Override snapshot date in YYYY-MM-DD format.")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
