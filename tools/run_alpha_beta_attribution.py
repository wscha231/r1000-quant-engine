#!/usr/bin/env python3
"""Alpha/beta attribution for broker-ledger portfolio returns.

Measurement-only diagnostic. This tool does not change selection, scoring,
cash policy, target books, workflows, or trading. It decomposes the broker
ledger equity curve into broad market, growth/tech, and semiconductor factor
exposures, then adds holdings-based name contribution diagnostics.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402


SCHEMA_VERSION = "alpha-beta-attribution-v1"
PORTFOLIOS = ("main", "concentrated")
BENCHMARKS = ("SPY", "QQQ", "SMH", "SOXX")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _equity_curve(latest_run: Path, portfolio: str) -> pd.DataFrame:
    raw = read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
    if raw.empty or "date" not in raw.columns:
        return pd.DataFrame()
    out = raw.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None)
    out = out.dropna(subset=["date"]).sort_values("date")
    equity_col = ""
    for candidate in ("equity_usd", "equity", "account_value", "account_value_usd"):
        if candidate in out.columns:
            equity_col = candidate
            break
    if not equity_col:
        return pd.DataFrame()
    out["equity_usd"] = pd.to_numeric(out[equity_col], errors="coerce")
    out["cash_weight"] = pd.to_numeric(out.get("cash_weight"), errors="coerce").fillna(0.0)
    out = out.dropna(subset=["equity_usd"])
    out["portfolio_return"] = out["equity_usd"].pct_change()
    return out[["date", "equity_usd", "cash_weight", "portfolio_return"]].dropna(subset=["portfolio_return"])


def _benchmark_returns(price_cache: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ticker in BENCHMARKS:
        px = load_price_series(price_cache, ticker)
        if px.empty or "close" not in px.columns:
            continue
        frame = px[["close"]].copy()
        frame.index = pd.to_datetime(frame.index, errors="coerce").tz_localize(None)
        frame = frame[frame.index.notna()].sort_index()
        frame[f"{ticker.lower()}_return"] = pd.to_numeric(frame["close"], errors="coerce").pct_change()
        frames.append(frame[[f"{ticker.lower()}_return"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1).dropna(how="all")
    out.index.name = "date"
    out = out.reset_index()
    if "smh_return" in out.columns and "soxx_return" in out.columns:
        out["semis_return"] = out[["smh_return", "soxx_return"]].mean(axis=1)
    elif "smh_return" in out.columns:
        out["semis_return"] = out["smh_return"]
    elif "soxx_return" in out.columns:
        out["semis_return"] = out["soxx_return"]
    return out


def _factor_frame(equity: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    if equity.empty or bench.empty:
        return pd.DataFrame()
    merged = equity.merge(bench, on="date", how="inner").sort_values("date")
    if merged.empty or "spy_return" not in merged.columns:
        return pd.DataFrame()
    merged["qqq_minus_spy"] = merged.get("qqq_return", merged["spy_return"]) - merged["spy_return"]
    merged["semis_minus_qqq"] = merged.get("semis_return", merged.get("qqq_return", merged["spy_return"])) - merged.get("qqq_return", merged["spy_return"])
    cols = ["portfolio_return", "spy_return", "qqq_minus_spy", "semis_minus_qqq", "cash_weight"]
    return merged[["date", "equity_usd", *cols]].replace([np.inf, -np.inf], np.nan).dropna(subset=cols)


def _ols(frame: pd.DataFrame) -> dict[str, Any]:
    if len(frame) < 30:
        return {"status": "blocked", "reason": "insufficient_aligned_observations", "observations": int(len(frame))}
    y = frame["portfolio_return"].to_numpy(dtype=float)
    x_cols = ["spy_return", "qqq_minus_spy", "semis_minus_qqq"]
    x = frame[x_cols].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(frame)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    pred = design @ coef
    resid = y - pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    daily_means = frame[x_cols].mean()
    alpha_daily = float(coef[0])
    contribs = {
        "spy_factor_annualized": float(coef[1] * daily_means["spy_return"] * 252.0),
        "qqq_growth_factor_annualized": float(coef[2] * daily_means["qqq_minus_spy"] * 252.0),
        "semiconductor_factor_annualized": float(coef[3] * daily_means["semis_minus_qqq"] * 252.0),
    }
    return {
        "status": "completed",
        "observations": int(len(frame)),
        "start_date": str(pd.Timestamp(frame["date"].iloc[0]).date()),
        "end_date": str(pd.Timestamp(frame["date"].iloc[-1]).date()),
        "alpha_daily": alpha_daily,
        "stock_selection_residual_alpha": float(alpha_daily * 252.0),
        "spy_beta": float(coef[1]),
        "qqq_beta": float(coef[2]),
        "smh_soxx_semiconductor_beta": float(coef[3]),
        "sector_theme_beta_proxy": float(coef[2] + coef[3]),
        "sector_theme_beta_method": "QQQ-minus-SPY plus SMH/SOXX-minus-QQQ proxy; not official sector ETF attribution",
        "r_squared": float(r2),
        "residual_vol_annualized": float(np.std(resid, ddof=1) * math.sqrt(252.0)) if len(resid) > 1 else 0.0,
        **contribs,
    }


def _portfolio_cagr(eq: pd.DataFrame) -> float:
    if eq.empty or len(eq) < 2:
        return float("nan")
    start = safe_float(eq["equity_usd"].iloc[0], math.nan)
    end = safe_float(eq["equity_usd"].iloc[-1], math.nan)
    days = (pd.Timestamp(eq["date"].iloc[-1]) - pd.Timestamp(eq["date"].iloc[0])).days
    years = max(days / 365.25, 1e-9)
    if not math.isfinite(start) or not math.isfinite(end) or start <= 0 or end <= 0:
        return float("nan")
    return float((end / start) ** (1.0 / years) - 1.0)


def _mdd_window(eq: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if eq.empty or "equity_usd" not in eq.columns:
        return None, None
    e = eq.sort_values("date").copy()
    e["running_peak"] = e["equity_usd"].cummax()
    e["drawdown"] = e["equity_usd"] / e["running_peak"] - 1.0
    trough_idx = int(e["drawdown"].idxmin())
    peak_idx = int(e.iloc[: trough_idx + 1]["equity_usd"].idxmax())
    return pd.Timestamp(e.loc[peak_idx, "date"]), pd.Timestamp(e.loc[trough_idx, "date"])


def _name_contributions(latest_run: Path, portfolio: str, start_equity: float, peak: pd.Timestamp | None, trough: pd.Timestamp | None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    path = latest_run / "broker_replay" / portfolio / "holdings_daily.csv"
    h = read_csv(path)
    if h.empty or "date" not in h.columns or "ticker" not in h.columns:
        positions_path = latest_run / "broker_replay" / portfolio / "positions_latest.csv"
        positions = read_csv(positions_path)
        required = {"ticker", "realized_pnl_usd", "unrealized_pnl_usd"}
        if positions.empty or not required.issubset(set(positions.columns)):
            return pd.DataFrame(), pd.DataFrame(), {"status": "missing_holdings_daily", "source": str(path)}
        contrib = positions.copy()
        contrib["ticker"] = contrib["ticker"].astype(str).str.upper().str.strip()
        contrib["realized_pnl_usd"] = pd.to_numeric(contrib["realized_pnl_usd"], errors="coerce").fillna(0.0)
        contrib["unrealized_pnl_usd"] = pd.to_numeric(contrib["unrealized_pnl_usd"], errors="coerce").fillna(0.0)
        contrib["pnl_usd"] = contrib["realized_pnl_usd"] + contrib["unrealized_pnl_usd"]
        contrib["contribution_return_on_start"] = contrib["pnl_usd"] / max(start_equity, 1e-9)
        total_positive = float(contrib.loc[contrib["pnl_usd"] > 0, "pnl_usd"].sum())
        contrib["positive_contribution_share"] = contrib["pnl_usd"].clip(lower=0.0) / max(total_positive, 1e-9)
        contrib = contrib.sort_values("pnl_usd", ascending=False)
        top = contrib.head(5)
        total_return = float(contrib["pnl_usd"].sum()) / max(start_equity, 1e-9)
        summary = {
            "status": "completed_positions_latest_fallback_partial",
            "source": str(positions_path),
            "coverage_note": "positions_latest fallback includes current open positions plus realized pnl tracked on those tickers; fully closed historical names may be absent",
            "top_1_winner_contribution": float(contrib.head(1)["contribution_return_on_start"].sum()) if not contrib.empty else 0.0,
            "top_3_winner_contribution": float(contrib.head(3)["contribution_return_on_start"].sum()) if not contrib.empty else 0.0,
            "top_5_winner_contribution": float(top["contribution_return_on_start"].sum()) if not top.empty else 0.0,
            "top_5_positive_share": float(top["pnl_usd"].clip(lower=0.0).sum() / max(total_positive, 1e-9)) if not top.empty else 0.0,
            "position_concentration_alpha": float(contrib.head(5)["contribution_return_on_start"].sum() - total_return) if not contrib.empty else 0.0,
        }
        return contrib, pd.DataFrame(), summary
    out = h.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    value_col = "market_value_usd" if "market_value_usd" in out.columns else "market_value" if "market_value" in out.columns else ""
    if not value_col:
        return pd.DataFrame(), pd.DataFrame(), {"status": "missing_market_value", "source": str(path)}
    out["market_value_usd"] = pd.to_numeric(out[value_col], errors="coerce").fillna(0.0)
    out = out.dropna(subset=["date"]).sort_values(["ticker", "date"])
    first = out.groupby("ticker")["market_value_usd"].first()
    last = out.groupby("ticker")["market_value_usd"].last()
    contrib = (last - first).rename("pnl_usd").reset_index()
    contrib["contribution_return_on_start"] = contrib["pnl_usd"] / max(start_equity, 1e-9)
    total_positive = float(contrib.loc[contrib["pnl_usd"] > 0, "pnl_usd"].sum())
    contrib["positive_contribution_share"] = contrib["pnl_usd"].clip(lower=0.0) / max(total_positive, 1e-9)
    contrib = contrib.sort_values("pnl_usd", ascending=False)
    drawdown = pd.DataFrame()
    if peak is not None and trough is not None:
        win = out[(out["date"] >= peak) & (out["date"] <= trough)].copy()
        if not win.empty:
            first_w = win.groupby("ticker")["market_value_usd"].first()
            last_w = win.groupby("ticker")["market_value_usd"].last()
            drawdown = (last_w - first_w).rename("drawdown_pnl_usd").reset_index().sort_values("drawdown_pnl_usd")
            drawdown["drawdown_contribution_return_on_start"] = drawdown["drawdown_pnl_usd"] / max(start_equity, 1e-9)
    top = contrib.head(5)
    total_return = float(contrib["pnl_usd"].sum()) / max(start_equity, 1e-9)
    summary = {
        "status": "completed",
        "source": str(path),
        "top_1_winner_contribution": float(contrib.head(1)["contribution_return_on_start"].sum()) if not contrib.empty else 0.0,
        "top_3_winner_contribution": float(contrib.head(3)["contribution_return_on_start"].sum()) if not contrib.empty else 0.0,
        "top_5_winner_contribution": float(top["contribution_return_on_start"].sum()) if not top.empty else 0.0,
        "top_5_positive_share": float(top["pnl_usd"].clip(lower=0.0).sum() / max(total_positive, 1e-9)) if not top.empty else 0.0,
        "position_concentration_alpha": float(contrib.head(5)["contribution_return_on_start"].sum() - total_return) if not contrib.empty else 0.0,
    }
    return contrib, drawdown, summary


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Alpha/Beta Attribution",
        "",
        "Measurement-only diagnostic. No strategy, target-book, cash-policy, workflow, or trading mutation.",
        "",
    ]
    for portfolio, block in sorted((payload.get("portfolios") or {}).items()):
        lines.extend(
            [
                f"## {portfolio}",
                "",
                f"- status: `{block.get('status')}`",
                f"- observations: {block.get('observations', 0)}",
                f"- SPY beta: `{safe_float(block.get('spy_beta'), 0.0):.3f}`",
                f"- QQQ growth beta: `{safe_float(block.get('qqq_beta'), 0.0):.3f}`",
                f"- SMH/SOXX semiconductor beta: `{safe_float(block.get('smh_soxx_semiconductor_beta'), 0.0):.3f}`",
                f"- residual alpha annualized: `{safe_float(block.get('stock_selection_residual_alpha'), 0.0):.2%}`",
                f"- cash drag proxy: `{safe_float(block.get('cash_drag'), 0.0):.2%}`",
                f"- R^2: `{safe_float(block.get('r_squared'), 0.0):.3f}`",
                f"- top 5 winner contribution: `{safe_float(block.get('top_5_winner_contribution'), 0.0):.2%}`",
                "",
            ]
        )
    return "\n".join(lines)


def analyze_portfolio(latest_run: Path, price_cache: Path, output_dir: Path, portfolio: str) -> dict[str, Any]:
    eq = _equity_curve(latest_run, portfolio)
    bench = _benchmark_returns(price_cache)
    frame = _factor_frame(eq, bench)
    model = _ols(frame)
    metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    start_equity = safe_float(eq["equity_usd"].iloc[0], 0.0) if not eq.empty else 0.0
    peak, trough = _mdd_window(eq)
    contrib, drawdown, name_summary = _name_contributions(latest_run, portfolio, start_equity, peak, trough)
    portfolio_dir = output_dir / portfolio
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    if not frame.empty:
        frame.to_csv(portfolio_dir / "factor_returns.csv", index=False)
    if not contrib.empty:
        contrib.to_csv(portfolio_dir / "name_contribution.csv", index=False)
    if not drawdown.empty:
        drawdown.to_csv(portfolio_dir / "drawdown_contribution_by_name.csv", index=False)
    avg_cash = safe_float(eq.get("cash_weight", pd.Series(dtype=float)).mean(), 0.0) if not eq.empty else 0.0
    spy_ann = safe_float(frame.get("spy_return", pd.Series(dtype=float)).mean(), 0.0) * 252.0 if not frame.empty else 0.0
    payload = {
        "schema_version": SCHEMA_VERSION,
        "portfolio": portfolio,
        "status": model.get("status", "blocked"),
        "metric_mode": "broker_ledger_next_close",
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "broker_cagr": safe_float(metrics.get("cagr"), _portfolio_cagr(eq)),
        "broker_max_dd": safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan),
        "cash_drag": float(avg_cash * max(spy_ann, 0.0)),
        "name_contribution_status": name_summary.get("status"),
        "name_contribution_source": name_summary.get("source"),
        **model,
        **{k: v for k, v in name_summary.items() if k not in {"status", "source"}},
    }
    write_json(portfolio_dir / "summary.json", payload)
    return payload


def run(latest_run: Path, price_cache: Path, output_dir: Path, portfolios: tuple[str, ...] = PORTFOLIOS) -> dict[str, Any]:
    latest_run = repo_path(latest_run)
    price_cache = repo_path(price_cache)
    output_dir = repo_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rolled = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "metric_mode": "broker_ledger_next_close",
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "portfolios": {},
    }
    rows = []
    for portfolio in portfolios:
        payload = analyze_portfolio(latest_run, price_cache, output_dir, portfolio)
        rolled["portfolios"][portfolio] = payload
        rows.append(payload)
    pd.DataFrame(rows).to_csv(output_dir / "portfolio_factor_summary.csv", index=False)
    write_json(output_dir / "summary.json", rolled)
    write_text(output_dir / "report.md", _render_report(rolled))
    return rolled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/alpha_beta_attribution")
    parser.add_argument("--portfolios", nargs="+", default=list(PORTFOLIOS))
    args = parser.parse_args(argv)
    payload = run(repo_path(args.latest_run), repo_path(args.price_cache), repo_path(args.output_dir), tuple(args.portfolios))
    for portfolio, block in payload.get("portfolios", {}).items():
        print(
            f"{portfolio}: status={block.get('status')} "
            f"spy_beta={safe_float(block.get('spy_beta'), 0.0):.3f} "
            f"semis_beta={safe_float(block.get('smh_soxx_semiconductor_beta'), 0.0):.3f} "
            f"alpha={safe_float(block.get('stock_selection_residual_alpha'), 0.0):.2%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
