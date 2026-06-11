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
        "main": {"cagr": 0.35, "max_dd": -0.25},
        "concentrated": {"cagr": 0.50, "max_dd": -0.25},
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


def latest_target_filter(path: Path) -> dict[str, str]:
    rows = read_csv_rows(path)
    if not rows:
        return {}
    dates = [parse_date(row.get("rebalance_date")) for row in rows]
    dates = [dt for dt in dates if dt is not None]
    if dates:
        max_date = max(dates).date().isoformat()
        rows = [row for row in rows if str(row.get("rebalance_date") or "")[:10] == max_date]
    rows = [row for row in rows if str(row.get("ticker") or "").upper().strip() != "CASH"]
    out: dict[str, str] = {}
    for col in ("target_stock_names", "target_n", "weighting_mode"):
        values = [filter_value(row.get(col)) for row in rows]
        values = [value for value in values if value]
        if values:
            out[col] = max(set(values), key=values.count)
    if "target_n" in out and "target_stock_names" not in out:
        out["target_stock_names"] = out["target_n"]
    return out


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


def target_book_shape(path: Path, portfolio: str) -> dict[str, Any]:
    rows = read_csv_rows(path)
    if not rows:
        return {"portfolio": portfolio, "path": str(path), "exists": path.exists(), "row_count": 0}
    dates = [parse_date(row.get("rebalance_date")) for row in rows]
    dates = [dt for dt in dates if dt is not None]
    max_date = max(dates).date().isoformat() if dates else None
    if max_date:
        rows = [row for row in rows if str(row.get("rebalance_date") or "")[:10] == max_date]
    stock_rows = [row for row in rows if str(row.get("ticker") or "").upper().strip() not in {"CASH", "__CASH__"}]
    cash_weight = sum(
        safe_float(row.get("weight") or row.get("target_weight"))
        for row in rows
        if str(row.get("ticker") or "").upper().strip() in {"CASH", "__CASH__"}
    )
    stock_weights = {
        str(row.get("ticker") or "").upper().strip(): safe_float(row.get("weight") or row.get("target_weight"))
        for row in stock_rows
    }
    max_stock_ticker = max(stock_weights, key=stock_weights.get) if stock_weights else ""
    industry_group_weights: dict[str, float] = {}
    for row in stock_rows:
        group = str(row.get("industry_group") or row.get("industry") or row.get("sector") or "").strip()
        if group:
            industry_group_weights[group] = industry_group_weights.get(group, 0.0) + safe_float(
                row.get("weight") or row.get("target_weight")
            )
    max_industry_group = max(industry_group_weights, key=industry_group_weights.get) if industry_group_weights else ""
    crisis_values = [
        str(row.get("crisis_state") or row.get("regime_capacity_regime") or "").strip()
        for row in stock_rows
        if str(row.get("crisis_state") or row.get("regime_capacity_regime") or "").strip()
    ]
    crisis_state = max(set(crisis_values), key=crisis_values.count) if crisis_values else ""
    return {
        "portfolio": portfolio,
        "path": str(path),
        "exists": path.exists(),
        "latest_rebalance_date": max_date,
        "row_count": len(rows),
        "stock_count": len(stock_rows),
        "cash_weight": cash_weight,
        "max_stock_weight": stock_weights.get(max_stock_ticker, 0.0),
        "max_stock_weight_ticker": max_stock_ticker,
        "max_industry_group_weight": industry_group_weights.get(max_industry_group, 0.0),
        "max_industry_group": max_industry_group,
        "crisis_state": crisis_state,
    }


def latest_target_book_shape(latest_run: Path, portfolio: str) -> dict[str, Any]:
    filename = "operating_main_target_book.csv" if portfolio == "main" else "operating_concentrated_target_book.csv"
    return target_book_shape(latest_run / "reports" / filename, portfolio)


CONCENTRATED_MAX_SINGLE_NAME_WEIGHT = 0.40
CONCENTRATED_MAX_INDUSTRY_GROUP_WEIGHT = 0.60


