"""r1000_valuations - Live-price-based valuation recompute (Strategy A).

User mandate (2026-04-24):
  "주가는 미래를 예측하는거다. 과거의 데이터들은 과거의 영광일 뿐이다.
   비율이나 가격 등은 현재가격으로 업데이트하고 재평가하자."

Every engine run recomputes price-dependent ratios using yesterday's close.
Fundamentals (quarterly, slow) stay cached. Prices (daily, fast) are fresh.

Also integrates Finnhub data when available:
  - aggressive/state/finnhub/r1000_features.parquet provides
    PE TTM, EPS growth 5y, analyst consensus, insider MSPR, earnings calendar.
  - If Finnhub data is fresher/more complete than SEC companyfacts, prefer it.

Design:
  Input  df (monthly panel) has: ticker, current_price_live, shares_outstanding,
                                   eps_ttm, revenues_ttm, net_income_ttm,
                                   book_value (total_equity), total_debt, cash
  Output df same + recomputed columns:
    market_cap_live, pe_ttm_live, forward_pe_live, peg_live,
    ev_live, ev_ebitda_live, book_to_market_live
  Override: forward_pe_final, peg_final (replaced with live-recomputed)

Integration point (r1000_pipeline.py build_universe_monthly):
  After merge_live_fundamentals, before sleeve scoring:
      monthly = compute_live_valuations(monthly, finnhub_df=fh_df)
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# Growth rate sanity bounds (user: "over-cyclical bias 방지")
GROWTH_FLOOR_PCT = 5.0    # below 5% treated as 5% (slow but stable names)
GROWTH_CEILING_PCT = 30.0  # above 30% treated as 30% (boom is unsustainable)
PEG_CEILING = 10.0         # clip at 10 for display sanity


# --- Helper: blended growth rate ------------------------------------------

def _blended_growth_pct(
    eps_g_5y_pct: float,
    eps_g_q_yoy_pct: float,
    eps_g_3y_pct: float,
    sales_g_3y_pct: float,
) -> float:
    """Median of up to 4 growth estimates with sanity clipping.

    Each input is percentage (e.g. 12.5 for 12.5% growth).
    NaN inputs are skipped.
    Result is clipped to [GROWTH_FLOOR, GROWTH_CEILING].
    """
    rates: list[float] = []
    for g in (eps_g_5y_pct, eps_g_q_yoy_pct, eps_g_3y_pct, sales_g_3y_pct):
        if g is None or pd.isna(g):
            continue
        try:
            g = float(g)
        except Exception:
            continue
        # Some sources give as decimal (0.125) instead of percentage (12.5)
        if abs(g) < 1.5:  # heuristic: treat as decimal
            g = g * 100.0
        # Clip to sanity range
        g = max(GROWTH_FLOOR_PCT, min(GROWTH_CEILING_PCT, g))
        rates.append(g)
    if not rates:
        return GROWTH_FLOOR_PCT
    return float(np.median(rates))


# --- Main recompute function ----------------------------------------------

def compute_live_valuations(
    df: pd.DataFrame,
    finnhub_df: Optional[pd.DataFrame] = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """Recompute all price-dependent valuation ratios.

    df columns expected (from pipeline):
      ticker, current_price_live, shares_outstanding
      eps_ttm  (or  net_income_ttm + shares)
      revenues_ttm, net_income_ttm
      book_value_ttm  (or total_equity, stockholders_equity)
      total_debt, cash_equivalents
      ebitda_ttm
      net_income_cagr_3y, net_income_cagr_5y, sales_cagr_3y

    finnhub_df columns (optional merge):
      ticker, fh_peExclExtraTTM, fh_epsGrowth5Y, fh_epsGrowthQuarterlyYoy,
      fh_revenueGrowthQuarterlyYoy, fh_peg_5y, fh_peg_quarterly,
      fh_mspr_latest, fh_mspr_3m_avg,
      fh_insider_cluster_30d_score, fh_insider_n_buyers_30d,
      fh_rec_bull_ratio, fh_rec_bear_ratio, fh_rec_buy_delta_mom,
      fh_days_to_next_earnings, fh_past_beat_rate
    """
    if df is None or df.empty:
        return df

    d = df.copy()

    # ---- Left-join Finnhub --------------------------------------------------
    if finnhub_df is not None and not finnhub_df.empty:
        fh = finnhub_df.copy()
        if "ticker" in fh.columns:
            fh["ticker"] = fh["ticker"].astype(str).str.upper().str.strip()
            d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
            # Only keep fh_ prefixed columns to avoid collisions
            keep_cols = ["ticker"] + [c for c in fh.columns if c.startswith("fh_")]
            fh = fh[keep_cols].drop_duplicates(subset=["ticker"])
            d = d.merge(fh, on="ticker", how="left")
            if verbose:
                print(f"[valuations] merged Finnhub: "
                      f"{len([c for c in d.columns if c.startswith('fh_')])} fh_ cols")

    # ---- Helper to get numeric series ---------------------------------------
    def num(col: str) -> pd.Series:
        if col not in d.columns:
            return pd.Series(np.nan, index=d.index, dtype=float)
        return pd.to_numeric(d[col], errors="coerce").astype(float)

    # ---- Live price (required) ---------------------------------------------
    price = num("current_price_live")
    if price.isna().all():
        # Fallback chain
        for alt in ("current_price", "close", "price"):
            alt_s = num(alt)
            if alt_s.notna().any():
                price = alt_s
                break
    if price.isna().all():
        if verbose:
            print("[valuations] no live price available; returning df unchanged")
        return d

    # ---- Shares outstanding -------------------------------------------------
    shares = num("shares_outstanding")
    if shares.isna().all():
        # Derive from market_cap_live / price (if mcap already exists)
        mcap_existing = num("market_cap_live")
        shares = mcap_existing / price.replace(0, np.nan)

    # ---- EPS TTM ------------------------------------------------------------
    eps_ttm = num("eps_ttm")
    if eps_ttm.isna().all():
        net_income = num("net_income_ttm")
        eps_ttm = net_income / shares.replace(0, np.nan)

    # =========================================================================
    # Live recompute
    # =========================================================================

    # Market cap
    mcap_live = price * shares
    d["market_cap_live"] = mcap_live

    # PE TTM live
    pe_ttm_live = price / eps_ttm.where(eps_ttm > 0)
    d["pe_ttm_live"] = pe_ttm_live

    # Forward PE: prefer Finnhub fh_peExclExtra_ttm (collector's key naming)
    # Fallback chain: fh_peExclExtra_ttm -> fh_peNormalized -> pe_ttm_live
    pe_fh = num("fh_peExclExtra_ttm") if "fh_peExclExtra_ttm" in d.columns else pd.Series(np.nan, index=d.index)
    pe_fh_norm = num("fh_peNormalized") if "fh_peNormalized" in d.columns else pd.Series(np.nan, index=d.index)
    forward_pe_live = pe_fh.where(pe_fh > 0)
    forward_pe_live = forward_pe_live.fillna(pe_fh_norm.where(pe_fh_norm > 0))
    # Only use computed pe_ttm_live if it looks reasonable (market_cap not clipped)
    mcap_capped = mcap_live >= 9.9e11    # 1T cap hit -> shares derivation unreliable
    safe_pe_ttm = pe_ttm_live.where(~mcap_capped)
    forward_pe_live = forward_pe_live.fillna(safe_pe_ttm)
    d["forward_pe_live"] = forward_pe_live

    # ---- Blended growth rate for PEG ----------------------------------------
    # Prefer Finnhub sources (fresher). Fallback to SEC CAGRs.
    fh_eps_5y = num("fh_epsGrowth5Y")
    fh_eps_3y = num("fh_epsGrowth3Y")
    fh_eps_q = num("fh_epsGrowthQuarterlyYoy")
    fh_rev_q = num("fh_revenueGrowthQuarterlyYoy")
    sec_ni_3y = num("net_income_cagr_3y") * 100.0
    sec_ni_5y = num("net_income_cagr_5y") * 100.0
    sec_sales_3y = num("sales_cagr_3y") * 100.0

    def row_blended(r):
        # Prefer Finnhub (fresher); fallback to SEC CAGRs
        return _blended_growth_pct(
            r.get("_eps5"), r.get("_epsq"), r.get("_eps3"), r.get("_revq"),
        )
    tmp = pd.DataFrame({
        "_eps5": fh_eps_5y.fillna(sec_ni_5y),
        "_epsq": fh_eps_q.fillna(sec_ni_3y),
        "_eps3": fh_eps_3y.fillna(sec_ni_3y),
        "_revq": fh_rev_q.fillna(sec_sales_3y),
    })
    blended = tmp.apply(row_blended, axis=1)
    d["earnings_growth_blended_pct"] = blended

    # PEG live: prefer Finnhub pre-computed peg_5y when available
    fh_peg_5y = num("fh_peg_5y") if "fh_peg_5y" in d.columns else pd.Series(np.nan, index=d.index)
    peg_live = fh_peg_5y.where(fh_peg_5y > 0)
    peg_live = peg_live.fillna(forward_pe_live / blended.replace(0, np.nan))
    # Sanity clip
    peg_live = peg_live.clip(upper=PEG_CEILING)
    d["peg_live"] = peg_live

    # EV / EBITDA live
    debt = num("total_debt").fillna(0.0)
    cash = num("cash_equivalents").fillna(0.0)
    if "total_debt" not in d.columns:
        debt = num("long_term_debt").fillna(0.0) + num("short_term_debt").fillna(0.0)
    ev_live = mcap_live + debt - cash
    d["ev_live"] = ev_live
    ebitda = num("ebitda_ttm")
    if ebitda.isna().all():
        ebitda = num("op_income_ttm")  # fallback
    ev_ebitda_live = ev_live / ebitda.where(ebitda > 0)
    d["ev_ebitda_live"] = ev_ebitda_live

    # Book-to-market
    book_value = num("book_value_ttm")
    if book_value.isna().all():
        book_value = num("total_equity")
    if book_value.isna().all():
        book_value = num("stockholders_equity")
    d["book_to_market_live"] = book_value / mcap_live.where(mcap_live > 0)

    # ---- Override legacy cached columns ------------------------------------
    # These columns are used by sleeve scoring -> make sure they use live values
    d["forward_pe_final"] = d["forward_pe_live"].fillna(num("forward_pe_final"))
    d["peg_final"] = d["peg_live"].fillna(num("peg_final"))
    # ev_to_ebitda_final if computed
    if "ev_to_ebitda_final" in d.columns:
        d["ev_to_ebitda_final"] = d["ev_ebitda_live"].fillna(num("ev_to_ebitda_final"))

    # ---- Sector-relative valuation gates -----------------------------------
    if "sector" in d.columns:
        for col in ("forward_pe_live", "peg_live", "ev_ebitda_live"):
            # Use sector median excluding extreme outliers
            grp = d.groupby("sector")[col]
            sector_med = grp.transform(
                lambda s: s[(s > 0) & (s < 200)].median()
            )
            rel_col = col.replace("_live", "_vs_sector_median")
            d[rel_col] = d[col] / sector_med.replace(0, np.nan)

    # ---- Valuation gate multiplier (Layer 4) -------------------------------
    val_mult = pd.Series(1.0, index=d.index, dtype=float)

    peg_vs_sec = num("peg_vs_sector_median") if "peg_vs_sector_median" in d.columns else pd.Series(np.nan, index=d.index)
    pe_vs_sec = num("forward_pe_vs_sector_median") if "forward_pe_vs_sector_median" in d.columns else pd.Series(np.nan, index=d.index)

    # PEG more than 2.5x sector median AND growth < 10% = absurd overvaluation
    growth_weak = blended < 10.0
    peg_extreme = peg_vs_sec > 2.5
    val_mult = val_mult.where(~(peg_extreme & growth_weak), val_mult * 0.5)

    # Forward PE more than 2.5x sector median
    pe_extreme = pe_vs_sec > 2.5
    val_mult = val_mult.where(~pe_extreme, val_mult * 0.80)

    d["val_mult"] = val_mult

    # ---- Summary fields for debugging --------------------------------------
    d["valuations_recomputed_at"] = datetime.utcnow().isoformat()

    if verbose:
        summary = {
            "market_cap_live": d["market_cap_live"].notna().sum(),
            "forward_pe_live": d["forward_pe_live"].notna().sum(),
            "peg_live": d["peg_live"].notna().sum(),
            "val_mult < 1": (d["val_mult"] < 1.0).sum(),
            "val_mult == 0.4": (d["val_mult"] <= 0.4 + 0.01).sum(),
        }
        print(f"[valuations] computed: {summary}")

    return d


# --- Finnhub loader --------------------------------------------------------

def load_finnhub_features(
    state_dir: Optional[Path] = None,
    max_age_hours: float = 72.0,
) -> pd.DataFrame:
    """Load consolidated Finnhub features parquet if present and fresh."""
    if state_dir is None:
        state_dir = Path(__file__).parent / "aggressive" / "state" / "finnhub"
    fpath = state_dir / "r1000_features.parquet"
    if not fpath.exists():
        # Try CSV fallback
        csv_fpath = state_dir / "r1000_features.csv"
        if csv_fpath.exists():
            try:
                return pd.read_csv(csv_fpath)
            except Exception:
                return pd.DataFrame()
        return pd.DataFrame()
    import time
    age_hours = (time.time() - fpath.stat().st_mtime) / 3600
    if age_hours > max_age_hours:
        print(f"[valuations] WARNING: Finnhub data is {age_hours:.1f}h old")
    try:
        return pd.read_parquet(fpath)
    except Exception as e:
        print(f"[valuations] parquet read failed: {e}")
        return pd.DataFrame()


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    # Load portfolio_latest.csv + Finnhub features, recompute
    import sys
    from pathlib import Path

    # Try gdrive output first
    gdrive_out = Path(r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv")
    if gdrive_out.exists():
        df = pd.read_csv(gdrive_out)
        print(f"[smoke] loaded {len(df)} portfolio stocks from gdrive")
    else:
        print("[smoke] no portfolio_latest.csv found; can't test")
        sys.exit(1)

    fh = load_finnhub_features()
    print(f"[smoke] Finnhub features: {len(fh)} tickers, {len(fh.columns)} cols")

    result = compute_live_valuations(df, finnhub_df=fh, verbose=True)

    # Show diff for AAPL
    comp_cols = [
        "ticker", "forward_pe_final", "forward_pe_live", "peg_final", "peg_live",
        "earnings_growth_blended_pct", "val_mult",
    ]
    comp_cols = [c for c in comp_cols if c in result.columns]
    print()
    print("Before/After recompute (select columns):")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    # Show the full portfolio
    show = result[comp_cols].head(20)
    print(show.to_string(index=False))
