#!/usr/bin/env python3
"""Leader-basket circuit grid for alpha-selector target books.

Broad SPY/QQQ crash circuits were too blunt for the user's objective: they cut
exposure when the market is weak, but monster leaders can keep working through
index noise. This research-only challenger scales an alpha-selector target book
only when the selected leader basket itself breaks down, then evaluates the
modified target book through the standard broker-ledger replay.

The circuit is point-in-time:
- target membership on day D is the latest target row dated <= D;
- basket state uses only closes available at D;
- injected circuit rows dated D are still filled by broker replay at next close.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_broker_ledger_replay import (  # noqa: E402
    normalize_targets,
    replay as broker_replay,
    repo_path,
    safe_float,
)
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


DEFAULT_OUT_DIR = "outputs/alpha_selector_leader_circuit_grid"
DEFAULT_GRID = "0.90:0.70,0.85:0.60,0.80:0.50,0.70:0.40"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_label(value: Any) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_") or "na"


def parse_grid(value: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(f"Invalid grid item {item!r}; expected caution:crisis")
        left, right = item.split(":", 1)
        caution = float(left)
        crisis = float(right)
        if not (0.0 <= crisis <= caution <= 1.0):
            raise ValueError(f"Invalid multiplier pair {item!r}; require 0 <= crisis <= caution <= 1")
        pairs.append((caution, crisis))
    if not pairs:
        raise ValueError("At least one caution:crisis pair is required")
    out: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for pair in pairs:
        if pair not in seen:
            out.append(pair)
            seen.add(pair)
    return out


def variant_id(caution: float, crisis: float) -> str:
    def fmt(x: float) -> str:
        return f"{x:.2f}".replace(".", "p")

    return f"leader_circuit_caution_{fmt(caution)}_crisis_{fmt(crisis)}"


def target_distance(portfolio_kind: str, metrics: dict[str, Any]) -> float:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio_kind, PORTFOLIO_GOAL_TARGETS["main"])
    cagr = safe_float(metrics.get("cagr"), math.nan)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan)
    if not math.isfinite(cagr) or not math.isfinite(max_dd):
        return math.inf
    return max(0.0, target["cagr"] - cagr) + max(0.0, target["max_dd"] - max_dd)


def rank_key(portfolio_kind: str, metrics: dict[str, Any]) -> tuple[float, float, float]:
    return (
        target_distance(portfolio_kind, metrics),
        -safe_float(metrics.get("cagr"), -1.0),
        abs(safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), -1.0)),
    )


def resolve_target_books(alpha_selector_dir: Path, explicit_target_book: str, top_n: int) -> list[Path]:
    if explicit_target_book:
        return [repo_path(explicit_target_book)]
    paths: list[Path] = []
    for metrics_name in ["best_target_distance_metrics.json", "best_metrics.json"]:
        payload = read_json(alpha_selector_dir / metrics_name)
        target = payload.get("target_book")
        if target:
            path = repo_path(str(target))
            if path.exists() and path not in paths:
                paths.append(path)
    summary_path = alpha_selector_dir / "summary.csv"
    if summary_path.exists() and len(paths) < int(top_n):
        try:
            summary = pd.read_csv(summary_path)
        except Exception:
            summary = pd.DataFrame()
        if not summary.empty and "variant_id" in summary.columns:
            summary = summary[summary.get("status", "").astype(str).eq("completed")].copy()
            for col in ["target_distance", "cagr"]:
                if col not in summary.columns:
                    summary[col] = np.nan
                summary[col] = pd.to_numeric(summary[col], errors="coerce")
            summary = summary.sort_values(["target_distance", "cagr"], ascending=[True, False])
            for _, row in summary.head(max(0, int(top_n) - len(paths))).iterrows():
                vid = str(row.get("variant_id") or "").strip()
                candidate = alpha_selector_dir / vid / "target_book.csv"
                if candidate.exists() and candidate not in paths:
                    paths.append(candidate)
    return paths[: max(1, int(top_n))]


def load_close_map(price_cache: Path, tickers: list[str]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for ticker in tickers:
        px = load_price_series(price_cache, ticker)
        if px.empty or "close" not in px.columns:
            continue
        s = pd.to_numeric(px["close"], errors="coerce").dropna()
        if s.empty:
            continue
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        out[ticker] = s[~s.index.duplicated(keep="last")].sort_index()
    return out


def latest_target(base: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.DataFrame]:
    dates = sorted(pd.to_datetime(base["rebalance_date"], errors="coerce").dropna().dt.normalize().unique())
    eligible = [pd.Timestamp(dt).normalize() for dt in dates if pd.Timestamp(dt).normalize() <= signal_date]
    if not eligible:
        return None, pd.DataFrame()
    chosen = max(eligible)
    rows = base[pd.to_datetime(base["rebalance_date"], errors="coerce").dt.normalize().eq(chosen)].copy()
    return chosen, rows


def build_leader_basket_series(base: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    if base.empty:
        return pd.DataFrame()
    tickers = sorted(base["ticker"].astype(str).str.upper().unique())
    close_map = load_close_map(price_cache, tickers)
    if not close_map:
        return pd.DataFrame()
    return_map = {ticker: series.pct_change() for ticker, series in close_map.items()}
    all_dates = sorted(set().union(*(set(s.index) for s in close_map.values())))
    target_start = pd.to_datetime(base["rebalance_date"], errors="coerce").dropna().min()
    all_dates = [pd.Timestamp(dt).normalize() for dt in all_dates if pd.Timestamp(dt).normalize() >= target_start]
    if len(all_dates) < 40:
        return pd.DataFrame()
    level = 100.0
    rows: list[dict[str, Any]] = []
    for dt in all_dates:
        _, target = latest_target(base, dt)
        if target.empty:
            continue
        ret_sum = 0.0
        weight_sum = 0.0
        available = 0
        for _, row in target.iterrows():
            ticker = str(row.get("ticker") or "").upper()
            weight = max(0.0, safe_float(row.get("weight"), 0.0))
            returns = return_map.get(ticker)
            if returns is None or dt not in returns.index:
                continue
            ret = safe_float(returns.loc[dt], math.nan)
            if not math.isfinite(ret):
                continue
            ret_sum += weight * ret
            weight_sum += weight
            available += 1
        if weight_sum > 1e-8:
            level *= 1.0 + ret_sum / weight_sum
        rows.append(
            {
                "date": dt,
                "leader_basket_level": float(level),
                "available_tickers": int(available),
                "target_tickers": int(target["ticker"].nunique()),
                "available_weight": float(weight_sum),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    return out.dropna(subset=["date"])


def compute_leader_states(
    basket: pd.DataFrame,
    *,
    caution_multiplier: float,
    crisis_multiplier: float,
) -> pd.DataFrame:
    if basket.empty or "leader_basket_level" not in basket.columns:
        return pd.DataFrame()
    d = basket.copy().sort_values("date").set_index("date")
    level = pd.to_numeric(d["leader_basket_level"], errors="coerce")
    d["level"] = level
    d["ma10"] = level.rolling(10, min_periods=8).mean()
    d["ma20"] = level.rolling(20, min_periods=15).mean()
    d["ma50"] = level.rolling(50, min_periods=35).mean()
    d["high20"] = level.rolling(20, min_periods=10).max()
    d["high50"] = level.rolling(50, min_periods=25).max()
    d["ret5"] = level.pct_change(5)
    d["ret10"] = level.pct_change(10)
    d["ret20"] = level.pct_change(20)
    d["dd20"] = level / d["high20"] - 1.0
    d["dd50"] = level / d["high50"] - 1.0

    state = "normal"
    rows: list[dict[str, Any]] = []
    for dt, row in d.iterrows():
        current = safe_float(row.get("level"), math.nan)
        if not math.isfinite(current):
            continue
        ma10 = safe_float(row.get("ma10"), math.nan)
        ma20 = safe_float(row.get("ma20"), math.nan)
        ma50 = safe_float(row.get("ma50"), math.nan)
        ret5 = safe_float(row.get("ret5"), 0.0)
        ret10 = safe_float(row.get("ret10"), 0.0)
        ret20 = safe_float(row.get("ret20"), 0.0)
        dd20 = safe_float(row.get("dd20"), 0.0)
        dd50 = safe_float(row.get("dd50"), 0.0)

        severe_trigger = dd50 <= -0.18 or ret20 <= -0.16 or (math.isfinite(ma50) and current < ma50 and ret20 <= -0.10)
        caution_trigger = dd20 <= -0.10 or ret10 <= -0.08 or (math.isfinite(ma20) and current < ma20 and ret10 <= -0.05)
        reentry_fast = (math.isfinite(ma10) and current > ma10 and ret5 >= 0.035) or dd20 >= -0.04
        reentry_full = (math.isfinite(ma20) and current > ma20 and ret10 >= 0.06) or dd50 >= -0.06

        if state == "normal":
            if severe_trigger:
                state = "crisis"
            elif caution_trigger:
                state = "caution"
        elif state == "caution":
            if severe_trigger:
                state = "crisis"
            elif reentry_fast:
                state = "normal"
        elif state == "crisis":
            if reentry_full:
                state = "normal"
            elif reentry_fast:
                state = "caution"

        multiplier = 1.0
        if state == "caution":
            multiplier = float(caution_multiplier)
        elif state == "crisis":
            multiplier = float(crisis_multiplier)
        rows.append(
            {
                "date": pd.Timestamp(dt).date().isoformat(),
                "state": state,
                "multiplier": multiplier,
                "leader_basket_level": current,
                "ret5": ret5,
                "ret10": ret10,
                "ret20": ret20,
                "dd20": dd20,
                "dd50": dd50,
                "severe_trigger": bool(severe_trigger),
                "caution_trigger": bool(caution_trigger),
                "reentry_fast": bool(reentry_fast),
                "reentry_full": bool(reentry_full),
                "available_tickers": int(safe_float(row.get("available_tickers"), 0.0)),
                "target_tickers": int(safe_float(row.get("target_tickers"), 0.0)),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    return out


def build_circuit_target_book(base: pd.DataFrame, states: pd.DataFrame, output_dir: Path) -> tuple[Path, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if base.empty or states.empty:
        path = output_dir / "leader_circuit_target_book.csv"
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(path, index=False)
        return path, pd.DataFrame()
    base = base.copy()
    base["rebalance_date"] = pd.to_datetime(base["rebalance_date"], errors="coerce").dt.normalize()
    base_dates = set(base["rebalance_date"].dropna())
    states = states.sort_values("date").copy()
    states["prev_multiplier"] = states["multiplier"].shift(1)
    change_dates = set(states.loc[states["multiplier"].ne(states["prev_multiplier"]), "date"].dropna())
    event_dates = sorted(base_dates | change_dates)
    state_by_date = states.set_index("date")

    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for raw_dt in event_dates:
        signal_date = pd.Timestamp(raw_dt).normalize()
        state_rows = state_by_date.loc[:signal_date]
        if state_rows.empty:
            state = "normal"
            multiplier = 1.0
        else:
            last = state_rows.iloc[-1]
            state = str(last.get("state") or "normal")
            multiplier = safe_float(last.get("multiplier"), 1.0)
        source_dt, target = latest_target(base, signal_date)
        if source_dt is None or target.empty:
            continue
        invested = 0.0
        for _, row in target.iterrows():
            weight = max(0.0, safe_float(row.get("weight"), 0.0) * multiplier)
            if weight <= 1e-12:
                continue
            rec = row.to_dict()
            rec["rebalance_date"] = signal_date.date().isoformat()
            rec["weight"] = weight
            rec["leader_circuit_state"] = state
            rec["leader_circuit_multiplier"] = multiplier
            rec["leader_circuit_source_rebalance_date"] = pd.Timestamp(source_dt).date().isoformat()
            rec["leader_circuit_target_book"] = True
            rows.append(rec)
            invested += weight
        events.append(
            {
                "rebalance_date": signal_date.date().isoformat(),
                "source_rebalance_date": pd.Timestamp(source_dt).date().isoformat(),
                "state": state,
                "multiplier": multiplier,
                "stock_weight_sum": invested,
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    target_path = output_dir / "leader_circuit_target_book.csv"
    out.to_csv(target_path, index=False)
    events_df = pd.DataFrame(events)
    events_df.to_csv(output_dir / "leader_circuit_events.csv", index=False)
    return target_path, events_df


def run_one_target(
    target_book: Path,
    *,
    args: argparse.Namespace,
    output_dir: Path,
    caution: float,
    crisis: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(target_book, low_memory=False) if target_book.exists() else pd.DataFrame()
    base = normalize_targets(raw, portfolio_kind=args.portfolio_kind)
    basket = build_leader_basket_series(base, repo_path(args.price_cache))
    basket.to_csv(output_dir / "leader_basket_series.csv", index=False)
    states = compute_leader_states(basket, caution_multiplier=caution, crisis_multiplier=crisis)
    states.to_csv(output_dir / "leader_circuit_states.csv", index=False)
    circuit_target, events = build_circuit_target_book(base, states, output_dir)
    try:
        metrics = broker_replay(
            target_book=circuit_target,
            price_cache=repo_path(args.price_cache),
            output_dir=output_dir,
            portfolio_kind=args.portfolio_kind,
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            integer_shares=not bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
        )
    except Exception as exc:
        metrics = {
            "status": "blocked",
            "reason": f"broker replay failed: {type(exc).__name__}: {exc}",
            "valid_for_production": False,
        }
    metrics.update(
        {
            "metric_mode": "alpha_selector_leader_circuit_next_close",
            "data_mode": "daily_selected_leader_basket_circuit",
            "portfolio_kind": args.portfolio_kind,
            "source_target_book": str(target_book),
            "leader_circuit_target_book": str(circuit_target),
            "caution_multiplier": float(caution),
            "crisis_multiplier": float(crisis),
            "circuit_event_count": int(len(events)),
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": bool(metrics.get("valid_for_production")),
        }
    )
    write_json(output_dir / "metrics.json", metrics)
    return metrics


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    alpha_selector_dir = repo_path(args.alpha_selector_dir)
    target_books = resolve_target_books(alpha_selector_dir, args.target_book, int(args.top_variants))
    pairs = parse_grid(args.grid)
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for target_book in target_books:
        target_label = clean_label(target_book.parent.name)
        for caution, crisis in pairs:
            vid = f"{target_label}_{variant_id(caution, crisis)}"
            variant_dir = output_dir / vid
            metrics = run_one_target(target_book, args=args, output_dir=variant_dir, caution=caution, crisis=crisis)
            metrics["leader_circuit_grid_variant"] = vid
            write_json(variant_dir / "metrics.json", metrics)
            row = {
                "variant_id": vid,
                "status": metrics.get("status"),
                "portfolio_kind": args.portfolio_kind,
                "source_target_book": str(target_book),
                "caution_multiplier": caution,
                "crisis_multiplier": crisis,
                "cagr": metrics.get("cagr"),
                "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                "sharpe": metrics.get("sharpe"),
                "trade_count": metrics.get("trade_count"),
                "avg_cash_weight": metrics.get("avg_cash_weight"),
                "total_fees_usd": metrics.get("total_fees_usd"),
                "circuit_event_count": metrics.get("circuit_event_count"),
                "target_distance": target_distance(args.portfolio_kind, metrics),
                "valid_for_production": bool(metrics.get("valid_for_production")),
                "reason": metrics.get("reason", ""),
            }
            rows.append(row)
            if metrics.get("status") == "completed" and metrics.get("valid_for_production"):
                completed.append(metrics)
    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr"], ascending=[True, False]).reset_index(drop=True)
    summary.to_csv(output_dir / "summary.csv", index=False)
    if completed:
        best = sorted(completed, key=lambda m: rank_key(args.portfolio_kind, m))[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "status": "completed",
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_leader_circuit_grid_best",
                "metric_mode": "alpha_selector_leader_circuit_grid_best_next_close",
                "variant_count": len(rows),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed leader-circuit grid variants",
            "portfolio_kind": args.portfolio_kind,
            "variant_count": len(rows),
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        f"# Alpha Selector Leader Circuit Grid: {args.portfolio_kind}",
        "",
        "Research-only account-ledger grid. It scales only the selected leader basket when that basket breaks, not when broad benchmarks wobble.",
        "",
        f"- variants: {len(rows)}",
        f"- best_variant: {best_payload.get('leader_circuit_grid_variant', '')}",
        f"- best_cagr: {safe_float(best_payload.get('cagr'), math.nan):.2%}" if best_payload.get("cagr") is not None else "- best_cagr: n/a",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown')), math.nan):.2%}"
        if best_payload.get("max_dd", best_payload.get("max_drawdown")) is not None
        else "- best_max_dd: n/a",
        f"- best_sharpe: {safe_float(best_payload.get('sharpe'), math.nan):.3f}" if best_payload.get("sharpe") is not None else "- best_sharpe: n/a",
        "",
        "Promotion requires broker-ledger target gates, stress-window review, and human approval.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha-selector-dir", default="outputs/alpha_selector_broker_grid/main")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--top-variants", type=int, default=2)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload.get("status"), "cagr": payload.get("cagr"), "max_dd": payload.get("max_dd")}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
