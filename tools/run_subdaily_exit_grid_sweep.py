#!/usr/bin/env python3
"""Sub-monthly exit stop-threshold grid sweep (Stage T2b).

Runs `run_position_risk_weekly_validation.py` with multiple
(hard_stop, trailing_stop) combinations on a fixed source full-rebuild run,
ranks every combo by a composite of CAGR + scaled MaxDD reduction vs the
monthly broker-ledger baseline, and writes a champion candidate. Research-only —
the winner config is NOT auto-promoted into production; it becomes a
candidate for explicit broker-ledger gate validation.

Why this exists: Stage T2 (run_subdaily_exit_compare) showed that PRWV's
default -8% hard / -15% trailing is "expensive" — MDD improves but CAGR
collapses. Diagnosis: the -8% hard_stop fires 95% of all exits. The
correct response is to find a stop pair where CAGR retention is high AND
crisis-window MaxDD is meaningfully better than monthly broker baseline.

Usage:
  python tools/run_subdaily_exit_grid_sweep.py \\
      --latest-run cloud_results/full_rebuild/latest_global_alpha_universe \\
      --price-cache cache_prices \\
      --output-dir outputs/subdaily_exit_grid_sweep \\
      --portfolio-kind main \\
      --hard-stop-grid -0.08,-0.10,-0.12,-0.15,disabled \\
      --trailing-stop-grid -0.15,-0.18,-0.22

`disabled` for hard_stop is encoded as a very-large negative (-1.0) which
PRWV's hard_stop check treats as never-firing in practice.
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


PRWV_TOOL = REPO_ROOT / "tools" / "run_position_risk_weekly_validation.py"

DEFAULT_HARD_GRID = "-0.08,-0.10,-0.12,-0.15,disabled"
DEFAULT_TRAILING_GRID = "-0.15,-0.18,-0.22"
DEFAULT_TRAILING_ACTIVATION = 0.15
DISABLED_HARD_STOP_VALUE = -1.0  # PRWV treats this as effectively never-firing.

# Composite score: CAGR (full weight) + MDD improvement vs baseline (0.5 weight).
# MaxDD is negative; baseline_mdd - overlay_mdd positive when overlay is shallower.
# Penalty for hard CAGR regression: -0.5 * max(0, baseline_cagr - overlay_cagr - 0.05).
DEFAULT_COMPOSITE_WEIGHTS = {
    "cagr_weight": 1.0,
    "mdd_improvement_weight": 0.5,
    "cagr_drag_penalty_threshold_pp": 5.0,   # CAGR drop beyond 5pp triggers extra penalty
    "cagr_drag_penalty_weight": 0.5,
}


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def parse_grid(spec: str, allow_disabled: bool = False) -> list[float]:
    out: list[float] = []
    for raw in spec.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token in {"disabled", "off", "none"}:
            if not allow_disabled:
                raise ValueError(f"`disabled` not allowed in this grid: {spec!r}")
            out.append(DISABLED_HARD_STOP_VALUE)
        else:
            out.append(float(token))
    return out


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


def baseline_for(latest: Path, portfolio: str) -> dict[str, Any]:
    """Pull broker-ledger monthly baseline for the portfolio."""
    m = load_json(latest / "broker_replay" / portfolio / "metrics.json")
    return {
        "cagr": safe_float(m.get("cagr")),
        "max_dd": safe_float(m.get("max_dd")),
        "sharpe": safe_float(m.get("sharpe")),
        "trade_count": int(safe_float(m.get("trade_count"))),
        "available": bool(m),
    }


def holdings_path_for(latest: Path, portfolio: str) -> tuple[Path, Path]:
    """Where PRWV looks for monthly holdings + period map."""
    if portfolio == "main":
        return (
            latest / "reports" / "main_monthly_weights.csv",
            latest / "reports" / "regime_by_month.csv",
        )
    if portfolio == "concentrated":
        return (
            latest / "reports" / "concentrated_strategy_holdings.csv",
            latest / "reports" / "concentrated_strategy_monthly.csv",
        )
    raise ValueError(f"unknown portfolio_kind: {portfolio!r}")


def score_composite(
    overlay_cagr: float,
    overlay_max_dd: float,
    baseline: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Composite score for ranking overlay combos."""
    w = dict(DEFAULT_COMPOSITE_WEIGHTS)
    if weights:
        w.update(weights)
    bcagr = float(baseline.get("cagr", 0.0))
    bmdd = float(baseline.get("max_dd", 0.0))
    cagr_term = float(w["cagr_weight"]) * overlay_cagr
    # MDD improvement positive when overlay's negative drawdown is shallower than baseline's.
    mdd_imp = (overlay_max_dd - bmdd)  # both negative; positive = improvement
    mdd_term = float(w["mdd_improvement_weight"]) * mdd_imp
    # Penalty for excessive CAGR regression beyond the threshold.
    cagr_gap_pp = (bcagr - overlay_cagr) * 100.0
    extra_drag = max(0.0, cagr_gap_pp - float(w["cagr_drag_penalty_threshold_pp"]))
    drag_penalty = float(w["cagr_drag_penalty_weight"]) * (extra_drag / 100.0)
    composite = cagr_term + mdd_term - drag_penalty
    return {
        "composite": float(composite),
        "cagr_term": float(cagr_term),
        "mdd_improvement_pp": float(mdd_imp * 100.0),
        "mdd_term": float(mdd_term),
        "cagr_gap_pp": float(cagr_gap_pp),
        "drag_penalty": float(drag_penalty),
    }


