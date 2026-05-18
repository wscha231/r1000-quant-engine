#!/usr/bin/env python3
"""Shadow-account drawdown circuit for alpha-selector target books.

This research-only sidecar keeps a full-risk *shadow* broker ledger for the
source target book, then scales the real target book when that observable
shadow account is in drawdown. The design is intentionally live-maintainable:
the shadow ledger can be paper-run every day without using future returns, and
the scaled target rows are still filled by the standard next-close broker
ledger replay.
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

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_broker_ledger_replay import (  # noqa: E402
    normalize_targets,
    replay as broker_replay,
    repo_path,
    safe_float,
)


DEFAULT_OUT_DIR = "outputs/alpha_selector_shadow_drawdown_grid"
DEFAULT_GRID = "-0.08:-0.14:0.50:0.25:-0.03,-0.12:-0.20:0.75:0.50:-0.06,-0.15:-0.25:0.80:0.55:-0.08,-0.05:-0.10:0.55:0.20:-0.02"


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


def parse_grid(value: str) -> list[tuple[float, float, float, float, float]]:
    """Parse caution_dd:crisis_dd:caution_mult:crisis_mult:reentry_dd."""

    items: list[tuple[float, float, float, float, float]] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 5:
            raise ValueError(f"Invalid grid item {item!r}; expected caution_dd:crisis_dd:caution_mult:crisis_mult:reentry_dd")
        caution_dd, crisis_dd, caution_mult, crisis_mult, reentry_dd = [float(x) for x in parts]
        if not (-1.0 < crisis_dd <= caution_dd < 0.0):
            raise ValueError(f"Invalid drawdown thresholds {item!r}; require -1 < crisis_dd <= caution_dd < 0")
        if not (0.0 <= crisis_mult <= caution_mult <= 1.0):
            raise ValueError(f"Invalid multipliers {item!r}; require 0 <= crisis_mult <= caution_mult <= 1")
        if not (crisis_dd < reentry_dd <= 0.0):
            raise ValueError(f"Invalid reentry threshold {item!r}; require crisis_dd < reentry_dd <= 0")
        items.append((caution_dd, crisis_dd, caution_mult, crisis_mult, reentry_dd))
    if not items:
        raise ValueError("At least one shadow drawdown grid item is required")
    out: list[tuple[float, float, float, float, float]] = []
    seen: set[tuple[float, float, float, float, float]] = set()
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def fmt(value: float) -> str:
    return f"{value:.2f}".replace("-", "m").replace(".", "p")


def variant_id(caution_dd: float, crisis_dd: float, caution_mult: float, crisis_mult: float, reentry_dd: float) -> str:
    return (
        f"shadow_dd_c{fmt(caution_dd)}_x{fmt(crisis_dd)}"
        f"_m{fmt(caution_mult)}_{fmt(crisis_mult)}_r{fmt(reentry_dd)}"
    )


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


def latest_target(base: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.DataFrame]:
    dates = sorted(pd.to_datetime(base["rebalance_date"], errors="coerce").dropna().dt.normalize().unique())
    eligible = [pd.Timestamp(dt).normalize() for dt in dates if pd.Timestamp(dt).normalize() <= signal_date]
    if not eligible:
        return None, pd.DataFrame()
    chosen = max(eligible)
    rows = base[pd.to_datetime(base["rebalance_date"], errors="coerce").dt.normalize().eq(chosen)].copy()
    return chosen, rows


def compute_shadow_states(
    equity_curve: pd.DataFrame,
    *,
    caution_dd: float,
    crisis_dd: float,
    caution_multiplier: float,
    crisis_multiplier: float,
    reentry_dd: float,
) -> pd.DataFrame:
    if equity_curve.empty or "equity_usd" not in equity_curve.columns:
        return pd.DataFrame()
    d = equity_curve.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["equity_usd"] = pd.to_numeric(d["equity_usd"], errors="coerce")
    d = d.dropna(subset=["date", "equity_usd"]).sort_values("date").drop_duplicates("date", keep="last")
    if d.empty:
        return pd.DataFrame()
    d["peak_equity_usd"] = d["equity_usd"].cummax()
    d["shadow_drawdown"] = d["equity_usd"] / d["peak_equity_usd"] - 1.0
    d["ret5"] = d["equity_usd"].pct_change(5)
    d["ret10"] = d["equity_usd"].pct_change(10)
    d["ma10"] = d["equity_usd"].rolling(10, min_periods=6).mean()

    state = "normal"
    rows: list[dict[str, Any]] = []
    for _, row in d.iterrows():
        dt = pd.Timestamp(row["date"]).normalize()
        dd = safe_float(row.get("shadow_drawdown"), 0.0)
        ret5 = safe_float(row.get("ret5"), 0.0)
        ret10 = safe_float(row.get("ret10"), 0.0)
        equity = safe_float(row.get("equity_usd"), math.nan)
        ma10 = safe_float(row.get("ma10"), math.nan)

        crisis_trigger = dd <= crisis_dd or ret10 <= -0.16
        caution_trigger = dd <= caution_dd or ret5 <= -0.08
        reentry_trigger = dd >= reentry_dd and (ret5 >= 0.015 or (math.isfinite(ma10) and equity >= ma10))
        full_reentry_trigger = dd >= min(-0.02, reentry_dd / 2.0) and ret10 >= 0.025

        if state == "normal":
            if crisis_trigger:
                state = "crisis"
            elif caution_trigger:
                state = "caution"
        elif state == "caution":
            if crisis_trigger:
                state = "crisis"
            elif reentry_trigger:
                state = "normal"
        elif state == "crisis":
            if full_reentry_trigger:
                state = "normal"
            elif reentry_trigger:
                state = "caution"

        multiplier = 1.0
        if state == "caution":
            multiplier = float(caution_multiplier)
        elif state == "crisis":
            multiplier = float(crisis_multiplier)
        rows.append(
            {
                "date": dt.date().isoformat(),
                "state": state,
                "multiplier": multiplier,
                "shadow_equity_usd": equity,
                "peak_equity_usd": safe_float(row.get("peak_equity_usd"), math.nan),
                "shadow_drawdown": dd,
                "ret5": ret5,
                "ret10": ret10,
                "crisis_trigger": bool(crisis_trigger),
                "caution_trigger": bool(caution_trigger),
                "reentry_trigger": bool(reentry_trigger),
                "full_reentry_trigger": bool(full_reentry_trigger),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    return out.dropna(subset=["date"])


def build_scaled_target_book(base: pd.DataFrame, states: pd.DataFrame, output_dir: Path) -> tuple[Path, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "shadow_drawdown_target_book.csv"
    if base.empty or states.empty:
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
            shadow_dd = 0.0
        else:
            last = state_rows.iloc[-1]
            state = str(last.get("state") or "normal")
            multiplier = safe_float(last.get("multiplier"), 1.0)
            shadow_dd = safe_float(last.get("shadow_drawdown"), 0.0)
        source_dt, target = latest_target(base, signal_date)
        if source_dt is None or target.empty:
            continue
        stock_weight_sum = 0.0
        for _, row in target.iterrows():
            weight = max(0.0, safe_float(row.get("weight"), 0.0) * multiplier)
            if weight <= 1e-12:
                continue
            rec = row.to_dict()
            rec["rebalance_date"] = signal_date.date().isoformat()
            rec["weight"] = weight
            rec["shadow_drawdown_state"] = state
            rec["shadow_drawdown_multiplier"] = multiplier
            rec["shadow_drawdown"] = shadow_dd
            rec["shadow_source_rebalance_date"] = pd.Timestamp(source_dt).date().isoformat()
            rec["shadow_drawdown_target_book"] = True
            rows.append(rec)
            stock_weight_sum += weight
        events.append(
            {
                "rebalance_date": signal_date.date().isoformat(),
                "source_rebalance_date": pd.Timestamp(source_dt).date().isoformat(),
                "state": state,
                "multiplier": multiplier,
                "shadow_drawdown": shadow_dd,
                "stock_weight_sum": stock_weight_sum,
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    out.to_csv(path, index=False)
    events_df = pd.DataFrame(events)
    events_df.to_csv(output_dir / "shadow_drawdown_events.csv", index=False)
    return path, events_df


def run_one_target(
    target_book: Path,
    *,
    args: argparse.Namespace,
    output_dir: Path,
    caution_dd: float,
    crisis_dd: float,
    caution_multiplier: float,
    crisis_multiplier: float,
    reentry_dd: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(target_book, low_memory=False) if target_book.exists() else pd.DataFrame()
    base = normalize_targets(raw, portfolio_kind=args.portfolio_kind)
    shadow_dir = output_dir / "shadow_full_risk"
    try:
        shadow_metrics = broker_replay(
            target_book=target_book,
            price_cache=repo_path(args.price_cache),
            output_dir=shadow_dir,
            portfolio_kind=args.portfolio_kind,
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            integer_shares=not bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
        )
    except Exception as exc:
        shadow_metrics = {
            "status": "blocked",
            "reason": f"shadow broker replay failed: {type(exc).__name__}: {exc}",
            "valid_for_production": False,
        }
    if shadow_metrics.get("status") != "completed":
        payload = {
            "status": "blocked",
            "reason": shadow_metrics.get("reason", "shadow broker replay did not complete"),
            "source_target_book": str(target_book),
            "shadow_metrics": shadow_metrics,
            "valid_for_production": False,
            "research_only": True,
        }
        write_json(output_dir / "metrics.json", payload)
        return payload
    equity_curve_path = shadow_dir / "equity_curve.csv"
    equity_curve = pd.read_csv(equity_curve_path) if equity_curve_path.exists() else pd.DataFrame()
    states = compute_shadow_states(
        equity_curve,
        caution_dd=caution_dd,
        crisis_dd=crisis_dd,
        caution_multiplier=caution_multiplier,
        crisis_multiplier=crisis_multiplier,
        reentry_dd=reentry_dd,
    )
    states.to_csv(output_dir / "shadow_drawdown_states.csv", index=False)
    scaled_target, events = build_scaled_target_book(base, states, output_dir)
    try:
        metrics = broker_replay(
            target_book=scaled_target,
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
            "reason": f"scaled broker replay failed: {type(exc).__name__}: {exc}",
            "valid_for_production": False,
        }
    metrics.update(
        {
            "metric_mode": "alpha_selector_shadow_drawdown_next_close",
            "data_mode": "shadow_full_risk_account_drawdown_circuit",
            "portfolio_kind": args.portfolio_kind,
            "source_target_book": str(target_book),
            "shadow_target_book": str(scaled_target),
            "shadow_full_risk_metrics": shadow_metrics,
            "caution_drawdown": float(caution_dd),
            "crisis_drawdown": float(crisis_dd),
            "reentry_drawdown": float(reentry_dd),
            "caution_multiplier": float(caution_multiplier),
            "crisis_multiplier": float(crisis_multiplier),
            "shadow_event_count": int(len(events)),
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
    grid = parse_grid(args.grid)
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for target_book in target_books:
        target_label = clean_label(target_book.parent.name)
        for caution_dd, crisis_dd, caution_mult, crisis_mult, reentry_dd in grid:
            vid = f"{target_label}_{variant_id(caution_dd, crisis_dd, caution_mult, crisis_mult, reentry_dd)}"
            variant_dir = output_dir / vid
            metrics = run_one_target(
                target_book,
                args=args,
                output_dir=variant_dir,
                caution_dd=caution_dd,
                crisis_dd=crisis_dd,
                caution_multiplier=caution_mult,
                crisis_multiplier=crisis_mult,
                reentry_dd=reentry_dd,
            )
            metrics["shadow_drawdown_grid_variant"] = vid
            write_json(variant_dir / "metrics.json", metrics)
            row = {
                "variant_id": vid,
                "status": metrics.get("status"),
                "portfolio_kind": args.portfolio_kind,
                "source_target_book": str(target_book),
                "cagr": metrics.get("cagr"),
                "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                "sharpe": metrics.get("sharpe"),
                "trade_count": metrics.get("trade_count"),
                "avg_cash_weight": metrics.get("avg_cash_weight"),
                "total_fees_usd": metrics.get("total_fees_usd"),
                "caution_drawdown": caution_dd,
                "crisis_drawdown": crisis_dd,
                "reentry_drawdown": reentry_dd,
                "caution_multiplier": caution_mult,
                "crisis_multiplier": crisis_mult,
                "shadow_event_count": metrics.get("shadow_event_count"),
                "shadow_full_risk_cagr": (metrics.get("shadow_full_risk_metrics") or {}).get("cagr")
                if isinstance(metrics.get("shadow_full_risk_metrics"), dict)
                else None,
                "shadow_full_risk_max_dd": (metrics.get("shadow_full_risk_metrics") or {}).get("max_dd")
                if isinstance(metrics.get("shadow_full_risk_metrics"), dict)
                else None,
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
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_shadow_drawdown_grid_best",
                "metric_mode": "alpha_selector_shadow_drawdown_grid_best_next_close",
                "variant_count": len(rows),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed valid shadow drawdown grid variants",
            "portfolio_kind": args.portfolio_kind,
            "variant_count": len(rows),
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)

    report = [
        "# Alpha Selector Shadow Drawdown Grid",
        "",
        "Research-only account-ledger grid. It keeps a full-risk shadow broker account and scales the real target book only after that observable shadow account enters drawdown.",
        "",
        f"- portfolio_kind: `{args.portfolio_kind}`",
        f"- variants: {len(rows)}",
        f"- best_status: `{best_payload.get('status')}`",
        f"- best_cagr: {safe_float(best_payload.get('cagr'), math.nan):.2%}"
        if best_payload.get("cagr") is not None
        else "- best_cagr: n/a",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown')), math.nan):.2%}"
        if best_payload.get("max_dd", best_payload.get("max_drawdown")) is not None
        else "- best_max_dd: n/a",
        "",
        "Promotion remains disabled until this sidecar is reviewed against trade count, fees, and stress windows.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha-selector-dir", default="")
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
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
