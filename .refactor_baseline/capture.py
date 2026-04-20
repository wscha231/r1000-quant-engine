#!/usr/bin/env python3
"""Capture baseline outputs for Refactor Phase A Stage 0.

Reads the current `outputs/` files on Drive, hashes them, copies them into
`.refactor_baseline/` as `*.ref.*`, and writes `reference.json` with the
SHA256 manifest plus engine metadata (commit, engine_version, row counts,
metric snapshot).

This is the OPPOSITE side of `verify.py`:
    capture.py  →  freeze current outputs as the reference
    verify.py   →  compare current outputs against the frozen reference

Usage
-----
    py -3 .refactor_baseline/capture.py

Exit codes
----------
    0 - baseline captured, reference.json + 4 ref files written
    1 - missing output files (run `py -3 run_local.py --no-collector` first)
    2 - script/filesystem error

Environment
-----------
    Reads from G:\\내 드라이브\\r1000_top30_institutional\\outputs\\ by default.
    Override with --base-dir when running in Colab:
        py -3 .refactor_baseline/capture.py --base-dir /content/drive/MyDrive/r1000_top30_institutional
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REF = Path(__file__).resolve().parent
REPO_ROOT = REF.parent
DEFAULT_BASE_DIR = r"G:\내 드라이브\r1000_top30_institutional"

# 4 files we freeze for byte-exact verification
REF_FILES = [
    ("scored_latest.csv", "scored_latest.ref.csv"),
    ("portfolio_latest.csv", "portfolio_latest.ref.csv"),
    ("weights_latest.json", "weights_latest.ref.json"),
    ("backtest_metrics.json", "backtest_metrics.ref.json"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=3,
        ).stdout.strip()
        return out or "(unknown)"
    except Exception:
        return "(unknown)"


def _git_dirty() -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=3,
        ).stdout.strip()
        return out != ""
    except Exception:
        return False


def _engine_reuse_version() -> str:
    """Parse ENGINE_REUSE_VERSION from r1000_top30_institutional.py without importing."""
    src = (REPO_ROOT / "r1000_top30_institutional.py").read_text(encoding="utf-8", errors="replace")
    for line in src.splitlines():
        if line.startswith("ENGINE_REUSE_VERSION"):
            # ENGINE_REUSE_VERSION = "YYYY-MM-DD-slug"
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "(unknown)"


def main() -> int:
    # Force UTF-8 stdout on Windows so Korean paths + emoji don't crash cp949
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR,
                        help=f"Drive mirror path containing outputs/ (default: {DEFAULT_BASE_DIR!r})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be captured without writing files.")
    args = parser.parse_args()

    base = Path(args.base_dir)
    outputs = base / "outputs"
    if not outputs.exists():
        print(f"ERROR: outputs dir missing: {outputs}")
        print(f"       Check --base-dir or run `py -3 run_local.py --no-collector` first.")
        return 1

    # Validate all 4 source files exist before we start copying
    missing = []
    src_paths: list[tuple[Path, Path]] = []
    for src_name, ref_name in REF_FILES:
        src = outputs / src_name
        ref = REF / ref_name
        if not src.exists():
            missing.append(str(src))
        src_paths.append((src, ref))
    if missing:
        print("ERROR: required output files missing, cannot capture baseline:")
        for m in missing:
            print(f"  - {m}")
        return 1

    # Hash + copy each file
    manifest: dict = {
        "schema_version": 1,
        "captured_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST"),
        "captured_from_commit": _git_sha(),
        "captured_from_commit_dirty": _git_dirty(),
        "engine_reuse_version": _engine_reuse_version(),
        "base_dir": str(base),
        "files": {},
    }

    print(f"Capturing baseline from {outputs}")
    print(f"  commit={manifest['captured_from_commit'][:10]}{'(DIRTY)' if manifest['captured_from_commit_dirty'] else ''}")
    print(f"  engine_version={manifest['engine_reuse_version']}")
    print()
    for src, ref in src_paths:
        h = _sha256(src)
        size = src.stat().st_size
        manifest["files"][src.name] = {
            "sha256": h,
            "size_bytes": size,
            "ref_path": str(ref.relative_to(REPO_ROOT)),
        }
        action = "DRY" if args.dry_run else ("COPY")
        print(f"  {action}  {src.name:25s}  sha={h[:10]}  size={size:,}  -> {ref.name}")
        if not args.dry_run:
            shutil.copy2(src, ref)

    # Numeric snapshot for quick human sanity (optional, pulled from backtest_metrics.json)
    bm_path = outputs / "backtest_metrics.json"
    try:
        bm = json.loads(bm_path.read_text(encoding="utf-8"))
        manifest["metrics_snapshot"] = {
            k: bm.get(k) for k in (
                "cagr", "sharpe", "max_dd", "ir", "excess_cagr",
                "avg_stock_names", "avg_turnover_monthly",
                "beat_month_ratio", "backtest_months",
            ) if k in bm
        }
    except Exception as exc:
        manifest["metrics_snapshot"] = {"error": str(exc)}

    # Concentrated champion snapshot (optional, for audit context)
    cm_path = outputs / "concentrated_backtest_metrics.json"
    if cm_path.exists():
        try:
            cm = json.loads(cm_path.read_text(encoding="utf-8"))
            manifest["concentrated_snapshot"] = {
                k: cm.get(k) for k in (
                    "target_stock_names", "rebalance_interval_months", "weighting_mode",
                    "strategy_cagr", "sharpe", "max_dd", "ir", "comparison_objective",
                ) if k in cm
            }
        except Exception as exc:
            manifest["concentrated_snapshot"] = {"error": str(exc)}

    # Row counts for csv ref files (sanity -- a future refactor might silently change row count)
    try:
        import csv
        row_counts = {}
        for src_name, _ in REF_FILES:
            if src_name.endswith(".csv"):
                with (outputs / src_name).open(encoding="utf-8") as f:
                    row_counts[src_name] = sum(1 for _ in f) - 1  # minus header
        manifest["csv_row_counts"] = row_counts
    except Exception as exc:
        manifest["csv_row_counts"] = {"error": str(exc)}

    if args.dry_run:
        print()
        print("DRY RUN -- reference.json would contain:")
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0

    ref_json = REF / "reference.json"
    ref_json.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print()
    print(f"  WROTE  {ref_json.relative_to(REPO_ROOT)}")
    print()
    print("BASELINE CAPTURED. Next steps:")
    print("  1. py -3 .refactor_baseline/verify.py       # confirm it self-validates")
    print("  2. git add .refactor_baseline/              # stage")
    print("  3. git commit -m 'Stage 0 DONE: baseline captured from <commit>'")
    print("  4. git push origin refactor/phase-a-module-split")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"\ncapture.py crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
