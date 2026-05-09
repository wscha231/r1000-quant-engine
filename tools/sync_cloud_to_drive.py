#!/usr/bin/env python3
"""sync_cloud_to_drive — copy GitHub Actions cloud_results/ to local Drive mirror.

User mandate (2026-04-26):
  Cloud full_rebuild commits CSV/JSON to cloud_results/full_rebuild/<date>_<mode>/.
  But local scripts (r1000_paper_executor, r1000_layer4_swap, advisor_v3) read
  from G:/내 드라이브/r1000_top30_institutional/outputs/ by default.
  This helper bridges the gap with a single command.

Usage:
    py -3 tools/sync_cloud_to_drive.py                    # latest variant (r1000+adr) → Drive
    py -3 tools/sync_cloud_to_drive.py --mode r1000       # baseline run
    py -3 tools/sync_cloud_to_drive.py --dry-run          # show what would copy
    py -3 tools/sync_cloud_to_drive.py --drive-base /custom/path  # override Drive root

What gets synced (from cloud_results/full_rebuild/latest_<mode>/):
    scored_latest.csv                  → outputs/scored_latest.csv (Drive)
    scored_unified.csv                 → outputs/scored_unified.csv (Drive)
    portfolio_latest.csv               → outputs/portfolio_latest.csv (Drive)
    concentrated_portfolio_latest.csv  → outputs/concentrated_portfolio_latest.csv (Drive)
    backtest_metrics.json              → outputs/backtest_metrics.json (Drive)
    concentrated_backtest_metrics.json → outputs/concentrated_backtest_metrics.json (Drive)
    reports/                           → outputs/reports/ (Drive)
    trade_journal/                     → outputs/trade_journal/ (Drive)
    auto_learning/                     → outputs/auto_learning/ (Drive)

After sync:
    py -3 r1000_rebalance_advisor_v3.py  (uses new scored_unified)
    py -3 r1000_paper_executor.py --advisor concentrated  (now finds Drive file)
    py -3 r1000_layer4_swap.py            (reads from Drive)

Preconditions:
    - User has run `git pull` to get latest cloud_results/ in repo
    - Drive folder exists (G:/내 드라이브/r1000_top30_institutional/outputs/ on Win,
      or override with --drive-base for other envs)

Exit codes:
    0  sync ok
    1  source dir missing (need to run full_rebuild first OR git pull)
    2  destination unwritable (Drive offline / wrong path)
    3  framework error
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DRIVE_BASE = r"G:/내 드라이브/r1000_top30_institutional"

# Files to sync (relative to source dir → relative to Drive base/outputs/)
SYNC_FILES = [
    "scored_latest.csv",
    "scored_unified.csv",
    "portfolio_latest.csv",
    "concentrated_portfolio_latest.csv",
    "backtest_metrics.json",
    "concentrated_backtest_metrics.json",
]

SYNC_DIRS = [
    "reports",
    "trade_journal",
    "broker_replay",
    "broker_trade_journal",
    "account_ledger_preview",
    "account_evaluation",
    "auto_learning",
    "macro_policy_engine",
    "selection_audit",
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", default="global_alpha_universe",
                   choices=["global_alpha_universe", "r1000", "r1000+adr", "r1000+cycle", "r1000+adr_phase14_off"],
                   help="universe_mode of the cloud rebuild to sync")
    p.add_argument("--drive-base", default=DEFAULT_DRIVE_BASE,
                   help="Drive base path (override on non-Windows or custom mount)")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would copy without writing anything")
    p.add_argument("--source-date", default="",
                   help="explicit date YYYYMMDD instead of 'latest_<mode>'")
    args = p.parse_args()

    # Resolve source
    if args.source_date:
        src_dir = ROOT / "cloud_results" / "full_rebuild" / f"{args.source_date}_{args.mode}"
    else:
        src_dir = ROOT / "cloud_results" / "full_rebuild" / f"latest_{args.mode}"

    if not src_dir.exists() or not src_dir.is_dir():
        print(f"ERROR: source dir missing: {src_dir}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Did you:", file=sys.stderr)
        print("  1. Trigger full_rebuild_manual.yml in GitHub UI?", file=sys.stderr)
        print("  2. `git pull` after the workflow committed cloud_results/?", file=sys.stderr)
        print("  3. Pass correct --mode? (default 'global_alpha_universe')", file=sys.stderr)
        return 1

    # Resolve destination
    dst_dir = Path(args.drive_base) / "outputs"
    if not args.dry_run:
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            print(f"ERROR: cannot write to Drive at {dst_dir}: {e}", file=sys.stderr)
            print("Pass --drive-base to override (e.g. ~/Documents/r1000_drive_mirror)",
                  file=sys.stderr)
            return 2

    print("=" * 70)
    print(f"sync_cloud_to_drive  {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    print(f"  source: {src_dir}")
    print(f"  dest:   {dst_dir}")
    print(f"  mode:   {'DRY-RUN' if args.dry_run else 'COPY'}")
    print()

    n_copied = 0
    n_skipped = 0
    for fname in SYNC_FILES:
        src = src_dir / fname
        dst = dst_dir / fname
        if not src.exists():
            print(f"  SKIP  {fname:42s} (not in source — full_rebuild may not have produced)")
            n_skipped += 1
            continue
        sz_kb = src.stat().st_size / 1024
        if args.dry_run:
            print(f"  WOULD {fname:42s} ({sz_kb:8.1f} KB)")
        else:
            try:
                shutil.copy2(src, dst)
                print(f"  OK    {fname:42s} ({sz_kb:8.1f} KB)")
                n_copied += 1
            except Exception as e:
                print(f"  FAIL  {fname:42s} {type(e).__name__}: {e}")
                n_skipped += 1

    for dname in SYNC_DIRS:
        src = src_dir / dname
        dst = dst_dir / dname
        label = f"{dname}/"
        if not src.exists() or not src.is_dir():
            print(f"  SKIP  {label:42s} (not in source)")
            n_skipped += 1
            continue
        if args.dry_run:
            print(f"  WOULD {label:42s} (directory)")
        else:
            try:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                print(f"  OK    {label:42s} (directory)")
                n_copied += 1
            except Exception as e:
                print(f"  FAIL  {label:42s} {type(e).__name__}: {e}")
                n_skipped += 1

    print()
    if args.dry_run:
        total_items = len(SYNC_FILES) + len(SYNC_DIRS)
        print(f"DRY-RUN: would have copied {total_items - n_skipped} items")
    else:
        print(f"Synced {n_copied} files. Skipped {n_skipped}.")
        print()
        print("Next steps:")
        print("  py -3 r1000_rebalance_advisor_v3.py            # uses new scored_unified")
        print("  py -3 r1000_paper_executor.py --advisor concentrated   # uses new portfolio")
        print("  py -3 r1000_layer4_swap.py                     # uses new scored_unified")

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
