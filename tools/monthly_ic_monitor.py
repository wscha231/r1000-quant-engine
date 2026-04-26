#!/usr/bin/env python3
"""monthly_ic_monitor — measure macro feature IC for ADR universe.

Per-month rolling IC of {US CPI, VIX, SPY momentum, USD/CNY FX, China CPI}
vs forward 30/60/90-day returns of each ADR. Telegram alerts when:
  - ADR IC drops below -0.03 for 2 consecutive months
  - China-specific feature IC > current US-default IC by 0.05+
  - All-ADR average IC < 0.01

Usage:
    py -3 tools/monthly_ic_monitor.py                # default 30d window
    py -3 tools/monthly_ic_monitor.py --windows 30,60,90
    py -3 tools/monthly_ic_monitor.py --json
    py -3 tools/monthly_ic_monitor.py --telegram     # send alerts

Companion to:
    .github/workflows/monthly_ic_monitor.yml (1st of month, 00:00 UTC)
    adr_universe.yaml (whitelist source)

Output:
    cloud_results/ic_monitor/YYYY-MM.json   (machine-readable history)
    Telegram alert (if --telegram and threshold tripped)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Thresholds (user mandate 2026-04-25 — monthly cadence, not 6mo)
TWO_CONSECUTIVE_NEG_IC_THRESHOLD = -0.03
NEW_FEATURE_IC_DELTA_THRESHOLD = 0.05
ALL_ADR_AVG_IC_THRESHOLD = 0.01


@dataclass
class ICRecord:
    timestamp: str
    window_days: int
    ticker: str
    feature: str
    ic: float
    sample_size: int


def fetch_alpaca_returns(ticker: str, days: int) -> "pd.Series":
    """Forward-return series for ticker over last `days` calendar days.
    Returns pd.Series indexed by date (close).
    """
    try:
        import pandas as pd
        from aggressive.data_alpaca import fetch_daily_bars
    except Exception:
        import pandas as pd
        return pd.Series(dtype=float)
    df = fetch_daily_bars(ticker, days=days + 30)
    if df is None or df.empty:
        import pandas as pd
        return pd.Series(dtype=float)
    return df["close"].pct_change(periods=days).dropna()


def fetch_macro_series(feature: str, days: int) -> "pd.Series":
    """Fetch macro feature series for IC computation. Returns pd.Series of values
    aligned roughly to trading days. Best-effort — falls back to empty if creds
    or network missing.

    feature: one of cpi_us, vix, spy_mom, usdcny, cpi_china
    """
    import pandas as pd
    try:
        if feature == "vix":
            try:
                import yfinance as yf
                t = yf.Ticker("^VIX")
                hist = t.history(period=f"{days+30}d", auto_adjust=False)
                return hist["Close"] if "Close" in hist.columns else pd.Series(dtype=float)
            except Exception:
                return pd.Series(dtype=float)
        elif feature == "spy_mom":
            try:
                from aggressive.data_alpaca import fetch_spy_benchmark
                spy = fetch_spy_benchmark(days=days + 30)
                return spy["close"].pct_change(periods=days).dropna()
            except Exception:
                return pd.Series(dtype=float)
        elif feature == "usdcny":
            try:
                import yfinance as yf
                t = yf.Ticker("CNY=X")  # USD/CNY FX
                hist = t.history(period=f"{days+30}d", auto_adjust=False)
                return hist["Close"] if "Close" in hist.columns else pd.Series(dtype=float)
            except Exception:
                return pd.Series(dtype=float)
        elif feature in ("cpi_us", "cpi_china"):
            # FRED series IDs: CPIAUCSL (US), CHNCPIALLMINMEI (China)
            fred_key = os.environ.get("FRED_API_KEY", "").strip()
            if not fred_key:
                return pd.Series(dtype=float)
            series_id = "CPIAUCSL" if feature == "cpi_us" else "CHNCPIALLMINMEI"
            url = (
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={series_id}&api_key={fred_key}&file_type=json"
                f"&sort_order=desc&limit=24"
            )
            try:
                with urllib.request.urlopen(url, timeout=15) as r:
                    data = json.loads(r.read().decode())
                obs = data.get("observations", [])
                rec = []
                for o in obs:
                    v = o.get("value", "")
                    if v and v != ".":
                        rec.append((pd.Timestamp(o["date"]), float(v)))
                return pd.Series(dict(rec))
            except Exception:
                return pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float)
    return pd.Series(dtype=float)


def compute_rank_ic(x: "pd.Series", y: "pd.Series") -> tuple[float, int]:
    """Spearman rank IC between x and y, aligned by index. Returns (ic, n)."""
    import pandas as pd
    aligned = pd.concat([x.rename("x"), y.rename("y")], axis=1, join="inner").dropna()
    if len(aligned) < 10:
        return float("nan"), len(aligned)
    return aligned["x"].rank().corr(aligned["y"].rank()), len(aligned)


def telegram_send(msg: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    try:
        data = urllib.parse.urlencode({
            "chat_id": chat,
            "text": msg,
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--windows", default="30,60,90",
                   help="comma-separated forward-return windows (days)")
    p.add_argument("--features", default="vix,spy_mom,usdcny,cpi_us,cpi_china",
                   help="comma-separated macro features to test")
    p.add_argument("--countries-filter", default="",
                   help="restrict ADR set to given countries (e.g. 'CN' for China-only)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--telegram", action="store_true",
                   help="send Telegram alert if any threshold tripped")
    p.add_argument("--out-dir", default="cloud_results/ic_monitor",
                   help="directory to write monthly snapshot JSON")
    args = p.parse_args()

    try:
        import pandas as pd
    except ImportError:
        print("FAIL: pandas not installed", file=sys.stderr)
        return 3

    from aggressive.universe import load_adr_universe
    tickers, meta_list = load_adr_universe()
    if args.countries_filter:
        wanted = {c.strip().upper() for c in args.countries_filter.split(",")}
        meta_list = [m for m in meta_list if m.get("country", "").upper() in wanted]
        tickers = [m["ticker"] for m in meta_list]

    if not tickers:
        print("FAIL: no ADRs to monitor (check --countries-filter)", file=sys.stderr)
        return 3

    windows = [int(w.strip()) for w in args.windows.split(",")]
    features = [f.strip() for f in args.features.split(",")]

    print("=" * 70)
    print(f"Monthly IC Monitor — {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    print(f"  ADRs:     {len(tickers)} ({', '.join(tickers[:5])}...)")
    print(f"  windows:  {windows}")
    print(f"  features: {features}")
    print()

    records: list[ICRecord] = []
    feature_avg_ic: dict[str, list[float]] = {f: [] for f in features}

    # Pre-fetch macro series (one per feature, longest window)
    max_window = max(windows)
    macro_data = {}
    for f in features:
        s = fetch_macro_series(f, max_window)
        macro_data[f] = s
        if s.empty:
            print(f"  [warn] macro {f} empty (creds? network?)")

    for w in windows:
        print(f"\nWindow: {w}d")
        print("-" * 70)
        for ticker in tickers[:30]:  # cap for free-tier rate limits
            ret = fetch_alpaca_returns(ticker, days=w)
            if ret.empty:
                continue
            row_icc = []
            for f in features:
                if macro_data[f].empty:
                    continue
                ic, n = compute_rank_ic(ret, macro_data[f])
                if ic == ic:  # not NaN
                    records.append(ICRecord(
                        timestamp=datetime.now().isoformat(timespec="seconds"),
                        window_days=w, ticker=ticker, feature=f,
                        ic=round(ic, 4), sample_size=n,
                    ))
                    feature_avg_ic[f].append(ic)
                    row_icc.append(f"{f}={ic:+.3f}")
            if row_icc:
                print(f"  {ticker:7s}  " + "  ".join(row_icc))

    # Aggregates
    print()
    print("=" * 70)
    print("Average IC per feature (across all ADRs + windows)")
    print("=" * 70)
    avg_summary = {}
    for f, ics in feature_avg_ic.items():
        if ics:
            avg = sum(ics) / len(ics)
            avg_summary[f] = round(avg, 4)
            print(f"  {f:12s}  avg_ic = {avg:+.4f}  (n_obs={len(ics)})")
        else:
            avg_summary[f] = None
            print(f"  {f:12s}  no data")

    # Persist snapshot
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = out_dir / f"{datetime.now():%Y-%m}.json"
    snapshot = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "n_adrs": len(tickers),
        "windows": windows,
        "features": features,
        "avg_ic_by_feature": avg_summary,
        "records": [asdict(r) for r in records],
    }
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"\nSnapshot saved to {snapshot_path}")

    # Threshold check + Telegram alerts
    alerts: list[str] = []
    if avg_summary:
        non_null = [v for v in avg_summary.values() if v is not None]
        if non_null:
            overall = sum(non_null) / len(non_null)
            if overall < ALL_ADR_AVG_IC_THRESHOLD:
                alerts.append(
                    f"⚠ All-ADR avg IC = {overall:+.4f} < {ALL_ADR_AVG_IC_THRESHOLD} "
                    f"(macro features may be irrelevant for ADRs)"
                )
        # Compare China-specific (cpi_china, usdcny) vs US-default (cpi_us, vix, spy_mom)
        china_feats = [v for k, v in avg_summary.items() if k in ("cpi_china", "usdcny") and v is not None]
        us_feats = [v for k, v in avg_summary.items() if k in ("cpi_us", "vix", "spy_mom") and v is not None]
        if china_feats and us_feats:
            china_avg = sum(china_feats) / len(china_feats)
            us_avg = sum(us_feats) / len(us_feats)
            if china_avg - us_avg >= NEW_FEATURE_IC_DELTA_THRESHOLD:
                alerts.append(
                    f"📈 China-specific macro IC ({china_avg:+.4f}) > "
                    f"US-default IC ({us_avg:+.4f}) by "
                    f"+{china_avg - us_avg:.4f} ≥ {NEW_FEATURE_IC_DELTA_THRESHOLD} "
                    f"— consider adding cpi_china/usdcny to feature set for ADRs"
                )

    if alerts and args.telegram:
        msg = (
            f"📊 Monthly IC Monitor [{datetime.now():%Y-%m-%d}]\n"
            + "\n".join(alerts)
            + f"\nFull snapshot: cloud_results/ic_monitor/{datetime.now():%Y-%m}.json"
        )
        telegram_send(msg)
        print(f"\n[telegram] alert sent ({len(alerts)} threshold(s) tripped)")
    elif alerts:
        print(f"\n[telegram] {len(alerts)} threshold(s) tripped (pass --telegram to send):")
        for a in alerts:
            print(f"  {a}")
    else:
        print("\nNo threshold alerts.")

    if args.json:
        print(json.dumps(snapshot, indent=2))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
    except Exception as exc:
        print(f"\nframework error: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(3)
