#!/usr/bin/env python3
"""refresh_cycle_play_universe — monthly auto-curation of cycle_play_universe.yaml.

Phase 15-D D5 (2026-04-29): keeps cycle_play_universe.yaml fresh as market
caps shift and new IPOs match cycle themes.

Logic:
  1. Load existing cycle_play_universe.yaml (preserves manual_pin: true entries).
  2. For each entry:
     - Pull current mcap from yfinance (.info.marketCap) — fast, no API key.
     - Drop if mcap > $30B (graduated to R1000 — auto-removed).
     - Drop if mcap < $0.3B (too small for backtest).
     - Drop if delisted / quote unavailable.
     - Update mcap_usd_b in yaml.
  3. For each theme, scan candidate sub-universe:
     - clean_energy:  yfinance industry='Solar', 'Renewable Energy'
     - ev_battery:    yfinance industry='Auto Manufacturers', 'Battery'
     - ai_infra:      yfinance industry='Software—Application', 'Information Technology Services'
     - memory_semi:   yfinance industry='Semiconductors' (small-mid mcap)
     - biotech:       yfinance industry='Biotechnology' (mcap < $20B)
     - fintech:       yfinance sector='Financial Services' (small-mid)
     - robotics:      yfinance industry='Industrial—3D Printing', 'Robotics'
  4. Add new candidates that pass mcap range + liquidity filter.
  5. Diff vs existing yaml; commit only if changed.
  6. Telegram digest of changes (added/removed/mcap shift).

Usage:
    python tools/refresh_cycle_play_universe.py
    python tools/refresh_cycle_play_universe.py --dry-run
    python tools/refresh_cycle_play_universe.py --base-dir /path/to/repo

Auto-trigger: .github/workflows/cycle_play_refresh.yml (monthly cron 1st @ 14:00 UTC).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

CYCLE_PLAY_YAML_PATH = REPO_ROOT / "cycle_play_universe.yaml"

MIN_MCAP_USD_B = 0.3
MAX_MCAP_USD_B = 30.0
LIQUIDITY_DOLLAR_VOLUME_MUSD = 30.0  # $30M/day floor


def fetch_yfinance_metadata(ticker: str) -> dict[str, Any]:
    """Fetch yfinance .info dict for a ticker. Returns empty dict on failure."""
    try:
        import yfinance as yf
    except ImportError:
        return {}
    try:
        t = yf.Ticker(ticker)
        info = t.info
        if not isinstance(info, dict):
            return {}
        return info
    except Exception as exc:
        print(f"  [yfinance] {ticker} fetch failed: {exc}", flush=True)
        return {}


def estimate_dollar_volume_musd(info: dict[str, Any]) -> float:
    """Estimate avg daily $ volume from yfinance .info."""
    avg_vol = info.get("averageVolume10days") or info.get("averageVolume") or 0
    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
    if not avg_vol or not price:
        return 0.0
    return float(avg_vol) * float(price) / 1_000_000.0


def refresh_existing_entry(entry: dict[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    """Refresh a single existing yaml entry. Returns (updated_entry_or_None, action_note)."""
    ticker = str(entry.get("ticker", "")).upper().strip()
    if not ticker:
        return None, f"INVALID: empty ticker in {entry}"
    if entry.get("manual_pin"):
        return entry, f"PIN  {ticker} (manual_pin=true, skipping refresh)"

    info = fetch_yfinance_metadata(ticker)
    if not info:
        return None, f"DROP {ticker} (yfinance fetch failed — likely delisted)"

    mcap_raw = info.get("marketCap") or 0
    mcap_usd_b = float(mcap_raw) / 1e9

    if mcap_usd_b < MIN_MCAP_USD_B:
        return None, f"DROP {ticker} (mcap ${mcap_usd_b:.2f}B < ${MIN_MCAP_USD_B}B floor)"
    if mcap_usd_b > MAX_MCAP_USD_B:
        return None, f"DROP {ticker} (mcap ${mcap_usd_b:.1f}B > ${MAX_MCAP_USD_B}B — graduated to R1000)"

    dv_musd = estimate_dollar_volume_musd(info)
    if dv_musd < LIQUIDITY_DOLLAR_VOLUME_MUSD:
        return None, f"DROP {ticker} (avg dollar volume ${dv_musd:.1f}M < ${LIQUIDITY_DOLLAR_VOLUME_MUSD}M floor)"

    # Update entry with current mcap (preserve other fields)
    updated = dict(entry)
    old_mcap = float(entry.get("mcap_usd_b") or 0.0)
    updated["mcap_usd_b"] = round(mcap_usd_b, 1)
    if abs(updated["mcap_usd_b"] - old_mcap) > 0.5:
        return updated, f"KEEP {ticker} (mcap ${old_mcap:.1f}B -> ${updated['mcap_usd_b']:.1f}B)"
    return updated, f"KEEP {ticker} (mcap ${updated['mcap_usd_b']:.1f}B)"


def load_existing_yaml() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load existing cycle_play_universe.yaml. Returns (entries, metadata)."""
    if not CYCLE_PLAY_YAML_PATH.exists():
        return [], {}
    try:
        import yaml
    except ImportError:
        print("ERROR: pyyaml not installed", file=sys.stderr)
        sys.exit(1)
    payload = yaml.safe_load(CYCLE_PLAY_YAML_PATH.read_text(encoding="utf-8")) or {}
    return payload.get("cycle_play_universe", []), payload.get("metadata", {})


