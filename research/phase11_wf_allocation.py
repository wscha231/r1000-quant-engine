"""Phase 11 B1-extend: re-measure allocation sensitivity with WF returns.

Walk-forward Phase 11 standalone: CAGR 23.4% (vs static 31.1%).
Question: does 50/50 blend still improve over main (29.1%)?
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "research"
DRIVE = Path(r"G:\내 드라이브\r1000_top30_institutional")

wf = pd.read_csv(OUT_DIR / "phase11_walkforward_returns.csv")
wf["date"] = pd.to_datetime(wf["date"])
phase11_r = wf["return"].values
print(f"WF phase11: {len(phase11_r)} months")

# Load main
eq = pd.read_csv(DRIVE / "outputs" / "equity_curve.csv")
eq["date"] = pd.to_datetime(eq["rebalance_date"])
eq_sub = eq[(eq["date"] >= wf["date"].min()) & (eq["date"] <= wf["date"].max())]
main_r = pd.to_numeric(eq_sub["net_return"], errors="coerce").fillna(0).values
print(f"Main: {len(main_r)} months")

# Align
n = min(len(phase11_r), len(main_r))
phase11_r = phase11_r[:n]
main_r = main_r[:n]
print(f"Aligned: {n} months\n")


def metrics(r):
    c = (1 + r).prod()
    years = len(r) / 12
    cagr = c ** (1 / years) - 1 if years > 0 else 0
    vol = r.std() * np.sqrt(12)
    sharpe = (r.mean() * 12) / vol if vol > 0 else 0
    w = np.cumprod(1 + r)
    peak = np.maximum.accumulate(w)
    mdd = ((w - peak) / peak).min()
    return cagr, sharpe, mdd


main_cagr, main_sharpe, main_mdd = metrics(main_r)
p11_cagr, p11_sharpe, p11_mdd = metrics(phase11_r)
print(f"Main:      CAGR {main_cagr:.2%}  Sharpe {main_sharpe:.2f}  MDD {main_mdd:.2%}")
print(f"Phase11:   CAGR {p11_cagr:.2%}  Sharpe {p11_sharpe:.2f}  MDD {p11_mdd:.2%}")

# Correlation
corr = np.corrcoef(main_r, phase11_r)[0, 1]
print(f"\nMonthly-return correlation: {corr:.3f}")

# Allocation sensitivity
print(f"\n{'alloc':>8s} {'CAGR':>8s} {'Sharpe':>8s} {'MDD':>8s} {'ΔCAGR':>10s} {'ΔSharpe':>10s}")
rows = []
for alloc in [0.0, 0.10, 0.20, 0.30, 0.50, 0.70, 1.00]:
    c = (1 - alloc) * main_r + alloc * phase11_r
    cc, cs, cm = metrics(c)
    delta_cagr = (cc - main_cagr) * 100
    delta_sharpe = cs - main_sharpe
    rows.append({
        "alloc": alloc, "cagr": cc, "sharpe": cs, "mdd": cm,
        "delta_cagr_pp": delta_cagr, "delta_sharpe": delta_sharpe,
    })
    print(f"  {alloc:6.0%}  {cc:7.2%}  {cs:7.2f}  {cm:7.2%}  {delta_cagr:+9.2f}pp  {delta_sharpe:+10.2f}")

pd.DataFrame(rows).to_csv(OUT_DIR / "phase11_wf_allocation.csv", index=False)
print(f"\nSaved: phase11_wf_allocation.csv")

# Best alloc by CAGR and by Sharpe
rows_df = pd.DataFrame(rows)
print(f"\nBest alloc by CAGR:    {rows_df.loc[rows_df['cagr'].idxmax(), 'alloc']:.0%}  (CAGR {rows_df['cagr'].max():.2%})")
print(f"Best alloc by Sharpe:  {rows_df.loc[rows_df['sharpe'].idxmax(), 'alloc']:.0%}  (Sharpe {rows_df['sharpe'].max():.2f})")
