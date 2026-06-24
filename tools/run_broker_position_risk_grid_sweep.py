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
import json
import math
import shutil
import subprocess
import sys
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
                **score_composite(overlay_cagr, overlay_mdd, baseline, weights=weights),
            }
        )
    return sorted(rows, key=lambda row: row["composite"], reverse=True)


def champion_from_ranked(ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in ranked:
        if row.get("status") == "ok":
            return row
    return None


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
    return payload


def render_report(portfolio: str, baseline: dict[str, Any], ranked: list[dict[str, Any]]) -> str:
    lines = [f"# Broker Position-Risk Grid Sweep - {portfolio}", ""]
    lines.append("Research-only broker-style daily-stop grid. It uses next-close account-ledger fills, integer shares, fees, and cash ledger.")
    lines.append("Production activation remains false; any candidate still needs explicit review and a full official run.")
    lines.append("")
    lines.append(
        f"Baseline broker replay: CAGR `{baseline.get('cagr', 0.0):.2%}` / MaxDD `{baseline.get('max_dd', 0.0):.2%}` / Sharpe `{baseline.get('sharpe', 0.0):.3f}`"
    )
    lines.append("")
    lines.append("| rank | hard | trailing | CAGR | MaxDD | cagr_gap_pp | mdd_imp_pp | exits | trades | composite |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for idx, row in enumerate(ranked, 1):
        if row.get("status") != "ok":
            lines.append(
                f"| {idx} | `{row.get('hard_stop_label', '?')}` | `{row.get('trailing_stop_label', '?')}` | - | - | - | - | - | - | `{row.get('status', '?')}` |"
            )
            continue
        lines.append(
            f"| {idx} | `{row['hard_stop_label']}` | `{row['trailing_stop_label']}` | {row['overlay_cagr']:.2%} | {row['overlay_max_dd']:.2%} | "
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
    ranked = rank_grid(combos, loader, baseline)
    champion = champion_from_ranked(ranked)
    if not keep_intermediate:
        shutil.rmtree(combo_dir, ignore_errors=True)
    return {
        "schema_version": "broker_position_risk_grid_sweep_v1",
        "portfolio": portfolio,
        "status": "completed",
        "target_book": str(target_book),
        "baseline_broker_ledger": baseline,
        "combos_evaluated": len(combos),
        "hard_stop_grid": hard_grid,
        "trailing_stop_grid": trailing_grid,
        "trailing_activation": trailing_activation,
        "relative_trim_threshold": relative_trim_threshold,
        "relative_exit_threshold": relative_exit_threshold,
        "disable_distribution_exit": bool(disable_distribution_exit),
        "ranked": ranked,
        "champion": champion,
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
        if result.get("status") == "completed":
            write_text(output_dir / portfolio / "report.md", render_report(portfolio, result["baseline_broker_ledger"], result["ranked"]))

    write_json(output_dir / "summary.json", summary)
    print(f"[broker_position_risk_grid_sweep] wrote {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
