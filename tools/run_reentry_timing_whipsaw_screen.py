#!/usr/bin/env python3
"""Screen daily re-entry timing triggers after sell events.

This is measurement-only.  It uses all sell events from broker trades and fires
candidate triggers from PIT price paths after each sell.  Future returns and
actual later rebuys are audit labels only; they never decide whether a trigger
fires.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402

SCHEMA_VERSION = "reentry-timing-whipsaw-screen-v1"
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/reentry_timing_whipsaw_screen"
CASH_TICKERS = {"CASH", "__CASH__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def default_trades_path(latest_run: Path, portfolio: str) -> Path:
    return latest_run / "broker_replay" / portfolio / "trades.csv"


def default_price_cache(latest_run: Path) -> Path:
    parent = latest_run.parent
    candidates = [
        parent / "cache_prices",
        latest_run / "cache_prices",
        REPO_ROOT / "cache_prices",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def read_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    if d.empty or "ticker" not in d.columns or "date" not in d.columns or "side" not in d.columns:
        return pd.DataFrame()
    d = d.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["side"] = d["side"].astype(str).str.upper().str.strip()
    d["fill_price"] = pd.to_numeric(d.get("fill_price"), errors="coerce")
    d["quantity"] = pd.to_numeric(d.get("quantity"), errors="coerce").fillna(0.0)
    d = d[d["date"].notna()]
    d = d[~d["ticker"].isin(CASH_TICKERS)]
    d = d[d["ticker"].ne("")]
    return d.sort_values(["ticker", "date"]).reset_index(drop=True)


def price_frame(price_cache: Path, ticker: str) -> pd.DataFrame:
    px = load_price_series(price_cache, ticker)
    if px.empty:
        return pd.DataFrame()
    out = px.reset_index().rename(columns={"Date": "date"})
    if "date" not in out.columns:
        out = out.rename(columns={out.columns[0]: "date"})
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out = out[out["date"].notna()].sort_values("date").reset_index(drop=True)
    close_col = "close"
    if close_col not in out.columns:
        return pd.DataFrame()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out[out["close"].gt(0)]
    out["ma200"] = out["close"].rolling(200, min_periods=120).mean()
    return out.reset_index(drop=True)


def future_price_return(px: pd.DataFrame, start_pos: int, horizon: int) -> float:
    end_pos = start_pos + int(horizon)
    if start_pos < 0 or start_pos >= len(px) or end_pos >= len(px):
        return math.nan
    start = safe_float(px["close"].iloc[start_pos], math.nan)
    end = safe_float(px["close"].iloc[end_pos], math.nan)
    if not math.isfinite(start) or start <= 0 or not math.isfinite(end):
        return math.nan
    return end / start - 1.0


def next_buy_after(trades: pd.DataFrame, ticker: str, sell_date: pd.Timestamp) -> dict[str, Any] | None:
    buys = trades[
        trades["ticker"].eq(ticker)
        & trades["side"].eq("BUY")
        & trades["date"].gt(sell_date)
    ].sort_values("date")
    if buys.empty:
        return None
    return buys.iloc[0].to_dict()


def first_trigger_hit(
    px: pd.DataFrame,
    *,
    sell_date: pd.Timestamp,
    sell_price: float,
    trigger: str,
    cooldown_trading_days: int,
    max_horizon_trading_days: int,
) -> tuple[int | None, str]:
    if px.empty:
        return None, "missing_price_series"
    pos = int(pd.DatetimeIndex(px["date"]).searchsorted(sell_date, side="right"))
    start = pos + int(cooldown_trading_days)
    end = min(len(px), pos + int(max_horizon_trading_days) + 1)
    if start >= end:
        return None, "insufficient_future_prices"
    trough = math.inf
    for i in range(start, end):
        price = safe_float(px["close"].iloc[i], math.nan)
        if not math.isfinite(price) or price <= 0:
            continue
        trough = min(trough, price)
        if trigger == "reclaim_5pct" and price >= sell_price * 1.05:
            return i, "price_reclaimed_sell_plus_5pct"
        if trigger == "reclaim_10pct" and price >= sell_price * 1.10:
            return i, "price_reclaimed_sell_plus_10pct"
        if trigger == "reclaim_15pct" and price >= sell_price * 1.15:
            return i, "price_reclaimed_sell_plus_15pct"
        if trigger == "trough_rebound_8pct" and math.isfinite(trough) and price >= trough * 1.08:
            return i, "price_rebounded_8pct_from_post_sell_trough"
        if trigger == "close_above_20d_high":
            lookback = px.iloc[max(0, i - 20):i]
            if len(lookback) >= 10 and price >= safe_float(lookback["close"].max(), math.inf):
                return i, "close_above_prior_20d_high"
    return None, "trigger_not_hit"


def screen(
    *,
    trades: pd.DataFrame,
    price_cache: Path,
    cooldown_trading_days: int,
    max_horizon_trading_days: int,
    triggers: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if trades.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "blocked", "reason": "missing_trades"}
    sells = trades[trades["side"].eq("SELL")].copy()
    price_cache_hits: dict[str, pd.DataFrame] = {}
    for _, sell in sells.iterrows():
        ticker = clean_ticker(sell.get("ticker"))
        sell_date = pd.Timestamp(sell.get("date")).normalize()
        sell_price = safe_float(sell.get("fill_price"), math.nan)
        if not ticker or not math.isfinite(sell_price) or sell_price <= 0:
            continue
        if ticker not in price_cache_hits:
            price_cache_hits[ticker] = price_frame(price_cache, ticker)
        px = price_cache_hits[ticker]
        rebuy = next_buy_after(trades, ticker, sell_date)
        rebuy_date = pd.Timestamp(rebuy["date"]).normalize() if rebuy else None
        rebuy_price = safe_float(rebuy.get("fill_price"), math.nan) if rebuy else math.nan
        rebuy_premium = rebuy_price / sell_price - 1.0 if math.isfinite(rebuy_price) and rebuy_price > 0 else math.nan
        for trigger in triggers:
            hit_pos, hit_reason = first_trigger_hit(
                px,
                sell_date=sell_date,
                sell_price=sell_price,
                trigger=trigger,
                cooldown_trading_days=cooldown_trading_days,
                max_horizon_trading_days=max_horizon_trading_days,
            )
            if hit_pos is None:
                rows.append(
                    {
                        "ticker": ticker,
                        "sell_date": sell_date.date().isoformat(),
                        "sell_price": sell_price,
                        "trigger": trigger,
                        "trigger_hit": False,
                        "trigger_reason": hit_reason,
                        "rebuy_date": rebuy_date.date().isoformat() if rebuy_date is not None else "",
                        "rebuy_price": rebuy_price,
                        "rebuy_premium_audit_only": rebuy_premium,
                    }
                )
                continue
            trigger_date = pd.Timestamp(px["date"].iloc[hit_pos]).normalize()
            trigger_price = safe_float(px["close"].iloc[hit_pos], math.nan)
            ma200 = safe_float(px["ma200"].iloc[hit_pos], math.nan)
            saved_premium = rebuy_price / trigger_price - 1.0 if math.isfinite(rebuy_price) and trigger_price > 0 else math.nan
            rows.append(
                {
                    "ticker": ticker,
                    "sell_date": sell_date.date().isoformat(),
                    "sell_price": sell_price,
                    "sell_quantity": safe_float(sell.get("quantity"), 0.0),
                    "trigger": trigger,
                    "trigger_hit": True,
                    "trigger_reason": hit_reason,
                    "trigger_date": trigger_date.date().isoformat(),
                    "trigger_price": trigger_price,
                    "trigger_days_after_sell": int((trigger_date - sell_date).days),
                    "trigger_above_ma200": bool(math.isfinite(ma200) and trigger_price >= ma200),
                    "rebuy_date": rebuy_date.date().isoformat() if rebuy_date is not None else "",
                    "rebuy_price": rebuy_price,
                    "rebuy_premium_audit_only": rebuy_premium,
                    "saved_premium_vs_actual_rebuy_audit_only": saved_premium,
                    "days_earlier_than_actual_rebuy_audit_only": int((rebuy_date - trigger_date).days) if rebuy_date is not None else math.nan,
                    "forward_20d_return_audit_only": future_price_return(px, hit_pos, 20),
                    "forward_63d_return_audit_only": future_price_return(px, hit_pos, 63),
                    "price_cache_file": str(price_cache / px_cache_name(ticker)),
                }
            )
    events = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    for trigger in triggers:
        part = events[events["trigger"].eq(trigger)].copy()
        hits = part[part["trigger_hit"].eq(True)].copy()
        true_whipsaw = hits[pd.to_numeric(hits.get("rebuy_premium_audit_only", pd.Series(dtype=float)), errors="coerce").gt(0.10)].copy()
        saved = pd.to_numeric(true_whipsaw.get("saved_premium_vs_actual_rebuy_audit_only", pd.Series(dtype=float)), errors="coerce").dropna()
        f20 = pd.to_numeric(hits.get("forward_20d_return_audit_only", pd.Series(dtype=float)), errors="coerce").dropna()
        f63 = pd.to_numeric(hits.get("forward_63d_return_audit_only", pd.Series(dtype=float)), errors="coerce").dropna()
        summary = {
            "trigger": trigger,
            "sell_event_count": int(len(part)),
            "trigger_count": int(len(hits)),
            "trigger_rate": float(len(hits) / len(part)) if len(part) else 0.0,
            "true_whipsaw_observation_count": int(len(saved)),
            "saved_premium_positive_rate": float((saved > 0).mean()) if len(saved) else 0.0,
            "saved_premium_mean": float(saved.mean()) if len(saved) else 0.0,
            "saved_premium_median": float(saved.median()) if len(saved) else 0.0,
            "false_positive_20d_loss_rate": float((f20 < 0).mean()) if len(f20) else 1.0,
            "false_positive_63d_loss_rate": float((f63 < 0).mean()) if len(f63) else 1.0,
            "below_ma200_trigger_rate": float((~hits.get("trigger_above_ma200", pd.Series(dtype=bool)).fillna(False).astype(bool)).mean()) if len(hits) else 1.0,
            "median_days_earlier_than_actual_rebuy": float(pd.to_numeric(hits.get("days_earlier_than_actual_rebuy_audit_only", pd.Series(dtype=float)), errors="coerce").median()) if len(hits) else 0.0,
        }
        summary["screen_pass"] = bool(
            summary["trigger_count"] >= 20
            and summary["saved_premium_positive_rate"] >= 0.60
            and summary["false_positive_20d_loss_rate"] <= 0.45
            and summary["saved_premium_median"] >= 0.05
            and summary["below_ma200_trigger_rate"] <= 0.50
        )
        summary["verdict"] = "screen_pass_design_reentry_hook" if summary["screen_pass"] else "reject_or_inconclusive"
        summaries.append(summary)
    summary_df = pd.DataFrame(summaries)
    any_pass = bool(summary_df["screen_pass"].any()) if not summary_df.empty else False
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "forward_columns_used_for_trigger": False,
        "sell_event_count": int(len(sells)),
        "trigger_count_total": int(events["trigger_hit"].eq(True).sum()) if not events.empty else 0,
        "screen_pass": any_pass,
        "verdict": "screen_pass_design_default_off_reentry_hook" if any_pass else "reject_or_inconclusive",
        "next_action": "design_default_off_reentry_hook" if any_pass else "discard_or_tighten_without_fullrun",
    }
    return events, summary_df, payload


def render_report(payload: dict[str, Any], summary_df: pd.DataFrame) -> str:
    lines = [
        "# Re-Entry Timing Whipsaw Screen",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Verdict: `{payload.get('verdict')}`",
        f"- Sell events: {payload.get('sell_event_count')}",
        f"- Total trigger hits: {payload.get('trigger_count_total')}",
        "",
        "| Trigger | Hits | Saved positive rate | Median saved premium | 20d loss rate | Verdict |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for _, row in summary_df.iterrows():
        lines.append(
            f"| {row.get('trigger')} | {int(safe_float(row.get('trigger_count')))} | "
            f"{safe_float(row.get('saved_premium_positive_rate')):.2%} | "
            f"{safe_float(row.get('saved_premium_median')):.2%} | "
            f"{safe_float(row.get('false_positive_20d_loss_rate')):.2%} | "
            f"`{row.get('verdict')}` |"
        )
    lines.extend(
        [
            "",
            "Triggers use only PIT price paths after sell events. Future returns and later actual rebuys are audit labels only.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--trades", default=None)
    parser.add_argument("--price-cache", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["concentrated"], default="concentrated")
    parser.add_argument("--cooldown-trading-days", type=int, default=3)
    parser.add_argument("--max-horizon-trading-days", type=int, default=63)
    parser.add_argument(
        "--triggers",
        default="reclaim_5pct,reclaim_10pct,trough_rebound_8pct,close_above_20d_high",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    trades_path = repo_path(args.trades) if args.trades else default_trades_path(latest_run, args.portfolio_kind)
    price_cache = repo_path(args.price_cache) if args.price_cache else default_price_cache(latest_run)
    output_dir = repo_path(args.output_dir)
    trades = read_trades(trades_path)
    triggers = [part.strip() for part in str(args.triggers).split(",") if part.strip()]
    if trades.empty or not price_cache.exists():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_trades_or_price_cache",
            "trades": str(trades_path),
            "price_cache": str(price_cache),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    events, summary_df, payload = screen(
        trades=trades,
        price_cache=price_cache,
        cooldown_trading_days=args.cooldown_trading_days,
        max_horizon_trading_days=args.max_horizon_trading_days,
        triggers=triggers,
    )
    payload.update(
        {
            "trades": str(trades_path),
            "price_cache": str(price_cache),
            "output_dir": str(output_dir),
            "cooldown_trading_days": int(args.cooldown_trading_days),
            "max_horizon_trading_days": int(args.max_horizon_trading_days),
            "triggers": triggers,
        }
    )
    write_csv(output_dir / "reentry_trigger_events.csv", events)
    write_csv(output_dir / "reentry_trigger_summary.csv", summary_df)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, summary_df), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
