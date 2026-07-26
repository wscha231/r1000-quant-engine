#!/usr/bin/env python3
"""auto_learning_promote - proposal-only champion/challenger eligibility check.

This is the non-mutating evidence layer for AlphaTrade-style learning.

Expected use in a challenger workflow:
  1. Generate a candidate gate file from trade insights.
  2. Run a rebuild with that candidate active.
  3. Run this tool against the rebuild metrics.
  4. If the hard gates pass, emit an eligible-for-review decision.

The tool is intentionally conservative. It never invents weights and it never
touches model code or the active champion artifact. Human review and a separate,
explicitly approved change are required to alter the active gate file.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAIN_METRICS = ROOT / "outputs" / "backtest_metrics.json"
DEFAULT_CONC_METRICS = ROOT / "outputs" / "concentrated_backtest_metrics.json"
DEFAULT_GRADES = ROOT / "outputs" / "trade_journal" / "grades.csv"
DEFAULT_CANDIDATE = ROOT / "research" / "auto_feature_gates_candidate.yaml"
DEFAULT_ACTIVE = ROOT / "research" / "auto_feature_gates.yaml"
DEFAULT_DECISION = ROOT / "outputs" / "auto_learning" / "promotion_decision.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _metric(metrics: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in metrics:
            try:
                return float(metrics[name])
            except (TypeError, ValueError):
                return default
    return default


def _count_trade_grades(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        import pandas as pd

        if path.suffix.lower() == ".parquet":
            return int(len(pd.read_parquet(path)))
        return int(len(pd.read_csv(path)))
    except Exception:
        return 0


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    main = _load_json(Path(args.main_metrics))
    conc = _load_json(Path(args.concentrated_metrics))
    candidate = Path(args.candidate_gates)
    active = Path(args.active_gates)
    grades_path = Path(args.grades)

    main_cagr = _metric(main, "cagr", "strategy_cagr")
    main_sharpe = _metric(main, "sharpe")
    main_max_dd = _metric(main, "max_dd")
    conc_cagr = _metric(conc, "strategy_cagr", "cagr")
    trade_count = _count_trade_grades(grades_path)

    max_cagr_regression = float(args.max_cagr_regression_pp) / 100.0
    max_dd_worsening = float(args.max_dd_worsening_pp) / 100.0

    checks = {
        "candidate_exists": candidate.exists(),
        "main_cagr_floor": main_cagr >= float(args.baseline_cagr) - max_cagr_regression,
        "main_sharpe_floor": main_sharpe >= float(args.baseline_sharpe) - float(args.max_sharpe_regression),
        "main_max_dd_floor": main_max_dd >= float(args.baseline_max_dd) - max_dd_worsening,
        "concentrated_cagr_floor": conc_cagr >= float(args.concentrated_cagr_floor),
        "trade_count_floor": trade_count >= int(args.min_trades),
    }
    eligible_for_review = all(checks.values())
    reasons = [name for name, ok in checks.items() if not ok]

    decision = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Legacy consumers treat approved as permission to promote. Keep it
        # fail-closed and expose positive evidence only via eligible_for_review.
        "approved": False,
        "eligible_for_review": bool(eligible_for_review),
        "automatic_promotion_allowed": False,
        "proposal_only": True,
        "dry_run": True,
        "reasons": reasons,
        "checks": checks,
        "metrics": {
            "main_cagr": main_cagr,
            "main_sharpe": main_sharpe,
            "main_max_dd": main_max_dd,
            "concentrated_cagr": conc_cagr,
            "trade_count": trade_count,
        },
        "thresholds": {
            "baseline_cagr": float(args.baseline_cagr),
            "baseline_sharpe": float(args.baseline_sharpe),
            "baseline_max_dd": float(args.baseline_max_dd),
            "max_cagr_regression_pp": float(args.max_cagr_regression_pp),
            "max_sharpe_regression": float(args.max_sharpe_regression),
            "max_dd_worsening_pp": float(args.max_dd_worsening_pp),
            "concentrated_cagr_floor": float(args.concentrated_cagr_floor),
            "min_trades": int(args.min_trades),
        },
        "candidate_gates": str(candidate),
        "active_gates": str(active),
        "promoted": False,
    }

    return decision


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--main-metrics", default=str(DEFAULT_MAIN_METRICS))
    p.add_argument("--concentrated-metrics", default=str(DEFAULT_CONC_METRICS))
    p.add_argument("--grades", default=str(DEFAULT_GRADES))
    p.add_argument("--candidate-gates", default=str(DEFAULT_CANDIDATE))
    p.add_argument("--active-gates", default=str(DEFAULT_ACTIVE))
    p.add_argument("--decision-out", default=str(DEFAULT_DECISION))
    p.add_argument("--baseline-cagr", type=float, default=0.2451)
    p.add_argument("--baseline-sharpe", type=float, default=1.2453)
    p.add_argument("--baseline-max-dd", type=float, default=-0.2579)
    p.add_argument("--max-cagr-regression-pp", type=float, default=1.0)
    p.add_argument("--max-sharpe-regression", type=float, default=0.08)
    p.add_argument("--max-dd-worsening-pp", type=float, default=1.0)
    p.add_argument("--concentrated-cagr-floor", type=float, default=0.30)
    p.add_argument("--min-trades", type=int, default=250)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Deprecated compatibility flag; this command is always proposal-only.",
    )
    args = p.parse_args()

    decision = evaluate(args)
    out_path = Path(args.decision_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(decision, indent=2, sort_keys=True), encoding="utf-8")

    status = "ELIGIBLE_FOR_REVIEW" if decision["eligible_for_review"] else "BLOCKED"
    print(f"[auto-learning] {status}: {out_path}")
    if decision["reasons"]:
        print("[auto-learning] reasons: " + ", ".join(decision["reasons"]))
    print("[auto-learning] proposal-only: active gates were not modified")
    return 0 if decision["eligible_for_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
