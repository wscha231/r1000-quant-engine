"""Phase 11 B1: Walk-forward validation (rolling retrain instead of static split).

Current static split: train 2018-2022, test 2022-2026. Single shot; risk of
lucky regime match. Walk-forward: for each test month t, retrain on data
strictly before (t - embargo_months). This simulates live rolling retrain.

Compares:
  1. Static split (current production path)
  2. Annual walk-forward (retrain every 12 months)
  3. Full walk-forward (retrain every month, heavy cost)

Output: walk-forward performance table + per-retrain AUC diagnostics.
If WF CAGR holds within 2pp of static, classifier is robust.
If WF CAGR drops >5pp, signals overfitting to 2022-06 split moment.

Usage:
    py -3 research/phase11_walkforward.py
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

from r1000_helpers import px_cache_name

OUT_DIR = ROOT / "research"
DRIVE = Path(r"G:\내 드라이브\r1000_top30_institutional")
FEATURE_STORE = DRIVE / "feature_store" / "feature_store_latest.parquet"
PRICE_CACHE = DRIVE / "cache_prices"
EPISODES_CSV = OUT_DIR / "multibagger_episodes.csv"

# Walk-forward config
EMBARGO_MONTHS = 36     # skip 36m before test month for training
RETRAIN_FREQ = 12        # retrain every 12 months (annual rolling)
MIN_TRAIN_MONTHS = 24    # skip early months with insufficient history
NAN_THRESHOLD = 0.50

# Sleeve backtest config (same as v1 standalone backtest)
SLEEVE_SIZE = 5
P_ENTRY_THRESHOLD = 0.30
P_TP_THRESHOLD = 0.50
P_SL_THRESHOLD = 0.70
MIN_HOLD_MONTHS = 3
RULE_BASED_TP_RETURN = 3.0
RULE_BASED_SL_RETURN = -0.15
RULE_BASED_SL_MIN_MONTHS = 6

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
    "label", "tp_label", "sl_label",
}


def prep_features(df):
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    feats = [c for c in numeric if c not in EXCLUDE_FEATURES and not c.startswith("score")]
    nan_pct = df[feats].isna().mean()
    good = nan_pct[nan_pct < NAN_THRESHOLD].index.tolist()
    X = df[good].copy()
    for c in good:
        med = X[c].median()
        X[c] = X[c].fillna(med if pd.notna(med) else 0.0)
        if X[c].std() > 0:
            z = (X[c] - X[c].mean()) / X[c].std()
            X[c] = X[c].where(z.abs() < 5, X[c].mean())
    return X, good


def construct_labels(df, episodes):
    """Entry / TP / SL labels. Same logic as phase11_exit_classifier.py."""
    df = df.copy()
    df["label"] = 0
    for ticker, grp in episodes.groupby("ticker"):
        mask_t = df["ticker"] == ticker
        for _, ep in grp.iterrows():
            pre = ep["surge_start_date"] - pd.DateOffset(months=6)
            post = ep["surge_start_date"] + pd.DateOffset(months=3)
            df.loc[mask_t & (df["rebalance_date"] >= pre) & (df["rebalance_date"] <= post), "label"] = 1

    df["tp_label"] = -9
    for ticker, grp in episodes.groupby("ticker"):
        mask_t = df["ticker"] == ticker
        for _, ep in grp.iterrows():
            peak = ep["peak_date"]
            near_start = peak - pd.DateOffset(months=2)
            near_end = peak + pd.DateOffset(months=1)
            healthy_end = peak - pd.DateOffset(months=3)
            pos = (df["rebalance_date"] >= near_start) & (df["rebalance_date"] <= near_end)
            df.loc[mask_t & pos, "tp_label"] = 1
            neg = (df["rebalance_date"] >= ep["surge_start_date"]) & (df["rebalance_date"] <= healthy_end)
            curr = df.loc[mask_t & neg, "tp_label"]
            df.loc[curr.index[curr == -9], "tp_label"] = 0

    df["sl_label"] = -9
    r12 = pd.to_numeric(df.get("r_12m", pd.Series(np.nan, index=df.index)), errors="coerce")
    df.loc[r12 < -0.15, "sl_label"] = 1
    df.loc[r12 > 0.20, "sl_label"] = 0
    return df


def train_classifier(X_train, y_train, X_test, y_test):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score
    from catboost import CatBoostClassifier

    scaler = StandardScaler().fit(X_train)
    lr = LogisticRegression(penalty="l2", C=1.0, class_weight="balanced",
                            max_iter=2000, random_state=42)
    lr.fit(scaler.transform(X_train), y_train)
    cb = CatBoostClassifier(iterations=500, learning_rate=0.03, depth=6,
                            auto_class_weights="Balanced", random_seed=42, verbose=False)
    cb.fit(X_train, y_train)
    p_tr = 0.5 * lr.predict_proba(scaler.transform(X_train))[:, 1] + 0.5 * cb.predict_proba(X_train)[:, 1]
    p_te = 0.5 * lr.predict_proba(scaler.transform(X_test))[:, 1] + 0.5 * cb.predict_proba(X_test)[:, 1]
    auc_tr = roc_auc_score(y_train, p_tr) if y_train.sum() > 0 else np.nan
    auc_te = roc_auc_score(y_test, p_te) if y_test.sum() > 0 else np.nan
    return {"lr": lr, "cb": cb, "scaler": scaler, "auc_train": auc_tr, "auc_test": auc_te}


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
print(f"  fs: {len(fs)}, episodes: {len(episodes)}")

df = construct_labels(fs, episodes)
X_full, good_feats = prep_features(df)

# ---------------------------------------------------------------------------
# Walk-forward: rolling retrains
# ---------------------------------------------------------------------------
print(f"\nWalk-forward validation (embargo {EMBARGO_MONTHS}m, retrain every {RETRAIN_FREQ}m)")

all_months = sorted(df["rebalance_date"].dropna().unique())
test_months = [m for m in all_months if m >= pd.Timestamp("2022-06-30")]
print(f"  Test months: {len(test_months)}")

# Build retrain anchors
retrain_anchors = []
last_train = None
for m in test_months:
    if last_train is None:
        retrain_anchors.append(m)
        last_train = m
    elif (m - last_train).days >= RETRAIN_FREQ * 30:
        retrain_anchors.append(m)
        last_train = m

print(f"  Retrain anchors: {len(retrain_anchors)} ({', '.join(str(m.date()) for m in retrain_anchors)})")

# For each retrain anchor, train on data < (anchor - embargo) and predict for
# all test months between this anchor and the next anchor
wf_predictions = []
wf_auc_log = []
for i, anchor in enumerate(retrain_anchors):
    train_cutoff = anchor - pd.DateOffset(months=EMBARGO_MONTHS)
    if i + 1 < len(retrain_anchors):
        predict_until = retrain_anchors[i + 1]
    else:
        predict_until = all_months[-1] + pd.DateOffset(days=1)

    # Train data: rebalance_date < train_cutoff
    train_mask = df["rebalance_date"] < train_cutoff
    # Entry label
    entry_rows = train_mask & df["label"].isin([0, 1])
    y_entry = df.loc[entry_rows, "label"].astype(int).values
    if y_entry.sum() < 20:
        print(f"  [{anchor.date()}] insufficient training positives ({int(y_entry.sum())}); skipping")
        continue
    X_train = X_full.loc[entry_rows].values
    # Predict test set: rebalance_date >= anchor AND < predict_until
    pred_mask = (df["rebalance_date"] >= anchor) & (df["rebalance_date"] < predict_until)
    X_test = X_full.loc[pred_mask].values
    y_test_entry = df.loc[pred_mask, "label"].fillna(0).astype(int).values  # for AUC diagnostic

    entry_clf = train_classifier(X_train, y_entry, X_test, y_test_entry)
    print(f"  [{anchor.date()}] Entry AUC train={entry_clf['auc_train']:.3f} test={entry_clf['auc_test']:.3f} "
          f"(n_train={train_mask.sum()}, n_test={pred_mask.sum()})")

    # Predict tp and sl the same way
    tp_train_mask = train_mask & df["tp_label"].isin([0, 1])
    y_tp = df.loc[tp_train_mask, "tp_label"].astype(int).values
    if y_tp.sum() >= 10:
        X_tp_train = X_full.loc[tp_train_mask].values
        tp_clf = train_classifier(X_tp_train, y_tp, X_test, np.zeros(pred_mask.sum()))
        p_tp = 0.5 * tp_clf["lr"].predict_proba(tp_clf["scaler"].transform(X_test))[:, 1] + 0.5 * tp_clf["cb"].predict_proba(X_test)[:, 1]
    else:
        p_tp = np.zeros(pred_mask.sum())

    sl_train_mask = train_mask & df["sl_label"].isin([0, 1])
    y_sl = df.loc[sl_train_mask, "sl_label"].astype(int).values
    if y_sl.sum() >= 50:
        X_sl_train = X_full.loc[sl_train_mask].values
        sl_clf = train_classifier(X_sl_train, y_sl, X_test, np.zeros(pred_mask.sum()))
        p_sl = 0.5 * sl_clf["lr"].predict_proba(sl_clf["scaler"].transform(X_test))[:, 1] + 0.5 * sl_clf["cb"].predict_proba(X_test)[:, 1]
    else:
        p_sl = np.zeros(pred_mask.sum())

    p_entry = 0.5 * entry_clf["lr"].predict_proba(entry_clf["scaler"].transform(X_test))[:, 1] + 0.5 * entry_clf["cb"].predict_proba(X_test)[:, 1]

    test_rows = df.loc[pred_mask].copy()
    test_rows["p_entry"] = p_entry
    test_rows["p_tp"] = p_tp
    test_rows["p_sl"] = p_sl
    wf_predictions.append(test_rows)
    wf_auc_log.append({
        "anchor": str(anchor.date()),
        "train_cutoff": str(train_cutoff.date()),
        "n_train_entry": int(y_entry.sum()),
        "entry_auc_test": float(entry_clf["auc_test"]),
        "n_pred": int(pred_mask.sum()),
    })

wf_df = pd.concat(wf_predictions, ignore_index=True) if wf_predictions else pd.DataFrame()
print(f"\nTotal WF predictions: {len(wf_df)}")

# ---------------------------------------------------------------------------
# Sleeve backtest using WF predictions
# ---------------------------------------------------------------------------
print("\nLoading monthly close prices ...")
prices = {}
for ticker in wf_df["ticker"].unique():
    p = PRICE_CACHE / px_cache_name(ticker)
    if not p.exists():
        continue
    try:
        pdf = pd.read_parquet(p)
    except Exception:
        continue
    col = "Adj Close" if "Adj Close" in pdf.columns else "Close"
    s = pd.to_numeric(pdf[col], errors="coerce").dropna()
    s.index = pd.to_datetime(s.index)
    monthly = s.resample("ME").last().dropna()
    prices[ticker] = monthly
print(f"  loaded {len(prices)} tickers")


def get_price(ticker, date):
    if ticker not in prices:
        return None
    s = prices[ticker]
    valid = s[s.index <= date]
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def run_backtest(pred_df, weighting="pscore"):
    test_months = sorted(pred_df["rebalance_date"].unique())
    holdings = {}
    monthly_returns = []
    trade_log = []
    for i, month_t in enumerate(test_months):
        m = pred_df[pred_df["rebalance_date"] == month_t]
        if m.empty:
            monthly_returns.append({"date": month_t, "return": 0.0, "n": 0})
            continue
        # Exits
        for ticker in list(holdings.keys()):
            row = m[m["ticker"] == ticker]
            if row.empty:
                continue
            r = row.iloc[0]
            cur_p = get_price(ticker, month_t)
            if cur_p is None:
                continue
            ep = holdings[ticker]["entry_price"]
            held = holdings[ticker]["held_months"]
            pos_ret = (cur_p / ep) - 1.0
            if held < MIN_HOLD_MONTHS:
                reason = None
            elif r.get("p_tp", 0) > P_TP_THRESHOLD:
                reason = "ml_tp"
            elif r.get("p_sl", 0) > P_SL_THRESHOLD:
                reason = "ml_sl"
            elif pos_ret > RULE_BASED_TP_RETURN and r.get("mom_3m", 0) < 0:
                reason = "rule_tp"
            elif held >= RULE_BASED_SL_MIN_MONTHS and pos_ret < RULE_BASED_SL_RETURN and r.get("p_entry", 0) < 0.20:
                reason = "rule_sl"
            else:
                reason = None
            if reason:
                trade_log.append({"ticker": ticker, "date": month_t, "return": pos_ret, "reason": reason})
                del holdings[ticker]
        # Monthly return
        if holdings:
            prs, ws = [], []
            for ticker, info in holdings.items():
                cp = get_price(ticker, month_t)
                if i + 1 < len(test_months):
                    np_price = get_price(ticker, test_months[i + 1])
                    if cp and np_price:
                        prs.append(np_price / cp - 1)
                        ws.append(info.get("weight", 1.0))
            if prs:
                w = np.array(ws)
                w = w / w.sum()
                rp = float(np.dot(w, prs))
            else:
                rp = 0.0
        else:
            rp = 0.0
        monthly_returns.append({"date": month_t, "return": rp, "n": len(holdings)})
        for ticker in holdings:
            holdings[ticker]["held_months"] += 1
        # Entries
        empty = SLEEVE_SIZE - len(holdings)
        if empty > 0:
            cand = m[
                (m["p_entry"] >= P_ENTRY_THRESHOLD)
                & (m["p_sl"] < 0.50)
                & (m["mktcap"] >= 1e9)
                & (m["revenues_ttm"] >= 1e8)
                & (~m["ticker"].isin(holdings.keys()))
            ]
            if not cand.empty:
                cand = cand.nlargest(empty, "p_entry")
                for _, c in cand.iterrows():
                    p = get_price(c["ticker"], month_t)
                    if p is None:
                        continue
                    w = float(c["p_entry"]) if weighting == "pscore" else 1.0
                    holdings[c["ticker"]] = {
                        "entry_date": month_t, "entry_price": p, "held_months": 0, "weight": w,
                    }
    return pd.DataFrame(monthly_returns), pd.DataFrame(trade_log)


print("\nRunning walk-forward sleeve backtest (size=5, pscore)...")
wf_ret_df, wf_trades = run_backtest(wf_df, weighting="pscore")

returns = wf_ret_df["return"].values
n = len(returns)
cumulative = (1 + returns).prod()
years = n / 12
cagr = cumulative ** (1 / years) - 1 if years > 0 else 0
ann_vol = returns.std() * np.sqrt(12)
sharpe = (returns.mean() * 12) / ann_vol if ann_vol > 0 else 0
wealth = np.cumprod(1 + returns)
peak = np.maximum.accumulate(wealth)
dd = (wealth - peak) / peak
max_dd = dd.min()
avg_n = wf_ret_df["n"].mean()

print(f"\n=== WALK-FORWARD BACKTEST RESULTS ===")
print(f"  Months:  {n}")
print(f"  CAGR:    {cagr:.2%}")
print(f"  Sharpe:  {sharpe:.2f}")
print(f"  MDD:     {max_dd:.2%}")
print(f"  avg N:   {avg_n:.1f}")
print(f"  trades:  {len(wf_trades)}")

# Compare with static split (from sleeve_backtest_results.json)
static_results_path = OUT_DIR / "phase11_sleeve_backtest_results.json"
static_cagr = static_sharpe = static_mdd = None
if static_results_path.exists():
    static = json.loads(static_results_path.read_text())
    best = static.get("best_config")
    if best and best in static.get("configs", {}):
        c = static["configs"][best]
        static_cagr = c.get("cagr")
        static_sharpe = c.get("sharpe")
        static_mdd = c.get("max_dd")

print(f"\n=== STATIC vs WALK-FORWARD ===")
print(f"  {'Metric':12s} {'Static':>10s} {'WF':>10s} {'Delta':>10s}")
if static_cagr is not None:
    print(f"  {'CAGR':12s} {static_cagr:>9.2%} {cagr:>9.2%} {(cagr-static_cagr)*100:>+9.2f}pp")
    print(f"  {'Sharpe':12s} {static_sharpe:>10.2f} {sharpe:>10.2f} {sharpe-static_sharpe:>+10.2f}")
    print(f"  {'MDD':12s} {static_mdd:>9.2%} {max_dd:>9.2%} {(max_dd-static_mdd)*100:>+9.2f}pp")

# Save
out = {
    "params": {
        "embargo_months": EMBARGO_MONTHS,
        "retrain_freq_months": RETRAIN_FREQ,
        "sleeve_size": SLEEVE_SIZE,
        "weighting": "pscore",
    },
    "retrains": wf_auc_log,
    "walkforward_results": {
        "cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(max_dd),
        "avg_n": float(avg_n), "n_trades": int(len(wf_trades)), "months": int(n),
    },
    "static_results": {
        "cagr": float(static_cagr) if static_cagr is not None else None,
        "sharpe": float(static_sharpe) if static_sharpe is not None else None,
        "max_dd": float(static_mdd) if static_mdd is not None else None,
    } if static_cagr is not None else None,
}
(OUT_DIR / "phase11_walkforward_results.json").write_text(json.dumps(out, indent=2, default=str))
wf_ret_df.to_csv(OUT_DIR / "phase11_walkforward_returns.csv", index=False)
print(f"\nSaved: phase11_walkforward_results.json + returns.csv")
