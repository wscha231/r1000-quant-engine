"""Phase 11 B2: Expand multibagger episodes dataset.

Current (v1): 54 episodes (5x+ in 36m, mcap>=$1B, rev>=$100M).
Target (v2): broader coverage while excluding junk:
  - Threshold: 3x+ (captures more lifecycle examples, still strong winners)
  - Window: 36m unchanged (matches entry horizon)
  - Quality: mcap>=$1B, revenues_ttm>=$100M (keep 잡주 filter strict)
  - Dedup: 1 episode per ticker (best return)

Also: try extended time window (2015-2026 vs 2018-2026) if price cache supports.

Output: research/multibagger_episodes_v2.csv (replaces v1 if validated)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from r1000_helpers import px_cache_name

DRIVE = Path(r"G:\내 드라이브\r1000_top30_institutional")
PRICE_CACHE = DRIVE / "cache_prices"
FEATURE_STORE = DRIVE / "feature_store" / "feature_store_latest.parquet"

OUT_DIR = ROOT / "research"

# v2 params
THRESHOLDS = [3.0, 4.0, 5.0]          # multiple thresholds to see count curve
WINDOW_MONTHS = 36
QUALITY_MIN_MCAP = 1e9
QUALITY_MIN_REV = 1e8
SURGE_BREAKOUT_THRESHOLD = 1.20


def load_monthly_close(ticker: str) -> pd.Series | None:
    fname = px_cache_name(ticker)
    path = PRICE_CACHE / fname
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    if col not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    if s.empty:
        return None
    s.index = pd.to_datetime(s.index)
    monthly = s.resample("ME").last().dropna()
    return monthly


def find_episodes(tickers: list[str], threshold: float) -> pd.DataFrame:
    episodes: list[dict] = []
    for i, ticker in enumerate(tickers):
        if i % 200 == 0:
            print(f"  [{threshold}x] [{i}/{len(tickers)}] episodes so far: {len(episodes)}")
        monthly = load_monthly_close(ticker)
        if monthly is None or len(monthly) < WINDOW_MONTHS:
            continue
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
            if max_return >= threshold:
                surge_mask = window >= (entry_price * SURGE_BREAKOUT_THRESHOLD)
                surge_idx_rel = int(np.argmax(surge_mask)) if surge_mask.any() else 0
                peak_t = t + max_idx_rel
                surge_t = t + surge_idx_rel
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
                t = peak_t + 1
            else:
                t += 1
    return pd.DataFrame(episodes)


def apply_quality_filter(episodes_df: pd.DataFrame, fs: pd.DataFrame) -> pd.DataFrame:
    qual_records = []
    for _, ep in episodes_df.iterrows():
        t = ep["ticker"]
        date = ep["surge_start_date"]
        subset = fs[(fs["ticker"] == t) & (fs["rebalance_date"] <= date)]
        if subset.empty:
            qual_records.append({"mcap": np.nan, "revenues_ttm": np.nan, "match_date": pd.NaT})
        else:
            row = subset.sort_values("rebalance_date").iloc[-1]
            qual_records.append({
                "mcap": float(pd.to_numeric(row.get("mktcap", np.nan), errors="coerce")),
                "revenues_ttm": float(pd.to_numeric(row.get("revenues_ttm", np.nan), errors="coerce")),
                "match_date": row["rebalance_date"],
            })
    qual_df = pd.DataFrame(qual_records)
    out = pd.concat([episodes_df.reset_index(drop=True), qual_df], axis=1)
    out["quality_pass"] = (out["mcap"] >= QUALITY_MIN_MCAP) & (out["revenues_ttm"] >= QUALITY_MIN_REV)
    qualified = out[out["quality_pass"]].copy()
    qualified = qualified.sort_values("max_return", ascending=False).drop_duplicates("ticker", keep="first")
    return qualified


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print("Loading feature_store ...")
fs = pd.read_parquet(FEATURE_STORE)
fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
fs = fs.dropna(subset=["rebalance_date", "ticker"]).reset_index(drop=True)
tickers = sorted(fs["ticker"].unique())
print(f"  {len(tickers)} tickers in universe")

# Survey: try multiple thresholds
print("\n=== Scanning episodes at multiple thresholds ===")
results = {}
for thresh in THRESHOLDS:
    print(f"\nThreshold {thresh}x:")
    raw_df = find_episodes(tickers, threshold=thresh)
    print(f"  Raw episodes: {len(raw_df)}")
    if raw_df.empty:
        continue
    qualified = apply_quality_filter(raw_df, fs)
    results[thresh] = {
        "raw": len(raw_df),
        "qualified": len(qualified),
        "df": qualified,
    }
    print(f"  Quality-passed (mcap>=$1B, rev>=$100M, 1 per ticker): {len(qualified)}")

# Summary
print("\n" + "=" * 70)
print("THRESHOLD SENSITIVITY")
print("=" * 70)
print(f"{'Threshold':>10s} {'Raw':>6s} {'Quality':>8s}")
for t, r in results.items():
    print(f"  {t:>6.1f}x   {r['raw']:>6d}   {r['qualified']:>8d}")

# Pick best threshold: 3x (more training data)
if 3.0 in results:
    best = results[3.0]["df"]
    out_path = OUT_DIR / "multibagger_episodes_v2.csv"
    best.to_csv(out_path, index=False)
    print(f"\nSaved v2 (3x+ threshold): {out_path}")
    print(f"  {len(best)} episodes (was 54 at 5x threshold)")
    print(f"\nTop 15 by max_return:")
    top = best.nlargest(15, "max_return")
    print(top[["ticker", "entry_date", "surge_start_date", "peak_date", "max_return", "mcap"]].to_string(index=False))
    print(f"\nReturn distribution:")
    print(best["max_return"].describe())
    print(f"\nEntry date distribution (quarterly):")
    entry_dates = pd.to_datetime(best["entry_date"])
    print(entry_dates.dt.to_period("Q").value_counts().sort_index().head(30))
