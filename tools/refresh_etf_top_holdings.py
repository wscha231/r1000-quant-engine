#!/usr/bin/env python3
"""Refresh thematic ETF top holdings (D-2 v2, F7).

Reads `thematic_etf_universe.yaml` etf_sources, fetches each ETF's top-N
holdings via yfinance funds_data.top_holdings, and rewrites the
`thematic_etf_universe:` list in place. Falls back to keeping the
existing yaml when fetch fails (silent rollback per the risk plan).

Filters:
  - US-listed only (skip tickers containing `.` like 3443.TW)
  - Skip leveraged/inverse/bond patterns from exclude_patterns
  - mktcap floor optional (default off; downstream liquidity gate
    handles real filtering)
  - Per-ETF cap (default N=5)

Outputs:
  - thematic_etf_universe.yaml updated in place (when --apply)
  - outputs/etf_holdings_history/<date>.csv snapshot (always when run)
  - outputs/etf_holdings_history/refresh_summary.json (always)

Usage:
  python tools/refresh_etf_top_holdings.py --apply  # writes yaml
  python tools/refresh_etf_top_holdings.py --dry-run  # prints proposal only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_TOP_N = 5
US_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]*$")


def fetch_etf_top_holdings(etf_ticker: str, top_n: int = DEFAULT_TOP_N) -> list[dict[str, Any]]:
    """Primary fetch: yfinance funds_data.top_holdings. Returns list of
    {ticker, name, weight} dicts. Empty list on failure.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(etf_ticker)
        fd = getattr(t, "funds_data", None)
        if fd is None:
            return []
        th = getattr(fd, "top_holdings", None)
        if th is None or th.empty:
            return []
        rows: list[dict[str, Any]] = []
        for idx, row in th.head(top_n * 2).iterrows():  # over-fetch then filter
            ticker = str(idx).upper().strip()
            if "." in ticker or "-" in ticker[:1]:
                continue  # skip foreign / non-US tickers
            if not US_TICKER_RE.match(ticker):
                continue
            if len(ticker) > 6:
                continue
            name = str(row.get("Name", "")) if "Name" in row else ""
            weight = float(row.get("Holding Percent", 0.0)) if "Holding Percent" in row else 0.0
            rows.append({"ticker": ticker, "name": name, "weight": weight})
            if len(rows) >= top_n:
                break
        return rows
    except Exception as exc:
        print(f"[etf-refresh] yfinance fetch failed for {etf_ticker}: {exc}", file=sys.stderr)
        return []


def matches_exclude_pattern(ticker: str, name: str, patterns: list[str]) -> bool:
    text = f"{ticker} {name}".upper()
    for pat in patterns:
        try:
            if re.search(pat, text, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def refresh(
    *,
    yaml_path: Path,
    output_dir: Path,
    top_n: int,
    apply: bool,
) -> dict[str, Any]:
    """Refresh the thematic ETF universe from yfinance top holdings.

    Returns the summary payload. If `apply` is True, also rewrites the
    `thematic_etf_universe:` list in the yaml file.
    """
    import yaml
    try:
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": f"yaml load failed: {exc}",
            "yaml_path": str(yaml_path),
        }
    etf_sources = payload.get("etf_sources") or []
    exclude_patterns = payload.get("exclude_patterns") or []
    existing_overlay = payload.get("thematic_etf_universe") or []
    existing_tickers_by_etf: dict[str, list[str]] = {}
    for entry in existing_overlay:
        if isinstance(entry, dict):
            src = str(entry.get("source_etf", "")).upper()
            tk = str(entry.get("ticker", "")).upper()
            existing_tickers_by_etf.setdefault(src, []).append(tk)

    fresh: list[dict[str, Any]] = []
    per_etf_diagnostics: dict[str, Any] = {}
    fetched_etfs = 0
    fetch_failed_etfs = 0
    for source in etf_sources:
        if not isinstance(source, dict):
            continue
        etf_ticker = str(source.get("ticker", "")).upper().strip()
        if not etf_ticker:
            continue
        theme = str(source.get("theme", "thematic"))
        rows = fetch_etf_top_holdings(etf_ticker, top_n=top_n)
        per_etf_diagnostics[etf_ticker] = {
            "theme": theme,
            "fetched": len(rows),
            "tickers": [r["ticker"] for r in rows],
        }
        if not rows:
            fetch_failed_etfs += 1
            # Carry over existing entries for this source_etf so silent rollback works.
            for entry in existing_overlay:
                if isinstance(entry, dict) and str(entry.get("source_etf", "")).upper() == etf_ticker:
                    fresh.append({k: v for k, v in entry.items()})
            continue
        fetched_etfs += 1
        for r in rows:
            ticker = r["ticker"]
            name = r["name"]
            if matches_exclude_pattern(ticker, name, exclude_patterns):
                continue
            fresh.append({
                "ticker": ticker,
                "name": name,
                "theme": theme,
                "source_etf": etf_ticker,
                "domicile": "US",
                "etf_weight": float(r.get("weight", 0.0)),
            })

    # Dedupe by ticker (keep first occurrence).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in fresh:
        tk = entry["ticker"]
        if tk in seen:
            continue
        seen.add(tk)
        deduped.append(entry)

    snapshot_dir = output_dir / "etf_holdings_history"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snapshot_path = snapshot_dir / f"{snapshot_date}.csv"
    import pandas as pd
    pd.DataFrame(deduped).to_csv(snapshot_path, index=False)

    summary = {
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "yaml_path": str(yaml_path),
        "etf_count": len(etf_sources),
        "etfs_fetched_ok": fetched_etfs,
        "etfs_fetch_failed": fetch_failed_etfs,
        "fresh_holdings_count": len(deduped),
        "existing_holdings_count": len(existing_overlay),
        "snapshot_path": str(snapshot_path),
        "apply": apply,
        "per_etf_diagnostics": per_etf_diagnostics,
    }
    summary_path = snapshot_dir / "refresh_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    if apply and fetched_etfs > 0:
        # Only rewrite the yaml if at least one ETF fetch succeeded -- otherwise
        # we'd wipe the entire universe to empty on a network failure.
        payload["thematic_etf_universe"] = deduped
        payload["_refresh_notes"] = {
            "last_refresh_utc": summary["generated_at_utc"],
            "etfs_fetched_ok": fetched_etfs,
            "etfs_fetch_failed": fetch_failed_etfs,
        }
        yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        summary["yaml_rewritten"] = True
    else:
        summary["yaml_rewritten"] = False
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", default="thematic_etf_universe.yaml")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="rewrite the yaml in place")
    g.add_argument("--dry-run", action="store_true", help="don't rewrite, just snapshot + summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    yaml_path = Path(args.yaml) if Path(args.yaml).is_absolute() else REPO_ROOT / args.yaml
    output_dir = Path(args.output_dir) if Path(args.output_dir).is_absolute() else REPO_ROOT / args.output_dir
    summary = refresh(
        yaml_path=yaml_path,
        output_dir=output_dir,
        top_n=args.top_n,
        apply=bool(args.apply),
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
