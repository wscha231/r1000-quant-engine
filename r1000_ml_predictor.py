"""r1000_ml_predictor - Apply trained LightGBM to predict forward 3m returns.

Loads the model trained by r1000_pattern_miner.py and produces predictions for
all R1000 names using the latest feature_store snapshot.

Output:
  outputs/discovered_rules/predictions_latest.csv
    columns: ticker, predicted_r3m_pct, decile, confidence_band

Usage:
  py -3 r1000_ml_predictor.py
  py -3 r1000_ml_predictor.py --feature-store path/to/parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd


def load_artifacts(model_dir: Path):
    """Load lightgbm model + features list + medians."""
    import lightgbm as lgb
    model_path = model_dir / "lgbm_r3m.txt"
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}. "
                                "Run r1000_pattern_miner.py first.")
    booster = lgb.Booster(model_file=str(model_path))
    features = pd.read_csv(model_dir / "features.csv")["feature"].tolist()
    medians = pd.read_csv(model_dir / "feature_medians.csv", index_col=0)
    if medians.shape[1] == 1:
        medians = medians.iloc[:, 0]
    return booster, features, medians


def predict_for_latest(
    feature_store_path: Path,
    model_dir: Path,
    snapshot_date: str = "latest",
) -> pd.DataFrame:
    """Predict r_3m for the latest snapshot in feature_store."""
    booster, features, medians = load_artifacts(model_dir)
    df = pd.read_parquet(feature_store_path)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    if snapshot_date == "latest":
        latest_date = df["rebalance_date"].max()
    else:
        latest_date = pd.Timestamp(snapshot_date)
    snap = df[df["rebalance_date"] == latest_date].copy()
    print(f"[predict] snapshot={latest_date.date()}, rows={len(snap)}")

    # Build feature matrix in the same order as training, fill NaN with medians
    X = snap[features].copy()
    for col in features:
        if col in X.columns:
            X[col] = X[col].fillna(medians.get(col, 0.0))
        else:
            X[col] = medians.get(col, 0.0)

    preds = booster.predict(X.values)
    out = pd.DataFrame({
        "ticker": snap["ticker"].values,
        "predicted_r3m_pct": preds * 100.0,    # convert decimal -> %
        "snapshot_date": latest_date.date().isoformat(),
    })
    out["decile"] = pd.qcut(
        out["predicted_r3m_pct"], 10, labels=False, duplicates="drop",
    )
    out["confidence_band"] = pd.cut(
        out["predicted_r3m_pct"],
        bins=[-100, -5, 0, 5, 10, 999],
        labels=["strong_bear", "bearish", "neutral", "bullish", "strong_bull"],
    )
    return out.sort_values("predicted_r3m_pct", ascending=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--feature-store",
                   default=r"G:/내 드라이브/r1000_top30_institutional/feature_store/feature_store_latest.parquet")
    p.add_argument("--model-dir", default="outputs/discovered_rules/model")
    p.add_argument("--snapshot-date", default="latest")
    p.add_argument("--output",
                   default="outputs/discovered_rules/predictions_latest.csv")
    args = p.parse_args()

    print("=" * 70)
    print(f"r1000 ML Predictor - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)

    preds = predict_for_latest(
        Path(args.feature_store), Path(args.model_dir), args.snapshot_date,
    )
    preds.to_csv(args.output, index=False)
    print(f"\n[save] {args.output} ({len(preds)} predictions)")

    # Show distribution
    print()
    print("Predicted r_3m distribution:")
    print(preds["confidence_band"].value_counts(dropna=False).sort_index())

    print()
    print("Top 25 (predicted_r3m_pct):")
    print(preds.head(25)[["ticker", "predicted_r3m_pct", "decile",
                            "confidence_band"]].to_string(index=False))

    print()
    print("Bottom 15 (avoid):")
    print(preds.tail(15)[["ticker", "predicted_r3m_pct", "decile",
                            "confidence_band"]].to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
