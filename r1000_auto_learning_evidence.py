"""Evidence loading for the research-only AutoLearning Policy Engine."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_LATEST_RUN = ROOT / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _metric(metrics: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in metrics:
            return safe_float(metrics.get(name), default)
    return default


def summarize_metrics(main: dict[str, Any], concentrated: dict[str, Any]) -> dict[str, Any]:
    return {
        "main": {
            "cagr": _metric(main, "cagr", "strategy_cagr"),
            "sharpe": _metric(main, "sharpe"),
            "max_dd": _metric(main, "max_dd"),
            "avg_turnover_monthly": _metric(main, "avg_turnover_monthly"),
            "avg_stock_names": _metric(main, "avg_stock_names"),
            "months": int(_metric(main, "months")),
        },
        "concentrated": {
            "cagr": _metric(concentrated, "strategy_cagr", "cagr"),
            "sharpe": _metric(concentrated, "sharpe"),
            "max_dd": _metric(concentrated, "max_dd"),
            "selected_names": int(_metric(concentrated, "selected_names")),
            "monitoring_review_days": int(_metric(concentrated, "monitoring_review_days")),
        },
    }


def summarize_trades(rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return {"trade_count": 0}
    regime_counts: Counter[str] = Counter()
    sleeve_counts: Counter[str] = Counter()
    exit_counts: Counter[str] = Counter()
    returns: list[float] = []
    alphas: list[float] = []
    holding_days: list[float] = []
    sleeve_returns: dict[str, list[float]] = defaultdict(list)
    regime_returns: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        regime = str(row.get("entry_regime_state") or "unknown")
        sleeve = str(row.get("entry_sleeve") or "unknown")
        regime_counts[regime] += 1
        sleeve_counts[sleeve] += 1
        exit_counts[str(row.get("exit_reason") or "unknown")] += 1
        ret = safe_float(row.get("realized_return"))
        alpha = safe_float(row.get("alpha_vs_benchmark"))
        returns.append(ret)
        alphas.append(alpha)
        holding_days.append(safe_float(row.get("holding_days")))
        sleeve_returns[sleeve].append(ret)
        regime_returns[regime].append(ret)

    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "trade_count": len(rows),
        "win_rate": sum(1 for value in returns if value > 0) / len(returns),
        "avg_realized_return": avg(returns),
        "avg_alpha_vs_benchmark": avg(alphas),
        "avg_holding_days": avg(holding_days),
        "regime_counts": dict(regime_counts.most_common()),
        "sleeve_counts": dict(sleeve_counts.most_common()),
        "exit_reason_counts": dict(exit_counts.most_common(8)),
        "avg_return_by_sleeve": {k: avg(v) for k, v in sorted(sleeve_returns.items())},
        "avg_return_by_regime": {k: avg(v) for k, v in sorted(regime_returns.items())},
    }


def parse_feature_gate_candidate(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "gates": []}
    gates: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- kind:"):
            if current:
                gates.append(current)
            current = {"kind": line.split(":", 1)[1].strip()}
            continue
        if current is None or ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in {"factor", "ic"}:
            current[key] = safe_float(value)
        elif key == "n":
            current[key] = int(safe_float(value))
        elif key in {"signal", "regime", "rationale"}:
            current[key] = value
    if current:
        gates.append(current)
    return {
        "available": True,
        "path": str(path),
        "gate_count": len(gates),
        "gates": gates,
    }


def summarize_sleeve_audit(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_sleeve: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row.get("portfolio_sleeve_label") or "unknown")
        by_sleeve[label] = {
            "months": int(safe_float(row.get("months"))),
            "latest_candidate_count": int(safe_float(row.get("latest_candidate_count"))),
            "latest_gate_pass_count": int(safe_float(row.get("latest_gate_pass_count"))),
            "latest_top10_gate_tickers": row.get("latest_top10_gate_tickers") or "",
            "hist_gate_avg_score": safe_float(row.get("hist_gate_avg_score")),
            "latest_gate_avg_score": safe_float(row.get("latest_gate_avg_score")),
            "hist_gate_avg_multi_year_winner_score": safe_float(row.get("hist_gate_avg_multi_year_winner_score")),
            "latest_gate_avg_multi_year_winner_score": safe_float(row.get("latest_gate_avg_multi_year_winner_score")),
        }
    return by_sleeve


def load_auto_learning_evidence(
    latest_run: Path | str = DEFAULT_LATEST_RUN,
    root: Path | str = ROOT,
) -> dict[str, Any]:
    root_path = Path(root)
    run_path = Path(latest_run)
    if not run_path.is_absolute():
        run_path = root_path / run_path

    trade_path = run_path / "trade_journal" / "trades.csv"
    if not trade_path.exists():
        trade_path = run_path / "trade_journal" / "trade_journal" / "trades.csv"
    sleeve_audit_path = run_path / "reports" / "global_alpha_sleeve_audit_summary.csv"
    feature_gate_path = run_path / "auto_learning" / "auto_feature_gates_candidate.yaml"

    main_metrics = read_json(run_path / "backtest_metrics.json")
    concentrated_metrics = read_json(run_path / "concentrated_backtest_metrics.json")
    trade_rows = read_csv_rows(trade_path)
    sleeve_audit_rows = read_csv_rows(sleeve_audit_path)
    main_v2_audit = read_json(root_path / "outputs" / "main_v2" / "main_v2_audit_latest.json")
    concentrated_policy_audit = read_json(root_path / "outputs" / "concentrated_policy" / "policy_audit_latest.json")
    alpha_sprint_latest = read_json(root_path / "outputs" / "alpha_sprint" / "alpha_sprint_latest.json")

    return {
        "run_path": str(run_path),
        "paths": {
            "trade_journal": str(trade_path),
            "sleeve_audit": str(sleeve_audit_path),
            "feature_gate_candidate": str(feature_gate_path),
            "main_metrics": str(run_path / "backtest_metrics.json"),
            "concentrated_metrics": str(run_path / "concentrated_backtest_metrics.json"),
            "main_v2_audit": str(root_path / "outputs" / "main_v2" / "main_v2_audit_latest.json"),
            "concentrated_policy_audit": str(root_path / "outputs" / "concentrated_policy" / "policy_audit_latest.json"),
            "alpha_sprint_latest": str(root_path / "outputs" / "alpha_sprint" / "alpha_sprint_latest.json"),
        },
        "metrics": summarize_metrics(main_metrics, concentrated_metrics),
        "trade_journal": summarize_trades(trade_rows),
        "feature_gate_candidate": parse_feature_gate_candidate(feature_gate_path),
        "sleeve_audit": summarize_sleeve_audit(sleeve_audit_rows),
        "main_v2": main_v2_audit,
        "concentrated_policy": concentrated_policy_audit,
        "alpha_sprint": {
            "regime_state": alpha_sprint_latest.get("regime_state"),
            "candidate_count": (alpha_sprint_latest.get("audit") or {}).get("candidate_count", 0),
            "active": (alpha_sprint_latest.get("audit") or {}).get("active", False),
            "capacity": (alpha_sprint_latest.get("audit") or {}).get("capacity", 0.0),
        },
    }
