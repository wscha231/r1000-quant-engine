#!/usr/bin/env python3
"""etf_leadership_snapshot — Phase 17 v3 Layer 8 (2026-04-30) ETF leadership tracker.

User insight (2026-04-29):
  "intel/qcom 등 반도체 주식들이 급등중이다. 시장 주도 섹터를 파악하기 위해
   ETF들도 참고하는게 어때. ETF 수익률들과 안에 내용물도. 섹터 분산 강요할
   필요 없음."

Captures the trailing 1m / 3m / 6m return of major sector + theme ETFs
and ranks them. The leader_state output feeds:
  * adaptive sector cap (relax when sector ETF is leading)
  * concentrated picker bias (boost stocks inside leading ETFs)
  * monthly Telegram digest

Tracked ETFs
============
    Sector S&P SPDRs:
        XLK (tech), XLF (financials), XLE (energy), XLV (health),
        XLY (cons disc), XLI (industrials), XLB (materials),
        XLP (cons staples), XLU (utilities), XLRE (real estate),
        XLC (communication services)
    Themes:
        SOXX (semis), XBI (biotech), ARKK (innovation),
        ICLN (clean energy), KWEB (china internet), TAN (solar),
        XME (mining), XOP (oil & gas E&P), XHB (homebuilders),
        IBB (big biotech)

Output
======
    cloud_results/etf_leadership/snapshot_YYYY-MM-DD.json
    cloud_results/etf_leadership/latest.json
    cloud_results/etf_leadership/leaderboard_30d.csv

Usage
=====
    python tools/etf_leadership_snapshot.py
    python tools/etf_leadership_snapshot.py --telegram
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "cloud_results" / "etf_leadership"

# Tickers to track + their human-readable theme labels
SECTOR_ETFS = {
    "XLK": "tech",
    "XLF": "financials",
    "XLE": "energy",
    "XLV": "health_care",
    "XLY": "consumer_discretionary",
    "XLI": "industrials",
    "XLB": "materials",
    "XLP": "consumer_staples",
    "XLU": "utilities",
    "XLRE": "real_estate",
    "XLC": "communication_services",
}

THEME_ETFS = {
    "SOXX": "semiconductors",
    "XBI": "biotech_small",
    "IBB": "biotech_large",
    "ARKK": "innovation",
    "ICLN": "clean_energy",
    "KWEB": "china_internet",
    "TAN": "solar",
    "XME": "mining",
    "XOP": "oil_gas_ep",
    "XHB": "homebuilders",
}

ALL_ETFS = {**SECTOR_ETFS, **THEME_ETFS}

# Leader state thresholds (trailing 1m return)
LEADER_HOT_RET_1M = 0.08      # > 8% in 1mo = leader
LEADER_WARM_RET_1M = 0.04     # > 4% = warm
LEADER_COLD_RET_1M = -0.04    # < -4% = lagging
LEADER_BEAR_RET_1M = -0.08    # < -8% = capitulating


def fetch_etf_history(ticker: str, days: int = 260):
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.7))
        df = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
        if df.empty:
            return None
        return df
    except Exception:
        return None


def compute_etf_metrics(ticker: str, label: str) -> dict | None:
    df = fetch_etf_history(ticker)
    if df is None or len(df) < 130:
        return None
    close = df["Close"]
    last = float(close.iloc[-1])
    rec = {
        "ticker": ticker,
        "label": label,
        "close": last,
    }
    for window_days, name in ((21, "ret_1m"), (63, "ret_3m"), (126, "ret_6m")):
        if len(close) > window_days:
            base = float(close.iloc[-window_days - 1])
            rec[name] = float(last / base - 1.0) if base > 0 else None
        else:
            rec[name] = None
    # Vs SPY relative strength (approximate -- use cached SPY if available)
    return rec


def classify_state(ret_1m: float | None) -> str:
    if ret_1m is None:
        return "unknown"
    if ret_1m >= LEADER_HOT_RET_1M:
        return "hot"
    if ret_1m >= LEADER_WARM_RET_1M:
        return "warm"
    if ret_1m <= LEADER_BEAR_RET_1M:
        return "capitulating"
    if ret_1m <= LEADER_COLD_RET_1M:
        return "lagging"
    return "neutral"


def build_snapshot() -> dict:
    asof = datetime.now(timezone.utc)
    snap = {
        "asof": asof.strftime("%Y-%m-%d %H:%M UTC"),
        "asof_date": asof.strftime("%Y-%m-%d"),
        "etfs": {},
        "leaders_1m": [],
        "laggards_1m": [],
        "sector_states": {},
    }

    metrics: list[dict] = []
    for ticker, label in ALL_ETFS.items():
        m = compute_etf_metrics(ticker, label)
        if m is None:
            continue
        m["state_1m"] = classify_state(m.get("ret_1m"))
        metrics.append(m)
        snap["etfs"][ticker] = m

    # Rank leaders / laggards by 1m return
    valid_1m = [m for m in metrics if m.get("ret_1m") is not None]
    valid_1m.sort(key=lambda m: m["ret_1m"], reverse=True)
    snap["leaders_1m"] = [
        {"ticker": m["ticker"], "label": m["label"], "ret_1m": m["ret_1m"], "state": m["state_1m"]}
        for m in valid_1m[:5]
    ]
    snap["laggards_1m"] = [
        {"ticker": m["ticker"], "label": m["label"], "ret_1m": m["ret_1m"], "state": m["state_1m"]}
        for m in valid_1m[-5:]
    ]
    # Sector-only state map (used by adaptive sleeve cap downstream)
    snap["sector_states"] = {
        SECTOR_ETFS[m["ticker"]]: m["state_1m"]
        for m in metrics
        if m["ticker"] in SECTOR_ETFS
    }

    return snap


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
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = build_snapshot()

    daily_path = out_dir / f"snapshot_{snap['asof_date']}.json"
    daily_path.write_text(json.dumps(snap, indent=2, default=str))
    (out_dir / "latest.json").write_text(json.dumps(snap, indent=2, default=str))

    # CSV leaderboard for human review
    try:
        import pandas as pd
        rows = list(snap["etfs"].values())
        if rows:
            df = pd.DataFrame(rows)[["ticker", "label", "close", "ret_1m", "ret_3m", "ret_6m", "state_1m"]]
            df = df.sort_values("ret_1m", ascending=False, na_position="last")
            df.to_csv(out_dir / "leaderboard_30d.csv", index=False)
    except ImportError:
        pass

    print(f"[etf-leader] {len(snap['etfs'])} ETFs scored")
    print(f"[etf-leader] top leaders 1m:")
    for l in snap["leaders_1m"]:
        ret = l.get("ret_1m")
        print(f"             {l['ticker']:>5}  {l['label']:<25}  {ret:+.2%}  ({l['state']})")
    print(f"[etf-leader] sector states: {snap['sector_states']}")
    print(f"[etf-leader] wrote {daily_path}")

    if args.telegram and snap["leaders_1m"]:
        body = [f"[etf-leadership {snap['asof_date']}]", "Top 5 leaders (1m):"]
        for l in snap["leaders_1m"]:
            ret = l.get("ret_1m") or 0
            body.append(f"  {l['ticker']:>5} {l['label']:<22} {ret:+.2%}")
        body.append("Bottom 5 (1m):")
        for l in snap["laggards_1m"]:
            ret = l.get("ret_1m") or 0
            body.append(f"  {l['ticker']:>5} {l['label']:<22} {ret:+.2%}")
        telegram_send("\n".join(body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
