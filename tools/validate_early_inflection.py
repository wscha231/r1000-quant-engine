#!/usr/bin/env python3
"""validate_early_inflection — sanity-check Phase 15-B early_cycle_inflection_score.

Two modes:

  --mode latest      Compute early_cycle_inflection_score on the latest
                     scored_latest.csv snapshot (no full rebuild needed) and
                     rank candidates. Shows per-condition breakdown so you can
                     judge whether the top names are plausible "next SNDK / MU
                     6 months ago"-style setups.

  --mode historical  Scan a feature_store_*.parquet across all rebalance dates
                     and check whether the score actually fired BEFORE known
                     winners broke out (e.g. SNDK +125% in 3 months in
                     2026-04). Use after the next FULL rebuild produces a
                     fresh feature_store.

Usage:
    py -3 tools/validate_early_inflection.py --mode latest \\
        --scored cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv \\
        --top 30

    py -3 tools/validate_early_inflection.py --mode historical \\
        --feature-store outputs/feature_store_latest.parquet \\
        --winners SNDK,MU,WDC,AMKR,MRVL,CIEN \\
        --lead-months 6

Output (--mode latest): pretty table to stdout + optional CSV via --out.
Output (--mode historical): per-winner timeline of score firings vs price
return — answers "did the score predict this winner?" empirically.

Ship-gate decision: if --mode latest top 30 is dominated by names that
don't look like reasonable cycle-bottom plays (random momentum names,
already-extended names), the score design needs tightening BEFORE the
3-3.5h cloud full_rebuild. Don't burn cloud minutes on a flawed score.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_features import compute_early_cycle_inflection_score  # noqa: E402

CONDITION_COLS = [
    "ticker", "sector", "score", "early_cycle_inflection_score",
    "dist_ma200", "mom_12m", "mom_3m", "mom_6m",
    "eps_revision_proxy", "any_profit_sign_flip_pos",
    "industry_breadth_above_ma200",
    "portfolio_sleeve_label",
]


def _format_pct(v: Optional[float], width: int = 7) -> str:
    if v is None or pd.isna(v):
        return f"{'NaN':>{width}s}"
    return f"{float(v) * 100:+{width-2}.1f}%"


def _format_score(v: Optional[float], width: int = 6) -> str:
    if v is None or pd.isna(v):
        return f"{'NaN':>{width}s}"
    return f"{float(v):>{width}.3f}"


def run_latest_mode(scored_path: Path, top_n: int, out_csv: Optional[Path]) -> int:
    if not scored_path.exists():
        print(f"ERROR: scored_latest.csv not found at {scored_path}", file=sys.stderr)
        return 2
    df = pd.read_csv(scored_path)
    print(f"[latest] loaded {len(df)} rows from {scored_path.name}")

    required = ["mom_3m", "mom_12m", "dist_ma200", "eps_revision_proxy",
                "any_profit_sign_flip_pos", "industry_breadth_above_ma200"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"WARN: missing input columns (will be NaN-filled to 0): {missing}", file=sys.stderr)

    df = compute_early_cycle_inflection_score(df)

    cols_present = [c for c in CONDITION_COLS if c in df.columns]
    top = df.nlargest(top_n, "early_cycle_inflection_score")[cols_present].copy()

    print()
    print(f"=== Top {top_n} by early_cycle_inflection_score ===")
    print(f"{'rank':>4s} {'ticker':<6s} {'sector':<24s} {'score':>6s} "
          f"{'early':>6s} {'distMA':>8s} {'mom12':>8s} {'mom3':>8s} "
          f"{'epsRev':>8s} {'flip':>5s} {'indBr':>7s} {'sleeve':<18s}")
    print("-" * 130)
    for i, (_, r) in enumerate(top.iterrows(), 1):
        print(
            f"{i:>4d} {str(r.get('ticker','')):<6s} {str(r.get('sector','?'))[:24]:<24s} "
            f"{_format_score(r.get('score'), 6)} "
            f"{_format_score(r.get('early_cycle_inflection_score'), 6)} "
            f"{_format_pct(r.get('dist_ma200'), 8)} "
            f"{_format_pct(r.get('mom_12m'), 8)} "
            f"{_format_pct(r.get('mom_3m'), 8)} "
            f"{_format_pct(r.get('eps_revision_proxy'), 8)} "
            f"{int(r.get('any_profit_sign_flip_pos', 0) or 0):>5d} "
            f"{_format_score(r.get('industry_breadth_above_ma200'), 7)} "
            f"{str(r.get('portfolio_sleeve_label','?'))[:18]:<18s}"
        )

    print()
    print(f"=== Score distribution ===")
    print(df["early_cycle_inflection_score"].describe(
        percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]
    ).to_string())
    print()
    print(f"  >= 0.50 (strong):    {int((df['early_cycle_inflection_score'] >= 0.50).sum()):>4d} names")
    print(f"  >= 0.40 (good):      {int((df['early_cycle_inflection_score'] >= 0.40).sum()):>4d} names")
    print(f"  >= 0.30 (moderate):  {int((df['early_cycle_inflection_score'] >= 0.30).sum()):>4d} names")

    if out_csv:
        out_cols = list(set(cols_present) | {"early_cycle_inflection_score"})
        df.nlargest(min(100, len(df)), "early_cycle_inflection_score")[out_cols].to_csv(out_csv, index=False)
        print(f"\n[csv] wrote top 100 to {out_csv}")

    print()
    print("Sanity check guidelines:")
    print("  - Top names should NOT be already-extended winners (mom_12m > +60%).")
    print("  - dist_ma200 should be -10% to +5% (not deep below, not far above).")
    print("  - mom_3m should be -5% to +20% (early turn, not full breakout).")
    print("  - Sectors should be diverse — not all semiconductors.")
    print("  - eps_revision_proxy or any_profit_sign_flip_pos should fire on most.")
    return 0


def run_historical_mode(
    fs_path: Path, winners: list[str], lead_months: int, out_csv: Optional[Path]
) -> int:
    if not fs_path.exists():
        print(f"ERROR: feature_store not found at {fs_path}", file=sys.stderr)
        print("HINT: run a FULL rebuild first; feature_store is produced by the engine.", file=sys.stderr)
        return 2
    fs = pd.read_parquet(fs_path)
    print(f"[historical] loaded {len(fs)} rows from {fs_path.name}")
    if "rebalance_date" not in fs.columns or "ticker" not in fs.columns:
        print("ERROR: feature_store missing required columns (rebalance_date / ticker)", file=sys.stderr)
        return 2

    fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
    fs = fs.dropna(subset=["rebalance_date"]).sort_values(["ticker", "rebalance_date"]).copy()

    print()
    print(f"=== Score firing history per winner (lead-time check) ===")
    print(f"For each winner, looks at score values {lead_months} months before "
          f"that ticker's all-time max return month.")

    fs = compute_early_cycle_inflection_score(fs)

    rows = []
    for w in winners:
        w = w.upper().strip()
        sub = fs[fs["ticker"].astype(str).str.upper() == w].sort_values("rebalance_date")
        if sub.empty:
            print(f"\n  {w:<6s} -> not in feature_store")
            continue
        # Find peak return month (proxy: highest mom_3m as of any date)
        if "mom_3m" not in sub.columns:
            print(f"\n  {w:<6s} -> no mom_3m column")
            continue
        peak_idx = sub["mom_3m"].idxmax()
        peak_date = sub.loc[peak_idx, "rebalance_date"]
        peak_mom_3m = sub.loc[peak_idx, "mom_3m"]
        # Find lookback row
        target_date = peak_date - pd.DateOffset(months=lead_months)
        prior = sub[sub["rebalance_date"] <= target_date]
        if prior.empty:
            print(f"\n  {w:<6s} -> insufficient history before peak")
            continue
        prior_row = prior.iloc[-1]
        prior_score = prior_row.get("early_cycle_inflection_score", float("nan"))
        prior_date = prior_row["rebalance_date"]
        rows.append({
            "ticker": w,
            "peak_date": str(peak_date.date()),
            "peak_mom_3m": peak_mom_3m,
            "checked_date": str(prior_date.date()),
            "score_at_check": prior_score,
            "fired_strong (>=0.50)": prior_score >= 0.50 if pd.notna(prior_score) else False,
            "fired_moderate (>=0.30)": prior_score >= 0.30 if pd.notna(prior_score) else False,
            "mom_3m_at_check": prior_row.get("mom_3m", float("nan")),
            "mom_12m_at_check": prior_row.get("mom_12m", float("nan")),
            "dist_ma200_at_check": prior_row.get("dist_ma200", float("nan")),
        })
        print(
            f"\n  {w:<6s} peak({str(peak_date.date())}) mom_3m={peak_mom_3m:+.1%}\n"
            f"          {lead_months}mo prior ({str(prior_date.date())}): "
            f"score={prior_score:.3f}  "
            f"mom_3m={prior_row.get('mom_3m', float('nan')):+.1%}  "
            f"mom_12m={prior_row.get('mom_12m', float('nan')):+.1%}  "
            f"dist_ma200={prior_row.get('dist_ma200', float('nan')):+.1%}"
        )

    if rows:
        result = pd.DataFrame(rows)
        n_strong = int(result["fired_strong (>=0.50)"].sum())
        n_moderate = int(result["fired_moderate (>=0.30)"].sum())
        print()
        print(f"=== Validation summary ===")
        print(f"  Winners checked:           {len(result)}")
        print(f"  Score fired strong (>=0.50): {n_strong}/{len(result)} = {100*n_strong/max(len(result),1):.0f}%")
        print(f"  Score fired moderate (>=0.30): {n_moderate}/{len(result)} = {100*n_moderate/max(len(result),1):.0f}%")
        print()
        if n_strong >= len(result) * 0.5:
            print("  VERDICT: design holds — score fires on majority of winners pre-breakout.")
        elif n_moderate >= len(result) * 0.5:
            print("  VERDICT: marginal — moderate fire rate. Consider tightening the threshold.")
        else:
            print("  VERDICT: design needs revision — score fails to fire on most winners.")
            print("  ACTION: re-check the 6 conditions, especially cond1/cond3 thresholds.")

        if out_csv:
            result.to_csv(out_csv, index=False)
            print(f"\n[csv] wrote validation results to {out_csv}")
    else:
        print("\n[historical] no winners matched in feature_store")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["latest", "historical"], default="latest")
    p.add_argument("--scored", default="cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv",
                   help="(latest mode) path to scored_latest.csv")
    p.add_argument("--feature-store", default="outputs/feature_store_latest.parquet",
                   help="(historical mode) path to feature_store_*.parquet")
    p.add_argument("--top", type=int, default=30, help="(latest mode) top N to print")
    p.add_argument("--winners", default="SNDK,MU,WDC,AMKR,MRVL,CIEN,NVDA,AVGO",
                   help="(historical mode) comma-separated winner tickers to validate")
    p.add_argument("--lead-months", type=int, default=6,
                   help="(historical mode) months before peak to check")
    p.add_argument("--out", default=None, help="optional output CSV path")
    args = p.parse_args()

    out_path = Path(args.out) if args.out else None
    if args.mode == "latest":
        return run_latest_mode(Path(args.scored), args.top, out_path)
    else:
        winners = [w.strip().upper() for w in args.winners.split(",") if w.strip()]
        return run_historical_mode(Path(args.feature_store), winners, args.lead_months, out_path)


if __name__ == "__main__":
    sys.exit(main())
