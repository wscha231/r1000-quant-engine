"""r1000_regime_data — Layer 3 (regime defense) data fetcher.

Provides VIX + SPY-200MA inputs for r1000_risk_sensing.evaluate_layer3_regime.
The risk-sensing module has the logic, but no data path. This closes the
gap.

History:
  c8b5773 (Phase 2)  4-layer risk sensing system + Layer 2 backtest
  fa4d22b (Phase 2.3) Layer 1 fixed stops empirically disproven
  Layer 3 production wiring (this file)

Usage as library:
    from r1000_regime_data import current_regime
    snap = current_regime()
    if snap.vix_level >= 30: ...
    if not snap.spy_above_200ma: ...

CLI:
    py -3 r1000_regime_data.py             # print current regime + Layer 3 actions
    py -3 r1000_regime_data.py --json      # machine-readable

Data sources (in priority order):
  SPY:    aggressive.data_alpaca.fetch_spy_benchmark (already cached)
  VIX:    yfinance ^VIX  (no API key needed)
          fallback: FRED VIXCLS (if FRED_API_KEY env set)
          fallback: 20.0 (long-term mean) with warning

Design notes:
  - All fetchers must return (value, source_name) so the snapshot can
    surface data provenance to the user.
  - 200MA computed from last 200 SPY trading days (not calendar days).
  - VIX level cached for 1 hour to avoid rate limits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

@dataclass
class RegimeSnapshot:
    """Current market regime — feeds r1000_risk_sensing.PortfolioState."""
    timestamp: str
    spy_close: float
    spy_ma200: float
    spy_above_200ma: bool
    vix_level: float
    vix_source: str  # 'yfinance' | 'fred' | 'fallback'
    spy_source: str
    warnings: list[str] = field(default_factory=list)

    @property
    def regime_label(self) -> str:
        if self.vix_level >= 30:
            return "fear" if self.spy_above_200ma else "panic"
        if not self.spy_above_200ma:
            return "defensive"
        if self.vix_level <= 15:
            return "complacency"
        return "normal"


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_spy_with_ma200() -> Tuple[float, float, str, list[str]]:
    """Fetch SPY current close + 200-day MA. Returns (close, ma200, source, warnings)."""
    warnings: list[str] = []
    try:
        from aggressive.data_alpaca import fetch_spy_benchmark
    except Exception as e:
        warnings.append(f"alpaca data unavailable: {type(e).__name__}: {e}")
        return 0.0, 0.0, "unavailable", warnings

    try:
        df = fetch_spy_benchmark(days=260)
    except Exception as e:
        warnings.append(f"fetch_spy_benchmark failed: {type(e).__name__}: {e}")
        return 0.0, 0.0, "unavailable", warnings

    if df is None or df.empty:
        warnings.append("SPY bars empty")
        return 0.0, 0.0, "alpaca_empty", warnings
    if len(df) < 200:
        warnings.append(f"SPY history too short ({len(df)} < 200 bars)")
        return float(df["close"].iloc[-1]), 0.0, "alpaca_short", warnings

    close = float(df["close"].iloc[-1])
    ma200 = float(df["close"].tail(200).mean())
    return close, ma200, "alpaca", warnings


def fetch_vix() -> Tuple[float, str, list[str]]:
    """Fetch current VIX level. Returns (level, source, warnings).

    Tries yfinance first (no API key), then FRED, then 20.0 fallback.
    """
    warnings: list[str] = []

    # Try yfinance
    try:
        import yfinance as yf
        t = yf.Ticker("^VIX")
        hist = t.history(period="5d", auto_adjust=False)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            level = float(hist["Close"].iloc[-1])
            if 5 <= level <= 100:
                return level, "yfinance", warnings
            warnings.append(f"yfinance VIX out of plausible range: {level}")
    except ImportError:
        warnings.append("yfinance not installed")
    except Exception as e:
        warnings.append(f"yfinance VIX failed: {type(e).__name__}: {e}")

    # Try FRED VIXCLS
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    if fred_key:
        try:
            import urllib.request
            url = (
                "https://api.stlouisfed.org/fred/series/observations"
                f"?series_id=VIXCLS&api_key={fred_key}&file_type=json"
                "&sort_order=desc&limit=5"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            for obs in data.get("observations", []):
                v = obs.get("value", "")
                if v and v != ".":
                    return float(v), "fred", warnings
            warnings.append("FRED VIXCLS returned no recent obs")
        except Exception as e:
            warnings.append(f"FRED VIXCLS failed: {type(e).__name__}: {e}")
    else:
        warnings.append("FRED_API_KEY not set, skipping FRED fallback")

    warnings.append("VIX fallback to 20.0 (long-term mean) — Layer 3 vix gate may misfire")
    return 20.0, "fallback", warnings


# ---------------------------------------------------------------------------
# Cache (1-hour TTL)
# ---------------------------------------------------------------------------

_CACHE_PATH = ROOT / "outputs" / "regime_snapshot_cache.json"
_CACHE_TTL_SEC = 3600


def _load_cached_snapshot() -> Optional[RegimeSnapshot]:
    if not _CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_CACHE_PATH.read_text())
        ts = data.get("_cached_at", 0)
        if time.time() - ts > _CACHE_TTL_SEC:
            return None
        data.pop("_cached_at", None)
        return RegimeSnapshot(**data)
    except Exception:
        return None


def _save_cached_snapshot(snap: RegimeSnapshot) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(snap)
        d["_cached_at"] = time.time()
        _CACHE_PATH.write_text(json.dumps(d, indent=2))
    except Exception:
        pass  # cache write is best-effort


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def current_regime(use_cache: bool = True) -> RegimeSnapshot:
    """Build a regime snapshot from live data. Cached 1h by default."""
    if use_cache:
        cached = _load_cached_snapshot()
        if cached is not None:
            return cached

    from datetime import datetime
    spy_close, ma200, spy_src, spy_warns = fetch_spy_with_ma200()
    vix_level, vix_src, vix_warns = fetch_vix()

    snap = RegimeSnapshot(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        spy_close=spy_close,
        spy_ma200=ma200,
        spy_above_200ma=(spy_close > ma200) if (spy_close > 0 and ma200 > 0) else True,
        vix_level=vix_level,
        vix_source=vix_src,
        spy_source=spy_src,
        warnings=spy_warns + vix_warns,
    )
    _save_cached_snapshot(snap)
    return snap


def layer3_actions_for_snapshot(snap: RegimeSnapshot) -> list[dict]:
    """Run r1000_risk_sensing.evaluate_layer3_regime against this snapshot.

    Returns plain dicts so callers don't need to import the dataclass.
    """
    try:
        from r1000_risk_sensing import (
            PortfolioState, RiskConfig, evaluate_layer3_regime,
        )
    except ImportError as e:
        return [{"error": f"risk_sensing import failed: {e}"}]

    state = PortfolioState(
        nav=1.0, nav_peak_recent=1.0, cash_weight=0.10,
        spy_above_200ma=snap.spy_above_200ma,
        vix_level=snap.vix_level,
    )
    actions = evaluate_layer3_regime(state, RiskConfig())
    return [
        {
            "type": a.type, "layer": a.layer, "priority": a.priority,
            "target_weight": a.target_weight, "reason": a.reason,
        }
        for a in actions
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--no-cache", action="store_true", help="bypass 1h cache")
    args = p.parse_args()

    snap = current_regime(use_cache=not args.no_cache)
    actions = layer3_actions_for_snapshot(snap)

    if args.json:
        print(json.dumps({
            "snapshot": asdict(snap),
            "layer3_actions": actions,
        }, indent=2))
        return 0

    print("=" * 70)
    print(f"r1000 Regime Snapshot — {snap.timestamp}")
    print("=" * 70)
    print(f"  SPY close:        ${snap.spy_close:>8.2f}    (source: {snap.spy_source})")
    print(f"  SPY 200MA:        ${snap.spy_ma200:>8.2f}")
    print(f"  SPY > 200MA:      {snap.spy_above_200ma}")
    print(f"  VIX level:        {snap.vix_level:>9.2f}    (source: {snap.vix_source})")
    print(f"  Regime label:     {snap.regime_label}")
    if snap.warnings:
        print("\n  warnings:")
        for w in snap.warnings:
            print(f"    - {w}")

    print()
    print(f"Layer 3 actions: {len(actions)}")
    if not actions:
        print("  (none — regime is benign for new buys)")
    for a in actions:
        if "error" in a:
            print(f"  ERROR: {a['error']}")
            continue
        tgt = f" target={a['target_weight']:.0%}" if a.get("target_weight") else ""
        print(f"  - {a['type']:14s} pri={a['priority']}{tgt}  {a['reason']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