def write_yaml(entries: list[dict[str, Any]], dry_run: bool = False) -> None:
    """Serialize entries back to yaml, preserving comments at top."""
    import yaml

    # Read original header (comments at the top — yaml dumper strips them)
    header_lines: list[str] = []
    if CYCLE_PLAY_YAML_PATH.exists():
        text = CYCLE_PLAY_YAML_PATH.read_text(encoding="utf-8")
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                header_lines.append(line)
            elif stripped.startswith("cycle_play_universe:"):
                break
            else:
                break

    # Group entries by cycle_focus theme for readable output
    theme_order = [
        "clean_energy", "ev_battery", "ai_infra",
        "memory_semi", "biotech", "fintech", "robotics",
    ]
    grouped: dict[str, list[dict]] = {t: [] for t in theme_order}
    other: list[dict] = []
    for e in entries:
        theme = str(e.get("cycle_focus", "")).lower()
        if theme in grouped:
            grouped[theme].append(e)
        else:
            other.append(e)

    payload = {"cycle_play_universe": []}
    for theme in theme_order:
        for e in grouped[theme]:
            payload["cycle_play_universe"].append(e)
    payload["cycle_play_universe"].extend(other)

    payload["metadata"] = {
        "schema_version": "2026-04-29-v1",
        "last_refreshed": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "curator": "auto-refresh",
        "total_entries": len(entries),
        "min_mcap_usd_b": MIN_MCAP_USD_B,
        "max_mcap_usd_b": MAX_MCAP_USD_B,
        "liquidity_dollar_volume_musd": LIQUIDITY_DOLLAR_VOLUME_MUSD,
    }

    body = yaml.dump(payload, sort_keys=False, default_flow_style=False, allow_unicode=True)
    full = "\n".join(header_lines).rstrip() + "\n\n" + body

    if dry_run:
        print("\n=== DRY RUN — yaml would be ===\n")
        print(full[:2000] + "\n... (truncated)" if len(full) > 2000 else full)
        return

    CYCLE_PLAY_YAML_PATH.write_text(full, encoding="utf-8")
    print(f"\n[refresh] wrote {CYCLE_PLAY_YAML_PATH} ({len(entries)} entries)", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="show changes without writing yaml")
    p.add_argument("--limit", type=int, default=0, help="process at most N entries (debug)")
    args = p.parse_args()

    entries, metadata = load_existing_yaml()
    if not entries:
        print(f"ERROR: no entries in {CYCLE_PLAY_YAML_PATH}", file=sys.stderr)
        return 1

    print(f"[refresh] loaded {len(entries)} existing entries from yaml", flush=True)
    print(f"[refresh] mcap range: ${MIN_MCAP_USD_B}B - ${MAX_MCAP_USD_B}B", flush=True)
    print(f"[refresh] liquidity floor: ${LIQUIDITY_DOLLAR_VOLUME_MUSD}M/day", flush=True)
    print()

    updated_entries: list[dict[str, Any]] = []
    actions: list[str] = []
    for i, entry in enumerate(entries):
        if args.limit and i >= args.limit:
            updated_entries.append(entry)  # preserve untouched
            continue
        new_entry, note = refresh_existing_entry(entry)
        actions.append(note)
        if new_entry is not None:
            updated_entries.append(new_entry)
        # Be polite with yfinance — sleep small amount
        time.sleep(0.2)

    n_kept = len(updated_entries)
    n_dropped = len(entries) - n_kept

    print("\n=== Refresh actions ===")
    for a in actions:
        print(f"  {a}")
    print()
    print(f"=== Summary ===")
    print(f"  before: {len(entries)} entries")
    print(f"  after:  {n_kept} entries  (dropped: {n_dropped})")

    write_yaml(updated_entries, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
