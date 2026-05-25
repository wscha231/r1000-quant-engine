#!/usr/bin/env python3
"""Rank long crisis/liquidity signals against future drawdown labels."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_long_crisis_liquidity import rank_auc  # noqa: E402


DEFAULT_FEATURES = "data_pit/macro/long_crisis_daily_features.parquet"
DEFAULT_OUTPUT_DIR = "outputs/long_crisis_learning"
DEFAULT_LABEL = "future_63d_drawdown_le_15pct"

FEATURE_CANDIDATES = [
    "crisis_score",
    "cash_raise_confirmation_score",
    "liquidity_confirmation_score",
    "market_trend_damage_score",
    "volatility_stress_score",
    "credit_stress_score",
    "rate_shock_score",
    "vix_zscore_252d",
    "hy_oas_zscore_252d",
    "m2_6m_change_lag1m",
    "net_liquidity_13w_change_pct",
    "fed_assets_13w_change_pct",
    "reverse_repo_13w_change_pct",
    "tga_13w_change_pct",
    "dxy_ret_20d",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_features(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _corr(feature: pd.Series, label: pd.Series) -> float:
    d = pd.DataFrame({"feature": feature, "label": label}).dropna()
    if len(d) < 20 or d["feature"].nunique() < 2 or d["label"].nunique() < 2:
        return float("nan")
    return float(d["feature"].corr(d["label"], method="spearman"))


def render_report(summary: dict[str, Any], ranking: pd.DataFrame) -> str:
    lines = [
        "# Long Crisis Signal Learning",
        "",
        f"- status: `{summary.get('status')}`",
        f"- label: `{summary.get('label')}`",
        f"- rows: {summary.get('rows', 0)}",
        "",
        "## Top Signals",
        "",
        "| split | feature | auc | spearman | rows |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    if not ranking.empty:
        top = ranking.sort_values(["split", "auc"], ascending=[True, False]).groupby("split").head(5)
        for _, row in top.iterrows():
            lines.append(
                f"| {row['split']} | {row['feature']} | {row['auc']:.3f} | {row['spearman']:.3f} | {int(row['rows'])} |"
            )
    lines.extend(["", "Research-only; no production target book changes.", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    features_path = repo_path(args.features)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    features = read_features(features_path)
    label_col = args.label
    if features.empty or label_col not in features.columns:
        summary = {
            "status": "blocked",
            "reason": "missing features or label column",
            "features": str(features_path),
            "label": label_col,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "signal_learning_summary.json", summary)
        (output_dir / "signal_learning_report.md").write_text(render_report(summary, pd.DataFrame()), encoding="utf-8")
        print(json.dumps({"status": "blocked", "reason": summary["reason"]}, sort_keys=True))
        return summary

    rows: list[dict[str, Any]] = []
    splits = sorted(features.get("split", pd.Series(["all"] * len(features))).dropna().astype(str).unique().tolist())
    if "all" not in splits:
        splits.append("all")
    for split in splits:
        d = features if split == "all" else features[features["split"].astype(str).eq(split)]
        label = pd.to_numeric(d[label_col], errors="coerce")
        for feature in FEATURE_CANDIDATES:
            if feature not in d.columns:
                continue
            s = pd.to_numeric(d[feature], errors="coerce")
            # For liquidity contraction columns, negative values imply risk.
            if feature in {"m2_6m_change_lag1m", "net_liquidity_13w_change_pct", "fed_assets_13w_change_pct"}:
                s = -s
            auc = rank_auc(s, label)
            corr = _corr(s, label)
            rows.append(
                {
                    "split": split,
                    "feature": feature,
                    "rows": int(pd.DataFrame({"s": s, "l": label}).dropna().shape[0]),
                    "auc": float(auc) if not np.isnan(auc) else np.nan,
                    "spearman": float(corr) if not np.isnan(corr) else np.nan,
                }
            )
    ranking = pd.DataFrame(rows)
    ranking_path = output_dir / "feature_signal_ranking.csv"
    ranking.to_csv(ranking_path, index=False)
    summary = {
        "status": "completed",
        "schema_version": "long-crisis-signal-learning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "features": str(features_path),
        "label": label_col,
        "rows": int(len(features)),
        "ranking": str(ranking_path),
    }
    write_json(output_dir / "signal_learning_summary.json", summary)
    (output_dir / "signal_learning_report.md").write_text(render_report(summary, ranking), encoding="utf-8")
    print(json.dumps({"status": "completed", "rows": int(len(features)), "ranking_rows": int(len(ranking))}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default=DEFAULT_FEATURES)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

