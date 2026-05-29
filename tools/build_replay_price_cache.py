#!/usr/bin/env python3
"""Build a minimal price cache for artifact-only replay workflows.

Full rebuild runners normally have cache_prices from the collector cache. A
fast replay run may not. This helper downloads only the tickers needed by
monthly books plus a bounded set of latest scored names, then writes the same
hashed parquet cache format consumed by run_weekly_evaluation.py.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import CASH_TICKERS, px_cache_name


DEFAULT_OUTPUT = "cache_prices"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    if not ticker or ticker in CASH_TICKERS or ticker == "NAN":
        return ""
    return ticker


def yfinance_symbol(ticker: str) -> str:
    # Yahoo uses dashes for class-share tickers such as BRK.B.
    return str(ticker).replace(".", "-")


def collect_book_tickers(paths: list[Path]) -> tuple[set[str], pd.Timestamp | None, pd.Timestamp | None]:
    tickers: set[str] = set()
    min_dt: pd.Timestamp | None = None
    max_dt: pd.Timestamp | None = None
    for path in paths:
        frame = read_csv(path)
        if frame.empty or "ticker" not in frame.columns:
            continue
        for ticker in frame["ticker"].map(normalize_ticker):
            if ticker:
                tickers.add(ticker)
        if "rebalance_date" in frame.columns:
            dates = pd.to_datetime(frame["rebalance_date"], errors="coerce").dropna()
            if not dates.empty:
                cur_min = pd.Timestamp(dates.min()).normalize()
                cur_max = pd.Timestamp(dates.max()).normalize()
                min_dt = cur_min if min_dt is None else min(min_dt, cur_min)
                max_dt = cur_max if max_dt is None else max(max_dt, cur_max)
    return tickers, min_dt, max_dt


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return default


def collect_scored_tickers(path: Path, max_scored: int) -> set[str]:
    frame = read_csv(path)
    if frame.empty or "ticker" not in frame.columns or max_scored <= 0:
        return set()
    d = frame.copy()
    score_cols = [
        col
        for col in [
            "score",
            "raw_score",
            "portfolio_monster_early_score",
            "rs_acceleration_score",
            "h6_dynamic_leader_score",
            "relative_strength_composite",
            "dollar_volume_20d",
        ]
        if col in d.columns
    ]
    if score_cols:
        rank_score = pd.Series(0.0, index=d.index)
        for col in score_cols:
            series = pd.to_numeric(d[col], errors="coerce")
            if series.notna().any():
                rank_score = rank_score + series.rank(pct=True).fillna(0.0)
        d["_rank_score"] = rank_score
        d = d.sort_values("_rank_score", ascending=False)
    out: set[str] = set()
    for ticker in d["ticker"].map(normalize_ticker).head(max_scored):
        if ticker:
            out.add(ticker)
    return out


def parse_required_tickers(values: list[str] | str | None) -> set[str]:
    if not values:
        return set()
    if isinstance(values, str):
        raw_values = [values]
    else:
        raw_values = values
    out: set[str] = set()
    for value in raw_values:
        for token in str(value or "").replace(";", ",").split(","):
            ticker = normalize_ticker(token)
            if ticker:
                out.add(ticker)
    return out


def existing_cache_count(output_dir: Path, tickers: set[str]) -> int:
    return sum(1 for ticker in tickers if (output_dir / px_cache_name(ticker)).exists())


def cached_max_date(output_dir: Path, ticker: str) -> pd.Timestamp | None:
    path = output_dir / px_cache_name(ticker)
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None
    if frame.empty:
        return None
    idx = pd.to_datetime(frame.index, errors="coerce").dropna()
    if idx.empty:
        return None
    return pd.Timestamp(idx.max()).tz_localize(None).normalize()


def stale_cache_tickers(
    output_dir: Path,
    tickers: set[str],
    *,
    today: pd.Timestamp,
    refresh_stale_days: int,
) -> list[str]:
    if refresh_stale_days < 0:
        return []
    stale: list[str] = []
    for ticker in sorted(tickers):
        path = output_dir / px_cache_name(ticker)
        if not path.exists():
            continue
        max_dt = cached_max_date(output_dir, ticker)
        if max_dt is None:
            stale.append(ticker)
            continue
        if (today - max_dt).days > int(refresh_stale_days):
            stale.append(ticker)
    return stale


def normalize_download_frame(data: pd.DataFrame, ticker: str, symbol: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    frame = data.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if ticker in frame.columns.get_level_values(0):
            frame = frame[ticker].copy()
        elif symbol in frame.columns.get_level_values(0):
            frame = frame[symbol].copy()
        elif ticker in frame.columns.get_level_values(-1):
            frame = frame.xs(ticker, axis=1, level=-1).copy()
        elif symbol in frame.columns.get_level_values(-1):
            frame = frame.xs(symbol, axis=1, level=-1).copy()
        else:
            return pd.DataFrame()
    keep = [col for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if col in frame.columns]
    if "Close" not in keep and "Adj Close" not in keep:
        return pd.DataFrame()
    out = frame[keep].copy()
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    out = out[out.index.notna()].sort_index()
    return out.dropna(how="all")


def download_prices(tickers: list[str], start: str, end: str, output_dir: Path, batch_size: int) -> dict[str, Any]:
    import yfinance as yf

    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    failed: list[str] = []
    symbol_to_ticker = {yfinance_symbol(ticker): ticker for ticker in tickers}
    symbols = list(symbol_to_ticker.keys())
    for i in range(0, len(symbols), max(int(batch_size), 1)):
        batch = symbols[i : i + max(int(batch_size), 1)]
        try:
            data = yf.download(
                batch if len(batch) > 1 else batch[0],
                start=start,
                end=end,
                auto_adjust=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
        except Exception:
            data = pd.DataFrame()
        for symbol in batch:
            ticker = symbol_to_ticker[symbol]
            frame = normalize_download_frame(data, ticker, symbol)
            if frame.empty:
                failed.append(ticker)
                continue
            frame.to_parquet(output_dir / px_cache_name(ticker))
            written += 1
    return {"written": written, "failed": failed[:50], "failed_count": len(failed)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    book_paths = [repo_path(x) for x in args.books]
    book_tickers, min_dt, max_dt = collect_book_tickers(book_paths)
    scored_tickers = collect_scored_tickers(repo_path(args.scored), args.max_scored) if args.scored else set()
    required_tickers = parse_required_tickers(getattr(args, "required_tickers", None))
    tickers = sorted(book_tickers | scored_tickers | required_tickers)
    if args.max_tickers and args.max_tickers > 0:
        tickers = sorted(set(tickers[: int(args.max_tickers)]) | required_tickers)
    today = pd.Timestamp.utcnow().tz_localize(None).normalize()
    start_dt = pd.Timestamp(args.start).normalize() if args.start else (min_dt or today - pd.DateOffset(years=8)) - pd.Timedelta(days=14)
    end_dt = pd.Timestamp(args.end).normalize() if args.end else today + pd.Timedelta(days=2)
    missing = [ticker for ticker in tickers if not (output_dir / px_cache_name(ticker)).exists()]
    stale = stale_cache_tickers(
        output_dir,
        set(tickers),
        today=today,
        refresh_stale_days=args.refresh_stale_days,
    )
    download_targets = sorted(set(missing) | set(stale))
    result: dict[str, Any] = {
        "books": [str(path) for path in book_paths],
        "scored": str(repo_path(args.scored)) if args.scored else "",
        "ticker_count": len(tickers),
        "book_ticker_count": len(book_tickers),
        "scored_ticker_count": len(scored_tickers),
        "required_tickers": sorted(required_tickers),
        "required_ticker_count": len(required_tickers),
        "existing_cache_count": existing_cache_count(output_dir, set(tickers)),
        "missing_before": len(missing),
        "stale_before": len(stale),
        "refresh_stale_days": int(args.refresh_stale_days),
        "download_target_count": len(download_targets),
        "start": start_dt.date().isoformat(),
        "end": end_dt.date().isoformat(),
        "output_dir": str(output_dir),
    }
    if args.dry_run or not download_targets:
        result.update({"downloaded": 0, "failed_count": 0, "failed": [], "status": "dry_run" if args.dry_run else "already_cached"})
    else:
        download_result = download_prices(download_targets, result["start"], result["end"], output_dir, args.batch_size)
        result.update(download_result)
        result["status"] = "completed"
    result["existing_cache_count_after"] = existing_cache_count(output_dir, set(tickers))
    manifest = output_dir / "replay_price_cache_manifest.json"
    manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", nargs="+", required=True)
    parser.add_argument("--scored", default="")
    parser.add_argument("--max-scored", type=int, default=250)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument(
        "--required-tickers",
        nargs="*",
        default=[],
        help="Tickers that must be included even if they are not in target books, e.g. SPY QQQ.",
    )
    parser.add_argument(
        "--refresh-stale-days",
        type=int,
        default=2,
        help="Refresh cached tickers whose latest cached bar is older than this many calendar days; use -1 to disable.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
