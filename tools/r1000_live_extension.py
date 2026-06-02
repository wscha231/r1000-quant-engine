#!/usr/bin/env python3
"""r1000_live_extension - forward-walk from backtest anchor to today.

User concern (2026-05-13):
  "2월까지밖에 기록이없네 여전히 지금 5월 13일이고 최근 몇달 사이에 시장이
   엉청 많이 바꼈는데"

Root cause: backtest anchor stops at the last month with complete forward
returns (r_1m/3m/6m). Today minus 6mo = ~Feb 2026 with full r_6m data.

This tool bridges the gap WITHOUT requiring forward-return validation:
  - Loads the backtest's final portfolio (portfolio_latest.csv).
  - For each held ticker, fetches daily price history from anchor_date to today.
  - Applies position-risk stops (-8% hard, -15% trailing from peak).
  - Tracks equity drift + cash accumulation from stops.
  - Optionally reads scored_latest.csv to flag NEW entry candidates (not
    auto-added — actual entry requires next monthly rebalance).

Output
------
    outputs/live_extension/
        daily_equity_curve.csv     ts, equity, cash, n_positions
        current_holdings.csv       ticker, anchor_weight, drift_weight,
                                   current_price, peak_price, status
        stops_triggered.csv        ticker, stop_type, exit_date, exit_price,
                                   ret_at_exit
        action_suggestions.csv     ticker, signal_type (NEW_ENTRY/HOLD/EXIT),
                                   score, regime, reason
        summary.json               anchor_date, today, days_elapsed,
                                   equity_now, equity_anchor, return_since,
                                   stops_triggered_count, fresh_signals_count

Inputs (auto-located, can be overridden)
----------------------------------------
    --portfolio: portfolio_latest.csv from backtest
    --scored:    scored_latest.csv from backtest (for new-entry detection)
    --start-cap: starting capital (default $100k, normalized to anchor)

Usage
-----
    python tools/r1000_live_extension.py
    python tools/r1000_live_extension.py --start-cap 587849.24  (= anchor equity)
    python tools/r1000_live_extension.py --hard-stop -0.08 --trailing -0.15
    python tools/r1000_live_extension.py --no-yfinance  (uses cached prices only)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "outputs" / "live_extension"

DEFAULT_PORTFOLIO_PATHS = [
    "outputs/portfolio_latest.csv",
    "cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_latest.csv",
    "cloud_results/full/portfolio_latest.csv",
]
DEFAULT_SCORED_PATHS = [
    "outputs/scored_latest.csv",
    "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv",
    "cloud_results/full/scored_latest.csv",
]

# Position-risk stop defaults (match backtest engine)
DEFAULT_HARD_STOP = -0.08
DEFAULT_TRAILING_STOP = -0.15

CASH_PROXY_TICKER = "CASH"


def find_file(override: Optional[str], candidates: list[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.exists() else None
    for rel in candidates:
        p = REPO_ROOT / rel
        if p.exists():
            return p
    return None


def load_portfolio(path: Path):
    import pandas as pd
    df = pd.read_csv(path)
    # Expected columns: ticker, weight, rebalance_date (or asof), portfolio_sleeve_label
    # Drop cash row for forward walk (cash doesn't move)
    if "ticker" not in df.columns:
        # Try lowercase
        df.columns = [c.lower() for c in df.columns]
    return df


def latest_date_from_frame(df, columns: list[str]) -> Optional[str]:
    import pandas as pd
    for col in columns:
        if col not in df.columns:
            continue
        dates = pd.to_datetime(df[col], errors="coerce").dropna()
        if not dates.empty:
            return str(pd.Timestamp(dates.max()).date())
    return None


def latest_date_from_json_payload(payload: dict, keys: list[str]) -> Optional[str]:
    import pandas as pd

    candidates: list[object] = []

    def collect(obj: object) -> None:
        if not isinstance(obj, dict):
            return
        for key in keys:
            value = obj.get(key)
            if value:
                candidates.append(value)
        portfolios = obj.get("portfolios")
        if isinstance(portfolios, dict):
            for item in portfolios.values():
                collect(item)

    collect(payload)
    dates: list[str] = []
    for value in candidates:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            continue
        dates.append(str(pd.Timestamp(ts).date()))
    return max(dates) if dates else None


def latest_date_from_json_file(path: Path, keys: list[str]) -> Optional[str]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return latest_date_from_json_payload(payload, keys)


def infer_anchor_date(portfolio_path: Path, portfolio_df, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    direct = latest_date_from_frame(
        portfolio_df,
        ["rebalance_date", "asof", "as_of_date", "date", "feature_date", "last_trade_date"],
    )
    if direct:
        return direct
    json_date_keys = ["end_date", "as_of_date", "asof", "date", "anchor_date"]
    json_candidates = [
        portfolio_path.parent / "backtest_metrics.json",
        portfolio_path.parent / "broker_replay" / "main" / "metrics.json",
        portfolio_path.parent / "user_current" / "04_official_metrics.json",
        portfolio_path.parent / "user_current" / "summary.json",
    ]
    for json_path in json_candidates:
        anchor = latest_date_from_json_file(json_path, json_date_keys)
        if anchor:
            print(f"[live-ext] anchor_date auto-detected from {json_path}: {anchor}")
            return anchor
    equity_candidates = [
        portfolio_path.parent / "equity_curve.csv",
        portfolio_path.parent.parent / "equity_curve.csv",
        REPO_ROOT / "outputs" / "equity_curve.csv",
        REPO_ROOT / "outputs" / "broker_replay" / "main" / "equity_curve.csv",
    ]
    try:
        import pandas as pd
    except ImportError:
        return None
    for eq_path in equity_candidates:
        if not eq_path.exists():
            continue
        try:
            eq = pd.read_csv(eq_path)
        except Exception:
            continue
        anchor = latest_date_from_frame(eq, ["rebalance_date", "asof", "as_of_date", "date"])
        if anchor:
            print(f"[live-ext] anchor_date auto-detected from {eq_path}: {anchor}")
            return anchor
    return None


def fetch_history(ticker: str, start: str, end: str):
    """Fetch daily OHLC via yfinance. Returns DataFrame with date index +
    'close' column, or None on failure."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    if str(ticker).upper() == CASH_PROXY_TICKER:
        return None
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return None
        return df[["Close"]].rename(columns={"Close": "close"})
    except Exception:
        return None


