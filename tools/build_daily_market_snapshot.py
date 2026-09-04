#!/usr/bin/env python3
"""Build a daily market snapshot from the refreshed price cache.

This is a data-plane artifact for daily review. It does not change selection,
scoring, sizing, target books, cash policy, production gates, or live trading.

The snapshot answers a narrow operating question: which latest close, open,
volume, shares outstanding, and close-based market cap were available when the
daily operating refresh was built?
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


CASH_TICKERS = {"", "CASH", "__CASH__", "NAN", "NONE"}
DEFAULT_REQUIRED_TICKERS = ("SPY", "QQQ", "SMH", "SOXX")
SCORE_SORT_COLUMNS = (
    "score_total",
    "concentrated_score",
    "score",
    "relative_strength_composite",
    "oneil_leadership_score",
    "dollar_volume_20d",
    "market_cap_live",
    "mktcap",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in CASH_TICKERS:
        return ""
    return text


def yf_symbol(ticker: str) -> str:
    return clean_ticker(ticker).replace(".", "-")


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, pd.Timestamp)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def collect_book_tickers(paths: list[Path]) -> tuple[list[str], dict[str, set[str]]]:
    sources: dict[str, set[str]] = {}
    ordered: list[str] = []
    for path in paths:
        frame = read_csv(path)
        if frame.empty or "ticker" not in frame.columns:
            continue
        label = str(path).replace("\\", "/")
        for raw in frame["ticker"].tolist():
            ticker = clean_ticker(raw)
            if not ticker:
                continue
            if ticker not in sources:
                sources[ticker] = set()
                ordered.append(ticker)
            sources[ticker].add(label)
    return ordered, sources


def collect_scored_tickers(path: Path, max_rows: int) -> tuple[list[str], dict[str, set[str]]]:
    frame = read_csv(path)
    if frame.empty or "ticker" not in frame.columns or max_rows <= 0:
        return [], {}
    d = frame.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d = d[d["ticker"].ne("")]
    if d.empty:
        return [], {}
    sort_cols = [c for c in SCORE_SORT_COLUMNS if c in d.columns]
    if sort_cols:
        for col in sort_cols:
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
    d = d.drop_duplicates("ticker", keep="first").head(max_rows)
    label = str(path).replace("\\", "/")
    return d["ticker"].tolist(), {ticker: {label} for ticker in d["ticker"].tolist()}


def merge_sources(target: dict[str, set[str]], extra: dict[str, set[str]]) -> None:
    for ticker, labels in extra.items():
        target.setdefault(ticker, set()).update(labels)


def load_latest_price(
    price_cache: Path,
    ticker: str,
    *,
    asof: date | None = None,
) -> dict[str, Any]:
    path = price_cache / px_cache_name(ticker)
    base = {
        "ticker": ticker,
        "price_cache_path": str(path),
        "price_available": False,
        "price_missing_reason": "price_cache_file_missing",
        "latest_price_date": "",
        "open": None,
        "high": None,
        "low": None,
        "previous_close": None,
        "adjusted_close": None,
        "volume": None,
        "dollar_volume": None,
    }
    if not path.exists():
        return base
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        base["price_missing_reason"] = f"price_cache_read_failed:{type(exc).__name__}"
        return base
    if frame.empty:
        base["price_missing_reason"] = "price_cache_empty"
        return base
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    d = frame.copy()
    d.index = pd.to_datetime(d.index, errors="coerce").tz_localize(None)
    d = d[d.index.notna()].sort_index()
    if asof is not None:
        cutoff = pd.Timestamp(asof).normalize()
        d = d[d.index.normalize() <= cutoff]
    if d.empty:
        base["price_missing_reason"] = (
            "price_cache_no_bar_on_or_before_asof"
            if asof is not None
            else "price_dates_invalid"
        )
        return base
    close_col = "Close" if "Close" in d.columns else ("Adj Close" if "Adj Close" in d.columns else "")
    if not close_col:
        base["price_missing_reason"] = "close_column_missing"
        return base
    d[close_col] = pd.to_numeric(d[close_col], errors="coerce")
    d = d[d[close_col].notna()]
    if d.empty:
        base["price_missing_reason"] = "close_values_missing"
        return base
    row = d.iloc[-1]
    close = safe_float(row.get("Close"))
    adj_close = safe_float(row.get("Adj Close"))
    if close is None:
        close = adj_close
    if adj_close is None:
        adj_close = close
    volume = safe_float(row.get("Volume"))
    base.update(
        {
            "price_available": True,
            "price_missing_reason": "",
            "latest_price_date": d.index[-1].date().isoformat(),
            "open": safe_float(row.get("Open")),
            "high": safe_float(row.get("High")),
            "low": safe_float(row.get("Low")),
            "previous_close": close,
            "adjusted_close": adj_close,
            "volume": volume,
            "dollar_volume": (adj_close * volume) if adj_close is not None and volume is not None else None,
        }
    )
    return base


def load_info_cache(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "shares_outstanding",
                "implied_shares_outstanding",
                "yfinance_market_cap",
                "current_price",
                "currency",
                "financial_currency",
                "info_updated_at_utc",
                "info_source",
            ]
        )
    d = frame.copy()
    if "ticker" not in d.columns:
        return pd.DataFrame(columns=frame.columns)
    d["ticker"] = d.get("ticker", "").map(clean_ticker)
    d = d[d["ticker"].ne("")]
    for col in ("shares_outstanding", "implied_shares_outstanding", "yfinance_market_cap", "current_price"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    return d.drop_duplicates("ticker", keep="last")


def info_age_days(value: Any, today: date) -> float | None:
    if value in (None, ""):
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return float((today - dt.astimezone(timezone.utc).date()).days)


def fetch_info_row(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf  # type: ignore

        info = yf.Ticker(yf_symbol(ticker)).info or {}
    except Exception as exc:
        return {
            "ticker": ticker,
            "shares_outstanding": None,
            "implied_shares_outstanding": None,
            "yfinance_market_cap": None,
            "current_price": None,
            "currency": "",
            "financial_currency": "",
            "info_updated_at_utc": now_utc().isoformat(),
            "info_source": f"yfinance_fetch_failed:{type(exc).__name__}",
        }
    return {
        "ticker": ticker,
        "shares_outstanding": safe_float(info.get("sharesOutstanding")),
        "implied_shares_outstanding": safe_float(info.get("impliedSharesOutstanding")),
        "yfinance_market_cap": safe_float(info.get("marketCap")),
        "current_price": safe_float(info.get("currentPrice") or info.get("regularMarketPrice")),
        "currency": str(info.get("currency") or ""),
        "financial_currency": str(info.get("financialCurrency") or ""),
        "info_updated_at_utc": now_utc().isoformat(),
        "info_source": "yfinance_info",
    }


def update_info_cache(
    *,
    tickers: list[str],
    path: Path,
    refresh_days: int,
    no_fetch_live_info: bool,
    max_fetch: int,
    sleep_seconds: float,
    today: date,
) -> pd.DataFrame:
    cache = load_info_cache(path)
    existing = cache.set_index("ticker", drop=False).to_dict("index") if not cache.empty else {}
    fetch: list[str] = []
    for ticker in tickers:
        row = existing.get(ticker)
        age = info_age_days(row.get("info_updated_at_utc"), today) if row else None
        has_mcap = bool(row) and (
            safe_float(row.get("shares_outstanding")) is not None
            or safe_float(row.get("implied_shares_outstanding")) is not None
            or safe_float(row.get("yfinance_market_cap")) is not None
        )
        if (not has_mcap or age is None or age > refresh_days) and not no_fetch_live_info:
            fetch.append(ticker)
    if max_fetch >= 0:
        fetch = fetch[:max_fetch]
    fetched_any = bool(fetch)
    for idx, ticker in enumerate(fetch):
        existing[ticker] = fetch_info_row(ticker)
        if sleep_seconds > 0 and idx + 1 < len(fetch):
            time.sleep(sleep_seconds)
    out = pd.DataFrame(list(existing.values())) if existing else cache
    if fetched_any and not out.empty:
        out["ticker"] = out["ticker"].map(clean_ticker)
        out = out[out["ticker"].ne("")].drop_duplicates("ticker", keep="last").sort_values("ticker")
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(path, index=False)
    return out


def build_rows(
    *,
    tickers: list[str],
    sources: dict[str, set[str]],
    price_cache: Path,
    info: pd.DataFrame,
    benchmark_tickers: set[str],
    today: date,
) -> pd.DataFrame:
    info_map = info.set_index("ticker", drop=False).to_dict("index") if not info.empty else {}
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        price = load_latest_price(price_cache, ticker, asof=today)
        item = dict(price)
        row = info_map.get(ticker, {})
        shares = safe_float(row.get("shares_outstanding"))
        implied_shares = safe_float(row.get("implied_shares_outstanding"))
        yf_mcap = safe_float(row.get("yfinance_market_cap"))
        close = safe_float(item.get("previous_close"))
        adj_close = safe_float(item.get("adjusted_close"))
        shares_used = shares if shares is not None and shares > 0 else implied_shares
        shares_source = "shares_outstanding" if shares is not None and shares > 0 else (
            "implied_shares_outstanding" if implied_shares is not None and implied_shares > 0 else "missing"
        )
        market_cap_close = close * shares_used if close is not None and shares_used is not None else None
        market_cap_adjusted_close = adj_close * shares_used if adj_close is not None and shares_used is not None else None
        market_cap_source = "close_x_shares_outstanding" if shares_source == "shares_outstanding" else (
            "close_x_implied_shares_outstanding" if shares_source == "implied_shares_outstanding" else "missing"
        )
        if market_cap_close is None and yf_mcap is not None:
            market_cap_close = yf_mcap
            market_cap_source = "yfinance_market_cap_fallback"
        info_age = info_age_days(row.get("info_updated_at_utc"), today) if row else None
        price_age = None
        if item.get("latest_price_date"):
            try:
                price_age = float((today - date.fromisoformat(str(item["latest_price_date"]))).days)
            except ValueError:
                price_age = None
        market_cap_usable = market_cap_close is not None and math.isfinite(float(market_cap_close))
        is_benchmark = ticker in benchmark_tickers
        item.update(
            {
                "as_of_date": today.isoformat(),
                "is_benchmark": bool(is_benchmark),
                "input_sources": ";".join(sorted(sources.get(ticker, set()))),
                "shares_outstanding": shares,
                "implied_shares_outstanding": implied_shares,
                "shares_used": shares_used,
                "shares_source": shares_source,
                "market_cap_close": market_cap_close,
                "market_cap_adjusted_close": market_cap_adjusted_close,
                "market_cap_source": market_cap_source,
                "market_cap_usable": bool(market_cap_usable),
                "yfinance_market_cap": yf_mcap,
                "current_price_info": safe_float(row.get("current_price")),
                "currency": str(row.get("currency") or ""),
                "financial_currency": str(row.get("financial_currency") or ""),
                "info_updated_at_utc": str(row.get("info_updated_at_utc") or ""),
                "info_source": str(row.get("info_source") or ""),
                "market_cap_stale_days": info_age,
                "price_stale_days": price_age,
                "selection_usable": bool(item.get("price_available")) and (market_cap_usable or is_benchmark),
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            }
        )
        rows.append(item)
    return pd.DataFrame(rows)


def summarize(
    snapshot: pd.DataFrame,
    *,
    output_dir: Path,
    data_lake_dir: Path,
    asof: date,
    require_exact_asof_close: bool = False,
    generated_at: pd.Timestamp | None = None,
) -> dict[str, Any]:
    price_dates = pd.to_datetime(snapshot.get("latest_price_date", pd.Series(dtype=str)), errors="coerce")
    available = snapshot.get("price_available", pd.Series(dtype=bool)).fillna(False).astype(bool)
    exact = available & price_dates.dt.normalize().eq(pd.Timestamp(asof))
    tickers = snapshot.get("ticker", pd.Series(dtype=str)).fillna("").astype(str)
    missing_exact = sorted(tickers[~exact].tolist()) if len(snapshot) else []
    status = "completed" if len(snapshot) and bool(available.any()) else "blocked"
    if require_exact_asof_close and (not len(snapshot) or missing_exact):
        status = "blocked"
    generated = pd.Timestamp(generated_at) if generated_at is not None else pd.Timestamp(now_utc())
    if generated.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    generated = generated.tz_convert("UTC")
    return {
        "schema_version": "daily-market-snapshot-v1",
        "generated_at_utc": generated.isoformat(),
        "asof_date": asof.isoformat(),
        "status": status,
        "ticker_count": int(len(snapshot)),
        "price_available_count": int(snapshot.get("price_available", pd.Series(dtype=bool)).fillna(False).sum()),
        "market_cap_available_count": int(snapshot.get("market_cap_usable", pd.Series(dtype=bool)).fillna(False).sum()),
        "selection_usable_count": int(snapshot.get("selection_usable", pd.Series(dtype=bool)).fillna(False).sum()),
        "benchmark_count": int(snapshot.get("is_benchmark", pd.Series(dtype=bool)).fillna(False).sum()),
        "latest_price_date_min": price_dates.min().date().isoformat() if price_dates.notna().any() else "",
        "latest_price_date_max": price_dates.max().date().isoformat() if price_dates.notna().any() else "",
        "exact_asof_close_required": bool(require_exact_asof_close),
        "exact_asof_close_count": int(exact.sum()),
        "exact_asof_close_missing_count": len(missing_exact),
        "exact_asof_close_missing_tickers": missing_exact,
        "stale_price_rows_gt_3d": int((pd.to_numeric(snapshot.get("price_stale_days"), errors="coerce") > 3).sum())
        if len(snapshot)
        else 0,
        "stale_market_info_rows_gt_14d": int(
            (pd.to_numeric(snapshot.get("market_cap_stale_days"), errors="coerce") > 14).sum()
        )
        if len(snapshot)
        else 0,
        "market_cap_sources": snapshot.get("market_cap_source", pd.Series(dtype=str)).value_counts(dropna=False).to_dict(),
        "output_dir": str(output_dir),
        "data_lake_dir": str(data_lake_dir),
        "source_label": "daily_market_snapshot",
        "pit_label": "latest_operating_snapshot_not_historical_pit",
        "official_r1000_universe": False,
        "review_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }


def render_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Daily Market Snapshot",
            "",
            f"- status: `{summary.get('status')}`",
            f"- as_of_date: `{summary.get('asof_date')}`",
            f"- ticker_count: `{summary.get('ticker_count')}`",
            f"- price_available_count: `{summary.get('price_available_count')}`",
            f"- market_cap_available_count: `{summary.get('market_cap_available_count')}`",
            f"- selection_usable_count: `{summary.get('selection_usable_count')}`",
            f"- latest_price_date_max: `{summary.get('latest_price_date_max')}`",
            f"- pit_label: `{summary.get('pit_label')}`",
            f"- review_only: `{str(summary.get('review_only')).lower()}`",
            f"- production_mutation_allowed: `{str(summary.get('production_mutation_allowed')).lower()}`",
            "",
            "This artifact is a data freshness and market-cap visibility layer. It does not mutate strategy,",
            "target books, cash policy, production gates, or live trading.",
            "",
        ]
    )


def write_outputs(snapshot: pd.DataFrame, summary: dict[str, Any], output_dir: Path, data_lake_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_lake_dir.mkdir(parents=True, exist_ok=True)
    snapshot.to_csv(output_dir / "market_snapshot.csv", index=False)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    snapshot.to_csv(data_lake_dir / "latest_market_snapshot.csv", index=False)
    manifest = {
        "schema_version": "daily-market-snapshot-manifest-v1",
        "generated_at_utc": summary.get("generated_at_utc"),
        "asof_date": summary.get("asof_date"),
        "latest_price_date_max": summary.get("latest_price_date_max"),
        "row_count": summary.get("ticker_count"),
        "selection_usable_count": summary.get("selection_usable_count"),
        "source_label": summary.get("source_label"),
        "pit_label": summary.get("pit_label"),
        "official_r1000_universe": False,
        "review_only": True,
        "production_mutation_allowed": False,
        "snapshot_csv": str(data_lake_dir / "latest_market_snapshot.csv"),
        "summary_json": str(data_lake_dir / "latest_summary.json"),
    }
    write_json(data_lake_dir / "latest_summary.json", summary)
    write_json(data_lake_dir / "latest_manifest.json", manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--book", action="append", default=[], help="Target/current book CSV with a ticker column.")
    parser.add_argument("--books", nargs="*", default=[], help="Additional target/current book CSVs with ticker columns.")
    parser.add_argument("--scored", default="outputs/scored_latest.csv")
    parser.add_argument("--max-scored", type=int, default=250)
    parser.add_argument("--required-tickers", nargs="*", default=list(DEFAULT_REQUIRED_TICKERS))
    parser.add_argument("--output-dir", default="outputs/daily_market_snapshot")
    parser.add_argument("--data-lake-dir", default="data_pit/free/market_snapshot")
    parser.add_argument("--info-cache", default="data_raw/free/market_snapshot/yf_market_info_cache.csv")
    parser.add_argument("--refresh-info-days", type=int, default=14)
    parser.add_argument("--max-info-fetch", type=int, default=500)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--no-fetch-live-info", action="store_true")
    parser.add_argument("--asof-date", default="")
    parser.add_argument(
        "--require-exact-asof-close",
        action="store_true",
        help=(
            "Fail closed unless every emitted ticker has exactly the requested "
            "as-of session close. Future cache rows are never eligible."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    asof = date.fromisoformat(args.asof_date) if args.asof_date else now_utc().date()
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    data_lake_dir = repo_path(args.data_lake_dir)
    info_cache = repo_path(args.info_cache)
    book_paths = [repo_path(p) for p in [*args.book, *args.books]]
    tickers, sources = collect_book_tickers(book_paths)
    scored_tickers, scored_sources = collect_scored_tickers(repo_path(args.scored), int(args.max_scored))
    for ticker in scored_tickers:
        if ticker not in sources:
            tickers.append(ticker)
    merge_sources(sources, scored_sources)
    required = [clean_ticker(ticker) for ticker in args.required_tickers]
    required = [ticker for ticker in required if ticker]
    for ticker in required:
        if ticker not in sources:
            tickers.append(ticker)
        sources.setdefault(ticker, set()).add("required_ticker")
    seen: set[str] = set()
    tickers = [ticker for ticker in tickers if not (ticker in seen or seen.add(ticker))]
    info = update_info_cache(
        tickers=tickers,
        path=info_cache,
        refresh_days=int(args.refresh_info_days),
        no_fetch_live_info=bool(args.no_fetch_live_info),
        max_fetch=int(args.max_info_fetch),
        sleep_seconds=float(args.sleep_seconds),
        today=asof,
    )
    snapshot = build_rows(
        tickers=tickers,
        sources=sources,
        price_cache=price_cache,
        info=info,
        benchmark_tickers=set(required),
        today=asof,
    )
    summary = summarize(
        snapshot,
        output_dir=output_dir,
        data_lake_dir=data_lake_dir,
        asof=asof,
        require_exact_asof_close=bool(args.require_exact_asof_close),
    )
    write_outputs(snapshot, summary, output_dir, data_lake_dir)
    print(json.dumps({"status": summary["status"], "ticker_count": summary["ticker_count"], "output_dir": str(output_dir)}))
    return 0 if summary["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
