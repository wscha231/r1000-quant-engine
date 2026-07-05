#!/usr/bin/env python3
"""Measure run287 end-date sensitivity from existing broker equity curves.

This is a measurement-only tool. It does not dispatch a workflow, replay trades,
change target books, or tune policy thresholds. It answers one question before
new alpha work: is the 2026-07-02 shortfall a broad deficit or a single
end-date shock?
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


PORTFOLIOS = ("main", "concentrated")
TARGETS = {
    "main": {"cagr": 0.35, "max_dd": -0.25},
    "concentrated": {"cagr": 0.50, "max_dd": -0.25},
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_equity_curve(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"equity curve not found: {path}")
    df = pd.read_csv(path)
    if "date" not in df.columns or "equity_usd" not in df.columns:
        raise ValueError(f"{path} must include date and equity_usd")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["equity_usd"] = pd.to_numeric(df["equity_usd"], errors="coerce")
    df = df.dropna(subset=["date", "equity_usd"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"equity curve empty: {path}")
    return df


def max_drawdown(equity: pd.Series) -> tuple[float, str, str]:
    values = pd.to_numeric(equity, errors="coerce").astype(float)
    running_peak = values.cummax()
    drawdowns = values / running_peak - 1.0
    trough_idx = int(drawdowns.idxmin()) if not drawdowns.empty else 0
    peak_slice = values.loc[:trough_idx]
    peak_idx = int(peak_slice.idxmax()) if not peak_slice.empty else trough_idx
    return (
        safe_float(drawdowns.loc[trough_idx]),
        "",
        "",
    ), peak_idx, trough_idx


def compute_metrics(frame: pd.DataFrame, starting_capital: float, label: str) -> dict[str, Any]:
    d = frame.sort_values("date").reset_index(drop=True).copy()
    start_date = pd.Timestamp(d["date"].iloc[0])
    end_date = pd.Timestamp(d["date"].iloc[-1])
    ending = safe_float(d["equity_usd"].iloc[-1])
    years = max((end_date - start_date).days / 365.25, 1.0 / 365.25)
    cagr = (ending / starting_capital) ** (1.0 / years) - 1.0 if starting_capital > 0 else 0.0
    daily_returns = pd.to_numeric(d["equity_usd"], errors="coerce").pct_change().dropna()
    sharpe = 0.0
    if not daily_returns.empty:
        std = safe_float(daily_returns.std(ddof=0))
        if std > 1e-12:
            sharpe = safe_float(daily_returns.mean()) / std * math.sqrt(252)
    values = pd.to_numeric(d["equity_usd"], errors="coerce").astype(float)
    running_peak = values.cummax()
    drawdowns = values / running_peak - 1.0
    trough_pos = int(drawdowns.idxmin()) if not drawdowns.empty else 0
    peak_pos = int(values.loc[:trough_pos].idxmax()) if not values.empty else trough_pos
    return {
        "label": label,
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "trading_days": int(len(d)),
        "years": years,
        "starting_capital_usd": starting_capital,
        "ending_capital_usd": ending,
        "cagr": safe_float(cagr),
        "max_dd": safe_float(drawdowns.iloc[trough_pos] if not drawdowns.empty else 0.0),
        "max_dd_peak_date": pd.Timestamp(d["date"].iloc[peak_pos]).date().isoformat(),
        "max_dd_trough_date": pd.Timestamp(d["date"].iloc[trough_pos]).date().isoformat(),
        "sharpe": safe_float(sharpe),
        "avg_cash_weight": safe_float(pd.to_numeric(d.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()),
    }


def endpoint_frame(
    equity: pd.DataFrame,
    *,
    portfolio: str,
    starting_capital: float,
    min_trading_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for idx in range(max(min_trading_days - 1, 0), len(equity)):
        subset = equity.iloc[: idx + 1].copy()
        metrics = compute_metrics(subset, starting_capital, label="full_start_to_endpoint")
        target = TARGETS[portfolio]
        rows.append(
            {
                "portfolio": portfolio,
                "endpoint_date": metrics["end_date"],
                "trading_days": metrics["trading_days"],
                "years": metrics["years"],
                "cagr": metrics["cagr"],
                "max_dd": metrics["max_dd"],
                "sharpe": metrics["sharpe"],
                "ending_capital_usd": metrics["ending_capital_usd"],
                "cagr_gap_to_target": safe_float(metrics["cagr"]) - target["cagr"],
                "max_dd_gap_to_target": safe_float(metrics["max_dd"]) - target["max_dd"],
                "target_pass": bool(metrics["cagr"] >= target["cagr"] and metrics["max_dd"] >= target["max_dd"]),
            }
        )
    return pd.DataFrame(rows)


def percentile_rank(values: pd.Series, value: float) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return float((clean <= value).mean())


def latest_slice(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    if window <= 0:
        return frame.copy()
    return frame.tail(min(window, len(frame))).copy()


def portfolio_payload(root: Path, portfolio: str, min_trading_days: int, lookback_windows: list[int]) -> tuple[dict[str, Any], pd.DataFrame]:
    curve_path = root / portfolio / "equity_curve.csv"
    metrics_path = root / portfolio / "metrics.json"
    metrics = read_json(metrics_path)
    equity = load_equity_curve(curve_path)
    starting_capital = safe_float(metrics.get("starting_capital_usd"), 100000.0)
    endpoints = endpoint_frame(equity, portfolio=portfolio, starting_capital=starting_capital, min_trading_days=min_trading_days)
    actual_date = str(endpoints["endpoint_date"].iloc[-1])
    pre_shock_rows = endpoints[endpoints["endpoint_date"].le("2026-06-29")]
    pre_shock = pre_shock_rows.iloc[-1].to_dict() if not pre_shock_rows.empty else {}
    actual = endpoints.iloc[-1].to_dict()

    lookbacks: dict[str, Any] = {}
    for window in lookback_windows:
        d = latest_slice(endpoints, window)
        lookbacks[f"last_{window}_endpoints"] = {
            "endpoint_count": int(len(d)),
            "target_pass_rate": safe_float(d["target_pass"].mean()) if not d.empty else 0.0,
            "actual_cagr_percentile": percentile_rank(d["cagr"], safe_float(actual.get("cagr"))),
            "actual_max_dd_percentile": percentile_rank(d["max_dd"], safe_float(actual.get("max_dd"))),
            "median_cagr": safe_float(d["cagr"].median()) if not d.empty else 0.0,
            "median_max_dd": safe_float(d["max_dd"].median()) if not d.empty else 0.0,
            "worst_cagr": safe_float(d["cagr"].min()) if not d.empty else 0.0,
            "worst_cagr_endpoint": str(d.loc[d["cagr"].idxmin(), "endpoint_date"]) if not d.empty else "",
            "worst_max_dd": safe_float(d["max_dd"].min()) if not d.empty else 0.0,
            "worst_max_dd_endpoint": str(d.loc[d["max_dd"].idxmin(), "endpoint_date"]) if not d.empty else "",
        }

    delta_vs_pre_shock = {}
    if pre_shock:
        delta_vs_pre_shock = {
            "pre_shock_endpoint": pre_shock.get("endpoint_date"),
            "actual_endpoint": actual_date,
            "cagr_delta": safe_float(actual.get("cagr")) - safe_float(pre_shock.get("cagr")),
            "cagr_delta_pp": (safe_float(actual.get("cagr")) - safe_float(pre_shock.get("cagr"))) * 100,
            "max_dd_delta": safe_float(actual.get("max_dd")) - safe_float(pre_shock.get("max_dd")),
            "ending_capital_delta_usd": safe_float(actual.get("ending_capital_usd")) - safe_float(pre_shock.get("ending_capital_usd")),
            "ending_capital_delta_pct": safe_float(actual.get("ending_capital_usd")) / max(safe_float(pre_shock.get("ending_capital_usd")), 1.0) - 1.0,
        }

    actual["is_actual_end"] = True
    payload = {
        "portfolio": portfolio,
        "equity_curve": str(curve_path),
        "metrics": str(metrics_path),
        "metric_mode": metrics.get("metric_mode", "broker_ledger_next_close_cash_carry"),
        "target": TARGETS[portfolio],
        "endpoint_count": int(len(endpoints)),
        "actual_endpoint": actual,
        "pre_shock_endpoint": pre_shock,
        "delta_actual_minus_pre_shock": delta_vs_pre_shock,
        "lookbacks": lookbacks,
    }
    return payload, endpoints


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 Rolling Window Deficit",
        "",
        "Status: `completed`",
        "",
        "This is equity-curve-only attribution. It does not replay trades, mutate",
        "target books, dispatch a fullrun, or tune thresholds.",
        "",
        "## Summary",
        "",
        "| Portfolio | Actual end | CAGR | MaxDD | Target pass | Delta CAGR vs 2026-06-29 | Last 20 CAGR pctile | Last 20 pass rate | Last 252 pass rate |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for portfolio, item in payload["portfolios"].items():
        actual = item["actual_endpoint"]
        delta = item.get("delta_actual_minus_pre_shock", {})
        lookback20 = item["lookbacks"].get("last_20_endpoints", {})
        lookback252 = item["lookbacks"].get("last_252_endpoints", {})
        lines.append(
            "| {portfolio} | {end} | {cagr:.2%} | {max_dd:.2%} | {target_pass} | {delta_pp:.2f}pp | {pct20:.1%} | {pass20:.1%} | {pass252:.1%} |".format(
                portfolio=portfolio,
                end=actual.get("endpoint_date", ""),
                cagr=safe_float(actual.get("cagr")),
                max_dd=safe_float(actual.get("max_dd")),
                target_pass=str(bool(actual.get("target_pass"))).lower(),
                delta_pp=safe_float(delta.get("cagr_delta_pp")),
                pct20=safe_float(lookback20.get("actual_cagr_percentile")),
                pass20=safe_float(lookback20.get("target_pass_rate")),
                pass252=safe_float(lookback252.get("target_pass_rate")),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Low latest-end percentile means the `2026-07-02` endpoint is a poor",
            "  endpoint relative to nearby endpoints; do not fit a rule directly to it.",
            "- A broad low pass rate means the deficit is structural across many",
            "  endpoints and needs ex-ante alpha/risk work.",
            "- A high pass rate with a low latest-end percentile points to end-date",
            "  shock sensitivity rather than a general alpha failure.",
            "- A low pass rate across many endpoints means the target is not robustly",
            "  met even if the immediate endpoint shock explains the last few days.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_path(args.root)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    lookback_windows = [int(x) for x in str(args.lookback_windows).split(",") if str(x).strip()]
    payload: dict[str, Any] = {
        "schema_version": "run287-rolling-window-deficit-v1",
        "status": "completed",
        "root": str(root),
        "metric_mode": "broker_ledger_next_close_cash_carry",
        "research_only": True,
        "fullrun_dispatched": False,
        "production_mutation_allowed": False,
        "threshold_tuning_performed": False,
        "min_trading_days": int(args.min_trading_days),
        "lookback_windows": lookback_windows,
        "portfolios": {},
    }
    frames: list[pd.DataFrame] = []
    for portfolio in PORTFOLIOS:
        item, endpoints = portfolio_payload(
            root,
            portfolio,
            min_trading_days=int(args.min_trading_days),
            lookback_windows=lookback_windows,
        )
        payload["portfolios"][portfolio] = item
        frames.append(endpoints)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    combined.to_csv(output_dir / "end_date_metrics.csv", index=False)
    payload["artifacts"] = {
        "end_date_metrics": str(output_dir / "end_date_metrics.csv"),
        "summary": str(output_dir / "summary.json"),
        "report": str(output_dir / "report.md"),
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="outputs/run287_metric_sidecar/generated_book_cash_carry")
    parser.add_argument("--output-dir", default="outputs/run287_rolling_window_deficit")
    parser.add_argument("--min-trading-days", type=int, default=252)
    parser.add_argument("--lookback-windows", default="20,63,126,252")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "output_dir": payload["artifacts"]["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
