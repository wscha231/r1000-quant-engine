"""Finnhub API client with rate limiter + parquet cache.

Free tier: 60 calls/min, no commercial use.
API key via env FINNHUB_API_KEY (loaded from aggressive/.env).

Endpoints used (all Finnhub Free):
  /stock/metric                    - PE/PEG/growth ratios
  /stock/recommendation            - analyst buy/hold/sell counts
  /stock/insider-transactions      - Form 4 raw trades
  /stock/insider-sentiment         - MSPR (Monthly Share Purchase Ratio)
  /calendar/earnings               - upcoming earnings dates
  /stock/earnings                  - past earnings surprises
  /stock/peers                     - sector peer list
  /quote                           - current quote (15min delayed)
  /company-news                    - news headlines

Caching strategy (differential TTL):
  metric              : 7 days (quarterly data, rarely changes)
  recommendations     : 7 days (analyst changes slow)
  insider_transactions: 1 day  (new Form 4 filings throughout month)
  insider_sentiment   : 1 day  (monthly but fresh)
  earnings_calendar   : 1 day  (new estimates)
  earnings_surprises  : 30 days (only during earnings season)
  peers               : 30 days (static)

Design principles:
  - Zero hardcoded tickers
  - Graceful degradation: 404 / rate-limit / network errors logged, return empty
  - Cache path: aggressive/cache/finnhub/{endpoint}/{ticker}_{YYYYMMDD}.parquet
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import requests

from aggressive.agg_config import load_agg_config


FINNHUB_BASE = "https://finnhub.io/api/v1"
RATE_LIMIT_CALLS_PER_MIN = 60
RATE_LIMIT_WINDOW_SEC = 60.0


# --- Rate limiter -----------------------------------------------------------

class RateLimiter:
    """Sliding window rate limiter. Blocks until capacity available."""
    def __init__(self, max_calls: int = RATE_LIMIT_CALLS_PER_MIN,
                 window_sec: float = RATE_LIMIT_WINDOW_SEC):
        self.max_calls = max_calls
        self.window_sec = window_sec
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        now = time.monotonic()
        # Drop calls outside window
        while self._calls and (now - self._calls[0]) > self.window_sec:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.window_sec - (now - self._calls[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            # recurse to re-check
            return self.acquire()
        self._calls.append(now)


# --- Client -----------------------------------------------------------------

@dataclass
class FinnhubFetchResult:
    ok: bool
    status: int
    data: Any = None
    error: str = ""
    from_cache: bool = False


class FinnhubClient:
    """Rate-limited, cached Finnhub client."""

    # TTL in hours per endpoint
    CACHE_TTL_HOURS = {
        "stock_metric":              24 * 7,
        "stock_recommendation":      24 * 7,
        "stock_insider_transactions": 24,
        "stock_insider_sentiment":   24,
        "calendar_earnings":         24,
        "stock_earnings":            24 * 30,
        "stock_peers":               24 * 30,
        "quote":                     1,      # 1h (15min-delayed anyway)
        "company_news":              6,
    }

    def __init__(self, api_key: Optional[str] = None,
                 cache_root: Optional[Path] = None):
        self.api_key = api_key or os.environ.get("FINNHUB_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError(
                "FINNHUB_API_KEY not set. Add to aggressive/.env"
            )
        cfg = load_agg_config()
        self.cache_root = cache_root or (cfg.cache_dir / "finnhub")
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.rate_limiter = RateLimiter()
        self.session = requests.Session()

    # --- Cache helpers -----------------------------------------------------

    def _cache_path(self, endpoint: str, ticker: str) -> Path:
        endpoint_slug = endpoint.strip("/").replace("/", "_")
        sub = self.cache_root / endpoint_slug
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{ticker.upper()}.json"

    def _is_cache_fresh(self, path: Path, endpoint: str) -> bool:
        if not path.exists():
            return False
        slug = endpoint.strip("/").replace("/", "_")
        ttl_hours = self.CACHE_TTL_HOURS.get(slug, 24)
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        return age_hours < ttl_hours

    def _read_cache(self, path: Path) -> Optional[Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, path: Path, data: Any) -> None:
        try:
            path.write_text(json.dumps(data, default=str), encoding="utf-8")
        except Exception as e:
            print(f"[finnhub] cache write failed: {path.name}: {e}")

    # --- Core fetch --------------------------------------------------------

    def _fetch(self, endpoint: str, cache_key: str,
               force_refresh: bool = False,
               **params) -> FinnhubFetchResult:
        """Low-level fetch with rate limit + cache."""
        cache_path = self._cache_path(endpoint, cache_key)

        if not force_refresh and self._is_cache_fresh(cache_path, endpoint):
            cached = self._read_cache(cache_path)
            if cached is not None:
                return FinnhubFetchResult(ok=True, status=200, data=cached,
                                          from_cache=True)

        self.rate_limiter.acquire()
        params["token"] = self.api_key
        try:
            resp = self.session.get(
                f"{FINNHUB_BASE}{endpoint}", params=params, timeout=10,
            )
        except Exception as e:
            return FinnhubFetchResult(ok=False, status=0,
                                      error=f"network: {e}")

        if resp.status_code == 429:
            # Rate limited - back off and retry once
            time.sleep(5.0)
            self.rate_limiter.acquire()
            try:
                resp = self.session.get(
                    f"{FINNHUB_BASE}{endpoint}", params=params, timeout=10,
                )
            except Exception as e:
                return FinnhubFetchResult(ok=False, status=0,
                                          error=f"retry network: {e}")

        if resp.status_code != 200:
            return FinnhubFetchResult(
                ok=False, status=resp.status_code,
                error=resp.text[:200],
            )

        try:
            data = resp.json()
        except Exception as e:
            return FinnhubFetchResult(ok=False, status=resp.status_code,
                                      error=f"json decode: {e}")

        # Cache successful response
        self._write_cache(cache_path, data)
        return FinnhubFetchResult(ok=True, status=200, data=data,
                                  from_cache=False)

    # --- Public endpoints ---------------------------------------------------

    def metric(self, ticker: str, force_refresh: bool = False) -> dict:
        """Returns flat metric dict. Most useful keys:
            peBasicExclExtraTTM, peExclExtraTTM, peNormalizedAnnual
            epsGrowth5Y, epsGrowthQuarterlyYoy, epsGrowth3Y
            revenueGrowthQuarterlyYoy, revenueGrowth5Y
            roeTTM, roaeTTM, netMarginTTM, grossMarginTTM
            currentRatioAnnual, totalDebt/totalEquityAnnual
            beta, 52WeekHigh, 52WeekLow
            dividendYieldIndicatedAnnual
        """
        r = self._fetch("/stock/metric", ticker, force_refresh=force_refresh,
                        symbol=ticker, metric="all")
        if not r.ok:
            return {"_error": r.error, "_status": r.status}
        return (r.data or {}).get("metric", {}) or {}

    def recommendations(self, ticker: str,
                        force_refresh: bool = False) -> list[dict]:
        """Returns list of monthly analyst rec snapshots (most recent first)."""
        r = self._fetch("/stock/recommendation", ticker,
                        force_refresh=force_refresh, symbol=ticker)
        if not r.ok:
            return []
        return r.data or []

    def insider_transactions(self, ticker: str, days: int = 90,
                             force_refresh: bool = False) -> list[dict]:
        """Returns list of Form 4 raw transactions. Fields:
            name, transactionDate, transactionCode, change (shares),
            transactionPrice, share, position
        Codes: P=purchase, S=sale, M=option exercise, F=tax, A=award
        """
        to_date = datetime.utcnow().strftime("%Y-%m-%d")
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = self._fetch("/stock/insider-transactions", ticker,
                        force_refresh=force_refresh,
                        symbol=ticker, **{"from": from_date, "to": to_date})
        if not r.ok:
            return []
        return (r.data or {}).get("data", []) or []

    def insider_sentiment(self, ticker: str, months: int = 12,
                          force_refresh: bool = False) -> list[dict]:
        """Returns monthly MSPR (Monthly Share Purchase Ratio) entries.
            Fields: year, month, change (shares), mspr
            MSPR range: -100 to +100; higher = more insider buying
        """
        to_date = datetime.utcnow().strftime("%Y-%m-%d")
        from_date = (datetime.utcnow() - timedelta(days=months * 31)
                     ).strftime("%Y-%m-%d")
        r = self._fetch("/stock/insider-sentiment", ticker,
                        force_refresh=force_refresh,
                        symbol=ticker, **{"from": from_date, "to": to_date})
        if not r.ok:
            return []
        return (r.data or {}).get("data", []) or []

    def earnings_calendar_for_ticker(self, ticker: str, days_ahead: int = 90,
                                     force_refresh: bool = False) -> list[dict]:
        """Upcoming earnings dates for one ticker."""
        from_date = datetime.utcnow().strftime("%Y-%m-%d")
        to_date = (datetime.utcnow() + timedelta(days=days_ahead)
                   ).strftime("%Y-%m-%d")
        r = self._fetch("/calendar/earnings", ticker,
                        force_refresh=force_refresh,
                        symbol=ticker, **{"from": from_date, "to": to_date})
        if not r.ok:
            return []
        return (r.data or {}).get("earningsCalendar", []) or []

    def earnings_surprises(self, ticker: str,
                           force_refresh: bool = False) -> list[dict]:
        """Past quarterly earnings beats/misses."""
        r = self._fetch("/stock/earnings", ticker,
                        force_refresh=force_refresh, symbol=ticker)
        if not r.ok:
            return []
        return r.data or []

    def peers(self, ticker: str, force_refresh: bool = False) -> list[str]:
        """Peer tickers."""
        r = self._fetch("/stock/peers", ticker,
                        force_refresh=force_refresh, symbol=ticker)
        if not r.ok:
            return []
        return r.data or []

    def quote(self, ticker: str, force_refresh: bool = True) -> dict:
        """Current quote. Fields: c (close), d (delta), dp (% delta),
        h (high), l (low), o (open), pc (prev close), t (timestamp)"""
        r = self._fetch("/quote", ticker, force_refresh=force_refresh,
                        symbol=ticker)
        if not r.ok:
            return {}
        return r.data or {}

    def company_news(self, ticker: str, days: int = 7,
                     force_refresh: bool = False) -> list[dict]:
        from_date = (datetime.utcnow() - timedelta(days=days)
                     ).strftime("%Y-%m-%d")
        to_date = datetime.utcnow().strftime("%Y-%m-%d")
        r = self._fetch("/company-news", ticker,
                        force_refresh=force_refresh,
                        symbol=ticker, **{"from": from_date, "to": to_date})
        if not r.ok:
            return []
        return r.data or []


# --- Derived signal helpers ------------------------------------------------

def compute_insider_cluster_score(
    transactions: list[dict], days: int = 30,
    min_value_usd: float = 10_000.0,
) -> dict:
    """From raw Form 4 data, compute insider buying cluster features.

    Returns:
      n_buyers_recent:   unique insiders who bought in window
      n_buys_recent:     total buy transactions in window
      total_value_usd:   total $ bought
      net_shares:        net shares bought (P - S)
      cluster_score:     0-100, higher = more bullish cluster
    """
    from datetime import datetime as dt
    cutoff = (dt.utcnow() - timedelta(days=days)).date()
    buyers = set()
    n_buys = 0
    total_val = 0.0
    net_shares = 0.0
    n_sales = 0

    for t in transactions:
        try:
            tx_date_str = str(t.get("transactionDate", ""))
            if not tx_date_str:
                continue
            tx_date = pd.to_datetime(tx_date_str).date()
            if tx_date < cutoff:
                continue
            code = str(t.get("transactionCode", ""))
            shares = float(t.get("change") or 0.0)
            price = float(t.get("transactionPrice") or 0.0)
            name = str(t.get("name", "")).strip()
            val = abs(shares) * price
            if code == "P" and val >= min_value_usd:    # real purchase
                n_buys += 1
                buyers.add(name)
                total_val += val
                net_shares += shares
            elif code == "S" and val >= min_value_usd:  # sale
                n_sales += 1
                net_shares += shares   # already negative
        except Exception:
            continue

    # Score: logistic based on n_buyers + total value
    score = 0.0
    if len(buyers) >= 1:
        score = min(100.0, 20.0 * len(buyers) + total_val / 1e5)
    return {
        "n_buyers_recent": len(buyers),
        "n_buys_recent": n_buys,
        "n_sales_recent": n_sales,
        "total_value_usd": total_val,
        "net_shares": net_shares,
        "cluster_score": score,
    }


def compute_mspr_latest(sentiment: list[dict]) -> dict:
    """Most recent insider MSPR + 3-month average."""
    if not sentiment:
        return {"mspr_latest": None, "mspr_3m_avg": None,
                "mspr_latest_period": None}
    # Sort by (year, month) desc
    sorted_s = sorted(sentiment,
                      key=lambda d: (int(d.get("year", 0)),
                                     int(d.get("month", 0))), reverse=True)
    latest = sorted_s[0]
    last3 = sorted_s[:3]
    avg3 = sum(float(d.get("mspr") or 0.0) for d in last3) / max(len(last3), 1)
    return {
        "mspr_latest": float(latest.get("mspr") or 0.0),
        "mspr_3m_avg": avg3,
        "mspr_latest_period": f"{latest.get('year')}-{latest.get('month'):02d}",
    }


def compute_recommendation_trend(recs: list[dict]) -> dict:
    """Analyst recommendation trend (latest + MoM change)."""
    if not recs:
        return {}
    # Sort by period desc
    sr = sorted(recs, key=lambda d: str(d.get("period", "")), reverse=True)
    cur = sr[0]
    tot = (int(cur.get("strongBuy") or 0) + int(cur.get("buy") or 0) +
           int(cur.get("hold") or 0) + int(cur.get("sell") or 0) +
           int(cur.get("strongSell") or 0))
    bull_ratio = ((int(cur.get("strongBuy") or 0) +
                   int(cur.get("buy") or 0)) / tot) if tot else 0.0
    bear_ratio = ((int(cur.get("sell") or 0) +
                   int(cur.get("strongSell") or 0)) / tot) if tot else 0.0

    delta_buy = 0
    if len(sr) >= 2:
        prev = sr[1]
        delta_buy = ((int(cur.get("strongBuy") or 0) + int(cur.get("buy") or 0)) -
                     (int(prev.get("strongBuy") or 0) + int(prev.get("buy") or 0)))

    return {
        "analyst_total": tot,
        "analyst_bull_ratio": bull_ratio,
        "analyst_bear_ratio": bear_ratio,
        "analyst_buy_delta_mom": delta_buy,
        "analyst_latest_period": str(cur.get("period", "")),
    }


def compute_earnings_event_features(
    calendar: list[dict],
    surprises: list[dict],
) -> dict:
    """Days to next earnings + past beat rate."""
    out: dict = {
        "days_to_next_earnings": None,
        "next_earnings_date": None,
        "next_earnings_hour": None,  # 'amc' | 'bmo'
        "past_beat_rate": None,
        "past_avg_surprise_pct": None,
    }
    # Next earnings
    if calendar:
        for c in calendar:
            dstr = c.get("date")
            if not dstr:
                continue
            try:
                dt_next = pd.to_datetime(dstr).date()
                days = (dt_next - datetime.utcnow().date()).days
                if days >= 0:
                    out["days_to_next_earnings"] = days
                    out["next_earnings_date"] = str(dt_next)
                    out["next_earnings_hour"] = c.get("hour", "")
                    break
            except Exception:
                continue
    # Past beats
    if surprises:
        recent = surprises[:4]
        beats = sum(1 for s in recent
                    if float(s.get("surprisePercent") or 0.0) > 0)
        avg = sum(float(s.get("surprisePercent") or 0.0)
                  for s in recent) / max(len(recent), 1)
        out["past_beat_rate"] = beats / len(recent) if recent else None
        out["past_avg_surprise_pct"] = avg
    return out


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    c = FinnhubClient()
    t = "AAPL"
    print("=" * 70)
    print(f"Finnhub Client Smoke Test [{t}]")
    print("=" * 70)

    # Metric
    m = c.metric(t)
    print(f"\n[metric] {len(m)} keys; PE-TTM={m.get('peExclExtraTTM')}, "
          f"EPS-growth-5Y={m.get('epsGrowth5Y')}")
    if m.get('peExclExtraTTM') and m.get('epsGrowth5Y'):
        peg = float(m['peExclExtraTTM']) / float(m['epsGrowth5Y'])
        print(f"  -> computed PEG (5y): {peg:.2f}")

    # Recommendations
    recs = c.recommendations(t)
    rec_feat = compute_recommendation_trend(recs)
    print(f"\n[recommendations] {len(recs)} periods")
    print(f"  -> {rec_feat}")

    # Insider transactions
    txs = c.insider_transactions(t, days=90)
    cluster = compute_insider_cluster_score(txs, days=30)
    print(f"\n[insider_transactions] {len(txs)} raw txs in 90d")
    print(f"  -> cluster (30d): {cluster}")

    # Insider sentiment
    sent = c.insider_sentiment(t, months=6)
    mspr = compute_mspr_latest(sent)
    print(f"\n[insider_sentiment] {len(sent)} months")
    print(f"  -> {mspr}")

    # Earnings
    cal = c.earnings_calendar_for_ticker(t, days_ahead=90)
    surp = c.earnings_surprises(t)
    earn_feat = compute_earnings_event_features(cal, surp)
    print(f"\n[earnings] next_in_calendar={len(cal)}, past_surprises={len(surp)}")
    print(f"  -> {earn_feat}")

    print("\nPASS")
