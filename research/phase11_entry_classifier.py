"""Phase 11 Step 2 — train Entry classifier for multibagger detection.

Binary classifier: given a (ticker, rebalance_date) feature vector, predict
probability that this point is in the "pre-surge accumulation" phase
(within 6 months BEFORE or 3 months AFTER surge_start of a 5x+ episode).

Usage:
    py -3 research/phase11_entry_classifier.py

Outputs:
    research/entry_classifier_metrics.json    -- AUC, precision@k, confusion matrix
    research/entry_classifier_featimp.csv     -- feature importance (top 40)
    research/entry_classifier_predictions.csv -- P(entry) for all test rows
    research/entry_classifier_top_picks.csv   -- highest P(entry) rows by month
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "research"

DRIVE = Path(r"G:\내 드라이브\r1000_top30_institutional")
FEATURE_STORE = DRIVE / "feature_store" / "feature_store_latest.parquet"
EPISODES_CSV = OUT_DIR / "multibagger_episodes.csv"

# Label window around surge_start_date
PRE_SURGE_MONTHS = 6   # include t-6 ... t-1
POST_SURGE_MONTHS = 3  # include t ... t+3 (surge beginning, still detectable)
AMBIGUOUS_AFTER_PEAK_MONTHS = 6  # exclude peak+1 ... peak+6 from negatives (post-peak ambiguity)

# Feature selection
NAN_THRESHOLD = 0.50  # drop column if >50% NaN
EXCLUDE_FEATURES = {
    # ID/leak columns
    "ticker", "Name", "sector", "industry", "industry_group", "subindustry",
    "universe_source", "cik10", "period", "accepted", "fund_period",
    "fund_accepted", "fund_source", "fund_asof_quarter", "feature_date",
    "entry_date", "rebalance_date", "macro_regime_label",
    "event_regime_label", "live_event_alert_label",
    "regime_rotation_label", "regime_rotation_short_label",
    "yf_sector", "yf_industry", "yf_industry_group", "yf_subindustry",
    "sage_sector", "cnn_fear_greed_label", "company_key",
    # Forward-looking / leakage
    "r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m",
    "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m",
    "bench_r_24m", "bench_r_36m",
}

# Train/test split (time-based)
# Train: all episodes with surge_start_date BEFORE the cutoff
# Test:  episodes with surge_start_date >= cutoff
SPLIT_DATE = pd.Timestamp("2022-06-30")

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("Loading data ...")
fs = pd.read_parquet(FEATURE_STORE)
fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
fs = fs.dropna(subset=["rebalance_date", "ticker"]).reset_index(drop=True)
print(f"  feature_store: {len(fs)} rows, {fs['ticker'].nunique()} tickers")

episodes = pd.read_csv(EPISODES_CSV)
episodes["surge_start_date"] = pd.to_datetime(episodes["surge_start_date"])
episodes["peak_date"] = pd.to_datetime(episodes["peak_date"])
print(f"  episodes: {len(episodes)} multibaggers")

# ---------------------------------------------------------------------------
# 2. Construct labels
# ---------------------------------------------------------------------------
print("\nConstructing labels ...")

# For each (ticker, rebalance_date), determine label:
#   1 = pre/early-surge window (surge_start - 6m ... surge_start + 3m)
#   -1 = ambiguous (mid-surge ... peak + 6m)  -> exclude from training
#   0 = safe negative
fs["label"] = 0

episodes_by_ticker = episodes.groupby("ticker")
for ticker, grp in episodes_by_ticker:
    mask_ticker = fs["ticker"] == ticker
    for _, ep in grp.iterrows():
        surge = ep["surge_start_date"]
        peak = ep["peak_date"]
        pre_start = surge - pd.DateOffset(months=PRE_SURGE_MONTHS)
        pre_end = surge + pd.DateOffset(months=POST_SURGE_MONTHS)
        amb_end = peak + pd.DateOffset(months=AMBIGUOUS_AFTER_PEAK_MONTHS)
        # Pre/early surge window -> positive
        in_pos = (fs["rebalance_date"] >= pre_start) & (fs["rebalance_date"] <= pre_end)
        fs.loc[mask_ticker & in_pos, "label"] = 1
        # Mid-surge to 6m-post-peak -> ambiguous (will exclude from negatives)
        in_amb = (fs["rebalance_date"] > pre_end) & (fs["rebalance_date"] <= amb_end)
        # Only set to -1 if not already positive
        curr = fs.loc[mask_ticker & in_amb, "label"]
        fs.loc[curr.index[curr == 0], "label"] = -1

n_pos = (fs["label"] == 1).sum()
n_amb = (fs["label"] == -1).sum()
n_neg = (fs["label"] == 0).sum()
print(f"  positive (pre/early-surge): {n_pos}")
print(f"  ambiguous (mid-surge .. post-peak): {n_amb} (excluded from training)")
print(f"  negative (safe non-winner): {n_neg}")

# Drop ambiguous
data = fs[fs["label"] >= 0].copy().reset_index(drop=True)
print(f"  total training-eligible rows: {len(data)}")

# ---------------------------------------------------------------------------
# 3. Feature selection
# ---------------------------------------------------------------------------
print("\nSelecting features ...")

numeric_cols = data.select_dtypes(include=[np.number]).columns.tolist()
features = [
    c for c in numeric_cols
    if c not in EXCLUDE_FEATURES
    and c != "label"
    and not c.startswith("score")  # Exclude pre-computed scores (too closely tied to target)
]
# Drop columns with too much missingness
nan_pct = data[features].isna().mean()
good_features = nan_pct[nan_pct < NAN_THRESHOLD].index.tolist()
print(f"  numeric columns: {len(numeric_cols)}")
print(f"  after excluding IDs/leakage: {len(features)}")
print(f"  after NaN < {int(NAN_THRESHOLD*100)}% filter: {len(good_features)}")

X_all = data[good_features].copy()
# Median-impute missing
for c in good_features:
    med = X_all[c].median()
    X_all[c] = X_all[c].fillna(med if pd.notna(med) else 0.0)

# Clip extreme outliers (5-sigma) to stabilize models
for c in good_features:
    if X_all[c].std() > 0:
        z = (X_all[c] - X_all[c].mean()) / X_all[c].std()
        X_all[c] = X_all[c].where(z.abs() < 5, X_all[c].mean())

y_all = data["label"].astype(int).values
dates = data["rebalance_date"]

# ---------------------------------------------------------------------------
# 4. Train/test split (time-based)
# ---------------------------------------------------------------------------
print(f"\nTime-based split at {SPLIT_DATE.date()} ...")

train_mask = dates < SPLIT_DATE
test_mask = dates >= SPLIT_DATE

X_train = X_all[train_mask].values
y_train = y_all[train_mask]
X_test = X_all[test_mask].values
y_test = y_all[test_mask]

print(f"  train: {train_mask.sum()} rows ({y_train.sum()} positive, {(y_train==0).sum()} negative)")
print(f"  test:  {test_mask.sum()} rows ({y_test.sum()} positive, {(y_test==0).sum()} negative)")

if y_train.sum() < 10 or y_test.sum() < 3:
    print("\nWARNING: very few positives in train/test. Consider adjusting SPLIT_DATE.")

# ---------------------------------------------------------------------------
# 5. Train models
# ---------------------------------------------------------------------------
print("\n=== Model 1: Logistic Regression (L2, balanced) ===")
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, average_precision_score, precision_recall_curve

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

lr = LogisticRegression(
    penalty="l2",
    C=1.0,
    class_weight="balanced",
    max_iter=2000,
    solver="lbfgs",
    random_state=42,
)
lr.fit(X_train_s, y_train)

p_train_lr = lr.predict_proba(X_train_s)[:, 1]
p_test_lr = lr.predict_proba(X_test_s)[:, 1]

auc_train_lr = roc_auc_score(y_train, p_train_lr) if y_train.sum() > 0 else np.nan
auc_test_lr = roc_auc_score(y_test, p_test_lr) if y_test.sum() > 0 else np.nan
ap_test_lr = average_precision_score(y_test, p_test_lr) if y_test.sum() > 0 else np.nan
print(f"  Train AUC: {auc_train_lr:.4f}")
print(f"  Test AUC:  {auc_test_lr:.4f}")
print(f"  Test Avg Precision: {ap_test_lr:.4f}")

# ---------------------------------------------------------------------------
print("\n=== Model 2: CatBoost (gradient boosting) ===")
try:
    from catboost import CatBoostClassifier

    cb = CatBoostClassifier(
        iterations=500,
        learning_rate=0.03,
        depth=6,
        loss_function="Logloss",
        auto_class_weights="Balanced",
        random_seed=42,
        verbose=False,
    )
    cb.fit(X_train, y_train)
    p_train_cb = cb.predict_proba(X_train)[:, 1]
    p_test_cb = cb.predict_proba(X_test)[:, 1]

    auc_train_cb = roc_auc_score(y_train, p_train_cb) if y_train.sum() > 0 else np.nan
    auc_test_cb = roc_auc_score(y_test, p_test_cb) if y_test.sum() > 0 else np.nan
    ap_test_cb = average_precision_score(y_test, p_test_cb) if y_test.sum() > 0 else np.nan
    print(f"  Train AUC: {auc_train_cb:.4f}")
    print(f"  Test AUC:  {auc_test_cb:.4f}")
    print(f"  Test Avg Precision: {ap_test_cb:.4f}")

    # Feature importance
    importances = pd.DataFrame(
        {"feature": good_features, "importance": cb.get_feature_importance()}
    ).sort_values("importance", ascending=False)
except Exception as e:
    print(f"  CatBoost failed: {e}")
    cb = None
    p_test_cb = p_test_lr
    auc_test_cb = auc_test_lr
    ap_test_cb = ap_test_lr
    importances = pd.DataFrame({"feature": good_features, "importance": np.abs(lr.coef_[0])}).sort_values("importance", ascending=False)

# ---------------------------------------------------------------------------
# 6. Blend + precision at top-k
# ---------------------------------------------------------------------------
print("\n=== Blend: 0.5 * LR + 0.5 * CatBoost ===")
p_test_blend = 0.5 * p_test_lr + 0.5 * p_test_cb
auc_test_blend = roc_auc_score(y_test, p_test_blend) if y_test.sum() > 0 else np.nan
ap_test_blend = average_precision_score(y_test, p_test_blend) if y_test.sum() > 0 else np.nan
print(f"  Test AUC: {auc_test_blend:.4f}")
print(f"  Test Avg Precision: {ap_test_blend:.4f}")


def precision_at_k(y_true: np.ndarray, p: np.ndarray, k_pct: float) -> float:
    n_top = max(1, int(len(p) * k_pct))
    idx = np.argsort(p)[::-1][:n_top]
    return y_true[idx].sum() / n_top


print("\n=== Precision at top-K% (test set) ===")
ks = [0.001, 0.005, 0.01, 0.02, 0.05, 0.10]
for k in ks:
    pk_lr = precision_at_k(y_test, p_test_lr, k)
    pk_cb = precision_at_k(y_test, p_test_cb, k)
    pk_bl = precision_at_k(y_test, p_test_blend, k)
    n_top = max(1, int(len(p_test_blend) * k))
    print(f"  top {k*100:4.1f}% (n={n_top:4d}):  LR={pk_lr:.3f}  CB={pk_cb:.3f}  Blend={pk_bl:.3f}")

base_rate = y_test.sum() / len(y_test) if len(y_test) > 0 else 0
print(f"\n  base rate (positive / total test): {base_rate:.4f}")
print(f"  Lift at top 1% (blend): {precision_at_k(y_test, p_test_blend, 0.01)/max(base_rate,1e-9):.2f}x")

# ---------------------------------------------------------------------------
# 7. Save artifacts
# ---------------------------------------------------------------------------
print("\nSaving artifacts ...")

# Metrics
metrics = {
    "train_rows": int(train_mask.sum()),
    "test_rows": int(test_mask.sum()),
    "train_positives": int(y_train.sum()),
    "test_positives": int(y_test.sum()),
    "n_features": int(len(good_features)),
    "lr_auc_train": float(auc_train_lr),
    "lr_auc_test": float(auc_test_lr),
    "lr_ap_test": float(ap_test_lr),
    "cb_auc_train": float(auc_train_cb) if cb is not None else None,
    "cb_auc_test": float(auc_test_cb) if cb is not None else None,
    "cb_ap_test": float(ap_test_cb) if cb is not None else None,
    "blend_auc_test": float(auc_test_blend),
    "blend_ap_test": float(ap_test_blend),
    "base_rate_test": float(base_rate),
    "precision_top_1pct_blend": float(precision_at_k(y_test, p_test_blend, 0.01)),
    "precision_top_5pct_blend": float(precision_at_k(y_test, p_test_blend, 0.05)),
    "lift_top_1pct_blend": float(precision_at_k(y_test, p_test_blend, 0.01) / max(base_rate, 1e-9)),
}
(OUT_DIR / "entry_classifier_metrics.json").write_text(json.dumps(metrics, indent=2))
print(f"  {OUT_DIR / 'entry_classifier_metrics.json'}")

# Feature importance
importances.head(40).to_csv(OUT_DIR / "entry_classifier_featimp.csv", index=False)
print(f"  {OUT_DIR / 'entry_classifier_featimp.csv'}")

# Test predictions
test_df = data[test_mask].copy().reset_index(drop=True)
test_df["p_entry_lr"] = p_test_lr
test_df["p_entry_cb"] = p_test_cb
test_df["p_entry_blend"] = p_test_blend
out_cols = ["ticker", "rebalance_date", "label", "p_entry_lr", "p_entry_cb", "p_entry_blend"]
test_df[out_cols].to_csv(OUT_DIR / "entry_classifier_predictions.csv", index=False)
print(f"  {OUT_DIR / 'entry_classifier_predictions.csv'}")

# Top picks per month
top_picks_rows = []
for m, grp in test_df.groupby(test_df["rebalance_date"].dt.to_period("M")):
    top = grp.nlargest(10, "p_entry_blend")[["ticker", "rebalance_date", "p_entry_blend", "label"]]
    top["month"] = str(m)
    top_picks_rows.append(top)
top_picks = pd.concat(top_picks_rows, ignore_index=True)
top_picks.to_csv(OUT_DIR / "entry_classifier_top_picks.csv", index=False)
print(f"  {OUT_DIR / 'entry_classifier_top_picks.csv'}")

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("ENTRY CLASSIFIER SUMMARY")
print("=" * 78)
print(f"\nTrain period: data before {SPLIT_DATE.date()}")
print(f"Test period:  data on/after {SPLIT_DATE.date()}")
print(f"Features:     {len(good_features)}")
print(f"\nModel AUC (test):")
print(f"  Logistic Regression: {auc_test_lr:.4f}")
print(f"  CatBoost:            {auc_test_cb:.4f}")
print(f"  Blend:               {auc_test_blend:.4f}")
print(f"\nPrecision at top-1% (blend): {precision_at_k(y_test, p_test_blend, 0.01):.3f}")
print(f"Base rate:                   {base_rate:.3f}")
print(f"Lift:                        {precision_at_k(y_test, p_test_blend, 0.01)/max(base_rate,1e-9):.2f}x")
print(f"\nTop 10 features by importance (CatBoost or LR):")
print(importances.head(10).to_string(index=False))
print("\n" + "=" * 78)
print("Interpretation: AUC > 0.60 = signal exists, AUC > 0.70 = strong signal.")
print("Lift > 2x at top 1% means top picks are 2x more likely to be multibaggers.")
print("=" * 78)
