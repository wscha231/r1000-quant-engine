"""Phase 11 Step 4 (Lite A/B test) - standalone sleeve backtest + allocation analysis.

Goals:
  1. Standalone Phase 11 sleeve CAGR/Sharpe/MDD (what if this engine alone?)
  2. Allocation sensitivity (portfolio mix of main + phase11 sleeve)
  3. Position sizing + exit rule sensitivity

This is a RESEARCH backtest only -- does NOT modify the engine.
Results inform whether to proceed with full sleeve integration (Step 5).

Usage:
    py -3 research/phase11_sleeve_backtest.py
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
PRICE_CACHE = DRIVE / "cache_prices"
EPISODES_CSV = OUT_DIR / "multibagger_episodes.csv"

from r1000_helpers import px_cache_name

SPLIT_DATE = pd.Timestamp("2022-06-30")
NAN_THRESHOLD = 0.50

# Sleeve configuration
SLEEVE_SIZE = 7              # 7 names in sleeve (mid between 5 and 10)
P_ENTRY_THRESHOLD = 0.30
P_TP_THRESHOLD = 0.50
P_SL_THRESHOLD = 0.70
MIN_HOLD_MONTHS = 3          # don't exit in first 3 months
RULE_BASED_TP_RETURN = 3.0   # +300% triggers rule-based take-profit if momentum turns
RULE_BASED_SL_RETURN = -0.15 # -15% triggers rule-based stop-loss after min hold
RULE_BASED_SL_MIN_MONTHS = 6
QUALITY_MIN_MCAP = 1e9
QUALITY_MIN_REV = 1e8

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


def prep_features(df, extra_exclude=None):
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    label_cols = {"label", "tp_label", "sl_label"}
    exclude = EXCLUDE_FEATURES | label_cols | (extra_exclude or set())
    feats = [c for c in numeric if c not in exclude and not c.startswith("score")]
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


# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("Loading data ...")
fs = pd.read_parquet(FEATURE_STORE)
fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
fs = fs.dropna(subset=["rebalance_date", "ticker"]).reset_index(drop=True)
episodes = pd.read_csv(EPISODES_CSV)
episodes["surge_start_date"] = pd.to_datetime(episodes["surge_start_date"])
episodes["peak_date"] = pd.to_datetime(episodes["peak_date"])
print(f"  feature_store: {len(fs)} rows")

# ---------------------------------------------------------------------------
# 2. Construct labels for all 3 classifiers + train
# ---------------------------------------------------------------------------
print("\nConstructing labels ...")
# Entry label
fs["label"] = 0
for ticker, grp in episodes.groupby("ticker"):
    mask_t = fs["ticker"] == ticker
    for _, ep in grp.iterrows():
        pre = ep["surge_start_date"] - pd.DateOffset(months=6)
        post = ep["surge_start_date"] + pd.DateOffset(months=3)
        fs.loc[mask_t & (fs["rebalance_date"] >= pre) & (fs["rebalance_date"] <= post), "label"] = 1

# TP label
fs["tp_label"] = -9
for ticker, grp in episodes.groupby("ticker"):
    mask_t = fs["ticker"] == ticker
    for _, ep in grp.iterrows():
        surge = ep["surge_start_date"]
        peak = ep["peak_date"]
        near_peak_start = peak - pd.DateOffset(months=2)
        near_peak_end = peak + pd.DateOffset(months=1)
        healthy_end = peak - pd.DateOffset(months=3)
        pos_mask = (fs["rebalance_date"] >= near_peak_start) & (fs["rebalance_date"] <= near_peak_end)
        fs.loc[mask_t & pos_mask, "tp_label"] = 1
        neg_mask = (fs["rebalance_date"] >= surge) & (fs["rebalance_date"] <= healthy_end)
        curr = fs.loc[mask_t & neg_mask, "tp_label"]
        fs.loc[curr.index[curr == -9], "tp_label"] = 0

# SL label (honest forward-return)
fs["sl_label"] = -9
r12 = pd.to_numeric(fs["r_12m"], errors="coerce")
fs.loc[r12 < -0.15, "sl_label"] = 1
fs.loc[r12 > 0.20, "sl_label"] = 0

# Prepare full feature matrix for predictions
X_full, good_feats = prep_features(fs)

# Train each classifier on TRAIN subset
train_mask_all = fs["rebalance_date"] < SPLIT_DATE

# ENTRY
print("\nTraining ENTRY classifier ...")
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from catboost import CatBoostClassifier

entry_train_mask = train_mask_all & (fs["label"] >= 0)  # 0/1 only, no exclusion
entry_y = fs.loc[entry_train_mask, "label"].astype(int).values
entry_X = X_full.loc[entry_train_mask].values
scaler_e = StandardScaler().fit(entry_X)
entry_lr = LogisticRegression(penalty="l2", C=1.0, class_weight="balanced",
                              max_iter=2000, random_state=42).fit(scaler_e.transform(entry_X), entry_y)
entry_cb = CatBoostClassifier(iterations=500, learning_rate=0.03, depth=6,
                              auto_class_weights="Balanced", random_seed=42, verbose=False).fit(entry_X, entry_y)
# Predict on all test rows
test_mask_all = fs["rebalance_date"] >= SPLIT_DATE
X_test_s = scaler_e.transform(X_full.loc[test_mask_all].values)
X_test_r = X_full.loc[test_mask_all].values
p_entry_lr = entry_lr.predict_proba(X_test_s)[:, 1]
p_entry_cb = entry_cb.predict_proba(X_test_r)[:, 1]
fs.loc[test_mask_all, "p_entry"] = 0.5 * p_entry_lr + 0.5 * p_entry_cb

# TP (only trained on in-surge rows)
print("Training TAKE_PROFIT classifier ...")
tp_train_mask = train_mask_all & (fs["tp_label"] >= 0)
if tp_train_mask.sum() >= 30:
    tp_y = fs.loc[tp_train_mask, "tp_label"].astype(int).values
    tp_X = X_full.loc[tp_train_mask].values
    scaler_tp = StandardScaler().fit(tp_X)
    tp_lr = LogisticRegression(penalty="l2", C=1.0, class_weight="balanced",
                               max_iter=2000, random_state=42).fit(scaler_tp.transform(tp_X), tp_y)
    tp_cb = CatBoostClassifier(iterations=500, learning_rate=0.03, depth=6,
                               auto_class_weights="Balanced", random_seed=42, verbose=False).fit(tp_X, tp_y)
    p_tp_lr = tp_lr.predict_proba(scaler_tp.transform(X_full.loc[test_mask_all].values))[:, 1]
    p_tp_cb = tp_cb.predict_proba(X_full.loc[test_mask_all].values)[:, 1]
    fs.loc[test_mask_all, "p_tp"] = 0.5 * p_tp_lr + 0.5 * p_tp_cb
else:
    print("  WARN: insufficient TP training data, using default=0")
    fs.loc[test_mask_all, "p_tp"] = 0.0

# SL
print("Training STOP_LOSS classifier ...")
sl_train_mask = train_mask_all & (fs["sl_label"] >= 0)
sl_y = fs.loc[sl_train_mask, "sl_label"].astype(int).values
sl_X = X_full.loc[sl_train_mask].values
scaler_sl = StandardScaler().fit(sl_X)
sl_lr = LogisticRegression(penalty="l2", C=1.0, class_weight="balanced",
                           max_iter=2000, random_state=42).fit(scaler_sl.transform(sl_X), sl_y)
sl_cb = CatBoostClassifier(iterations=500, learning_rate=0.03, depth=6,
                           auto_class_weights="Balanced", random_seed=42, verbose=False).fit(sl_X, sl_y)
p_sl_lr = sl_lr.predict_proba(scaler_sl.transform(X_full.loc[test_mask_all].values))[:, 1]
p_sl_cb = sl_cb.predict_proba(X_full.loc[test_mask_all].values)[:, 1]
fs.loc[test_mask_all, "p_sl"] = 0.5 * p_sl_lr + 0.5 * p_sl_cb

print("  All 3 classifiers trained + predictions generated.")

# Subset to test period with predictions
test_df = fs.loc[test_mask_all].copy().reset_index(drop=True)
print(f"  Test rows with predictions: {len(test_df)}")

# ---------------------------------------------------------------------------
# 3. Load monthly price data for backtest
# ---------------------------------------------------------------------------
print("\nLoading monthly close prices ...")
prices = {}
for ticker in test_df["ticker"].unique():
    p = PRICE_CACHE / px_cache_name(ticker)
    if not p.exists():
        continue
    try:
        df = pd.read_parquet(p)
    except Exception:
        continue
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    if col not in df.columns:
        continue
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    s.index = pd.to_datetime(s.index)
    monthly = s.resample("ME").last().dropna()
    prices[ticker] = monthly

print(f"  Loaded prices for {len(prices)} tickers")

# ---------------------------------------------------------------------------
# 4. Backtest simulation
# ---------------------------------------------------------------------------
print("\nRunning backtest simulation ...")

test_months = sorted(test_df["rebalance_date"].unique())
print(f"  Test months: {len(test_months)} ({test_months[0]} to {test_months[-1]})")


def get_price(ticker, date):
    if ticker not in prices:
        return None
    s = prices[ticker]
    valid = s[s.index <= date]
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def run_sleeve_backtest(
    test_df,
    prices,
    test_months,
    sleeve_size=7,
    p_entry_threshold=0.30,
    p_tp_threshold=0.50,
    p_sl_threshold=0.70,
    min_hold_months=3,
    rule_tp_return=3.0,
    rule_sl_return=-0.15,
    rule_sl_min_months=6,
    quality_min_mcap=1e9,
    quality_min_rev=1e8,
    weighting="equal",  # "equal" or "pscore" (P(entry) weighted)
):
    """Return monthly portfolio return series + trade log."""
    holdings = {}  # ticker -> {"entry_date", "entry_price", "held_months"}
    monthly_returns = []
    trade_log = []

    for i, month_t in enumerate(test_months):
        month_df = test_df[test_df["rebalance_date"] == month_t].copy()
        if month_df.empty:
            monthly_returns.append({"date": month_t, "return": 0.0, "n_held": 0})
            continue

        # === EXIT STEP: evaluate current holdings ===
        exits = []
        for ticker in list(holdings.keys()):
            row = month_df[month_df["ticker"] == ticker]
            if row.empty:
                continue
            r = row.iloc[0]
            cur_price = get_price(ticker, month_t)
            if cur_price is None:
                continue
            entry_price = holdings[ticker]["entry_price"]
            held = holdings[ticker]["held_months"]
            pos_return = (cur_price / entry_price) - 1.0

            if held < min_hold_months:
                reason = None
            elif r.get("p_tp", 0) > p_tp_threshold:
                reason = "ml_take_profit"
            elif r.get("p_sl", 0) > p_sl_threshold:
                reason = "ml_stop_loss"
            elif pos_return > rule_tp_return and r.get("mom_3m", 0) < 0:
                reason = "rule_take_profit"
            elif held >= rule_sl_min_months and pos_return < rule_sl_return and r.get("p_entry", 0) < 0.20:
                reason = "rule_stop_loss"
            else:
                reason = None

            if reason:
                exits.append({"ticker": ticker, "exit_date": month_t, "exit_price": cur_price,
                              "entry_date": holdings[ticker]["entry_date"],
                              "entry_price": entry_price, "return": pos_return, "reason": reason})

        for ex in exits:
            trade_log.append(ex)
            del holdings[ex["ticker"]]

        # === MONTHLY RETURN COMPUTATION ===
        if holdings:
            # For each held position, compute 1-month return
            pos_returns = []
            weights = []
            for ticker, info in holdings.items():
                cur_price = get_price(ticker, month_t)
                if i + 1 < len(test_months):
                    next_month = test_months[i + 1]
                    next_price = get_price(ticker, next_month)
                    if cur_price is None or next_price is None:
                        continue
                    r1m = (next_price / cur_price) - 1.0
                    pos_returns.append(r1m)
                    weights.append(info.get("weight", 1.0))
            if pos_returns:
                w = np.array(weights)
                w = w / w.sum()
                r_port = float(np.dot(w, pos_returns))
            else:
                r_port = 0.0
        else:
            r_port = 0.0  # cash

        monthly_returns.append({"date": month_t, "return": r_port, "n_held": len(holdings)})

        # Increment held_months
        for ticker in holdings:
            holdings[ticker]["held_months"] += 1

        # === ENTRY STEP: fill empty slots ===
        empty = sleeve_size - len(holdings)
        if empty > 0:
            candidates = month_df[
                (month_df["p_entry"] >= p_entry_threshold)
                & (month_df["p_sl"] < 0.50)
                & (month_df["mktcap"] >= quality_min_mcap)
                & (month_df["revenues_ttm"] >= quality_min_rev)
                & (~month_df["ticker"].isin(holdings.keys()))
            ].copy()
            if not candidates.empty:
                candidates = candidates.nlargest(empty, "p_entry")
                for _, c in candidates.iterrows():
                    p = get_price(c["ticker"], month_t)
                    if p is None:
                        continue
                    w = float(c["p_entry"]) if weighting == "pscore" else 1.0
                    holdings[c["ticker"]] = {
                        "entry_date": month_t,
                        "entry_price": p,
                        "held_months": 0,
                        "p_entry_at_entry": float(c["p_entry"]),
                        "weight": w,
                    }

    ret_df = pd.DataFrame(monthly_returns)
    ret_df["date"] = pd.to_datetime(ret_df["date"])
    return ret_df, pd.DataFrame(trade_log), holdings


# Run multiple configurations
print("\n=== Running sleeve configurations ===")

configs = [
    {"name": "size5_equal",        "sleeve_size": 5,  "weighting": "equal"},
    {"name": "size7_equal",        "sleeve_size": 7,  "weighting": "equal"},
    {"name": "size10_equal",       "sleeve_size": 10, "weighting": "equal"},
    {"name": "size5_pscore",       "sleeve_size": 5,  "weighting": "pscore"},
    {"name": "size7_pscore",       "sleeve_size": 7,  "weighting": "pscore"},
    {"name": "size10_pscore",      "sleeve_size": 10, "weighting": "pscore"},
]

results = {}
for cfg in configs:
    print(f"  {cfg['name']}: ", end="", flush=True)
    ret_df, trades, _ = run_sleeve_backtest(
        test_df, prices, test_months,
        sleeve_size=cfg["sleeve_size"],
        weighting=cfg["weighting"],
    )
    if ret_df["return"].std() == 0:
        print("all-zero returns, skipping")
        continue
    # Compute metrics
    returns = ret_df["return"].values
    months = len(returns)
    cumulative = (1 + returns).prod()
    years = months / 12
    cagr = cumulative ** (1 / years) - 1 if years > 0 else 0
    ann_vol = returns.std() * np.sqrt(12)
    sharpe = (returns.mean() * 12) / ann_vol if ann_vol > 0 else 0
    # Max drawdown
    wealth = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(wealth)
    dd = (wealth - peak) / peak
    max_dd = dd.min()
    avg_held = ret_df["n_held"].mean()
    win_rate = (returns > 0).mean()
    total_trades = len(trades)
    exit_reasons = trades["reason"].value_counts().to_dict() if not trades.empty else {}

    results[cfg["name"]] = {
        "cagr": cagr, "sharpe": sharpe, "max_dd": max_dd, "win_rate": win_rate,
        "avg_held": avg_held, "total_trades": total_trades,
        "exit_reasons": exit_reasons, "months": months,
    }
    print(f"CAGR={cagr:.2%}  Sharpe={sharpe:.2f}  MDD={max_dd:.2%}  "
          f"avgN={avg_held:.1f}  trades={total_trades}")

# ---------------------------------------------------------------------------
# 5. Benchmark comparison (S&P 500 same period)
# ---------------------------------------------------------------------------
print("\n=== Benchmark: S&P 500 same period ===")
# Try to find SPY price
spy_file = PRICE_CACHE / px_cache_name("SPY")
if spy_file.exists():
    spy = pd.read_parquet(spy_file)
    col = "Adj Close" if "Adj Close" in spy.columns else "Close"
    spy_m = pd.to_numeric(spy[col], errors="coerce").resample("ME").last().dropna()
    spy_in = spy_m[(spy_m.index >= test_months[0]) & (spy_m.index <= test_months[-1])]
    if len(spy_in) >= 2:
        spy_ret = spy_in.pct_change().dropna().values
        spy_cagr = ((1 + spy_ret).prod()) ** (12 / len(spy_ret)) - 1
        spy_sharpe = (spy_ret.mean() * 12) / (spy_ret.std() * np.sqrt(12))
        spy_wealth = np.cumprod(1 + spy_ret)
        spy_peak = np.maximum.accumulate(spy_wealth)
        spy_dd = ((spy_wealth - spy_peak) / spy_peak).min()
        print(f"  SPY: CAGR={spy_cagr:.2%}  Sharpe={spy_sharpe:.2f}  MDD={spy_dd:.2%}  months={len(spy_ret)}")
    else:
        spy_cagr = None
else:
    print("  SPY price not found")
    spy_cagr = None

# ---------------------------------------------------------------------------
# 6. Allocation sensitivity — combine with main portfolio
# ---------------------------------------------------------------------------
print("\n=== Allocation sensitivity: main portfolio + phase11 sleeve ===")

# Load main baseline monthly returns from recent backtest equity_curve.csv
MAIN_EQUITY = DRIVE / "outputs" / "equity_curve.csv"
main_returns = None
if MAIN_EQUITY.exists():
    eq = pd.read_csv(MAIN_EQUITY)
    date_col = "rebalance_date" if "rebalance_date" in eq.columns else eq.columns[0]
    eq["date"] = pd.to_datetime(eq[date_col])
    strategy_col = "net_return" if "net_return" in eq.columns else None
    if strategy_col:
        eq_subset = eq[(eq["date"] >= test_months[0]) & (eq["date"] <= test_months[-1])]
        main_returns = pd.to_numeric(eq_subset[strategy_col], errors="coerce").fillna(0).values
        if len(main_returns) >= 10:
            main_cagr = ((1 + main_returns).prod()) ** (12 / len(main_returns)) - 1
            main_sharpe = (main_returns.mean() * 12) / (main_returns.std() * np.sqrt(12))
            main_wealth = np.cumprod(1 + main_returns)
            main_peak = np.maximum.accumulate(main_wealth)
            main_dd = ((main_wealth - main_peak) / main_peak).min()
            print(f"  MAIN: CAGR={main_cagr:.2%}  Sharpe={main_sharpe:.2f}  MDD={main_dd:.2%}  months={len(main_returns)}")
        else:
            print(f"  MAIN: insufficient data ({len(main_returns)} months)")
            main_returns = None
    else:
        print("  MAIN: no return column found in equity_curve.csv")
else:
    print("  MAIN: equity_curve.csv not found")

# Pick best-performing sleeve config for allocation study
best_config_name = max(results, key=lambda k: results[k]["cagr"])
best_results = results[best_config_name]
print(f"\nBest Phase 11 standalone: {best_config_name} -- CAGR {best_results['cagr']:.2%} Sharpe {best_results['sharpe']:.2f}")

# Re-run best config to get return series
print(f"\nAllocation sensitivity using {best_config_name}:")
best_cfg = next(c for c in configs if c["name"] == best_config_name)
best_ret_df, _, _ = run_sleeve_backtest(test_df, prices, test_months,
                                        sleeve_size=best_cfg["sleeve_size"],
                                        weighting=best_cfg["weighting"])
phase11_returns = best_ret_df["return"].values

if main_returns is not None and len(main_returns) >= 10 and len(phase11_returns) >= 10:
    # Align by truncating to min length (main may be shorter if earlier stop)
    n_common = min(len(main_returns), len(phase11_returns))
    main_r = main_returns[:n_common]
    p11_r = phase11_returns[:n_common]
    # Recompute main stats on truncated
    main_cagr = ((1 + main_r).prod()) ** (12 / n_common) - 1
    alloc_rows = []
    print(f"  Aligned to {n_common} common months")
    print(f"\n{'alloc':>8s} {'CAGR':>8s} {'Sharpe':>8s} {'MDD':>8s} {'vs main':>10s}")
    for alloc in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.00]:
        combined = (1 - alloc) * main_r + alloc * p11_r
        c_cagr = ((1 + combined).prod()) ** (12 / len(combined)) - 1
        c_sharpe = (combined.mean() * 12) / (combined.std() * np.sqrt(12)) if combined.std() > 0 else 0
        c_wealth = np.cumprod(1 + combined)
        c_peak = np.maximum.accumulate(c_wealth)
        c_dd = ((c_wealth - c_peak) / c_peak).min()
        delta_cagr_pp = (c_cagr - main_cagr) * 100
        alloc_rows.append({"alloc_phase11": alloc, "cagr": c_cagr, "sharpe": c_sharpe,
                           "max_dd": c_dd, "delta_cagr_pp": delta_cagr_pp})
        print(f"  {alloc:6.0%}  {c_cagr:7.2%}  {c_sharpe:7.2f}  {c_dd:7.2%}  {delta_cagr_pp:+9.2f}pp")
    pd.DataFrame(alloc_rows).to_csv(OUT_DIR / "phase11_allocation_sensitivity.csv", index=False)
elif main_returns is None:
    print("  [skipped - no main returns available]")
else:
    print(f"  [length mismatch: main={len(main_returns)} vs phase11={len(phase11_returns)}]")

# ---------------------------------------------------------------------------
# 7. Save all results
# ---------------------------------------------------------------------------
print("\nSaving results ...")
with open(OUT_DIR / "phase11_sleeve_backtest_results.json", "w", encoding="utf-8") as f:
    json.dump({
        "period": {"start": str(test_months[0]), "end": str(test_months[-1]), "months": len(test_months)},
        "configs": {k: {kk: (vv if not isinstance(vv, dict) else {str(kkk): vvv for kkk, vvv in vv.items()})
                        for kk, vv in v.items()} for k, v in results.items()},
        "benchmark_spy_cagr": float(spy_cagr) if spy_cagr is not None else None,
        "best_config": best_config_name,
    }, f, indent=2, default=str)

best_ret_df.to_csv(OUT_DIR / "phase11_sleeve_returns.csv", index=False)

# ---------------------------------------------------------------------------
# 8. Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("PHASE 11 STANDALONE SLEEVE BACKTEST RESULTS")
print("=" * 78)
print(f"\nTest period: {test_months[0]} to {test_months[-1]} ({len(test_months)} months)")
if spy_cagr is not None:
    print(f"\nSPY benchmark: CAGR {spy_cagr:.2%}")
if main_returns is not None:
    print(f"Main engine:   CAGR {main_cagr:.2%}  Sharpe {main_sharpe:.2f}  MDD {main_dd:.2%}")

print(f"\n{'Config':<18s} {'CAGR':>8s} {'Sharpe':>8s} {'MDD':>8s} {'avg N':>7s} {'trades':>7s}")
for name, r in sorted(results.items(), key=lambda kv: -kv[1]["cagr"]):
    print(f"  {name:<16s}  {r['cagr']:7.2%}  {r['sharpe']:7.2f}  {r['max_dd']:7.2%}  "
          f"{r['avg_held']:6.1f}  {r['total_trades']:6d}")

print(f"\nBest: {best_config_name}")
print(f"  Exit reasons: {best_results['exit_reasons']}")
print("\n" + "=" * 78)
