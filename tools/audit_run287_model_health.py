#!/usr/bin/env python3
"""Build review-only data, feature, prediction, and performance drift audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HEADS = (
    "pred_lin_ret", "pred_lin_p", "pred_future_winner_ret",
    "pred_future_winner_p", "pred_cat_ret", "pred_cat_p",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def git_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=False, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path), "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_series(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    return out[np.isfinite(out)]


def deduplicate(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in ("decision_date", "ticker", "source_bundle_sha256") if column in frame]
    return frame.sort_values(columns, kind="mergesort").drop_duplicates(["decision_date", "ticker"], keep="first")


def parse_feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    index: list[tuple[str, str]] = []
    for row in frame[["decision_date", "ticker", "raw_model_features_json"]].itertuples(index=False):
        try:
            payload = json.loads(row.raw_model_features_json) if row.raw_model_features_json else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}
        rows.append(payload)
        index.append((str(row.decision_date), str(row.ticker)))
    matrix = pd.DataFrame(rows, index=pd.MultiIndex.from_tuples(index, names=["decision_date", "ticker"]))
    return matrix.apply(pd.to_numeric, errors="coerce")


def psi(base: pd.Series, current: pd.Series, bins: int = 10) -> float | None:
    base = finite_series(base)
    current = finite_series(current)
    if len(base) < 2 or len(current) < 2:
        return None
    edges = np.unique(np.quantile(base, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0 if float(base.mean()) == float(current.mean()) else None
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.histogram(base, bins=edges)[0] / len(base)
    c = np.histogram(current, bins=edges)[0] / len(current)
    b, c = np.clip(b, 1e-6, None), np.clip(c, 1e-6, None)
    return float(np.sum((c - b) * np.log(c / b)))


def ks_stat(base: pd.Series, current: pd.Series) -> float | None:
    base = np.sort(finite_series(base).to_numpy())
    current = np.sort(finite_series(current).to_numpy())
    if len(base) < 2 or len(current) < 2:
        return None
    values = np.sort(np.unique(np.concatenate([base, current])))
    base_cdf = np.searchsorted(base, values, side="right") / len(base)
    current_cdf = np.searchsorted(current, values, side="right") / len(current)
    return float(np.max(np.abs(base_cdf - current_cdf)))


def data_drift(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for date, group in frame.groupby("decision_date", sort=True):
        coverage = finite_series(group["raw_model_feature_finite_ratio"])
        rows.append(
            {
                "status": "OBSERVED_COVERAGE_ONLY",
                "decision_date": date,
                "ticker_count": int(group["ticker"].nunique()),
                "raw_feature_finite_ratio_mean": float(coverage.mean()) if len(coverage) else None,
                "raw_feature_finite_ratio_min": float(coverage.min()) if len(coverage) else None,
                "stale_source_ratio": None,
                "pit_block_ratio": None,
                "stale_source_status": "NOT_AVAILABLE_IN_CURRENT_DECISION_FRAME",
                "pit_status": "PIT_UNIVERSE_LABEL_NOT_CLEAN",
            }
        )
    return pd.DataFrame(rows)


def feature_drift(matrix: pd.DataFrame) -> pd.DataFrame:
    dates = sorted(matrix.index.get_level_values("decision_date").unique())
    if not dates:
        return pd.DataFrame(columns=["status", "baseline_date", "current_date", "feature", "psi", "ks"])
    baseline_date, current_date = dates[0], dates[-1]
    baseline, current = matrix.loc[baseline_date], matrix.loc[current_date]
    status = "COMPLETED_DRIFT_COMPARISON" if baseline_date != current_date else "UNDERPOWERED_SINGLE_DECISION_DATE"
    rows = []
    for feature in sorted(matrix.columns):
        rows.append(
            {
                "status": status,
                "baseline_date": baseline_date,
                "current_date": current_date,
                "feature": feature,
                "baseline_finite_count": int(finite_series(baseline[feature]).shape[0]),
                "current_finite_count": int(finite_series(current[feature]).shape[0]),
                "psi": psi(baseline[feature], current[feature]) if baseline_date != current_date else None,
                "ks": ks_stat(baseline[feature], current[feature]) if baseline_date != current_date else None,
            }
        )
    return pd.DataFrame(rows)


def entropy(weights: list[float]) -> float | None:
    clean = np.array([x for x in weights if math.isfinite(x) and x > 0], dtype=float)
    if not len(clean):
        return None
    clean /= clean.sum()
    return float(-(clean * np.log(clean)).sum())


def prediction_drift(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    columns = [f"registered_{head}" for head in HEADS]
    for date, group in frame.groupby("decision_date", sort=True):
        numeric = group.reindex(columns=columns).apply(pd.to_numeric, errors="coerce")
        correlations = numeric.corr(method="spearman", min_periods=20)
        weights = [
            float(pd.to_numeric(group[column], errors="coerce").dropna().iloc[0])
            for column in ("ensemble_weight_linear", "ensemble_weight_catboost", "ensemble_weight_ranker")
            if column in group and pd.to_numeric(group[column], errors="coerce").notna().any()
        ]
        correlation_json = correlations.round(10).to_json(orient="split")
        for column in columns:
            values = finite_series(numeric[column])
            rows.append(
                {
                    "status": "OBSERVED_PREDICTION_DISTRIBUTION",
                    "decision_date": date,
                    "head": column.removeprefix("registered_"),
                    "finite_count": int(len(values)),
                    "mean": float(values.mean()) if len(values) else None,
                    "std": float(values.std(ddof=0)) if len(values) else None,
                    "p05": float(values.quantile(0.05)) if len(values) else None,
                    "p50": float(values.quantile(0.50)) if len(values) else None,
                    "p95": float(values.quantile(0.95)) if len(values) else None,
                    "ensemble_weight_entropy": entropy(weights),
                    "head_spearman_correlation_json": correlation_json,
                }
            )
    return pd.DataFrame(rows)


def performance_drift(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ret_col = "outcome_63d_ticker_total_return"
    status_col = "outcome_63d_status"
    for date, group in frame.groupby("decision_date", sort=True):
        if ret_col in group and status_col in group:
            resolved = group[group[status_col].eq("completed")].copy()
            resolved[ret_col] = pd.to_numeric(resolved[ret_col], errors="coerce")
            resolved = resolved[resolved[ret_col].notna()]
        else:
            resolved = group.iloc[0:0].copy()
        selected = resolved[resolved["selector_selected"].fillna(False).astype(bool)] if len(resolved) else resolved
        control = resolved[
            ~resolved["selector_selected"].fillna(False).astype(bool)
            & resolved["published_ranking_eligible"].fillna(False).astype(bool)
        ] if len(resolved) else resolved
        score = pd.to_numeric(resolved.get("published_score"), errors="coerce") if len(resolved) else pd.Series(dtype=float)
        rank_ic = score.corr(resolved[ret_col], method="spearman") if len(resolved) >= 20 else None
        mae_col, mfe_col = "outcome_63d_ticker_mae", "outcome_63d_ticker_mfe"
        rows.append(
            {
                "status": "COMPLETED_63D_MODEL_HEALTH" if len(resolved) >= 200 else "UNDERPOWERED_63D_MODEL_HEALTH",
                "decision_date": date,
                "resolved_63d_count": int(len(resolved)),
                "distinct_ticker_count": int(resolved["ticker"].nunique()) if len(resolved) else 0,
                "rank_ic_63d": float(rank_ic) if rank_ic is not None and math.isfinite(rank_ic) else None,
                "selected_count": int(len(selected)),
                "control_count": int(len(control)),
                "selected_control_spread_63d": float(selected[ret_col].mean() - control[ret_col].mean()) if len(selected) and len(control) else None,
                "selected_hit_rate_63d": float(selected[ret_col].gt(0).mean()) if len(selected) else None,
                "selected_mae_63d": float(pd.to_numeric(selected[mae_col], errors="coerce").mean()) if len(selected) and mae_col in selected else None,
                "selected_mfe_63d": float(pd.to_numeric(selected[mfe_col], errors="coerce").mean()) if len(selected) and mfe_col in selected else None,
            }
        )
    return pd.DataFrame(rows)


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = repo_path(args.ledger_dir)
    input_path = repo_path(args.current_status) if args.current_status else ledger_dir / "current_status.parquet"
    output_dir = repo_path(args.output_dir) if args.output_dir else ledger_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    frame = pd.read_parquet(input_path) if input_path.is_file() else pd.DataFrame()
    if frame.empty:
        blockers.append("current_status_missing_or_empty")
    required = {"decision_date", "ticker", "raw_model_features_json", "raw_model_feature_finite_ratio"}
    blockers.extend(f"missing_column:{column}" for column in sorted(required - set(frame.columns)))
    if not blockers:
        frame = deduplicate(frame)
        matrix = parse_feature_matrix(frame)
        products = {
            "data_drift.csv": data_drift(frame),
            "feature_drift.csv": feature_drift(matrix),
            "prediction_drift.csv": prediction_drift(frame),
            "performance_drift.csv": performance_drift(frame),
        }
    else:
        products = {name: pd.DataFrame() for name in ("data_drift.csv", "feature_drift.csv", "prediction_drift.csv", "performance_drift.csv")}
    for name, product in products.items():
        product.to_csv(output_dir / name, index=False, lineterminator="\n")
    decision_dates = int(frame["decision_date"].nunique()) if "decision_date" in frame else 0
    resolved = int(frame.get("outcome_63d_status", pd.Series(dtype=str)).eq("completed").sum())
    status = "BLOCKED_MODEL_HEALTH" if blockers else (
        "READY_MODEL_HEALTH_REVIEW_ONLY" if decision_dates >= 26 and resolved >= 200 else "UNDERPOWERED_MODEL_HEALTH_HISTORY"
    )
    payload = {
        "schema_version": "run287-model-health-v1",
        "status": status,
        "generated_at_utc": args.generated_at_utc,
        "git_head": git_head(),
        "blockers": blockers,
        "decision_date_count": decision_dates,
        "unique_ticker_count": int(frame["ticker"].nunique()) if "ticker" in frame else 0,
        "resolved_63d_count": resolved,
        "automatic_retraining_allowed": False,
        "automatic_promotion_allowed": False,
        "pit_universe_label_clean": False,
        "outputs": {name: fingerprint(output_dir / name) for name in products},
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    write_json(output_dir / "model_health_manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", default="outputs/run287_decision_outcome_ledger")
    parser.add_argument("--current-status")
    parser.add_argument("--output-dir")
    parser.add_argument("--generated-at-utc", default="2026-07-16T00:00:00Z")
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(2 if result["status"].startswith("BLOCKED") else 0)
