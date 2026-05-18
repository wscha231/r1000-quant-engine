#!/usr/bin/env python3
"""Diagnose hold-vs-replace mistakes from broker-ledger trades.

This report is diagnostic only. It pairs SELL trades with nearby BUY trades and
compares post-trade forward returns using only price-cache bars after the fill
date. The result explains churn and wrong substitutions; it must never be used
inside target-book selection.
"""
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

from tools.run_weekly_evaluation import load_price_series, price_on_or_after, price_on_or_before  # noqa: E402


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def forward_return(price_cache: Path, ticker: str, start_date: Any, horizon_days: int) -> dict[str, Any]:
    px = load_price_series(price_cache, ticker)
    if px.empty:
        return {"status": "missing_price", "return": math.nan, "start_price": math.nan, "end_price": math.nan}
    start_dt, start_px = price_on_or_after(px, start_date, "close")
    if start_dt is None or start_px is None:
        return {"status": "missing_start", "return": math.nan, "start_price": math.nan, "end_price": math.nan}
    end_target = pd.Timestamp(start_dt) + pd.Timedelta(days=int(horizon_days))
    end_dt, end_px = price_on_or_before(px, end_target, "close")
    if end_dt is None or end_px is None or pd.Timestamp(end_dt) <= pd.Timestamp(start_dt):
        return {"status": "missing_end", "return": math.nan, "start_price": start_px, "end_price": math.nan}
    ret = float(end_px / start_px - 1.0)
    return {
        "status": "ok",
        "return": ret,
        "start_date": pd.Timestamp(start_dt).date().isoformat(),
        "end_date": pd.Timestamp(end_dt).date().isoformat(),
        "start_price": float(start_px),
        "end_price": float(end_px),
    }


def normalize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    required = {"ticker", "side", "date"}
    if not required.issubset(trades.columns):
        return pd.DataFrame()
    d = trades.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["side"] = d["side"].astype(str).str.upper().str.strip()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["gross_value"] = pd.to_numeric(d.get("gross_value", 0.0), errors="coerce").fillna(0.0).abs()
    d["quantity"] = pd.to_numeric(d.get("quantity", 0.0), errors="coerce").fillna(0.0).abs()
    d = d[d["date"].notna() & d["ticker"].ne("") & d["side"].isin({"BUY", "SELL"})].copy()
    return d.sort_values(["date", "side", "gross_value"], ascending=[True, True, False])


