"""Phase 11 retrospective — find historical 5x+ multibagger episodes + feature profile.

Goal: validate whether current engine features distinguish pre-surge
multibagger candidates from non-winners. Output CSV files for inspection.

Usage:
    py -3 research/phase11_retrospective.py

Outputs:
    research/multibagger_episodes.csv        -- one row per 5x+ episode
    research/feature_profile_winners.csv     -- feature means at surge_start (winners)
    research/feature_profile_losers.csv      -- feature means at same months (non-winners)
    research/feature_separation.csv          -- delta (winner-loser) + t-stat per feature
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_helpers import px_cache_name

# Drive paths
DRIVE = Path(r"G:\내 드라이브\r1000_top30_institutional")
PRICE_CACHE = DRIVE / "cache_prices"
FEATURE_STORE = DRIVE / "feature_store" / "feature_store_latest.parquet"

# Output paths
OUT_DIR = ROOT / "research"
OUT_DIR.mkdir(exist_ok=True)

# Surge detection parameters
WINDOW_MONTHS = 36       # 3-year forward window
MIN_RETURN = 5.0         # 5x = 400% cumulative
QUALITY_MIN_MCAP = 1e9   # $1B market cap at surge start
QUALITY_MIN_REV = 1e8    # $100M revenues_ttm at surge start
SURGE_BREAKOUT_THRESHOLD = 1.20  # price > 1.2x trailing 12m avg = surge_start

# ---------------------------------------------------------------------------
# 1. Load universe of tickers
# ---------------------------------------------------------------------------
print("Loading feature_store to identify tickers + fundamentals ...")
fs = pd.read_parquet(FEATURE_STORE)
print(f"  {len(fs)} rows, {fs['ticker'].nunique()} tickers, "
      f"{fs['rebalance_date'].min().date()} to {fs['rebalance_date'].max().date()}")

tickers = sorted(fs["ticker"].unique())
print(f"  {len(tickers)} unique tickers to scan")


def load_monthly_close(ticker: str) -> pd.Series | None:
    """Return month-end adjusted close series for ticker, or None if missing."""
    fname = px_cache_name(ticker)
    path = PRICE_CACHE / fname
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    if close_col not in df.columns:
        return None
    s = pd.to_numeric(df[close_col], errors="coerce").dropna()
    if s.empty:
        return None
    s.index = pd.to_datetime(s.index)
    # Month-end resample
    monthly = s.resample("ME").last()
    return monthly.dropna()


# ---------------------------------------------------------------------------
# 2. Scan for 5x+ episodes
# ---------------------------------------------------------------------------
print(f"\nScanning {len(tickers)} tickers for {MIN_RETURN}x+ episodes "
      f"in {WINDOW_MONTHS}-month rolling windows ...")

episodes: list[dict] = []
missing_prices = 0
total_scanned = 0

for i, ticker in enumerate(tickers):
    if i % 100 == 0:
        print(f"  [{i}/{len(tickers)}] scanned={total_scanned} episodes={len(episodes)}")
    monthly = load_monthly_close(ticker)
    if monthly is None or len(monthly) < WINDOW_MONTHS:
        missing_prices += 1
        continue
    total_scanned += 1

    # Rolling max return: for each t, what's the max (future_price/today_price) in next 36 months?
    vals = monthly.values
    dates = monthly.index
    t = 0
    while t < len(vals) - WINDOW_MONTHS:
        entry_price = vals[t]
        if entry_price <= 0:
            t += 1
            continue
        window_end = min(t + WINDOW_MONTHS, len(vals))
        window = vals[t:window_end]
        max_idx_rel = int(np.argmax(window))
        peak_price = window[max_idx_rel]
        max_return = peak_price / entry_price
        if max_return >= MIN_RETURN:
            # Found an episode. Find surge_start = first month where price > 1.2x entry
            surge_mask = window >= (entry_price * SURGE_BREAKOUT_THRESHOLD)
            surge_idx_rel = int(np.argmax(surge_mask)) if surge_mask.any() else 0
            # peak_date
            peak_t = t + max_idx_rel
            surge_t = t + surge_idx_rel
            # decline_start: first month after peak with -10% drawdown from peak, or end of window
            decline_t = None
            if peak_t < len(vals) - 1:
                post_peak = vals[peak_t:]
                dd_mask = post_peak <= (peak_price * 0.90)
                if dd_mask.any():
                    decline_t = peak_t + int(np.argmax(dd_mask))
            episodes.append({
                "ticker": ticker,
                "entry_date": dates[t],
                "entry_price": float(entry_price),
                "surge_start_date": dates[surge_t],
                "surge_start_price": float(vals[surge_t]),
                "peak_date": dates[peak_t],
                "peak_price": float(peak_price),
                "decline_start_date": dates[decline_t] if decline_t else pd.NaT,
                "max_return": float(max_return),
                "months_to_peak": int(max_idx_rel),
            })
            # Skip to after peak so we don't double-count the same run-up
            t = peak_t + 1
        else:
            t += 1

print(f"\nScan complete. {total_scanned} tickers scanned, {missing_prices} missing prices.")
print(f"Found {len(episodes)} raw 5x+ episodes (pre-quality-filter).")

ep_df = pd.DataFrame(episodes)
if ep_df.empty:
    print("No episodes found. Exiting.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 3. Apply quality filter at surge_start (from feature_store)
# ---------------------------------------------------------------------------
print("\nApplying quality filter at surge_start (mcap > $1B, revenues_ttm > $100M) ...")

fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
fs_key = fs.set_index(["ticker", "rebalance_date"])

# For each episode, find the closest feature_store row at/before surge_start_date
def lookup_fundamentals(ticker: str, date: pd.Timestamp) -> dict:
    subset = fs[(fs["ticker"] == ticker) & (fs["rebalance_date"] <= date)]
    if subset.empty:
        return {"mcap": np.nan, "revenues_ttm": np.nan, "match_date": pd.NaT}
    row = subset.sort_values("rebalance_date").iloc[-1]
    return {
        "mcap": float(pd.to_numeric(row.get("mktcap", np.nan), errors="coerce")),
        "revenues_ttm": float(pd.to_numeric(row.get("revenues_ttm", np.nan), errors="coerce")),
        "match_date": row["rebalance_date"],
    }


qual_records = []
for _, ep in ep_df.iterrows():
    q = lookup_fundamentals(ep["ticker"], ep["surge_start_date"])
    qual_records.append(q)

qual_df = pd.DataFrame(qual_records)
ep_df = pd.concat([ep_df.reset_index(drop=True), qual_df], axis=1)

# Filter
pre = len(ep_df)
ep_df["quality_pass"] = (
    (ep_df["mcap"] >= QUALITY_MIN_MCAP)
    & (ep_df["revenues_ttm"] >= QUALITY_MIN_REV)
)
qualified = ep_df[ep_df["quality_pass"]].copy()
print(f"  {pre} raw -> {len(qualified)} quality-passed episodes.")

# Dedupe: one episode per ticker (keep highest max_return)
qualified = qualified.sort_values("max_return", ascending=False).drop_duplicates("ticker", keep="first")
print(f"  {len(qualified)} unique tickers after dedup (one best episode per ticker).")

qualified.to_csv(OUT_DIR / "multibagger_episodes.csv", index=False)
print(f"  Saved: {OUT_DIR / 'multibagger_episodes.csv'}")

# ---------------------------------------------------------------------------
# 4. Feature profile at surge_start — winners vs losers
# ---------------------------------------------------------------------------
print("\nBuilding feature profiles at surge_start ...")

# For each winner episode, get the feature_store row at surge_start
def lookup_features(ticker: str, date: pd.Timestamp) -> pd.Series | None:
    subset = fs[(fs["ticker"] == ticker) & (fs["rebalance_date"] <= date)]
    if subset.empty:
        return None
    return subset.sort_values("rebalance_date").iloc[-1]


winner_rows = []
winner_keys = set()  # (ticker, date) tuples to exclude from loser pool
for _, ep in qualified.iterrows():
    row = lookup_features(ep["ticker"], ep["surge_start_date"])
    if row is not None:
        winner_rows.append(row)
        winner_keys.add((ep["ticker"], row["rebalance_date"]))

winners = pd.DataFrame(winner_rows)
print(f"  Winner feature rows: {len(winners)}")

# Losers: randomly sample feature_store rows from same surge_start_date periods
# (so market regime matching is controlled)
loser_pool = fs[~fs.set_index(["ticker", "rebalance_date"]).index.isin(winner_keys)]
# Pick rows from each winner's surge_start_date to balance by period
loser_rows = []
for _, ep in qualified.iterrows():
    surge_date = ep["surge_start_date"]
    # Get feature_store rows at same month (any ticker except the winner's)
    month_pool = loser_pool[
        (loser_pool["rebalance_date"].dt.year == surge_date.year)
        & (loser_pool["rebalance_date"].dt.month == surge_date.month)
    ]
    if len(month_pool) > 10:
        # Sample ~5 losers per winner for statistical power
        sample = month_pool.sample(n=min(5, len(month_pool)), random_state=42)
        loser_rows.append(sample)

losers = pd.concat(loser_rows, ignore_index=True) if loser_rows else pd.DataFrame()
print(f"  Loser feature rows (matched period): {len(losers)}")

# ---------------------------------------------------------------------------
# 5. Feature separation analysis
# ---------------------------------------------------------------------------
print("\nComputing feature separation (winner vs loser) ...")

# Select numeric features that we think might matter for multibagger detection
KEY_FEATURES = [
    "mktcap",
    "revenues_ttm", "op_income_ttm", "net_income_ttm", "ocf_ttm",
    "sales_cagr_1y", "sales_cagr_3y", "sales_cagr_5y",
    "op_income_cagr_1y", "op_income_cagr_3y",
    "op_margin_ttm", "roe_proxy", "gp_to_assets_ttm",
    "fund_history_quarters_available",
    "rs_industry_12m", "rs_industry_group_12m", "rs_benchmark_12m",
    "oneil_leadership_score", "industry_group_strength_score",
    "mom_3m", "mom_6m", "mom_12m", "near_52w_high_pct",
    "breakout_volume_z", "vol_63d_annualized",
    "forward_pe_final", "ev_to_ebitda_final", "fcfy_ttm", "peg_ratio_final",
    "ni_sign_flip_pos", "ocf_sign_flip_pos", "fcf_sign_flip_pos",
    "any_profit_sign_flip_pos", "any_profitability_turn_positive_4q",
    "fundamental_turnaround_acceleration_score",
    "cashflow_inflection_under_loss_score",
    "value_inflection_score",
    "uptrend_continuation_score",
]

# Keep only features present in both frames
avail = [f for f in KEY_FEATURES if f in winners.columns and f in losers.columns]
print(f"  {len(avail)} of {len(KEY_FEATURES)} KEY_FEATURES available in data")

rows = []
for feat in avail:
    w = pd.to_numeric(winners[feat], errors="coerce").dropna()
    l = pd.to_numeric(losers[feat], errors="coerce").dropna()
    if len(w) < 5 or len(l) < 5:
        continue
    # Simple t-stat (not assuming normality, but ok for ranking purposes)
    mean_w = w.mean()
    mean_l = l.mean()
    std_pool = np.sqrt(((len(w)-1)*w.var() + (len(l)-1)*l.var()) / (len(w)+len(l)-2))
    if std_pool == 0 or np.isnan(std_pool):
        continue
    tstat = (mean_w - mean_l) / (std_pool * np.sqrt(1/len(w) + 1/len(l)))
    rows.append({
        "feature": feat,
        "winner_mean": mean_w,
        "winner_median": w.median(),
        "winner_n": len(w),
        "loser_mean": mean_l,
        "loser_median": l.median(),
        "loser_n": len(l),
        "delta_mean": mean_w - mean_l,
        "delta_pct": (mean_w - mean_l) / abs(mean_l) if mean_l != 0 else np.nan,
        "t_stat": tstat,
        "abs_t": abs(tstat),
    })

sep = pd.DataFrame(rows).sort_values("abs_t", ascending=False)
sep.to_csv(OUT_DIR / "feature_separation.csv", index=False)
print(f"  Saved: {OUT_DIR / 'feature_separation.csv'}")

# ---------------------------------------------------------------------------
# 6. Summary printout
# ---------------------------------------------------------------------------
print("\n" + "=" * 78)
print("RETROSPECTIVE SUMMARY")
print("=" * 78)
print(f"\nEpisodes: {len(qualified)} unique tickers with 5x+ in 36-month window")
print(f"Top 10 multibaggers by max_return:")
top = qualified.sort_values("max_return", ascending=False).head(10)
print(top[["ticker", "entry_date", "surge_start_date", "peak_date", "max_return", "mcap"]].to_string(index=False))

print(f"\nTop 15 features by |t-stat| (winner vs loser separation at surge_start):")
print(sep.head(15)[["feature", "winner_mean", "loser_mean", "delta_pct", "t_stat"]].to_string(index=False))

print(f"\nFeatures with |t-stat| > 3 (highly predictive):")
strong = sep[sep["abs_t"] > 3]
print(f"  {len(strong)} features")
if not strong.empty:
    print(strong[["feature", "winner_mean", "loser_mean", "delta_pct", "t_stat"]].to_string(index=False))

print("\n" + "=" * 78)
print("Next step: review feature_separation.csv + multibagger_episodes.csv")
print("=" * 78)
