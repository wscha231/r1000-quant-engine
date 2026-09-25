#!/usr/bin/env python3
"""Cheap broker A/B for Main intramonth/event-driven defense.

This is the next step after monthly Main cap/fragility variants failed to move
the 2020 max drawdown. It reuses existing target books and daily crisis state,
builds event target books with different research-only defense settings, and
measures each arm through the broker-ledger replay.

No full policy replay, fullrun, production sync, or live trading is performed.
"""

from __future__ import annotations

import argparse
import copy
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

import tools.build_event_target_books as event_books  # noqa: E402
from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402
from tools.run_main_crash_fragility_screen import read_csv, repo_path, safe_float, write_json  # noqa: E402

SCHEMA_VERSION = "main-event-defense-broker-ab-v1"

DEFAULT_ARMS = (
    "baseline_monthly",
    "crisis_cash_preserve_default",
    "crisis_cash_preserve_strict",
    "crisis_cash_preserve_strict_fast_release",
    "event_default",
    "crisis_cash_strict",
    "crisis_cash_strict_fast_release",
    "event_default_no_cluster_caps",
)

DISABLED_STOP = -9.0

BASE_MAIN_FLOORS = {
    "GREEN": 0.03,
    "WATCH": 0.08,
    "DEFENSE_REVIEW": 0.25,
    "CRISIS_DEFENSE": 0.45,
    "REENTRY_READY": 0.20,
}

STRICT_MAIN_FLOORS = {
    "GREEN": 0.03,
    "WATCH": 0.12,
    "DEFENSE_REVIEW": 0.35,
    "CRISIS_DEFENSE": 0.60,
    "REENTRY_READY": 0.25,
}

