#!/usr/bin/env python3
"""Attribute alpha-selector market-circuit broker replay performance.

Research-only sidecar. It reads the best market-circuit challenger produced by
`run_alpha_selector_market_circuit_grid.py` and explains remaining drawdowns,
monthly returns by circuit state, and obvious replacement mistakes. It does not
change portfolio weights or promotion state.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_PORTFOLIO_KIND = "main"
DEFAULT_OUTPUT_DIR = "outputs/market_circuit_attribution/main"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def output_relative_path(raw: Any) -> Path | None:
    text = str(raw or "").replace("\\", "/")
    if not text:
        return None
    marker = "/outputs/"
    if marker in text:
        return Path(text.split(marker, 1)[1])
    if text.startswith("outputs/"):
        return Path(text.split("outputs/", 1)[1])
    return None


def resolve_from_latest(latest_run: Path, raw: Any) -> Path | None:
    text = str(raw or "")
    if text:
        path = Path(text)
        if path.exists():
            return path
    rel = output_relative_path(raw)
    if rel is not None:
        candidate = latest_run / rel
        if candidate.exists():
            return candidate
    return None


def find_best_variant_dir(latest_run: Path, portfolio_kind: str, explicit_dir: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    base = repo_path(explicit_dir) if explicit_dir else latest_run / "alpha_selector_market_circuit_grid" / portfolio_kind
    metrics = read_json(base / "best_metrics.json")
    target_book = resolve_from_latest(latest_run, metrics.get("target_book") or metrics.get("market_circuit_target_book"))
    if target_book is not None:
        variant_dir = target_book.parent
        if (variant_dir / "equity_curve.csv").exists():
            return variant_dir, metrics
    precise_dir = resolve_from_latest(latest_run, metrics.get("source_variant_dir"))
    if precise_dir is not None and (precise_dir / "equity_curve.csv").exists():
        return precise_dir, metrics
    if base.exists():
        for path in sorted(base.rglob("equity_curve.csv")):
            variant_dir = path.parent
            if (variant_dir / "market_circuit_states.csv").exists():
                local_metrics = read_json(variant_dir / "metrics.json")
                return variant_dir, metrics or local_metrics
    return base, metrics


def normalized_equity(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    equity_col = "equity_usd" if "equity_usd" in d.columns else ""
    if not equity_col:
        for col in ["account_value_usd", "value_usd", "equity"]:
            if col in d.columns:
                equity_col = col
                break
    if not equity_col:
        return pd.DataFrame()
    d["equity_usd"] = pd.to_numeric(d[equity_col], errors="coerce")
    d = d[d["date"].notna() & d["equity_usd"].notna()].sort_values("date").copy()
    d["peak_equity_usd"] = d["equity_usd"].cummax()
    d["drawdown"] = d["equity_usd"] / d["peak_equity_usd"] - 1.0
    return d


def state_by_date(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty or "date" not in states.columns:
        return pd.DataFrame(columns=["date", "state"])
    d = states.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["state"] = d.get("state", "unknown").astype(str)
    return d[d["date"].notna()][["date", "state"]].drop_duplicates("date", keep="last")


def dominant_state(states: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> str:
    if states.empty:
        return ""
    mask = states["date"].between(start, end)
    if not mask.any():
        return ""
    counts = states.loc[mask, "state"].astype(str).value_counts()
    return str(counts.index[0]) if not counts.empty else ""


def drawdown_periods(equity: pd.DataFrame, states: pd.DataFrame, min_drawdown: float) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    underwater = equity["drawdown"].lt(0.0)
    start_idx: int | None = None
    for idx, is_underwater in zip(range(len(equity)), underwater):
        if is_underwater and start_idx is None:
            start_idx = idx
        if start_idx is not None and (not is_underwater or idx == len(equity) - 1):
            end_idx = idx if is_underwater else idx - 1
            chunk = equity.iloc[start_idx : end_idx + 1]
            trough_pos = chunk["drawdown"].idxmin()
            trough = equity.loc[trough_pos]
            dd = safe_float(trough["drawdown"], 0.0)
            if dd <= float(min_drawdown):
                start = equity.iloc[start_idx]
                end = equity.iloc[end_idx]
                rows.append(
                    {
                        "start_date": pd.Timestamp(start["date"]).date().isoformat(),
                        "trough_date": pd.Timestamp(trough["date"]).date().isoformat(),
                        "end_date": pd.Timestamp(end["date"]).date().isoformat(),
                        "drawdown": dd,
                        "equity_start": safe_float(start["equity_usd"]),
                        "equity_trough": safe_float(trough["equity_usd"]),
                        "equity_end": safe_float(end["equity_usd"]),
                        "days": int((pd.Timestamp(end["date"]) - pd.Timestamp(start["date"])).days) + 1,
                        "dominant_state": dominant_state(states, pd.Timestamp(start["date"]), pd.Timestamp(end["date"])),
                    }
                )
            start_idx = None
    if not rows:
        return pd.DataFrame(columns=["start_date", "trough_date", "end_date", "drawdown", "dominant_state"])
    return pd.DataFrame(rows).sort_values("drawdown", ascending=True)


def monthly_state_returns(equity: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame()
    d = equity[["date", "equity_usd"]].copy()
    d["month"] = d["date"].dt.to_period("M").astype(str)
    month_end = d.groupby("month").tail(1).copy()
    month_end["monthly_return"] = month_end["equity_usd"].pct_change()
    rows: list[dict[str, Any]] = []
    for row in month_end.itertuples(index=False):
        month = str(row.month)
        start = pd.Timestamp(f"{month}-01")
        end = pd.Timestamp(row.date)
        rows.append(
            {
                "month": month,
                "month_end_date": pd.Timestamp(row.date).date().isoformat(),
                "equity_usd": safe_float(row.equity_usd),
                "monthly_return": safe_float(row.monthly_return),
                "dominant_state": dominant_state(states, start, end),
            }
        )
    return pd.DataFrame(rows)


def price_lookup(holdings_daily: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if holdings_daily.empty or not {"date", "ticker", "price"}.issubset(holdings_daily.columns):
        return {}
    d = holdings_daily.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["price"] = pd.to_numeric(d["price"], errors="coerce")
    d = d[d["date"].notna() & d["ticker"].ne("") & d["price"].notna()].copy()
    out: dict[str, pd.DataFrame] = {}
    for ticker, group in d.groupby("ticker"):
        out[ticker] = group[["date", "price"]].drop_duplicates("date", keep="last").sort_values("date")
    return out


def forward_return(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp, horizon_days: int) -> float:
    history = prices.get(str(ticker).upper())
    if history is None or history.empty:
        return math.nan
    dates = pd.DatetimeIndex(history["date"])
    start_pos = int(dates.searchsorted(date, side="left"))
    if start_pos >= len(history):
        return math.nan
    end_dt = date + pd.Timedelta(days=int(horizon_days))
    end_pos = int(dates.searchsorted(end_dt, side="left"))
    if end_pos >= len(history):
        end_pos = len(history) - 1
    if end_pos <= start_pos:
        return math.nan
    start_px = safe_float(history.iloc[start_pos]["price"], math.nan)
    end_px = safe_float(history.iloc[end_pos]["price"], math.nan)
    if not math.isfinite(start_px) or start_px <= 0 or not math.isfinite(end_px):
        return math.nan
    return end_px / start_px - 1.0


def wrong_substitutions(trades: pd.DataFrame, holdings_daily: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    if trades.empty or not {"date", "ticker", "side"}.issubset(trades.columns):
        return pd.DataFrame()
    d = trades.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["side"] = d["side"].astype(str).str.upper()
    d = d[d["date"].notna() & d["ticker"].ne("")].sort_values("date").copy()
    prices = price_lookup(holdings_daily)
    rows: list[dict[str, Any]] = []
    sells = d[d["side"].eq("SELL")]
    buys = d[d["side"].eq("BUY")]
    for sell in sells.itertuples(index=False):
        sell_dt = pd.Timestamp(sell.date)
        near_buys = buys[buys["date"].between(sell_dt, sell_dt + pd.Timedelta(days=10))]
        if near_buys.empty:
            continue
        sold_forward = forward_return(prices, str(sell.ticker), sell_dt, horizon_days)
        if not math.isfinite(sold_forward):
            continue
        for buy in near_buys.itertuples(index=False):
            buy_dt = pd.Timestamp(buy.date)
            bought_forward = forward_return(prices, str(buy.ticker), buy_dt, horizon_days)
            if not math.isfinite(bought_forward):
                continue
            gap = sold_forward - bought_forward
            if gap > 0.05:
                rows.append(
                    {
                        "sell_date": sell_dt.date().isoformat(),
                        "sold_ticker": str(sell.ticker),
                        "buy_date": buy_dt.date().isoformat(),
                        "bought_ticker": str(buy.ticker),
                        "sold_forward_return": sold_forward,
                        "bought_forward_return": bought_forward,
                        "opportunity_gap": gap,
                        "horizon_days": int(horizon_days),
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["sell_date", "sold_ticker", "buy_date", "bought_ticker", "opportunity_gap"])
    return pd.DataFrame(rows).sort_values("opportunity_gap", ascending=False)


def render_report(summary: dict[str, Any]) -> str:
    metrics = summary.get("metrics", {}) or {}
    return "\n".join(
        [
            "# Market Circuit Attribution",
            "",
            "Research-only attribution for the alpha-selector market-circuit challenger.",
            "",
            f"- status: `{summary.get('status')}`",
            f"- portfolio: `{summary.get('portfolio_kind')}`",
            f"- variant_dir: `{summary.get('variant_dir')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}" if math.isfinite(safe_float(metrics.get("cagr"))) else "- CAGR: n/a",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}" if math.isfinite(safe_float(metrics.get("max_dd"))) else "- MaxDD: n/a",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}" if math.isfinite(safe_float(metrics.get("sharpe"))) else "- Sharpe: n/a",
            f"- drawdown periods: {summary.get('drawdown_period_count')}",
            f"- wrong substitutions: {summary.get('wrong_substitution_count')}",
            "",
            "## Outputs",
            "",
            "- `main_drawdown_periods.csv`",
            "- `monthly_state_returns.csv`",
            "- `wrong_substitutions.csv`",
            "- `summary.json`",
            "",
        ]
    )


def run(
    latest_run: str | Path = DEFAULT_LATEST_RUN,
    portfolio_kind: str = DEFAULT_PORTFOLIO_KIND,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    market_circuit_dir: str | Path | None = None,
    min_drawdown: float = -0.05,
    substitution_horizon_days: int = 20,
) -> dict[str, Any]:
    latest = repo_path(latest_run)
    out = repo_path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    variant_dir, best_metrics = find_best_variant_dir(latest, portfolio_kind, market_circuit_dir)
    equity = normalized_equity(read_csv(variant_dir / "equity_curve.csv"))
    states = state_by_date(read_csv(variant_dir / "market_circuit_states.csv"))
    trades = read_csv(variant_dir / "trades.csv")
    holdings = read_csv(variant_dir / "holdings_daily.csv")
    local_metrics = read_json(variant_dir / "metrics.json")
    metrics = best_metrics or local_metrics

    dd = drawdown_periods(equity, states, min_drawdown)
    monthly = monthly_state_returns(equity, states)
    wrong = wrong_substitutions(trades, holdings, substitution_horizon_days)
    dd.to_csv(out / "main_drawdown_periods.csv", index=False)
    monthly.to_csv(out / "monthly_state_returns.csv", index=False)
    wrong.to_csv(out / "wrong_substitutions.csv", index=False)

    status = "completed" if not equity.empty and variant_dir.exists() else "blocked_missing_market_circuit_replay"
    summary = {
        "status": status,
        "schema_version": "market-circuit-attribution-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest),
        "portfolio_kind": portfolio_kind,
        "variant_dir": str(variant_dir),
        "metrics": {
            "candidate_id": metrics.get("candidate_id", ""),
            "metric_mode": metrics.get("metric_mode", ""),
            "cagr": safe_float(metrics.get("cagr")),
            "max_dd": safe_float(metrics.get("max_dd")),
            "sharpe": safe_float(metrics.get("sharpe")),
            "trade_count": safe_float(metrics.get("trade_count")),
            "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
            "valid_for_production": bool(metrics.get("valid_for_production", False)),
        },
        "drawdown_period_count": int(len(dd)),
        "worst_drawdown": safe_float(dd["drawdown"].min()) if not dd.empty and "drawdown" in dd.columns else math.nan,
        "wrong_substitution_count": int(len(wrong)),
        "source_files": {
            "best_metrics": str((latest / "alpha_selector_market_circuit_grid" / portfolio_kind / "best_metrics.json")),
            "equity_curve": str(variant_dir / "equity_curve.csv"),
            "market_circuit_states": str(variant_dir / "market_circuit_states.csv"),
            "trades": str(variant_dir / "trades.csv"),
            "holdings_daily": str(variant_dir / "holdings_daily.csv"),
        },
    }
    write_json(out / "summary.json", summary)
    (out / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--portfolio-kind", default=DEFAULT_PORTFOLIO_KIND, choices=["main", "concentrated"])
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--market-circuit-dir", default="")
    parser.add_argument("--min-drawdown", type=float, default=-0.05)
    parser.add_argument("--substitution-horizon-days", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        latest_run=args.latest_run,
        portfolio_kind=args.portfolio_kind,
        output_dir=args.output_dir,
        market_circuit_dir=args.market_circuit_dir or None,
        min_drawdown=args.min_drawdown,
        substitution_horizon_days=args.substitution_horizon_days,
    )
    print(json.dumps({"status": payload.get("status"), "drawdowns": payload.get("drawdown_period_count")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