def pair_sells_to_buys(trades: pd.DataFrame, max_pair_lag_days: int) -> list[tuple[pd.Series, pd.Series | None]]:
    buys = trades[trades["side"].eq("BUY")].copy()
    sells = trades[trades["side"].eq("SELL")].copy()
    pairs: list[tuple[pd.Series, pd.Series | None]] = []
    for _, sell in sells.iterrows():
        start = sell["date"]
        end = start + pd.Timedelta(days=int(max_pair_lag_days))
        window = buys[(buys["date"].ge(start)) & (buys["date"].le(end)) & buys["ticker"].ne(sell["ticker"])].copy()
        if window.empty:
            pairs.append((sell, None))
            continue
        # Prefer same-date / near-date largest replacement dollars.
        window["lag_days"] = (window["date"] - start).dt.days
        replacement = window.sort_values(["lag_days", "gross_value"], ascending=[True, False]).iloc[0]
        pairs.append((sell, replacement))
    return pairs


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_root = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_root.mkdir(parents=True, exist_ok=True)

    portfolios = [p.strip() for p in str(args.portfolios).split(",") if p.strip()]
    summaries: list[dict[str, Any]] = []
    all_rows: list[pd.DataFrame] = []
    for portfolio in portfolios:
        trades_path = repo_path(args.trades) if args.trades else latest_run / "broker_replay" / portfolio / "trades.csv"
        trades = normalize_trades(read_csv(trades_path))
        rows: list[dict[str, Any]] = []
        for sell, replacement in pair_sells_to_buys(trades, int(args.max_pair_lag_days)):
            sold = forward_return(price_cache, str(sell["ticker"]), sell["date"], int(args.horizon_days))
            bought = (
                forward_return(price_cache, str(replacement["ticker"]), replacement["date"], int(args.horizon_days))
                if replacement is not None
                else {"status": "no_replacement", "return": math.nan}
            )
            sold_ret = safe_float(sold.get("return"), math.nan)
            bought_ret = safe_float(bought.get("return"), math.nan)
            spread = sold_ret - bought_ret if math.isfinite(sold_ret) and math.isfinite(bought_ret) else math.nan
            is_wrong = bool(math.isfinite(spread) and spread > float(args.wrong_substitution_threshold))
            rows.append(
                {
                    "portfolio_kind": portfolio,
                    "sell_date": pd.Timestamp(sell["date"]).date().isoformat(),
                    "sold_ticker": sell["ticker"],
                    "sold_gross_value": safe_float(sell.get("gross_value")),
                    "sold_forward_return": sold_ret,
                    "sold_forward_status": sold.get("status"),
                    "replacement_date": pd.Timestamp(replacement["date"]).date().isoformat() if replacement is not None else "",
                    "replacement_ticker": replacement["ticker"] if replacement is not None else "",
                    "replacement_gross_value": safe_float(replacement.get("gross_value")) if replacement is not None else 0.0,
                    "replacement_forward_return": bought_ret,
                    "replacement_forward_status": bought.get("status"),
                    "sold_minus_replacement_return": spread,
                    "wrong_substitution": is_wrong,
                    "horizon_days": int(args.horizon_days),
                    "diagnostic_only": True,
                    "production_activation_allowed": False,
                }
            )
        frame = pd.DataFrame(rows)
        out_dir = output_root / portfolio
        out_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(out_dir / "wrong_substitution.csv", index=False)
        wrong = int(frame["wrong_substitution"].sum()) if "wrong_substitution" in frame else 0
        comparable = int(frame["sold_minus_replacement_return"].notna().sum()) if "sold_minus_replacement_return" in frame else 0
        summary = {
            "status": "completed" if not trades.empty else "blocked",
            "portfolio_kind": portfolio,
            "trades_path": str(trades_path),
            "trade_rows": int(len(trades)),
            "sell_rows": int((trades["side"].eq("SELL")).sum()) if not trades.empty else 0,
            "paired_rows": int(len(frame)),
            "comparable_rows": comparable,
            "wrong_substitution_count": wrong,
            "wrong_substitution_rate": float(wrong / comparable) if comparable else 0.0,
            "horizon_days": int(args.horizon_days),
            "max_pair_lag_days": int(args.max_pair_lag_days),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(out_dir / "summary.json", summary)
        report = [
            "# Hold vs Replace Audit",
            "",
            f"- portfolio: `{portfolio}`",
            f"- status: `{summary['status']}`",
            f"- trade_rows: {summary['trade_rows']}",
            f"- paired_rows: {summary['paired_rows']}",
            f"- comparable_rows: {summary['comparable_rows']}",
            f"- wrong_substitution_count: {summary['wrong_substitution_count']}",
            f"- wrong_substitution_rate: {summary['wrong_substitution_rate']:.2%}",
            "",
            "Diagnostic only. Forward returns are used only after trades have already been simulated.",
            "",
        ]
        (out_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
        summaries.append(summary)
        if not frame.empty:
            all_rows.append(frame)

    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if not combined.empty:
        combined.to_csv(output_root / "wrong_substitution.csv", index=False)
    payload = {
        "status": "completed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolios": summaries,
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_root / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/hold_vs_replace_audit")
    parser.add_argument("--portfolios", default="main,concentrated")
    parser.add_argument("--trades", default="", help="Optional explicit trades.csv for single-portfolio smoke/debug runs.")
    parser.add_argument("--horizon-days", type=int, default=63)
    parser.add_argument("--max-pair-lag-days", type=int, default=3)
    parser.add_argument("--wrong-substitution-threshold", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
