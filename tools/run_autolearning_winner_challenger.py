#!/usr/bin/env python3
"""AutoLearning winner-signal challenger harness.

This runner connects AutoLearning v2 hypotheses with the report-only winner
lifecycle and winner-onset studies. It is deliberately separate from the
production pipeline:

1. It never changes portfolio defaults.
2. It writes proposal-only experiment configs.
3. It distinguishes event-level evidence from true portfolio-level replay.

Use it after running:

    python tools/run_auto_learning_v2.py
    python tools/run_winner_lifecycle_reports.py ...
    python tools/run_winner_onset_study.py ...

Outputs
-------
    outputs/autolearning_winner_challenger/summary.json
    outputs/autolearning_winner_challenger/event_backtest.csv
    outputs/autolearning_winner_challenger/candidate_experiment.yaml
    outputs/autolearning_winner_challenger/challenger_report.md
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = REPO_ROOT / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"
DEFAULT_AUTOLEARNING_DIR = REPO_ROOT / "outputs" / "auto_learning_v2"
DEFAULT_LIFECYCLE_DIR = REPO_ROOT / "outputs" / "winner_lifecycle"
DEFAULT_ONSET_DIR = REPO_ROOT / "outputs" / "winner_onset_study"
DEFAULT_SHAKEOUT_DIR = REPO_ROOT / "outputs" / "shakeout_breakdown_study"
DEFAULT_CASH_DRAG_DIR = REPO_ROOT / "outputs" / "main_cash_drag_replay"
DEFAULT_MAIN_V2_REPLAY_DIR = REPO_ROOT / "outputs" / "main_v2_backtest"
DEFAULT_CONCENTRATED_REPLAY_DIR = REPO_ROOT / "outputs" / "concentrated_policy_replay"
DEFAULT_ALPHA_SPRINT_REPLAY_DIR = REPO_ROOT / "outputs" / "alpha_sprint_backtest"
DEFAULT_POSITION_RISK_REPLAY_DIR = REPO_ROOT / "outputs" / "position_aware_risk_replay"
DEFAULT_MONSTER_LIFECYCLE_REPLAY_DIR = REPO_ROOT / "outputs" / "monster_lifecycle_replay"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "autolearning_winner_challenger"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def pct(value: Any) -> str:
    value = safe_float(value)
    if not math.isfinite(value):
        return "NA"
    return f"{value:.2%}"


def latest_main_cash_weight(latest_run: Path) -> float:
    rows = read_csv_rows(latest_run / "reports" / "main_monthly_weights.csv")
    if not rows:
        return float("nan")
    dates = sorted({str(row.get("rebalance_date", "")) for row in rows if row.get("rebalance_date")})
    if not dates:
        return float("nan")
    latest_date = dates[-1]
    latest_rows = [row for row in rows if str(row.get("rebalance_date", "")) == latest_date]
    cash = 0.0
    for row in latest_rows:
        if str(row.get("ticker", "")).upper() == "CASH":
            cash += safe_float(row.get("weight"), 0.0)
    if cash > 0:
        return cash
    stock_sum = sum(safe_float(row.get("weight"), 0.0) for row in latest_rows)
    return max(0.0, 1.0 - stock_sum)


def load_baseline(latest_run: Path) -> dict[str, Any]:
    main = read_json(latest_run / "backtest_metrics.json", {}) or {}
    conc = read_json(latest_run / "concentrated_backtest_metrics.json", {}) or {}
    latest_cash = latest_main_cash_weight(latest_run)
    return {
        "main": {
            "cagr": safe_float(main.get("cagr", main.get("strategy_cagr"))),
            "sharpe": safe_float(main.get("sharpe")),
            "max_dd": safe_float(main.get("max_dd")),
            "avg_cash_weight": safe_float(main.get("avg_cash_weight"), 0.0),
            "latest_cash_weight": latest_cash,
            "avg_turnover_monthly": safe_float(main.get("avg_turnover_monthly")),
            "months": safe_float(main.get("months")),
        },
        "concentrated": {
            "cagr": safe_float(conc.get("strategy_cagr", conc.get("cagr"))),
            "sharpe": safe_float(conc.get("sharpe")),
            "max_dd": safe_float(conc.get("max_dd")),
            "selected_names": safe_float(conc.get("selected_names")),
        },
        "source_run": str(latest_run),
    }


def load_autolearning(autolearning_dir: Path) -> dict[str, Any]:
    hypotheses = read_json(autolearning_dir / "hypotheses_latest.json", []) or []
    counter_rows = read_csv_rows(autolearning_dir / "counterfactual_results.csv")
    challenger = read_json(autolearning_dir / "challenger_review.json", {}) or {}
    promotion = read_json(autolearning_dir / "promotion_decision.json", {}) or {}
    return {
        "hypothesis_count": len(hypotheses),
        "hypothesis_ids": [str(h.get("id", "")) for h in hypotheses if isinstance(h, dict)],
        "counterfactual_count": len(counter_rows),
        "counterfactuals": counter_rows,
        "challenger_status": challenger.get("status"),
        "promotion_status": promotion.get("status"),
        "source_dir": str(autolearning_dir),
    }


def top_values(rows: list[dict[str, str]], col: str, n: int = 10) -> list[str]:
    out: list[str] = []
    for row in rows[:n]:
        value = str(row.get(col, "")).strip()
        if value:
            out.append(value)
    return out


def load_lifecycle(lifecycle_dir: Path) -> dict[str, Any]:
    summary = read_json(lifecycle_dir / "winner_lifecycle_summary.json", {}) or {}
    missed = read_csv_rows(lifecycle_dir / "missed_winner_report.csv")
    stale = read_csv_rows(lifecycle_dir / "stale_winner_report.csv")
    rotations = read_csv_rows(lifecycle_dir / "leadership_rotation_report.csv")
    return {
        "status": "available" if missed or stale or rotations else "missing",
        "missed_count": len(missed),
        "stale_count": len(stale),
        "rotation_count": len(rotations),
        "top_missed": top_values(missed, "ticker", 12),
        "top_stale": top_values(stale, "ticker", 12),
        "top_rotations": [
            f"{row.get('held_ticker') or row.get('current_ticker')}->{row.get('challenger_ticker')}"
            for row in rotations[:12]
            if row.get("held_ticker") or row.get("current_ticker") or row.get("challenger_ticker")
        ],
        "summary": summary,
        "source_dir": str(lifecycle_dir),
    }


def return_stats(values: list[float]) -> dict[str, Any]:
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return {
            "n": 0,
            "avg_return": None,
            "median_return": None,
            "hit_rate": None,
            "loss_rate": None,
            "worst_return": None,
            "best_return": None,
            "trade_sharpe": None,
        }
    avg = sum(vals) / len(vals)
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return {
        "n": len(vals),
        "avg_return": avg,
        "median_return": statistics.median(vals),
        "hit_rate": sum(1 for v in vals if v > 0) / len(vals),
        "loss_rate": sum(1 for v in vals if v < 0) / len(vals),
        "worst_return": min(vals),
        "best_return": max(vals),
        "trade_sharpe": avg / std if std > 0 else None,
    }


def load_onset(onset_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = read_json(onset_dir / "pattern_summary.json", {}) or {}
    holds = read_csv_rows(onset_dir / "hold_diagnostics.csv")
    events = read_csv_rows(onset_dir / "events.csv")
    strategies = [
        "hold_3m_return",
        "hold_6m_return",
        "hold_12m_return",
        "hold_18m_return",
        "trail20_after_50pct_return",
        "ma50_5d_after_50pct_return",
        "ma200_after_50pct_return",
    ]
    event_rows: list[dict[str, Any]] = []
    for strategy in strategies:
        stats = return_stats([safe_float(row.get(strategy)) for row in holds])
        event_rows.append({
            "strategy": strategy,
            "status": "event_level" if stats["n"] else "missing",
            **stats,
        })
    onset = {
        "status": "available" if events or holds else "missing",
        "event_count": len(events),
        "hold_rows": len(holds),
        "production_activation_allowed": bool(summary.get("production_activation_allowed", False)),
        "filters": summary.get("filters", {}),
        "source_dir": str(onset_dir),
    }
    return onset, event_rows


def load_shakeout(shakeout_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = read_json(shakeout_dir / "pattern_summary.json", {}) or {}
    action_rows = read_csv_rows(shakeout_dir / "action_summary.csv")
    events = read_csv_rows(shakeout_dir / "events.csv")
    label_counts = summary.get("label_counts") or {}
    return {
        "status": "available" if events or action_rows else "missing",
        "event_count": len(events),
        "label_counts": label_counts,
        "production_activation_allowed": bool(summary.get("production_activation_allowed", False)),
        "filters": summary.get("filters", {}),
        "source_dir": str(shakeout_dir),
    }, [
        {
            "label": row.get("label"),
            "horizon": row.get("horizon"),
            "action": row.get("action"),
            "n": safe_float(row.get("n"), 0.0),
            "avg_return": safe_float(row.get("avg_return")),
            "median_return": safe_float(row.get("median_return")),
            "hit_rate": safe_float(row.get("hit_rate")),
            "worst_return": safe_float(row.get("worst_return")),
            "best_return": safe_float(row.get("best_return")),
        }
        for row in action_rows
    ]


def load_cash_drag(cash_drag_dir: Path) -> dict[str, Any]:
    summary = read_json(cash_drag_dir / "summary.json", {}) or {}
    best = summary.get("best_by_cagr") if isinstance(summary, dict) else {}
    return {
        "status": "available" if best else "missing",
        "production_activation_allowed": bool(summary.get("production_activation_allowed", False)) if isinstance(summary, dict) else False,
        "base_metrics": summary.get("base_metrics", {}) if isinstance(summary, dict) else {},
        "best_by_cagr": best or {},
        "source_dir": str(cash_drag_dir),
    }


def load_replay_metric_dir(path: Path) -> dict[str, Any]:
    metrics = read_json(path / "metrics.json", {}) or {}
    return {
        "status": metrics.get("status", "missing") if metrics else "missing",
        "production_activation_allowed": bool(metrics.get("production_activation_allowed", False)) if metrics else False,
        "metrics": metrics,
        "source_dir": str(path),
    }


def replay_input_status(latest_run: Path) -> dict[str, Any]:
    required = {
        "main_monthly_weights": latest_run / "reports" / "main_monthly_weights.csv",
        "sleeve_returns_by_month": latest_run / "reports" / "sleeve_returns_by_month.csv",
        "regime_by_month": latest_run / "reports" / "regime_by_month.csv",
        "concentrated_strategy_monthly": latest_run / "reports" / "concentrated_strategy_monthly.csv",
        "candidate_replay_book": latest_run / "reports" / "candidate_replay_book.csv",
    }
    exists = {name: path.exists() for name, path in required.items()}
    missing = [name for name, ok in exists.items() if not ok]
    return {
        "status": "ready" if not missing else "blocked_missing_monthly_books",
        "exists": exists,
        "missing": missing,
        "required_paths": {name: str(path) for name, path in required.items()},
    }


def build_decision(
    baseline: dict[str, Any],
    autolearning: dict[str, Any],
    lifecycle: dict[str, Any],
    onset: dict[str, Any],
    event_rows: list[dict[str, Any]],
    shakeout: dict[str, Any],
    shakeout_rows: list[dict[str, Any]],
    cash_drag: dict[str, Any],
    main_v2_replay: dict[str, Any],
    concentrated_replay: dict[str, Any],
    alpha_sprint_replay: dict[str, Any],
    position_risk_replay: dict[str, Any],
    monster_lifecycle_replay: dict[str, Any],
    replay_status: dict[str, Any],
) -> dict[str, Any]:
    best_event = None
    ready_events = [row for row in event_rows if row.get("n") and row.get("median_return") is not None]
    if ready_events:
        best_event = max(ready_events, key=lambda row: safe_float(row.get("median_return"), -999.0))
    main = baseline.get("main") or {}
    conc = baseline.get("concentrated") or {}
    main_cagr = safe_float(main.get("cagr"), 0.0)
    main_avg_cash = safe_float(main.get("avg_cash_weight"), 0.0)
    main_latest_cash = safe_float(main.get("latest_cash_weight"), 0.0)
    cash_drag_warning = bool(main_avg_cash > 0.08 or main_latest_cash > 0.10)
    main_cagr_gap_warning = bool(main_cagr < 0.25)
    policy_value_status = (
        "CAGR_FIRST_REPLAY_REQUIRED"
        if cash_drag_warning or main_cagr_gap_warning
        else "READY_FOR_VALUE_FUNCTION_REPLAY"
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only",
        "production_activation_allowed": False,
        "baseline": baseline,
        "autolearning": autolearning,
        "winner_lifecycle": lifecycle,
        "winner_onset": onset,
        "shakeout_breakdown": shakeout,
        "main_cash_drag_replay": cash_drag,
        "main_v2_historical_replay": main_v2_replay,
        "concentrated_policy_replay": concentrated_replay,
        "alpha_sprint_historical_sidecar": alpha_sprint_replay,
        "position_aware_risk_replay": position_risk_replay,
        "monster_lifecycle_replay": monster_lifecycle_replay,
        "event_level_backtest": {
            "status": "available" if onset.get("status") == "available" and ready_events else "missing_onset_event_backtest",
            "best_strategy_by_median_return": best_event,
            "rows": event_rows,
        },
        "shakeout_action_backtest": {
            "status": "available" if shakeout.get("status") == "available" and shakeout_rows else "missing_shakeout_action_backtest",
            "rows": shakeout_rows,
        },
        "policy_value_replay": {
            "status": policy_value_status,
            "cash_drag_warning": cash_drag_warning,
            "main_cagr_gap_warning": main_cagr_gap_warning,
            "observed": {
                "main_cagr": main_cagr,
                "main_avg_cash_weight": main_avg_cash,
                "main_latest_cash_weight": main_latest_cash,
                "concentrated_cagr": safe_float(conc.get("cagr"), 0.0),
                "concentrated_max_dd": safe_float(conc.get("max_dd"), 0.0),
            },
            "objective": {
                "primary": "maximize_net_cagr_subject_to_drawdown",
                "main_min_cagr": 0.25,
                "main_max_dd_floor": -0.22,
                "concentrated_min_cagr": 0.40,
                "concentrated_max_dd_floor": -0.25,
                "cash_drag_penalty": 0.30,
                "turnover_penalty": 0.10,
            },
            "candidate_grids": {
                "main_cash_cap_grid": [0.00, 0.03, 0.05, 0.08],
                "main_single_name_cap_grid": [0.18, 0.22, 0.25, 0.33],
                "concentrated_single_name_cap_grid": [0.25, 0.33, 0.40, 0.50],
                "shakeout_action_grid": ["hold", "trim50", "exit_to_cash", "add25_when_quality_high"],
                "distribution_action_grid": ["trim50", "exit_to_cash", "swap_to_new_leader"],
            },
        },
        "portfolio_level_replay": replay_status,
        "verdict": decide_verdict(onset, lifecycle, shakeout, replay_status),
    }


def decide_verdict(
    onset: dict[str, Any],
    lifecycle: dict[str, Any],
    shakeout: dict[str, Any],
    replay_status: dict[str, Any],
) -> str:
    if lifecycle.get("status") == "missing":
        return "BLOCKED_MISSING_WINNER_LIFECYCLE"
    if onset.get("status") == "missing" and shakeout.get("status") == "missing":
        return "BLOCKED_MISSING_WINNER_EVENT_STUDIES"
    if replay_status.get("status") != "ready":
        return "EVENT_LEVEL_ONLY_WAIT_FOR_MONTHLY_BOOKS"
    return "READY_FOR_PORTFOLIO_CHALLENGER_REPLAY"


def render_candidate_yaml(decision: dict[str, Any]) -> str:
    lifecycle = decision.get("winner_lifecycle") or {}
    onset = decision.get("winner_onset") or {}
    shakeout = decision.get("shakeout_breakdown") or {}
    cash_drag = decision.get("main_cash_drag_replay") or {}
    best = ((decision.get("event_level_backtest") or {}).get("best_strategy_by_median_return") or {})
    best_cash = cash_drag.get("best_by_cagr") or {}
    lines = [
        "# Generated by tools/run_autolearning_winner_challenger.py",
        "mode: proposal_only",
        "production_activation_allowed: false",
        "requires_historical_replay: true",
        "requires_human_approval: true",
        f"verdict: {decision.get('verdict')}",
        "inputs:",
        f"  auto_learning_hypotheses: {decision.get('autolearning', {}).get('hypothesis_count', 0)}",
        f"  lifecycle_missed_count: {lifecycle.get('missed_count', 0)}",
        f"  lifecycle_stale_count: {lifecycle.get('stale_count', 0)}",
        f"  onset_event_count: {onset.get('event_count', 0)}",
        f"  shakeout_event_count: {shakeout.get('event_count', 0)}",
        "candidate_rules:",
        "  - id: autolearning_winner_onset_overlay",
        "    status: proposal_only",
        "    action: replay_as_separate_challenger",
        "    components:",
        "      - missed_winner_acceleration_override",
        "      - stale_winner_trim_or_replace",
        "      - leadership_rotation_swap",
        "      - winner_onset_hold_until_trend_break",
        "      - shakeout_hold_add_or_breakdown_exit",
        "    suggested_event_hold_rule:",
        f"      strategy: {best.get('strategy', 'NA')}",
        f"      median_return: {best.get('median_return', 'NA')}",
        "    limits:",
        "      max_shadow_capacity: 0.10",
        "      max_single_name_weight: 0.05",
        "      production_activation_allowed: false",
        "      require_portfolio_level_replay: true",
        "  - id: high_conviction_sizing_grid",
        "    status: proposal_only",
        "    action: replay_concentrated_and_main_cap_grid",
        "    concentrated_single_name_cap_grid: [0.25, 0.33, 0.40, 0.50]",
        "    main_single_name_cap_grid: [0.15, 0.20, 0.25, 0.33]",
        "    activation: challenger_only",
        "  - id: cash_drag_reduction_grid",
        "    status: proposal_only",
        "    action: replay_main_cash_caps_before_any_production_change",
        "    main_cash_cap_grid: [0.00, 0.03, 0.05, 0.08]",
        f"    current_best_cash_cap: {best_cash.get('cash_cap', 'NA')}",
        f"    current_best_single_name_cap: {best_cash.get('single_name_cap', 'NA')}",
        "    objective: maximize_cagr_if_maxdd_and_turnover_do_not_regress",
        "    activation: challenger_only",
        "policy_value_replay:",
        f"  status: {(decision.get('policy_value_replay') or {}).get('status', 'UNKNOWN')}",
        "  objective: maximize_net_cagr_subject_to_drawdown",
    ]
    return "\n".join(lines) + "\n"


def render_report(decision: dict[str, Any], event_rows: list[dict[str, Any]]) -> str:
    baseline = decision.get("baseline") or {}
    main = baseline.get("main") or {}
    conc = baseline.get("concentrated") or {}
    lifecycle = decision.get("winner_lifecycle") or {}
    onset = decision.get("winner_onset") or {}
    shakeout = decision.get("shakeout_breakdown") or {}
    cash_drag = decision.get("main_cash_drag_replay") or {}
    main_v2_replay = decision.get("main_v2_historical_replay") or {}
    concentrated_replay = decision.get("concentrated_policy_replay") or {}
    alpha_sprint_replay = decision.get("alpha_sprint_historical_sidecar") or {}
    position_risk_replay = decision.get("position_aware_risk_replay") or {}
    monster_lifecycle_replay = decision.get("monster_lifecycle_replay") or {}
    replay = decision.get("portfolio_level_replay") or {}
    lines = [
        "# AutoLearning Winner Challenger",
        "",
        "Research-only harness connecting AutoLearning v2 with winner lifecycle, winner onset, and shakeout/breakdown studies.",
        "",
        "## Verdict",
        "",
        f"- `{decision.get('verdict')}`",
        f"- production_activation_allowed: `{decision.get('production_activation_allowed')}`",
        "",
        "## Baseline",
        "",
        f"- Main CAGR / Sharpe / MaxDD: {pct(main.get('cagr'))} / {main.get('sharpe')} / {pct(main.get('max_dd'))}",
        f"- Main avg/latest cash: {pct(main.get('avg_cash_weight'))} / {pct(main.get('latest_cash_weight'))}",
        f"- Concentrated CAGR / Sharpe / MaxDD: {pct(conc.get('cagr'))} / {conc.get('sharpe')} / {pct(conc.get('max_dd'))}",
        "",
        "## Connected Signals",
        "",
        f"- AutoLearning hypotheses: {decision.get('autolearning', {}).get('hypothesis_count', 0)}",
        f"- Missed winners: {lifecycle.get('missed_count', 0)} top={lifecycle.get('top_missed', [])[:8]}",
        f"- Stale winners: {lifecycle.get('stale_count', 0)} top={lifecycle.get('top_stale', [])[:8]}",
        f"- Leadership rotations: {lifecycle.get('rotation_count', 0)} top={lifecycle.get('top_rotations', [])[:8]}",
        f"- Onset events: {onset.get('event_count', 0)}",
        f"- Shakeout/breakdown events: {shakeout.get('event_count', 0)} labels={shakeout.get('label_counts', {})}",
        f"- Main cash-drag replay: {cash_drag.get('status')} best={cash_drag.get('best_by_cagr', {}).get('model')}",
        f"- Main v2 historical replay: {main_v2_replay.get('status')}",
        f"- Concentrated policy replay: {concentrated_replay.get('status')}",
        f"- Alpha Sprint historical sidecar: {alpha_sprint_replay.get('status')}",
        f"- Position-aware risk replay: {position_risk_replay.get('status')}",
        f"- Monster lifecycle replay: {monster_lifecycle_replay.get('status')} policy={monster_lifecycle_replay.get('metrics', {}).get('policy')}",
        "",
        "## Event-Level Backtest",
        "",
        "| Strategy | N | Median | Avg | Hit Rate | Worst | Best |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in event_rows:
        lines.append(
            f"| {row.get('strategy')} | {row.get('n')} | {pct(row.get('median_return'))} | "
            f"{pct(row.get('avg_return'))} | {pct(row.get('hit_rate'))} | "
            f"{pct(row.get('worst_return'))} | {pct(row.get('best_return'))} |"
        )
    shake_rows = (decision.get("shakeout_action_backtest") or {}).get("rows") or []
    lines.extend([
        "",
        "## Shakeout/Breakdown Action Backtest",
        "",
        "| Label | Horizon | Action | N | Median | Avg | Hit Rate | Worst |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in shake_rows:
        if str(row.get("horizon")) != "6m":
            continue
        lines.append(
            f"| {row.get('label')} | {row.get('horizon')} | {row.get('action')} | {int(safe_float(row.get('n'), 0))} | "
            f"{pct(row.get('median_return'))} | {pct(row.get('avg_return'))} | "
            f"{pct(row.get('hit_rate'))} | {pct(row.get('worst_return'))} |"
        )
    lines.extend([
        "",
        "## Portfolio Replay Readiness",
        "",
        f"- status: `{replay.get('status')}`",
        f"- missing: {replay.get('missing', [])}",
        f"- policy_value_replay: `{(decision.get('policy_value_replay') or {}).get('status')}`",
        "",
        "Event-level evidence can prioritize rules. It is not a substitute for portfolio-level CAGR/MaxDD replay.",
        "",
    ])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    autolearning_dir = repo_path(args.autolearning_dir)
    lifecycle_dir = repo_path(args.lifecycle_dir)
    onset_dir = repo_path(args.onset_dir)
    shakeout_dir = repo_path(args.shakeout_dir)
    cash_drag_dir = repo_path(args.cash_drag_dir)
    main_v2_replay_dir = repo_path(args.main_v2_replay_dir)
    concentrated_replay_dir = repo_path(args.concentrated_replay_dir)
    alpha_sprint_replay_dir = repo_path(args.alpha_sprint_replay_dir)
    position_risk_replay_dir = repo_path(args.position_risk_replay_dir)
    monster_lifecycle_replay_dir = repo_path(args.monster_lifecycle_replay_dir)
    output_dir = repo_path(args.output_dir)

    baseline = load_baseline(latest_run)
    autolearning = load_autolearning(autolearning_dir)
    lifecycle = load_lifecycle(lifecycle_dir)
    onset, event_rows = load_onset(onset_dir)
    shakeout, shakeout_rows = load_shakeout(shakeout_dir)
    cash_drag = load_cash_drag(cash_drag_dir)
    main_v2_replay = load_replay_metric_dir(main_v2_replay_dir)
    concentrated_replay = load_replay_metric_dir(concentrated_replay_dir)
    alpha_sprint_replay = load_replay_metric_dir(alpha_sprint_replay_dir)
    position_risk_replay = load_replay_metric_dir(position_risk_replay_dir)
    monster_lifecycle_replay = load_replay_metric_dir(monster_lifecycle_replay_dir)
    replay_status = replay_input_status(latest_run)
    decision = build_decision(
        baseline,
        autolearning,
        lifecycle,
        onset,
        event_rows,
        shakeout,
        shakeout_rows,
        cash_drag,
        main_v2_replay,
        concentrated_replay,
        alpha_sprint_replay,
        position_risk_replay,
        monster_lifecycle_replay,
        replay_status,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", decision)
    write_csv(
        output_dir / "event_backtest.csv",
        event_rows,
        [
            "strategy",
            "status",
            "n",
            "avg_return",
            "median_return",
            "hit_rate",
            "loss_rate",
            "worst_return",
            "best_return",
            "trade_sharpe",
        ],
    )
    write_text(output_dir / "candidate_experiment.yaml", render_candidate_yaml(decision))
    write_text(output_dir / "challenger_report.md", render_report(decision, event_rows))
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest-run", default=str(DEFAULT_LATEST_RUN))
    parser.add_argument("--autolearning-dir", default=str(DEFAULT_AUTOLEARNING_DIR))
    parser.add_argument("--lifecycle-dir", default=str(DEFAULT_LIFECYCLE_DIR))
    parser.add_argument("--onset-dir", default=str(DEFAULT_ONSET_DIR))
    parser.add_argument("--shakeout-dir", default=str(DEFAULT_SHAKEOUT_DIR))
    parser.add_argument("--cash-drag-dir", default=str(DEFAULT_CASH_DRAG_DIR))
    parser.add_argument("--main-v2-replay-dir", default=str(DEFAULT_MAIN_V2_REPLAY_DIR))
    parser.add_argument("--concentrated-replay-dir", default=str(DEFAULT_CONCENTRATED_REPLAY_DIR))
    parser.add_argument("--alpha-sprint-replay-dir", default=str(DEFAULT_ALPHA_SPRINT_REPLAY_DIR))
    parser.add_argument("--position-risk-replay-dir", default=str(DEFAULT_POSITION_RISK_REPLAY_DIR))
    parser.add_argument("--monster-lifecycle-replay-dir", default=str(DEFAULT_MONSTER_LIFECYCLE_REPLAY_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    decision = run(args)
    print(json.dumps({
        "verdict": decision.get("verdict"),
        "output_dir": str(repo_path(args.output_dir)),
        "production_activation_allowed": decision.get("production_activation_allowed"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
