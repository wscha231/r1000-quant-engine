#!/usr/bin/env python3
"""Run the r1000 Quant Engine pipeline LOCALLY (no Colab round-trip).

This replicates `colab_run.ipynb` Cells 2-4 + Cell E (verdict) as a single
Python script. Uses the locally-synced Drive mirror for all cached data
(cache_prices, feature_store, checkpoints, etc).

Usage
-----
    py -3 run_local.py                          # QUICK_RESCORE (~15-25 min)
    py -3 run_local.py --full                   # FULL REBUILD (~2-3 h CPU, longer w/o GPU)
    py -3 run_local.py --no-collector           # Skip collector (use cached prices)
    py -3 run_local.py --verdict-only           # Skip pipeline, only print Cell E verdict
    py -3 run_local.py --end-date 2026-04-18    # Override end date (default: today KST)
    py -3 run_local.py --base-dir "G:/..."      # Override Drive mirror path

Phase toggles (same env-var convention as Colab Cell 2):
    set PHASE_PHASE9_C1_REBALANCE_ENABLED=0     # Windows cmd.exe
    $env:PHASE_PHASE9_C1_REBALANCE_ENABLED = "0" # PowerShell
    py -3 run_local.py --phase9-c1=0            # CLI shortcut for common ones
    py -3 run_local.py --phase9-c2=0

Prerequisites
-------------
    * py -3 with numpy, pandas, sklearn, catboost, yfinance, requests, pyarrow
      (verify: `py -3 tests/smoke_test.py --quick`)
    * Drive synced to default `G:/내 드라이브/r1000_top30_institutional/`,
      or pass `--base-dir` pointing at another cached copy.
    * SEC_USER_AGENT + FRED_API_KEY environment variables (defaults embedded).

Exit codes
----------
    0 - pipeline complete (or verdict printed), see stdout for SHIP/PARTIAL/REGRESS
    1 - pipeline crashed (traceback printed)
    2 - prerequisite missing (deps, Drive path, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_DIR = r"G:\내 드라이브\r1000_top30_institutional"

# ------------------------------------------------------------------
# Baseline metrics — used for Cell E verdict delta comparison.
#
# CURRENT BASELINE: Phase 9 C1+C2 (SHIPPED 2026-04-18). Rotated from
# Phase 8 after SHIP decision on commit 79d6fe8 verdict PARTIAL (user
# accepted -0.74pp CAGR trade for +0.08 Sharpe, +5.78pp MaxDD, and
# sleeve taxonomy restoration with 8 early_scout names).
#
# HISTORICAL BASELINES (kept as reference; do not use for verdict):
#   Phase 8  (pre-Phase-9): cagr 0.2186, sharpe 0.9856, max_dd -0.3208
#   2026-04-15 concentrated: cagr 0.2180, sharpe 0.73, max_dd -0.3686
#
# When next phase (C3 / refactor / etc.) SHIPs, rotate CURRENT_BASELINE
# again per SESSION_HANDOFF.md §7 rotation rule.
# ------------------------------------------------------------------
CURRENT_BASELINE = {
    "name": "Phase 9 C1+C2 (SHIPPED 2026-04-18)",
    "cagr": 0.2112,
    "sharpe": 1.0664,
    "max_dd": -0.2630,
    "ir": 0.6977,
    "avg_turnover_monthly": 0.4774,
    "avg_stock_names": 24.35,
    "beat_month_ratio": 0.6145,
    "excess_cagr": 0.0763,
    # Sleeve counts for regression check (Phase 8 was 0 early -> shipped 8)
    "sleeve_counts_reference": {"core_compounder": 4, "future_winner": 5, "early_scout": 8},
}

# Previous baseline kept for legacy / historical comparison utilities
PHASE8_BASELINE = {
    "cagr": 0.2186,
    "sharpe": 0.9856,
    "max_dd": -0.3208,
    "ir": 0.5800,
    "avg_turnover_monthly": 0.5119,
    "avg_stock_names": 21.34,
}


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--full", action="store_true",
                   help="FULL rebuild (rebuilds feature_store + retrains models). Default is QUICK_RESCORE.")
    p.add_argument("--no-collector", action="store_true",
                   help="Skip the data collection step (use existing cached prices + SEC + macro).")
    p.add_argument("--verdict-only", action="store_true",
                   help="Skip the entire pipeline. Read existing outputs and print Cell E verdict.")
    p.add_argument("--end-date", default=None,
                   help="End date YYYY-MM-DD (default: today Asia/Seoul).")
    p.add_argument("--base-dir", default=DEFAULT_BASE_DIR,
                   help=f"Drive mirror path (default: {DEFAULT_BASE_DIR!r}).")
    p.add_argument("--fast-mode", default="true", choices=["true", "false"],
                   help="fast_mode flag for collector/pipeline (default: true).")
    # Common Phase 9 toggle shortcuts
    p.add_argument("--phase9-c1", choices=["auto", "0", "1"], default="auto",
                   help="Phase 9 C1 multi_year rebalance (default: auto = on per cfg).")
    p.add_argument("--phase9-c2", choices=["auto", "0", "1"], default="auto",
                   help="Phase 9 C2 percentile thesis-gate (default: auto = on per cfg).")
    return p.parse_args()


# ------------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------------

def check_prereqs(base_dir: Path) -> tuple[bool, list[str]]:
    """Return (ok, messages). If not ok, caller should exit 2."""
    msgs: list[str] = []

    # Python version
    if sys.version_info < (3, 10):
        msgs.append(f"ERROR: Python {sys.version_info[0]}.{sys.version_info[1]} too old (need 3.10+)")

    # Deps
    for pkg in ["numpy", "pandas", "sklearn", "catboost", "yfinance", "requests", "pyarrow"]:
        try:
            __import__(pkg)
        except ImportError as e:
            msgs.append(f"ERROR: missing dependency `{pkg}` ({e})")

    # Drive path
    if not base_dir.exists():
        msgs.append(f"ERROR: base_dir does not exist: {base_dir}")
    else:
        expected_subdirs = ["cache_prices", "cache_macro", "cache_sec_actual", "feature_store", "outputs"]
        for sub in expected_subdirs:
            if not (base_dir / sub).exists():
                msgs.append(f"WARNING: {sub} missing under {base_dir} -- first-time run, will be created")

    return (not any(m.startswith("ERROR") for m in msgs), msgs)


def apply_phase_toggle(env_name: str, value: str) -> None:
    """Set env var unless value is 'auto' (keep cfg default)."""
    if value and value.lower() != "auto":
        os.environ[env_name] = str(value)


def resolve_commit_sha() -> tuple[str, bool]:
    """Return (short_sha, is_dirty). Is dirty when working tree has uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, timeout=3,
        ).stdout.strip() or "(unknown)"
        dirty = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=3,
        ).stdout.strip() != ""
        return (sha, dirty)
    except Exception:
        return ("(unknown)", False)


