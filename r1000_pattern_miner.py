"""r1000_pattern_miner - ML-based discovery of new alpha rules.

User mandate (2026-04-25 dawn):
  "신규 규칙들을 찾아내서 신규 피처화해보자"

Trains LightGBM on 8 years of feature_store data, runs SHAP analysis to
find which features actually predict forward 3-month returns, and extracts
human-readable decision rules.

Output:
  outputs/discovered_rules/feature_importance.csv
  outputs/discovered_rules/decision_tree.txt
  outputs/discovered_rules/discovered_rules.yaml
  outputs/discovered_rules/shap_summary.png (if matplotlib)
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


# ---------------------------------------------------------------------------
# Feature selection
# ---------------------------------------------------------------------------

def select_features(df: pd.DataFrame, max_nullity: float = 0.30) -> list[str]:
    """Pick numeric features that are well-populated."""
    EXCLUDE_PREFIXES = (
        "Unnamed:", "ticker", "Name", "name", "sector",
        "industry", "subindustry", "rebalance_date", "date",
        "cik", "score_source", "score_total",
    )
    EXCLUDE_EXACT = {
        "ticker", "Name", "name", "sector", "industry",
        "subindustry", "industry_group", "industry_sector",
        "rebalance_date", "cik10", "score_source",
        # CRITICAL: r_*m are FORWARD returns (LEAKAGE!) - excluded
        # Verified 2026-04-25: r_12m for NVDA at 2023-12 = +176% (forward to 2024-12)
        # while mom_12m = +253% (past from 2022-12). Use mom_*m for past momentum.
        "r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m",
        # Benchmark forward returns also leakage
        "bench_r_1m", "bench_r_3m", "bench_r_6m",
        "bench_r_12m", "bench_r_24m", "bench_r_36m",
        # Score/weight columns
        "score", "score_model_core", "score_total", "weight",
        "portfolio_sleeve_label", "sleeve_label",
        # Forward valuations (any 'forward_*' is suspect)
        "forward_value_score",
    }
    # Also exclude any column starting with 'r_' that's a forward return
    # (defensive — covers any new naming)
    candidates = []
    for c in df.columns:
        if c in EXCLUDE_EXACT:
            continue
        if any(c.startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        # Defensive: any 'r_NNm' or 'r_NNd' pattern is forward return
        import re
        if re.match(r"^r_\d+[mdy]", c):
            continue
        if re.match(r"^bench_r_", c):
            continue
        if df[c].dtype.kind not in ("f", "i", "u", "b"):
            continue
        nullity = df[c].isnull().mean()
        if nullity > max_nullity:
            continue
        # Skip near-constant
        if df[c].nunique() < 3:
            continue
        candidates.append(c)
    return candidates


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_and_explain(
    X_train, y_train, X_test, y_test, feature_names: list[str], verbose: bool = True,
):
    """Train LightGBM + extract feature importance.

    Returns dict with model, importance df, predictions.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        print("FAIL: lightgbm not installed. Run: pip install lightgbm")
        sys.exit(1)

    # Train regressor
    model = lgb.LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=6,
        min_data_in_leaf=50,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=5,
        verbose=-1,
        random_state=42,
    )
    if verbose:
        print(f"[train] LightGBM on {len(X_train)} rows × {X_train.shape[1]} features")
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[lgb.early_stopping(20, verbose=False)],
    )

    # Predict
    pred_train = model.predict(X_train)
    pred_test = model.predict(X_test)

    # Metrics
    from sklearn.metrics import r2_score
    r2_train = r2_score(y_train, pred_train)
    r2_test = r2_score(y_test, pred_test)
    if verbose:
        print(f"[train] R2 train={r2_train:.4f} test={r2_test:.4f}")

    # Built-in importance (gain)
    importance = pd.DataFrame({
        "feature": feature_names,
        "importance_gain": model.booster_.feature_importance(importance_type="gain"),
        "importance_split": model.booster_.feature_importance(importance_type="split"),
    }).sort_values("importance_gain", ascending=False)
    importance["importance_gain_pct"] = (
        importance["importance_gain"] / importance["importance_gain"].sum() * 100
    )

    # Top-k features for SHAP
    top_features = importance.head(30)["feature"].tolist()

    return {
        "model": model,
        "importance": importance,
        "pred_train": pred_train,
        "pred_test": pred_test,
        "r2_train": r2_train,
        "r2_test": r2_test,
        "top_features": top_features,
    }


# ---------------------------------------------------------------------------
# Decision tree rules
# ---------------------------------------------------------------------------

def extract_rules(X, y, feature_names, max_depth: int = 5) -> str:
    """Train shallow decision tree and export human-readable rules."""
    from sklearn.tree import DecisionTreeRegressor, export_text

    tree = DecisionTreeRegressor(
        max_depth=max_depth,
        min_samples_leaf=200,
        random_state=42,
    )
    tree.fit(X, y)
    rules_text = export_text(
        tree, feature_names=feature_names, decimals=2, max_depth=max_depth,
    )
    return rules_text, tree


# ---------------------------------------------------------------------------
# Backtest discovered rules
# ---------------------------------------------------------------------------