def shape_violations(shape: dict[str, Any]) -> list[str]:
    if not shape.get("exists") or not shape.get("row_count"):
        return []
    violations: list[str] = []
    if shape.get("portfolio") == "main":
        cash = safe_float(shape.get("cash_weight"))
        stock_count = int(safe_float(shape.get("stock_count"), 0))
        if cash >= 0.25 - 1e-9 and stock_count > 8:
            violations.append("main_cash_ge_25pct_requires_stock_count_le_8")
        if cash >= 0.20 - 1e-9 and stock_count > 12:
            violations.append("main_cash_ge_20pct_requires_stock_count_le_12")
        if cash >= 0.15 - 1e-9 and stock_count > 15:
            violations.append("main_cash_ge_15pct_requires_stock_count_le_15")
    else:
        # Single-sector / single-name concentration discipline. A book like
        # LRCX 50 / AMAT 25 / SNDK 25 must not pass silently before broker
        # MDD evidence exists for that exact shape.
        if safe_float(shape.get("max_stock_weight")) > CONCENTRATED_MAX_SINGLE_NAME_WEIGHT + 1e-9:
            violations.append("concentrated_single_name_weight_gt_40pct")
        if safe_float(shape.get("max_industry_group_weight")) > CONCENTRATED_MAX_INDUSTRY_GROUP_WEIGHT + 1e-9:
            violations.append("concentrated_industry_group_weight_gt_60pct")
    return violations


def structure_check_row(check_name: str, shape: dict[str, Any], baseline_book: Path | None) -> dict[str, Any] | None:
    if not shape.get("exists") or not shape.get("row_count"):
        return None
    violations = shape_violations(shape)
    baseline_violations: list[str] = []
    if baseline_book is not None:
        baseline_shape = target_book_shape(baseline_book, str(shape.get("portfolio")))
        baseline_violations = shape_violations(baseline_shape)
    new_violations = [v for v in violations if v not in baseline_violations]
    preexisting = [v for v in violations if v in baseline_violations]
    # Violations inherited unchanged from the baseline book stay visible but do
    # not hard-fail PR-cadence runs: the PR did not introduce them, and failing
    # every unrelated PR until the production book changes only trains people
    # to override the guard.
    if new_violations:
        severity = "error"
    elif preexisting:
        severity = "warn"
    else:
        severity = "ok"
    if shape.get("portfolio") == "main":
        shape_detail = (
            f"cash={safe_float(shape.get('cash_weight')):.2%}; "
            f"stock_count={int(safe_float(shape.get('stock_count'), 0))}; "
            f"crisis_state={shape.get('crisis_state') or 'unknown'}"
        )
    else:
        shape_detail = (
            f"max_name={shape.get('max_stock_weight_ticker')}@{safe_float(shape.get('max_stock_weight')):.2%}; "
            f"max_industry_group={shape.get('max_industry_group')}@{safe_float(shape.get('max_industry_group_weight')):.2%}"
        )
    return {
        "check": check_name,
        "passed": not violations,
        "severity": severity,
        "detail": (
            f"latest_date={shape.get('latest_rebalance_date')}; {shape_detail}; "
            f"violations={violations}; preexisting_in_baseline={preexisting}"
        ),
    }


def target_structure_checks(latest_run: Path, baseline_books: dict[str, Path | None] | None = None) -> list[dict[str, Any]]:
    baseline_books = baseline_books or {}
    out: list[dict[str, Any]] = []
    main_row = structure_check_row(
        "main_cash_position_count_contract",
        latest_target_book_shape(latest_run, "main"),
        baseline_books.get("main"),
    )
    if main_row:
        out.append(main_row)
    concentrated_row = structure_check_row(
        "concentrated_concentration_contract",
        latest_target_book_shape(latest_run, "concentrated"),
        baseline_books.get("concentrated"),
    )
    if concentrated_row:
        out.append(concentrated_row)
    return out


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
    metric_source = metrics.get("_metric_source", "legacy_weight_backtest")
    official_source = metric_source == "broker_ledger_next_close" and bool(metrics.get("valid_for_production", False))
    cagr = metric(metrics, "cagr", "strategy_cagr")
    max_dd = metric(metrics, "max_dd")
    sharpe = metric(metrics, "sharpe")
    turnover = metric(metrics, "avg_turnover_monthly", default=0.0)
    cagr_gap = cagr_target - cagr
    maxdd_gap = max_dd_target - max_dd
    cagr_pass = official_source and cagr >= cagr_target
    max_dd_pass = official_source and max_dd >= max_dd_target
    return {
        "portfolio": name,
        "metric_source": metric_source,
        "official_source_pass": official_source,
        "cagr": cagr,
        "cagr_target": cagr_target,
        "cagr_pass": cagr_pass,
        "cagr_gap_pp": pp(max(0.0, cagr_gap)),
        "max_dd": max_dd,
        "max_dd_target": max_dd_target,
        "max_dd_pass": max_dd_pass,
        "max_dd_improvement_needed_pp": pp(max(0.0, maxdd_gap)),
        "sharpe": sharpe,
        "avg_turnover_monthly": turnover,
        "target_pass": cagr_pass and max_dd_pass,
    }


