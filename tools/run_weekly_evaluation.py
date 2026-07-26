#!/usr/bin/env python3
"""Weekly mark-to-market evaluation for monthly portfolio replay books.

This sidecar does not change production selection or rebalance cadence. It
uses the existing monthly holding books and daily price cache to create a
weekly equity view, plus a freshness audit that makes reporting lag explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CASH_TICKERS = {"CASH", "__CASH__"}
CONCENTRATED_CHAMPION_FILTERS = {
    "target_stock_names": "3",
    "weighting_mode": "score_power",
    "active_rebalance_interval_months": "1",
}


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(str(ticker).upper().encode('utf-8')).hexdigest()[:16]}.parquet"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.date().isoformat() if pd.notna(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value) if not isinstance(value, (dict, list, tuple, str)) else False:
        return None
    return value


def load_price_series(
    price_cache: Path,
    ticker: str,
    *,
    include_liquidity: bool = False,
) -> pd.DataFrame:
    path = price_cache / px_cache_name(ticker)
    if not path.exists():
        return pd.DataFrame()
    try:
        px = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if px.empty:
        return pd.DataFrame()
    px = px.copy()
    px.index = pd.to_datetime(px.index, errors="coerce").tz_localize(None)
    px = px[px.index.notna()].sort_index()
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in px.columns else "Close"
    if close_col not in px.columns:
        return pd.DataFrame()
    out = pd.DataFrame(index=px.index)
    out["close"] = pd.to_numeric(px[close_col], errors="coerce")
    raw_close = pd.to_numeric(
        px["Close"] if "Close" in px.columns else px[close_col],
        errors="coerce",
    )
    adjustment = pd.Series(1.0, index=px.index, dtype=float)
    if "Adj Close" in px.columns and "Close" in px.columns:
        adjustment = pd.to_numeric(px["Adj Close"], errors="coerce") / raw_close.replace(
            0, np.nan
        )
    price_fields = [("Open", "open")]
    if include_liquidity:
        price_fields.extend([("High", "high"), ("Low", "low")])
    for source, target in price_fields:
        if source in px.columns:
            out[target] = pd.to_numeric(px[source], errors="coerce") * adjustment
    if "open" not in out.columns:
        out["open"] = out["close"]
    if include_liquidity and "Volume" in px.columns:
        volume = pd.to_numeric(px["Volume"], errors="coerce")
        out["volume"] = volume
        # Dollar ADV must stay on the contemporaneous price scale. Multiplying
        # split/dividend-adjusted close by raw volume can distort historical
        # liquidity, so preserve raw close * raw shares explicitly.
        out["dollar_volume"] = raw_close * volume
    return out.dropna(how="all")


def price_on_or_after(px: pd.DataFrame, date_like: Any, column: str) -> tuple[pd.Timestamp | None, float | None]:
    if px.empty or column not in px.columns:
        return None, None
    dt = pd.Timestamp(date_like)
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(dt, side="left"))
    if pos >= len(idx):
        return None, None
    actual = pd.Timestamp(idx[pos])
    val = float(px[column].iloc[pos])
    if not np.isfinite(val) or val <= 0:
        return None, None
    return actual, val


def price_on_or_before(px: pd.DataFrame, date_like: Any, column: str) -> tuple[pd.Timestamp | None, float | None]:
    if px.empty or column not in px.columns:
        return None, None
    dt = pd.Timestamp(date_like)
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(dt, side="right")) - 1
    if pos < 0:
        return None, None
    actual = pd.Timestamp(idx[pos])
    val = float(px[column].iloc[pos])
    if not np.isfinite(val) or val <= 0:
        return None, None
    return actual, val


def filter_concentrated_champion(df: pd.DataFrame, portfolio_kind: str) -> pd.DataFrame:
    if portfolio_kind != "concentrated" or df.empty:
        return df
    out = df.copy()
    for col, expected in CONCENTRATED_CHAMPION_FILTERS.items():
        if col not in out.columns:
            continue
        values = out[col].astype(str).str.strip()
        mask = values.eq(expected)
        if mask.any():
            out = out[mask].copy()
    return out


def normalize_holdings(df: pd.DataFrame, portfolio_kind: str) -> pd.DataFrame:
    if df.empty or "rebalance_date" not in df.columns or "ticker" not in df.columns:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight", "portfolio_kind"])
    d = filter_concentrated_champion(df.copy(), portfolio_kind)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d.get("weight"), errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[d["ticker"].ne("")]
    d = d[d["weight"] > 1e-12]
    d["portfolio_kind"] = portfolio_kind
    keep = [c for c in ["rebalance_date", "ticker", "weight", "portfolio_kind", "Name", "sector"] if c in d.columns]
    out = d[keep].copy()
    out = out.groupby(["portfolio_kind", "rebalance_date", "ticker"], as_index=False).agg(
        {
            "weight": "sum",
            **({"Name": "last"} if "Name" in out.columns else {}),
            **({"sector": "last"} if "sector" in out.columns else {}),
        }
    )
    return out.sort_values(["portfolio_kind", "rebalance_date", "weight"], ascending=[True, True, False])


def period_end_map(path: Path) -> dict[pd.Timestamp, pd.Timestamp]:
    d = _read_csv(path)
    if d.empty or "rebalance_date" not in d.columns or "next_rebalance_date" not in d.columns:
        return {}
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["next_rebalance_date"] = pd.to_datetime(d["next_rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date", "next_rebalance_date"])
    return {
        pd.Timestamp(r.rebalance_date): pd.Timestamp(r.next_rebalance_date)
        for r in d.drop_duplicates("rebalance_date", keep="last").itertuples(index=False)
    }


def weekly_targets(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    if pd.isna(start) or pd.isna(end) or end < start:
        return []
    targets = list(pd.date_range(start=start, end=end, freq="W-FRI"))
    if not targets or pd.Timestamp(targets[-1]).normalize() < pd.Timestamp(end).normalize():
        targets.append(pd.Timestamp(end))
    clean = sorted({pd.Timestamp(x).normalize() for x in targets if pd.notna(x)})
    return clean


def latest_price_date(prices: dict[str, pd.DataFrame], tickers: list[str]) -> pd.Timestamp | None:
    dates: list[pd.Timestamp] = []
    for ticker in tickers:
        px = prices.get(ticker, pd.DataFrame())
        if px.empty:
            continue
        idx = pd.to_datetime(px.index, errors="coerce").dropna()
        if not idx.empty:
            dates.append(pd.Timestamp(idx.max()).normalize())
    return max(dates) if dates else None


def build_weekly_curve(
    holdings: pd.DataFrame,
    next_dates: dict[pd.Timestamp, pd.Timestamp],
    price_cache: Path,
    portfolio_kind: str,
    benchmark_tickers: tuple[str, ...] = ("SPY", "QQQ"),
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if holdings.empty:
        return pd.DataFrame(), {"status": "missing_holdings", "portfolio_kind": portfolio_kind}
    prices: dict[str, pd.DataFrame] = {}
    tickers = sorted(set(holdings["ticker"].astype(str).str.upper()) - CASH_TICKERS)
    for ticker in tickers + list(benchmark_tickers):
        if ticker not in prices:
            prices[ticker] = load_price_series(price_cache, ticker)

    rows: list[dict[str, Any]] = []
    equity = 1.0
    prev_rebalance_dates = sorted(pd.to_datetime(holdings["rebalance_date"], errors="coerce").dropna().unique())
    latest_px_date = latest_price_date(prices, tickers)
    for i, raw_dt in enumerate(prev_rebalance_dates):
        dt = pd.Timestamp(raw_dt)
        period_holdings = holdings[pd.to_datetime(holdings["rebalance_date"], errors="coerce").eq(dt)].copy()
        if period_holdings.empty:
            continue
        if dt in next_dates:
            scheduled_end_dt = next_dates[dt]
        elif i + 1 < len(prev_rebalance_dates):
            scheduled_end_dt = pd.Timestamp(prev_rebalance_dates[i + 1])
        else:
            scheduled_end_dt = latest_px_date
        if scheduled_end_dt is None or pd.isna(scheduled_end_dt):
            continue
        end_dt = pd.Timestamp(scheduled_end_dt).normalize()
        final_period_extension = False
        if i == len(prev_rebalance_dates) - 1 and latest_px_date is not None and latest_px_date > end_dt:
            end_dt = latest_px_date
            final_period_extension = True
        entry_dt = dt + pd.Timedelta(days=1)
        stock_weight = float(period_holdings.loc[~period_holdings["ticker"].isin(CASH_TICKERS), "weight"].sum())
        explicit_cash = float(period_holdings.loc[period_holdings["ticker"].isin(CASH_TICKERS), "weight"].sum())
        cash_weight = float(np.clip(explicit_cash + max(0.0, 1.0 - stock_weight - explicit_cash), 0.0, 1.0))
        start_prices: dict[str, float] = {}
        start_actuals: dict[str, pd.Timestamp] = {}
        for row in period_holdings.itertuples(index=False):
            ticker = str(row.ticker).upper()
            if ticker in CASH_TICKERS:
                continue
            actual, price = price_on_or_after(prices.get(ticker, pd.DataFrame()), entry_dt, "open")
            if actual is not None and price is not None:
                start_prices[ticker] = float(price)
                start_actuals[ticker] = actual
        if not start_prices and stock_weight > 1e-8:
            continue
        prev_period_rel = 1.0
        for target in weekly_targets(entry_dt, end_dt):
            period_rel = cash_weight
            missing = 0
            actual_week_dates: list[pd.Timestamp] = []
            for row in period_holdings.itertuples(index=False):
                ticker = str(row.ticker).upper()
                weight = float(row.weight)
                if ticker in CASH_TICKERS:
                    continue
                entry_price = start_prices.get(ticker)
                if entry_price is None:
                    missing += 1
                    period_rel += weight
                    continue
                actual_end, end_price = price_on_or_before(prices.get(ticker, pd.DataFrame()), target, "close")
                if actual_end is None or end_price is None or actual_end < start_actuals.get(ticker, entry_dt):
                    missing += 1
                    period_rel += weight
                    continue
                actual_week_dates.append(actual_end)
                period_rel += weight * (float(end_price) / float(entry_price))
            if not np.isfinite(period_rel) or period_rel <= 0:
                continue
            weekly_return = period_rel / max(prev_period_rel, 1e-12) - 1.0
            equity *= 1.0 + weekly_return
            prev_period_rel = period_rel
            row_payload: dict[str, Any] = {
                "portfolio_kind": portfolio_kind,
                "week_end_date": max(actual_week_dates).date().isoformat() if actual_week_dates else target.date().isoformat(),
                "target_week_end_date": target.date().isoformat(),
                "rebalance_date": dt.date().isoformat(),
                "period_end_date": pd.Timestamp(end_dt).date().isoformat(),
                "scheduled_period_end_date": pd.Timestamp(scheduled_end_dt).date().isoformat(),
                "final_period_extension": bool(final_period_extension and target > pd.Timestamp(scheduled_end_dt).normalize()),
                "weekly_return": float(weekly_return),
                "period_return_since_rebalance": float(period_rel - 1.0),
                "equity": float(equity),
                "cash_weight": float(cash_weight),
                "stock_weight": float(stock_weight),
                "selected_names": int((~period_holdings["ticker"].isin(CASH_TICKERS)).sum()),
                "missing_price_count": int(missing),
            }
            for bench in benchmark_tickers:
                bench_px = prices.get(bench, pd.DataFrame())
                b0_dt, b0 = price_on_or_after(bench_px, entry_dt, "open")
                b1_dt, b1 = price_on_or_before(bench_px, target, "close")
                if b0_dt is not None and b1_dt is not None and b0 and b1 and b1_dt >= b0_dt:
                    row_payload[f"{bench.lower()}_period_return_since_rebalance"] = float(b1 / b0 - 1.0)
            rows.append(row_payload)
    curve = pd.DataFrame(rows)
    if curve.empty:
        return curve, {"status": "no_weekly_rows", "portfolio_kind": portfolio_kind, "input_rebalance_count": len(prev_rebalance_dates)}
    curve["week_end_date"] = pd.to_datetime(curve["week_end_date"], errors="coerce")
    curve = curve.dropna(subset=["week_end_date"]).drop_duplicates(["portfolio_kind", "week_end_date"], keep="last")
    curve = curve.sort_values("week_end_date").reset_index(drop=True)
    metrics = weekly_metrics(curve, portfolio_kind)
    return curve, metrics


def weekly_metrics(curve: pd.DataFrame, portfolio_kind: str) -> dict[str, Any]:
    if curve.empty:
        return {"status": "empty", "portfolio_kind": portfolio_kind}
    returns = pd.to_numeric(curve["weekly_return"], errors="coerce").dropna()
    equity = pd.to_numeric(curve["equity"], errors="coerce").dropna()
    dates = pd.to_datetime(curve["week_end_date"], errors="coerce").dropna()
    if returns.empty or equity.empty or dates.empty:
        return {"status": "empty", "portfolio_kind": portfolio_kind}
    years = max((dates.max() - dates.min()).days / 365.25, len(returns) / 52.0, 1e-6)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    vol_ann = float(returns.std(ddof=0) * math.sqrt(52.0))
    sharpe = float((returns.mean() * 52.0) / (vol_ann + 1e-12))
    dd = equity / equity.cummax() - 1.0
    final_extensions = curve[curve.get("final_period_extension", False).astype(bool)] if "final_period_extension" in curve.columns else pd.DataFrame()
    return {
        "status": "completed",
        "portfolio_kind": portfolio_kind,
        "evaluation_granularity": "weekly_mark_to_market",
        "production_selection_changed": False,
        "uses_monthly_holding_books": True,
        "true_weekly_scoring": False,
        "weeks": int(len(returns)),
        "start_date": dates.min().date().isoformat(),
        "end_date": dates.max().date().isoformat(),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": float(dd.min()),
        "vol_ann": vol_ann,
        "ending_equity": float(equity.iloc[-1]),
        "avg_cash_weight": float(pd.to_numeric(curve.get("cash_weight"), errors="coerce").mean()),
        "avg_stock_weight": float(pd.to_numeric(curve.get("stock_weight"), errors="coerce").mean()),
        "max_stock_weight": float(pd.to_numeric(curve.get("stock_weight"), errors="coerce").max()),
        "avg_missing_price_count": float(pd.to_numeric(curve.get("missing_price_count"), errors="coerce").mean()),
        "uses_stale_final_holdings_extension": bool(not final_extensions.empty),
        "extension_start_date": (
            pd.to_datetime(final_extensions["week_end_date"], errors="coerce").min().date().isoformat()
            if not final_extensions.empty
            else None
        ),
    }


def latest_date_from_csv(path: Path, candidates: tuple[str, ...]) -> str | None:
    d = _read_csv(path)
    if d.empty:
        return None
    for col in candidates:
        if col in d.columns:
            s = pd.to_datetime(d[col], errors="coerce").dropna()
            if not s.empty:
                return s.max().date().isoformat()
    return None


def build_freshness(
    latest_run: Path,
    curves: dict[str, pd.DataFrame],
    metrics: dict[str, dict[str, Any]],
    stale_days_threshold: int,
) -> dict[str, Any]:
    latest_scored = latest_date_from_csv(latest_run / "scored_latest.csv", ("rebalance_date", "feature_date"))
    latest_portfolio = latest_date_from_csv(latest_run / "portfolio_latest.csv", ("rebalance_date", "feature_date", "last_trade_date"))
    latest_eval_dates = {}
    for name, curve in curves.items():
        if curve.empty:
            latest_eval_dates[name] = None
        else:
            latest_eval_dates[name] = pd.to_datetime(curve["week_end_date"], errors="coerce").max().date().isoformat()
    primary_eval = latest_eval_dates.get("main") or next((v for v in latest_eval_dates.values() if v), None)
    lag_days = None
    if latest_scored and primary_eval:
        lag_days = int((pd.Timestamp(latest_scored) - pd.Timestamp(primary_eval)).days)
    status = "ok"
    if lag_days is None:
        status = "unknown"
    elif lag_days > int(stale_days_threshold):
        status = "stale"
    unified = _read_json(latest_run / "orchestrator" / "unified_target_latest.json")
    raw_portfolio = _read_csv(latest_run / "portfolio_latest.csv")
    raw_portfolio_cash_target = None
    if not raw_portfolio.empty and "cash_target" in raw_portfolio.columns:
        cash_values = pd.to_numeric(raw_portfolio["cash_target"], errors="coerce").dropna()
        if not cash_values.empty:
            raw_portfolio_cash_target = float(cash_values.max())
    return {
        "status": status,
        "stale_days_threshold": int(stale_days_threshold),
        "latest_scored_date": latest_scored,
        "latest_portfolio_date": latest_portfolio,
        "latest_weekly_eval_dates": latest_eval_dates,
        "primary_weekly_eval_date": primary_eval,
        "scored_vs_weekly_eval_lag_days": lag_days,
        "latest_raw_portfolio_cash_target": raw_portfolio_cash_target,
        "latest_unified_target": {
            "cash_target": unified.get("cash_target"),
            "by_mandate_capacity": unified.get("by_mandate_capacity"),
            "invested_amount": (unified.get("audit_checks") or {}).get("invested_amount"),
            "n_positions": (unified.get("audit_checks") or {}).get("n_positions"),
        } if unified else {},
        "explanation": (
            "Weekly evaluation is mark-to-market on monthly holding books. "
            "The final available monthly holding book can be extended to the latest cached price date, "
            "but true production promotion still requires true weekly scored snapshots."
        ),
        "metrics": metrics,
    }


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# Weekly Evaluation Freshness Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- latest_scored_date: `{payload.get('latest_scored_date')}`",
        f"- primary_weekly_eval_date: `{payload.get('primary_weekly_eval_date')}`",
        f"- scored_vs_weekly_eval_lag_days: `{payload.get('scored_vs_weekly_eval_lag_days')}`",
        f"- stale_days_threshold: `{payload.get('stale_days_threshold')}`",
        f"- latest_raw_portfolio_cash_target: `{payload.get('latest_raw_portfolio_cash_target')}`",
        f"- latest_unified_cash_target: `{(payload.get('latest_unified_target') or {}).get('cash_target')}`",
        "",
        "## Portfolio Metrics",
    ]
    for name, metric in (payload.get("metrics") or {}).items():
        lines.extend(
            [
                "",
                f"### {name}",
                f"- status: `{metric.get('status')}`",
                f"- weeks: `{metric.get('weeks')}`",
                f"- range: `{metric.get('start_date')}` -> `{metric.get('end_date')}`",
                f"- CAGR: `{metric.get('cagr')}`",
                f"- Sharpe: `{metric.get('sharpe')}`",
                f"- MaxDD: `{metric.get('max_dd')}`",
                f"- avg_cash_weight: `{metric.get('avg_cash_weight')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Notes",
            "- This sidecar does not alter production portfolio selection.",
            "- Monthly backtest labels can lag because they need a next rebalance date to realize returns.",
            "- A stale status means the engine needs true weekly scored snapshots, not just a display fix.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(latest_run: Path, output_dir: Path, price_cache: Path, stale_days_threshold: int = 10) -> dict[str, Any]:
    latest_run = Path(latest_run)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    price_cache = Path(price_cache)

    main_holdings = normalize_holdings(_read_csv(latest_run / "reports" / "main_monthly_weights.csv"), "main")
    concentrated_holdings = normalize_holdings(
        _read_csv(latest_run / "reports" / "concentrated_strategy_holdings.csv"),
        "concentrated",
    )
    sources = {
        "main": (
            main_holdings,
            period_end_map(latest_run / "reports" / "regime_by_month.csv"),
        ),
        "concentrated": (
            concentrated_holdings,
            period_end_map(latest_run / "reports" / "concentrated_strategy_monthly.csv"),
        ),
    }
    curves: dict[str, pd.DataFrame] = {}
    metrics: dict[str, dict[str, Any]] = {}
    for name, (holdings, next_dates) in sources.items():
        curve, metric = build_weekly_curve(holdings, next_dates, price_cache, name)
        curves[name] = curve
        metrics[name] = metric
        if not curve.empty:
            curve.to_csv(output_dir / f"{name}_weekly_equity_curve.csv", index=False)
    combined = pd.concat([c for c in curves.values() if not c.empty], ignore_index=True) if any(not c.empty for c in curves.values()) else pd.DataFrame()
    if not combined.empty:
        combined.sort_values(["portfolio_kind", "week_end_date"]).to_csv(output_dir / "weekly_equity_curve.csv", index=False)
    freshness = build_freshness(latest_run, curves, metrics, stale_days_threshold=stale_days_threshold)
    (output_dir / "weekly_metrics.json").write_text(json.dumps(metrics, indent=2, default=_json_default), encoding="utf-8")
    (output_dir / "weekly_freshness_audit.json").write_text(
        json.dumps(freshness, indent=2, default=_json_default),
        encoding="utf-8",
    )
    write_markdown(freshness, output_dir / "weekly_freshness_audit.md")
    return freshness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly mark-to-market evaluation from monthly holding books.")
    parser.add_argument("--latest-run", type=Path, default=Path("outputs"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/weekly_evaluation"))
    parser.add_argument("--price-cache", type=Path, default=Path("cache_prices"))
    parser.add_argument("--stale-days-threshold", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args.latest_run, args.output_dir, args.price_cache, args.stale_days_threshold)
    print(json.dumps(payload, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