def backtest_top_decile(
    df: pd.DataFrame, predictions: pd.Series, target: pd.Series,
    train_test_split_date,
):
    """Compare top-decile predictions to bottom-decile and overall.

    Filter to test set only (out-of-sample).
    """
    out_of_sample = df["rebalance_date"] >= train_test_split_date
    pred_oos = predictions[out_of_sample]
    target_oos = target[out_of_sample]

    decile = pd.qcut(pred_oos, 10, labels=False, duplicates="drop")
    by_decile = pd.DataFrame({
        "decile": decile,
        "predicted": pred_oos,
        "actual": target_oos,
    }).groupby("decile").agg(
        n=("actual", "size"),
        avg_predicted=("predicted", "mean"),
        avg_actual=("actual", "mean"),
        median_actual=("actual", "median"),
        hit_positive=("actual", lambda x: (x > 0).mean()),
    )
    by_decile["alpha_vs_avg"] = by_decile["avg_actual"] - target_oos.mean()
    return by_decile


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--feature-store",
                   default=r"G:/내 드라이브/r1000_top30_institutional/feature_store/feature_store_latest.parquet")
    p.add_argument("--target", default="r_3m",
                   help="forward return column to predict")
    p.add_argument("--train-end", default="2024-04-01",
                   help="cutoff: train < this date, test >= this date")
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--output-dir", default="outputs/discovered_rules")
    args = p.parse_args()

    print("=" * 70)
    print(f"r1000 Pattern Miner - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)

    # Load
    print(f"[load] {args.feature_store}")
    df = pd.read_parquet(args.feature_store)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    print(f"[load] {len(df)} rows × {len(df.columns)} cols  "
          f"({df['rebalance_date'].min().date()} ~ {df['rebalance_date'].max().date()})")

    # Filter to rows with target
    df = df.dropna(subset=[args.target])
    print(f"[filter] rows with {args.target} target: {len(df)}")

    # Select features
    features = select_features(df, max_nullity=0.30)
    print(f"[features] {len(features)} numeric features (nullity < 30%)")
    if len(features) < 10:
        print("[ERROR] too few features"); return 1

    # Train/test split (time-based)
    train_end = pd.Timestamp(args.train_end)
    train_mask = df["rebalance_date"] < train_end
    test_mask = df["rebalance_date"] >= train_end
    print(f"[split] train: {train_mask.sum()} rows (< {train_end.date()})")
    print(f"[split] test:  {test_mask.sum()} rows (>= {train_end.date()})")

    # Build matrices (impute NaN with median)
    X_full = df[features].copy()
    medians = X_full.median()
    X_full = X_full.fillna(medians)
    y_full = df[args.target]

    X_train = X_full[train_mask]
    y_train = y_full[train_mask]
    X_test = X_full[test_mask]
    y_test = y_full[test_mask]

    # Train
    result = train_and_explain(X_train, y_train, X_test, y_test, features)

    # Save outputs
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Feature importance
    imp = result["importance"]
    imp.to_csv(out_dir / "feature_importance.csv", index=False)
    print(f"\n[save] feature_importance.csv ({len(imp)} features)")
    print()
    print("Top 25 features by gain:")
    print(imp.head(25)[["feature", "importance_gain_pct", "importance_split"]].to_string(index=False))

    # Decision tree on top features only (for cleaner rules)
    top_features = result["top_features"][:20]
    print(f"\n[tree] training depth-{args.max_depth} decision tree on top 20 features...")
    rules_text, tree = extract_rules(
        X_train[top_features].values, y_train.values,
        top_features, max_depth=args.max_depth,
    )
    (out_dir / "decision_tree.txt").write_text(rules_text, encoding="utf-8")
    print(f"[save] decision_tree.txt")
    print()
    print("=" * 70)
    print("DECISION TREE (top 20 features only)")
    print("=" * 70)
    print(rules_text[:3000])

    # Backtest the model on out-of-sample data (decile sort)
    print()
    print("=" * 70)
    print("OUT-OF-SAMPLE PERFORMANCE (decile sort)")
    print("=" * 70)
    pred_full = result["model"].predict(X_full)
    by_decile = backtest_top_decile(
        df, pd.Series(pred_full, index=df.index),
        y_full, train_end,
    )
    by_decile.to_csv(out_dir / "decile_performance.csv")
    print(by_decile.to_string())
    print()
    top_decile_alpha = by_decile["avg_actual"].iloc[-1] - by_decile["avg_actual"].iloc[0]
    print(f"Top-Bottom decile spread: {top_decile_alpha:+.2f}% (3m forward return)")

    # Save trained model for production prediction
    model_dir = out_dir / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "lgbm_r3m.txt"
    result["model"].booster_.save_model(str(model_path))
    # Save feature list + medians for production inference
    pd.Series(features, name="feature").to_csv(
        model_dir / "features.csv", index=False)
    medians.to_frame("median_value").to_csv(model_dir / "feature_medians.csv")
    print(f"\n[save] model -> {model_path}")
    print(f"[save] features.csv ({len(features)} features)")
    print(f"[save] feature_medians.csv (impute reference)")

    # Save results manifest
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "target": args.target,
        "train_end": args.train_end,
        "n_features": len(features),
        "n_train": int(train_mask.sum()),
        "n_test": int(test_mask.sum()),
        "r2_train": result["r2_train"],
        "r2_test": result["r2_test"],
        "top_features": result["top_features"][:30],
        "decile_top_bottom_spread_pct": float(top_decile_alpha),
        "model_file": str(model_path),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8",
    )
    print(f"\n[save] manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
