#!/usr/bin/env python3
"""Broker-ledger position-risk grid sweep.

This is the stricter companion to `run_subdaily_exit_grid_sweep.py`.
It repeats `run_broker_position_risk_replay.py` across a stop grid so the
candidate is measured with integer shares, cash ledger, fees, next-close fills,
and daily account equity. It is research-only: winners are persisted as
diagnostic artifacts and are not promoted into production policy.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


BROKER_RISK_TOOL = REPO_ROOT / "tools" / "run_broker_position_risk_replay.py"
DISABLED_STOP_VALUE = -1.0
DEFAULT_HARD_GRID = "disabled"
DEFAULT_TRAILING_GRID = "-0.25,-0.30,-0.35,-0.45"
DEFAULT_TRAILING_ACTIVATION = 0.30
DEFAULT_RELATIVE_TRIM_THRESHOLD = -99.0
DEFAULT_RELATIVE_EXIT_THRESHOLD = -99.0
DEFAULT_COMPOSITE_WEIGHTS = {
    "cagr_weight": 1.0,
    "mdd_improvement_weight": 0.50,
    "cagr_drag_penalty_threshold_pp": 1.0,
    "cagr_drag_penalty_weight": 0.75,
}
PORTFOLIO_TARGETS = {
    "main": {"cagr": 0.35, "max_dd": -0.25},
    "concentrated": {"cagr": 0.50, "max_dd": -0.25},
}
ERA_BUCKETS = [
    ("2019_2020", date(2019, 1, 1), date(2020, 12, 31)),
    ("2021_2022", date(2021, 1, 1), date(2022, 12, 31)),
    ("2023_2024", date(2023, 1, 1), date(2024, 12, 31)),
    ("2025_2026", date(2025, 1, 1), date(2026, 12, 31)),
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> dict[str, Any]:
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


def parse_grid(spec: str, *, allow_disabled: bool = False) -> list[float]:
    values: list[float] = []
    for raw in spec.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token in {"disabled", "off", "none"}:
            if not allow_disabled:
                raise ValueError(f"`disabled` not allowed in this grid: {spec!r}")
            values.append(DISABLED_STOP_VALUE)
        else:
            values.append(float(token))
    return values


def label_for_stop(value: float) -> str:
    if value <= DISABLED_STOP_VALUE + 1e-9:
        return "disabled"
    return f"{value:+.2%}"


def target_book_for(latest: Path, portfolio: str) -> Path:
    if portfolio == "main":
        alphaops = latest / "alphaops_vnext" / "official_main_target_book.csv"
        if alphaops.exists():
            return alphaops
        return latest / "reports" / "operating_main_target_book.csv"
    if portfolio == "concentrated":
        alphaops = latest / "alphaops_vnext" / "official_concentrated_target_book.csv"
        if alphaops.exists():
            return alphaops
        return latest / "reports" / "operating_concentrated_target_book.csv"
    raise ValueError(f"unknown portfolio: {portfolio!r}")


def baseline_for(latest: Path, portfolio: str) -> dict[str, Any]:
    metrics = load_json(latest / "broker_replay" / portfolio / "metrics.json")
    return {
        "available": bool(metrics),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "metric_mode": metrics.get("metric_mode", ""),
    }


def score_composite(
    overlay_cagr: float,
    overlay_max_dd: float,
    baseline: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    w = dict(DEFAULT_COMPOSITE_WEIGHTS)
    if weights:
        w.update(weights)
    baseline_cagr = safe_float(baseline.get("cagr"))
    baseline_mdd = safe_float(baseline.get("max_dd"))
    cagr_gap_pp = (baseline_cagr - overlay_cagr) * 100.0
    mdd_improvement_pp = (overlay_max_dd - baseline_mdd) * 100.0
    cagr_term = float(w["cagr_weight"]) * overlay_cagr
    mdd_term = float(w["mdd_improvement_weight"]) * (mdd_improvement_pp / 100.0)
    extra_drag_pp = max(0.0, cagr_gap_pp - float(w["cagr_drag_penalty_threshold_pp"]))
    drag_penalty = float(w["cagr_drag_penalty_weight"]) * (extra_drag_pp / 100.0)
    composite = cagr_term + mdd_term - drag_penalty
    return {
        "composite": float(composite),
        "cagr_gap_pp": float(cagr_gap_pp),
        "mdd_improvement_pp": float(mdd_improvement_pp),
        "cagr_term": float(cagr_term),
        "mdd_term": float(mdd_term),
        "drag_penalty": float(drag_penalty),
    }


def rank_grid(
    combos: Sequence[tuple[float, float]],
    overlay_metrics_loader: Callable[[float, float], dict[str, Any]],
    baseline: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hard, trailing in combos:
        metrics = overlay_metrics_loader(hard, trailing)
        if metrics.get("status") != "completed":
            rows.append(
                {
                    "status": metrics.get("status") or "missing",
                    "hard_stop": hard,
                    "hard_stop_label": label_for_stop(hard),
                    "trailing_stop": trailing,
                    "trailing_stop_label": label_for_stop(trailing),
                    "composite": float("-inf"),
                    "error": metrics.get("error", metrics.get("stderr_tail", "")),
                }
            )
            continue
        overlay_cagr = safe_float(metrics.get("cagr"))
        overlay_mdd = safe_float(metrics.get("max_dd"))
        rows.append(
            {
                "status": "ok",
                "hard_stop": hard,
                "hard_stop_label": label_for_stop(hard),
                "trailing_stop": trailing,
                "trailing_stop_label": label_for_stop(trailing),
                "overlay_cagr": overlay_cagr,
                "overlay_max_dd": overlay_mdd,
                "overlay_sharpe": safe_float(metrics.get("sharpe")),
                "overlay_avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
                "overlay_risk_exit_count": int(safe_float(metrics.get("risk_exit_count"))),
                "overlay_risk_trim_count": int(safe_float(metrics.get("risk_trim_count"))),
                "overlay_trade_count": int(safe_float(metrics.get("trade_count"))),
                "metric_mode": metrics.get("metric_mode", ""),
                "combo_output_dir": metrics.get("_output_dir", ""),
                **score_composite(overlay_cagr, overlay_mdd, baseline, weights=weights),
            }
        )
    return sorted(rows, key=lambda row: row["composite"], reverse=True)


def annotate_gate_status(ranked: list[dict[str, Any]], portfolio: str) -> list[dict[str, Any]]:
    targets = PORTFOLIO_TARGETS.get(portfolio, {"cagr": 0.0, "max_dd": 0.0})
    out: list[dict[str, Any]] = []
    for row in ranked:
        updated = dict(row)
        reasons: list[str] = []
        if updated.get("status") != "ok":
            reasons.append(str(updated.get("status") or "not_ok"))
        if safe_float(updated.get("overlay_cagr")) < safe_float(targets.get("cagr")):
            reasons.append("cagr_below_target")
        if safe_float(updated.get("overlay_max_dd")) < safe_float(targets.get("max_dd")):
            reasons.append("mdd_below_target")
        updated["target_cagr"] = safe_float(targets.get("cagr"))
        updated["target_max_dd"] = safe_float(targets.get("max_dd"))
        updated["gate_pass"] = not reasons
        updated["gate_fail_reasons"] = reasons
        out.append(updated)
    return out


def champion_from_ranked(ranked: list[dict[str, Any]], *, gate_first: bool = False) -> dict[str, Any] | None:
    for row in ranked:
        if row.get("status") == "ok" and (not gate_first or bool(row.get("gate_pass"))):
            return row
    return None


def parse_iso_date(value: Any) -> date | None:
    try:
        if value is None or value == "":
            return None
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def era_for_date(value: date | None) -> str:
    if value is None:
        return "unknown"
    for label, start, end in ERA_BUCKETS:
        if start <= value <= end:
            return label
    return "outside"


def period_metrics(points: list[tuple[date, float]]) -> dict[str, Any]:
    if len(points) < 2:
        return {"available": False}
    ordered = sorted(points, key=lambda item: item[0])
    start_dt, start_equity = ordered[0]
    end_dt, end_equity = ordered[-1]
    years = max((end_dt - start_dt).days / 365.25, 1e-9)
    total_return = end_equity / max(start_equity, 1e-12) - 1.0
    cagr = (end_equity / max(start_equity, 1e-12)) ** (1.0 / years) - 1.0
    peak = -float("inf")
    max_dd = 0.0
    for _dt, equity in ordered:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = min(max_dd, equity / peak - 1.0)
    return {
        "available": True,
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "days": (end_dt - start_dt).days + 1,
        "years": years,
        "total_return": total_return,
        "cagr": cagr,
        "max_dd": max_dd,
    }


def read_equity_points(path: Path) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            dt = parse_iso_date(row.get("date"))
            equity = safe_float(row.get("equity_usd"), default=float("nan"))
            if dt is not None and math.isfinite(equity) and equity > 0:
                rows.append((dt, equity))
    return rows


def read_exit_counts_by_era(path: Path) -> dict[str, int]:
    counts = {label: 0 for label, _start, _end in ERA_BUCKETS}
    counts["unknown"] = 0
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            reason = str(row.get("reason") or row.get("risk_rule_action") or "")
            if "exit" not in reason:
                continue
            dt = parse_iso_date(row.get("fill_date") or row.get("signal_date") or row.get("date"))
            era = era_for_date(dt)
            counts[era] = counts.get(era, 0) + 1
    return counts


def build_robustness_block(champion_dir: Path) -> dict[str, Any]:
    equity_points = read_equity_points(champion_dir / "equity_curve.csv")
    exit_counts = read_exit_counts_by_era(champion_dir / "risk_actions.csv")
    per_era: dict[str, Any] = {}
    for label, start, end in ERA_BUCKETS:
        points = [(dt, equity) for dt, equity in equity_points if start <= dt <= end]
        metrics = period_metrics(points)
        metrics["risk_exit_count"] = int(exit_counts.get(label, 0))
        per_era[label] = metrics
    total_exits = sum(int(v) for k, v in exit_counts.items() if k not in {"unknown", "outside"})
    active_eras = sum(1 for k, v in exit_counts.items() if k not in {"unknown", "outside"} and int(v) > 0)
    flags: list[str] = []
    if total_exits <= 2:
        flags.append("thin_exit_evidence")
    if active_eras <= 1 and total_exits > 0:
        flags.append("single_era_exit_concentration")
    if not equity_points:
        flags.append("missing_equity_curve")
    return {
        "schema_version": "broker_position_risk_grid_robustness_v1",
        "method": "per_era_diagnostics_not_oos_selection",
        "oos_selection_used": False,
        "robustness_flag": "review_required" if flags else "no_obvious_concentration_flag",
        "flags": flags,
        "risk_exit_count": total_exits,
        "risk_exit_active_era_count": active_eras,
        "risk_exit_count_by_era": exit_counts,
        "per_era": per_era,
    }


def persist_champion_artifacts(champion: dict[str, Any] | None, destination: Path) -> dict[str, Any]:
    if not champion:
        shutil.rmtree(destination, ignore_errors=True)
        return {"persisted": False, "reason": "no_gate_passing_champion"}
    source = Path(str(champion.get("combo_output_dir") or ""))
    if not source.exists():
        return {"persisted": False, "reason": "missing_combo_output_dir", "source": str(source)}
    shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    return {
        "persisted": True,
        "source": str(source),
        "destination": str(destination),
        "trades_csv": str(destination / "trades.csv"),
        "equity_curve_csv": str(destination / "equity_curve.csv"),
    }


def run_broker_position_risk(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio: str,
    hard_stop: float,
    trailing_stop: float,
    trailing_activation: float,
    relative_trim_threshold: float,
    relative_exit_threshold: float,
    disable_distribution_exit: bool,
    python_exec: str | None = None,
) -> dict[str, Any]:
    if not target_book.exists():
        return {"status": "missing_inputs", "error": f"missing target book: {target_book}"}
    py = python_exec or sys.executable
    cmd = [
        py,
        str(BROKER_RISK_TOOL),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--output-dir",
        str(output_dir),
        "--portfolio-kind",
        portfolio,
        "--fill-mode",
        "next_close",
        "--cost-bps",
        "25",
        "--max-fill-lag-days",
        "7",
        "--hard-stop",
        str(hard_stop),
        "--trailing-stop",
        str(trailing_stop),
        "--trailing-activation",
        str(trailing_activation),
        "--relative-trim-threshold",
        str(relative_trim_threshold),
        "--relative-exit-threshold",
        str(relative_exit_threshold),
        "--candidate-id",
        f"{portfolio}_broker_position_risk_grid_hard_{label_for_stop(hard_stop)}_trail_{label_for_stop(trailing_stop)}",
    ]
    if disable_distribution_exit:
        cmd.append("--disable-distribution-exit")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"status": "broker_position_risk_failed", "stderr_tail": proc.stderr[-800:], "stdout_tail": proc.stdout[-800:]}
    payload = load_json(output_dir / "metrics.json")
    if not payload:
        return {"status": "missing_metrics", "error": str(output_dir / "metrics.json")}
    payload["_output_dir"] = str(output_dir)
    return payload


def render_report(
    portfolio: str,
    baseline: dict[str, Any],
    ranked: list[dict[str, Any]],
    champion: dict[str, Any] | None,
    best_ranked: dict[str, Any] | None = None,
) -> str:
    lines = [f"# Broker Position-Risk Grid Sweep - {portfolio}", ""]
    lines.append("Research-only broker-style daily-stop grid. It uses next-close account-ledger fills, integer shares, fees, and cash ledger.")
    lines.append("Production activation remains false; any candidate still needs explicit review and a full official run.")
    lines.append("")
    lines.append(
        f"Baseline broker replay: CAGR `{baseline.get('cagr', 0.0):.2%}` / MaxDD `{baseline.get('max_dd', 0.0):.2%}` / Sharpe `{baseline.get('sharpe', 0.0):.3f}`"
    )
    targets = PORTFOLIO_TARGETS.get(portfolio, {"cagr": 0.0, "max_dd": 0.0})
    lines.append(
        f"Gate-first champion target: CAGR `>= {targets['cagr']:.2%}` and MaxDD `>= {targets['max_dd']:.2%}`."
    )
    if champion is None:
        lines.append("No gate-passing champion was found. Composite ranking below is diagnostic only.")
        if best_ranked is not None:
            lines.append(
                f"Best ranked near-miss: `{best_ranked.get('hard_stop_label')}` hard / `{best_ranked.get('trailing_stop_label')}` trailing, "
                f"CAGR `{safe_float(best_ranked.get('overlay_cagr')):.2%}`, MaxDD `{safe_float(best_ranked.get('overlay_max_dd')):.2%}`."
            )
    else:
        lines.append(
            f"Champion: `{champion.get('hard_stop_label')}` hard / `{champion.get('trailing_stop_label')}` trailing, "
            f"CAGR `{safe_float(champion.get('overlay_cagr')):.2%}`, MaxDD `{safe_float(champion.get('overlay_max_dd')):.2%}`."
        )
    lines.append("")
    lines.append("| rank | gate | hard | trailing | CAGR | MaxDD | cagr_gap_pp | mdd_imp_pp | exits | trades | composite |")
    lines.append("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for idx, row in enumerate(ranked, 1):
        if row.get("status") != "ok":
            lines.append(
                f"| {idx} | no | `{row.get('hard_stop_label', '?')}` | `{row.get('trailing_stop_label', '?')}` | - | - | - | - | - | - | `{row.get('status', '?')}` |"
            )
            continue
        lines.append(
            f"| {idx} | {'yes' if row.get('gate_pass') else 'no'} | `{row['hard_stop_label']}` | `{row['trailing_stop_label']}` | {row['overlay_cagr']:.2%} | {row['overlay_max_dd']:.2%} | "
            f"{row['cagr_gap_pp']:+.2f} | {row['mdd_improvement_pp']:+.2f} | {row['overlay_risk_exit_count']} | {row['overlay_trade_count']} | `{row['composite']:.4f}` |"
        )
    lines.append("")
    return "\n".join(lines)


def evaluate_portfolio(
    *,
    portfolio: str,
    latest: Path,
    price_cache: Path,
    output_dir: Path,
    hard_grid: list[float],
    trailing_grid: list[float],
    trailing_activation: float,
    relative_trim_threshold: float,
    relative_exit_threshold: float,
    disable_distribution_exit: bool,
    keep_intermediate: bool,
) -> dict[str, Any]:
    baseline = baseline_for(latest, portfolio)
    if not baseline["available"]:
        return {"portfolio": portfolio, "status": "missing_baseline", "production_activation_allowed": False}
    target_book = target_book_for(latest, portfolio)
    if not target_book.exists():
        return {
            "portfolio": portfolio,
            "status": "missing_target_book",
            "target_book": str(target_book),
            "production_activation_allowed": False,
        }

    combo_dir = output_dir / portfolio / "_combos"
    combo_dir.mkdir(parents=True, exist_ok=True)
    combo_metrics: dict[tuple[float, float], dict[str, Any]] = {}

    def loader(hard: float, trailing: float) -> dict[str, Any]:
        key = (hard, trailing)
        if key in combo_metrics:
            return combo_metrics[key]
        sub_out = combo_dir / f"hard_{hard:.4f}_trail_{trailing:.4f}".replace("-", "neg")
        metrics = run_broker_position_risk(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=sub_out,
            portfolio=portfolio,
            hard_stop=hard,
            trailing_stop=trailing,
            trailing_activation=trailing_activation,
            relative_trim_threshold=relative_trim_threshold,
            relative_exit_threshold=relative_exit_threshold,
            disable_distribution_exit=disable_distribution_exit,
        )
        combo_metrics[key] = metrics
        return metrics

    combos = [(hard, trailing) for hard in hard_grid for trailing in trailing_grid]
    ranked = annotate_gate_status(rank_grid(combos, loader, baseline), portfolio)
    best_ranked = champion_from_ranked(ranked, gate_first=False)
    champion = champion_from_ranked(ranked, gate_first=True)
    champion_dir = output_dir / portfolio / "champion"
    best_ranked_dir = output_dir / portfolio / "best_ranked"
    champion_artifacts = persist_champion_artifacts(champion, champion_dir)
    best_ranked_artifacts = persist_champion_artifacts(best_ranked, best_ranked_dir)
    robustness = build_robustness_block(champion_dir) if champion_artifacts.get("persisted") else {
        "schema_version": "broker_position_risk_grid_robustness_v1",
        "method": "per_era_diagnostics_not_oos_selection",
        "oos_selection_used": False,
        "robustness_flag": "no_gate_passing_champion",
        "flags": ["no_gate_passing_champion"],
    }
    best_ranked_robustness = build_robustness_block(best_ranked_dir) if best_ranked_artifacts.get("persisted") else {
        "schema_version": "broker_position_risk_grid_robustness_v1",
        "method": "per_era_diagnostics_not_oos_selection",
        "oos_selection_used": False,
        "robustness_flag": "missing_best_ranked",
        "flags": ["missing_best_ranked"],
    }
    if champion is not None:
        champion = dict(champion)
        champion["champion_artifacts"] = champion_artifacts
        champion["robustness"] = robustness
        # Avoid persisting machine-local temporary paths in the public summary.
        champion.pop("combo_output_dir", None)
    if best_ranked is not None:
        best_ranked = dict(best_ranked)
        best_ranked["best_ranked_artifacts"] = best_ranked_artifacts
        best_ranked["robustness"] = best_ranked_robustness
        best_ranked.pop("combo_output_dir", None)
    public_ranked: list[dict[str, Any]] = []
    for row in ranked:
        clean = dict(row)
        clean.pop("combo_output_dir", None)
        public_ranked.append(clean)
    if not keep_intermediate:
        shutil.rmtree(combo_dir, ignore_errors=True)
    status = "completed" if champion is not None else "no_gate_passing_config"
    return {
        "schema_version": "broker_position_risk_grid_sweep_v1",
        "portfolio": portfolio,
        "status": status,
        "target_book": str(target_book),
        "baseline_broker_ledger": baseline,
        "combos_evaluated": len(combos),
        "hard_stop_grid": hard_grid,
        "trailing_stop_grid": trailing_grid,
        "trailing_activation": trailing_activation,
        "relative_trim_threshold": relative_trim_threshold,
        "relative_exit_threshold": relative_exit_threshold,
        "disable_distribution_exit": bool(disable_distribution_exit),
        "gate_targets": PORTFOLIO_TARGETS.get(portfolio, {}),
        "ranked": public_ranked,
        "champion": champion,
        "best_ranked": best_ranked,
        "champion_artifacts": champion_artifacts,
        "best_ranked_artifacts": best_ranked_artifacts,
        "robustness": robustness,
        "best_ranked_robustness": best_ranked_robustness,
        "production_activation_allowed": False,
        "review_only": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/broker_position_risk_grid_wide_trailing")
    parser.add_argument("--portfolio-kind", default="both", choices=("main", "concentrated", "both"))
    parser.add_argument("--hard-stop-grid", default=DEFAULT_HARD_GRID)
    parser.add_argument("--trailing-stop-grid", default=DEFAULT_TRAILING_GRID)
    parser.add_argument("--trailing-activation", type=float, default=DEFAULT_TRAILING_ACTIVATION)
    parser.add_argument("--relative-trim-threshold", type=float, default=DEFAULT_RELATIVE_TRIM_THRESHOLD)
    parser.add_argument("--relative-exit-threshold", type=float, default=DEFAULT_RELATIVE_EXIT_THRESHOLD)
    parser.add_argument("--enable-distribution-exit", action="store_true")
    parser.add_argument("--keep-intermediate", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    hard_grid = parse_grid(args.hard_stop_grid, allow_disabled=True)
    trailing_grid = parse_grid(args.trailing_stop_grid, allow_disabled=False)
    portfolios = ("main", "concentrated") if args.portfolio_kind == "both" else (args.portfolio_kind,)

    summary: dict[str, Any] = {
        "schema_version": "broker_position_risk_grid_sweep_v1",
        "latest_run": str(latest),
        "price_cache": str(price_cache),
        "hard_stop_grid": hard_grid,
        "trailing_stop_grid": trailing_grid,
        "trailing_activation": args.trailing_activation,
        "relative_trim_threshold": args.relative_trim_threshold,
        "relative_exit_threshold": args.relative_exit_threshold,
        "disable_distribution_exit": not bool(args.enable_distribution_exit),
        "production_activation_allowed": False,
        "review_only": True,
    }
    for portfolio in portfolios:
        result = evaluate_portfolio(
            portfolio=portfolio,
            latest=latest,
            price_cache=price_cache,
            output_dir=output_dir,
            hard_grid=hard_grid,
            trailing_grid=trailing_grid,
            trailing_activation=args.trailing_activation,
            relative_trim_threshold=args.relative_trim_threshold,
            relative_exit_threshold=args.relative_exit_threshold,
            disable_distribution_exit=not bool(args.enable_distribution_exit),
            keep_intermediate=args.keep_intermediate,
        )
        summary[portfolio] = result
        if result.get("status") in {"completed", "no_gate_passing_config"}:
            write_text(
                output_dir / portfolio / "report.md",
                render_report(
                    portfolio,
                    result["baseline_broker_ledger"],
                    result["ranked"],
                    result.get("champion"),
                    result.get("best_ranked"),
                ),
            )

    write_json(output_dir / "summary.json", summary)
    print(f"[broker_position_risk_grid_sweep] wrote {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