def walk_one_position(
    ticker: str,
    anchor_weight: float,
    anchor_date: str,
    today: str,
    hard_stop: float,
    trailing_stop: float,
) -> dict:
    """Walk one position day-by-day from anchor to today. Returns dict with
    daily equity series + stop info."""
    import pandas as pd
    import numpy as np
    hist = fetch_history(ticker, anchor_date, today)
    if hist is None or hist.empty:
        return {
            "ticker": ticker,
            "status": "no_data",
            "drift_weight": anchor_weight,
            "cumret_at_today": 0.0,
            "stop_triggered": None,
            "exit_date": None,
            "exit_price": None,
            "peak_price": None,
            "current_price": None,
            "daily_returns": pd.Series(dtype=float),
        }

    closes = hist["close"]
    anchor_price = float(closes.iloc[0])
    if anchor_price <= 0:
        return {"ticker": ticker, "status": "bad_anchor_price"}

    peak = anchor_price
    stop_triggered = None
    exit_date = None
    exit_price = None
    daily_rets = closes.pct_change().fillna(0.0)
    walk_ret_series = pd.Series(0.0, index=closes.index)

    cum_ret_from_anchor = 1.0
    for i, dt in enumerate(closes.index):
        if i == 0:
            walk_ret_series.iloc[i] = 0.0
            continue
        c = float(closes.iloc[i])
        if c <= 0:
            continue
        cum_ret_from_anchor = c / anchor_price
        # Check hard stop (loss from anchor)
        if hard_stop is not None and (cum_ret_from_anchor - 1.0) <= hard_stop:
            stop_triggered = "hard_stop"
            exit_date = str(dt.date())
            exit_price = anchor_price * (1.0 + hard_stop)
            break
        # Check trailing stop (loss from peak)
        if c > peak:
            peak = c
        if trailing_stop is not None and (c / peak - 1.0) <= trailing_stop:
            stop_triggered = "trailing_stop"
            exit_date = str(dt.date())
            exit_price = peak * (1.0 + trailing_stop)
            break
        walk_ret_series.iloc[i] = float(daily_rets.iloc[i])

    current_price = float(closes.iloc[-1])
    final_ret = (exit_price / anchor_price - 1.0) if exit_price is not None else (current_price / anchor_price - 1.0)
    return {
        "ticker": ticker,
        "anchor_weight": anchor_weight,
        "anchor_price": anchor_price,
        "peak_price": peak,
        "current_price": current_price,
        "cumret_at_today": final_ret,
        "drift_weight": anchor_weight * (1.0 + final_ret),
        "stop_triggered": stop_triggered,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "status": "stopped" if stop_triggered else "held",
        "daily_returns": walk_ret_series,
    }


