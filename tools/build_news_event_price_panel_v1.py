#!/usr/bin/env python3
"""Build a research-only price/session panel for News Event Alpha V1.

Reuses the existing replay price-cache parquet files and the authoritative NYSE
schedule helper already used by the forward paper ledger. Missing benchmark or
event-security price files fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.news_event_alpha_v1.runtime import canonical_bytes, digest  # noqa: E402
from tools.run_free_data_forward_paper_ledger import (  # noqa: E402
    load_nyse_schedule,
    normalize_ticker,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"event row must be object: {path}:{lineno}")
        rows.append(item)
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def locate_cache_file(cache_dir: Path, ticker: str) -> Path | None:
    candidates = [
        cache_dir / f"{ticker}.parquet",
        cache_dir / f"{ticker.replace('-', '_')}.parquet",
        cache_dir / f"{ticker.replace('-', '.')}.parquet",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def normalize_cache_frame(path: Path, ticker: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if frame.empty:
        raise ValueError(f"empty price cache: {ticker} {path}")
    if "Date" in frame.columns:
        dates = pd.to_datetime(frame["Date"], errors="coerce", utc=True)
    else:
        dates = pd.to_datetime(frame.index, errors="coerce", utc=True)
    if isinstance(dates, pd.Series):
        dates = dates.dt.tz_convert(None).dt.normalize()
    else:
        dates = pd.DatetimeIndex(dates).tz_convert(None).normalize()

    adjusted_col = None
    for name in ("Adj Close", "Adj_Close", "adj_close", "adjusted_close"):
        if name in frame.columns:
            adjusted_col = name
            break
    if adjusted_col is None:
        raise ValueError(
            f"{ticker} cache lacks adjusted-close column; refusing to use raw Close"
        )

    adjusted = pd.to_numeric(frame[adjusted_col], errors="coerce")
    volume = (
        pd.to_numeric(frame["Volume"], errors="coerce")
        if "Volume" in frame.columns
        else pd.Series([pd.NA] * len(frame), index=frame.index)
    )
    out = pd.DataFrame(
        {
            "session_dt": list(dates),
            "adjusted_close": list(adjusted),
            "volume": list(volume),
        }
    )
    out = out.dropna(subset=["session_dt", "adjusted_close"])
    out = out[out["adjusted_close"] > 0].copy()
    out = out.sort_values("session_dt").drop_duplicates("session_dt", keep="last")
    if out.empty:
        raise ValueError(f"{ticker} has no valid adjusted-close rows")
    first = float(out.iloc[0]["adjusted_close"])
    out["total_return_index"] = out["adjusted_close"].astype(float) / first * 100.0
    return out


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--price-cache-manifest", default="")
    args = parser.parse_args()

    events_path = Path(args.events)
    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.output_dir)
    benchmark = normalize_ticker(args.benchmark)
    if not benchmark:
        raise ValueError("benchmark ticker required")

    events = load_jsonl(events_path)
    event_tickers = sorted(
        {
            normalize_ticker(row.get("security_id"))
            for row in events
            if normalize_ticker(row.get("security_id"))
        }
    )
    required = sorted(set(event_tickers + [benchmark]))
    if not event_tickers:
        raise ValueError("event file contains no security_id values")

    frames: dict[str, pd.DataFrame] = {}
    cache_files: dict[str, Path] = {}
    missing: list[str] = []
    for ticker in required:
        path = locate_cache_file(cache_dir, ticker)
        if path is None:
            missing.append(ticker)
            continue
        frames[ticker] = normalize_cache_frame(path, ticker)
        cache_files[ticker] = path
    if missing:
        raise ValueError(
            "missing required replay price cache files: " + ",".join(missing)
        )

    min_date = min(frame["session_dt"].min() for frame in frames.values())
    max_date = max(frame["session_dt"].max() for frame in frames.values())
    schedule = load_nyse_schedule(min_date, max_date)
    if schedule is None or schedule.empty:
        raise RuntimeError(
            "authoritative NYSE schedule unavailable; refusing calendar-date inference"
        )

    schedule_dates = set(pd.DatetimeIndex(schedule.index).normalize())
    session_rows: list[dict[str, Any]] = []
    for session, row in schedule.iterrows():
        session_rows.append(
            {
                "session": pd.Timestamp(session).date().isoformat(),
                "market_close_utc": pd.Timestamp(row["market_close"])
                .tz_convert("UTC")
                .isoformat(),
            }
        )

    price_rows: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for ticker, frame in frames.items():
        filtered = frame[frame["session_dt"].isin(schedule_dates)].copy()
        if filtered.empty:
            raise ValueError(f"{ticker} has no rows on authoritative NYSE sessions")
        for _, row in filtered.iterrows():
            volume = row["volume"]
            price_rows.append(
                {
                    "security_id": ticker,
                    "session": pd.Timestamp(row["session_dt"]).date().isoformat(),
                    "total_return_index": float(row["total_return_index"]),
                    "volume": (
                        None
                        if pd.isna(volume)
                        else float(volume)
                    ),
                }
            )
        coverage[ticker] = {
            "rows": int(len(filtered)),
            "start": pd.Timestamp(filtered["session_dt"].min()).date().isoformat(),
            "end": pd.Timestamp(filtered["session_dt"].max()).date().isoformat(),
            "cache_sha256": sha256_file(cache_files[ticker]),
        }

    price_rows.sort(key=lambda x: (x["session"], x["security_id"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    prices_path = out_dir / "prices.jsonl"
    sessions_path = out_dir / "market_sessions.jsonl"
    manifest_path = out_dir / "price_panel_manifest.json"
    write_jsonl(prices_path, price_rows)
    write_jsonl(sessions_path, session_rows)

    manifest_input = None
    if args.price_cache_manifest:
        manifest_input = Path(args.price_cache_manifest)
        if not manifest_input.exists():
            raise FileNotFoundError(manifest_input)

    manifest = {
        "schema": "news-event-alpha-price-panel-v1",
        "research_only": True,
        "price_basis": "YAHOO_ADJUSTED_CLOSE_INDEX",
        "benchmark": benchmark,
        "event_security_count": len(event_tickers),
        "required_security_count": len(required),
        "price_row_count": len(price_rows),
        "nyse_session_count": len(session_rows),
        "coverage": coverage,
        "inputs": {
            "events": {
                "path": str(events_path),
                "sha256": sha256_file(events_path),
            },
            "price_cache_manifest": (
                {
                    "path": str(manifest_input),
                    "sha256": sha256_file(manifest_input),
                }
                if manifest_input is not None
                else None
            ),
        },
        "outputs": {
            "prices": str(prices_path),
            "market_sessions": str(sessions_path),
        },
        "notes": [
            "Adj Close is converted to a normalized adjusted-price index for return calculations.",
            "Raw Close is never substituted when Adj Close is absent.",
            "NYSE schedule comes from pandas_market_calendars and preserves actual UTC close times.",
            "Missing event security or SPY cache fails closed.",
        ],
    }
    manifest["manifest_sha256"] = digest(manifest)
    manifest_path.write_bytes(canonical_bytes(manifest))
    print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
