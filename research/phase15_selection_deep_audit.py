#!/usr/bin/env python3
"""phase15_selection_deep_audit.py

Deep research on the stock selection mechanism.

Motivation: user asks for a thorough audit to strengthen the current
selection system. Ranking quality is already weak (rank_ic_mean=0.019,
precision_at_k=0.046), and recent production CAGR (22.95% main / 33.17%
concentrated) is below user's 25%/40% targets.

This script answers four questions:

  1. WINNER RETROSPECTIVE
     - Which 20 tickers had the highest cumulative return over 83 months?
     - Did the engine select them? When (how early)?
     - How much did the engine miss?

  2. ML PREDICTION QUALITY
     - Correlation of each pred_* column with realized forward returns
     - Which predictor carries the most signal?
     - Per-horizon (1m vs 3m vs 12m) comparison

  3. TOP-N STABILITY
     - Month-to-month overlap of top-N selections per sleeve
     - Does flipping produce alpha or noise?
     - Average hold period per sleeve

  4. FEATURE IMPORTANCE STRUCTURE
     - Which features correlate most with forward returns at the
       universe level (per sleeve)?
     - Redundancy detection: which features are >0.9 correlated with
       another (candidate for dedup)?

Output: prints analysis + writes research/phase15_selection_deep_audit_report.md

Run:
  py -3 research/phase15_selection_deep_audit.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

SCORED_PATH = r"G:\내 드라이브\r1000_top30_institutional\feature_store\scored_oos_latest.parquet"
CONC_HOLD = r"G:\내 드라이브\r1000_top30_institutional\outputs\reports\concentrated_strategy_holdings.csv"
DIAG_MONTHLY = r"G:\내 드라이브\r1000_top30_institutional\outputs\reports\engine_diagnostics_by_month.csv"
REPORT = Path(__file__).parent / "phase15_selection_deep_audit_report.md"


def add_forward_returns(df):
    """Add forward_r_1m, forward_r_3m, forward_r_6m, forward_r_12m per ticker.

    forward_r_Hm(t) = sum of r_1m for months (t+1) .. (t+H).
    For H=1 this is simply shift(-1) of r_1m.
    """
    df = df.sort_values(["ticker", "rebalance_date"]).copy()
    r1m_next = df.groupby("ticker")["r_1m"].shift(-1)
    df["forward_r_1m"] = r1m_next
    for h, col in [(3, "forward_r_3m"), (6, "forward_r_6m"), (12, "forward_r_12m")]:
        # reverse the series within each ticker, rolling sum, then reverse back
        # simpler: iterate shift(-1), shift(-2), ..., shift(-h) and sum
        total = None
        for k in range(1, h + 1):
            shifted = df.groupby("ticker")["r_1m"].shift(-k)
            total = shifted if total is None else (total + shifted)
        df[col] = total
    return df


def q1_winner_retrospective(df, concentrated):
    """Identify cumulative winners and check if engine selected them."""
    print("=" * 90)
    print("Q1. WINNER RETROSPECTIVE")
    print("=" * 90)
    # Compute per-ticker cumulative return across full window
    df2 = df.sort_values(["ticker", "rebalance_date"]).copy()
    df2["r_1m_safe"] = pd.to_numeric(df2["r_1m"], errors="coerce").fillna(0.0)
    cum = df2.groupby("ticker").agg(
        n_months=("rebalance_date", "count"),
        cum_return=("r_1m_safe", lambda s: (1 + s).prod() - 1),
        avg_monthly=("r_1m_safe", "mean"),
        first_month=("rebalance_date", "min"),
    ).reset_index()
    cum["cum_return_pct"] = cum["cum_return"] * 100
    top20 = cum.nlargest(20, "cum_return")[["ticker", "n_months", "cum_return_pct", "avg_monthly"]]
    print("Top 20 cumulative winners (83-month window):")
    print(top20.to_string(index=False))
    print()

    # Engine selection check: for each top-20 winner, how many times was it in concentrated?
    conc_counts = concentrated["ticker"].value_counts().to_dict() if "ticker" in concentrated.columns else {}
    top20["conc_selection_count"] = top20["ticker"].map(conc_counts).fillna(0).astype(int)
    print("Did engine capture these winners? (concentrated selection count across grid)")
    print(top20[["ticker", "cum_return_pct", "conc_selection_count"]].to_string(index=False))
    print()

    # Missed opportunities: winners with ≤10 concentrated selections
    missed = top20[top20["conc_selection_count"] <= 10]
    if not missed.empty:
        print(f"MISSED WINNERS (concentrated picks ≤ 10 times): {missed['ticker'].tolist()}")
    else:
        print("Engine captured all top-20 winners with material selection frequency.")
    print()
    return top20, missed


def q2_ml_prediction_quality(df):
    """Correlate each ML predictor with realized forward returns."""
    print("=" * 90)
    print("Q2. ML PREDICTION QUALITY")
    print("=" * 90)
    pred_cols = [c for c in df.columns if c.startswith("pred_") or c in ("score_linear", "score_cat", "score_ranker", "score")]
    pred_cols = [c for c in pred_cols if not c.endswith("_p") or c in ("score",)]  # focus on regression / score
    results = []
    for target in ["forward_r_1m", "forward_r_3m", "forward_r_12m"]:
        for col in pred_cols:
            sub = df[[col, target]].dropna()
            if len(sub) < 1000:
                continue
            try:
                rho = stats.spearmanr(sub[col], sub[target]).statistic
            except Exception:
                continue
            # Per-month IC
            per_month_ic = []
            for date, grp in df.groupby("rebalance_date"):
                sub2 = grp[[col, target]].dropna()
                if len(sub2) >= 30:
                    try:
                        r = stats.spearmanr(sub2[col], sub2[target]).statistic
                        if np.isfinite(r):
                            per_month_ic.append(r)
                    except Exception:
                        pass
            if per_month_ic:
                mean_ic = np.mean(per_month_ic)
                std_ic = np.std(per_month_ic, ddof=1) if len(per_month_ic) > 1 else 0
                ic_ir = mean_ic / std_ic if std_ic > 1e-10 else np.nan
                results.append({
                    "predictor": col,
                    "target": target,
                    "rho_pooled": round(rho, 4),
                    "ic_mean": round(mean_ic, 4),
                    "ic_ir": round(ic_ir, 3),
                    "n_months": len(per_month_ic),
                })
    res = pd.DataFrame(results).sort_values(["target", "ic_ir"], ascending=[True, False])
    print("Per-predictor IC vs forward returns:")
    for target in ["forward_r_1m", "forward_r_3m", "forward_r_12m"]:
        sub = res[res["target"] == target]
        if sub.empty:
            continue
        print(f"--- target = {target} ---")
        print(sub.head(10).to_string(index=False))
        print()
    return res


def q3_topn_stability(df):
    """How often do top-N selections change month-to-month?"""
    print("=" * 90)
    print("Q3. TOP-N SELECTION STABILITY")
    print("=" * 90)
    # Use score as ranking proxy
    df2 = df.copy()
    df2["rebalance_date"] = pd.to_datetime(df2["rebalance_date"])
    dates = sorted(df2["rebalance_date"].dropna().unique())

    overlap_history = []
    for i in range(1, len(dates)):
        prev_month = df2[df2["rebalance_date"] == dates[i-1]].nlargest(7, "score")["ticker"].tolist()
        curr_month = df2[df2["rebalance_date"] == dates[i]].nlargest(7, "score")["ticker"].tolist()
        overlap = len(set(prev_month) & set(curr_month))
        overlap_history.append({
            "date": dates[i], "overlap": overlap, "overlap_pct": overlap / 7 * 100
        })
    oh = pd.DataFrame(overlap_history)
    print(f"Top-7 month-to-month overlap (out of 7):")
    print(f"  mean: {oh['overlap'].mean():.1f} / 7   ({oh['overlap'].mean()/7*100:.1f}%)")
    print(f"  min:  {oh['overlap'].min()}")
    print(f"  max:  {oh['overlap'].max()}")
    print(f"  share of months with >= 5/7 overlap (high stability): {(oh['overlap'] >= 5).mean() * 100:.1f}%")
    print(f"  share of months with <= 2/7 overlap (churn): {(oh['overlap'] <= 2).mean() * 100:.1f}%")
    print()

    # Implied avg hold period = 1 / (1 - overlap_rate)
    mean_overlap_pct = oh['overlap'].mean() / 7
    if mean_overlap_pct < 1:
        avg_hold = 1 / (1 - mean_overlap_pct)
        print(f"Implied avg top-7 hold period: {avg_hold:.2f} months")
    print()
    return oh


def q4_feature_importance(df):
    """Find features most correlated with forward returns."""
    print("=" * 90)
    print("Q4. FEATURE IMPORTANCE vs FORWARD RETURNS")
    print("=" * 90)
    target = "forward_r_3m"  # 3m is the sweet spot per earlier IC audit
    # Candidate feature pool: numeric cols, exclude obvious non-features
    exclude = {target, "forward_r_1m", "forward_r_6m", "forward_r_12m", "r_1m", "r_3m", "r_6m", "r_12m",
               "r_24m", "r_36m", "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m",
               "bench_r_24m", "bench_r_36m", "mktcap"}
    feat_cols = [c for c in df.columns
                 if c not in exclude
                 and pd.api.types.is_numeric_dtype(df[c])
                 and df[c].notna().sum() > len(df) * 0.3]

    print(f"Auditing {len(feat_cols)} numeric features against {target}...")
    ic_rows = []
    for col in feat_cols:
        per_month_ic = []
        for date, grp in df.groupby("rebalance_date"):
            sub = grp[[col, target]].dropna()
            if len(sub) >= 50:
                try:
                    r = stats.spearmanr(sub[col], sub[target]).statistic
                    if np.isfinite(r):
                        per_month_ic.append(r)
                except Exception:
                    pass
        if len(per_month_ic) >= 30:
            mean_ic = np.mean(per_month_ic)
            std_ic = np.std(per_month_ic, ddof=1)
            ir = mean_ic / std_ic if std_ic > 1e-10 else np.nan
            ic_rows.append({
                "feature": col,
                "ic_mean": round(mean_ic, 4),
                "ic_ir": round(ir, 3) if np.isfinite(ir) else np.nan,
                "n_months": len(per_month_ic),
            })
    ic_df = pd.DataFrame(ic_rows).sort_values("ic_ir", ascending=False, na_position="last")
    ic_df = ic_df.dropna(subset=["ic_ir"])

    print(f"\nTop 25 features by 3m IC_IR (positive alpha):")
    print(ic_df.head(25).to_string(index=False))
    print(f"\nBottom 10 features by 3m IC_IR (negative alpha / drop candidates):")
    print(ic_df.tail(10).to_string(index=False))
    print()

    # Buckets
    strong = ic_df[ic_df["ic_ir"] >= 1.0]
    moderate = ic_df[(ic_df["ic_ir"] >= 0.5) & (ic_df["ic_ir"] < 1.0)]
    weak = ic_df[(ic_df["ic_ir"] > -0.3) & (ic_df["ic_ir"] < 0.5)]
    negative = ic_df[ic_df["ic_ir"] < -0.3]
    print(f"Feature strength buckets:")
    print(f"  STRONG (IR >= 1.0):  {len(strong)} features")
    print(f"  MODERATE (0.5-1.0):  {len(moderate)} features")
    print(f"  WEAK (-0.3 to 0.5):  {len(weak)} features  <-- prune candidates")
    print(f"  NEGATIVE (< -0.3):   {len(negative)} features  <-- urgent drop")
    print()
    return ic_df


def write_report(top20, missed, pred_res, stability_df, ic_df):
    lines = []
    lines.append("# Phase 15 — Stock Selection Deep Audit Report\n")
    lines.append(f"Generated: {pd.Timestamp.now()}\n\n")

    lines.append("## Q1. Winner retrospective (83-month cumulative)\n\n")
    lines.append(f"Top 20 cumulative winners:\n\n```\n{top20.to_string(index=False)}\n```\n\n")
    if not missed.empty:
        lines.append(f"**Missed winners** (≤10 concentrated selections): {missed['ticker'].tolist()}\n\n")
    else:
        lines.append("**Engine captured all top-20 winners with material selection frequency.**\n\n")

    lines.append("## Q2. ML predictor quality\n\n")
    for target in ["forward_r_1m", "forward_r_3m", "forward_r_12m"]:
        sub = pred_res[pred_res["target"] == target]
        if sub.empty:
            continue
        lines.append(f"### Target: {target}\n\n```\n{sub.head(10).to_string(index=False)}\n```\n\n")

    lines.append("## Q3. Top-7 month-to-month overlap\n\n")
    mo = stability_df["overlap"].mean()
    lines.append(f"- Mean top-7 overlap: {mo:.2f} / 7 ({mo/7*100:.1f}%)\n")
    lines.append(f"- High stability (≥5/7): {(stability_df['overlap'] >= 5).mean() * 100:.1f}% of months\n")
    lines.append(f"- High churn (≤2/7): {(stability_df['overlap'] <= 2).mean() * 100:.1f}% of months\n")
    lines.append(f"- Implied avg hold: {1 / (1 - mo / 7):.2f} months\n\n")

    lines.append("## Q4. Top features by 3m IC_IR (strongest predictors)\n\n")
    lines.append("### Top 25 (positive alpha)\n\n")
    lines.append(f"```\n{ic_df.head(25).to_string(index=False)}\n```\n\n")
    lines.append("### Bottom 10 (drop candidates)\n\n")
    lines.append(f"```\n{ic_df.tail(10).to_string(index=False)}\n```\n\n")

    strong = len(ic_df[ic_df['ic_ir'] >= 1.0])
    moderate = len(ic_df[(ic_df['ic_ir'] >= 0.5) & (ic_df['ic_ir'] < 1.0)])
    weak = len(ic_df[(ic_df['ic_ir'] > -0.3) & (ic_df['ic_ir'] < 0.5)])
    negative = len(ic_df[ic_df['ic_ir'] < -0.3])
    lines.append(f"### Feature strength buckets (n=~{len(ic_df)})\n\n")
    lines.append(f"- STRONG (IR ≥ 1.0): **{strong}** features\n")
    lines.append(f"- MODERATE (0.5-1.0): **{moderate}** features\n")
    lines.append(f"- WEAK (-0.3 to 0.5): **{weak}** features — prune candidates\n")
    lines.append(f"- NEGATIVE (< -0.3): **{negative}** features — urgent drop\n\n")

    REPORT.write_text("".join(lines), encoding="utf-8")
    print(f"\nWrote report: {REPORT}")


def main():
    print("Loading scored_oos_latest.parquet...")
    df = pd.read_parquet(SCORED_PATH)
    df = add_forward_returns(df)
    print(f"  rows={len(df):,} months={df.rebalance_date.nunique()} tickers={df.ticker.nunique()}")
    print()

    concentrated = pd.read_csv(CONC_HOLD)

    top20, missed = q1_winner_retrospective(df, concentrated)
    pred_res = q2_ml_prediction_quality(df)
    stability = q3_topn_stability(df)
    ic_df = q4_feature_importance(df)

    write_report(top20, missed, pred_res, stability, ic_df)


if __name__ == "__main__":
    main()