def label_for_stop(value: float) -> str:
    if value <= DISABLED_HARD_STOP_VALUE + 1e-9:
        return "disabled"
    return f"{value:+.2%}"


def rank_grid(
    combos: Sequence[tuple[float, float]],
    overlay_metrics_loader: Callable[[float, float], dict[str, Any]],
    baseline: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Score every combo, rank by composite descending. Pure function for testing."""
    rows: list[dict[str, Any]] = []
    for hard, trailing in combos:
        metrics = overlay_metrics_loader(hard, trailing)
        if metrics.get("status") != "completed":
            rows.append(
                {
                    "hard_stop": hard,
                    "hard_stop_label": label_for_stop(hard),
                    "trailing_stop": trailing,
                    "trailing_stop_label": label_for_stop(trailing),
                    "status": metrics.get("status") or "missing",
                    "composite": float("-inf"),
                }
            )
            continue
        overlay_cagr = safe_float(metrics.get("cagr"))
        overlay_mdd = safe_float(metrics.get("max_dd"))
        score = score_composite(overlay_cagr, overlay_mdd, baseline, weights=weights)
        rows.append(
            {
                "hard_stop": hard,
                "hard_stop_label": label_for_stop(hard),
                "trailing_stop": trailing,
                "trailing_stop_label": label_for_stop(trailing),
                "status": "ok",
                "overlay_cagr": overlay_cagr,
                "overlay_max_dd": overlay_mdd,
                "overlay_sharpe": safe_float(metrics.get("sharpe")),
                "overlay_exit_count": int(safe_float(metrics.get("exit_count"))),
                "overlay_trim_count": int(safe_float(metrics.get("trim_count"))),
                **score,
            }
        )
    return sorted(rows, key=lambda r: r["composite"], reverse=True)


def run_prwv(
    hard: float,
    trailing: float,
    trailing_activation: float,
    latest: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio: str,
    python_exec: str | None = None,
) -> dict[str, Any]:
    holdings, period_map = holdings_path_for(latest, portfolio)
    if not holdings.exists() or not period_map.exists():
        return {"status": "missing_inputs"}
    py = python_exec or sys.executable
    cmd = [
        py, str(PRWV_TOOL),
        "--holdings", str(holdings),
        "--period-map", str(period_map),
        "--price-cache", str(price_cache),
        "--portfolio-kind", portfolio,
        "--output-dir", str(output_dir),
        "--hard-stop", str(hard),
        "--trailing-stop", str(trailing),
        "--trailing-activation", str(trailing_activation),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"status": "prwv_failed", "stderr_tail": proc.stderr[-400:]}
    return load_json(output_dir / "metrics.json")


def champion_from_ranked(ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ranked:
        return None
    for row in ranked:
        if row.get("status") == "ok":
            return row
    return None


def render_report(portfolio: str, baseline: dict[str, Any], ranked: list[dict[str, Any]]) -> str:
    lines = [f"# Sub-Monthly Exit Stop-Threshold Grid Sweep — {portfolio}", ""]
    lines.append(
        "Composite = `cagr_weight × overlay_cagr + mdd_improvement_weight × (overlay_max_dd − baseline_max_dd) − drag_penalty`. "
        "Drag_penalty fires only when CAGR drops more than 5pp vs baseline."
    )
    lines.append("")
    lines.append(
        f"Baseline (broker monthly): CAGR `{baseline.get('cagr', 0.0):.2%}` / MaxDD `{baseline.get('max_dd', 0.0):.2%}` / Sharpe `{baseline.get('sharpe', 0.0):.4f}`"
    )
    lines.append("")
    lines.append("| rank | hard_stop | trailing_stop | overlay_cagr | overlay_max_dd | cagr_gap_pp | mdd_imp_pp | exits | trims | composite |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, row in enumerate(ranked, 1):
        if row.get("status") != "ok":
            lines.append(
                f"| {i} | {row.get('hard_stop_label', '?')} | {row.get('trailing_stop_label', '?')} | — | — | — | — | — | — | `{row.get('status', '?')}` |"
            )
            continue
        lines.append(
            f"| {i} | `{row['hard_stop_label']}` | `{row['trailing_stop_label']}` | {row['overlay_cagr']:.2%} | {row['overlay_max_dd']:.2%} | "
            f"{row['cagr_gap_pp']:+.2f} | {row['mdd_improvement_pp']:+.2f} | {row['overlay_exit_count']} | {row['overlay_trim_count']} | `{row['composite']:.4f}` |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/subdaily_exit_grid_sweep")
    parser.add_argument("--portfolio-kind", default="main", choices=("main", "concentrated", "both"))
    parser.add_argument("--hard-stop-grid", default=DEFAULT_HARD_GRID)
    parser.add_argument("--trailing-stop-grid", default=DEFAULT_TRAILING_GRID)
    parser.add_argument("--trailing-activation", type=float, default=DEFAULT_TRAILING_ACTIVATION)
    parser.add_argument(
        "--keep-intermediate", action="store_true",
        help="keep per-combo PRWV output dirs (default deletes them after metrics.json is captured)",
    )
    return parser.parse_args()


def evaluate_portfolio(
    portfolio: str,
    latest: Path,
    price_cache: Path,
    out_dir: Path,
    hard_grid: list[float],
    trailing_grid: list[float],
    trailing_activation: float,
    keep_intermediate: bool = False,
) -> dict[str, Any]:
    baseline = baseline_for(latest, portfolio)
    if not baseline["available"]:
        return {"portfolio": portfolio, "status": "missing_baseline"}

    work_dir = out_dir / portfolio / "_combos"
    work_dir.mkdir(parents=True, exist_ok=True)

    combo_metrics: dict[tuple[float, float], dict[str, Any]] = {}

    def loader(hard: float, trailing: float) -> dict[str, Any]:
        if (hard, trailing) in combo_metrics:
            return combo_metrics[(hard, trailing)]
        sub_out = work_dir / f"hard_{hard:.4f}_trail_{trailing:.4f}".replace("-", "neg")
        sub_out.mkdir(parents=True, exist_ok=True)
        metrics = run_prwv(hard, trailing, trailing_activation, latest, price_cache, sub_out, portfolio)
        combo_metrics[(hard, trailing)] = metrics
        return metrics

    combos = [(h, t) for h in hard_grid for t in trailing_grid]
    ranked = rank_grid(combos, loader, baseline)

    if not keep_intermediate:
        shutil.rmtree(work_dir, ignore_errors=True)

    champion = champion_from_ranked(ranked)
    return {
        "portfolio": portfolio,
        "schema_version": "subdaily_exit_grid_sweep_v1",
        "baseline_broker_ledger_monthly": baseline,
        "combos_evaluated": len(combos),
        "ranked": ranked,
        "champion": champion,
        "trailing_activation": trailing_activation,
        "production_activation_allowed": False,
    }


def main() -> int:
    args = parse_args()
    latest = repo_path(args.latest_run)
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    price_cache = repo_path(args.price_cache)

    hard_grid = parse_grid(args.hard_stop_grid, allow_disabled=True)
    trailing_grid = parse_grid(args.trailing_stop_grid, allow_disabled=False)

    summary: dict[str, Any] = {
        "schema_version": "subdaily_exit_grid_sweep_v1",
        "latest_run": str(latest),
        "hard_stop_grid": hard_grid,
        "trailing_stop_grid": trailing_grid,
        "trailing_activation": args.trailing_activation,
    }
    portfolios = ("main", "concentrated") if args.portfolio_kind == "both" else (args.portfolio_kind,)
    for portfolio in portfolios:
        block = evaluate_portfolio(
            portfolio, latest, price_cache, out_dir,
            hard_grid, trailing_grid, args.trailing_activation,
            keep_intermediate=args.keep_intermediate,
        )
        summary[portfolio] = block
        if block.get("status") == "missing_baseline":
            continue
        write_text(
            out_dir / portfolio / "report.md",
            render_report(portfolio, block["baseline_broker_ledger_monthly"], block["ranked"]),
        )

    write_json(out_dir / "summary.json", summary)
    print(f"[subdaily_exit_grid_sweep] wrote {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