ARM_SPECS: dict[str, dict[str, Any]] = {
    "baseline_monthly": {"kind": "baseline"},
    "crisis_cash_preserve_default": {
        "kind": "cash_only",
        "cash_floors": BASE_MAIN_FLOORS,
        "cluster_caps": {"single_name": 1.00, "industry_group": 1.00, "sector": 1.00},
        "preserve_monthly_cash_floor": True,
        "reentry_delay_days": 10,
        "crisis_release_step": 0.10,
        "crisis_change_band": 0.03,
    },
    "crisis_cash_preserve_strict": {
        "kind": "cash_only",
        "cash_floors": STRICT_MAIN_FLOORS,
        "cluster_caps": {"single_name": 1.00, "industry_group": 1.00, "sector": 1.00},
        "preserve_monthly_cash_floor": True,
        "reentry_delay_days": 10,
        "crisis_release_step": 0.10,
        "crisis_change_band": 0.03,
    },
    "crisis_cash_preserve_strict_fast_release": {
        "kind": "cash_only",
        "cash_floors": STRICT_MAIN_FLOORS,
        "cluster_caps": {"single_name": 1.00, "industry_group": 1.00, "sector": 1.00},
        "preserve_monthly_cash_floor": True,
        "reentry_delay_days": 5,
        "crisis_release_step": 0.20,
        "crisis_change_band": 0.03,
    },
    "event_default": {
        "kind": "event",
        "cash_floors": BASE_MAIN_FLOORS,
        "cluster_caps": {"single_name": 0.12, "industry_group": 0.35, "sector": 0.55},
        "hard_stop": -0.12,
        "trailing_stop": -0.20,
        "trailing_activation": 0.25,
        "relative_trim_threshold": -0.10,
        "relative_exit_threshold": -0.20,
        "trim_weight": 0.35,
        "reentry_delay_days": 10,
        "crisis_release_step": 0.10,
        "crisis_change_band": 0.03,
    },
    "crisis_cash_strict": {
        "kind": "event",
        "cash_floors": STRICT_MAIN_FLOORS,
        "cluster_caps": {"single_name": 1.00, "industry_group": 1.00, "sector": 1.00},
        "hard_stop": DISABLED_STOP,
        "trailing_stop": DISABLED_STOP,
        "trailing_activation": 9.0,
        "relative_trim_threshold": -9.0,
        "relative_exit_threshold": -9.0,
        "trim_weight": 0.0,
        "reentry_delay_days": 10,
        "crisis_release_step": 0.10,
        "crisis_change_band": 0.03,
    },
    "crisis_cash_strict_fast_release": {
        "kind": "event",
        "cash_floors": STRICT_MAIN_FLOORS,
        "cluster_caps": {"single_name": 1.00, "industry_group": 1.00, "sector": 1.00},
        "hard_stop": DISABLED_STOP,
        "trailing_stop": DISABLED_STOP,
        "trailing_activation": 9.0,
        "relative_trim_threshold": -9.0,
        "relative_exit_threshold": -9.0,
        "trim_weight": 0.0,
        "reentry_delay_days": 5,
        "crisis_release_step": 0.20,
        "crisis_change_band": 0.03,
    },
    "event_default_no_cluster_caps": {
        "kind": "event",
        "cash_floors": BASE_MAIN_FLOORS,
        "cluster_caps": {"single_name": 1.00, "industry_group": 1.00, "sector": 1.00},
        "hard_stop": -0.12,
        "trailing_stop": -0.20,
        "trailing_activation": 0.25,
        "relative_trim_threshold": -0.10,
        "relative_exit_threshold": -0.20,
        "trim_weight": 0.35,
        "reentry_delay_days": 10,
        "crisis_release_step": 0.10,
        "crisis_change_band": 0.03,
    },
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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_monthly_target(target_book: Path, output_path: Path) -> None:
    frame = read_csv(target_book)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(output_path, index=False)
    else:
        frame.to_csv(output_path, index=False)


def build_cash_only_target_for_arm(
    *,
    arm: str,
    spec: dict[str, Any],
    target_book: Path,
    price_cache: Path,
    crisis_state: Path,
    output_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    old_floors = copy.deepcopy(event_books.CASH_FLOORS_BY_STATE)
    try:
        event_books.CASH_FLOORS_BY_STATE["main"] = dict(spec["cash_floors"])
        raw = event_books.read_csv(target_book)
        targets, filter_meta = event_books.normalize_targets(raw, "main", target_book)
        crisis = event_books.load_daily_crisis_states(crisis_state)
        prices = event_books.price_dict_for_targets(price_cache, targets, "SPY") if not targets.empty else {}
        rows: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        if targets.empty or not prices:
            summary = {
                "arm": arm,
                "status": "blocked",
                "reason": "target book or price cache empty",
                "event_count": 0,
                "daily_crisis_event_count": 0,
                "exit_count": 0,
                "trim_count": 0,
                **filter_meta,
            }
        else:
            dates = [pd.Timestamp(x).normalize() for x in sorted(targets["rebalance_date"].dropna().unique())]
            risk_cash_target = event_books.cash_floor_for_state("main", "GREEN")
            last_defense_date: pd.Timestamp | None = None
            event_count = 0
            for idx, dt in enumerate(dates):
                period = targets[targets["rebalance_date"].eq(dt)].copy()
                if period.empty:
                    continue
                end_dt = event_books.latest_period_end(targets, prices, dt, idx, dates)
                if end_dt is None or end_dt <= dt:
                    continue
                templates = event_books.original_template_by_ticker(period)
                current_weights = event_books.period_base_weights(period)
                period_cash_floor = max(0.0, 1.0 - sum(current_weights.values())) if bool(spec.get("preserve_monthly_cash_floor")) else 0.0
                crisis_to_dt = crisis[crisis["date"].le(dt)] if not crisis.empty else pd.DataFrame()
                if not crisis_to_dt.empty:
                    risk_cash_target, last_defense_date, _ = event_books.risk_cash_update(
                        portfolio_kind="main",
                        state=crisis_to_dt.iloc[-1].get("crisis_state"),
                        event_date=dt,
                        current_risk_cash=risk_cash_target,
                        last_defense_date=last_defense_date,
                        reentry_delay_days=int(spec["reentry_delay_days"]),
                        release_step=float(spec["crisis_release_step"]),
                    )
                current_weights = event_books.set_cash_level(current_weights, max(period_cash_floor, risk_cash_target))
                snapshot, current_weights, _cap_events = event_books.snapshot_rows(
                    snapshot_date=dt,
                    weights=current_weights,
                    templates=templates,
                    portfolio_kind="main",
                    event_kind="scheduled_rebalance",
                    event_reason="base_target_book_cash_only",
                    event_source_tickers=[],
                    cluster_caps=dict(spec["cluster_caps"]),
                )
                rows.extend(snapshot)
                crisis_window = crisis[(crisis["date"].gt(dt)) & (crisis["date"].lt(end_dt))].copy() if not crisis.empty else pd.DataFrame()
                for crisis_row in crisis_window.to_dict("records"):
                    action_dt = pd.Timestamp(crisis_row["date"]).normalize()
                    prior_risk_cash = risk_cash_target
                    risk_cash_target, last_defense_date, risk_reason = event_books.risk_cash_update(
                        portfolio_kind="main",
                        state=crisis_row.get("crisis_state"),
                        event_date=action_dt,
                        current_risk_cash=risk_cash_target,
                        last_defense_date=last_defense_date,
                        reentry_delay_days=int(spec["reentry_delay_days"]),
                        release_step=float(spec["crisis_release_step"]),
                    )
                    if abs(risk_cash_target - prior_risk_cash) < float(spec["crisis_change_band"]):
                        continue
                    current_weights = event_books.set_cash_level(current_weights, max(period_cash_floor, risk_cash_target))
                    snapshot, current_weights, _cap_events = event_books.snapshot_rows(
                        snapshot_date=action_dt,
                        weights=current_weights,
                        templates=templates,
                        portfolio_kind="main",
                        event_kind="daily_crisis_cash_overlay",
                        event_reason=risk_reason,
                        event_source_tickers=["CASH"],
                        cluster_caps=dict(spec["cluster_caps"]),
                    )
                    rows = [
                        row
                        for row in rows
                        if not (
                            str(row.get("rebalance_date")) == action_dt.date().isoformat()
                            and str(row.get("event_kind")) != "scheduled_rebalance"
                        )
                    ]
                    rows.extend(snapshot)
                    event_count += 1
                    events.append(
                        {
                            "portfolio_kind": "main",
                            "base_rebalance_date": dt.date().isoformat(),
                            "period_end_date": end_dt.date().isoformat(),
                            "action_date": action_dt.date().isoformat(),
                            "ticker": "CASH",
                            "action": "daily_crisis_cash_raise" if risk_cash_target > prior_risk_cash else "daily_crisis_cash_release",
                            "reason": risk_reason,
                            "crisis_state": crisis_row.get("crisis_state"),
                            "crisis_score": crisis_row.get("crisis_score", ""),
                            "prior_cash_target": float(prior_risk_cash),
                            "target_cash": float(risk_cash_target),
                        }
                    )
            summary = {
                "arm": arm,
                "status": "completed" if rows else "blocked",
                "data_mode": "target_book_plus_daily_crisis_cash_only",
                "event_count": int(event_count),
                "daily_crisis_event_count": int(event_count),
                "exit_count": 0,
                "trim_count": 0,
                "cash_floors": dict(spec["cash_floors"]),
                "cluster_caps": dict(spec["cluster_caps"]),
                **filter_meta,
            }
    finally:
        event_books.CASH_FLOORS_BY_STATE.clear()
        event_books.CASH_FLOORS_BY_STATE.update(old_floors)

    book = pd.DataFrame(rows)
    events_df = pd.DataFrame(events)
    target_out = output_dir / arm / "target_book.csv"
    events_out = output_dir / arm / "events.csv"
    target_out.parent.mkdir(parents=True, exist_ok=True)
    if book.empty:
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(target_out, index=False)
    else:
        book.to_csv(target_out, index=False)
    events_df.to_csv(events_out, index=False)
    summary["event_target_book_path"] = str(target_out)
    summary["events_path"] = str(events_out)
    return target_out, events_out, summary


def build_event_target_for_arm(
    *,
    arm: str,
    spec: dict[str, Any],
    target_book: Path,
    price_cache: Path,
    crisis_state: Path,
    output_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    old_floors = copy.deepcopy(event_books.CASH_FLOORS_BY_STATE)
    try:
        event_books.CASH_FLOORS_BY_STATE["main"] = dict(spec["cash_floors"])
        book, events, summary = event_books.build_event_book(
            target_book=target_book,
            price_cache=price_cache,
            portfolio_kind="main",
            benchmark_ticker="SPY",
            crisis_state_path=crisis_state,
            enable_daily_crisis_cash_overlay=True,
            reentry_delay_days=int(spec["reentry_delay_days"]),
            crisis_release_step=float(spec["crisis_release_step"]),
            crisis_change_band=float(spec["crisis_change_band"]),
            cluster_caps=dict(spec["cluster_caps"]),
            hard_stop=float(spec["hard_stop"]),
            trailing_stop=float(spec["trailing_stop"]),
            trailing_activation=float(spec["trailing_activation"]),
            relative_trim_threshold=float(spec["relative_trim_threshold"]),
            relative_exit_threshold=float(spec["relative_exit_threshold"]),
            trim_weight=float(spec["trim_weight"]),
        )
    finally:
        event_books.CASH_FLOORS_BY_STATE.clear()
        event_books.CASH_FLOORS_BY_STATE.update(old_floors)

    target_out = output_dir / arm / "target_book.csv"
    events_out = output_dir / arm / "events.csv"
    target_out.parent.mkdir(parents=True, exist_ok=True)
    if book.empty:
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(target_out, index=False)
    else:
        book.to_csv(target_out, index=False)
    events.to_csv(events_out, index=False)
    summary.update(
        {
            "arm": arm,
            "cash_floors": dict(spec["cash_floors"]),
            "cluster_caps": dict(spec["cluster_caps"]),
            "events_path": str(events_out),
            "event_target_book_path": str(target_out),
        }
    )
    return target_out, events_out, summary


def metrics_delta(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "delta_cagr": metric_float(metrics, "cagr") - metric_float(baseline, "cagr"),
        "delta_max_dd": metric_float(metrics, "max_dd") - metric_float(baseline, "max_dd"),
        "delta_sharpe": metric_float(metrics, "sharpe") - metric_float(baseline, "sharpe"),
    }


def arm_verdict(metrics: dict[str, Any], baseline: dict[str, Any], event_summary: dict[str, Any]) -> str:
    if metrics.get("metric_mode") != "broker_ledger_next_close":
        return "blocked_invalid_metric_mode"
    event_count = int(safe_float(event_summary.get("event_count")))
    if event_count <= 0:
        return "blocked_no_event_rows"
    delta = metrics_delta(metrics, baseline)
    max_dd = metric_float(metrics, "max_dd")
    if max_dd >= -0.25 and delta["delta_cagr"] >= -0.005:
        return "research_pass_main_mdd_candidate"
    if delta["delta_max_dd"] >= 0.005 and delta["delta_cagr"] >= -0.005:
        return "research_observe_partial_mdd_improvement"
    if delta["delta_cagr"] < -0.005:
        return "reject_cagr_damage"
    if delta["delta_max_dd"] < 0:
        return "reject_mdd_worse"
    return "reject_no_material_mdd_edge"


def render_report(summary: dict[str, Any], arm_metrics: pd.DataFrame) -> str:
    lines = [
        "# Main Event Defense Broker A/B",
        "",
        f"- schema: `{summary.get('schema_version')}`",
        f"- verdict: `{summary.get('verdict')}`",
        f"- research_only: `{summary.get('research_only')}`",
        f"- production_activation_allowed: `{summary.get('production_activation_allowed')}`",
        "",
        "## Arms",
        "",
        "| arm | verdict | events | daily crisis events | exits | CAGR | MaxDD | Sharpe | delta CAGR | delta MaxDD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in arm_metrics.to_dict(orient="records"):
        lines.append(
            "| {arm} | `{verdict}` | {events} | {crisis_events} | {exits} | {cagr} | {mdd} | {sharpe:.3f} | {dcagr} | {dmdd} |".format(
                arm=row.get("arm"),
                verdict=row.get("verdict"),
                events=int(safe_float(row.get("event_count"))),
                crisis_events=int(safe_float(row.get("daily_crisis_event_count"))),
                exits=int(safe_float(row.get("exit_count"))),
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
            "This is a research-only target-book/event overlay replay. It does not",
            "create live orders or mutate production policy.",
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
    oos_start: str = "2024-06-03",
    oos2_start: str = "2023-06-03",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    event_summaries: list[dict[str, Any]] = []
    baseline_metrics: dict[str, Any] | None = None

    for arm in arms:
        if arm not in ARM_SPECS:
            raise ValueError(f"unknown arm: {arm}")
        spec = ARM_SPECS[arm]
        arm_dir = output_dir / arm
        target_out = arm_dir / "target_book.csv"
        events_out = arm_dir / "events.csv"
        if spec["kind"] == "baseline":
            copy_monthly_target(target_book, target_out)
            pd.DataFrame(columns=["action_date", "ticker", "action", "reason"]).to_csv(events_out, index=False)
            event_summary = {
                "arm": arm,
                "status": "baseline",
                "event_count": 0,
                "daily_crisis_event_count": 0,
                "exit_count": 0,
                "trim_count": 0,
                "event_target_book_path": str(target_out),
                "events_path": str(events_out),
            }
        elif spec["kind"] == "cash_only":
            target_out, events_out, event_summary = build_cash_only_target_for_arm(
                arm=arm,
                spec=spec,
                target_book=target_book,
                price_cache=price_cache,
                crisis_state=crisis_state,
                output_dir=output_dir,
            )
        else:
            target_out, events_out, event_summary = build_event_target_for_arm(
                arm=arm,
                spec=spec,
                target_book=target_book,
                price_cache=price_cache,
                crisis_state=crisis_state,
                output_dir=output_dir,
            )
        event_summaries.append(event_summary)
        metrics = broker_replay(
            target_book=target_out,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
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
        if arm == "baseline_monthly":
            baseline_metrics = metrics
        baseline = baseline_metrics or metrics
        delta = metrics_delta(metrics, baseline)
        verdict = "reference" if arm == "baseline_monthly" else arm_verdict(metrics, baseline, event_summary)
        rows.append(
            {
                "arm": arm,
                "verdict": verdict,
                "metric_mode": metrics.get("metric_mode"),
                "start_date": metrics.get("start_date"),
                "end_date": metrics.get("end_date"),
                "years": metric_float(metrics, "years"),
                "cagr": metric_float(metrics, "cagr"),
                "max_dd": metric_float(metrics, "max_dd"),
                "sharpe": metric_float(metrics, "sharpe"),
                "trade_count": int(safe_float(metrics.get("trade_count"))),
                "avg_cash_weight": metric_float(metrics, "avg_cash_weight"),
                "event_count": int(safe_float(event_summary.get("event_count"))),
                "daily_crisis_event_count": int(safe_float(event_summary.get("daily_crisis_event_count"))),
                "exit_count": int(safe_float(event_summary.get("exit_count"))),
                "trim_count": int(safe_float(event_summary.get("trim_count"))),
                **delta,
            }
        )

    arm_metrics = pd.DataFrame(rows)
    arm_metrics.to_csv(output_dir / "arm_metrics.csv", index=False)
    write_json(output_dir / "event_summaries.json", event_summaries)
    pass_rows = arm_metrics[arm_metrics["verdict"].astype(str).str.startswith("research_pass")]
    observe_rows = arm_metrics[arm_metrics["verdict"].astype(str).str.startswith("research_observe")]
    if not pass_rows.empty:
        final_verdict = "screen_pass_design_default_off_event_defense"
    elif not observe_rows.empty:
        final_verdict = "screen_observe_partial_mdd_improvement_only"
    else:
        final_verdict = "screen_reject_no_policy_safe_event_defense_edge"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "research_only": True,
        "production_activation_allowed": False,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "crisis_state": str(crisis_state),
        "arms": list(arms),
        "verdict": final_verdict,
        "best_arm": None if pass_rows.empty and observe_rows.empty else str((pass_rows if not pass_rows.empty else observe_rows).iloc[0]["arm"]),
        "arm_count": int(len(arm_metrics)),
    }
    write_json(output_dir / "summary.json", summary)
    write_text(output_dir / "report.md", render_report(summary, arm_metrics))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--crisis-state", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS), help="Comma-separated arm ids.")
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
        oos_start=args.oos_start,
        oos2_start=args.oos2_start,
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
