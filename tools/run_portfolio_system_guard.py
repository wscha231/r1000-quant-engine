#!/usr/bin/env python3
"""Run a fast portfolio system guard from existing artifacts.

This guard is intentionally lightweight:
- it reuses committed/latest rebuild data when available;
- it checks target gaps for main and concentrated portfolios;
- it summarizes automation ownership and blocked promotion reasons;
- it writes review artifacts for GitHub Actions;
- it only fails the process when --strict-targets is set.

It does not alter production defaults or promote any candidate policy.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from r1000_config import PORTFOLIO_GOAL_TARGETS
except Exception:  # pragma: no cover - isolated smoke fallback
    PORTFOLIO_GOAL_TARGETS = {
        "main": {"cagr": 0.30, "max_dd": -0.15},
        "concentrated": {"cagr": 0.50, "max_dd": -0.18},
    }

DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/portfolio_system_guard"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


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


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10])
    except ValueError:
        return None


def csv_date_summary(path: Path, date_col: str) -> dict[str, Any]:
    rows = read_csv_rows(path)
    dates = [parse_date(row.get(date_col)) for row in rows]
    dates = [dt for dt in dates if dt is not None]
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "date_col": date_col,
        "min_date": min(dates).date().isoformat() if dates else None,
        "max_date": max(dates).date().isoformat() if dates else None,
        "unique_date_count": len({dt.date().isoformat() for dt in dates}),
    }


def csv_row_count(path: Path) -> int:
    return len(read_csv_rows(path))


def target_book_summaries(latest_run: Path, portfolio: str) -> dict[str, dict[str, Any]]:
    if portfolio == "main":
        historical = latest_run / "reports" / "main_monthly_weights.csv"
        operating = latest_run / "reports" / "operating_main_target_book.csv"
    else:
        historical = latest_run / "reports" / "concentrated_strategy_holdings.csv"
        operating = latest_run / "reports" / "operating_concentrated_target_book.csv"
    historical_summary = csv_date_summary(historical, "rebalance_date")
    historical_summary["target_book_role"] = "historical_research_book"
    operating_summary = csv_date_summary(operating, "rebalance_date")
    operating_summary["target_book_role"] = "operating_target_book"
    selected = operating_summary if operating_summary["exists"] and int(operating_summary["row_count"]) > 0 else historical_summary
    return {
        "selected": selected,
        "historical": historical_summary,
        "operating": operating_summary,
    }


def filter_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = float(text)
        if abs(number - round(number)) < 1e-9:
            return str(int(round(number)))
    except ValueError:
        pass
    return text


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if out != out:
            return default
        return out
    except (TypeError, ValueError):
        return default


def pp(value: float) -> float:
    return round(value * 100.0, 4)


def metric(metrics: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in metrics:
            return safe_float(metrics.get(name), default)
    return default


def portfolio_status(name: str, metrics: dict[str, Any], cagr_target: float, max_dd_target: float) -> dict[str, Any]:
    cagr = metric(metrics, "cagr", "strategy_cagr")
    max_dd = metric(metrics, "max_dd")
    sharpe = metric(metrics, "sharpe")
    turnover = metric(metrics, "avg_turnover_monthly", default=0.0)
    cagr_gap = cagr_target - cagr
    maxdd_gap = max_dd_target - max_dd
    return {
        "portfolio": name,
        "metric_source": metrics.get("_metric_source", "legacy_weight_backtest"),
        "cagr": cagr,
        "cagr_target": cagr_target,
        "cagr_pass": cagr >= cagr_target,
        "cagr_gap_pp": pp(max(0.0, cagr_gap)),
        "max_dd": max_dd,
        "max_dd_target": max_dd_target,
        "max_dd_pass": max_dd >= max_dd_target,
        "max_dd_improvement_needed_pp": pp(max(0.0, maxdd_gap)),
        "sharpe": sharpe,
        "avg_turnover_monthly": turnover,
        "target_pass": cagr >= cagr_target and max_dd >= max_dd_target,
    }


def write_target_gap_csv(path: Path, statuses: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "portfolio",
        "metric_source",
        "cagr",
        "cagr_target",
        "cagr_pass",
        "cagr_gap_pp",
        "max_dd",
        "max_dd_target",
        "max_dd_pass",
        "max_dd_improvement_needed_pp",
        "sharpe",
        "avg_turnover_monthly",
        "target_pass",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in statuses:
            writer.writerow({key: row.get(key) for key in fieldnames})


def existing_workflows() -> list[str]:
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    return sorted(path.name for path in workflow_dir.glob("*.yml"))


def broker_or_legacy_metrics(latest_run: Path, portfolio: str) -> dict[str, Any]:
    """Prefer account-like broker ledger metrics for target governance.

    Legacy weight-level backtests remain useful for research comparison, but
    target pass/fail must use replayed trades with cash, fills, shares, and
    transaction costs when those artifacts exist.
    """

    broker = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    legacy_name = "backtest_metrics.json" if portfolio == "main" else "concentrated_backtest_metrics.json"
    legacy = read_json(latest_run / legacy_name)
    if broker:
        out = dict(broker)
        out["_metric_source"] = "broker_ledger_next_close"
        out["_legacy_cagr"] = metric(legacy, "cagr", "strategy_cagr") if legacy else None
        out["_legacy_max_dd"] = metric(legacy, "max_dd", "max_drawdown") if legacy else None
        return out
    out = dict(legacy)
    if out:
        out["_metric_source"] = "legacy_weight_backtest"
    return out


def load_inputs(latest_run: Path) -> dict[str, Any]:
    return {
        "main_metrics": broker_or_legacy_metrics(latest_run, "main"),
        "concentrated_metrics": broker_or_legacy_metrics(latest_run, "concentrated"),
        "experiment_summary": read_json(REPO_ROOT / "outputs" / "experiments" / "experiment_matrix_summary.json"),
        "auto_learning_v2": read_json(REPO_ROOT / "outputs" / "auto_learning_v2" / "challenger_review.json"),
        "promotion_v2": read_json(REPO_ROOT / "outputs" / "auto_learning_v2" / "promotion_decision.json"),
        "policy_candidate_v2": read_json(REPO_ROOT / "outputs" / "auto_learning_v2" / "policy_candidate.json"),
        "orchestrator_replay": read_json(REPO_ROOT / "outputs" / "orchestrator_replay" / "concentrated_balanced" / "metrics.json"),
        "goal_search": read_json(latest_run / "portfolio_goal_search" / "goal_search_summary.json")
        or read_json(REPO_ROOT / "outputs" / "portfolio_goal_search" / "goal_search_summary.json"),
        "account_evaluation": read_json(latest_run / "account_evaluation" / "account_evaluation_summary.json")
        or read_json(REPO_ROOT / "outputs" / "account_evaluation" / "account_evaluation_summary.json"),
        "operating_event_backtest": read_json(latest_run / "operating_event_backtest" / "operating_event_backtest_summary.json")
        or read_json(REPO_ROOT / "outputs" / "operating_event_backtest" / "operating_event_backtest_summary.json"),
        "workflows": existing_workflows(),
    }


def operating_alignment_checks(inputs: dict[str, Any], latest_run: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    target_books = {portfolio: target_book_summaries(latest_run, portfolio) for portfolio in ("main", "concentrated")}
    broker_end = {
        "main": inputs.get("main_metrics", {}).get("end_date"),
        "concentrated": inputs.get("concentrated_metrics", {}).get("end_date"),
    }
    for portfolio, summaries in target_books.items():
        summary = summaries["selected"]
        historical = summaries["historical"]
        operating = summaries["operating"]
        max_dt = parse_date(summary.get("max_date"))
        end_dt = parse_date(broker_end.get(portfolio))
        passed = bool(max_dt and end_dt and max_dt.date() >= end_dt.date())
        checks.append(
            {
                "check": f"{portfolio}_target_book_reaches_broker_end",
                "passed": passed,
                "severity": "error" if not passed else "ok",
                "detail": f"selected_role={summary.get('target_book_role')}; target_book_max={summary.get('max_date')}; broker_end={broker_end.get(portfolio)}; rows={summary.get('row_count')}; path={summary.get('path')}",
            }
        )
        operating_exists = bool(operating.get("exists") and int(operating.get("row_count") or 0) > 0)
        checks.append(
            {
                "check": f"{portfolio}_operating_target_book_available",
                "passed": operating_exists,
                "severity": "error" if not operating_exists else "ok",
                "detail": f"operating_book={operating.get('path')}; rows={operating.get('row_count')}; max_date={operating.get('max_date')}",
            }
        )
        historical_max_dt = parse_date(historical.get("max_date"))
        historical_recent = bool(historical_max_dt and end_dt and historical_max_dt.date() >= end_dt.date())
        checks.append(
            {
                "check": f"{portfolio}_historical_research_book_reaches_broker_end",
                "passed": historical_recent,
                "severity": "warn" if not historical_recent else "ok",
                "detail": f"historical_book_max={historical.get('max_date')}; broker_end={broker_end.get(portfolio)}; rows={historical.get('row_count')}; operating_book_max={operating.get('max_date')}; operating_rows={operating.get('row_count')}",
            }
        )
        metrics = inputs.get(f"{portfolio}_metrics", {}) or {}
        metric_target_book = str(metrics.get("target_book") or "")
        uses_operating = f"operating_{portfolio}_target_book.csv" in metric_target_book.replace("\\", "/")
        checks.append(
            {
                "check": f"{portfolio}_broker_replay_uses_operating_target_book",
                "passed": uses_operating,
                "severity": "error" if not uses_operating else "ok",
                "detail": f"metric_target_book={metric_target_book or 'missing'}",
            }
        )

    current_only = latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv"
    legacy_current = latest_run / "operating_snapshot" / "current_portfolio_snapshot_latest.csv"
    current_only_rows = csv_row_count(current_only)
    checks.append(
        {
            "check": "current_only_operating_holdings_available",
            "passed": current_only_rows > 0,
            "severity": "warn" if current_only_rows == 0 else "ok",
            "detail": f"{current_only}; rows={current_only_rows}; legacy_snapshot_exists={legacy_current.exists()}",
        }
    )

    main_positions = csv_row_count(latest_run / "broker_replay" / "main" / "positions_latest.csv")
    main_target_rows = csv_row_count(latest_run / "portfolio_latest.csv")
    main_excess = max(0, main_positions - main_target_rows)
    checks.append(
        {
            "check": "main_current_position_count_near_latest_target_count",
            "passed": main_excess <= 5,
            "severity": "warn" if main_excess > 5 else "ok",
            "detail": f"main_positions={main_positions}; latest_target_rows={main_target_rows}; excess={main_excess}",
        }
    )

    concentrated_metrics = inputs.get("concentrated_metrics", {})
    metric_filter = concentrated_metrics.get("target_book_filter") or {}
    latest_conc_rows = read_csv_rows(latest_run / "concentrated_portfolio_latest.csv")
    latest_conc = latest_conc_rows[0] if latest_conc_rows else {}
    metric_n = filter_value(metric_filter.get("target_stock_names"))
    latest_n = filter_value(latest_conc.get("target_stock_names"))
    metric_mode = filter_value(metric_filter.get("weighting_mode"))
    latest_mode = filter_value(latest_conc.get("weighting_mode"))
    filter_match = bool(metric_n and latest_n and metric_n == latest_n and metric_mode == latest_mode)
    checks.append(
        {
            "check": "concentrated_replay_filter_matches_latest_target",
            "passed": filter_match,
            "severity": "warn" if not filter_match else "ok",
            "detail": f"broker_filter_n={metric_n or 'missing'}; latest_target_n={latest_n or 'missing'}; broker_mode={metric_mode or 'missing'}; latest_mode={latest_mode or 'missing'}",
        }
    )
    return checks


def error_checks(inputs: dict[str, Any], latest_run: Path, require_latest_artifacts: bool = False) -> list[dict[str, Any]]:
    def rel(path: Path) -> str:
        try:
            return path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)

    latest_artifact_severity = "error" if require_latest_artifacts else "warn"
    checks = [
        ("main_metrics_available", bool(inputs["main_metrics"]), rel(latest_run / "backtest_metrics.json")),
        ("concentrated_metrics_available", bool(inputs["concentrated_metrics"]), rel(latest_run / "concentrated_backtest_metrics.json")),
        ("experiment_matrix_available", bool(inputs["experiment_summary"]), "outputs/experiments/experiment_matrix_summary.json"),
        ("auto_learning_v2_challenger_available", bool(inputs["auto_learning_v2"]), "outputs/auto_learning_v2/challenger_review.json"),
        ("auto_learning_v2_policy_available", bool(inputs["policy_candidate_v2"]), "outputs/auto_learning_v2/policy_candidate.json"),
        ("orchestrator_replay_available", bool(inputs["orchestrator_replay"]), "outputs/orchestrator_replay/concentrated_balanced/metrics.json"),
        ("portfolio_goal_search_available", bool(inputs["goal_search"]), "outputs/portfolio_goal_search/goal_search_summary.json"),
        ("account_evaluation_available", bool(inputs["account_evaluation"]), "outputs/account_evaluation/account_evaluation_summary.json"),
        ("github_workflows_available", bool(inputs["workflows"]), ".github/workflows"),
    ]
    out = []
    for check_id, passed, detail in checks:
        severity = "ok"
        if not passed:
            if check_id in {"main_metrics_available", "concentrated_metrics_available"}:
                severity = latest_artifact_severity
            elif check_id == "account_evaluation_available":
                severity = "warn"
            else:
                severity = "error"
        out.append({"check": check_id, "passed": passed, "severity": severity, "detail": detail})

    challenger = inputs.get("auto_learning_v2") or {}
    missing_counterfactual = int(safe_float(challenger.get("missing_counterfactual_count"), 0))
    out.append(
        {
            "check": "counterfactual_replay_coverage",
            "passed": missing_counterfactual == 0,
            "severity": "warn" if missing_counterfactual else "ok",
            "detail": f"missing_counterfactual_count={missing_counterfactual}",
        }
    )
    production_ready = int(safe_float(challenger.get("production_ready_count"), 0))
    out.append(
        {
            "check": "candidate_production_ready",
            "passed": production_ready > 0,
            "severity": "warn" if production_ready == 0 else "ok",
            "detail": f"production_ready_count={production_ready}",
        }
    )
    operating_event = inputs.get("operating_event_backtest") or {}
    out.append(
        {
            "check": "operating_event_backtest_available",
            "passed": bool(operating_event),
            "severity": "warn" if not operating_event else "ok",
            "detail": "outputs/operating_event_backtest/operating_event_backtest_summary.json",
        }
    )
    if operating_event:
        daily_risk = bool(operating_event.get("daily_risk_overlay_validated"))
        full_entries = bool(operating_event.get("full_nonmonthly_entry_replacement_validated"))
        action_count = int(safe_float(operating_event.get("daily_risk_action_evidence_count"), 0))
        out.append(
            {
                "check": "daily_risk_overlay_backtest_validated",
                "passed": daily_risk,
                "severity": "warn" if not daily_risk else "ok",
                "detail": f"daily_risk_overlay_validated={daily_risk}; nonmonthly_risk_action_count={action_count}",
            }
        )
        out.append(
            {
                "check": "full_nonmonthly_entry_replacement_backtest_validated",
                "passed": full_entries,
                "severity": "warn" if not full_entries else "ok",
                "detail": f"full_nonmonthly_entry_replacement_validated={full_entries}; daily_risk_action_evidence_count={action_count}",
            }
        )
    replay = inputs.get("orchestrator_replay") or {}
    replay_valid = bool(replay.get("valid_for_promotion"))
    out.append(
        {
            "check": "orchestrator_replay_valid_for_promotion",
            "passed": replay_valid,
            "severity": "warn" if not replay_valid else "ok",
            "detail": f"status={replay.get('status')}; data_mode={replay.get('data_mode')}",
        }
    )
    out.extend(operating_alignment_checks(inputs, latest_run))
    return out


def top_research_candidates(experiment_summary: dict[str, Any], orchestrator_replay: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ranked = experiment_summary.get("ranked") or []
    candidates = []
    for row in ranked:
        if row.get("experiment_id") == "E0_baseline_latest":
            continue
        if row.get("passed_discovery") or row.get("requires_full_challenger_backtest"):
            candidates.append(
                {
                    "experiment_id": row.get("experiment_id"),
                    "status": row.get("status"),
                    "passed_discovery": bool(row.get("passed_discovery")),
                    "requires_full_challenger_backtest": bool(row.get("requires_full_challenger_backtest")),
                    "cagr_delta_pp": row.get("cagr_delta_pp"),
                    "maxdd_delta_pp": row.get("maxdd_delta_pp"),
                    "sharpe_delta": row.get("sharpe_delta"),
                    "priority": candidate_priority(row),
                }
            )
    replay = orchestrator_replay or {}
    if replay:
        unified = ((replay.get("metrics") or {}).get("unified_balanced") or {})
        candidates.append(
            {
                "experiment_id": replay.get("experiment_id", "E4_concentrated_balanced_replay"),
                "status": replay.get("status"),
                "passed_discovery": bool(replay.get("valid_for_promotion")),
                "requires_full_challenger_backtest": not bool(replay.get("valid_for_promotion")),
                "cagr_delta_pp": None,
                "maxdd_delta_pp": None,
                "sharpe_delta": None,
                "priority": 12.0 if replay.get("valid_for_promotion") else 4.0,
                "replay_cagr": unified.get("cagr"),
                "replay_max_dd": unified.get("max_dd"),
                "data_mode": replay.get("data_mode"),
            }
        )
    return sorted(candidates, key=lambda row: safe_float(row.get("priority"), 0.0), reverse=True)[:8]


def goal_search_candidates(goal_search: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    goal_search = goal_search or {}
    out: list[dict[str, Any]] = []
    for key in ("best_main", "best_concentrated"):
        row = goal_search.get(key) or {}
        if not row.get("candidate_id"):
            continue
        out.append(
            {
                "portfolio": row.get("portfolio"),
                "candidate_id": row.get("candidate_id"),
                "target_pass": bool(row.get("target_pass")),
                "governance_action": row.get("governance_action"),
                "cagr": row.get("cagr"),
                "cagr_gap_pp": row.get("cagr_gap_pp"),
                "max_dd": row.get("max_dd"),
                "max_dd_gap_pp": row.get("max_dd_gap_pp"),
                "valid_for_production": bool(row.get("valid_for_production")),
            }
        )
    return out


def candidate_priority(row: dict[str, Any]) -> float:
    score = safe_float(row.get("discovery_score"), 0.0)
    if row.get("passed_discovery"):
        score += 10.0
    if row.get("requires_full_challenger_backtest"):
        score += 3.0
    return score


def automation_plan(inputs: dict[str, Any], targets_pass: bool) -> dict[str, Any]:
    workflows = set(inputs.get("workflows") or [])
    return {
        "production_defaults": "unchanged",
        "fast_guard": {
            "owner": ".github/workflows/portfolio_system_guard.yml",
            "status": "active_after_this_change" if "portfolio_system_guard.yml" in workflows else "new_workflow_added",
            "role": "Fast PR/manual target gap, artifact, error, and promotion-blocker check from committed data.",
            "default_runtime": "short",
            "strict_mode": "manual input only",
        },
        "data_refresh": {
            "owner": ".github/workflows/weekly_data_refresh.yml",
            "role": "Refresh Finnhub/theme substrate before deeper rebuilds.",
            "default_runtime": "medium",
        },
        "full_rebuild": {
            "owner": ".github/workflows/full_rebuild_manual.yml",
            "role": "Manual long-run only; use skip_collector=true and fast_mode=true when cached data exists.",
            "default_runtime": "long",
        },
        "aggressive_lab": {
            "owner": ".github/workflows/aggressive_lab_manual.yml and tools/run_aggressive_experiment_matrix.py",
            "role": "Discovery experiments; failures are retained as research artifacts.",
            "next_change_needed": "Wire full historical replay for Main v2, concentrated policy, orchestrator, and Alpha Sprint.",
        },
        "auto_learning": {
            "owner": ".github/workflows/quarterly_auto_learning.yml and tools/run_auto_learning_v2.py",
            "role": "Feature gates plus Alpha Scientist hypotheses. Proposal-only by default.",
            "promotion_rule": "No production write without challenger pass, strict target gate, and human approval.",
        },
        "target_management": {
            "main_target": f"CAGR >= {PORTFOLIO_GOAL_TARGETS['main']['cagr']:.0%}, MaxDD >= {PORTFOLIO_GOAL_TARGETS['main']['max_dd']:.0%}",
            "concentrated_target": f"CAGR >= {PORTFOLIO_GOAL_TARGETS['concentrated']['cagr']:.0%}, MaxDD >= {PORTFOLIO_GOAL_TARGETS['concentrated']['max_dd']:.0%}",
            "current_target_pass": targets_pass,
            "recommended_next_focus": [
                "Concentrated full orchestrator replay at 20-30% capacity with caps.",
                "Main v2 historical replay with target N 12/15 and future_winner-heavy sleeve allocation.",
                "Risk sensing Layer 1/3/4 position-aware exits to keep MaxDD improvement without CAGR drag.",
                "Alpha Sprint bull-only replay using breakout/RS/catalyst fallback because explosion_* is dormant.",
            ],
        },
    }


def render_report(
    main_status: dict[str, Any],
    concentrated_status: dict[str, Any],
    candidates: list[dict[str, Any]],
    goal_candidates: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    plan: dict[str, Any],
    strict_targets: bool,
) -> str:
    lines = [
        "# Portfolio System Guard",
        "",
        "Fast integrated check from existing artifacts. Production defaults are not changed.",
        "",
        "## Target Status",
        "",
        "| Portfolio | CAGR | Target | Gap | MaxDD | Target | DD improvement needed | Pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in [main_status, concentrated_status]:
        lines.append(
            "| {portfolio} | {cagr:.2%} | {cagr_target:.2%} | {cagr_gap:.2f}pp | {max_dd:.2%} | {max_dd_target:.2%} | {dd_gap:.2f}pp | {passed} |".format(
                portfolio=row["portfolio"],
                cagr=safe_float(row.get("cagr")),
                cagr_target=safe_float(row.get("cagr_target")),
                cagr_gap=safe_float(row.get("cagr_gap_pp")),
                max_dd=safe_float(row.get("max_dd")),
                max_dd_target=safe_float(row.get("max_dd_target")),
                dd_gap=safe_float(row.get("max_dd_improvement_needed_pp")),
                passed=str(row.get("target_pass")).lower(),
            )
        )
    lines.extend(["", "Metric sources:"])
    for row in [main_status, concentrated_status]:
        lines.append(f"- `{row['portfolio']}`: `{row.get('metric_source', 'unknown')}`")
    lines.extend(["", f"Strict target mode: `{str(strict_targets).lower()}`", ""])

    lines.extend(["## Candidate Priority", ""])
    if candidates:
        lines.extend(["| Experiment | Status | Discovery | Needs replay | CAGR delta pp | MaxDD delta pp |", "| --- | --- | ---: | ---: | ---: | ---: |"])
        for row in candidates[:6]:
            lines.append(
                "| {experiment} | `{status}` | {discovery} | {replay} | {cagr} | {maxdd} |".format(
                    experiment=row.get("experiment_id"),
                    status=row.get("status"),
                    discovery=str(row.get("passed_discovery")).lower(),
                    replay=str(row.get("requires_full_challenger_backtest")).lower(),
                    cagr="" if row.get("cagr_delta_pp") is None else f"{safe_float(row.get('cagr_delta_pp')):.2f}",
                    maxdd="" if row.get("maxdd_delta_pp") is None else f"{safe_float(row.get('maxdd_delta_pp')):.2f}",
                )
            )
    else:
        lines.append("No experiment candidates found.")
    lines.append("")

    lines.extend(["## Goal Search", ""])
    if goal_candidates:
        lines.extend(["| Portfolio | Best candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"])
        for row in goal_candidates:
            lines.append(
                "| {portfolio} | `{candidate}` | {cagr:.2%} | {cagr_gap:.2f}pp | {max_dd:.2%} | {dd_gap:.2f}pp | {passed} | `{action}` |".format(
                    portfolio=row.get("portfolio"),
                    candidate=row.get("candidate_id"),
                    cagr=safe_float(row.get("cagr")),
                    cagr_gap=safe_float(row.get("cagr_gap_pp")),
                    max_dd=safe_float(row.get("max_dd")),
                    dd_gap=safe_float(row.get("max_dd_gap_pp")),
                    passed=str(row.get("target_pass")).lower(),
                    action=row.get("governance_action"),
                )
            )
    else:
        lines.append("Goal search artifact is not available yet.")
    lines.append("")

    lines.extend(["## Error Checks", ""])
    for check in checks:
        marker = "PASS" if check["passed"] else check["severity"].upper()
        lines.append(f"- `{marker}` {check['check']}: {check['detail']}")
    lines.append("")

    lines.extend(["## Automation Plan", ""])
    lines.append(f"- Fast guard: {plan['fast_guard']['role']}")
    lines.append(f"- Data refresh: {plan['data_refresh']['role']}")
    lines.append(f"- Full rebuild: {plan['full_rebuild']['role']}")
    lines.append(f"- Aggressive lab: {plan['aggressive_lab']['role']}")
    lines.append(f"- AutoLearning: {plan['auto_learning']['role']}")
    lines.append("")
    lines.extend(["## Next Focus", ""])
    for item in plan["target_management"]["recommended_next_focus"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    inputs = load_inputs(latest_run)

    main_status = portfolio_status("main", inputs["main_metrics"], args.main_cagr_target, args.main_max_dd_target)
    concentrated_status = portfolio_status(
        "concentrated",
        inputs["concentrated_metrics"],
        args.concentrated_cagr_target,
        args.concentrated_max_dd_target,
    )
    statuses = [main_status, concentrated_status]
    targets_pass = all(row["target_pass"] for row in statuses)
    checks = error_checks(
        inputs,
        latest_run,
        require_latest_artifacts=bool(getattr(args, "require_latest_artifacts", False) or args.strict_targets),
    )
    candidates = top_research_candidates(inputs["experiment_summary"], inputs.get("orchestrator_replay"))
    goal_candidates = goal_search_candidates(inputs.get("goal_search"))
    plan = automation_plan(inputs, targets_pass)
    hard_errors = [row for row in checks if row["severity"] == "error" and not row["passed"]]
    overall_status = "target_pass" if targets_pass and not hard_errors else "blocked"

    payload = {
        "overall_status": overall_status,
        "strict_targets": args.strict_targets,
        "targets_pass": targets_pass,
        "portfolio_status": statuses,
        "top_research_candidates": candidates,
        "goal_search_candidates": goal_candidates,
        "error_checks": checks,
        "automation_plan": plan,
    }

    write_json(output_dir / "target_gap.json", payload)
    write_target_gap_csv(output_dir / "target_gap.csv", statuses)
    write_json(output_dir / "error_check.json", {"checks": checks, "hard_error_count": len(hard_errors)})
    write_json(output_dir / "automation_plan.json", plan)
    write_text(output_dir / "automation_plan.md", render_automation_plan(plan))
    report = render_report(main_status, concentrated_status, candidates, goal_candidates, checks, plan, args.strict_targets)
    write_text(output_dir / "system_guard_report.md", report)

    return payload


def render_automation_plan(plan: dict[str, Any]) -> str:
    lines = [
        "# Portfolio Automation Plan",
        "",
        "Production defaults remain unchanged. Automation is split by runtime cost and promotion risk.",
        "",
    ]
    for key in ["fast_guard", "data_refresh", "full_rebuild", "aggressive_lab", "auto_learning"]:
        item = plan[key]
        lines.extend([f"## {key}", "", f"- Owner: `{item.get('owner')}`", f"- Role: {item.get('role')}", ""])
    lines.extend(["## Target Management", ""])
    for focus in plan["target_management"]["recommended_next_focus"]:
        lines.append(f"- {focus}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--main-cagr-target", type=float, default=PORTFOLIO_GOAL_TARGETS["main"]["cagr"])
    parser.add_argument("--main-max-dd-target", type=float, default=PORTFOLIO_GOAL_TARGETS["main"]["max_dd"])
    parser.add_argument("--concentrated-cagr-target", type=float, default=PORTFOLIO_GOAL_TARGETS["concentrated"]["cagr"])
    parser.add_argument("--concentrated-max-dd-target", type=float, default=PORTFOLIO_GOAL_TARGETS["concentrated"]["max_dd"])
    parser.add_argument("--strict-targets", action="store_true")
    parser.add_argument(
        "--require-latest-artifacts",
        action="store_true",
        help="Fail when committed/latest rebuild metrics are absent. Default PR mode treats them as warnings.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.strict_targets and not result["targets_pass"]:
        return 2
    hard_errors = [row for row in result["error_checks"] if row["severity"] == "error" and not row["passed"]]
    if hard_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
