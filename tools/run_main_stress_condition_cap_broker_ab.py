#!/usr/bin/env python3
"""Cheap broker A/B for selective Main stress-condition caps.

This tool does not run the full AlphaOps policy replay. It reads an existing
Main target book, applies narrowly-scoped PIT-observable caps to already
selected names, and replays each generated target book through the broker
ledger. Forward/stress labels are not used in the transformation.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402
from tools.run_main_crash_fragility_screen import (  # noqa: E402
    build_feature_rows,
    clean_ticker,
    normalize_crisis_state,
    normalize_target_book,
    read_csv,
    repo_path,
    safe_float,
    write_json,
)

SCHEMA_VERSION = "main-stress-condition-cap-broker-ab-v1"
CASH_TICKERS = {"CASH", "__CASH__"}

DEFAULT_ARMS = (
    "baseline",
    "large_ext_cap10",
    "large_ext_cap11",
    "large_ext_weak_cap10",
    "large_ext_weak_cap11",
    "large_ext_vol_cap10",
    "large_ext_fragile_cap10",
)

ARM_SPECS: dict[str, dict[str, Any]] = {
    "baseline": {"predicate": "none", "cap": None},
    "large_ext_cap10": {"predicate": "large_ext", "cap": 0.10},
    "large_ext_cap11": {"predicate": "large_ext", "cap": 0.11},
    "large_ext_weak_cap10": {"predicate": "large_ext_weak", "cap": 0.10},
    "large_ext_weak_cap11": {"predicate": "large_ext_weak", "cap": 0.11},
    "large_ext_vol_cap10": {"predicate": "large_ext_vol", "cap": 0.10},
    "large_ext_fragile_cap10": {"predicate": "large_ext_fragile", "cap": 0.10},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pct(value: Any) -> str:
    try:
        out = float(value)
        return f"{out:.2%}" if math.isfinite(out) else ""
    except (TypeError, ValueError):
        return ""


def metric_float(metrics: dict[str, Any], key: str) -> float:
    return safe_float(metrics.get(key), float("nan"))


def normalize_raw_target_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    if "target_weight" not in d.columns:
        d["target_weight"] = d.get("weight", 0.0)
    d["target_weight"] = pd.to_numeric(d["target_weight"], errors="coerce").fillna(0.0)
    d["weight"] = d["target_weight"]
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["target_weight"] >= 0.0)]
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def add_live_condition_columns(features: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return features
    d = features.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    for col in ["target_weight", "ma200_distance", "trailing_volatility_63d", "main_crash_fragility_score", "spy_drawdown"]:
        d[col] = pd.to_numeric(d.get(col, np.nan), errors="coerce")
    d["weight_rank"] = d.groupby("rebalance_date")["target_weight"].transform(lambda s: s.rank(pct=True)).fillna(0.0)
    d["ma200_extension_rank"] = d.groupby("rebalance_date")["ma200_distance"].transform(lambda s: s.rank(pct=True)).fillna(0.0)
    d["vol_rank_live"] = d.groupby("rebalance_date")["trailing_volatility_63d"].transform(lambda s: s.rank(pct=True)).fillna(0.0)
    crisis = d.get("crisis_state", "").astype(str).str.upper().str.strip()
    d["weak_market_state"] = crisis.isin(["WATCH", "DEFENSE_REVIEW", "CRISIS_DEFENSE"]) | (d["spy_drawdown"] <= -0.03)
    d["large_weight"] = d["weight_rank"] >= 0.80
    d["extension_top20"] = d["ma200_extension_rank"] >= 0.80
    d["vol_top20"] = d["vol_rank_live"] >= 0.80
    d["fragility_high"] = d["main_crash_fragility_score"] >= 0.66
    d["predicate_large_ext"] = d["large_weight"] & d["extension_top20"]
    d["predicate_large_ext_weak"] = d["predicate_large_ext"] & d["weak_market_state"]
    d["predicate_large_ext_vol"] = d["predicate_large_ext"] & d["vol_top20"]
    d["predicate_large_ext_fragile"] = d["predicate_large_ext"] & d["fragility_high"]
    keep = [
        "rebalance_date",
        "ticker",
        "weight_rank",
        "ma200_extension_rank",
        "vol_rank_live",
        "main_crash_fragility_score",
        "weak_market_state",
        "large_weight",
        "extension_top20",
        "vol_top20",
        "fragility_high",
        "predicate_large_ext",
        "predicate_large_ext_weak",
        "predicate_large_ext_vol",
        "predicate_large_ext_fragile",
    ]
    return d[[col for col in keep if col in d.columns]].copy()


def merge_conditions(raw: pd.DataFrame, conditions: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    if conditions.empty:
        for col in ["predicate_large_ext", "predicate_large_ext_weak", "predicate_large_ext_vol", "predicate_large_ext_fragile"]:
            d[col] = False
        return d
    c = conditions.copy()
    c["rebalance_date"] = pd.to_datetime(c["rebalance_date"], errors="coerce").dt.normalize()
    c["ticker"] = c["ticker"].map(clean_ticker)
    merged = d.merge(c, how="left", on=["rebalance_date", "ticker"])
    for col in ["predicate_large_ext", "predicate_large_ext_weak", "predicate_large_ext_vol", "predicate_large_ext_fragile"]:
        if col not in merged.columns:
            merged[col] = False
        merged[col] = merged[col].fillna(False).astype(bool)
    return merged


def predicate_column(name: str) -> str | None:
    if name == "none":
        return None
    return f"predicate_{name}"


def distribute_excess(group: pd.DataFrame, *, excess: float, max_receive_weight: float) -> tuple[pd.DataFrame, float]:
    if excess <= 1e-12:
        return group, 0.0
    out = group.copy()
    stock_mask = ~out["ticker"].isin(CASH_TICKERS)
    blocked = out.get("_cap_blocked_receiver", False)
    if not isinstance(blocked, pd.Series):
        blocked = pd.Series(False, index=out.index)
    receiver_mask = stock_mask & (~blocked.astype(bool)) & (out["target_weight"] < max_receive_weight - 1e-12)
    while excess > 1e-10 and receiver_mask.any():
        capacity = (max_receive_weight - out.loc[receiver_mask, "target_weight"]).clip(lower=0.0)
        total_capacity = float(capacity.sum())
        if total_capacity <= 1e-12:
            break
        add = capacity / total_capacity * min(excess, total_capacity)
        out.loc[receiver_mask, "target_weight"] = out.loc[receiver_mask, "target_weight"] + add
        excess -= float(add.sum())
        receiver_mask = stock_mask & (~blocked.astype(bool)) & (out["target_weight"] < max_receive_weight - 1e-12)
    return out, max(0.0, excess)


def apply_condition_cap(
    frame: pd.DataFrame,
    *,
    predicate: str,
    cap: float | None,
    max_receive_weight: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    d = frame.copy()
    if predicate == "none" or cap is None:
        d["weight"] = d["target_weight"]
        max_weight = float(pd.to_numeric(d[~d["ticker"].isin(CASH_TICKERS)]["target_weight"], errors="coerce").max()) if not d.empty else 0.0
        return d, pd.DataFrame(), {
            "applied_rows": 0,
            "applied_dates": 0,
            "total_reduced_weight": 0.0,
            "residual_cash_weight": 0.0,
            "max_adjusted_weight": max_weight,
        }
    pred_col = predicate_column(predicate)
    if pred_col is None or pred_col not in d.columns:
        d["weight"] = d["target_weight"]
        max_weight = float(pd.to_numeric(d[~d["ticker"].isin(CASH_TICKERS)]["target_weight"], errors="coerce").max()) if not d.empty else 0.0
        return d, pd.DataFrame(), {
            "applied_rows": 0,
            "applied_dates": 0,
            "total_reduced_weight": 0.0,
            "residual_cash_weight": 0.0,
            "max_adjusted_weight": max_weight,
        }
    change_rows: list[dict[str, Any]] = []
    adjusted_groups: list[pd.DataFrame] = []
    residual_total = 0.0
    reduced_total = 0.0
    applied_dates: set[str] = set()
    for dt, group in d.groupby("rebalance_date", sort=True):
        g = group.copy()
        g["_baseline_weight"] = g["target_weight"]
        eligible = (~g["ticker"].isin(CASH_TICKERS)) & g[pred_col].astype(bool) & (g["target_weight"] > cap + 1e-12)
        if eligible.any():
            g["_cap_blocked_receiver"] = eligible
            reduced = g.loc[eligible, "target_weight"] - cap
            reduction = float(reduced.sum())
            g.loc[eligible, "target_weight"] = cap
            g, residual = distribute_excess(g, excess=reduction, max_receive_weight=max_receive_weight)
            if residual > 1e-10:
                cash_mask = g["ticker"].isin(CASH_TICKERS)
                if cash_mask.any():
                    idx = g[cash_mask].index[0]
                    g.loc[idx, "target_weight"] = safe_float(g.loc[idx, "target_weight"]) + residual
                else:
                    cash_row = {col: "" for col in g.columns}
                    cash_row.update({"rebalance_date": dt, "ticker": "CASH", "Name": "Cash", "sector": "Cash", "target_weight": residual})
                    g = pd.concat([g, pd.DataFrame([cash_row])], ignore_index=True)
            residual_total += residual
            reduced_total += reduction
            applied_dates.add(pd.Timestamp(dt).date().isoformat())
        for idx in g.index:
            base = safe_float(g.loc[idx].get("_baseline_weight"), 0.0)
            new = safe_float(g.loc[idx, "target_weight"])
            if abs(new - base) > 1e-10:
                change_rows.append(
                    {
                        "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                        "ticker": g.loc[idx, "ticker"],
                        "predicate": predicate,
                        "cap": cap,
                        "baseline_weight": base,
                        "adjusted_weight": new,
                        "delta_weight": new - base,
                        "predicate_matched": bool(g.loc[idx].get(pred_col, False)),
                    }
                )
        adjusted_groups.append(g)
    out = pd.concat(adjusted_groups, ignore_index=True) if adjusted_groups else d
    for private_col in ["_baseline_weight", "_cap_blocked_receiver"]:
        if private_col in out.columns:
            out = out.drop(columns=[private_col])
    out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    out["weight"] = out["target_weight"]
    changes = pd.DataFrame(change_rows)
    summary = {
        "applied_rows": int(len(changes[changes.get("predicate_matched", False).astype(bool)]) if not changes.empty else 0),
        "applied_dates": int(len(applied_dates)),
        "total_reduced_weight": float(reduced_total),
        "residual_cash_weight": float(residual_total),
        "max_adjusted_weight": float(pd.to_numeric(out[~out["ticker"].isin(CASH_TICKERS)]["target_weight"], errors="coerce").max()) if not out.empty else 0.0,
    }
    return out, changes, summary


def metrics_delta(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "delta_cagr": metric_float(metrics, "cagr") - metric_float(baseline, "cagr"),
        "delta_max_dd": metric_float(metrics, "max_dd") - metric_float(baseline, "max_dd"),
        "delta_sharpe": metric_float(metrics, "sharpe") - metric_float(baseline, "sharpe"),
    }


def arm_verdict(metrics: dict[str, Any], baseline: dict[str, Any], applied_rows: int) -> str:
    if metrics.get("metric_mode") != "broker_ledger_next_close":
        return "blocked_invalid_metric_mode"
    if applied_rows <= 0 and baseline:
        return "blocked_no_applied_rows"
    d = metrics_delta(metrics, baseline)
    max_dd = metric_float(metrics, "max_dd")
    if max_dd >= -0.25 and d["delta_cagr"] >= -0.005:
        return "research_pass_main_mdd_candidate"
    if d["delta_max_dd"] >= 0.005 and d["delta_cagr"] >= -0.005:
        return "research_observe_partial_mdd_improvement"
    if d["delta_max_dd"] < 0:
        return "reject_mdd_worse"
    if d["delta_cagr"] < -0.005:
        return "reject_cagr_damage"
    return "reject_no_material_mdd_edge"


def render_report(summary: dict[str, Any], arm_metrics: pd.DataFrame) -> str:
    lines = [
        "# Main Stress-Condition Cap Broker A/B",
        "",
        f"- schema: `{summary.get('schema_version')}`",
        f"- verdict: `{summary.get('verdict')}`",
        f"- research_only: `{summary.get('research_only')}`",
        f"- production_activation_allowed: `{summary.get('production_activation_allowed')}`",
        "",
        "## Arms",
        "",
        "| arm | verdict | applied rows | CAGR | MaxDD | Sharpe | delta CAGR | delta MaxDD |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in arm_metrics.to_dict(orient="records"):
        lines.append(
            "| {arm} | `{verdict}` | {applied_rows} | {cagr} | {mdd} | {sharpe:.3f} | {dcagr} | {dmdd} |".format(
                arm=row.get("arm"),
                verdict=row.get("verdict"),
                applied_rows=int(row.get("applied_rows") or 0),
                cagr=pct(row.get("cagr")),
                mdd=pct(row.get("max_dd")),
                sharpe=safe_float(row.get("sharpe"), float("nan")),
                dcagr=pct(row.get("delta_cagr")),
                dmdd=pct(row.get("delta_max_dd")),
            )
        )
    lines.extend(
        [
            "",
            "This is a target-book broker replay only. It does not change selection,",
            "scoring, cash policy, production gates, or live trading.",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    *,
    target_book: Path,
    price_cache: Path,
    crisis_state: Path,
    output_dir: Path,
    arms: tuple[str, ...] = DEFAULT_ARMS,
    max_receive_weight: float = 0.12,
    oos_start: str = "2024-06-03",
    oos2_start: str = "2023-06-03",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = normalize_raw_target_book(read_csv(target_book))
    stocks = normalize_target_book(raw)
    crisis = normalize_crisis_state(read_csv(crisis_state))
    features = add_live_condition_columns(build_feature_rows(stocks, price_cache, crisis))
    enriched = merge_conditions(raw, features)
    features.to_csv(output_dir / "condition_features.csv", index=False)

    rows: list[dict[str, Any]] = []
    all_changes: list[pd.DataFrame] = []
    baseline_metrics: dict[str, Any] | None = None
    for arm in arms:
        if arm not in ARM_SPECS:
            raise ValueError(f"unknown arm: {arm}")
        spec = ARM_SPECS[arm]
        adjusted, changes, change_summary = apply_condition_cap(
            enriched,
            predicate=str(spec["predicate"]),
            cap=spec["cap"],
            max_receive_weight=max_receive_weight,
        )
        target_out = output_dir / arm / "target_book.csv"
        broker_out = output_dir / arm / "broker"
        target_out.parent.mkdir(parents=True, exist_ok=True)
        adjusted.to_csv(target_out, index=False)
        if not changes.empty:
            c = changes.copy()
            c["arm"] = arm
            all_changes.append(c)
        metrics = broker_replay(
            target_book=target_out,
            price_cache=price_cache,
            output_dir=broker_out,
            portfolio_kind="main",
            starting_capital=100000.0,
            fill_mode="next_close",
            cost_bps=25.0,
            integer_shares=True,
            max_reasonable_weight_sum=1.05,
            max_fill_lag_days=7,
            disable_concentrated_champion_filter=True,
            oos_start=oos_start,
            oos_end=None,
            oos2_start=oos2_start,
            oos2_end=None,
        )
        if arm == "baseline":
            baseline_metrics = metrics
        baseline = baseline_metrics or metrics
        delta = metrics_delta(metrics, baseline)
        verdict = "reference" if arm == "baseline" else arm_verdict(metrics, baseline, int(change_summary["applied_rows"]))
        rows.append(
            {
                "arm": arm,
                "predicate": spec["predicate"],
                "cap": spec["cap"],
                "verdict": verdict,
                "applied_rows": int(change_summary["applied_rows"]),
                "applied_dates": int(change_summary["applied_dates"]),
                "total_reduced_weight": float(change_summary["total_reduced_weight"]),
                "residual_cash_weight": float(change_summary["residual_cash_weight"]),
                "max_adjusted_weight": float(change_summary["max_adjusted_weight"]),
                "metric_mode": metrics.get("metric_mode"),
                "start_date": metrics.get("start_date"),
                "end_date": metrics.get("end_date"),
                "years": metric_float(metrics, "years"),
                "cagr": metric_float(metrics, "cagr"),
                "max_dd": metric_float(metrics, "max_dd"),
                "sharpe": metric_float(metrics, "sharpe"),
                "trade_count": int(safe_float(metrics.get("trade_count"))),
                **delta,
            }
        )

    arm_metrics = pd.DataFrame(rows)
    arm_metrics.to_csv(output_dir / "arm_metrics.csv", index=False)
    changes_out = pd.concat(all_changes, ignore_index=True) if all_changes else pd.DataFrame()
    changes_out.to_csv(output_dir / "arm_weight_changes.csv", index=False)
    pass_rows = arm_metrics[arm_metrics["verdict"].astype(str).str.startswith("research_pass")]
    observe_rows = arm_metrics[arm_metrics["verdict"].astype(str).str.startswith("research_observe")]
    if not pass_rows.empty:
        final_verdict = "screen_pass_design_default_off_stress_condition_cap"
    elif not observe_rows.empty:
        final_verdict = "screen_observe_partial_mdd_improvement_only"
    else:
        final_verdict = "screen_reject_no_policy_safe_mdd_edge"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "research_only": True,
        "production_activation_allowed": False,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "crisis_state": str(crisis_state),
        "arms": list(arms),
        "max_receive_weight": float(max_receive_weight),
        "verdict": final_verdict,
        "best_arm": None if pass_rows.empty and observe_rows.empty else str((pass_rows if not pass_rows.empty else observe_rows).iloc[0]["arm"]),
        "arm_count": int(len(arm_metrics)),
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, arm_metrics), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--crisis-state", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS), help="Comma-separated arm ids.")
    parser.add_argument("--max-receive-weight", type=float, default=0.12)
    parser.add_argument("--oos-start", default="2024-06-03")
    parser.add_argument("--oos2-start", default="2023-06-03")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    arms = tuple(part.strip() for part in str(args.arms).split(",") if part.strip())
    payload = run(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        crisis_state=repo_path(args.crisis_state),
        output_dir=repo_path(args.output_dir),
        arms=arms,
        max_receive_weight=float(args.max_receive_weight),
        oos_start=args.oos_start,
        oos2_start=args.oos2_start,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
