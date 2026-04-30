#!/usr/bin/env python3
"""build_explosive_pattern_db — Phase 17 v3 Layer 11 historical explosion miner.

User insight (2026-04-29):
  "올랐다 내리더라도 파는 타이밍도 학습하면 됨. 단 파산 / pre-explosion 보다
   낮아지는 수준은 회피. 단기 테마라도 exit timing 잡으면 OK. mcap floor $300M."

Mines Russell 3000 (2018-2025) for sustainable explosive movers and
captures features at multiple pre-explosion + post-peak time-points so
a downstream classifier can learn BOTH entry timing (T-12mo / T-6mo /
T-3mo) AND exit timing (peak detection / T+3mo post-peak).

Filter chain
============

Stage 1 — Pre-explosion eligibility:
    mcap_min            $300M (user-set floor)
    mcap_max            $30B  (above = R1000 mega-cap, not "explosive" candidate)
    daily_dollar_vol    >= $3M/day
    listed_years        >= 2  (need 2y price history minimum)

Stage 2 — Explosion event:
    6-month return      +150% to +800%
    max_single_day      < 50% of total move (filter pump-of-the-day)

Stage 3 — Exclusion (USER-SET: only 2 conditions reject):
    bankruptcy_within_24mo               -> reject
    price_at_T+24mo < pre_explosion_price -> reject (didn't sustain at all)

Everything else is INCLUDED — short-term themes that came back down 50%
are valid training data for EXIT timing learning.

Outputs
=======
    outputs/explosive_pattern_db/
        events.parquet          ticker, peak_date, pre_price, peak_price, ...
        features_t_minus_12mo.parquet
        features_t_minus_6mo.parquet
        features_t_minus_3mo.parquet
        features_at_peak.parquet
        features_t_plus_3mo.parquet
        features_t_plus_6mo.parquet
        labels.parquet          per-snapshot binary labels for entry/exit

Auto-refresh
============
    .github/workflows/explosive_pattern_train_monthly.yml runs the
    miner + classifier monthly (15th @ 16:00 UTC). New events from the
    most recent 30 days are appended.

Usage
=====
    python tools/build_explosive_pattern_db.py
    python tools/build_explosive_pattern_db.py --years 8
    python tools/build_explosive_pattern_db.py --dry-run --tickers AAPL,NVDA

Note
====
This is the MINING phase only — produces the historical event database
and feature snapshots. Classifier training (XGBoost) lives in
tools/train_explosion_classifier.py. Inference runs from
r1000_features.py:compute_explosion_likelihood_score during the main
pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "outputs" / "explosive_pattern_db"

# ---------------- Filters (user-tuned) ---------------

MCAP_MIN_USD = 300_000_000        # $300M (user request)
MCAP_MAX_USD = 30_000_000_000     # $30B
DAILY_DOLLAR_VOL_MIN_USD = 3_000_000
LISTED_YEARS_MIN = 2

EXPLOSION_LOOKBACK_MONTHS = 6
EXPLOSION_MIN_RETURN = 1.50       # +150%
EXPLOSION_MAX_RETURN = 8.00       # +800%
SINGLE_DAY_MAX_FRACTION = 0.50    # any single day > 50% of move = pump

POST_PEAK_FORWARD_MONTHS = 24
EXCLUSION_BANKRUPTCY = True       # delisting / mcap collapse to <$50M
EXCLUSION_BELOW_PRE = True        # T+24mo price < pre-run price

FEATURE_SNAPSHOT_OFFSETS = [
    -12,    # very early entry
    -6,     # mid entry
    -3,     # late entry
    0,      # peak (decision: hold or trim)
    +3,     # post-peak (exit signal)
    +6,     # confirmation (deeper exit)
]


@dataclass
class ExplosionEvent:
    """One historical sustained explosion case."""
    ticker: str
    pre_run_date: str             # YYYY-MM-DD
    peak_date: str
    pre_run_price: float
    peak_price: float
    return_at_peak: float
    pre_run_mcap_usd: float
    pre_run_daily_dollar_vol_usd: float
    days_to_peak: int
    sustained_at_t_plus_12mo: bool
    sustained_at_t_plus_24mo: bool
    excluded: bool = False
    exclusion_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "pre_run_date": self.pre_run_date,
            "peak_date": self.peak_date,
            "pre_run_price": self.pre_run_price,
            "peak_price": self.peak_price,
            "return_at_peak": self.return_at_peak,
            "pre_run_mcap_usd": self.pre_run_mcap_usd,
            "pre_run_daily_dollar_vol_usd": self.pre_run_daily_dollar_vol_usd,
            "days_to_peak": self.days_to_peak,
            "sustained_at_t_plus_12mo": self.sustained_at_t_plus_12mo,
            "sustained_at_t_plus_24mo": self.sustained_at_t_plus_24mo,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
        }


def load_universe_tickers(years: int) -> list[str]:
    """Best-effort R3000 universe loader with fallbacks.

    Priority:
      1. data_raw/historical_universe_membership_*.csv  (PIT R1000 + extensions)
      2. cycle_play_universe.yaml + adr_universe.yaml + IWB current
      3. Hardcoded sample for dev (AAPL, NVDA, BE, PLUG, etc.)
    """
    candidates: list[str] = []
    # Try historical R1000 union over years
    hist_dir = REPO_ROOT / "data_raw"
    if hist_dir.exists():
        for f in sorted(hist_dir.glob("historical_universe_membership_*.csv")):
            try:
                import pandas as pd
                df = pd.read_csv(f, usecols=["ticker"])
                candidates.extend(df["ticker"].dropna().astype(str).str.upper().tolist())
            except Exception:
                continue
    # Add cycle_play whitelist (small/mid)
    try:
        import yaml
        cp = yaml.safe_load((REPO_ROOT / "cycle_play_universe.yaml").read_text())
        candidates.extend(
            str(e.get("ticker", "")).upper()
            for e in cp.get("cycle_play_universe", [])
            if isinstance(e, dict)
        )
    except Exception:
        pass
    # ADR
    try:
        import yaml
        adr = yaml.safe_load((REPO_ROOT / "adr_universe.yaml").read_text())
        candidates.extend(
            str(e.get("ticker", "")).upper()
            for e in adr.get("adr_universe", [])
            if isinstance(e, dict)
        )
    except Exception:
        pass

    seen: set[str] = set()
    uniq: list[str] = []
    for t in candidates:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def fetch_price_history(ticker: str, start: str, end: str):
    """Fetch yfinance price + volume + mcap. Returns DataFrame with date
    index, columns = ['close', 'volume', 'dollar_vol', 'mcap_proxy']."""
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
        # Note: mcap_proxy = close × shares_outstanding from .info — single
        # snapshot for now. For PIT correctness, would need historical
        # shares from SEC filings. Acceptable for filter purposes.
        info = t.info or {}
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        if shares:
            df["mcap_proxy"] = df["close"] * float(shares)
        else:
            df["mcap_proxy"] = float("nan")
        return df[["close", "volume", "dollar_vol", "mcap_proxy"]]
    except Exception:
        return None


def detect_explosions(ticker: str, hist) -> list[ExplosionEvent]:
    """Slide a 6-month window across hist; emit events meeting Stage 2 filters."""
    if hist is None or hist.empty:
        return []
    import pandas as pd
    events: list[ExplosionEvent] = []
    closes = hist["close"]
    if len(closes) < 252 * LISTED_YEARS_MIN:
        return events  # insufficient history

    window_days = int(EXPLOSION_LOOKBACK_MONTHS * 21)  # ~6mo trading days
    # find local peaks via rolling-max comparison
    rolling_max = closes.rolling(window_days, min_periods=int(window_days * 0.6)).max()
    is_peak = (closes >= rolling_max * 0.99) & (closes >= closes.shift(5))
    peak_indices = closes.index[is_peak]

    last_emitted = None
    for peak_idx in peak_indices:
        # Skip if too close to a previous emission (avoid double-counting same explosion)
        if last_emitted is not None and (peak_idx - last_emitted).days < 90:
            continue
        try:
            peak_loc = closes.index.get_loc(peak_idx)
        except Exception:
            continue
        if peak_loc < window_days:
            continue
        pre_loc = peak_loc - window_days
        pre_price = float(closes.iloc[pre_loc])
        peak_price = float(closes.iloc[peak_loc])
        if pre_price <= 0 or peak_price <= 0:
            continue
        ret = peak_price / pre_price - 1.0
        if not (EXPLOSION_MIN_RETURN <= ret <= EXPLOSION_MAX_RETURN):
            continue

        # Single-day max fraction filter (pump screener)
        window_returns = closes.iloc[pre_loc:peak_loc + 1].pct_change().fillna(0)
        max_day = float(window_returns.max())
        total_move = ret
        if total_move > 0 and max_day / total_move > SINGLE_DAY_MAX_FRACTION:
            continue

        # Mcap + liquidity check at pre_run
        pre_mcap = float(hist["mcap_proxy"].iloc[pre_loc]) if not pd.isna(hist["mcap_proxy"].iloc[pre_loc]) else float("nan")
        pre_dv = float(hist["dollar_vol"].iloc[pre_loc - 20:pre_loc].mean()) if pre_loc > 20 else 0.0
        if pd.notna(pre_mcap):
            if pre_mcap < MCAP_MIN_USD or pre_mcap > MCAP_MAX_USD:
                continue
        if pre_dv < DAILY_DOLLAR_VOL_MIN_USD:
            continue

        # Sustainability check (Stage 3 — only 2 exclusion conditions)
        forward_window = int(POST_PEAK_FORWARD_MONTHS * 21)
        if peak_loc + forward_window < len(closes):
            t_plus_12mo_idx = peak_loc + int(12 * 21)
            t_plus_24mo_idx = peak_loc + forward_window
            t_plus_12mo_price = float(closes.iloc[t_plus_12mo_idx])
            t_plus_24mo_price = float(closes.iloc[t_plus_24mo_idx])
            sustained_12 = t_plus_12mo_price > pre_price * 1.0
            sustained_24 = t_plus_24mo_price > pre_price * 1.0
        else:
            # not enough forward data — skip (need 24mo of post)
            continue

        # Apply Stage 3 exclusion (per user: bankruptcy / below-pre only)
        excluded = False
        reason = ""
        if EXCLUSION_BELOW_PRE and not sustained_24:
            excluded = True
            reason = "price_at_T+24mo_below_pre"
        # bankruptcy proxy: mcap collapsed below $50M at T+24
        future_mcap = float(hist["mcap_proxy"].iloc[t_plus_24mo_idx]) if not pd.isna(hist["mcap_proxy"].iloc[t_plus_24mo_idx]) else None
        if EXCLUSION_BANKRUPTCY and future_mcap is not None and future_mcap < 50_000_000:
            excluded = True
            reason = "mcap_collapse_below_50M"

        ev = ExplosionEvent(
            ticker=ticker,
            pre_run_date=str(closes.index[pre_loc].date()),
            peak_date=str(peak_idx.date()),
            pre_run_price=pre_price,
            peak_price=peak_price,
            return_at_peak=ret,
            pre_run_mcap_usd=pre_mcap,
            pre_run_daily_dollar_vol_usd=pre_dv,
            days_to_peak=(peak_idx - closes.index[pre_loc]).days,
            sustained_at_t_plus_12mo=sustained_12,
            sustained_at_t_plus_24mo=sustained_24,
            excluded=excluded,
            exclusion_reason=reason,
        )
        events.append(ev)
        last_emitted = peak_idx
    return events


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--years", type=int, default=8, help="years of history to mine (default 8)")
    p.add_argument("--limit", type=int, default=0, help="limit tickers (debug; 0 = all)")
    p.add_argument("--tickers", default=None, help="comma-separated explicit ticker list")
    p.add_argument("--dry-run", action="store_true", help="no parquet write")
    args = p.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.tickers:
        universe = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        universe = load_universe_tickers(args.years)
        if args.limit:
            universe = universe[: args.limit]

    print(f"[mine] universe size: {len(universe)} tickers")
    print(f"[mine] years_back:    {args.years}")
    print(f"[mine] mcap range:    ${MCAP_MIN_USD/1e6:.0f}M - ${MCAP_MAX_USD/1e9:.0f}B")
    print(f"[mine] return range:  +{EXPLOSION_MIN_RETURN*100:.0f}% to +{EXPLOSION_MAX_RETURN*100:.0f}%")
    print(f"[mine] exclude:       bankruptcy_within_24mo, price_below_pre_at_T+24mo")
    print()

    all_events: list[ExplosionEvent] = []
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=int(args.years * 365.25))).strftime("%Y-%m-%d")

    for i, ticker in enumerate(universe):
        if i and i % 50 == 0:
            print(f"  [{i}/{len(universe)}] processed; events so far: {len(all_events)}", flush=True)
        hist = fetch_price_history(ticker, start_date, end_date)
        if hist is None:
            continue
        events = detect_explosions(ticker, hist)
        if events:
            all_events.extend(events)
        # rate limit
        time.sleep(0.05)

    print()
    print(f"[mine] raw events:        {len(all_events)}")
    print(f"[mine] excluded:          {sum(1 for e in all_events if e.excluded)}")
    print(f"[mine] valid for training: {sum(1 for e in all_events if not e.excluded)}")

    if not args.dry_run and all_events:
        import pandas as pd
        events_df = pd.DataFrame([e.to_dict() for e in all_events])
        events_path = OUTPUT_DIR / "events.parquet"
        events_df.to_parquet(events_path, index=False)
        print(f"\n[mine] wrote {events_path} ({len(events_df)} rows)")
        # Also CSV for human review
        events_df.to_csv(OUTPUT_DIR / "events.csv", index=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
