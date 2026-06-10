#!/usr/bin/env python3
"""macro_daily_snapshot - Phase 17 v3 Layer 12 daily macro pulse.

Computes daily changes in macro inputs used by regime_state, including VIX,
SPY trend, SPY 3m return, high-yield OAS, and breadth. It can post a concise
Telegram digest when indicators cross regime boundaries.

Outputs
-------
    cloud_results/macro_daily/snapshot_YYYY-MM-DD.json
    cloud_results/macro_daily/latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "cloud_results" / "macro_daily"

VIX_TICKER = "^VIX"
SPY_TICKER = "SPY"

# Regime thresholds matching r1000_features.compute_regime_state_classifier
THRESHOLDS = {
    "vix_hot": 25.0,             # raw VIX level above this = caution
    "vix_extreme": 35.0,
    "spy_3m_bear": -0.03,
    "spy_3m_deep_bear": -0.10,
    "spy_3m_bull": 0.05,
    "spy_3m_strong_bull": 0.10,
    "ma200_breach_pct": 0.0,     # SPY/MA200 crossing
}


def fetch_yfinance_history(ticker: str, days: int = 260):
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.7))   # buffer for weekends
        df = yf.Ticker(ticker).history(start=start.strftime("%Y-%m-%d"),
                                       end=end.strftime("%Y-%m-%d"),
                                       auto_adjust=True)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def fetch_fred_series(series_id: str, api_key: str | None) -> float | None:
    if not api_key:
        return None
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={api_key}&file_type=json"
        f"&sort_order=desc&limit=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        for obs in data.get("observations", []):
            v = obs.get("value")
            if v not in (".", "", None):
                return float(v)
    except Exception:
        return None
    return None


def compute_snapshot() -> dict:
    snap: dict = {
        "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "asof_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # ---- SPY block
    spy = fetch_yfinance_history(SPY_TICKER)
    if spy is not None and len(spy) > 200:
        close = spy["Close"]
        last = float(close.iloc[-1])
        ma200 = float(close.iloc[-200:].mean())
        spy_ret_3m = float(last / float(close.iloc[-63]) - 1.0) if len(close) > 63 else None
        spy_ret_1m = float(last / float(close.iloc[-21]) - 1.0) if len(close) > 21 else None
        snap["spy_close"] = last
        snap["spy_ma200"] = ma200
        snap["spy_above_ma200"] = bool(last > ma200)
        snap["spy_dist_ma200_pct"] = float(last / ma200 - 1.0)
        snap["spy_ret_1m"] = spy_ret_1m
        snap["spy_ret_3m"] = spy_ret_3m
    else:
        snap["spy_error"] = "no SPY history"

    # ---- VIX block
    vix = fetch_yfinance_history(VIX_TICKER, days=120)
    if vix is not None and len(vix) > 63:
        last_vix = float(vix["Close"].iloc[-1])
        win = vix["Close"].iloc[-63:]
        mu = float(win.mean()); sd = float(win.std(ddof=1))
        snap["vix"] = last_vix
        snap["vix_z_63d"] = float((last_vix - mu) / sd) if sd > 0 else 0.0
    else:
        snap["vix_error"] = "no VIX history"

    # ---- FRED block (HY OAS, DGS10) - optional, only if FRED_API_KEY set
    api = os.getenv("FRED_API_KEY")
    if api:
        snap["hy_oas"] = fetch_fred_series("BAMLH0A0HYM2", api)
        snap["dgs10"] = fetch_fred_series("DGS10", api)
        snap["unrate"] = fetch_fred_series("UNRATE", api)

    # ---- Regime classification (matches L1)
    snap["regime_state"] = classify_regime(snap)
    return snap


def classify_regime(snap: dict) -> str:
    spy_above = bool(snap.get("spy_above_ma200", True))
    spy_3m = float(snap.get("spy_ret_3m") or 0.0)
    vix_z = float(snap.get("vix_z_63d") or 0.0)

    if (not spy_above) and spy_3m < THRESHOLDS["spy_3m_deep_bear"] and vix_z > 2.0:
        return "deep_bear"
    if (not spy_above) or (vix_z > 1.0 and spy_3m < THRESHOLDS["spy_3m_bear"]):
        return "bear"
    if spy_above and vix_z < -0.5 and spy_3m > THRESHOLDS["spy_3m_strong_bull"]:
        return "strong_bull"
    if spy_above and vix_z < 0.0 and spy_3m > THRESHOLDS["spy_3m_bull"]:
        return "bull"
    return "neutral"


def detect_transitions(today: dict, prev: dict | None) -> list[str]:
    if not prev:
        return []
    msgs: list[str] = []
    if today.get("regime_state") != prev.get("regime_state"):
        msgs.append(f"regime: {prev.get('regime_state')} -> {today.get('regime_state')}")
    # MA200 cross
    if (today.get("spy_above_ma200") is not None and
            prev.get("spy_above_ma200") is not None and
            today["spy_above_ma200"] != prev["spy_above_ma200"]):
        side = "above" if today["spy_above_ma200"] else "below"
        msgs.append(f"SPY crossed {side} MA200")
    # VIX spike
    if (today.get("vix") is not None and prev.get("vix") is not None and
            (today["vix"] - prev["vix"]) > 5.0):
        msgs.append(f"VIX +{today['vix'] - prev['vix']:.1f} ({prev['vix']:.1f} -> {today['vix']:.1f})")
    return msgs


def telegram_send(msg: str) -> None:
    tok = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15).read()
    except Exception:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--telegram", action="store_true", help="post Telegram digest")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = compute_snapshot()

    # Compare against latest.json from the previous run
    latest_path = out_dir / "latest.json"
    prev = None
    if latest_path.exists():
        try:
            prev = json.loads(latest_path.read_text())
        except Exception:
            prev = None

    transitions = detect_transitions(snap, prev)
    snap["transitions"] = transitions

    daily_path = out_dir / f"snapshot_{snap['asof_date']}.json"
    daily_path.write_text(json.dumps(snap, indent=2, default=str))
    latest_path.write_text(json.dumps(snap, indent=2, default=str))

    print(f"[macro-daily] regime_state: {snap.get('regime_state')}")
    print(f"[macro-daily] spy_above_ma200: {snap.get('spy_above_ma200')}")
    print(f"[macro-daily] spy_ret_3m: {snap.get('spy_ret_3m')}")
    print(f"[macro-daily] vix: {snap.get('vix')}  vix_z_63d: {snap.get('vix_z_63d')}")
    if transitions:
        print(f"[macro-daily] transitions: {transitions}")
    print(f"[macro-daily] wrote {daily_path}")

    if args.telegram and transitions:
        body = "\n".join([f"[macro-daily {snap['asof_date']}]"] + transitions
                         + [f"regime: {snap.get('regime_state')}",
                            f"VIX: {snap.get('vix')} (z={snap.get('vix_z_63d')})",
                            f"SPY 3m: {snap.get('spy_ret_3m')}"])
        telegram_send(body)

    return 0


if __name__ == "__main__":
    sys.exit(main())
