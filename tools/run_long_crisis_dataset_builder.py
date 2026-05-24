#!/usr/bin/env python3
"""Build the research-only 1990+ long crisis/liquidity dataset.

The output includes future drawdown labels for research. Downstream live or
broker-replay tools must not consume columns beginning with `future_`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_long_crisis_liquidity import build_long_crisis_features  # noqa: E402


DEFAULT_OUTPUT = "data_pit/macro/long_crisis_daily_features.parquet"
DEFAULT_REPORT_DIR = "outputs/long_crisis_learning"

FRED_SERIES = {
    "sp500": ("sp500", "SP500"),
    "vix": ("vix", "VIXCLS"),
    "dgs10": ("dgs10", "DGS10"),
    "hy_oas": ("hy_oas", "BAMLH0A0HYM2"),
    "dxy": ("dxy", "DTWEXBGS"),
    "m2": ("m2", "M2SL"),
    "fed_assets": ("fed_assets", "WALCL"),
    "reverse_repo": ("reverse_repo", "RRPTSYD"),
    "reverse_repo_alt": ("reverse_repo", "RRPONTSYD"),
    "tga": ("tga", "WDTGAL"),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(str(ticker).upper().encode('utf-8')).hexdigest()[:16]}.parquet"


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def load_price_close(cache_prices: Path, ticker: str) -> pd.Series:
    candidates = [
        cache_prices / px_cache_name(ticker),
        cache_prices / f"{ticker}.parquet",
        cache_prices / f"{ticker.replace('^', '')}.parquet",
        cache_prices / f"{ticker.replace('^', 'idx_')}.parquet",
    ]
    for path in candidates:
        df = read_parquet(path)
        if df.empty:
            continue
        if "Date" in df.columns:
            df = df.set_index("Date")
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()]
        for col in ("Adj Close", "adj_close", "Close", "close"):
            if col in df.columns:
                s = pd.to_numeric(df[col], errors="coerce").dropna()
                s.name = ticker
                return s.sort_index()
    return pd.Series(dtype=float)


def load_fred(cache_macro: Path, name: str, series_id: str) -> pd.Series:
    candidates = [
        cache_macro / f"fred_{name}_{series_id}.parquet",
        cache_macro / f"{name}.parquet",
        cache_macro / f"{series_id}.parquet",
    ]
    for path in candidates:
        df = read_parquet(path)
        if df.empty:
            continue
        if "value" in df.columns:
            date_values = df["date"] if "date" in df.columns else df.index
            idx = pd.to_datetime(date_values, errors="coerce")
            s = pd.to_numeric(df["value"], errors="coerce")
        elif len(df.columns) == 1:
            idx = pd.to_datetime(df.index, errors="coerce")
            s = pd.to_numeric(df.iloc[:, 0], errors="coerce")
        else:
            continue
        out = pd.Series(s.values, index=idx, name=name).dropna()
        out = out[~out.index.isna()].sort_index()
        if not out.empty:
            return out
    return pd.Series(dtype=float)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Long Crisis/Liquidity Dataset",
        "",
        "Research-only 1990+ crisis and liquidity feature panel.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- rows: {summary.get('rows', 0)}",
        f"- first date: `{summary.get('first_date')}`",
        f"- last date: `{summary.get('last_date')}`",
        f"- production activation allowed: `{summary.get('production_activation_allowed')}`",
        "",
        "## Sources",
        "",
        "| source | rows |",
        "| --- | ---: |",
    ]
    for name, rows in (summary.get("source_rows") or {}).items():
        lines.append(f"| {name} | {rows} |")
    lines.extend(
        [
            "",
            "Future drawdown columns are labels for research only and must not feed live features.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    base = repo_path(args.base_dir) if args.base_dir else REPO_ROOT
    cache_prices = repo_path(args.cache_prices) if args.cache_prices else base / "cache_prices"
    cache_macro = repo_path(args.cache_macro) if args.cache_macro else base / "cache_macro"
    output_path = repo_path(args.output)
    report_dir = repo_path(args.report_dir)

    market = load_price_close(cache_prices, "SPY")
    market_source = "SPY"
    if market.empty:
        market = load_price_close(cache_prices, "^GSPC")
        market_source = "^GSPC"
    fred_sp500 = load_fred(cache_macro, *FRED_SERIES["sp500"])
    if market.empty and not fred_sp500.empty:
        market = fred_sp500
        market_source = "FRED:SP500"

    qqq = load_price_close(cache_prices, "QQQ")
    macro: dict[str, pd.Series] = {}
    source_rows: dict[str, int] = {
        "market_" + market_source: int(len(market)),
        "qqq": int(len(qqq)),
    }
    for key, (name, series_id) in FRED_SERIES.items():
        if key == "sp500":
            continue
        s = load_fred(cache_macro, name, series_id)
        if key == "reverse_repo_alt" and macro.get("reverse_repo", pd.Series(dtype=float)).empty:
            macro["reverse_repo"] = s
            source_rows["reverse_repo_alt_" + series_id] = int(len(s))
            continue
        if key == "reverse_repo_alt":
            continue
        macro[name] = s
        source_rows[f"{name}_{series_id}"] = int(len(s))

    features = build_long_crisis_features(
        market,
        macro,
        qqq_close=qqq,
        start=args.start,
        end=args.end or None,
        m2_lag_months=int(args.m2_lag_months),
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    if features.empty:
        summary = {
            "status": "blocked",
            "reason": "missing broad market price series; need SPY, ^GSPC, or FRED SP500 cache",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "production_activation_allowed": False,
            "source_rows": source_rows,
        }
        write_json(report_dir / "summary.json", summary)
        (report_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
        print(json.dumps({"status": "blocked", "reason": summary["reason"]}, sort_keys=True))
        return summary

    output_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(output_path, index=True)
    liquidity_path = report_dir / "liquidity_regime_by_day.parquet"
    regime_cols = [
        c for c in (
            "liquidity_confirmation_score",
            "cash_raise_confirmation_score",
            "market_trend_damage_score",
            "credit_stress_score",
            "crisis_score",
            "split",
        )
        if c in features.columns
    ]
    features[regime_cols].to_parquet(liquidity_path, index=True)
    summary = {
        "status": "completed",
        "schema_version": "long-crisis-liquidity-dataset-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "rows": int(len(features)),
        "first_date": features.index.min().date().isoformat(),
        "last_date": features.index.max().date().isoformat(),
        "source_rows": source_rows,
        "output": str(output_path),
        "liquidity_regime_by_day": str(liquidity_path),
        "columns": sorted(features.columns.tolist()),
    }
    write_json(report_dir / "summary.json", summary)
    (report_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"status": "completed", "rows": int(len(features)), "output": str(output_path)}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default="")
    parser.add_argument("--cache-prices", default="")
    parser.add_argument("--cache-macro", default="")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--start", default="1990-01-01")
    parser.add_argument("--end", default="")
    parser.add_argument("--m2-lag-months", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

