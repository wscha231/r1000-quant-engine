#!/usr/bin/env python3
"""trade_insights — Phase 18b (2026-04-30) AlphaTrade analysis layer.

Reads outputs/trade_journal/{trades,grades}.parquet (produced by 18a)
and emits three artifacts under outputs/trade_journal/insights/:

    ic_matrix.csv        Spearman rank-IC of each entry signal vs
                         realized_return, conditional on regime_state.
                         Rows = signals, cols = regimes.
                         Negative cell = signal mis-fires in that regime.

    cluster_winrate.csv  K-means clusters on entry_signal_breakdown.
                         Each cluster shows centroid + win_rate + n.
                         Lowest-win-rate cluster = trap pattern candidate.

    shap_importance.csv  XGBoost meta-model trained on entry features ->
                         realized_return. SHAP global importance per
                         signal + regime. Tells you WHICH signal causes
                         the most error variance.

    summary.md           Human-readable digest of all three with the top
                         actionable findings (e.g. "theme_phase IC = -0.05
                         in deep_bear, n=42 -> propose gate").

This script does NOT modify the engine. Phase 18c reads these CSVs and
proposes feature-gate YAML edits, gated by human review.

Usage
=====
    python tools/trade_insights.py
    python tools/trade_insights.py --trades outputs/trade_journal/trades.parquet
    python tools/trade_insights.py --no-shap            # skip SHAP
    python tools/trade_insights.py --clusters 10        # k for k-means
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = REPO_ROOT / "outputs" / "trade_journal"
INSIGHTS_DIR = JOURNAL_DIR / "insights"

# Signals we expect in entry_signal_breakdown JSON. Keep in sync with
# r1000_trade_journal.SIGNAL_BREAKDOWN_COLUMNS.
EXPECTED_SIGNALS = (
    "rs_acceleration_score",
    "h1_oversold_value_score",
    "h6_dynamic_leader_score",
    "stage2_overext_penalty",
    "theme_phase_multiplier_primary",
    "theme_phase_multiplier_max",
    "explosion_entry_score",
    "explosion_exit_score",
    "explosion_net_score",
)

REGIME_ORDER = ["deep_bear", "bear", "neutral", "bull", "strong_bull"]


# ----------------------------- IO + parsing ---------------------------------

def load_journal(trades_path: Path) -> Optional[pd.DataFrame]:
    if not trades_path.exists():
        return None
    if trades_path.suffix == ".csv":
        return pd.read_csv(trades_path)
    return pd.read_parquet(trades_path)


def expand_signal_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    """Parse entry_signal_breakdown JSON into one column per signal.

    Missing signal -> 0.0. Returns NEW DataFrame with original cols +
    one column per signal in EXPECTED_SIGNALS.
    """
    out = trades.copy()

    def _parse(s):
        if isinstance(s, dict):
            return s
        if isinstance(s, str):
            try:
                return json.loads(s) if s else {}
            except Exception:
                return {}
        return {}

    parsed = out["entry_signal_breakdown"].apply(_parse) if "entry_signal_breakdown" in out.columns else pd.Series([{}] * len(out), index=out.index)
    for sig in EXPECTED_SIGNALS:
        out[f"feat_{sig}"] = parsed.apply(lambda d, k=sig: float(d.get(k, 0.0)) if isinstance(d, dict) else 0.0)
    return out


# ----------------------------- IC matrix ------------------------------------

def compute_ic_matrix(trades_expanded: pd.DataFrame, min_n: int = 8) -> pd.DataFrame:
    """Spearman rank-IC of each feat_* signal vs realized_return,
    conditional on entry_regime_state. Cells with n < min_n -> NaN."""
    if trades_expanded.empty or "realized_return" not in trades_expanded.columns:
        return pd.DataFrame()

    realized = pd.to_numeric(trades_expanded["realized_return"], errors="coerce")
    regimes = trades_expanded.get("entry_regime_state", pd.Series("neutral", index=trades_expanded.index)).astype(str)

    rows: list[dict] = []
    for sig in EXPECTED_SIGNALS:
        col = f"feat_{sig}"
        if col not in trades_expanded.columns:
            continue
        sig_values = pd.to_numeric(trades_expanded[col], errors="coerce")
        rec: dict = {"signal": sig}
        # Aggregate IC across all regimes
        all_ok = sig_values.notna() & realized.notna()
        if all_ok.sum() >= min_n and sig_values[all_ok].std() > 0:
            rec["ic_all"] = float(sig_values[all_ok].rank().corr(realized[all_ok].rank(), method="pearson"))
            rec["n_all"] = int(all_ok.sum())
        else:
            rec["ic_all"] = float("nan")
            rec["n_all"] = int(all_ok.sum())
        # Per regime
        for reg in REGIME_ORDER:
            mask = (regimes == reg) & sig_values.notna() & realized.notna()
            n = int(mask.sum())
            if n >= min_n and sig_values[mask].std() > 0:
                ic = float(sig_values[mask].rank().corr(realized[mask].rank(), method="pearson"))
            else:
                ic = float("nan")
            rec[f"ic_{reg}"] = ic
            rec[f"n_{reg}"] = n
        rows.append(rec)

    return pd.DataFrame(rows)


# ----------------------------- Clustering -----------------------------------

def compute_cluster_winrate(
    trades_expanded: pd.DataFrame,
    n_clusters: int = 8,
    min_cluster_size: int = 5,
) -> pd.DataFrame:
    """K-means on feat_* columns; return per-cluster centroid + win_rate + n."""
    if trades_expanded.empty:
        return pd.DataFrame()
    feat_cols = [f"feat_{s}" for s in EXPECTED_SIGNALS if f"feat_{s}" in trades_expanded.columns]
    if not feat_cols:
        return pd.DataFrame()

    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return pd.DataFrame([{"error": "sklearn not installed"}])

    X = trades_expanded[feat_cols].astype(float).fillna(0.0).to_numpy()
    if len(X) < n_clusters * 2:
        return pd.DataFrame([{"error": f"too few trades ({len(X)}) for {n_clusters} clusters"}])

    Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    labels = km.fit_predict(Xs)

    realized = pd.to_numeric(trades_expanded["realized_return"], errors="coerce").fillna(0.0).to_numpy()
    grade_label = trades_expanded.get("grade_label")  # may be NaN if grades not yet merged

    centroids_unscaled = km.cluster_centers_  # in standardized space — for centroid display, invert
    rows: list[dict] = []
    for k in range(n_clusters):
        mask = labels == k
        n = int(mask.sum())
        if n < min_cluster_size:
            continue
        win_rate = float((realized[mask] > 0).mean())
        avg_ret = float(realized[mask].mean())
        loss_rate = float((realized[mask] < -0.10).mean())
        rec = {
            "cluster_id": k,
            "n": n,
            "win_rate": win_rate,
            "loss_rate": loss_rate,
            "avg_realized_return": avg_ret,
        }
        # Top 3 dominant signals (highest absolute centroid in std-space)
        cz = centroids_unscaled[k]
        order = np.argsort(-np.abs(cz))
        for j, idx in enumerate(order[:3], start=1):
            rec[f"top{j}_signal"] = feat_cols[idx].replace("feat_", "")
            rec[f"top{j}_centroid_z"] = float(cz[idx])
        rows.append(rec)

    df = pd.DataFrame(rows).sort_values("win_rate")
    return df


# ----------------------------- SHAP -----------------------------------------

def compute_shap_importance(trades_expanded: pd.DataFrame, n_estimators: int = 200) -> pd.DataFrame:
    """Train XGBoost on feat_* -> realized_return, return SHAP global
    importance per feature. Falls back to gain importance if shap not installed."""
    if trades_expanded.empty:
        return pd.DataFrame()
    feat_cols = [f"feat_{s}" for s in EXPECTED_SIGNALS if f"feat_{s}" in trades_expanded.columns]
    if not feat_cols:
        return pd.DataFrame()

    X = trades_expanded[feat_cols].astype(float).fillna(0.0).to_numpy()
    y = pd.to_numeric(trades_expanded["realized_return"], errors="coerce").fillna(0.0).to_numpy()
    if len(X) < 30 or float(np.std(y)) <= 0:
        return pd.DataFrame([{"error": f"insufficient samples ({len(X)}) or zero variance"}])

    try:
        import xgboost as xgb
    except ImportError:
        return pd.DataFrame([{"error": "xgboost not installed"}])

    model = xgb.XGBRegressor(
        n_estimators=n_estimators, max_depth=4, learning_rate=0.05,
        subsample=0.85, colsample_bytree=0.85, random_state=42, verbosity=0,
        tree_method="hist",
    )
    model.fit(X, y)
    rows: list[dict] = []
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(X)
        # Global importance = mean(|SHAP|) per feature
        mean_abs = np.mean(np.abs(sv), axis=0)
        for i, f in enumerate(feat_cols):
            rows.append({
                "signal": f.replace("feat_", ""),
                "shap_mean_abs": float(mean_abs[i]),
                "method": "shap",
            })
    except ImportError:
        # Fallback to gain importance
        gains = model.feature_importances_
        for i, f in enumerate(feat_cols):
            rows.append({
                "signal": f.replace("feat_", ""),
                "shap_mean_abs": float(gains[i]),
                "method": "xgb_gain",
            })

    return pd.DataFrame(rows).sort_values("shap_mean_abs", ascending=False)


# ----------------------------- Summary --------------------------------------

def write_summary(
    out_dir: Path,
    n_trades: int,
    ic_df: pd.DataFrame,
    cluster_df: pd.DataFrame,
    shap_df: pd.DataFrame,
) -> Path:
    """Generate human-readable insights summary in Markdown."""
    lines: list[str] = []
    lines.append(f"# Trade Insights Summary")
    lines.append("")
    lines.append(f"- trades analyzed: **{n_trades}**")
    lines.append(f"- generated: {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # IC findings
    lines.append("## 1. Signal IC by regime (rank correlation)")
    if ic_df.empty:
        lines.append("_(no IC data — too few trades or signals missing)_")
    else:
        lines.append("Top actionable findings:")
        # Most negative IC per signal × regime
        long = ic_df.melt(id_vars=["signal"],
                          value_vars=[c for c in ic_df.columns if c.startswith("ic_") and c != "ic_all"],
                          var_name="regime", value_name="ic")
        long["regime"] = long["regime"].str.replace("ic_", "", regex=False)
        long = long.dropna(subset=["ic"])
        if not long.empty:
            worst = long.sort_values("ic").head(3)
            lines.append("")
            lines.append("**Worst signal × regime cells (potential gate candidates)**:")
            for _, r in worst.iterrows():
                lines.append(f"- `{r['signal']}` in **{r['regime']}**: IC = {r['ic']:+.3f}")
            best = long.sort_values("ic", ascending=False).head(3)
            lines.append("")
            lines.append("**Best signal × regime cells (amplify candidates)**:")
            for _, r in best.iterrows():
                lines.append(f"- `{r['signal']}` in **{r['regime']}**: IC = {r['ic']:+.3f}")
        lines.append("")
        lines.append("Full matrix in `ic_matrix.csv`.")
    lines.append("")

    # Cluster findings
    lines.append("## 2. Trade pattern clusters")
    if cluster_df.empty or "error" in cluster_df.columns:
        lines.append(f"_(no clusters — {cluster_df.iloc[0]['error'] if not cluster_df.empty else 'no data'})_")
    else:
        worst = cluster_df.sort_values("win_rate").head(2)
        lines.append("**Worst pattern clusters (block candidates)**:")
        for _, r in worst.iterrows():
            sig_summary = ", ".join([f"{r.get(f'top{i}_signal','')}={r.get(f'top{i}_centroid_z',0):+.2f}" for i in range(1, 4) if r.get(f'top{i}_signal')])
            lines.append(f"- cluster {int(r['cluster_id'])}: win_rate={r['win_rate']:.2f}, n={int(r['n'])}, signature: {sig_summary}")
        best = cluster_df.sort_values("win_rate", ascending=False).head(2)
        lines.append("")
        lines.append("**Best pattern clusters (amplify candidates)**:")
        for _, r in best.iterrows():
            sig_summary = ", ".join([f"{r.get(f'top{i}_signal','')}={r.get(f'top{i}_centroid_z',0):+.2f}" for i in range(1, 4) if r.get(f'top{i}_signal')])
            lines.append(f"- cluster {int(r['cluster_id'])}: win_rate={r['win_rate']:.2f}, n={int(r['n'])}, signature: {sig_summary}")
    lines.append("")
    lines.append("Full table in `cluster_winrate.csv`.")
    lines.append("")

    # SHAP
    lines.append("## 3. SHAP / model importance")
    if shap_df.empty or "error" in shap_df.columns:
        lines.append(f"_(no SHAP — {shap_df.iloc[0]['error'] if not shap_df.empty else 'no data'})_")
    else:
        method = shap_df.iloc[0].get("method", "shap")
        lines.append(f"**Top 5 features by {method} importance** (impact on realized_return):")
        for _, r in shap_df.head(5).iterrows():
            lines.append(f"- `{r['signal']}`: {r['shap_mean_abs']:.4f}")
        lines.append("")
        lines.append("Full ranking in `shap_importance.csv`.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines))
    return path


# ----------------------------- main -----------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trades", default=str(JOURNAL_DIR / "trades.parquet"))
    p.add_argument("--out-dir", default=str(INSIGHTS_DIR))
    p.add_argument("--clusters", type=int, default=8)
    p.add_argument("--no-shap", action="store_true")
    p.add_argument("--min-ic-n", type=int, default=8)
    args = p.parse_args()

    trades_path = Path(args.trades)
    trades = load_journal(trades_path)
    if trades is None or trades.empty:
        print(f"[insights] ERROR: {trades_path} not found or empty.", file=sys.stderr)
        print(f"[insights] Run a backtest first to populate outputs/trade_journal/", file=sys.stderr)
        return 2

    print(f"[insights] loaded {len(trades)} trades from {trades_path}")

    # Optional grades merge
    grades_path = trades_path.parent / "grades.parquet"
    if grades_path.exists():
        try:
            grades = pd.read_parquet(grades_path)[["trade_id", "grade_label"]]
            trades = trades.merge(grades, on="trade_id", how="left")
            print(f"[insights] merged {len(grades)} grade rows")
        except Exception as exc:
            print(f"[insights] grade merge failed (non-fatal): {exc}")

    expanded = expand_signal_breakdown(trades)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[insights] computing IC matrix ...")
    ic_df = compute_ic_matrix(expanded, min_n=args.min_ic_n)
    if not ic_df.empty:
        ic_df.to_csv(out_dir / "ic_matrix.csv", index=False)

    print("[insights] computing cluster win-rates ...")
    cluster_df = compute_cluster_winrate(expanded, n_clusters=args.clusters)
    if not cluster_df.empty:
        cluster_df.to_csv(out_dir / "cluster_winrate.csv", index=False)

    if args.no_shap:
        shap_df = pd.DataFrame()
    else:
        print("[insights] computing SHAP importance ...")
        shap_df = compute_shap_importance(expanded)
        if not shap_df.empty:
            shap_df.to_csv(out_dir / "shap_importance.csv", index=False)

    print("[insights] writing summary.md ...")
    summary_path = write_summary(out_dir, len(trades), ic_df, cluster_df, shap_df)
    print(f"[insights] wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
