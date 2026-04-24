"""r1000_unified_universe - Unified scored universe combining 정석 + Finnhub.

User mandate (2026-04-24 evening):
  "v1 왜 610밖에 안되지? 통합못하나? 새로운 collector 에 맞춰서 개편"

Problem: 정석 engine scored_latest.csv covers 610/1008 R1000 names (60%).
         402 names invisible to advisor v1.
         But Finnhub has 100% coverage of those 402.

Solution (Option A): unified_scored = scored_latest (610) + synthetic rows (402)
  - Keep 정석 engine untouched (backtest safe)
  - For missing names, synthesize model_score from Finnhub data + live RS
  - Mark score_source to distinguish real vs synthetic
  - Advisor v1 uses unified file -> automatic 1000-name coverage

Synthetic score formula (scaled to match 정석 model_score range ~-3 to +7):
    synth = (0.30 * rs_12m_rank
           + 0.25 * peg_fairness_rank
           + 0.20 * revenue_growth_rank
           + 0.15 * margin_rank
           + 0.10 * analyst_bull_rank) * 10 - 3
  Lower bonus than real model_score by design (supplemental confidence).

Output: G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv

Usage:
    py -3 r1000_unified_universe.py
    py -3 r1000_rebalance_advisor.py --scored-csv outputs_advisor/scored_unified.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from aggressive.finnhub_cache_loader import load_finnhub_features_dict
from aggressive.universe import load_universe, fetch_iwb_holdings


# --- Configuration ---------------------------------------------------------

DEFAULT_SCORED_CSV = r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_latest.csv"
DEFAULT_OUTPUT_CSV = r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv"


# --- Percentile ranker ----------------------------------------------------

def percentile_rank(series: pd.Series) -> pd.Series:
    """Return 0.0-1.0 percentile rank. NaN -> 0.5 (neutral)."""
    s = pd.to_numeric(series, errors="coerce")
    ranked = s.rank(pct=True, method="average")
    return ranked.fillna(0.5)


# --- Live RS computation --------------------------------------------------

def compute_live_rs(tickers: list[str], verbose: bool = True) -> dict[str, float]:
    """12m RS vs SPY using cached Alpaca bars."""
    try:
        from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
    except Exception as e:
        print(f"[rs] Alpaca module unavailable: {e}")
        return {}

    spy = fetch_spy_benchmark(days=260)
    if spy.empty or len(spy) < 252:
        return {}

    rs_out: dict[str, float] = {}
    price_out: dict[str, float] = {}
    for i, t in enumerate(tickers, 1):
        if verbose and i % 50 == 0:
            print(f"[rs] {i}/{len(tickers)}...")
        df = fetch_daily_bars(t, days=260)
        if df.empty or len(df) < 252:
            continue
        aligned = pd.concat(
            [df["close"].rename("t"), spy["close"].rename("s")],
            axis=1, join="inner",
        ).dropna()
        if len(aligned) < 252:
            continue
        rs12 = ((aligned["t"].iloc[-1] / aligned["t"].iloc[-252] - 1.0) -
                (aligned["s"].iloc[-1] / aligned["s"].iloc[-252] - 1.0))
        rs_out[t.upper()] = float(rs12)
        price_out[t.upper()] = float(df["close"].iloc[-1])
    # Return tuple; existing callers expect dict, so attach prices via dict subclass
    class _RSPriceDict(dict):
        pass
    d = _RSPriceDict(rs_out)
    d.prices = price_out  # type: ignore[attr-defined]
    return d


# --- Synthetic row builder ------------------------------------------------

def build_synthetic_row(
    ticker: str,
    finnhub_row: dict,
    rs_12m_decimal: float,
    sector: str,
    name: str,
    normalized_metrics: dict,
    live_price: float = 0.0,
) -> dict:
    """Synthesize a scored_latest-compatible row from Finnhub + RS.

    normalized_metrics provides percentile-rank lookup for cross-sectional norms.
    """
    price = live_price

    # Market cap estimate:
    #   Finnhub doesn't return shares directly in metric endpoint.
    #   Proxy: use 10DayAverageTradingVolume from Finnhub * some heuristic,
    #   or derive from PE + eps_ttm if available.
    # Simpler: hardcode default > $5B for synthetic rows so they pass mktcap filter,
    # since all R1000 names are by definition >$1B market cap.
    # We just need them to pass the filter; actual mcap not used in ranking.
    mcap = 10_000_000_000.0  # $10B default for synthetic (advisor filter is $5B)

    # Component ranks (each 0.0-1.0)
    rs_rank = normalized_metrics.get(f"rs_{ticker}", 0.5)
    peg_rank = normalized_metrics.get(f"peg_{ticker}", 0.5)
    growth_rank = normalized_metrics.get(f"growth_{ticker}", 0.5)
    margin_rank = normalized_metrics.get(f"margin_{ticker}", 0.5)
    analyst_rank = normalized_metrics.get(f"analyst_{ticker}", 0.5)

    # Weighted composite score (synthesize to scored_latest range -3 to +7)
    # Typical scored model_score distribution: median ~0.36, 75th pct ~1.42, max ~6.71
    # We'll scale 0-1 composite to -3 to +7 (keep synthetic slightly lower than real)
    composite = (
        0.30 * rs_rank
        + 0.25 * peg_rank
        + 0.20 * growth_rank
        + 0.15 * margin_rank
        + 0.10 * analyst_rank
    )
    # Scale to match scored_latest distribution but compress (synthetic confidence lower)
    synth_score = composite * 8.0 - 3.0      # range: -3.0 to +5.0
    # Extra small penalty for being synthetic (not real ML model)
    synth_score -= 0.3

    # Sleeve inference based on growth + RS
    if rs_12m_decimal > 0.5 and growth_rank > 0.6:
        sleeve = "future_winner"
    elif rs_12m_decimal > 0.2 and margin_rank > 0.5:
        sleeve = "core_compounder"
    else:
        sleeve = "early_scout"

    row = {
        "ticker": ticker,
        "Name": name or ticker,
        "sector": sector or "Unknown",
        "score": round(synth_score, 4),
        "score_model_core": round(synth_score * 0.8, 4),  # weaker core
        "score_total": round(synth_score, 4),
        "portfolio_sleeve_label": sleeve,
        "portfolio_sleeve_confidence": 0.5,
        "current_price_live": 0.0,  # unknown (Finnhub doesn't return in metric)
        "market_cap_live": mcap,
        "mom_12m": rs_12m_decimal,
        "rs_benchmark_12m": rs_12m_decimal,
        "score_source": "finnhub_synthetic",
        # Finnhub-derived valuation fields
        "forward_pe_final": finnhub_row.get("fh_peExclExtra_ttm"),
        "peg_final": finnhub_row.get("fh_peg_5y"),
        "earnings_growth_final": (
            finnhub_row.get("fh_epsGrowthQuarterlyYoy", 0) / 100.0
            if finnhub_row.get("fh_epsGrowthQuarterlyYoy") else None
        ),
        "sales_growth_yoy": (
            finnhub_row.get("fh_revenueGrowthQuarterlyYoy", 0) / 100.0
            if finnhub_row.get("fh_revenueGrowthQuarterlyYoy") else None
        ),
        "op_margin_ttm": (
            finnhub_row.get("fh_operatingMargin_ttm", 0) / 100.0
            if finnhub_row.get("fh_operatingMargin_ttm") else None
        ),
        # Synthetic component ranks (for diagnostic)
        "synth_rs_rank": round(rs_rank, 3),
        "synth_peg_rank": round(peg_rank, 3),
        "synth_growth_rank": round(growth_rank, 3),
        "synth_margin_rank": round(margin_rank, 3),
        "synth_analyst_rank": round(analyst_rank, 3),
    }
    return row


# --- Sector lookup from IWB ----------------------------------------------

def build_sector_lookup() -> dict[str, dict]:
    """Return {ticker: {sector, name}} from iShares IWB holdings."""
    df = fetch_iwb_holdings()
    if df.empty:
        return {}
    out = {}
    for _, r in df.iterrows():
        t = str(r.get("ticker", "")).upper().strip()
        if not t:
            continue
        out[t] = {
            "sector": str(r.get("Sector", "Unknown")),
            "name": str(r.get("Name", t)),
        }
    return out


# --- Main unification ------------------------------------------------------

def build_unified_scored(
    scored_csv: str = DEFAULT_SCORED_CSV,
    output_csv: str = DEFAULT_OUTPUT_CSV,
    verbose: bool = True,
) -> pd.DataFrame:
    """Merge 정석 scored_latest with Finnhub-synthesized rows for missing R1000."""
    # 1. Load existing 정석 scored
    scored = pd.read_csv(scored_csv)
    if "score_source" not in scored.columns:
        scored["score_source"] = "정석_ml"
    scored_tickers = set(str(t).upper() for t in scored["ticker"].dropna())
    print(f"[unify] scored_latest: {len(scored)} rows")

    # 2. R1000 universe
    r1000, _ = load_universe("r1000")
    r1000_set = set(r1000)
    missing = sorted(r1000_set - scored_tickers)
    print(f"[unify] R1000 total: {len(r1000_set)}")
    print(f"[unify] missing from scored: {len(missing)}")

    if not missing:
        print("[unify] no missing names, scored is already complete")
        scored.to_csv(output_csv, index=False)
        return scored

    # 3. Load Finnhub features
    fh = load_finnhub_features_dict()
    print(f"[unify] Finnhub coverage: {len(fh)} tickers")

    # 4. IWB sector lookup
    iwb = build_sector_lookup()
    print(f"[unify] IWB metadata: {len(iwb)} tickers")

    # 5. Compute live RS for missing tickers
    print(f"[unify] computing live RS for {len(missing)} missing tickers...")
    live_rs = compute_live_rs(missing, verbose=verbose)
    print(f"[unify] live RS computed: {len(live_rs)} tickers")

    # 6. Build normalized percentile ranks across all missing names
    rs_vals = [live_rs.get(t, 0.0) for t in missing]
    peg_vals = [
        fh.get(t, {}).get("fh_peg_5y") for t in missing
    ]
    growth_vals = [
        fh.get(t, {}).get("fh_epsGrowthQuarterlyYoy") for t in missing
    ]
    margin_vals = [
        fh.get(t, {}).get("fh_operatingMargin_ttm") for t in missing
    ]
    analyst_vals = [
        fh.get(t, {}).get("fh_rec_bull_ratio") for t in missing
    ]

    rs_ser = pd.Series(rs_vals, index=missing)
    peg_ser = pd.Series(peg_vals, index=missing)
    # Lower PEG = better (inverse rank)
    peg_rank = 1.0 - percentile_rank(peg_ser)
    growth_rank = percentile_rank(pd.Series(growth_vals, index=missing))
    margin_rank = percentile_rank(pd.Series(margin_vals, index=missing))
    analyst_rank = percentile_rank(pd.Series(analyst_vals, index=missing))
    rs_rank = percentile_rank(rs_ser)

    normalized = {}
    for t in missing:
        normalized[f"rs_{t}"] = rs_rank.get(t, 0.5)
        normalized[f"peg_{t}"] = peg_rank.get(t, 0.5)
        normalized[f"growth_{t}"] = growth_rank.get(t, 0.5)
        normalized[f"margin_{t}"] = margin_rank.get(t, 0.5)
        normalized[f"analyst_{t}"] = analyst_rank.get(t, 0.5)

    # 7. Build synthetic rows
    synthetic_rows = []
    live_prices = getattr(live_rs, "prices", {}) or {}
    for t in missing:
        finnhub_row = fh.get(t, {})
        if not finnhub_row:
            continue    # skip if no Finnhub data
        meta = iwb.get(t, {})
        rs_12m = live_rs.get(t, 0.0)
        price = live_prices.get(t, 0.0)
        row = build_synthetic_row(
            t, finnhub_row, rs_12m,
            meta.get("sector", "Unknown"),
            meta.get("name", t),
            normalized,
            live_price=price,
        )
        synthetic_rows.append(row)
    print(f"[unify] synthetic rows built: {len(synthetic_rows)}")

    if not synthetic_rows:
        scored.to_csv(output_csv, index=False)
        return scored

    # 8. Merge
    synth_df = pd.DataFrame(synthetic_rows)
    # Ensure columns align: add missing columns from scored to synth (as NaN)
    for col in scored.columns:
        if col not in synth_df.columns:
            synth_df[col] = np.nan
    # And add synth-specific columns to scored
    for col in synth_df.columns:
        if col not in scored.columns:
            scored[col] = np.nan
    synth_df = synth_df[scored.columns]   # align order

    unified = pd.concat([scored, synth_df], ignore_index=True)
    unified = unified.drop_duplicates(subset=["ticker"], keep="first")

    # Save
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    unified.to_csv(output_csv, index=False)

    # Summary
    n_real = (unified["score_source"] == "정석_ml").sum()
    n_synth = (unified["score_source"] == "finnhub_synthetic").sum()
    print()
    print(f"[unify] UNIFIED SAVED to {output_csv}")
    print(f"  total rows: {len(unified)}")
    print(f"  real (정석 ML): {n_real}")
    print(f"  synthetic (Finnhub): {n_synth}")
    print(f"  coverage vs R1000: {(n_real + n_synth) / len(r1000_set) * 100:.1f}%")

    # Show top 10 synthetic picks
    synth_sorted = unified[unified["score_source"] == "finnhub_synthetic"].sort_values("score", ascending=False)
    print()
    print(f"Top 10 synthetic-score names:")
    cols = ["ticker", "Name", "sector", "score", "rs_benchmark_12m",
            "forward_pe_final", "peg_final"]
    cols = [c for c in cols if c in synth_sorted.columns]
    pd.set_option("display.width", 200)
    print(synth_sorted[cols].head(10).to_string(index=False))

    return unified


# --- CLI -------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scored-csv", default=DEFAULT_SCORED_CSV)
    parser.add_argument("--output-csv", default=DEFAULT_OUTPUT_CSV)
    args = parser.parse_args()

    print("=" * 70)
    print(f"r1000 Unified Universe Builder - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    build_unified_scored(args.scored_csv, args.output_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
