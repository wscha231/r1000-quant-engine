"""Phase 11 Step 3 -- TWO exit classifiers for multibagger sleeve.

Mechanism 1 (익절 / TAKE_PROFIT):
    "Stock is already up 2x+, is it at/near peak?"
    Positive: peak_date - 2m to peak_date + 1m (of confirmed 5x+ episodes)
    Negative: mid-surge (surge_start to peak - 3m, still climbing)
    Use: exit winner positions before decline starts.

Mechanism 2 (손절 / STOP_LOSS / thesis break):
    "Stock looked like entry candidate but is going to fail"
    Positive: any (ticker, month) where forward_24m return < -20%
    Negative: any (ticker, month) where forward_24m return > 30%
    Use: cut losses on entries that don't pan out, avoid dead money.

Usage:
    py -3 research/phase11_exit_classifier.py

Outputs:
    research/takeprofit_classifier_metrics.json
    research/takeprofit_classifier_featimp.csv
    research/takeprofit_classifier_predictions.csv
    research/stoploss_classifier_metrics.json
    research/stoploss_classifier_featimp.csv
    research/stoploss_classifier_predictions.csv
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

SPLIT_DATE = pd.Timestamp("2022-06-30")
NAN_THRESHOLD = 0.50

EXCLUDE_FEATURES = {
    "ticker", "Name", "sector", "industry", "industry_group", "subindustry",
    "universe_source", "cik10", "period", "accepted", "fund_period",
    "fund_accepted", "fund_source", "fund_asof_quarter", "feature_date",
    "entry_date", "rebalance_date", "macro_regime_label",
    "event_regime_label", "live_event_alert_label",
    "regime_rotation_label", "regime_rotation_short_label",
    "yf_sector", "yf_industry", "yf_industry_group", "yf_subindustry",
    "sage_sector", "cnn_fear_greed_label", "company_key",
    "r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m",
    "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m",
    "bench_r_24m", "bench_r_36m",
}


def prep_features(df: pd.DataFrame, extra_exclude: set[str] = None) -> tuple[pd.DataFrame, list[str]]:
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    # Exclude label columns (original + all phase-11 labels) to prevent leakage
    label_cols = {"label", "tp_label", "sl_label"}
    exclude = EXCLUDE_FEATURES | label_cols | (extra_exclude or set())
    feats = [c for c in numeric if c not in exclude
             and not c.startswith("score")]
    nan_pct = df[feats].isna().mean()
    good = nan_pct[nan_pct < NAN_THRESHOLD].index.tolist()
    X = df[good].copy()
    for c in good:
        med = X[c].median()
        X[c] = X[c].fillna(med if pd.notna(med) else 0.0)
        # Clip 5-sigma outliers
        if X[c].std() > 0:
            z = (X[c] - X[c].mean()) / X[c].std()
            X[c] = X[c].where(z.abs() < 5, X[c].mean())
    return X, good


def train_eval(X_train, y_train, X_test, y_test, features, label_name):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, average_precision_score

    scaler = StandardScaler()
    Xts = scaler.fit_transform(X_train)
    Xes = scaler.transform(X_test)

    print(f"\n=== {label_name}: Logistic Regression (L2, balanced) ===")
    lr = LogisticRegression(penalty="l2", C=1.0, class_weight="balanced",
                            max_iter=2000, solver="lbfgs", random_state=42)
    lr.fit(Xts, y_train)
    p_te_lr = lr.predict_proba(Xes)[:, 1]
    p_tr_lr = lr.predict_proba(Xts)[:, 1]

    auc_train_lr = roc_auc_score(y_train, p_tr_lr) if y_train.sum() > 0 else np.nan
    auc_test_lr = roc_auc_score(y_test, p_te_lr) if y_test.sum() > 0 else np.nan
    print(f"  Train AUC: {auc_train_lr:.4f}  Test AUC: {auc_test_lr:.4f}")

    print(f"\n=== {label_name}: CatBoost ===")
    try:
        from catboost import CatBoostClassifier
        cb = CatBoostClassifier(iterations=500, learning_rate=0.03, depth=6,
                                loss_function="Logloss", auto_class_weights="Balanced",
                                random_seed=42, verbose=False)
        cb.fit(X_train, y_train)
        p_te_cb = cb.predict_proba(X_test)[:, 1]
        p_tr_cb = cb.predict_proba(X_train)[:, 1]
        auc_train_cb = roc_auc_score(y_train, p_tr_cb) if y_train.sum() > 0 else np.nan
        auc_test_cb = roc_auc_score(y_test, p_te_cb) if y_test.sum() > 0 else np.nan
        print(f"  Train AUC: {auc_train_cb:.4f}  Test AUC: {auc_test_cb:.4f}")
        fi = pd.DataFrame({"feature": features, "importance": cb.get_feature_importance()}).sort_values("importance", ascending=False)
    except Exception as e:
        print(f"  CatBoost failed: {e}")
        cb = None
        p_te_cb = p_te_lr
        auc_test_cb = auc_test_lr
        fi = pd.DataFrame({"feature": features, "importance": np.abs(lr.coef_[0])}).sort_values("importance", ascending=False)

    p_te_blend = 0.5 * p_te_lr + 0.5 * p_te_cb
    auc_test_blend = roc_auc_score(y_test, p_te_blend) if y_test.sum() > 0 else np.nan
    ap_test_blend = average_precision_score(y_test, p_te_blend) if y_test.sum() > 0 else np.nan

    print(f"\n=== {label_name}: Blend ===")
    print(f"  Test AUC: {auc_test_blend:.4f}  Avg Precision: {ap_test_blend:.4f}")

    def pk(y, p, k):
        n = max(1, int(len(p) * k))
        idx = np.argsort(p)[::-1][:n]
        return y[idx].sum() / n

    base = y_test.sum() / len(y_test) if len(y_test) else 0
    print(f"  base rate: {base:.4f}")
    for k in [0.01, 0.05, 0.10]:
        print(f"  top {k*100:4.1f}%: precision={pk(y_test, p_te_blend, k):.3f}  lift={pk(y_test, p_te_blend, k)/max(base, 1e-9):.2f}x")

    return {
        "lr_auc_test": float(auc_test_lr),
        "cb_auc_test": float(auc_test_cb),
        "blend_auc_test": float(auc_test_blend),
        "blend_ap_test": float(ap_test_blend),
        "base_rate_test": float(base),
        "precision_top_5pct_blend": float(pk(y_test, p_te_blend, 0.05)),
        "precision_top_10pct_blend": float(pk(y_test, p_te_blend, 0.10)),
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "n_train_pos": int(y_train.sum()),
        "n_test_pos": int(y_test.sum()),
    }, p_te_blend, fi


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading data ...")
fs = pd.read_parquet(FEATURE_STORE)
fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
fs = fs.dropna(subset=["rebalance_date", "ticker"]).reset_index(drop=True)
episodes = pd.read_csv(EPISODES_CSV)
episodes["surge_start_date"] = pd.to_datetime(episodes["surge_start_date"])
episodes["peak_date"] = pd.to_datetime(episodes["peak_date"])
print(f"  feature_store: {len(fs)} rows, episodes: {len(episodes)}")

# =====================================================================
# CLASSIFIER 1: TAKE_PROFIT (익절) -- peak detection for active winners
# =====================================================================
print("\n" + "=" * 78)
print("CLASSIFIER 1: TAKE_PROFIT (익절) -- detect peak in active multibagger surges")
print("=" * 78)

# Positive: peak_date - 2m ... peak_date + 1m (near peak)
# Negative: surge_start ... peak_date - 3m (healthy climb, well before peak)
# Other rows: EXCLUDE (not in active surge, not relevant to this classifier)

fs["tp_label"] = -9  # default exclude

for ticker, grp in episodes.groupby("ticker"):
    mask_ticker = fs["ticker"] == ticker
    for _, ep in grp.iterrows():
        surge = ep["surge_start_date"]
        peak = ep["peak_date"]
        near_peak_start = peak - pd.DateOffset(months=2)
        near_peak_end = peak + pd.DateOffset(months=1)
        healthy_climb_end = peak - pd.DateOffset(months=3)
        # Near peak -> positive
        pos_mask = (fs["rebalance_date"] >= near_peak_start) & (fs["rebalance_date"] <= near_peak_end)
        fs.loc[mask_ticker & pos_mask, "tp_label"] = 1
        # Healthy climb -> negative
        neg_mask = (fs["rebalance_date"] >= surge) & (fs["rebalance_date"] <= healthy_climb_end)
        # Only set to 0 if still at default (avoid overwriting pos from overlapping episodes)
        curr = fs.loc[mask_ticker & neg_mask, "tp_label"]
        fs.loc[curr.index[curr == -9], "tp_label"] = 0

# Add engineered features helpful for peak detection
# - months_since_surge_start (how long has this been climbing)
# - return_since_surge_start (how much has it gained)
# We already have mom_* features; Test will see if they capture this.

tp_data = fs[fs["tp_label"] >= 0].copy().reset_index(drop=True)
n_pos_tp = (tp_data["tp_label"] == 1).sum()
n_neg_tp = (tp_data["tp_label"] == 0).sum()
print(f"\nPositive (near-peak): {n_pos_tp}, Negative (healthy climb): {n_neg_tp}")
print(f"Total in-surge rows: {len(tp_data)}")

X_tp, feats_tp = prep_features(tp_data)
y_tp = tp_data["tp_label"].astype(int).values
dates_tp = tp_data["rebalance_date"]

tr = dates_tp < SPLIT_DATE
te = dates_tp >= SPLIT_DATE
print(f"Train: {tr.sum()} ({y_tp[tr].sum()} pos, {(y_tp[tr]==0).sum()} neg)")
print(f"Test:  {te.sum()} ({y_tp[te].sum()} pos, {(y_tp[te]==0).sum()} neg)")

if y_tp[tr].sum() < 5 or y_tp[te].sum() < 3:
    print("WARNING: insufficient labels for take_profit classifier")
    tp_metrics = {"error": "insufficient labels"}
    tp_pred = np.zeros(te.sum())
    tp_fi = pd.DataFrame()
else:
    tp_metrics, tp_pred, tp_fi = train_eval(
        X_tp[tr].values, y_tp[tr], X_tp[te].values, y_tp[te],
        feats_tp, "TAKE_PROFIT"
    )

# Save
(OUT_DIR / "takeprofit_classifier_metrics.json").write_text(json.dumps(tp_metrics, indent=2))
tp_fi.head(40).to_csv(OUT_DIR / "takeprofit_classifier_featimp.csv", index=False)
tp_test_df = tp_data[te].copy().reset_index(drop=True)
tp_test_df["p_takeprofit"] = tp_pred
tp_test_df[["ticker", "rebalance_date", "tp_label", "p_takeprofit"]].to_csv(
    OUT_DIR / "takeprofit_classifier_predictions.csv", index=False
)
print(f"\n  Saved: takeprofit_classifier_metrics.json / featimp.csv / predictions.csv")

# =====================================================================
# CLASSIFIER 2: STOP_LOSS (손절) -- detect stocks that will fail
# =====================================================================
print("\n" + "=" * 78)
print("CLASSIFIER 2: STOP_LOSS (손절) -- detect stocks with failing forward return")
print("=" * 78)

# Use forward_24m return (r_24m column in feature_store)
# Positive: r_24m < -20% (thesis break, will go down)
# Negative: r_24m > 30% (healthy, going up)
# Middle zone (-20%..+30%): EXCLUDE (ambiguous)

# HONEST 손절 label: pure forward-return, NO fundamental filter (avoid leakage)
# Positive (fail):     r_12m < -15% (clear 12m loss)
# Negative (healthy):  r_12m > +20% (clear 12m gain)
# Middle zone (-15..+20%): EXCLUDE (ambiguous)
# Label only uses forward prices; features are all point-in-time.

fs["sl_label"] = -9
r12 = pd.to_numeric(fs["r_12m"], errors="coerce")
fs.loc[r12 < -0.15, "sl_label"] = 1
fs.loc[r12 > 0.20, "sl_label"] = 0
ret_col = "r_12m < -15% (pos) vs r_12m > +20% (neg), pure forward-return label"

sl_data = fs[fs["sl_label"] >= 0].copy().reset_index(drop=True)
n_pos_sl = (sl_data["sl_label"] == 1).sum()
n_neg_sl = (sl_data["sl_label"] == 0).sum()
print(f"\nPositive (fail, {ret_col}): {n_pos_sl}")
print(f"Negative (healthy, r_12m > +20%): {n_neg_sl}")
print(f"Excluded (ambiguous + insufficient data): {len(fs) - len(sl_data)}")

# Label is pure r_12m forward return (no fundamental filter) — no feature exclusions needed
X_sl, feats_sl = prep_features(sl_data)
y_sl = sl_data["sl_label"].astype(int).values
dates_sl = sl_data["rebalance_date"]

tr_sl = dates_sl < SPLIT_DATE
te_sl = dates_sl >= SPLIT_DATE
print(f"Train: {tr_sl.sum()} ({y_sl[tr_sl].sum()} pos, {(y_sl[tr_sl]==0).sum()} neg)")
print(f"Test:  {te_sl.sum()} ({y_sl[te_sl].sum()} pos, {(y_sl[te_sl]==0).sum()} neg)")

sl_metrics, sl_pred, sl_fi = train_eval(
    X_sl[tr_sl].values, y_sl[tr_sl], X_sl[te_sl].values, y_sl[te_sl],
    feats_sl, "STOP_LOSS"
)

(OUT_DIR / "stoploss_classifier_metrics.json").write_text(json.dumps(sl_metrics, indent=2))
sl_fi.head(40).to_csv(OUT_DIR / "stoploss_classifier_featimp.csv", index=False)
sl_test_df = sl_data[te_sl].copy().reset_index(drop=True)
sl_test_df["p_stoploss"] = sl_pred
sl_test_df[["ticker", "rebalance_date", "sl_label", "p_stoploss"]].to_csv(
    OUT_DIR / "stoploss_classifier_predictions.csv", index=False
)
print(f"\n  Saved: stoploss_classifier_metrics.json / featimp.csv / predictions.csv")

# =====================================================================
# SUMMARY
# =====================================================================
print("\n" + "=" * 78)
print("STEP 3 COMPLETE -- TWO EXIT MECHANISMS TRAINED")
print("=" * 78)
print(f"\nTAKE_PROFIT (익절, peak detection):")
print(f"  AUC (blend test): {tp_metrics.get('blend_auc_test', 0):.4f}")
print(f"  Precision top 10%: {tp_metrics.get('precision_top_10pct_blend', 0):.3f}")
print(f"  Top 10 features:")
print(tp_fi.head(10).to_string(index=False))

print(f"\n\nSTOP_LOSS (손절, thesis break):")
print(f"  AUC (blend test): {sl_metrics.get('blend_auc_test', 0):.4f}")
print(f"  Precision top 10%: {sl_metrics.get('precision_top_10pct_blend', 0):.3f}")
print(f"  Top 10 features:")
print(sl_fi.head(10).to_string(index=False))

print("\n" + "=" * 78)
print("Next: Step 4 -- multibagger_watch sleeve integration with 3-signal logic:")
print("  ENTRY:     P(entry) > 0.30 AND quality filter")
print("  HOLD:      P(takeprofit) < 0.30 AND P(stoploss) < 0.50")
print("  TAKE:      P(takeprofit) > 0.50  (익절 -- sell after profit)")
print("  STOP:      P(stoploss) > 0.70    (손절 -- cut losses)")
print("=" * 78)
