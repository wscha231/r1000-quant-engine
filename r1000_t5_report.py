"""r1000_t5_report - Detailed T5 turnaround candidates with full context.

Re-runs T5 detector across R1000 and produces a CSV with all the context user
needs for manual review:
  ticker, name, sector, T5 score
  current price, 52w high/low
  days below MA200 (Stage 4 length)
  off lows %, off high %
  RS 1m/3m/6m/12m
  Finnhub: PE, PEG, growth, insider, analyst
  Recommended action

User mandate (2026-04-25):
  "T5 차트 분석 가능 종목 검토 - 25개 turnaround 후보 직접 검토"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
from aggressive.finnhub_cache_loader import load_finnhub_features_dict
from aggressive.signals_technical import evaluate_ticker
from aggressive.universe import load_universe


def build_t5_report(min_score: float = 70.0, verbose: bool = True) -> pd.DataFrame:
    r1000, _ = load_universe("r1000")
    spy = fetch_spy_benchmark(days=400)
    fh = load_finnhub_features_dict()

    # Load IWB names + sector
    from aggressive.universe import fetch_iwb_holdings
    iwb = fetch_iwb_holdings()
    iwb_meta = {}
    if not iwb.empty:
        for _, row in iwb.iterrows():
            iwb_meta[str(row["ticker"]).upper()] = {
                "name": str(row.get("Name", "")),
                "sector": str(row.get("Sector", "Unknown")),
            }

    rows = []
    for i, t in enumerate(r1000, 1):
        if verbose and i % 100 == 0:
            print(f"  [{i}/{len(r1000)}]")
        df = fetch_daily_bars(t, days=400)
        if df.empty or len(df) < 252:
            continue
        res = evaluate_ticker(t, df, spy)
        t5 = res.tiers[4]
        if t5.score < min_score:
            continue

        # RS calculations
        c = df["close"]
        spy_close = spy["close"]
        aligned = pd.concat([c.rename("t"), spy_close.rename("s")],
                              axis=1, join="inner").dropna()
        rs = {}
        for label, days in [("rs_1m", 21), ("rs_3m", 63),
                              ("rs_6m", 126), ("rs_12m", 252)]:
            if len(aligned) >= days + 1:
                rs[label] = ((aligned["t"].iloc[-1]/aligned["t"].iloc[-days-1] - 1) -
                              (aligned["s"].iloc[-1]/aligned["s"].iloc[-days-1] - 1)) * 100

        meta = iwb_meta.get(t, {})
        fh_row = fh.get(t, {})

        rows.append({
            "ticker": t,
            "name": meta.get("name", "")[:30],
            "sector": meta.get("sector", "Unknown"),
            "t5_score": round(t5.score, 1),
            "t5_fired": t5.fired,
            "n_checks_passed": int(sum(t5.checks.values())),
            "current_price": float(c.iloc[-1]),
            "high_52w": float(c.tail(252).max()),
            "low_52w": float(c.tail(252).min()),
            "days_below_ma200": int(t5.metrics.get("days_below_ma200", 0)),
            "pct_off_low": round(t5.metrics.get("pct_off_52w_low", 0), 1),
            "pct_off_high": round(t5.metrics.get("pct_off_52w_high", 0), 1),
            "rs_1m_pct": round(rs.get("rs_1m", float("nan")), 1),
            "rs_3m_pct": round(rs.get("rs_3m", float("nan")), 1),
            "rs_6m_pct": round(rs.get("rs_6m", float("nan")), 1),
            "rs_12m_pct": round(rs.get("rs_12m", float("nan")), 1),
            "ma200_slope_now": round(t5.metrics.get("ma200_slope_now", 0), 3),
            "ma200_slope_60d_ago": round(t5.metrics.get("ma200_slope_60d_ago", 0), 3),
            "fh_pe_ttm": fh_row.get("fh_peExclExtra_ttm"),
            "fh_peg_5y": fh_row.get("fh_peg_5y"),
            "fh_eps_growth_q_yoy": fh_row.get("fh_epsGrowthQuarterlyYoy"),
            "fh_revenue_growth_q_yoy": fh_row.get("fh_revenueGrowthQuarterlyYoy"),
            "fh_roe_ttm": fh_row.get("fh_roe_ttm"),
            "fh_op_margin_ttm": fh_row.get("fh_operatingMargin_ttm"),
            "fh_insider_cluster_30d": fh_row.get("fh_insider_cluster_30d_score"),
            "fh_insider_n_buyers_30d": fh_row.get("fh_insider_n_buyers_30d"),
            "fh_analyst_bull_ratio": fh_row.get("fh_rec_bull_ratio"),
            "fh_analyst_total": fh_row.get("fh_rec_total"),
            "fh_days_to_earnings": fh_row.get("fh_days_to_next_earnings"),
            "rationale": t5.rationale,
        })

    return pd.DataFrame(rows).sort_values("t5_score", ascending=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-score", type=float, default=70.0)
    p.add_argument("--output", default="outputs/t5_turnaround_report.csv")
    args = p.parse_args()

    print("=" * 70)
    print(f"T5 Turnaround Report - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    print()

    df = build_t5_report(min_score=args.min_score)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"\n[save] {args.output} ({len(df)} candidates)")

    # Display top 25 with key columns
    if not df.empty:
        print()
        print("=" * 100)
        print("TOP T5 TURNAROUND CANDIDATES (sorted by score)")
        print("=" * 100)
        cols_show = ["ticker", "name", "sector", "t5_score",
                       "n_checks_passed",
                       "days_below_ma200", "pct_off_low", "pct_off_high",
                       "rs_3m_pct", "rs_12m_pct",
                       "fh_pe_ttm", "fh_peg_5y", "fh_eps_growth_q_yoy"]
        cols_show = [c for c in cols_show if c in df.columns]
        pd.set_option("display.width", 200)
        pd.set_option("display.max_columns", 20)
        print(df[cols_show].head(30).to_string(index=False))

        # Verdict guidance
        print()
        print("=" * 100)
        print("VERDICT GUIDANCE")
        print("=" * 100)
        for _, r in df.head(15).iterrows():
            verdict = []
            if r["n_checks_passed"] >= 7:
                verdict.append("STRONG turnaround")
            elif r["n_checks_passed"] >= 6:
                verdict.append("Solid")
            else:
                verdict.append("Marginal")

            if r.get("fh_peg_5y") and r["fh_peg_5y"] < 2.0:
                verdict.append("cheap PEG")
            if r.get("fh_eps_growth_q_yoy") and r["fh_eps_growth_q_yoy"] > 20:
                verdict.append("growth accelerating")
            if r.get("rs_3m_pct") and r["rs_3m_pct"] > 20:
                verdict.append("RS turning hard")
            if r.get("fh_days_to_earnings") and 0 <= r["fh_days_to_earnings"] <= 14:
                verdict.append(f"[!] earnings in {int(r['fh_days_to_earnings'])}d")

            print(f"  {r['ticker']:<6} {r['name'][:30]:<30}  "
                  f"{', '.join(verdict)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