def now_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")


# ------------------------------------------------------------------
# Verdict (mirror of Cell E in SESSION_HANDOFF.md §2)
# ------------------------------------------------------------------

def print_verdict(base_dir: Path) -> int:
    """Read outputs, print verdict. Returns 0/1 (verdict irrelevant) or 2 (outputs missing)."""
    import pandas as pd

    out_dir = base_dir / "outputs"
    required = [
        out_dir / "scored_latest.csv",
        out_dir / "backtest_metrics.json",
        out_dir / "weights_latest.json",
        out_dir / "portfolio_latest.csv",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print()
        print("VERDICT: outputs missing -- cannot run Cell E verdict:")
        for p in missing:
            print(f"  MISS  {p}")
        return 2

    print()
    print("=" * 70)
    print("CELL E -- PHASE 9 C1+C2 DIAGNOSTIC")
    print("=" * 70)

    scored = pd.read_csv(out_dir / "scored_latest.csv", low_memory=False)
    print(f"\nScored rows: {len(scored)}")

    if "portfolio_sleeve_label" in scored.columns:
        print(f"\nSleeve distribution (raw):")
        print(scored["portfolio_sleeve_label"].value_counts().to_string())

    phase9_cols = [
        "phase9_thesis_gate_active", "phase9_core_eligible", "phase9_future_eligible",
        "phase9_early_eligible", "phase9_unassigned", "phase9_mktcap_percentile",
    ]
    print("\nPhase 9 diagnostic columns (expect populated if C2 active):")
    import pandas
    for c in phase9_cols:
        if c in scored.columns:
            v = pandas.to_numeric(scored[c], errors="coerce").fillna(0)
            print(f"  {c:40s}  mean={v.mean():.3f}  sum={v.sum():.0f}")
        else:
            print(f"  {c:40s}  MISSING (C2 toggle may be off)")

    pf = pd.read_csv(out_dir / "portfolio_latest.csv")
    print(f"\nFinal portfolio: {len(pf)} positions")
    if "portfolio_sleeve_label" in pf.columns:
        print(f"  Sleeve dist: {pf.groupby('portfolio_sleeve_label').size().to_dict()}")
    if "weight" in pf.columns and "ticker" in pf.columns:
        top = pf.nlargest(10, "weight")
        keep = [c for c in ["ticker", "portfolio_sleeve_label", "weight"] if c in top.columns]
        print(f"  Top 10 by weight:")
        print(top[keep].to_string(index=False))

    print("\n" + "=" * 70)
    print(f"METRICS vs baseline: {CURRENT_BASELINE['name']}")
    print("=" * 70)
    bm = json.loads((out_dir / "backtest_metrics.json").read_text(encoding="utf-8"))
    print(f"  {'metric':24s} {'new':>10s} {'baseline':>10s} {'delta':>14s}")
    for k in ["cagr", "sharpe", "max_dd", "ir", "avg_turnover_monthly",
              "avg_stock_names", "beat_month_ratio", "excess_cagr"]:
        new_v = bm.get(k)
        bl_v = CURRENT_BASELINE.get(k)
        if bl_v is None:
            if isinstance(new_v, (int, float)):
                print(f"  {k:24s} {new_v:>10.4f}")
            continue
        if not isinstance(new_v, (int, float)):
            print(f"  {k:24s} {'n/a':>10s}")
            continue
        if k in ("cagr", "max_dd", "avg_turnover_monthly", "excess_cagr"):
            d_str = f"{(new_v - bl_v) * 100:+.2f}pp"
        else:
            d_str = f"{new_v - bl_v:+.4f}"
        print(f"  {k:24s} {new_v:>10.4f} {bl_v:>10.4f} {d_str:>14s}")

    print("\n=== SLEEVE ALLOCATION ===")
    weights = json.loads((out_dir / "weights_latest.json").read_text(encoding="utf-8"))
    print(f"  target:  {weights.get('sleeve_target_weights')}")
    print(f"  actual:  {weights.get('sleeve_actual_weights')}")
    print(f"  counts:  {weights.get('sleeve_selected_counts', '?')}")

    print("\n=== VERDICT ===")
    cagr = bm.get("cagr")
    sharpe = bm.get("sharpe")
    max_dd = bm.get("max_dd")
    if not all(isinstance(x, (int, float)) for x in (cagr, sharpe, max_dd)):
        print("  metrics malformed; manual inspection required")
        return 1

    dCAGR = (cagr - CURRENT_BASELINE["cagr"]) * 100
    dSharpe = sharpe - CURRENT_BASELINE["sharpe"]
    dMaxDD = (max_dd - CURRENT_BASELINE["max_dd"]) * 100
    counts = weights.get("sleeve_selected_counts") or {}
    early_n = counts.get("early_scout", 0) if isinstance(counts, dict) else 0

    print(f"  dCAGR    {dCAGR:+.2f}pp   (gate >= +0.5pp)")
    print(f"  dSharpe  {dSharpe:+.4f}    (gate >= -0.05)")
    print(f"  dMaxDD   {dMaxDD:+.2f}pp   (gate >= -3pp; positive better)")
    print(f"  early_scout selected: {early_n}    (gate >= 4)")

    if dCAGR >= 0.5 and dSharpe >= -0.05 and dMaxDD >= -3.0 and early_n >= 4:
        print(f"\n  --> SHIP vs {CURRENT_BASELINE['name']}. Rotate baseline + next phase.")
    elif dCAGR >= -2.0 and early_n >= 2:
        print(f"\n  --> PARTIAL vs {CURRENT_BASELINE['name']}. See SESSION_HANDOFF.md §3b (A/B isolation).")
    else:
        print(f"\n  --> REGRESS vs {CURRENT_BASELINE['name']}. See SESSION_HANDOFF.md §3c (rollback).")

    return 0


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

COMMON_CFG_OVERRIDES = {
    "sec_user_agent": "R1000InstitutionalBot (contact: andrewcha231@gmail.com)",
    "fred_api_key": "8d92fb5a5de226657d912fe0284dfc00",
    "macro_refresh_days": 0,
    "live_refresh_days": 1,
    "companyfacts_refresh_days": 7,
    "alpha_vantage_free_refresh_tickers": 0,
    "alpha_vantage_free_statement_repair_tickers": 0,
    "alpha_vantage_free_statement_refresh_days": 7,
    "macro_slow_release_lag_months": 1,
}


def main() -> int:
    # Force UTF-8 stdout/stderr on Windows so Korean paths (G:\내 드라이브\...)
    # render correctly instead of cp949 mojibake.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = parse_args()
    base_dir = Path(args.base_dir)
    end_date = args.end_date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    fast_mode = args.fast_mode.lower() == "true"

    # Phase toggles
    apply_phase_toggle("PHASE_PHASE9_C1_REBALANCE_ENABLED", args.phase9_c1)
    apply_phase_toggle("PHASE_PHASE9_THESIS_GATE_ENABLED", args.phase9_c2)

    # Banner
    sha, dirty = resolve_commit_sha()
    dirty_tag = " (DIRTY)" if dirty else ""
    print("=" * 70)
    print(f"r1000 Quant Engine -- local run")
    print("=" * 70)
    print(f"  commit:        {sha}{dirty_tag}")
    print(f"  started:       {now_kst()}")
    print(f"  base_dir:      {base_dir}")
    print(f"  end_date:      {end_date}")
    print(f"  mode:          {'FULL REBUILD' if args.full else 'QUICK_RESCORE'}")
    print(f"  fast_mode:     {fast_mode}")
    print(f"  collector:     {'skipped' if args.no_collector else 'run'}")
    print(f"  verdict_only:  {args.verdict_only}")
    print(f"  Phase 9 C1:    {args.phase9_c1}")
    print(f"  Phase 9 C2:    {args.phase9_c2}")
    print("=" * 70)

    # Prereqs
    ok, msgs = check_prereqs(base_dir)
    for m in msgs:
        print(m)
    if not ok:
        return 2

    # Verdict-only mode: skip everything, just read existing outputs
    if args.verdict_only:
        return print_verdict(base_dir)

    # Main pipeline flow
    sys.path.insert(0, str(REPO_ROOT))
    os.chdir(base_dir)

    # Import after env vars are set and sys.path is ready
    from r1000_data_collector import (  # noqa: E402
        collector_lean_full_run_cfg,
        pipeline_quick_rescore_cfg,
        run_data_collection,
        run_full_validation_suite,
    )
    from r1000_top30_institutional import run_default_pipeline  # noqa: E402

    t_start = time.perf_counter()

    # ---------- Step 1: collector ----------
    if not args.no_collector:
        print(f"\n[{now_kst()}] >>> Step 1: Collector ({('FULL' if args.full else 'lean')}, fast_mode={fast_mode})")
        t0 = time.perf_counter()
        collector_cfg = collector_lean_full_run_cfg(str(base_dir), end_date=end_date)
        collector_cfg.update(COMMON_CFG_OVERRIDES)
        collector_cfg["fast_mode"] = fast_mode
        try:
            collector_summary = run_data_collection(collector_cfg)
            dt = time.perf_counter() - t0
            print(f"[{now_kst()}] Collector OK in {dt/60:.1f} min")
            print(f"  core coverage keys: {list(collector_summary.get('core_latest_coverage', {}).keys())[:5]} ...")
        except Exception:
            print(f"[{now_kst()}] Collector FAILED:")
            traceback.print_exc()
            return 1
    else:
        print(f"\n[{now_kst()}] >>> Step 1: Collector SKIPPED")

    # ---------- Step 2: pipeline ----------
    print(f"\n[{now_kst()}] >>> Step 2: Pipeline ({('FULL REBUILD' if args.full else 'QUICK_RESCORE')})")
    t0 = time.perf_counter()
    if args.full:
        pipeline_cfg = collector_lean_full_run_cfg(str(base_dir), end_date=end_date)
    else:
        pipeline_cfg = pipeline_quick_rescore_cfg(str(base_dir), end_date=end_date)
    pipeline_cfg.update(COMMON_CFG_OVERRIDES)
    pipeline_cfg["fast_mode"] = fast_mode if args.full else True
    if args.full:
        pipeline_cfg["reuse_existing_artifacts"] = True
        pipeline_cfg["resume_partial_walkforward"] = False
        pipeline_cfg["reuse_phase4_models_for_latest_recommendations"] = False
        pipeline_cfg["force_full_fund_panel_rebuild"] = False
        # Warm industry metadata cache on first FULL run
        pipeline_cfg["industry_metadata_max_new_per_run"] = 1200
        pipeline_cfg["industry_metadata_refresh_days"] = 60

    try:
        result = run_default_pipeline(pipeline_cfg)
        report = run_full_validation_suite(pipeline_cfg, rerun_pipeline=False)
        dt = time.perf_counter() - t0
        print(f"[{now_kst()}] Pipeline OK in {dt/60:.1f} min")
        print(f"  acceptance_checks: {result.get('acceptance_checks', {})}")
        print(f"  portfolio_shape:   {report.get('portfolio_shape', '?')}")
    except Exception:
        print(f"[{now_kst()}] Pipeline FAILED:")
        traceback.print_exc()
        return 1

    total_dt = time.perf_counter() - t_start
    print(f"\n[{now_kst()}] TOTAL runtime: {total_dt/60:.1f} min")

    # ---------- Step 3: verdict ----------
    return print_verdict(base_dir)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\ninterrupted by user", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # top-level safety net
        print(f"\n\nrun_local.py crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
