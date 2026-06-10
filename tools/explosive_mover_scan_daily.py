#!/usr/bin/env python3
"""explosive_mover_scan_daily - Phase 17 v3 Layer 9 daily scanner.

Reads the latest scored output, ranks fresh candidates by explosion scores,
dedupes against already-alerted tickers, and can post a Telegram digest.
This is a new-alert scanner, not a re-rank of the full universe.

Filters
-------
    explosion_entry_score    >= 0.65
    explosion_net_score      >= 0.40
    explosion_exit_score     <= 0.50
    regime_state             in {bull, strong_bull, neutral}
    mktcap                   >= $300M
    excluded                 not in seen.json within TTL

Usage
-----
    python tools/explosive_mover_scan_daily.py
    python tools/explosive_mover_scan_daily.py --scored cloud_results/scored_latest.csv
    python tools/explosive_mover_scan_daily.py --dry-run
    python tools/explosive_mover_scan_daily.py --top-n 15
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
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "cloud_results" / "explosive_movers"

# Default candidate scored-data files (first existing wins)
DEFAULT_SCORED_CANDIDATES = [
    "outputs/scored_latest.csv",
    "cloud_results/scored_latest.csv",
    "cloud_results/full/scored_latest.csv",
    "cloud_results/quick/scored_latest.csv",
]

# Filter thresholds (tunable)
THR_ENTRY = 0.65
THR_NET = 0.40
THR_EXIT_MAX = 0.50
THR_MCAP_MIN = 300_000_000
SEEN_TTL_HOURS = 24
ALLOWED_REGIMES = {"bull", "strong_bull", "neutral"}  # neutral incl. for early signal
DEFAULT_TOP_N = 10


def find_scored_file(override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.exists() else None
    for rel in DEFAULT_SCORED_CANDIDATES:
        p = REPO_ROOT / rel
        if p.exists():
            return p
    return None


def load_seen(path: Path, ttl_hours: int = SEEN_TTL_HOURS) -> dict[str, str]:
    """Load dedupe state. Returns {ticker: iso_timestamp}.
    Drops entries older than ttl_hours."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    out: dict[str, str] = {}
    for ticker, ts in (raw or {}).items():
        try:
            tdt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if tdt >= cutoff:
                out[str(ticker)] = str(ts)
        except Exception:
            continue
    return out


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
    p.add_argument("--scored", default=None, help="path to scored_latest.csv")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    p.add_argument("--entry-threshold", type=float, default=THR_ENTRY)
    p.add_argument("--net-threshold", type=float, default=THR_NET)
    p.add_argument("--exit-max", type=float, default=THR_EXIT_MAX)
    p.add_argument("--mcap-min", type=float, default=THR_MCAP_MIN)
    p.add_argument("--ttl-hours", type=int, default=SEEN_TTL_HOURS)
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="print preview only; no file write, no telegram")
    p.add_argument("--reset-seen", action="store_true",
                   help="clear dedupe state before scanning")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_path = out_dir / "seen.json"

    if args.reset_seen and seen_path.exists():
        seen_path.unlink()
        print(f"[mover-scan] reset {seen_path}")

    scored_path = find_scored_file(args.scored)
    if scored_path is None:
        print("[mover-scan] ERROR: no scored_latest.csv found", file=sys.stderr)
        for c in DEFAULT_SCORED_CANDIDATES:
            print(f"            tried: {c}", file=sys.stderr)
        print("            run a backtest first or pass --scored", file=sys.stderr)
        return 2

    try:
        import pandas as pd
    except ImportError:
        print("[mover-scan] ERROR: pandas required", file=sys.stderr)
        return 2

    df = pd.read_csv(scored_path)
    print(f"[mover-scan] loaded {len(df)} rows from {scored_path}")

    # Surface columns we need; tolerate missing (set to NaN/0.0)
    for c in ("explosion_entry_score", "explosion_exit_score", "explosion_net_score",
              "regime_state", "mktcap", "ticker", "Name", "sector"):
        if c not in df.columns:
            df[c] = pd.NA if c in ("regime_state", "ticker", "Name", "sector") else 0.0

    # Snapshot key context
    if "explosion_entry_score" not in df.columns or pd.to_numeric(df["explosion_entry_score"], errors="coerce").fillna(0).abs().max() == 0:
        print("[mover-scan] WARN: explosion_* scores are all zero. "
              "L11 models likely not yet trained -- no candidates can fire.")

    # Apply filters
    e = pd.to_numeric(df["explosion_entry_score"], errors="coerce").fillna(0.0)
    x = pd.to_numeric(df["explosion_exit_score"], errors="coerce").fillna(0.0)
    n = pd.to_numeric(df["explosion_net_score"], errors="coerce").fillna(0.0)
    mc = pd.to_numeric(df["mktcap"], errors="coerce").fillna(0.0)
    reg = df["regime_state"].astype(str).str.lower().fillna("neutral")

    mask = (
        (e >= args.entry_threshold)
        & (n >= args.net_threshold)
        & (x <= args.exit_max)
        & (mc >= args.mcap_min)
        & reg.isin({s.lower() for s in ALLOWED_REGIMES})
    )
    candidates = df.loc[mask].copy()
    candidates["explosion_score"] = e.loc[mask] - x.loc[mask]
    candidates = candidates.sort_values("explosion_score", ascending=False)

    print(f"[mover-scan] post-filter: {len(candidates)} candidates")

    # Dedupe against seen
    seen = load_seen(seen_path, ttl_hours=args.ttl_hours)
    fresh = candidates[~candidates["ticker"].astype(str).isin(seen.keys())].head(args.top_n).copy()
    print(f"[mover-scan] after dedupe (seen TTL {args.ttl_hours}h): {len(fresh)} fresh")

    asof = datetime.now(timezone.utc)
    snap = {
        "asof": asof.strftime("%Y-%m-%d %H:%M UTC"),
        "asof_date": asof.strftime("%Y-%m-%d"),
        "scored_source": str(scored_path),
        "thresholds": {
            "entry": args.entry_threshold, "net": args.net_threshold,
            "exit_max": args.exit_max, "mcap_min": args.mcap_min,
        },
        "n_universe": int(len(df)),
        "n_post_filter": int(len(candidates)),
        "n_fresh": int(len(fresh)),
        "fresh_candidates": [
            {
                "ticker": str(r["ticker"]),
                "name": str(r.get("Name", "")),
                "sector": str(r.get("sector", "")),
                "regime_state": str(r.get("regime_state", "")),
                "explosion_entry": float(r["explosion_entry_score"] or 0.0),
                "explosion_exit": float(r["explosion_exit_score"] or 0.0),
                "explosion_net": float(r["explosion_net_score"] or 0.0),
                "explosion_score": float(r["explosion_score"]),
                "mktcap_usd": float(r.get("mktcap") or 0.0),
            }
            for _, r in fresh.iterrows()
        ],
    }

    print()
    print(f"[mover-scan] top {len(fresh)} fresh:")
    for c in snap["fresh_candidates"]:
        print(f"   {c['ticker']:>6} {c['name'][:24]:<24} regime={c['regime_state']:<12} "
              f"entry={c['explosion_entry']:.2f} exit={c['explosion_exit']:.2f} "
              f"score={c['explosion_score']:+.2f}")

    if args.dry_run:
        print("[mover-scan] --dry-run: no file write, no telegram")
        return 0

    # Write scan + latest
    daily_path = out_dir / f"scan_{snap['asof_date']}.json"
    daily_path.write_text(json.dumps(snap, indent=2, default=str))
    (out_dir / "latest.json").write_text(json.dumps(snap, indent=2, default=str))
    print(f"[mover-scan] wrote {daily_path}")

    # Update seen state with newly alerted tickers
    new_seen = dict(seen)
    for c in snap["fresh_candidates"]:
        new_seen[c["ticker"]] = asof.isoformat()
    seen_path.write_text(json.dumps(new_seen, indent=2, default=str))

    # Telegram digest
    if args.telegram and snap["fresh_candidates"]:
        body = [f"[explosive-movers {snap['asof_date']}]",
                f"universe={snap['n_universe']} -> {snap['n_fresh']} fresh"]
        for c in snap["fresh_candidates"]:
            mc_str = f"${c['mktcap_usd']/1e9:.1f}B" if c['mktcap_usd'] >= 1e9 else f"${c['mktcap_usd']/1e6:.0f}M"
            body.append(f"  {c['ticker']:>5} {c['name'][:20]:<20} "
                        f"score={c['explosion_score']:+.2f} ({c['regime_state']}, {mc_str})")
        telegram_send("\n".join(body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