def write_target_gap_csv(path: Path, statuses: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "portfolio",
        "metric_source",
        "official_source_pass",
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
        out["valid_for_production"] = False
        out["official_metric_required"] = "broker_ledger_next_close"
        out["DO_NOT_USE_FOR_PRODUCTION"] = True
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
        "data_readiness": read_json(latest_run / "data_readiness" / "summary.json")
        or read_json(REPO_ROOT / "outputs" / "data_readiness" / "summary.json"),
        "dataset_coverage": read_json(latest_run / "reports" / "dataset_coverage_audit.json")
        or read_json(REPO_ROOT / "outputs" / "reports" / "dataset_coverage_audit.json"),
        "sec_enriched_candidate": read_json(latest_run / "sec_enriched_candidate_replay" / "summary.json")
        or read_json(REPO_ROOT / "outputs" / "sec_enriched_candidate_replay" / "summary.json"),
        "alphaops_vnext": read_json(latest_run / "alphaops_vnext" / "summary.json")
        or read_json(REPO_ROOT / "outputs" / "alphaops_vnext" / "summary.json"),
        "production_activation": read_json(latest_run / "alphaops_vnext" / "production_activation.json")
        or read_json(REPO_ROOT / "outputs" / "alphaops_vnext" / "production_activation.json"),
        "sec_restore_manifest": read_json(latest_run / "full_rebuild_logs" / "sec_evidence_restore_manifest.json")
        or read_json(REPO_ROOT / "outputs" / "full_rebuild_logs" / "sec_evidence_restore_manifest.json"),
        "theme_leadership": read_json(latest_run / "theme_leadership_tape" / "summary.json")
        or read_json(REPO_ROOT / "outputs" / "theme_leadership_tape" / "summary.json"),
        "macro_circuit_main": read_json(latest_run / "macro_circuit_filter" / "main" / "diagnostics.json")
        or read_json(REPO_ROOT / "outputs" / "macro_circuit_filter" / "main" / "diagnostics.json"),
        "macro_circuit_concentrated": read_json(latest_run / "macro_circuit_filter" / "concentrated" / "diagnostics.json")
        or read_json(REPO_ROOT / "outputs" / "macro_circuit_filter" / "concentrated" / "diagnostics.json"),
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
        allowed_lag_days = 7 if summary.get("target_book_role") == "operating_target_book" else 0
        date_gap_days = (end_dt.date() - max_dt.date()).days if max_dt and end_dt else None
        passed = bool(max_dt and end_dt and date_gap_days is not None and date_gap_days <= allowed_lag_days)
        checks.append(
            {
                "check": f"{portfolio}_target_book_reaches_broker_end",
                "passed": passed,
                "severity": "error" if not passed else "ok",
                "detail": f"selected_role={summary.get('target_book_role')}; target_book_max={summary.get('max_date')}; broker_end={broker_end.get(portfolio)}; date_gap_days={date_gap_days}; allowed_lag_days={allowed_lag_days}; rows={summary.get('row_count')}; path={summary.get('path')}",
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
    operating_filter = latest_target_filter(latest_run / "reports" / "operating_concentrated_target_book.csv")
    latest_conc_rows = read_csv_rows(latest_run / "concentrated_portfolio_latest.csv")
    latest_conc = latest_conc_rows[0] if latest_conc_rows else {}
    metric_n = filter_value(metric_filter.get("target_stock_names"))
    latest_n = filter_value(operating_filter.get("target_stock_names") or latest_conc.get("target_stock_names"))
    metric_mode = filter_value(metric_filter.get("weighting_mode"))
    latest_mode = filter_value(operating_filter.get("weighting_mode") or latest_conc.get("weighting_mode"))
    metric_target_book = str(concentrated_metrics.get("target_book") or "").replace("\\", "/")
    uses_operating = "operating_concentrated_target_book.csv" in metric_target_book
    filter_match = bool(
        (uses_operating and latest_n)
        or (metric_n and latest_n and metric_n == latest_n and (not metric_mode or metric_mode == latest_mode))
    )
    checks.append(
        {
            "check": "concentrated_replay_filter_matches_latest_target",
            "passed": filter_match,
            "severity": "warn" if not filter_match else "ok",
            "detail": f"broker_filter_n={metric_n or ('operating_book' if uses_operating else 'missing')}; latest_operating_target_n={latest_n or 'missing'}; broker_mode={metric_mode or ('operating_book' if uses_operating else 'missing')}; latest_mode={latest_mode or 'missing'}",
        }
    )
    return checks


def error_checks(
    inputs: dict[str, Any],
    latest_run: Path,
    require_latest_artifacts: bool = False,
    baseline_books: dict[str, Path | None] | None = None,
) -> list[dict[str, Any]]:
    def rel(path: Path) -> str:
        try:
            return path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(path)

    latest_artifact_severity = "error" if require_latest_artifacts else "warn"
    checks = [
        ("main_metrics_available", bool(inputs["main_metrics"]), rel(latest_run / "broker_replay" / "main" / "metrics.json")),
        ("concentrated_metrics_available", bool(inputs["concentrated_metrics"]), rel(latest_run / "broker_replay" / "concentrated" / "metrics.json")),
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
    data_readiness = inputs.get("data_readiness") or {}
    out.append(
        {
            "check": "data_readiness_audit_available",
            "passed": bool(data_readiness),
            "severity": "warn" if not data_readiness else "ok",
            "detail": "outputs/data_readiness/summary.json",
        }
    )
    if data_readiness:
        ready_for_fullrun = bool(data_readiness.get("ready_for_fullrun"))
        ready_for_policy_replay = bool(data_readiness.get("ready_for_policy_replay"))
        blockers = data_readiness.get("blockers") or []
        policy_blockers = data_readiness.get("policy_replay_blockers") or []
        warnings = data_readiness.get("warnings") or []
        ready_for_production_replay = ready_for_fullrun or ready_for_policy_replay
        out.append(
            {
                "check": "data_readiness_ready_for_production_replay",
                "passed": ready_for_production_replay,
                "severity": "error" if not ready_for_production_replay else "ok",
                "detail": (
                    f"status={data_readiness.get('status')}; ready_for_fullrun={ready_for_fullrun}; "
                    f"ready_for_policy_replay={ready_for_policy_replay}; blockers={blockers}; "
                    f"policy_replay_blockers={policy_blockers}; warnings={warnings}"
                ),
            }
        )
    dataset_coverage = inputs.get("dataset_coverage") or {}
    out.append(
        {
            "check": "dataset_coverage_audit_available",
            "passed": bool(dataset_coverage),
            "severity": "warn" if not dataset_coverage else "ok",
            "detail": "outputs/reports/dataset_coverage_audit.json",
        }
    )
    if dataset_coverage:
        sec_present = bool(dataset_coverage.get("sec_enriched_candidate_present"))
        sec_summary = dataset_coverage.get("sec_enriched_evidence_summary") or {}
        evidence_rows = int(safe_float(sec_summary.get("rows_with_smart_money_evidence"), 0))
        out.append(
            {
                "check": "sec_enriched_candidate_materialized_for_audit",
                "passed": sec_present or evidence_rows == 0,
                "severity": "error" if evidence_rows > 0 and not sec_present else "ok",
                "detail": f"sec_enriched_candidate_present={sec_present}; rows_with_smart_money_evidence={evidence_rows}",
            }
        )
    sec_enriched = inputs.get("sec_enriched_candidate") or {}
    alphaops = inputs.get("alphaops_vnext") or {}
    activation = inputs.get("production_activation") or {}
    production_policy = str(activation.get("production_policy") or alphaops.get("production_policy") or "")
    alphaops_candidate = str(alphaops.get("candidate_book") or "").replace("\\", "/")
    sec_rows = int(safe_float(sec_enriched.get("rows_with_smart_money_evidence"), 0))
    if production_policy == "alphaops_vnext_production" and sec_rows > 0:
        uses_enriched = "sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv" in alphaops_candidate
        out.append(
            {
                "check": "alphaops_vnext_uses_sec_enriched_candidate_book",
                "passed": uses_enriched,
                "severity": "error" if not uses_enriched else "ok",
                "detail": f"candidate_book={alphaops_candidate or 'missing'}; rows_with_smart_money_evidence={sec_rows}",
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
    out.extend(data_quality_contract_checks(inputs))
    out.extend(target_structure_checks(latest_run, baseline_books))
    return out


def data_quality_contract_checks(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    activation = inputs.get("production_activation") or {}
    alphaops = inputs.get("alphaops_vnext") or {}
    production_policy = str(activation.get("production_policy") or alphaops.get("production_policy") or "")
    if production_policy == "alphaops_vnext_production":
        flags = {
            "production_applied": activation.get("production_applied"),
            "sidecar_only": activation.get("sidecar_only"),
            "sidecar_applied_to_production": activation.get("sidecar_applied_to_production"),
            "current_holdings_source": activation.get("current_holdings_source"),
        }
        flags_present = any(value is not None for value in flags.values())
        flags_correct = (
            bool(flags.get("production_applied"))
            and flags.get("sidecar_only") is False
            and bool(flags.get("sidecar_applied_to_production"))
            and flags.get("current_holdings_source") == "alphaops_vnext_policy_target_book"
        )
        checks.append(
            {
                "check": "alphaops_vnext_production_flags_correct",
                "passed": flags_correct if flags_present else False,
                "severity": "error" if flags_present and not flags_correct else ("warn" if not flags_present else "ok"),
                "detail": json.dumps(flags, sort_keys=True),
            }
        )
    for portfolio in ("main", "concentrated"):
        metrics = inputs.get(f"{portfolio}_metrics") or {}
        source = metrics.get("_metric_source")
        valid = bool(metrics.get("valid_for_production", False))
        checks.append(
            {
                "check": f"{portfolio}_official_broker_metrics_valid_for_production",
                "passed": source == "broker_ledger_next_close" and valid,
                "severity": "error" if metrics and (source != "broker_ledger_next_close" or not valid) else ("warn" if not metrics else "ok"),
                "detail": f"metric_source={source or 'missing'}; valid_for_production={valid}; fill_mode={metrics.get('fill_mode') or 'missing'}",
            }
        )
    restore_manifest = inputs.get("sec_restore_manifest") or {}
    restored = restore_manifest.get("restored") or []
    checks.append(
        {
            "check": "sec_drive_restore_manifest_available",
            "passed": bool(restore_manifest),
            "severity": "warn" if not restore_manifest else "ok",
            "detail": f"restored_count={len(restored)}; missing={restore_manifest.get('missing') or []}; errors={restore_manifest.get('errors') or []}",
        }
    )
    theme = inputs.get("theme_leadership") or {}
    checks.append(
        {
            "check": "theme_leadership_tape_available",
            "passed": bool(theme),
            "severity": "warn" if not theme else "ok",
            "detail": f"top_theme={theme.get('top_theme') or 'missing'}; top_theme_state={theme.get('top_theme_state') or 'missing'}",
        }
    )
    macro_main = inputs.get("macro_circuit_main") or {}
    macro_concentrated = inputs.get("macro_circuit_concentrated") or {}
    checks.append(
        {
            "check": "macro_circuit_diagnostics_available",
            "passed": bool(macro_main) and bool(macro_concentrated),
            "severity": "warn" if not (macro_main and macro_concentrated) else "ok",
            "detail": f"main_status={macro_main.get('status') or 'missing'}; concentrated_status={macro_concentrated.get('status') or 'missing'}",
        }
    )
    data_readiness = inputs.get("data_readiness") or {}
    feature_coverage = data_readiness.get("feature_source_coverage") or {}
    checks.append(
        {
            "check": "feature_source_coverage_available",
            "passed": bool(feature_coverage),
            "severity": "warn" if not feature_coverage else "ok",
            "detail": "outputs/data_readiness/summary.json::feature_source_coverage",
        }
    )
    if feature_coverage:
        overall = feature_coverage.get("overall") or {}
        future_rows = int(safe_float(overall.get("pit_future_available_from_rows"), 0))
        available_column_count = int(safe_float(overall.get("available_from_column_count"), 0))
        checks.append(
            {
                "check": "feature_source_coverage_pit_available_from_clean",
                "passed": future_rows == 0,
                "severity": "error" if future_rows else "ok",
                "detail": f"pit_future_available_from_rows={future_rows}; available_from_column_count={available_column_count}",
            }
        )
        missing_groups: list[str] = []
        for portfolio, book in (feature_coverage.get("books") or {}).items():
            for group_name, category in (book.get("categories") or {}).items():
                if not (category.get("present_columns") or []):
                    missing_groups.append(f"{portfolio}:{group_name}")
        checks.append(
            {
                "check": "feature_source_groups_present_for_target_books",
                "passed": not missing_groups,
                "severity": "warn" if missing_groups else "ok",
                "detail": f"missing_groups={missing_groups}",
            }
        )
    return checks


def data_quality_update_plan(inputs: dict[str, Any], latest_run: Path) -> dict[str, Any]:
    data_readiness = inputs.get("data_readiness") or {}
    dataset_coverage = inputs.get("dataset_coverage") or {}
    sec_enriched = inputs.get("sec_enriched_candidate") or {}
    restore_manifest = inputs.get("sec_restore_manifest") or {}
    activation = inputs.get("production_activation") or {}
    alphaops = inputs.get("alphaops_vnext") or {}
    feature_coverage = data_readiness.get("feature_source_coverage") or {}
    feature_overall = feature_coverage.get("overall") or {}
    return {
        "metric_contract": {
            "official_source": "broker_ledger_next_close",
            "main_target": PORTFOLIO_GOAL_TARGETS["main"],
            "concentrated_target": PORTFOLIO_GOAL_TARGETS["concentrated"],
            "legacy_weight_metrics_allowed_for": "research_hints_only",
        },
        "latest_run": str(latest_run),
        "readiness": {
            "ready_for_fullrun": bool(data_readiness.get("ready_for_fullrun")),
            "ready_for_policy_replay": bool(data_readiness.get("ready_for_policy_replay")),
            "blockers": data_readiness.get("blockers") or [],
            "policy_replay_blockers": data_readiness.get("policy_replay_blockers") or [],
            "warnings": data_readiness.get("warnings") or [],
        },
        "coverage": {
            "sec_enriched_candidate_present": bool(dataset_coverage.get("sec_enriched_candidate_present")),
            "rows_with_smart_money_evidence": int(
                safe_float((dataset_coverage.get("sec_enriched_evidence_summary") or {}).get("rows_with_smart_money_evidence"), 0)
            ),
            "sec_enriched_rows_with_smart_money_evidence": int(safe_float(sec_enriched.get("rows_with_smart_money_evidence"), 0)),
            "alphaops_candidate_book": str(alphaops.get("candidate_book") or ""),
            "production_policy": activation.get("production_policy") or alphaops.get("production_policy"),
        },
        "feature_source_coverage": {
            "available": bool(feature_coverage),
            "status": feature_coverage.get("status"),
            "pit_future_available_from_rows": int(safe_float(feature_overall.get("pit_future_available_from_rows"), 0)),
            "available_from_column_count": int(safe_float(feature_overall.get("available_from_column_count"), 0)),
            "missing_feature_groups_by_portfolio": feature_overall.get("missing_feature_groups_by_portfolio") or {},
        },
        "large_data_restore": {
            "manifest_available": bool(restore_manifest),
            "restored": restore_manifest.get("restored") or [],
            "missing": restore_manifest.get("missing") or [],
            "errors": restore_manifest.get("errors") or [],
            "must_remain_out_of_git": [
                "data_raw/free/sec/companyfacts.zip",
                "data_pit/sec/*.parquet",
                "data_pit/etf_holdings/*.parquet",
                "data_pit/macro/*",
                "cache_prices/*",
                "full replay artifacts",
            ],
        },
        "update_cadence": {
            "prices": "daily_after_close",
            "macro": "daily_after_close_with_release_lag",
            "form4": "daily_or_next_available",
            "13f": "quarterly_after_public_filing_availability",
            "etf_holdings": "weekly_or_provider_snapshot",
            "universe": "monthly_snapshot_plus_delisting_and_symbol_map_audit",
            "theme_leadership": "daily_tape_weekly_taxonomy_review",
            "full_rebuild": "manual_only_after_data_schema_or_feature_generation_changes",
        },
        "pit_leakage_rules": [
            "Every external evidence row must have available_from or latest_available_from before it can boost scoring.",
            "SEC 13F must use public filing accepted/available time, never report_period as availability.",
            "Macro release-lagged series must preserve publication lag and must not be backfilled into earlier rebalance dates.",
            "ETF holdings are latest/discovery aids unless a point-in-time holding snapshot exists.",
            "Missing evidence is neutral: no boost, no standalone penalty, and no buy rule.",
        ],
        "next_data_work": [
            "Add a full-period feature-store coverage report by month, source, and portfolio target book.",
            "Track universe membership, delistings, ADR eligibility, and symbol changes as monthly PIT snapshots.",
            "Add macro regime features for QQQ-vs-SPY damage, credit/rate/liquidity stress, breadth, and theme rotation before changing production sizing.",
            "Run broker-trade attribution first, then promote only PIT-safe rules that improve official broker MDD without losing target CAGR.",
        ],
    }


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


def cash_trap_guard(statuses: list[dict[str, Any]], inputs: dict[str, Any], latest_run: Path) -> list[dict[str, Any]]:
    """Flag high-cash portfolios that still miss the drawdown gate.

    This is a diagnosis guard, not a production blocker by itself. It prevents
    the common misread that more cash automatically means better MDD defense.
    """

    out: list[dict[str, Any]] = []
    status_by_portfolio = {str(row.get("portfolio")): row for row in statuses}
    thresholds = {"main": 0.20, "concentrated": 0.25}
    for portfolio in ("main", "concentrated"):
        status = status_by_portfolio.get(portfolio, {})
        metrics = inputs.get(f"{portfolio}_metrics", {}) or {}
        account_state = read_json(latest_run / "broker_replay" / portfolio / "account_state_latest.json")
        avg_cash = metric(metrics, "avg_cash_weight", default=0.0)
        latest_cash = metric(account_state, "cash_weight", default=0.0)
        cagr_gap = max(0.0, safe_float(status.get("cagr_target"), 0.0) - safe_float(status.get("cagr"), 0.0))
        dd_gap = max(0.0, safe_float(status.get("max_dd_target"), 0.0) - safe_float(status.get("max_dd"), 0.0))
        avg_cash_high = avg_cash >= thresholds[portfolio]
        latest_cash_high = latest_cash >= 0.50
        dd_not_defended = dd_gap >= 0.05
        reasons: list[str] = []
        if avg_cash_high and dd_not_defended:
            reasons.append("avg_cash_high_without_mdd_target_pass")
        if avg_cash_high and cagr_gap > 0:
            reasons.append("cash_drag_with_cagr_gap")
        if latest_cash_high:
            reasons.append("latest_cash_above_50pct_requires_crisis_state_review")
        out.append(
            {
                "portfolio": portfolio,
                "severity": "warn" if reasons else "ok",
                "cash_trap": bool(reasons),
                "avg_cash_weight": avg_cash,
                "latest_cash_weight": latest_cash,
                "cagr_gap_pp": pp(cagr_gap),
                "max_dd_gap_pp": pp(dd_gap),
                "reasons": reasons,
                "diagnosis": "cash is defensive only when MDD gap improves without unacceptable CAGR/reentry drag",
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
            "role": "Refresh substrate data, PIT freshness, universe, theme, and coverage diagnostics before deeper rebuilds.",
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
            "next_change_needed": "Use only after data-quality and PIT coverage pass; broker replay must confirm any discovered policy.",
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
                "Run data quality and PIT coverage checks before interpreting CAGR/MDD.",
                "Use broker-trade attribution to separate data gaps from policy errors across the full period.",
                "Improve theme leadership and macro regime features before adding broad cash or sizing rules.",
                "Promote only reversible PIT-safe rules that improve official broker MDD without losing target CAGR.",
            ],
        },
    }


def render_report(
    main_status: dict[str, Any],
    concentrated_status: dict[str, Any],
    candidates: list[dict[str, Any]],
    goal_candidates: list[dict[str, Any]],
    cash_trap: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    plan: dict[str, Any],
    data_quality: dict[str, Any],
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

    lines.extend(["## Cash Trap Guard", ""])
    for row in cash_trap:
        reasons = ", ".join(row.get("reasons") or []) or "none"
        lines.append(
            "- `{portfolio}`: severity=`{severity}`, avg_cash={avg_cash:.2%}, latest_cash={latest_cash:.2%}, reasons={reasons}".format(
                portfolio=row.get("portfolio"),
                severity=row.get("severity"),
                avg_cash=safe_float(row.get("avg_cash_weight"), 0.0),
                latest_cash=safe_float(row.get("latest_cash_weight"), 0.0),
                reasons=reasons,
            )
        )
    lines.append("")

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

    lines.extend(["## Data Quality Update Plan", ""])
    readiness = data_quality.get("readiness") or {}
    coverage = data_quality.get("coverage") or {}
    restore = data_quality.get("large_data_restore") or {}
    lines.append(
        "- Readiness: ready_for_fullrun=`{full}`, ready_for_policy_replay=`{policy}`, blockers={blockers}, policy_blockers={policy_blockers}".format(
            full=str(readiness.get("ready_for_fullrun")).lower(),
            policy=str(readiness.get("ready_for_policy_replay")).lower(),
            blockers=readiness.get("blockers") or [],
            policy_blockers=readiness.get("policy_replay_blockers") or [],
        )
    )
    lines.append(
        "- Coverage: sec_enriched_candidate_present=`{present}`, smart_money_rows={rows}, candidate_book=`{book}`".format(
            present=str(coverage.get("sec_enriched_candidate_present")).lower(),
            rows=coverage.get("rows_with_smart_money_evidence"),
            book=coverage.get("alphaops_candidate_book") or "missing",
        )
    )
    lines.append(
        "- Large data restore: manifest_available=`{available}`, restored={restored}, missing={missing}, errors={errors}".format(
            available=str(restore.get("manifest_available")).lower(),
            restored=restore.get("restored") or [],
            missing=restore.get("missing") or [],
            errors=restore.get("errors") or [],
        )
    )
    lines.append("- PIT rules:")
    for rule in data_quality.get("pit_leakage_rules") or []:
        lines.append(f"  - {rule}")
    lines.append("- Next data work:")
    for item in data_quality.get("next_data_work") or []:
        lines.append(f"  - {item}")
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
    baseline_books: dict[str, Path | None] = {}
    if getattr(args, "baseline_main_target_book", None):
        baseline_books["main"] = repo_path(args.baseline_main_target_book)
    if getattr(args, "baseline_concentrated_target_book", None):
        baseline_books["concentrated"] = repo_path(args.baseline_concentrated_target_book)
    checks = error_checks(
        inputs,
        latest_run,
        require_latest_artifacts=bool(getattr(args, "require_latest_artifacts", False) or args.strict_targets),
        baseline_books=baseline_books,
    )
    candidates = top_research_candidates(inputs["experiment_summary"], inputs.get("orchestrator_replay"))
    goal_candidates = goal_search_candidates(inputs.get("goal_search"))
    cash_trap = cash_trap_guard(statuses, inputs, latest_run)
    plan = automation_plan(inputs, targets_pass)
    data_quality = data_quality_update_plan(inputs, latest_run)
    hard_errors = [row for row in checks if row["severity"] == "error" and not row["passed"]]
    warning_count = sum(1 for row in checks if row["severity"] == "warn" and not row["passed"])
    overall_status = "target_pass" if targets_pass and not hard_errors else "blocked"

    payload = {
        "overall_status": overall_status,
        "strict_targets": args.strict_targets,
        "enforce_contracts": bool(getattr(args, "enforce_contracts", False)),
        "baseline_books": {key: str(value) for key, value in baseline_books.items()},
        "targets_pass": targets_pass,
        "hard_error_count": len(hard_errors),
        "warning_count": int(warning_count),
        "portfolio_status": statuses,
        "top_research_candidates": candidates,
        "goal_search_candidates": goal_candidates,
        "cash_trap_guard": cash_trap,
        "error_checks": checks,
        "data_quality_update_plan": data_quality,
        "automation_plan": plan,
    }

    write_json(output_dir / "target_gap.json", payload)
    write_target_gap_csv(output_dir / "target_gap.csv", statuses)
    write_json(output_dir / "error_check.json", {"checks": checks, "hard_error_count": len(hard_errors)})
    write_json(output_dir / "automation_plan.json", plan)
    write_json(output_dir / "data_quality_update_plan.json", data_quality)
    write_text(output_dir / "automation_plan.md", render_automation_plan(plan))
    report = render_report(
        main_status,
        concentrated_status,
        candidates,
        goal_candidates,
        cash_trap,
        checks,
        plan,
        data_quality,
        args.strict_targets,
    )
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
    parser.add_argument(
        "--enforce-contracts",
        action="store_true",
        help=(
            "Fail on hard contract errors (book shape, concentration) without also "
            "failing on unmet aspirational CAGR/MDD goals. Intended for PR cadence: "
            "combine with --baseline-*-target-book so violations inherited from the "
            "base ref are reported as warnings instead of failing unrelated PRs."
        ),
    )
    parser.add_argument(
        "--baseline-main-target-book",
        default="",
        help="Base-ref operating_main_target_book.csv; shape violations also present there are downgraded to warnings.",
    )
    parser.add_argument(
        "--baseline-concentrated-target-book",
        default="",
        help="Base-ref operating_concentrated_target_book.csv; concentration violations also present there are downgraded to warnings.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.strict_targets and not result["targets_pass"]:
        return 2
    hard_errors = [row for row in result["error_checks"] if row["severity"] == "error" and not row["passed"]]
    if (args.strict_targets or args.require_latest_artifacts or args.enforce_contracts) and hard_errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
