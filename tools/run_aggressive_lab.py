#!/usr/bin/env python3
"""Run isolated AlphaOps aggressive lab experiments.

The runner is intentionally report-only until an experiment has a real
historical strategy adapter. It normalizes existing artifacts into the lab
contract and keeps production defaults untouched.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aggressive_lab_common import (
    ROOT,
    load_yaml,
    read_csv_rows,
    read_json,
    safe_float,
    write_csv_rows,
    write_json,
)
from experiment_gate_eval import evaluate_discovery, render_markdown as render_gate_markdown


DEFAULT_MATRIX = "research/aggressive_lab_202605/experiment_matrix.yaml"
DEFAULT_GATES = "research/aggressive_lab_202605/discovery_gates.yaml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _find_experiment(matrix: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    for exp in matrix.get("experiments", []) or []:
        if exp.get("id") == experiment_id:
            return exp
    raise KeyError(f"experiment not found in matrix: {experiment_id}")


def _copy_text_if_exists(src: Path, dst: Path, status: list[dict[str, Any]]) -> bool:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        status.append({"artifact": dst.name, "source": _rel(src), "status": "copied"})
        return True
    status.append({"artifact": dst.name, "source": _rel(src), "status": "missing"})
    return False


def _first_existing(base: Path, rels: list[str]) -> Path | None:
    for rel in rels:
        path = base / rel
        if path.exists():
            return path
    return None


def _write_unavailable_csv(path: Path, artifact_name: str, reason: str) -> None:
    write_csv_rows(
        path,
        [{"artifact": artifact_name, "status": "not_available", "reason": reason}],
        fieldnames=["artifact", "status", "reason"],
    )


def _main_metrics_from_registry(registry: dict[str, Any]) -> dict[str, Any]:
    current = registry.get("current_run", {}) if isinstance(registry, dict) else {}
    metrics = dict(current.get("metrics", {}) or {})
    conc = dict(current.get("concentrated_metrics", {}) or {})
    diagnostics = dict(current.get("diagnostics", {}) or {})
    out = {
        "experiment_id": "E0_baseline_latest",
        "status": "completed",
        "control": True,
        "artifact_mode": "baseline_registry_normalized",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cagr": metrics.get("cagr"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "max_dd": metrics.get("max_dd"),
        "avg_turnover_monthly": metrics.get("avg_turnover_monthly"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "avg_stock_names": metrics.get("avg_stock_names"),
        "months": metrics.get("months"),
        "ending_capital_usd": metrics.get("ending_capital_usd"),
        "main": metrics,
        "concentrated": conc,
        "diagnostics": diagnostics,
        "run_identity": current.get("run_identity", {}),
    }
    return out


def _load_baseline_metrics(baseline_run: Path) -> tuple[dict[str, Any], Path]:
    registry_path = baseline_run / "reports" / "baseline_registry.json"
    registry = read_json(registry_path, {}) or {}
    metrics = _main_metrics_from_registry(registry)
    metrics["source_run"] = _rel(baseline_run)
    return metrics, registry_path


def _ensure_baseline_metrics_snapshot(matrix: dict[str, Any], baseline_run: Path, outputs_root: Path) -> Path:
    path = outputs_root / "E0_baseline_latest" / "metrics.json"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics, _ = _load_baseline_metrics(baseline_run)
    metrics["matrix_version"] = matrix.get("version")
    write_json(path, metrics)
    return path


def _trade_journal_summary(src_run: Path, out_dir: Path, status: list[dict[str, Any]]) -> None:
    for rel in [
        "trade_journal/insights/summary.md",
        "trade_journal/trade_journal/insights/summary.md",
    ]:
        src = src_run / rel
        if _copy_text_if_exists(src, out_dir / "trade_journal_summary.md", status):
            return
    (out_dir / "trade_journal_summary.md").write_text(
        "# Trade Journal Summary\n\nNo trade journal summary artifact found for this baseline run.\n",
        encoding="utf-8",
    )


def _write_turnover(src_run: Path, out_dir: Path, status: list[dict[str, Any]]) -> None:
    src = src_run / "reports" / "backtest_window_comparison.csv"
    rows = read_csv_rows(src)
    if rows:
        fields = [
            "window_years",
            "strategy_cagr",
            "sharpe",
            "max_dd",
            "avg_turnover_monthly",
            "avg_cash_weight",
            "avg_stock_names",
            "months",
            "status",
        ]
        write_csv_rows(out_dir / "turnover.csv", [{k: row.get(k, "") for k in fields} for row in rows], fields)
        status.append({"artifact": "turnover.csv", "source": _rel(src), "status": "derived"})
    else:
        _write_unavailable_csv(out_dir / "turnover.csv", "turnover.csv", "backtest_window_comparison.csv missing")
        status.append({"artifact": "turnover.csv", "source": _rel(src), "status": "missing"})


def _write_stress_windows(src_run: Path, out_dir: Path, stress_windows: list[str], status: list[dict[str, Any]]) -> None:
    # Existing cloud artifacts do not include monthly equity in this branch.
    # Preserve the contract while making the limitation explicit.
    rows = [
        {
            "stress_window": name,
            "status": "needs_monthly_equity_curve",
            "reason": "baseline cloud artifact does not include equity_curve.csv",
        }
        for name in stress_windows
    ]
    write_csv_rows(out_dir / "stress_windows.csv", rows, ["stress_window", "status", "reason"])
    status.append({"artifact": "stress_windows.csv", "source": _rel(src_run), "status": "limitation_logged"})


def _write_report_only_required_outputs(
    out_dir: Path,
    stress_windows: list[str],
    status: list[dict[str, Any]],
    reason: str,
) -> None:
    for name in ["equity_curve.csv", "monthly_allocations.csv", "sleeve_returns.csv", "turnover.csv"]:
        _write_unavailable_csv(out_dir / name, name, reason)
        status.append({"artifact": name, "source": "", "status": "report_only_placeholder"})
    rows = [
        {
            "stress_window": name,
            "status": "not_backtested",
            "reason": reason,
        }
        for name in stress_windows
    ]
    write_csv_rows(out_dir / "stress_windows.csv", rows, ["stress_window", "status", "reason"])
    status.append({"artifact": "stress_windows.csv", "source": "", "status": "report_only_placeholder"})


def _write_monthly_allocations(src_run: Path, out_dir: Path, status: list[dict[str, Any]]) -> None:
    src = src_run / "reports" / "global_alpha_sleeve_audit_by_month.csv"
    if src.exists():
        shutil.copy2(src, out_dir / "monthly_allocations.csv")
        status.append({"artifact": "monthly_allocations.csv", "source": _rel(src), "status": "copied_proxy"})
    else:
        _write_unavailable_csv(out_dir / "monthly_allocations.csv", "monthly_allocations.csv", "monthly audit missing")
        status.append({"artifact": "monthly_allocations.csv", "source": _rel(src), "status": "missing"})


def _write_sleeve_returns(out_dir: Path, status: list[dict[str, Any]]) -> None:
    _write_unavailable_csv(
        out_dir / "sleeve_returns.csv",
        "sleeve_returns.csv",
        "baseline artifacts do not include sleeve return series; future runner must generate it",
    )
    status.append({"artifact": "sleeve_returns.csv", "source": "", "status": "limitation_logged"})


def _write_equity_curve(src_run: Path, out_dir: Path, status: list[dict[str, Any]]) -> None:
    for rel in ["equity_curve.csv", "outputs/equity_curve.csv"]:
        src = src_run / rel
        if src.exists():
            shutil.copy2(src, out_dir / "equity_curve.csv")
            status.append({"artifact": "equity_curve.csv", "source": _rel(src), "status": "copied"})
            return
    _write_unavailable_csv(
        out_dir / "equity_curve.csv",
        "equity_curve.csv",
        "baseline cloud artifact does not include equity_curve.csv",
    )
    status.append({"artifact": "equity_curve.csv", "source": _rel(src_run), "status": "limitation_logged"})


def _render_experiment_report(metrics: dict[str, Any], artifact_status: list[dict[str, Any]], exp: dict[str, Any]) -> str:
    lines = [
        "# Aggressive Lab Experiment Report",
        "",
        f"- Experiment: `{metrics.get('experiment_id')}`",
        f"- Status: `{metrics.get('status')}`",
        f"- Category: `{exp.get('category')}`",
        f"- Description: {exp.get('description')}",
        f"- Control: `{metrics.get('control')}`",
        "",
        "## Main Metrics",
        "",
        f"- CAGR: {metrics.get('cagr')}",
        f"- Sharpe: {metrics.get('sharpe')}",
        f"- MaxDD: {metrics.get('max_dd')}",
        f"- Monthly turnover: {metrics.get('avg_turnover_monthly')}",
        f"- Avg stock names: {metrics.get('avg_stock_names')}",
        "",
        "## Concentrated Metrics",
        "",
    ]
    conc = metrics.get("concentrated") or {}
    lines.extend(
        [
            f"- CAGR: {conc.get('strategy_cagr')}",
            f"- Sharpe: {conc.get('sharpe')}",
            f"- MaxDD: {conc.get('max_dd')}",
            f"- Selected names: {conc.get('selected_names')}",
            "",
            "## Artifact Status",
            "",
            "| Artifact | Source | Status |",
            "| --- | --- | --- |",
        ]
    )
    for row in artifact_status:
        lines.append(f"| `{row.get('artifact')}` | `{row.get('source')}` | `{row.get('status')}` |")
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append(
        "This E0 run normalizes existing baseline artifacts into the aggressive lab output contract. "
        "It does not rerun the production engine and is not a challenger."
    )
    lines.append("")
    return "\n".join(lines)


def _render_report_only_report(
    metrics: dict[str, Any],
    artifact_status: list[dict[str, Any]],
    exp: dict[str, Any],
    interpretation: list[str],
) -> str:
    lines = [
        "# Aggressive Lab Experiment Report",
        "",
        f"- Experiment: `{metrics.get('experiment_id')}`",
        f"- Status: `{metrics.get('status')}`",
        f"- Category: `{exp.get('category')}`",
        f"- Description: {exp.get('description')}",
        f"- Backtest executed: `{metrics.get('backtest_executed')}`",
        f"- Production activation allowed: `{metrics.get('production_activation_allowed')}`",
        "",
        "## Metrics Source",
        "",
        f"- Metric mode: `{metrics.get('metric_mode')}`",
        f"- CAGR: {metrics.get('cagr')}",
        f"- Sharpe: {metrics.get('sharpe')}",
        f"- MaxDD: {metrics.get('max_dd')}",
        f"- Monthly turnover: {metrics.get('avg_turnover_monthly')}",
        "",
        "## Artifact Status",
        "",
        "| Artifact | Source | Status |",
        "| --- | --- | --- |",
    ]
    for row in artifact_status:
        lines.append(f"| `{row.get('artifact')}` | `{row.get('source')}` | `{row.get('status')}` |")
    lines.extend(["", "## Interpretation", ""])
    lines.extend(interpretation)
    lines.append("")
    return "\n".join(lines)


def _ensure_regression_attribution(out_dir: Path) -> None:
    attribution = out_dir / "regression_attribution.md"
    if not attribution.exists():
        metrics = read_json(out_dir / "metrics.json", {}) or {}
        attribution.write_text(
            "# Regression Attribution\n\n"
            f"- Experiment: `{metrics.get('experiment_id', out_dir.name)}`\n"
            f"- Status: `{metrics.get('status')}`\n"
            f"- Metric mode: `{metrics.get('metric_mode')}`\n"
            f"- Backtest executed: `{metrics.get('backtest_executed')}`\n\n"
            "Historical attribution is not available for this experiment unless the adapter generated a full "
            "equity curve and per-period allocations. This file preserves the failure/limitation explicitly.\n",
            encoding="utf-8",
        )


def _write_discovery_gate(out_dir: Path, matrix: dict[str, Any], baseline_run: Path, outputs_root: Path, gates_path: Path) -> None:
    _ensure_regression_attribution(out_dir)
    baseline_path = _ensure_baseline_metrics_snapshot(matrix, baseline_run, outputs_root)
    gate_report = evaluate_discovery(out_dir, baseline_path, gates_path)
    write_json(out_dir / "gate_report.json", gate_report)
    (out_dir / "gate_report.md").write_text(render_gate_markdown(gate_report), encoding="utf-8")


def _write_contract_placeholders(
    out_dir: Path,
    common: dict[str, Any],
    artifact_status: list[dict[str, Any]],
    reason: str,
    skip: set[str] | None = None,
) -> None:
    skip = skip or set()
    for name in ["equity_curve.csv", "monthly_allocations.csv", "sleeve_returns.csv", "turnover.csv"]:
        if name in skip:
            continue
        _write_unavailable_csv(out_dir / name, name, reason)
        artifact_status.append({"artifact": name, "source": "", "status": "report_only_placeholder"})
    if "stress_windows.csv" not in skip:
        rows = [
            {
                "stress_window": name,
                "status": "not_backtested",
                "reason": reason,
            }
            for name in common.get("stress_windows", []) or []
        ]
        write_csv_rows(out_dir / "stress_windows.csv", rows, ["stress_window", "status", "reason"])
        artifact_status.append({"artifact": "stress_windows.csv", "source": "", "status": "report_only_placeholder"})


def _copy_trade_insight_artifacts(baseline_run: Path, out_dir: Path, status: list[dict[str, Any]]) -> None:
    for rel, dst_name in [
        ("trade_journal/insights/ic_matrix.csv", "trade_journal_ic_matrix.csv"),
        ("trade_journal/insights/cluster_winrate.csv", "trade_journal_cluster_winrate.csv"),
        ("trade_journal/insights/proposal_diff.md", "trade_journal_proposal_diff.md"),
    ]:
        src = baseline_run / rel
        if src.exists():
            shutil.copy2(src, out_dir / dst_name)
            status.append({"artifact": dst_name, "source": _rel(src), "status": "copied"})


def _candidate_gate_rows(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, gate in enumerate(candidate.get("gates", []) or [], start=1):
        rows.append(
            {
                "rank": idx,
                "kind": gate.get("kind"),
                "signal": gate.get("signal"),
                "regime": gate.get("regime"),
                "factor": gate.get("factor"),
                "ic": gate.get("ic"),
                "n": gate.get("n"),
                "rationale": gate.get("rationale"),
            }
        )
    return rows


def _load_normalized_weights(path: Path) -> tuple[dict[str, float], dict[str, Any]]:
    rows = read_csv_rows(path)
    weights: dict[str, float] = {}
    skipped = 0
    for row in rows:
        ticker = (row.get("ticker") or row.get("Ticker") or "").strip().upper()
        if not ticker or ticker == "CASH":
            skipped += 1
            continue
        weight = safe_float(row.get("weight"))
        if weight is None:
            weight = safe_float(row.get("target_weight"))
        if weight is None or weight <= 0:
            skipped += 1
            continue
        weights[ticker] = weights.get(ticker, 0.0) + weight
    raw_total = sum(weights.values())
    normalized = {ticker: weight / raw_total for ticker, weight in weights.items()} if raw_total > 0 else {}
    audit = {
        "source": _rel(path),
        "rows": len(rows),
        "valid_positions": len(normalized),
        "skipped_rows": skipped,
        "raw_weight_sum": raw_total,
    }
    return normalized, audit


def _sum_then_cap(
    mandate_weights: dict[str, dict[str, float]],
    capacities: dict[str, float],
    single_name_cap: float,
) -> dict[str, Any]:
    raw: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}
    for mandate, weights in mandate_weights.items():
        capacity = capacities.get(mandate, 0.0)
        if capacity <= 0:
            continue
        for ticker, normalized_weight in weights.items():
            contribution = normalized_weight * capacity
            if contribution <= 0:
                continue
            raw[ticker] = raw.get(ticker, 0.0) + contribution
            contributions.setdefault(ticker, {})[mandate] = contribution

    capped: dict[str, float] = {}
    capped_excess = 0.0
    capped_names: list[str] = []
    for ticker, weight in raw.items():
        capped_weight = min(weight, single_name_cap)
        capped[ticker] = capped_weight
        if capped_weight < weight:
            capped_excess += weight - capped_weight
            capped_names.append(ticker)

    invested = sum(capped.values())
    cash = max(0.0, 1.0 - invested)
    conflicts = [
        {
            "ticker": ticker,
            "mandates": sorted(parts),
            "raw_weight": raw[ticker],
            "capped_weight": capped[ticker],
            "weights_per_mandate": parts,
        }
        for ticker, parts in sorted(contributions.items())
        if len(parts) > 1
    ]
    rows = [
        {
            "rank": idx,
            "ticker": ticker,
            "target_weight": weight,
            "raw_weight": raw[ticker],
            "capped_excess": max(0.0, raw[ticker] - weight),
            "row_type": "equity",
        }
        for idx, (ticker, weight) in enumerate(sorted(capped.items(), key=lambda item: item[1], reverse=True), start=1)
    ]
    rows.append(
        {
            "rank": len(rows) + 1,
            "ticker": "CASH",
            "target_weight": cash,
            "raw_weight": cash,
            "capped_excess": 0.0,
            "row_type": "cash",
        }
    )
    return {
        "unified_weights": capped,
        "cash_target": cash,
        "invested": invested,
        "expected_invested_before_cap": sum(capacities.values()),
        "capped_excess": capped_excess,
        "capped_names": capped_names,
        "n_positions": len(capped),
        "n_conflicts": len(conflicts),
        "conflicts": conflicts,
        "rows": rows,
    }


def run_e0(matrix: dict[str, Any], exp: dict[str, Any], baseline_run: Path, outputs_root: Path, gates_path: Path) -> int:
    common = matrix.get("common", {}) or {}
    required_outputs = list(common.get("required_outputs", []) or [])
    out_dir = outputs_root / "E0_baseline_latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []

    metrics, registry_path = _load_baseline_metrics(baseline_run)
    metrics["matrix_version"] = matrix.get("version")
    metrics["required_outputs"] = required_outputs
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": _rel(registry_path), "status": "derived"})

    _write_equity_curve(baseline_run, out_dir, artifact_status)
    _write_monthly_allocations(baseline_run, out_dir, artifact_status)
    _write_sleeve_returns(out_dir, artifact_status)
    _write_turnover(baseline_run, out_dir, artifact_status)
    _write_stress_windows(baseline_run, out_dir, list(common.get("stress_windows", []) or []), artifact_status)
    _trade_journal_summary(baseline_run, out_dir, artifact_status)

    (out_dir / "experiment_report.md").write_text(
        _render_experiment_report(metrics, artifact_status, exp),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)

    _ensure_regression_attribution(out_dir)
    gate_report = evaluate_discovery(out_dir, out_dir / "metrics.json", gates_path)
    write_json(out_dir / "gate_report.json", gate_report)
    (out_dir / "gate_report.md").write_text(render_gate_markdown(gate_report), encoding="utf-8")
    print(f"[lab] wrote E0 baseline outputs to {out_dir}")
    return 0


def run_e1(matrix: dict[str, Any], exp: dict[str, Any], baseline_run: Path, outputs_root: Path, gates_path: Path) -> int:
    common = matrix.get("common", {}) or {}
    out_dir = outputs_root / "E1_auto_feature_gates_on"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []

    baseline_metrics, _ = _load_baseline_metrics(baseline_run)
    candidate_path = _first_existing(
        baseline_run,
        [
            "auto_learning/auto_feature_gates_candidate.yaml",
            "auto_learning/auto_learning/auto_feature_gates_candidate.yaml",
        ],
    )
    promotion_path = _first_existing(
        baseline_run,
        [
            "auto_learning/promotion_decision.json",
            "auto_learning/auto_learning/promotion_decision.json",
        ],
    )
    candidate = load_yaml(candidate_path) if candidate_path else {}
    promotion = read_json(promotion_path, {}) if promotion_path else {}
    promotion_metrics = promotion.get("metrics", {}) if isinstance(promotion, dict) else {}

    if candidate_path:
        shutil.copy2(candidate_path, out_dir / "feature_gate_candidate.yaml")
        artifact_status.append(
            {"artifact": "feature_gate_candidate.yaml", "source": _rel(candidate_path), "status": "copied"}
        )
    if promotion_path:
        shutil.copy2(promotion_path, out_dir / "promotion_decision.json")
        artifact_status.append(
            {"artifact": "promotion_decision.json", "source": _rel(promotion_path), "status": "copied"}
        )
    gate_rows = _candidate_gate_rows(candidate if isinstance(candidate, dict) else {})
    write_csv_rows(
        out_dir / "feature_gate_candidates.csv",
        gate_rows,
        ["rank", "kind", "signal", "regime", "factor", "ic", "n", "rationale"],
    )
    artifact_status.append({"artifact": "feature_gate_candidates.csv", "source": "", "status": "derived"})

    _write_report_only_required_outputs(
        out_dir,
        list(common.get("stress_windows", []) or []),
        artifact_status,
        "E1 normalizes auto-learning dry-run outputs; no isolated historical challenger backtest was executed",
    )
    _trade_journal_summary(baseline_run, out_dir, artifact_status)
    _copy_trade_insight_artifacts(baseline_run, out_dir, artifact_status)

    metrics = {
        "experiment_id": "E1_auto_feature_gates_on",
        "status": "candidate_only",
        "control": False,
        "artifact_mode": "auto_learning_candidate_normalized",
        "metric_mode": "auto_learning_dry_run_metrics_when_available",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_full_challenger_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "source_run": _rel(baseline_run),
        "candidate_gate_file": _rel(candidate_path) if candidate_path else None,
        "promotion_decision_file": _rel(promotion_path) if promotion_path else None,
        "proposal_count": (candidate or {}).get("n_proposals", len(gate_rows)) if isinstance(candidate, dict) else 0,
        "candidate_gates": gate_rows,
        "promotion_approved": promotion.get("approved") if isinstance(promotion, dict) else None,
        "promotion_promoted": promotion.get("promoted") if isinstance(promotion, dict) else None,
        "promotion_dry_run": promotion.get("dry_run") if isinstance(promotion, dict) else None,
        "promotion_checks": promotion.get("checks", {}) if isinstance(promotion, dict) else {},
        "promotion_reasons": promotion.get("reasons", []) if isinstance(promotion, dict) else [],
        "promotion_thresholds": promotion.get("thresholds", {}) if isinstance(promotion, dict) else {},
        "trade_count": promotion_metrics.get("trade_count"),
        "cagr": promotion_metrics.get("main_cagr", baseline_metrics.get("cagr")),
        "sharpe": promotion_metrics.get("main_sharpe", baseline_metrics.get("sharpe")),
        "max_dd": promotion_metrics.get("main_max_dd", baseline_metrics.get("max_dd")),
        "avg_turnover_monthly": None,
        "avg_stock_names": baseline_metrics.get("avg_stock_names"),
        "baseline_main": baseline_metrics.get("main"),
        "candidate_dry_run_metrics": promotion_metrics,
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})

    interpretation = [
        "E1 is not ready for promotion. The candidate gates are useful research hypotheses, but the latest promotion decision rejected the dry-run because main CAGR, Sharpe, and MaxDD floors failed.",
        "",
        "Next code stage should route these gates through the historical scoring/backtest path as an isolated challenger, then compare 20260430/latest attribution before any active gate file changes.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)

    _ensure_regression_attribution(out_dir)
    baseline_path = _ensure_baseline_metrics_snapshot(matrix, baseline_run, outputs_root)
    gate_report = evaluate_discovery(out_dir, baseline_path, gates_path)
    write_json(out_dir / "gate_report.json", gate_report)
    (out_dir / "gate_report.md").write_text(render_gate_markdown(gate_report), encoding="utf-8")
    print(f"[lab] wrote E1 auto-gate report-only outputs to {out_dir}")
    return 0


def run_e5(matrix: dict[str, Any], exp: dict[str, Any], baseline_run: Path, outputs_root: Path, gates_path: Path) -> int:
    common = matrix.get("common", {}) or {}
    out_dir = outputs_root / "E5_orchestrator_balanced"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []

    baseline_metrics, _ = _load_baseline_metrics(baseline_run)
    current_path = _first_existing(
        baseline_run,
        [
            "orchestrator/unified_target_latest.json",
            "orchestrator/orchestrator/unified_target_latest.json",
        ],
    )
    current = read_json(current_path, {}) if current_path else {}
    regime = current.get("regime_state") or "neutral"
    overrides = exp.get("overrides", {}) or {}
    capacity_by_regime = overrides.get("mandate_capacity_by_regime", {}) or {}
    regime_capacity = dict(capacity_by_regime.get(regime, {}) or capacity_by_regime.get("neutral", {}) or {})
    capacities = {
        "main": safe_float(regime_capacity.get("main"), 0.0) or 0.0,
        "concentrated": safe_float(regime_capacity.get("concentrated"), 0.0) or 0.0,
        "alpha_sprint": safe_float(regime_capacity.get("alpha_sprint"), 0.0) or 0.0,
    }
    expected_cash = safe_float(regime_capacity.get("cash"), max(0.0, 1.0 - sum(capacities.values()))) or 0.0
    single_name_cap = safe_float(overrides.get("unified_single_name_cap"), 0.20) or 0.20

    main_weights, main_audit = _load_normalized_weights(baseline_run / "portfolio_latest.csv")
    concentrated_weights, concentrated_audit = _load_normalized_weights(baseline_run / "concentrated_portfolio_latest.csv")
    mandate_weights = {
        "main": main_weights,
        "concentrated": concentrated_weights,
        "alpha_sprint": {},
    }
    proposed = _sum_then_cap(mandate_weights, capacities, single_name_cap)
    proposed["expected_cash_from_matrix"] = expected_cash
    proposed["regime_state"] = regime
    proposed["merge_mode"] = "sum_then_cap"
    proposed["single_name_cap"] = single_name_cap
    proposed["by_mandate_capacity"] = capacities
    proposed["source_audit"] = {
        "main": main_audit,
        "concentrated": concentrated_audit,
        "alpha_sprint": {"source": None, "valid_positions": 0, "reason": "capacity is zero for neutral regime"},
    }

    current_audit = current.get("audit", {}) if isinstance(current, dict) else {}
    current_checks = current.get("audit_checks", {}) if isinstance(current, dict) else {}
    current_invested = safe_float(current_checks.get("invested_amount"))
    if current_invested is None:
        current_invested = sum((safe_float(w, 0.0) or 0.0) for w in (current.get("unified_weights", {}) or {}).values())
    current_cash = safe_float(current.get("cash_target"), max(0.0, 1.0 - (current_invested or 0.0))) or 0.0
    current_conflict_drag = safe_float(
        (current_audit.get("policy_capacity", {}) or {}).get("merged_below_expected_due_to_conflicts"),
        0.0,
    ) or 0.0

    if current_path:
        shutil.copy2(current_path, out_dir / "current_unified_target_latest.json")
        artifact_status.append(
            {"artifact": "current_unified_target_latest.json", "source": _rel(current_path), "status": "copied"}
        )
    write_json(out_dir / "orchestrator_comparison.json", {"current": current, "proposed": proposed})
    artifact_status.append({"artifact": "orchestrator_comparison.json", "source": "", "status": "derived"})
    write_json(out_dir / "proposed_unified_target_latest.json", proposed)
    artifact_status.append({"artifact": "proposed_unified_target_latest.json", "source": "", "status": "derived"})
    write_csv_rows(
        out_dir / "proposed_unified_target_latest.csv",
        proposed["rows"],
        ["rank", "ticker", "target_weight", "raw_weight", "capped_excess", "row_type"],
    )
    artifact_status.append({"artifact": "proposed_unified_target_latest.csv", "source": "", "status": "derived"})

    _write_unavailable_csv(
        out_dir / "equity_curve.csv",
        "equity_curve.csv",
        "E5 currently compares latest orchestrator snapshot only; historical monthly equity is not generated",
    )
    artifact_status.append({"artifact": "equity_curve.csv", "source": "", "status": "report_only_placeholder"})
    write_csv_rows(
        out_dir / "monthly_allocations.csv",
        [
            {
                "snapshot": "current_max_merge",
                "regime_state": regime,
                "merge_mode": "max",
                "main_capacity": (current.get("by_mandate_capacity", {}) or {}).get("main"),
                "concentrated_capacity": (current.get("by_mandate_capacity", {}) or {}).get("concentrated"),
                "alpha_sprint_capacity": (current.get("by_mandate_capacity", {}) or {}).get("tactical"),
                "invested": current_invested,
                "cash": current_cash,
                "n_positions": current_checks.get("n_positions"),
                "n_conflicts": current_checks.get("n_conflicts"),
            },
            {
                "snapshot": "proposed_sum_then_cap",
                "regime_state": regime,
                "merge_mode": "sum_then_cap",
                "main_capacity": capacities["main"],
                "concentrated_capacity": capacities["concentrated"],
                "alpha_sprint_capacity": capacities["alpha_sprint"],
                "invested": proposed["invested"],
                "cash": proposed["cash_target"],
                "n_positions": proposed["n_positions"],
                "n_conflicts": proposed["n_conflicts"],
            },
        ],
        [
            "snapshot",
            "regime_state",
            "merge_mode",
            "main_capacity",
            "concentrated_capacity",
            "alpha_sprint_capacity",
            "invested",
            "cash",
            "n_positions",
            "n_conflicts",
        ],
    )
    artifact_status.append({"artifact": "monthly_allocations.csv", "source": "", "status": "derived_snapshot"})
    _write_sleeve_returns(out_dir, artifact_status)
    _write_unavailable_csv(
        out_dir / "turnover.csv",
        "turnover.csv",
        "E5 latest-snapshot comparison does not estimate historical turnover",
    )
    artifact_status.append({"artifact": "turnover.csv", "source": "", "status": "report_only_placeholder"})
    _write_stress_windows(baseline_run, out_dir, list(common.get("stress_windows", []) or []), artifact_status)
    _trade_journal_summary(baseline_run, out_dir, artifact_status)

    metrics = {
        "experiment_id": "E5_orchestrator_balanced",
        "status": "snapshot_report_only",
        "control": False,
        "artifact_mode": "orchestrator_latest_snapshot_comparison",
        "metric_mode": "baseline_performance_metrics_plus_latest_snapshot_orchestrator_delta",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_full_challenger_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "source_run": _rel(baseline_run),
        "regime_state": regime,
        "merge_mode": "sum_then_cap",
        "unified_single_name_cap": single_name_cap,
        "current_invested": current_invested,
        "current_cash_target": current_cash,
        "current_conflict_drag": current_conflict_drag,
        "proposed_invested": proposed["invested"],
        "proposed_cash_target": proposed["cash_target"],
        "proposed_expected_cash_from_matrix": expected_cash,
        "cash_drag_improvement_pp": (current_cash - proposed["cash_target"]) * 100.0,
        "incremental_invested_pp": (proposed["invested"] - (current_invested or 0.0)) * 100.0,
        "proposed_capped_excess_pp": proposed["capped_excess"] * 100.0,
        "current_n_positions": current_checks.get("n_positions"),
        "proposed_n_positions": proposed["n_positions"],
        "current_n_conflicts": current_checks.get("n_conflicts"),
        "proposed_n_conflicts": proposed["n_conflicts"],
        "cagr": baseline_metrics.get("cagr"),
        "sharpe": baseline_metrics.get("sharpe"),
        "max_dd": baseline_metrics.get("max_dd"),
        "avg_turnover_monthly": baseline_metrics.get("avg_turnover_monthly"),
        "avg_stock_names": baseline_metrics.get("avg_stock_names"),
        "baseline_main": baseline_metrics.get("main"),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})

    interpretation = [
        "E5 now has executable orchestrator mechanics for the latest snapshot. Under the neutral matrix, proposed sum-then-cap uses 55% main and 25% concentrated capacity, preserving a 20% cash target unless name caps bind.",
        "",
        "This is not yet the requested 83-month orchestrator backtest. The next implementation needs historical monthly raw mandate books or an engine hook that can replay main/concentrated/tactical selections before merge.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)

    _ensure_regression_attribution(out_dir)
    baseline_path = _ensure_baseline_metrics_snapshot(matrix, baseline_run, outputs_root)
    gate_report = evaluate_discovery(out_dir, baseline_path, gates_path)
    write_json(out_dir / "gate_report.json", gate_report)
    (out_dir / "gate_report.md").write_text(render_gate_markdown(gate_report), encoding="utf-8")
    print(f"[lab] wrote E5 orchestrator snapshot outputs to {out_dir}")
    return 0


def _main_v2_policy_from_experiment(exp: dict[str, Any]) -> dict[str, Any]:
    from r1000_main_v2 import MAIN_V2_BALANCED_POLICY

    overrides = exp.get("overrides", {}) or {}
    raw_weights = overrides.get("main_sleeve_weights", {}) or {}
    sleeve_weights = {
        "core": safe_float(raw_weights.get("core"), 0.25) or 0.25,
        "future": safe_float(raw_weights.get("future_winner"), 0.55) or 0.55,
        "early": safe_float(raw_weights.get("early_scout"), 0.15) or 0.15,
    }
    cash = max(0.0, 1.0 - sum(sleeve_weights.values()))
    target_n = int(safe_float(overrides.get("main_target_n"), 15) or 15)
    target_counts = _target_counts_from_weights(target_n, sleeve_weights)
    policy = dict(MAIN_V2_BALANCED_POLICY)
    policy["name"] = str(exp.get("id"))
    policy["single_name_cap"] = safe_float(overrides.get("single_name_cap"), 0.15) or 0.15
    policy["incumbent_buffer"] = int(safe_float(overrides.get("incumbent_buffer"), 3) or 3)
    capacity_by_regime = dict(policy.get("sleeve_capacity_by_regime") or {})
    capacity_by_regime["neutral"] = {
        "core": sleeve_weights["core"],
        "future": sleeve_weights["future"],
        "early": sleeve_weights["early"],
        "cash": cash,
    }
    policy["sleeve_capacity_by_regime"] = capacity_by_regime
    target_by_regime = dict(policy.get("target_n_by_regime") or {})
    target_by_regime["neutral"] = target_counts
    policy["target_n_by_regime"] = target_by_regime
    return policy


def _target_counts_from_weights(total_n: int, weights: dict[str, float]) -> dict[str, int]:
    keys = ["core", "future", "early"]
    raw = {key: max(0.0, float(weights.get(key, 0.0))) for key in keys}
    total_weight = sum(raw.values()) or 1.0
    exact = {key: total_n * raw[key] / total_weight for key in keys}
    counts = {key: int(exact[key]) for key in keys}
    for key in keys:
        if raw[key] > 0 and counts[key] == 0:
            counts[key] = 1
    while sum(counts.values()) > total_n:
        key = max(keys, key=lambda k: counts[k] - exact[k])
        counts[key] -= 1
    while sum(counts.values()) < total_n:
        key = max(keys, key=lambda k: exact[k] - counts[k])
        counts[key] += 1
    return counts


def run_main_v2_experiment(
    matrix: dict[str, Any],
    exp: dict[str, Any],
    baseline_run: Path,
    outputs_root: Path,
    gates_path: Path,
) -> int:
    from r1000_main_v2 import compose_main_sleeve_portfolio, result_to_rows

    common = matrix.get("common", {}) or {}
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []
    baseline_metrics, _ = _load_baseline_metrics(baseline_run)
    scored_rows = read_csv_rows(baseline_run / "scored_latest.csv")
    policy = _main_v2_policy_from_experiment(exp)
    result = compose_main_sleeve_portfolio(scored_rows, policy=policy)

    write_json(out_dir / "main_v2_latest.json", result)
    write_json(out_dir / "main_v2_audit_latest.json", result.get("audit", {}))
    write_csv_rows(
        out_dir / "main_v2_latest.csv",
        result_to_rows(result),
        ["rank", "ticker", "target_weight", "main_v2_sleeves", "main_v2_score", "regime_state", "row_type"],
    )
    artifact_status.extend(
        [
            {"artifact": "main_v2_latest.json", "source": "", "status": "derived_snapshot"},
            {"artifact": "main_v2_audit_latest.json", "source": "", "status": "derived_snapshot"},
            {"artifact": "main_v2_latest.csv", "source": "", "status": "derived_snapshot"},
        ]
    )
    _write_contract_placeholders(
        out_dir,
        common,
        artifact_status,
        f"{exp_id} is latest-snapshot Main v2 only; historical backtest not executed",
        skip={"monthly_allocations.csv", "sleeve_returns.csv"},
    )
    caps = result.get("by_sleeve_capacity") or {}
    selected = (result.get("audit") or {}).get("selected_n_by_sleeve") or {}
    write_csv_rows(
        out_dir / "monthly_allocations.csv",
        [
            {
                "snapshot": exp_id,
                "regime_state": result.get("regime_state"),
                "core_capacity": caps.get("core"),
                "future_capacity": caps.get("future"),
                "early_capacity": caps.get("early"),
                "cash_target": result.get("cash_target"),
                "core_n": selected.get("core"),
                "future_n": selected.get("future"),
                "early_n": selected.get("early"),
            }
        ],
        ["snapshot", "regime_state", "core_capacity", "future_capacity", "early_capacity", "cash_target", "core_n", "future_n", "early_n"],
    )
    write_csv_rows(
        out_dir / "sleeve_returns.csv",
        [
            {"sleeve": "core", "status": "not_backtested", "reason": "latest snapshot only"},
            {"sleeve": "future", "status": "not_backtested", "reason": "latest snapshot only"},
            {"sleeve": "early", "status": "not_backtested", "reason": "latest snapshot only"},
        ],
        ["sleeve", "status", "reason"],
    )
    artifact_status.extend(
        [
            {"artifact": "monthly_allocations.csv", "source": "", "status": "derived_snapshot"},
            {"artifact": "sleeve_returns.csv", "source": "", "status": "limitation_logged"},
        ]
    )
    _trade_journal_summary(baseline_run, out_dir, artifact_status)

    audit = result.get("audit") or {}
    metrics = {
        "experiment_id": exp_id,
        "status": "snapshot_report_only",
        "control": False,
        "category": exp.get("category"),
        "artifact_mode": "main_v2_latest_snapshot",
        "metric_mode": "baseline_performance_metrics_plus_main_v2_snapshot",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_full_challenger_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "source_run": _rel(baseline_run),
        "cagr": baseline_metrics.get("cagr"),
        "sharpe": baseline_metrics.get("sharpe"),
        "max_dd": baseline_metrics.get("max_dd"),
        "avg_turnover_monthly": baseline_metrics.get("avg_turnover_monthly"),
        "avg_stock_names": baseline_metrics.get("avg_stock_names"),
        "baseline_main": baseline_metrics.get("main"),
        "main_v2_positions": audit.get("n_positions"),
        "main_v2_cash_target": audit.get("cash_target"),
        "main_v2_cap_excess_to_cash": audit.get("cap_excess_to_cash"),
        "main_v2_conflicts": audit.get("n_conflicts"),
        "target_n_by_sleeve": audit.get("target_n_by_sleeve"),
        "selected_n_by_sleeve": audit.get("selected_n_by_sleeve"),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})
    interpretation = [
        f"{exp_id} converts the latest scored universe into a Main v2 internal sleeve book.",
        "It is intentionally not promoted because no historical Main v2 replay has been executed.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)
    _write_discovery_gate(out_dir, matrix, baseline_run, outputs_root, gates_path)
    print(f"[lab] wrote {exp_id} Main v2 snapshot outputs to {out_dir}")
    return 0


def run_concentrated_experiment(
    matrix: dict[str, Any],
    exp: dict[str, Any],
    baseline_run: Path,
    outputs_root: Path,
    gates_path: Path,
) -> int:
    from r1000_concentrated_policy import CONCENTRATED_POLICY_BY_REGIME, audit_concentrated_portfolio

    common = matrix.get("common", {}) or {}
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []
    overrides = exp.get("overrides", {}) or {}
    policy = {
        **CONCENTRATED_POLICY_BY_REGIME,
        "capacity": overrides.get("concentrated_capacity_by_regime", CONCENTRATED_POLICY_BY_REGIME.get("capacity")),
        "target_n": overrides.get("concentrated_target_n_by_regime", CONCENTRATED_POLICY_BY_REGIME.get("target_n")),
        "risk": {
            **dict(CONCENTRATED_POLICY_BY_REGIME.get("risk") or {}),
            "single_name_cap": safe_float(overrides.get("concentrated_single_name_cap"), 0.25) or 0.25,
            "theme_cap": safe_float(overrides.get("concentrated_theme_cap"), 0.45) or 0.45,
            "sector_cap": safe_float(overrides.get("concentrated_sector_cap"), 0.55) or 0.55,
        },
    }
    holdings = read_csv_rows(baseline_run / "concentrated_portfolio_latest.csv")
    scored = read_csv_rows(baseline_run / "scored_latest.csv")
    audit = audit_concentrated_portfolio(holdings, scored_rows=scored, policy=policy)
    conc_metrics = read_json(baseline_run / "concentrated_backtest_metrics.json", {}) or {}
    write_json(out_dir / "concentrated_policy_audit.json", audit)
    write_csv_rows(
        out_dir / "concentrated_policy_audit.csv",
        audit.get("rows") or [],
        ["ticker", "name", "sector", "weight", "concentrated_score", "concentrated_conviction_score", "entry_gate_pass", "risk_gate_pass", "entry_failed", "risk_failed"],
    )
    artifact_status.extend(
        [
            {"artifact": "concentrated_policy_audit.json", "source": "", "status": "derived_snapshot"},
            {"artifact": "concentrated_policy_audit.csv", "source": "", "status": "derived_snapshot"},
        ]
    )
    _write_contract_placeholders(
        out_dir,
        common,
        artifact_status,
        "E4 uses standalone concentrated historical metrics plus latest policy audit; no orchestrated portfolio backtest executed",
        skip={"monthly_allocations.csv", "sleeve_returns.csv"},
    )
    write_csv_rows(
        out_dir / "monthly_allocations.csv",
        [
            {"regime_state": regime, "concentrated_capacity": cap, "target_n": (policy.get("target_n") or {}).get(regime)}
            for regime, cap in (policy.get("capacity") or {}).items()
        ],
        ["regime_state", "concentrated_capacity", "target_n"],
    )
    write_csv_rows(
        out_dir / "sleeve_returns.csv",
        [
            {
                "sleeve": "concentrated",
                "cagr": conc_metrics.get("strategy_cagr"),
                "sharpe": conc_metrics.get("sharpe"),
                "max_dd": conc_metrics.get("max_dd"),
                "selected_names": conc_metrics.get("selected_names"),
            }
        ],
        ["sleeve", "cagr", "sharpe", "max_dd", "selected_names"],
    )
    artifact_status.extend(
        [
            {"artifact": "monthly_allocations.csv", "source": "", "status": "derived_policy"},
            {"artifact": "sleeve_returns.csv", "source": _rel(baseline_run / "concentrated_backtest_metrics.json"), "status": "derived"},
        ]
    )
    _trade_journal_summary(baseline_run, out_dir, artifact_status)
    metrics = {
        "experiment_id": exp_id,
        "status": "standalone_sleeve_policy_audit",
        "control": False,
        "artifact_mode": "concentrated_metrics_plus_latest_policy_audit",
        "metric_mode": "standalone_concentrated_not_full_portfolio",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_orchestrator_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "cagr": conc_metrics.get("strategy_cagr"),
        "sharpe": conc_metrics.get("sharpe"),
        "max_dd": conc_metrics.get("max_dd"),
        "avg_turnover_monthly": None,
        "selected_names": conc_metrics.get("selected_names"),
        "cap_violations": len(audit.get("cap_violations") or []),
        "entry_blocked": len(audit.get("entry_blocked") or []),
        "risk_blocked": len(audit.get("risk_blocked") or []),
        "recommended_capacity": audit.get("recommended_capacity"),
        "recommended_target_n": audit.get("recommended_target_n"),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})
    interpretation = [
        "E4 confirms concentrated remains a strong standalone alpha source, but latest cap and entry/risk audit findings block automatic capital expansion.",
        "The next step is an orchestrated historical backtest with these caps and weekly timing rules.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)
    _write_discovery_gate(out_dir, matrix, baseline_run, outputs_root, gates_path)
    print(f"[lab] wrote {exp_id} concentrated outputs to {out_dir}")
    return 0


def run_risk_sensing_experiment(
    matrix: dict[str, Any],
    exp: dict[str, Any],
    baseline_run: Path,
    outputs_root: Path,
    gates_path: Path,
) -> int:
    common = matrix.get("common", {}) or {}
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []
    compare_path = ROOT / "outputs" / "strategy_backtest" / "risk_sensing_compare.json"
    compare = read_json(compare_path, {}) or {}
    js = (compare.get("jeongseok_v1") or {})
    original = js.get("original") or {}
    risked = js.get("with_risk_sensing") or {}
    if compare_path.exists():
        shutil.copy2(compare_path, out_dir / "risk_sensing_compare.json")
        artifact_status.append({"artifact": "risk_sensing_compare.json", "source": _rel(compare_path), "status": "copied"})
    _write_contract_placeholders(
        out_dir,
        common,
        artifact_status,
        "E6 uses simplified Layer 2 DD breaker comparison; full position-aware risk backtest is not available",
        skip={"sleeve_returns.csv"},
    )
    write_csv_rows(
        out_dir / "sleeve_returns.csv",
        [
            {"variant": "original", **original},
            {"variant": "with_risk_sensing", **risked},
        ],
        ["variant", "name", "n_months", "cagr_pct", "sharpe", "max_dd_pct", "calmar", "vol_ann_pct"],
    )
    artifact_status.append({"artifact": "sleeve_returns.csv", "source": _rel(compare_path), "status": "derived"})
    _trade_journal_summary(baseline_run, out_dir, artifact_status)
    metrics = {
        "experiment_id": exp_id,
        "status": "simplified_layer2_backtest",
        "control": False,
        "artifact_mode": "risk_sensing_compare_normalized",
        "metric_mode": "simplified_dd_breaker_backtest",
        "backtest_executed": bool(compare),
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_full_position_replay": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "cagr": (safe_float(risked.get("cagr_pct"), 0.0) or 0.0) / 100.0,
        "sharpe": risked.get("sharpe"),
        "max_dd": (safe_float(risked.get("max_dd_pct"), 0.0) or 0.0) / 100.0,
        "avg_turnover_monthly": None,
        "original": original,
        "with_risk_sensing": risked,
        "cagr_delta_pp": safe_float(risked.get("cagr_pct"), 0.0) - safe_float(original.get("cagr_pct"), 0.0),
        "maxdd_delta_pp": safe_float(risked.get("max_dd_pct"), 0.0) - safe_float(original.get("max_dd_pct"), 0.0),
        "sharpe_delta": safe_float(risked.get("sharpe"), 0.0) - safe_float(original.get("sharpe"), 0.0),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})
    interpretation = [
        "E6 is valuable for drawdown research: simplified Layer 2 risk sensing reduced main MaxDD materially, but it also cut CAGR and Sharpe.",
        "This is a discovery candidate for stress defense, not a production policy until Layer 1/3/4 position-aware replay exists.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)
    _write_discovery_gate(out_dir, matrix, baseline_run, outputs_root, gates_path)
    print(f"[lab] wrote {exp_id} risk sensing outputs to {out_dir}")
    return 0


def run_tactical_experiment(
    matrix: dict[str, Any],
    exp: dict[str, Any],
    baseline_run: Path,
    outputs_root: Path,
    gates_path: Path,
) -> int:
    common = matrix.get("common", {}) or {}
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []
    tactical_dir = ROOT / "cloud_results" / "tactical_alpha" / "latest"
    summary = read_json(tactical_dir / "tactical_run_summary.json", {}) or {}
    for name in ["tactical_run_summary.json", "tactical_portfolio_latest.csv", "tactical_trade_plan.csv"]:
        src = tactical_dir / name
        if src.exists():
            shutil.copy2(src, out_dir / name)
            artifact_status.append({"artifact": name, "source": _rel(src), "status": "copied"})
    _copy_text_if_exists(tactical_dir / "reports" / "tactical_daily_review.md", out_dir / "tactical_daily_review.md", artifact_status)
    _write_contract_placeholders(
        out_dir,
        common,
        artifact_status,
        "E7 tactical latest sidecar is review-ready but no isolated tactical historical performance was produced",
        skip={"monthly_allocations.csv"},
    )
    caps = ((exp.get("overrides") or {}).get("tactical_capacity_by_regime") or {})
    write_csv_rows(
        out_dir / "monthly_allocations.csv",
        [{"regime_state": k, "tactical_capacity": v} for k, v in caps.items()],
        ["regime_state", "tactical_capacity"],
    )
    artifact_status.append({"artifact": "monthly_allocations.csv", "source": "", "status": "derived_policy"})
    _trade_journal_summary(baseline_run, out_dir, artifact_status)
    metrics = {
        "experiment_id": exp_id,
        "status": "sidecar_latest_only",
        "control": False,
        "artifact_mode": "tactical_latest_sidecar",
        "metric_mode": "no_historical_performance",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_tactical_historical_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "cagr": None,
        "sharpe": None,
        "max_dd": None,
        "avg_turnover_monthly": None,
        "candidate_count": summary.get("candidate_count"),
        "selected_count": summary.get("selected_count"),
        "trade_count": summary.get("trade_count"),
        "target_n": summary.get("target_n"),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})
    interpretation = [
        "E7 keeps tactical in sidecar mode. The latest candidate book is copied for inspection, but historical alpha contribution is still missing.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)
    _write_discovery_gate(out_dir, matrix, baseline_run, outputs_root, gates_path)
    print(f"[lab] wrote {exp_id} tactical outputs to {out_dir}")
    return 0


def run_alpha_sprint_experiment(
    matrix: dict[str, Any],
    exp: dict[str, Any],
    baseline_run: Path,
    outputs_root: Path,
    gates_path: Path,
) -> int:
    common = matrix.get("common", {}) or {}
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []
    src_dir = ROOT / "outputs" / "alpha_sprint"
    snapshot = read_json(src_dir / "alpha_sprint_latest.json", {}) or {}
    backtest_metrics = read_json(src_dir / "backtest_metrics.json", {}) or {}
    for name in ["alpha_sprint_latest.json", "candidates_latest.csv", "portfolio_latest.csv", "risk_actions.csv", "weekly_returns.csv", "backtest_metrics.json"]:
        src = src_dir / name
        if src.exists():
            shutil.copy2(src, out_dir / name)
            artifact_status.append({"artifact": name, "source": _rel(src), "status": "copied"})
    _write_contract_placeholders(
        out_dir,
        common,
        artifact_status,
        "E8 alpha sprint is candidate/latest only; no weekly historical backtest yet",
        skip={"monthly_allocations.csv", "sleeve_returns.csv"},
    )
    activation = ((snapshot.get("portfolio") or {}).get("activation") or {})
    write_csv_rows(
        out_dir / "monthly_allocations.csv",
        [
            {
                "regime_state": snapshot.get("regime_state"),
                "alpha_sprint_capacity": activation.get("capacity"),
                "active": activation.get("active"),
                "candidate_count": activation.get("candidate_count"),
            }
        ],
        ["regime_state", "alpha_sprint_capacity", "active", "candidate_count"],
    )
    write_csv_rows(
        out_dir / "sleeve_returns.csv",
        [{"sleeve": "alpha_sprint", "status": backtest_metrics.get("status"), "reason": "weekly historical backtest missing"}],
        ["sleeve", "status", "reason"],
    )
    artifact_status.extend(
        [
            {"artifact": "monthly_allocations.csv", "source": "", "status": "derived_snapshot"},
            {"artifact": "sleeve_returns.csv", "source": _rel(src_dir / "backtest_metrics.json"), "status": "limitation_logged"},
        ]
    )
    _trade_journal_summary(baseline_run, out_dir, artifact_status)
    audit = snapshot.get("audit") or {}
    metrics = {
        "experiment_id": exp_id,
        "status": "sidecar_latest_only",
        "control": False,
        "artifact_mode": "alpha_sprint_latest_sidecar",
        "metric_mode": "no_historical_performance",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "requires_weekly_historical_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "cagr": None,
        "sharpe": None,
        "max_dd": None,
        "avg_turnover_monthly": None,
        "regime_state": snapshot.get("regime_state"),
        "candidate_count": audit.get("candidate_count"),
        "active": audit.get("active"),
        "capacity": audit.get("capacity"),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})
    interpretation = [
        "E8 correctly stays inactive in neutral regime while preserving candidates for future bull/strong-bull replay.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)
    _write_discovery_gate(out_dir, matrix, baseline_run, outputs_root, gates_path)
    print(f"[lab] wrote {exp_id} alpha sprint outputs to {out_dir}")
    return 0


def run_kitchen_sink_experiment(
    matrix: dict[str, Any],
    exp: dict[str, Any],
    baseline_run: Path,
    outputs_root: Path,
    gates_path: Path,
) -> int:
    from r1000_orchestrator import compose_unified_portfolio, orchestrator_result_to_frame

    common = matrix.get("common", {}) or {}
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_status: list[dict[str, Any]] = []
    baseline_metrics, _ = _load_baseline_metrics(baseline_run)
    main_v2_weights, main_v2_audit = _load_normalized_weights(ROOT / "outputs" / "main_v2" / "main_v2_latest.csv")
    concentrated_weights, concentrated_audit = _load_normalized_weights(baseline_run / "concentrated_portfolio_latest.csv")
    alpha_weights, alpha_audit = _load_normalized_weights(ROOT / "outputs" / "alpha_sprint" / "portfolio_latest.csv")
    capacity_override = {"main": 0.55, "concentrated": 0.25, "alpha_sprint": 0.00, "tactical": 0.00}
    result = compose_unified_portfolio(
        mandate_weights={
            "main": main_v2_weights,
            "concentrated": concentrated_weights,
            "alpha_sprint": alpha_weights,
            "tactical": {},
        },
        regime_state="neutral",
        merge_mode="sum_then_cap",
        unified_single_name_cap=0.20,
        capacity_override=capacity_override,
    )
    write_json(out_dir / "kitchen_sink_unified_latest.json", result)
    write_csv_rows(
        out_dir / "kitchen_sink_unified_latest.csv",
        orchestrator_result_to_frame(result),
        ["rank", "ticker", "target_weight", "regime_state", "row_type"],
    )
    write_json(
        out_dir / "source_audit.json",
        {"main_v2": main_v2_audit, "concentrated": concentrated_audit, "alpha_sprint": alpha_audit},
    )
    artifact_status.extend(
        [
            {"artifact": "kitchen_sink_unified_latest.json", "source": "", "status": "derived_snapshot"},
            {"artifact": "kitchen_sink_unified_latest.csv", "source": "", "status": "derived_snapshot"},
            {"artifact": "source_audit.json", "source": "", "status": "derived"},
        ]
    )
    _write_contract_placeholders(
        out_dir,
        common,
        artifact_status,
        "E9 combines latest sidecar books only; full all-on historical replay is not implemented",
        skip={"monthly_allocations.csv"},
    )
    audit = result.get("audit") or {}
    policy_capacity = audit.get("policy_capacity") or {}
    write_csv_rows(
        out_dir / "monthly_allocations.csv",
        [
            {
                "regime_state": result.get("regime_state"),
                "main_capacity": capacity_override["main"],
                "concentrated_capacity": capacity_override["concentrated"],
                "alpha_sprint_capacity": capacity_override["alpha_sprint"],
                "cash_target": result.get("cash_target"),
                "invested": policy_capacity.get("actual_total_invested_after_merge"),
                "n_positions": audit.get("n_unique_tickers"),
                "n_conflicts": audit.get("n_conflicts"),
            }
        ],
        ["regime_state", "main_capacity", "concentrated_capacity", "alpha_sprint_capacity", "cash_target", "invested", "n_positions", "n_conflicts"],
    )
    artifact_status.append({"artifact": "monthly_allocations.csv", "source": "", "status": "derived_snapshot"})
    _trade_journal_summary(baseline_run, out_dir, artifact_status)
    metrics = {
        "experiment_id": exp_id,
        "status": "snapshot_discovery_only",
        "control": False,
        "artifact_mode": "all_on_latest_snapshot",
        "metric_mode": "baseline_performance_metrics_plus_all_on_snapshot",
        "backtest_executed": False,
        "production_defaults_mutable": False,
        "production_activation_allowed": False,
        "never_promote_to_production": True,
        "requires_full_challenger_backtest": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "matrix_version": matrix.get("version"),
        "cagr": baseline_metrics.get("cagr"),
        "sharpe": baseline_metrics.get("sharpe"),
        "max_dd": baseline_metrics.get("max_dd"),
        "avg_turnover_monthly": baseline_metrics.get("avg_turnover_monthly"),
        "avg_stock_names": baseline_metrics.get("avg_stock_names"),
        "cash_target": result.get("cash_target"),
        "n_positions": audit.get("n_unique_tickers"),
        "n_conflicts": audit.get("n_conflicts"),
    }
    write_json(out_dir / "metrics.json", metrics)
    artifact_status.append({"artifact": "metrics.json", "source": "", "status": "derived"})
    interpretation = [
        "E9 is intentionally wild-lab only. It combines Main v2, concentrated, and sprint/tactical hooks in a latest neutral snapshot.",
        "It cannot be promoted; its purpose is to expose conflicts, cap behavior, and missing historical replay requirements.",
    ]
    (out_dir / "experiment_report.md").write_text(
        _render_report_only_report(metrics, artifact_status, exp, interpretation),
        encoding="utf-8",
    )
    write_json(out_dir / "artifact_status.json", artifact_status)
    _write_discovery_gate(out_dir, matrix, baseline_run, outputs_root, gates_path)
    print(f"[lab] wrote {exp_id} kitchen sink outputs to {out_dir}")
    return 0


def run_not_implemented(exp: dict[str, Any], outputs_root: Path) -> int:
    exp_id = str(exp.get("id"))
    out_dir = outputs_root / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = {
        "experiment_id": exp_id,
        "status": "not_implemented",
        "control": False,
        "description": exp.get("description"),
        "category": exp.get("category"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "strategy adapter not implemented in Stage 1 runner",
    }
    write_json(out_dir / "metrics.json", metrics)
    (out_dir / "experiment_report.md").write_text(
        "# Aggressive Lab Experiment Report\n\n"
        f"- Experiment: `{exp_id}`\n"
        "- Status: `not_implemented`\n\n"
        "This experiment is declared in the matrix but requires a strategy adapter in a later stage.\n",
        encoding="utf-8",
    )
    print(f"[lab] {exp_id} is not implemented yet")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default=DEFAULT_MATRIX)
    parser.add_argument("--discovery-gates", default=DEFAULT_GATES)
    parser.add_argument("--experiment-id", action="append", dest="experiment_ids")
    parser.add_argument("--baseline-run", default=None)
    parser.add_argument("--outputs-root", default=None)
    args = parser.parse_args()

    matrix_path = ROOT / args.matrix
    matrix = load_yaml(matrix_path)
    common = matrix.get("common", {}) or {}
    experiment_ids = args.experiment_ids or ["E0_baseline_latest"]
    baseline_run = ROOT / (args.baseline_run or common.get("baseline_run"))
    outputs_root = ROOT / (args.outputs_root or common.get("outputs_root", "outputs/experiments"))
    gates_path = ROOT / args.discovery_gates

    rc = 0
    for exp_id in experiment_ids:
        exp = _find_experiment(matrix, exp_id)
        if exp_id == "E0_baseline_latest":
            rc = max(rc, run_e0(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E1_auto_feature_gates_on":
            rc = max(rc, run_e1(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id in {"E2_main_v2_balanced", "E3_main_v2_aggressive"}:
            rc = max(rc, run_main_v2_experiment(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E4_concentrated_balanced":
            rc = max(rc, run_concentrated_experiment(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E5_orchestrator_balanced":
            rc = max(rc, run_e5(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E6_risk_sensing_on":
            rc = max(rc, run_risk_sensing_experiment(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E7_tactical_bull_only":
            rc = max(rc, run_tactical_experiment(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E8_alpha_sprint_sidecar":
            rc = max(rc, run_alpha_sprint_experiment(matrix, exp, baseline_run, outputs_root, gates_path))
        elif exp_id == "E9_kitchen_sink_all_on":
            rc = max(rc, run_kitchen_sink_experiment(matrix, exp, baseline_run, outputs_root, gates_path))
        else:
            rc = max(rc, run_not_implemented(exp, outputs_root))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
