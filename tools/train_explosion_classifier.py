#!/usr/bin/env python3
"""train_explosion_classifier — Phase 17 v3 Layer 11 dual entry/exit trainer.

Reads outputs/explosive_pattern_db/events.parquet (produced by
build_explosive_pattern_db.py) and trains 6 XGBoost binary classifiers:

    entry models  : was-this-snapshot-12mo-before-an-explosion?
                    (T-12mo / T-6mo / T-3mo)
    exit models   : will-price-be-lower-from-here-N-months-out?
                    (T+0 peak / T+3mo post-peak / T+6mo post-peak)

Features at each snapshot are computed on-demand from yfinance price
history (price-derived only — momentum, vol, RS-vs-SPY, RSI, MA-cross,
volume surge, log mcap proxy). Negative samples for entry models drawn
from random non-event dates within the same universe.

Outputs
=======
    outputs/explosive_pattern_db/models/
        entry_12mo.json
        entry_6mo.json
        entry_3mo.json
        exit_at_peak.json
        exit_post_peak_3mo.json
        exit_post_peak_6mo.json
        feature_importance.csv
        cv_metrics.json

Inference is NOT in this script. r1000_features.py:
compute_explosion_likelihood_score loads these JSON booster files and
emits the score column during the main pipeline.

Usage
=====
    python tools/train_explosion_classifier.py
    python tools/train_explosion_classifier.py --neg-per-pos 5 --cv-folds 5
    python tools/train_explosion_classifier.py --dry-run

Design notes
============
* yfinance is the data source (matches the miner). On-demand fetch is
  slow but the event count is small (expect 200-800 events globally),
  so total training time stays under ~30 min.
* If xgboost is missing, falls back to sklearn GradientBoostingClassifier
  so the workflow still produces a model (lower quality but bootstraps
  the pipeline).
* Negative sampling uses random dates from the SAME ticker universe
  excluding any 12-month window around real events — keeps survivorship
  / sector mix balanced.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "outputs" / "explosive_pattern_db"
MODEL_DIR = DB_DIR / "models"

SNAPSHOT_OFFSETS_MONTHS = [-12, -6, -3, 0, 3, 6]

# Entry models: positive label if a real explosion peak lies within N months
# from the snapshot date (matches the offset). Negative = random snapshot.
ENTRY_TARGETS = {
    "entry_12mo": -12,
    "entry_6mo": -6,
    "entry_3mo": -3,
}

# Exit models: from this snapshot, will price be LOWER 6 months forward?
# Trained on event-only rows so the model learns peak/post-peak topology.
EXIT_TARGETS = {
    "exit_at_peak": 0,
    "exit_post_peak_3mo": 3,
    "exit_post_peak_6mo": 6,
}

EXIT_FORWARD_MONTHS = 6      # all exit models look 6mo forward
EXIT_DROP_THRESHOLD = -0.10  # forward return < -10% = positive "exit" label

FEATURE_COLUMNS = [
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "vol_30d",
    "vol_90d",
    "max_dd_90d",
    "rs_vs_spy_3m",
    "rs_vs_spy_6m",
    "rsi_14",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "volume_surge",
    "dollar_vol_avg_20d_log",
    "mcap_proxy_log",
]


@dataclass
class Snapshot:
    ticker: str
    date: str
    label: int
    features: dict


# ----------------------------- feature compute ------------------------------

def fetch_history(ticker: str, start: str, end: str):
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return None
        df = df.rename(columns={"Close": "close", "Volume": "volume"})
        df["dollar_vol"] = df["close"] * df["volume"]
        info = t.info or {}
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        df["mcap_proxy"] = df["close"] * float(shares) if shares else np.nan
        return df[["close", "volume", "dollar_vol", "mcap_proxy"]]
    except Exception:
        return None


_SPY_CACHE: Optional["pandas.DataFrame"] = None  # noqa: F821


def get_spy_history(start: str, end: str):
    global _SPY_CACHE
    if _SPY_CACHE is not None:
        return _SPY_CACHE
    _SPY_CACHE = fetch_history("SPY", start, end)
    return _SPY_CACHE


def compute_features_at(hist, idx: int, spy_hist=None) -> Optional[dict]:
    """Compute the FEATURE_COLUMNS vector at row `idx` of hist."""
    import pandas as pd
    if hist is None or idx < 252 or idx >= len(hist):
        return None
    closes = hist["close"]
    if not np.isfinite(closes.iloc[idx]) or closes.iloc[idx] <= 0:
        return None

    def _ret(window):
        if idx - window < 0:
            return np.nan
        p0 = closes.iloc[idx - window]
        p1 = closes.iloc[idx]
        if not (np.isfinite(p0) and p0 > 0):
            return np.nan
        return float(p1 / p0 - 1.0)

    mom_1m = _ret(21)
    mom_3m = _ret(63)
    mom_6m = _ret(126)
    mom_12m = _ret(252)

    rets_30 = closes.iloc[max(0, idx - 30):idx + 1].pct_change().dropna()
    rets_90 = closes.iloc[max(0, idx - 90):idx + 1].pct_change().dropna()
    vol_30 = float(rets_30.std() * np.sqrt(252)) if len(rets_30) > 5 else np.nan
    vol_90 = float(rets_90.std() * np.sqrt(252)) if len(rets_90) > 10 else np.nan

    win90 = closes.iloc[max(0, idx - 90):idx + 1]
    max_dd_90 = float(win90.iloc[-1] / win90.cummax().iloc[-1] - 1.0) if len(win90) else np.nan

    # RS vs SPY (3m / 6m)
    rs_3m = rs_6m = np.nan
    if spy_hist is not None and len(spy_hist) > 0:
        try:
            spy_closes = spy_hist["close"]
            d = hist.index[idx]
            sp_idx = spy_closes.index.get_indexer([d], method="pad")[0]
            if sp_idx >= 252:
                spy_3m_ret = float(spy_closes.iloc[sp_idx] / spy_closes.iloc[sp_idx - 63] - 1.0)
                spy_6m_ret = float(spy_closes.iloc[sp_idx] / spy_closes.iloc[sp_idx - 126] - 1.0)
                if np.isfinite(mom_3m):
                    rs_3m = mom_3m - spy_3m_ret
                if np.isfinite(mom_6m):
                    rs_6m = mom_6m - spy_6m_ret
        except Exception:
            pass

    # RSI 14
    delta = closes.diff().iloc[max(0, idx - 14):idx + 1]
    up = delta.clip(lower=0).mean()
    down = -delta.clip(upper=0).mean()
    rsi_14 = float(100 - 100 / (1 + up / down)) if down and down > 0 else 50.0

    sma_50 = closes.iloc[max(0, idx - 50):idx + 1].mean()
    sma_200 = closes.iloc[max(0, idx - 200):idx + 1].mean()
    p_vs_50 = float(closes.iloc[idx] / sma_50 - 1.0) if sma_50 > 0 else np.nan
    p_vs_200 = float(closes.iloc[idx] / sma_200 - 1.0) if sma_200 > 0 else np.nan

    vol_30d = hist["volume"].iloc[max(0, idx - 30):idx + 1].mean()
    vol_180d = hist["volume"].iloc[max(0, idx - 180):idx + 1].mean()
    volume_surge = float(vol_30d / vol_180d) if vol_180d > 0 else np.nan

    dv_20 = hist["dollar_vol"].iloc[max(0, idx - 20):idx + 1].mean()
    dv_log = float(np.log1p(dv_20)) if np.isfinite(dv_20) and dv_20 > 0 else np.nan

    mcap = hist["mcap_proxy"].iloc[idx]
    mcap_log = float(np.log1p(mcap)) if np.isfinite(mcap) and mcap > 0 else np.nan

    return {
        "mom_1m": mom_1m,
        "mom_3m": mom_3m,
        "mom_6m": mom_6m,
        "mom_12m": mom_12m,
        "vol_30d": vol_30,
        "vol_90d": vol_90,
        "max_dd_90d": max_dd_90,
        "rs_vs_spy_3m": rs_3m,
        "rs_vs_spy_6m": rs_6m,
        "rsi_14": rsi_14,
        "price_vs_sma_50": p_vs_50,
        "price_vs_sma_200": p_vs_200,
        "volume_surge": volume_surge,
        "dollar_vol_avg_20d_log": dv_log,
        "mcap_proxy_log": mcap_log,
    }


# ----------------------------- snapshot building ----------------------------

def build_event_snapshots(events_df, args) -> tuple[list[Snapshot], dict]:
    """For each event, fetch hist once and emit one snapshot per offset.

    Returns
    -------
    snapshots : flat list (one Snapshot per event × offset)
    by_target : {target_name: list[Snapshot]} grouping for trainer
    """
    import pandas as pd
    snapshots: list[Snapshot] = []
    by_target: dict[str, list[Snapshot]] = {k: [] for k in {**ENTRY_TARGETS, **EXIT_TARGETS}}

    n_events = len(events_df)
    print(f"[train] building snapshots for {n_events} events ...")

    earliest = events_df["pre_run_date"].min()
    latest = events_df["peak_date"].max()
    spy_start = (pd.to_datetime(earliest) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    spy_end = (pd.to_datetime(latest) + pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    spy_hist = get_spy_history(spy_start, spy_end)

    for i, row in events_df.iterrows():
        if row.get("excluded"):
            continue
        ticker = str(row["ticker"]).upper()
        peak_date = pd.to_datetime(row["peak_date"])
        # Need: T-12mo .. T+12mo coverage (training feature window 252d → fetch +1y back)
        fetch_start = (peak_date - pd.Timedelta(days=int(2 * 365.25))).strftime("%Y-%m-%d")
        fetch_end = (peak_date + pd.Timedelta(days=int(1.5 * 365.25))).strftime("%Y-%m-%d")
        hist = fetch_history(ticker, fetch_start, fetch_end)
        if hist is None or hist.empty:
            continue

        for offset_m in SNAPSHOT_OFFSETS_MONTHS:
            snap_date = peak_date + pd.DateOffset(months=offset_m)
            try:
                snap_idx = hist.index.get_indexer([snap_date], method="nearest")[0]
            except Exception:
                continue
            if snap_idx < 252 or snap_idx >= len(hist):
                continue

            feats = compute_features_at(hist, snap_idx, spy_hist=spy_hist)
            if feats is None:
                continue

            # Entry label: positive iff offset matches an entry target (e.g. -12 → entry_12mo)
            for tgt_name, tgt_off in ENTRY_TARGETS.items():
                if offset_m == tgt_off:
                    s = Snapshot(ticker, str(hist.index[snap_idx].date()), label=1, features=feats)
                    by_target[tgt_name].append(s)
                    snapshots.append(s)

            # Exit label: forward 6mo return < threshold from this snapshot
            for tgt_name, tgt_off in EXIT_TARGETS.items():
                if offset_m == tgt_off:
                    fwd_idx = snap_idx + int(EXIT_FORWARD_MONTHS * 21)
                    if fwd_idx >= len(hist):
                        continue
                    p0 = hist["close"].iloc[snap_idx]
                    p1 = hist["close"].iloc[fwd_idx]
                    if not (p0 > 0 and np.isfinite(p1)):
                        continue
                    fwd_ret = float(p1 / p0 - 1.0)
                    label = 1 if fwd_ret < EXIT_DROP_THRESHOLD else 0
                    s = Snapshot(ticker, str(hist.index[snap_idx].date()), label=label, features=feats)
                    by_target[tgt_name].append(s)
                    snapshots.append(s)

        if i and i % 25 == 0:
            print(f"  [{i}/{n_events}] events processed", flush=True)

    return snapshots, by_target


def build_negative_snapshots(events_df, args, by_target: dict) -> None:
    """Sample random snapshots from the universe to act as negatives for
    entry models. Mutates by_target in place.

    A snapshot is rejected as a negative if it falls within [-15mo, +6mo]
    of any event peak for the same ticker (avoids leaking the event into
    the negative set).
    """
    import pandas as pd
    rng = np.random.default_rng(seed=42)
    universe = events_df["ticker"].unique().tolist()

    n_pos_total = sum(len(by_target[k]) for k in ENTRY_TARGETS)
    n_neg_target = int(n_pos_total * args.neg_per_pos)
    if n_neg_target <= 0:
        return

    print(f"[train] sampling {n_neg_target} negative snapshots from {len(universe)} tickers ...")

    # Map ticker -> blackout windows
    blackout: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for _, row in events_df.iterrows():
        if row.get("excluded"):
            continue
        t = str(row["ticker"]).upper()
        peak = pd.to_datetime(row["peak_date"])
        blackout.setdefault(t, []).append(
            (peak - pd.DateOffset(months=15), peak + pd.DateOffset(months=6))
        )

    # SPY history reused
    spy_hist = _SPY_CACHE

    n_added = 0
    attempts = 0
    while n_added < n_neg_target and attempts < n_neg_target * 8:
        attempts += 1
        ticker = str(rng.choice(universe)).upper()
        # random date in last 7 years (within typical history coverage)
        days_back = int(rng.integers(365, 7 * 365))
        rand_date = pd.Timestamp.now() - pd.Timedelta(days=days_back)

        # Reject if within event blackout
        if any(lo <= rand_date <= hi for lo, hi in blackout.get(ticker, [])):
            continue

        fetch_start = (rand_date - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        fetch_end = (rand_date + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        hist = fetch_history(ticker, fetch_start, fetch_end)
        if hist is None or hist.empty:
            continue
        try:
            idx = hist.index.get_indexer([rand_date], method="nearest")[0]
        except Exception:
            continue
        if idx < 252 or idx >= len(hist):
            continue

        feats = compute_features_at(hist, idx, spy_hist=spy_hist)
        if feats is None:
            continue
        s = Snapshot(ticker, str(hist.index[idx].date()), label=0, features=feats)
        # Add this single negative sample to all entry models
        for tgt in ENTRY_TARGETS:
            by_target[tgt].append(s)
        n_added += 1
        if n_added % 50 == 0:
            print(f"  [neg-sample] {n_added}/{n_neg_target}", flush=True)


# ----------------------------- training -------------------------------------

def train_one(target_name: str, snaps: list[Snapshot], args) -> dict:
    """Train one binary classifier; return CV metric dict."""
    import pandas as pd
    if len(snaps) < 20:
        print(f"[train] {target_name}: skipped — only {len(snaps)} samples")
        return {"target": target_name, "n_samples": len(snaps), "skipped": True}

    X = pd.DataFrame([s.features for s in snaps])[FEATURE_COLUMNS].astype(float)
    y = np.array([s.label for s in snaps], dtype=int)
    pos_rate = float(y.mean())
    if pos_rate <= 0 or pos_rate >= 1:
        print(f"[train] {target_name}: degenerate label (pos_rate={pos_rate}), skipped")
        return {"target": target_name, "n_samples": len(snaps), "pos_rate": pos_rate, "skipped": True}

    # Try xgboost first; fall back to sklearn
    booster_kind: str
    try:
        import xgboost as xgb
        from sklearn.model_selection import StratifiedKFold
        from sklearn.metrics import roc_auc_score, average_precision_score

        clf_kwargs = dict(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.0,
            objective="binary:logistic",
            eval_metric="auc",
            tree_method="hist",
            verbosity=0,
        )
        booster_kind = "xgboost"
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import StratifiedKFold
        from sklearn.metrics import roc_auc_score, average_precision_score
        booster_kind = "sklearn_gbdt"
        clf_kwargs = dict(n_estimators=200, max_depth=4, learning_rate=0.05)

    skf = StratifiedKFold(n_splits=args.cv_folds, shuffle=True, random_state=42)
    aucs: list[float] = []
    aps: list[float] = []
    for fold, (tr, te) in enumerate(skf.split(X, y)):
        if booster_kind == "xgboost":
            clf = xgb.XGBClassifier(**clf_kwargs)
        else:
            clf = GradientBoostingClassifier(**clf_kwargs)
        clf.fit(X.iloc[tr], y[tr])
        p = clf.predict_proba(X.iloc[te])[:, 1]
        try:
            aucs.append(float(roc_auc_score(y[te], p)))
        except ValueError:
            pass
        try:
            aps.append(float(average_precision_score(y[te], p)))
        except ValueError:
            pass

    # Final model on all data → save
    if booster_kind == "xgboost":
        final = xgb.XGBClassifier(**clf_kwargs)
        final.fit(X, y)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        final.save_model(str(MODEL_DIR / f"{target_name}.json"))
        importance = dict(zip(FEATURE_COLUMNS, final.feature_importances_.tolist()))
    else:
        from sklearn.ensemble import GradientBoostingClassifier
        final = GradientBoostingClassifier(**clf_kwargs)
        final.fit(X, y)
        # Save via joblib (sklearn pickle); JSON unsupported here.
        try:
            import joblib
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(final, MODEL_DIR / f"{target_name}.pkl")
        except Exception:
            pass
        importance = dict(zip(FEATURE_COLUMNS, final.feature_importances_.tolist()))

    metrics = {
        "target": target_name,
        "booster": booster_kind,
        "n_samples": len(snaps),
        "pos_rate": pos_rate,
        "auc_mean": float(np.mean(aucs)) if aucs else None,
        "auc_std": float(np.std(aucs)) if aucs else None,
        "ap_mean": float(np.mean(aps)) if aps else None,
        "ap_std": float(np.std(aps)) if aps else None,
        "importance": importance,
    }
    print(
        f"[train] {target_name:>22s}  n={len(snaps):4d}  pos={pos_rate:.3f}  "
        f"auc={metrics['auc_mean']}  ap={metrics['ap_mean']}"
    )
    return metrics


# ----------------------------- main -----------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--neg-per-pos", type=float, default=4.0,
                   help="negative-sample multiplier for entry models (default 4)")
    p.add_argument("--cv-folds", type=int, default=5)
    p.add_argument("--limit-events", type=int, default=0,
                   help="train on at most N events (debug)")
    p.add_argument("--dry-run", action="store_true",
                   help="build snapshots, skip training")
    args = p.parse_args()

    events_path = DB_DIR / "events.parquet"
    if not events_path.exists():
        print(f"[train] ERROR: {events_path} not found. "
              f"Run tools/build_explosive_pattern_db.py first.", file=sys.stderr)
        return 2

    import pandas as pd
    events_df = pd.read_parquet(events_path)
    if args.limit_events:
        events_df = events_df.head(args.limit_events)

    print(f"[train] loaded {len(events_df)} events from {events_path}")
    print(f"[train] excluded: {int(events_df['excluded'].sum())}")
    print()

    snapshots, by_target = build_event_snapshots(events_df, args)
    build_negative_snapshots(events_df, args, by_target)

    print()
    print("[train] snapshot counts per target:")
    for k, v in by_target.items():
        pos = sum(1 for s in v if s.label == 1)
        print(f"    {k:>22s}  total={len(v):4d}  pos={pos:4d}  neg={len(v) - pos:4d}")
    print()

    if args.dry_run:
        print("[train] --dry-run set, skipping training")
        return 0

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    all_metrics = []
    for target in list(ENTRY_TARGETS) + list(EXIT_TARGETS):
        m = train_one(target, by_target[target], args)
        all_metrics.append(m)

    metrics_path = MODEL_DIR / "cv_metrics.json"
    metrics_path.write_text(json.dumps(all_metrics, indent=2, default=str))
    print(f"\n[train] wrote {metrics_path}")

    # Flatten importance to CSV
    rows = []
    for m in all_metrics:
        if m.get("skipped"):
            continue
        for feat, imp in (m.get("importance") or {}).items():
            rows.append({"target": m["target"], "feature": feat, "importance": imp})
    if rows:
        imp_df = pd.DataFrame(rows)
        imp_path = MODEL_DIR / "feature_importance.csv"
        imp_df.to_csv(imp_path, index=False)
        print(f"[train] wrote {imp_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