def detect_new_signals(scored_path: Path, current_holdings: set, top_n: int = 10):
    """Scan scored_latest.csv for high-confidence NEW entry candidates not
    in current holdings. Returns list of dicts."""
    try:
        import pandas as pd
        df = pd.read_csv(scored_path)
    except Exception:
        return []
    out = []
    score_col = next((c for c in ("score", "concentrated_score", "portfolio_score") if c in df.columns), None)
    if score_col is None:
        return []
    df = df.sort_values(score_col, ascending=False)
    cnt = 0
    for _, row in df.iterrows():
        if cnt >= top_n:
            break
        t = str(row.get("ticker", "")).upper()
        if not t or t in current_holdings or t == CASH_PROXY_TICKER:
            continue
        out.append({
            "ticker": t,
            "score": float(row.get(score_col, 0.0)),
            "regime_state": str(row.get("regime_state", "neutral")),
            "sector": str(row.get("sector", "")),
            "sleeve": str(row.get("portfolio_sleeve_label", "")),
            "explosion_entry": float(row.get("explosion_entry_score", 0.0) or 0.0),
            "signal_type": "NEW_ENTRY_CANDIDATE",
        })
        cnt += 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--portfolio", default=None, help="path to portfolio_latest.csv")
    p.add_argument("--scored", default=None, help="path to scored_latest.csv")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    p.add_argument("--anchor-date", default=None,
                   help="override anchor date (default: from portfolio_latest)")
    p.add_argument("--today", default=None,
                   help="override today's date (default: actual today)")
    p.add_argument("--hard-stop", type=float, default=DEFAULT_HARD_STOP)
    p.add_argument("--trailing-stop", type=float, default=DEFAULT_TRAILING_STOP)
    p.add_argument("--start-cap", type=float, default=100000.0,
                   help="starting capital normalized to anchor (default 100k)")
    p.add_argument("--top-new-signals", type=int, default=10)
    p.add_argument("--no-yfinance", action="store_true",
                   help="skip yfinance fetches (cached only — dev mode)")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    portfolio_path = find_file(args.portfolio, DEFAULT_PORTFOLIO_PATHS)
    if portfolio_path is None:
        print("[live-ext] ERROR: portfolio_latest.csv not found", file=sys.stderr)
        for c in DEFAULT_PORTFOLIO_PATHS:
            print(f"           tried: {c}", file=sys.stderr)
        return 2

    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        print("[live-ext] ERROR: pandas + numpy required", file=sys.stderr)
        return 2

    df = pd.read_csv(portfolio_path)
    print(f"[live-ext] loaded portfolio: {portfolio_path} ({len(df)} rows)")

    anchor_date = infer_anchor_date(portfolio_path, df, args.anchor_date)
    if not anchor_date:
        print(
            "[live-ext] ERROR: no rebalance/asof/date column in portfolio and no usable equity curve "
            "date found. Pass --anchor-date YYYY-MM-DD explicitly.",
            file=sys.stderr,
        )
        return 2

    today_str = args.today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    anchor_dt = pd.to_datetime(anchor_date)
    today_dt = pd.to_datetime(today_str)
    days_elapsed = int((today_dt - anchor_dt).days)
    if days_elapsed <= 0:
        print(f"[live-ext] anchor {anchor_date} >= today {today_str}; nothing to walk", file=sys.stderr)
        return 1
    print(f"[live-ext] anchor: {anchor_date}  today: {today_str}  days elapsed: {days_elapsed}")

    # Find weight column
    weight_col = "weight" if "weight" in df.columns else next(
        (c for c in df.columns if "weight" in c.lower()), None
    )
    if weight_col is None:
        print("[live-ext] ERROR: no weight column", file=sys.stderr)
        return 2

    # Drop cash row (handled separately)
    positions = df[df["ticker"].astype(str).str.upper() != CASH_PROXY_TICKER].copy()
    anchor_cash = float(
        df[df["ticker"].astype(str).str.upper() == CASH_PROXY_TICKER][weight_col].sum()
        if (df["ticker"].astype(str).str.upper() == CASH_PROXY_TICKER).any()
        else max(0.0, 1.0 - positions[weight_col].sum())
    )
    print(f"[live-ext] anchor cash: {anchor_cash:.4f}, {len(positions)} stock positions")

    # Walk each position
    print(f"[live-ext] fetching {len(positions)} ticker histories (yfinance)...")
    walk_results: list[dict] = []
    if args.no_yfinance:
        print("[live-ext] --no-yfinance set; skipping price fetch (dev mode)")
    else:
        for i, row in positions.iterrows():
            ticker = str(row["ticker"]).upper()
            w = float(row[weight_col])
            res = walk_one_position(
                ticker, w, anchor_date, today_str,
                args.hard_stop, args.trailing_stop,
            )
            walk_results.append(res)
            if (len(walk_results)) % 5 == 0:
                print(f"  [{len(walk_results)}/{len(positions)}] processed", flush=True)

    # Build daily equity curve (union of all dates)
    all_dates = set()
    for r in walk_results:
        if isinstance(r.get("daily_returns"), pd.Series):
            all_dates.update(r["daily_returns"].index)
    dates = sorted(all_dates)
    print(f"[live-ext] {len(dates)} trading days in walk window")

    # Per-day equity walk: each position contributes anchor_weight * cumret
    # If stopped, contribution freezes at exit_price/anchor_price * weight
    equity_rows = []
    running_cash = anchor_cash
    for dt in dates:
        equity_invested = 0.0
        cash_from_stops = 0.0
        n_active = 0
        for r in walk_results:
            w = r.get("anchor_weight", 0.0)
            if w <= 0:
                continue
            if r.get("stop_triggered"):
                exit_dt = pd.to_datetime(r.get("exit_date"))
                if dt <= exit_dt:
                    # Pre-exit: track cumret
                    series = r.get("daily_returns")
                    if isinstance(series, pd.Series) and dt in series.index:
                        cum = (1.0 + series.loc[:dt]).prod()
                    else:
                        cum = 1.0
                    equity_invested += w * cum
                    n_active += 1
                else:
                    # Post-exit: freeze at exit return + accumulate to cash
                    exit_cum = 1.0 + r.get("cumret_at_today", 0.0)
                    cash_from_stops += w * exit_cum
            else:
                series = r.get("daily_returns")
                if isinstance(series, pd.Series) and dt in series.index:
                    cum = (1.0 + series.loc[:dt]).prod()
                else:
                    cum = 1.0
                equity_invested += w * cum
                n_active += 1
        total_equity = anchor_cash + equity_invested + cash_from_stops
        equity_rows.append({
            "date": str(pd.Timestamp(dt).date()),
            "equity_norm": total_equity,
            "equity_usd": args.start_cap * total_equity,
            "invested_norm": equity_invested,
            "cash_norm": anchor_cash + cash_from_stops,
            "n_active_positions": n_active,
            "n_stopped": sum(1 for r in walk_results if r.get("stop_triggered") and pd.to_datetime(r.get("exit_date", "1900-01-01")) <= dt),
        })

    equity_df = pd.DataFrame(equity_rows)
    if not equity_df.empty:
        equity_df.to_csv(out_dir / "daily_equity_curve.csv", index=False)

    # Current holdings snapshot
    holdings_rows = []
    for r in walk_results:
        holdings_rows.append({
            "ticker": r["ticker"],
            "anchor_weight": r.get("anchor_weight"),
            "drift_weight": r.get("drift_weight"),
            "anchor_price": r.get("anchor_price"),
            "current_price": r.get("current_price"),
            "peak_price": r.get("peak_price"),
            "cumret_since_anchor": r.get("cumret_at_today"),
            "status": r.get("status"),
            "stop_triggered": r.get("stop_triggered"),
            "exit_date": r.get("exit_date"),
        })
    if holdings_rows:
        holdings_df = pd.DataFrame(holdings_rows).sort_values("drift_weight", ascending=False, na_position="last")
        holdings_df.to_csv(out_dir / "current_holdings.csv", index=False)
    else:
        holdings_df = pd.DataFrame()
        print("[live-ext] WARN: no walk results (likely --no-yfinance dev mode); skipping holdings CSV")

    # Stops triggered
    stops_rows = [
        {
            "ticker": r["ticker"],
            "stop_type": r["stop_triggered"],
            "exit_date": r["exit_date"],
            "anchor_price": r.get("anchor_price"),
            "exit_price": r.get("exit_price"),
            "ret_at_exit": r.get("cumret_at_today"),
            "peak_price": r.get("peak_price"),
        }
        for r in walk_results if r.get("stop_triggered")
    ]
    stops_df = pd.DataFrame(stops_rows)
    if not stops_df.empty:
        stops_df.to_csv(out_dir / "stops_triggered.csv", index=False)

    # New entry signals (read scored_latest if available)
    # Build current_holdings set from BOTH walk_results AND raw portfolio (so
    # detection works even if yfinance fetch failed and walk_results is sparse).
    scored_path = find_file(args.scored, DEFAULT_SCORED_PATHS)
    current_holdings = {str(r["ticker"]).upper() for r in walk_results if r.get("ticker")}
    current_holdings.update(
        str(t).upper() for t in positions["ticker"].astype(str).tolist() if t
    )
    new_signals = []
    if scored_path is not None:
        new_signals = detect_new_signals(scored_path, current_holdings, args.top_new_signals)
        if new_signals:
            pd.DataFrame(new_signals).to_csv(out_dir / "action_suggestions.csv", index=False)

    # Summary
    n_stops = sum(1 for r in walk_results if r.get("stop_triggered"))
    final_equity = float(equity_df["equity_norm"].iloc[-1]) if not equity_df.empty else 1.0
    return_since = final_equity - 1.0
    summary = {
        "anchor_date": anchor_date,
        "today": today_str,
        "days_elapsed": days_elapsed,
        "anchor_cash_weight": anchor_cash,
        "n_anchor_positions": int(len(positions)),
        "n_stops_triggered": int(n_stops),
        "stop_hard_pct": args.hard_stop,
        "stop_trailing_pct": args.trailing_stop,
        "equity_anchor_norm": 1.0,
        "equity_now_norm": float(final_equity),
        "return_since_anchor": float(return_since),
        "equity_anchor_usd": float(args.start_cap),
        "equity_now_usd": float(args.start_cap * final_equity),
        "n_new_signals": int(len(new_signals)),
        "scored_source": str(scored_path) if scored_path else None,
        "portfolio_source": str(portfolio_path),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # Console output
    print()
    print("=" * 60)
    print("LIVE EXTENSION SUMMARY")
    print("=" * 60)
    print(f"  anchor:           {anchor_date}")
    print(f"  today:            {today_str}")
    print(f"  days elapsed:     {days_elapsed}")
    print(f"  positions:        {len(positions)}")
    print(f"  stops triggered:  {n_stops}")
    print(f"  return since:     {return_since:+.4f}  ({return_since*100:+.2f}%)")
    print(f"  equity norm:      {final_equity:.4f}  (anchor 1.0)")
    if args.start_cap and args.start_cap != 100000.0:
        print(f"  equity USD:       ${args.start_cap * final_equity:,.0f}")
    if new_signals:
        print()
        print(f"  fresh signal candidates ({len(new_signals)}, not in current holdings):")
        for s in new_signals[:5]:
            print(f"    {s['ticker']:>6}  score={s['score']:.4f}  regime={s['regime_state']:<12} sector={s['sector']}")
    print()
    print(f"  wrote: {out_dir / 'daily_equity_curve.csv'}")
    print(f"  wrote: {out_dir / 'current_holdings.csv'}")
    if n_stops:
        print(f"  wrote: {out_dir / 'stops_triggered.csv'}")
    if new_signals:
        print(f"  wrote: {out_dir / 'action_suggestions.csv'}")
    print(f"  wrote: {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
