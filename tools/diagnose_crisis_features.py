#!/usr/bin/env python3
"""Run the NEW crisis_score function over an EXISTING daily_features.parquet.

Pure-function diagnosis: takes the features built by a prior Full Rebuild
(or staged in by the sidecar-only verify workflow) and emits the coverage
breakdown + score distribution the renormalized formula produces.

Together with run_integrated_leader_crisis_replay this lets the fix be
validated without re-collecting macro data or re-running the walk-forward
pipeline. Read-only on the input parquet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_crisis_signal_builder import (  # noqa: E402
    CRISIS_COMPONENT_WEIGHTS,
    composite_crisis_coverage,
    compute_composite_crisis_score,
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def diagnose(features_path: Path) -> dict[str, Any]:
    if not features_path.exists():
        return {"status": "missing", "features": str(features_path)}
    features = pd.read_parquet(features_path)
    coverage = composite_crisis_coverage(features)
    live = sorted(name for name, info in coverage.items() if info["live"])
    dead = sorted(name for name, info in coverage.items() if not info["live"])
    nominal_live_weight = sum(CRISIS_COMPONENT_WEIGHTS[n] for n in live)

    # NEW score (renormalized) — what the fixed code would emit.
    new_score = compute_composite_crisis_score(features)
    # OLD score (pre-fix weighted sum) — for an apples-to-apples delta.
    old_components = {
        "market_trend": (0.25, _market_trend(features)),
        "credit_stress": (0.20, _series(features, "hy_oas_zscore_60d", divisor=3.0)),
        "vol_spike": (0.15, _series(features, "vix_zscore_60d", divisor=3.0)),
        "breadth": (0.15, _breadth(features)),
        "liquidity": (0.10, pd.Series(0.0, index=features.index)),
        "rate_shock": (0.10, _series(features, "ten_year_5d_change_bps", divisor=50.0, take_abs=True)),
        "portfolio_damage": (0.05, pd.Series(0.0, index=features.index)),
    }
    old_score = sum(w * s for w, s in old_components.values())
    if isinstance(old_score, pd.Series):
        old_score = old_score.clip(0.0, 1.0)

    def stats(s: pd.Series) -> dict[str, float]:
        if s is None or s.empty:
            return {"max": 0.0, "p99": 0.0, "p95": 0.0, "p90": 0.0, "mean": 0.0, "days_caution": 0, "days_defense": 0, "days_crisis": 0}
        s = pd.to_numeric(s, errors="coerce").dropna()
        return {
            "max": float(s.max()),
            "p99": float(s.quantile(0.99)),
            "p95": float(s.quantile(0.95)),
            "p90": float(s.quantile(0.90)),
            "mean": float(s.mean()),
            "days_caution_default": int((s >= 0.30).sum()),
            "days_defense_default": int((s >= 0.50).sum()),
            "days_crisis_default": int((s >= 0.70).sum()),
        }

    return {
        "status": "ok",
        "features_path": str(features_path),
        "rows": int(len(features)),
        "first_date": str(features.index.min().date()) if len(features) else "",
        "last_date": str(features.index.max().date()) if len(features) else "",
        "live_components": live,
        "dead_components": dead,
        "pre_renorm_ceiling": float(nominal_live_weight),
        "renormalization_active": bool(dead and nominal_live_weight < 1.0),
        "component_coverage": coverage,
        "score_new": stats(new_score),
        "score_old_for_comparison": stats(old_score),
    }


def _series(features: pd.DataFrame, col: str, *, divisor: float, take_abs: bool = False) -> pd.Series:
    if col not in features.columns:
        return pd.Series(0.0, index=features.index)
    s = pd.to_numeric(features[col], errors="coerce").fillna(0.0)
    if take_abs:
        s = s.abs()
    return (s / float(divisor)).clip(0.0, 1.0)


def _market_trend(features: pd.DataFrame) -> pd.Series:
    if "spy_below_ma200" not in features or "spy_20d_dd" not in features:
        return pd.Series(0.0, index=features.index)
    return (
        features["spy_below_ma200"].fillna(0) * 0.5
        + (-features["spy_20d_dd"].clip(upper=0).fillna(0) / 0.15) * 0.5
    ).clip(0.0, 1.0)


def _breadth(features: pd.DataFrame) -> pd.Series:
    if "spy_below_ma200" not in features or "qqq_below_ma200" not in features:
        return pd.Series(0.0, index=features.index)
    return (
        features["spy_below_ma200"].fillna(0) * 0.5
        + features["qqq_below_ma200"].fillna(0) * 0.5
    ).clip(0.0, 1.0)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--features", required=True, help="Path to daily_features.parquet")
    p.add_argument("--output", default="outputs/sidecar_only_verify/crisis_features_diagnosis.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = diagnose(repo_path(args.features))
    out = repo_path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        f"[crisis-diagnose] status={payload.get('status')}"
        + (
            f" live={payload.get('live_components')}"
            f" dead={payload.get('dead_components')}"
            f" pre_renorm_ceiling={payload.get('pre_renorm_ceiling')}"
            f" new_max={payload.get('score_new', {}).get('max')}"
            f" old_max={payload.get('score_old_for_comparison', {}).get('max')}"
            if payload.get("status") == "ok"
            else ""
        )
    )
    return 0 if payload.get("status") in {"ok", "missing"} else 2


if __name__ == "__main__":
    sys.exit(main())
