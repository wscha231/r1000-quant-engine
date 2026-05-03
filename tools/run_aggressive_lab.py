#!/usr/bin/env python3
"""Run isolated AlphaOps aggressive lab experiments.

The runner is intentionally report-only until an experiment has a real
historical strategy adapter. It normalizes existing artifacts into the lab
contract and keeps production defaults untouched.
"""
from __future__ import annotations

import argparse
import shutil
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

    baseline_path = _ensure_baseline_metrics_snapshot(matrix, baseline_run, outputs_root)
    gate_report = evaluate_discovery(out_dir, baseline_path, gates_path)
    write_json(out_dir / "gate_report.json", gate_report)
    (out_dir / "gate_report.md").write_text(render_gate_markdown(gate_report), encoding="utf-8")
    print(f"[lab] wrote E5 orchestrator snapshot outputs to {out_dir}")
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
        elif exp_id == "E5_orchestrator_balanced":
            rc = max(rc, run_e5(matrix, exp, baseline_run, outputs_root, gates_path))
        else:
            rc = max(rc, run_not_implemented(exp, outputs_root))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
