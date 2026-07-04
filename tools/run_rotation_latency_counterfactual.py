#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    replay,
    resolve_cash_carry_config,
)


DEFAULT_OUTPUT_DIR = "outputs/rotation_latency_counterfactual"


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def read_weights(path: Path, portfolio_kind: str, weight_col: str, date_col: str | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "portfolio_kind" in frame.columns:
        mask = frame["portfolio_kind"].astype(str).str.lower().eq(portfolio_kind)
    elif "portfolio" in frame.columns:
        mask = frame["portfolio"].astype(str).str.lower().eq(portfolio_kind)
    else:
        mask = pd.Series([True] * len(frame), index=frame.index)
    out = frame[mask].copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["weight"] = pd.to_numeric(out[weight_col], errors="coerce").fillna(0.0)
    if date_col and date_col in out.columns:
        out["source_date"] = out[date_col].astype(str)
    return out[["ticker", "weight"]].groupby("ticker", as_index=False)["weight"].sum()


def latest_target_weights(path: Path, portfolio_kind: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce")
    frame = frame[frame["rebalance_date"].notna()].copy()
    if "portfolio_kind" in frame.columns:
        frame = frame[frame["portfolio_kind"].astype(str).str.lower().eq(portfolio_kind)].copy()
    latest = frame["rebalance_date"].max()
    out = frame[frame["rebalance_date"].eq(latest)].copy()
    wcol = "target_weight" if "target_weight" in out.columns else "weight"
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["weight"] = pd.to_numeric(out[wcol], errors="coerce").fillna(0.0)
    return out[["ticker", "weight"]].groupby("ticker", as_index=False)["weight"].sum()


def replace_last_rebalance(base_book: pd.DataFrame, weights: pd.DataFrame, rebalance_date: str) -> pd.DataFrame:
    out = base_book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    final_date = pd.Timestamp(rebalance_date)
    out = out[out["rebalance_date"].lt(final_date)].copy()
    template = base_book.tail(1).copy()
    rows: list[pd.Series] = []
    for _, weight_row in weights.iterrows():
        row = template.iloc[0].copy()
        row.loc[:] = pd.NA
        row["rebalance_date"] = final_date.strftime("%Y-%m-%d")
        row["ticker"] = normalize_ticker(weight_row["ticker"])
        row["weight"] = float(weight_row["weight"])
        row["target_weight"] = float(weight_row["weight"])
        rows.append(row)
    combined = pd.concat([out, pd.DataFrame(rows)], ignore_index=True)
    combined["rebalance_date"] = pd.to_datetime(combined["rebalance_date"], errors="coerce").dt.date.astype(str)
    return combined


def delta_metrics(base: dict[str, Any], challenger: dict[str, Any]) -> dict[str, Any]:
    if base.get("status") != "completed" or challenger.get("status") != "completed":
        return {
            "status": "blocked",
            "delta_cagr": None,
            "delta_max_dd": None,
            "delta_sharpe": None,
            "reason": "baseline_or_challenger_not_completed",
        }
    return {
        "status": "completed",
        "delta_cagr": float(challenger.get("cagr", 0.0) or 0.0) - float(base.get("cagr", 0.0) or 0.0),
        "delta_max_dd": float(challenger.get("max_dd", 0.0) or 0.0) - float(base.get("max_dd", 0.0) or 0.0),
        "delta_sharpe": float(challenger.get("sharpe", 0.0) or 0.0) - float(base.get("sharpe", 0.0) or 0.0),
    }


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2%}"
    except Exception:
        return ""


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Rotation Latency Counterfactual",
        "",
        f"- status: `{payload.get('status')}`",
        f"- portfolio kind: `{payload.get('portfolio_kind')}`",
        f"- decision date normalized to: `{payload.get('decision_date')}`",
        f"- replay end date: `{payload.get('replay_end_date')}`",
        "- research only: `true`",
        "- production activation allowed: `false`",
        "- fullrun executed: `false`",
        "",
        "## Arms",
        "",
        "| arm | CAGR | MaxDD | Sharpe | ΔCAGR vs hold | ΔMDD vs hold | target names | verdict |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for arm in payload.get("arms", []):
        m = arm.get("metrics") or {}
        d = arm.get("delta_vs_hold") or {}
        lines.append(
            f"| {arm.get('arm')} | {pct(m.get('cagr'))} | {pct(m.get('max_dd'))} | "
            f"{float(m.get('sharpe') or 0.0):.3f} | {pct(d.get('delta_cagr'))} | "
            f"{pct(d.get('delta_max_dd'))} | {', '.join(arm.get('target_tickers') or [])} | "
            f"{arm.get('verdict')} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        payload.get("interpretation", ""),
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    portfolio_kind = str(args.portfolio_kind).lower()
    base_book_path = repo_path(args.base_target_book)
    base_book = pd.read_csv(base_book_path)
    decision_date = args.decision_date
    cash_carry_config = resolve_cash_carry_config(
        mode=args.cash_carry_mode,
        rate_source=args.cash_rate_source,
        rate_path=args.cash_rate_path,
        rate_lag_days=args.cash_rate_lag_days,
        haircut_bps=args.cash_carry_haircut_bps,
        day_count=args.cash_carry_day_count,
    )
    arm_sources = {
        "june_operating_hold": read_weights(repo_path(args.previous_current_holdings), portfolio_kind, "current_weight"),
        "june_raw_rotation": read_weights(repo_path(args.previous_raw_target), portfolio_kind, "target_weight"),
        "july_actual_rotation_applied_early": latest_target_weights(repo_path(args.current_target_book), portfolio_kind),
    }

    arms: list[dict[str, Any]] = []
    hold_metrics: dict[str, Any] | None = None
    for name, weights in arm_sources.items():
        arm_dir = output_dir / name
        arm_dir.mkdir(parents=True, exist_ok=True)
        target = replace_last_rebalance(base_book, weights, decision_date)
        target_path = arm_dir / "target_book.csv"
        target.to_csv(target_path, index=False)
        metrics = replay(
            target_book=target_path,
            price_cache=repo_path(args.price_cache),
            output_dir=arm_dir / "broker",
            portfolio_kind=portfolio_kind,
            starting_capital=float(args.starting_capital),
            fill_mode="next_close",
            cost_bps=float(args.cost_bps),
            integer_shares=not bool(args.fractional_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
            disable_concentrated_champion_filter=portfolio_kind == "concentrated",
            max_reasonable_weight_sum=float(args.max_reasonable_weight_sum),
            oos_start=args.oos_start or None,
            oos_end=args.oos_end or None,
            oos2_start=args.oos2_start or None,
            oos2_end=args.oos2_end or None,
            replay_end_date=args.replay_end_date,
            official_baseline_end_date=args.replay_end_date,
            cash_carry_config=cash_carry_config,
        )
        if name == "june_operating_hold":
            hold_metrics = metrics
        arms.append(
            {
                "arm": name,
                "target_book": str(target_path),
                "metrics_path": str(arm_dir / "broker" / "metrics.json"),
                "metrics": {k: metrics.get(k) for k in ("status", "reason", "cagr", "max_dd", "sharpe", "end_date", "metric_mode")},
                "target_tickers": weights.loc[weights["weight"].gt(0), "ticker"].tolist(),
            }
        )

    hold_metrics = hold_metrics or {}
    for arm in arms:
        arm["delta_vs_hold"] = delta_metrics(hold_metrics, arm.get("metrics") or {})
        dc = arm["delta_vs_hold"].get("delta_cagr")
        dd = arm["delta_vs_hold"].get("delta_max_dd")
        if arm["arm"] == "june_operating_hold":
            verdict = "control"
        elif arm["delta_vs_hold"].get("status") != "completed":
            verdict = "blocked_invalid_replay"
        elif dc >= 0.01 and dd >= -0.0025:
            verdict = "latency_cost_candidate"
        else:
            verdict = "reject_no_latency_edge"
        arm["verdict"] = verdict

    metrics_rows = []
    for arm in arms:
        row = {"arm": arm["arm"], **(arm.get("metrics") or {}), **(arm.get("delta_vs_hold") or {}), "verdict": arm["verdict"]}
        metrics_rows.append(row)
    pd.DataFrame(metrics_rows).to_csv(output_dir / "metrics.csv", index=False)
    challengers = [a for a in arms if a["arm"] != "june_operating_hold"]
    completed_challengers = [a for a in challengers if a["delta_vs_hold"].get("status") == "completed"]
    if hold_metrics.get("status") != "completed" or not completed_challengers:
        interpretation = "Control or challenger replay did not complete; fix price/cache/window coverage before interpreting rotation latency."
        status = "blocked_invalid_rotation_latency_replay"
    else:
        best = max(completed_challengers, key=lambda a: a["delta_vs_hold"]["delta_cagr"])
        if best["verdict"] == "latency_cost_candidate":
            interpretation = (
                f"`{best['arm']}` beats the June operating hold by {best['delta_vs_hold']['delta_cagr']:.4f} CAGR "
                "without material MDD damage; C2 anti-stickiness research is authorized."
            )
            status = "screen_pass_latency_cost_candidate"
        else:
            interpretation = (
                "No rotation arm beat the June operating hold by the required +1pp CAGR without MDD damage. "
                "Stickiness is not proven costly by this crash counterfactual."
            )
            status = "screen_reject_no_rotation_latency_edge"
    payload = {
        "schema_version": "rotation-latency-counterfactual-v1",
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "portfolio_kind": portfolio_kind,
        "decision_date": decision_date,
        "replay_end_date": args.replay_end_date,
        "base_target_book": str(base_book_path),
        "previous_current_holdings": str(repo_path(args.previous_current_holdings)),
        "previous_raw_target": str(repo_path(args.previous_raw_target)),
        "current_target_book": str(repo_path(args.current_target_book)),
        "price_cache": str(repo_path(args.price_cache)),
        "cash_carry_mode": cash_carry_config.mode,
        "research_only": True,
        "production_activation_allowed": False,
        "policy_mutation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
        "arms": arms,
        "metrics_csv": str(output_dir / "metrics.csv"),
        "report_md": str(output_dir / "report.md"),
        "interpretation": interpretation,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-target-book", required=True)
    parser.add_argument("--previous-current-holdings", required=True)
    parser.add_argument("--previous-raw-target", required=True)
    parser.add_argument("--current-target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["concentrated", "main"], default="concentrated")
    parser.add_argument("--decision-date", default="2026-06-29")
    parser.add_argument("--replay-end-date", default="2026-07-02")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--fractional-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--max-reasonable-weight-sum", type=float, default=1.05)
    parser.add_argument("--oos-start", default="2024-07-01")
    parser.add_argument("--oos-end", default="")
    parser.add_argument("--oos2-start", default="2023-01-01")
    parser.add_argument("--oos2-end", default="")
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default=CASH_CARRY_MODE_NONE)
    parser.add_argument("--cash-rate-source", default=None)
    parser.add_argument("--cash-rate-path", default=None)
    parser.add_argument("--cash-rate-lag-days", type=int, default=None)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=None)
    parser.add_argument("--cash-carry-day-count", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if str(payload.get("status", "")).startswith("screen_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
