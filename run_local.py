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
# CURRENT BASELINE: Phase 14 hybrid alpha (SHIPPED 2026-04-27).
# Verdict source: GitHub Actions run 24961673988 artifact archived under
# research/phase14_artifact/. Important: that run did not actually exercise
# ADRs (0/26 ADRs in scored_latest.csv); this baseline reflects the Phase 14
# six-feature hybrid-alpha contribution on the R1000-only effective universe.
#
# HISTORICAL BASELINES (kept as reference; do not use for verdict):
#   Phase 9 C3 + CE v2: cagr 0.2291, sharpe 1.1721, max_dd -0.2626
#   Phase 8  (pre-Phase-9): cagr 0.2186, sharpe 0.9856, max_dd -0.3208
#   2026-04-15 concentrated: cagr 0.2180, sharpe 0.73, max_dd -0.3686
#
# When next phase SHIPs, rotate CURRENT_BASELINE again per SESSION_HANDOFF.md.
# ------------------------------------------------------------------
CURRENT_BASELINE = {
    "name": "Phase 14 hybrid alpha (SHIPPED 2026-04-27, R1000-only effective)",
    "cagr": 0.2358,
    "sharpe": 1.1783,
    "max_dd": -0.2317,
    "ir": 0.9955,
    "avg_turnover_monthly": 0.4550,
    "avg_stock_names": 21.99,
    "beat_month_ratio": 0.6265,
    "excess_cagr": 0.1008,
    # Sleeve counts from run 24961673988 artifact verdict.log.
    "sleeve_counts_reference": {"core_compounder": 7, "future_winner": 7, "early_scout": 4},
    # Alternate policy metrics (not used for verdict; informational)
    "alt_policies": {
        "concentrated_champion": {
            "target_stock_names": 5,
            "rebalance_interval_months": 1,
            "weighting_mode": "score_power",
            "cagr": 0.3340,
            "sharpe": 1.284,
            "max_dd": -0.2529,
            "holdings": ["MRVL (26.2%)", "AMKR (22.5%)", "WDC (18.7%)", "CIEN (18.3%)", "FTI (14.3%)"],
        },
    },
}

# Prior production baseline (pre-Phase-14) — kept for historical delta calc
PHASE9_C3_CE_V2_BASELINE = {
    # Phase 9 C3 + CE v2 SHIPPED 2026-04-18 21:22 KST on commit d3d3a91.
    # Measured via `py -3 run_local.py --no-collector` QUICK_RESCORE (which
    # re-did Phase 3 + 4 due to config_fingerprint change after CE v2 commit).
    # See CHANGELOG 21:30 KST entry for full verdict.
    #
    # Main diversified metrics below are from `outputs/backtest_metrics.json`
    # (adaptive monthly policy). Ship gate PASS: ΔCAGR +1.22pp, ΔSharpe +0.099,
    # ΔMaxDD -2.29pp (within -3pp gate), ΔIR +0.149 vs prior Phase 9 C1+C2
    # baseline (21.69% / 1.073 / -23.97% / 0.799).
    #
    # CE v2 result: 10 combos > 30% CAGR. Engine-selected concentrated champion
    # captured in `alt_policies.concentrated_champion` below.
    "name": "Phase 9 C3 + CE v2 (SHIPPED 2026-04-18, adaptive monthly)",
    "cagr": 0.2291,
    "sharpe": 1.1721,
    "max_dd": -0.2626,
    "ir": 0.9474,
    "avg_turnover_monthly": 0.4308,
    "avg_stock_names": 20.43,
    "beat_month_ratio": 0.5783,
    "excess_cagr": 0.0942,
    # Sleeve counts from this run (defensive_drawdown_control cap policy 60/25/15)
    "sleeve_counts_reference": {"core_compounder": 8, "future_winner": 5, "early_scout": 4},
    # Alternate policy metrics (not used for verdict; informational)
    "alt_policies": {
        # 🎯 User's original CAGR 30%+ goal SHIPPED via this config:
        "concentrated_champion": {
            "target_stock_names": 5,
            "rebalance_interval_months": 1,
            "weighting_mode": "score_power",
            "cagr": 0.3475,
            "sharpe": 1.2538,
            "max_dd": -0.2674,
            "ir": 1.0734,
            "avg_turnover_monthly": 0.5379,
            "ending_capital_usd": 786745,
            "holdings": ["PR (30.3%)", "ETR (27.8%)", "GEV (15.2%)", "FTI (14.5%)", "AKAM (12.3%)"],
        },
        # Runner-up concentrated combos (all >30% CAGR on 83-month backtest):
        "concentrated_alternatives_gt30pct": [
            {"n": 3, "interval": 1, "mode": "score_power", "cagr": 0.3377, "sharpe": 1.193},
            {"n": 4, "interval": 1, "mode": "score_power", "cagr": 0.3270, "sharpe": 1.185},
            {"n": 7, "interval": 2, "mode": "score_power", "cagr": 0.3092, "sharpe": 1.227},
            {"n": "3..10", "interval": 1, "mode": "conviction_curve", "cagr": 0.3080, "sharpe": 1.136, "note": "N-insensitive tie due to conviction curve weight decay"},
            {"n": 7, "interval": 1, "mode": "score_power", "cagr": 0.3028, "sharpe": 1.192},
        ],
    },
}

# Prior production baseline (pre-C3+CE v2) — kept for historical delta calc
PHASE9_C1C2_BASELINE = {
    "name": "Phase 9 C1+C2 (SHIPPED 2026-04-18, adaptive monthly) — prior baseline",
    "cagr": 0.2169,
    "sharpe": 1.0732,
    "max_dd": -0.2397,
    "ir": 0.7985,
    "avg_turnover_monthly": 0.4498,
    "avg_stock_names": 22.81,
    "beat_month_ratio": 0.5904,
    "excess_cagr": 0.0819,
    "sleeve_counts_reference": {"core_compounder": 7, "future_winner": 6, "early_scout": 4},
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
    p.add_argument("--universe-mode", default=None,
                   help="Universe mode override. Defaults to UNIVERSE_MODE env when set. "
                        "Supported: r1000, r1000+adr, global_alpha_universe, adr, "
                        "r1000+adr_phase14_off.")
    p.add_argument("--backtest-years", type=int, default=None,
                   help="Default out-of-sample backtest window in years. Defaults to "
                        "BACKTEST_YEARS env when set, otherwise EngineConfig default.")
    p.add_argument("--ab-quick", action="store_true",
                   help="A/B fast-iter mode: disable 7 expensive grid comparisons "
                        "(portfolio_size, rebalance_interval, backtest_window, sleeve_regime, "
                        "sleeve_cap_policy, standalone_sleeve, concentrated grid). "
                        "Main backtest + latest concentrated champion only. "
                        "Expected runtime ~2-5 min vs ~20-30 for default QUICK. "
                        "NOTE: concentrated_backtest_metrics.json may be stale from prior grid run; "
                        "use default QUICK when you need full concentrated grid A/B.")
    # Common Phase 9 toggle shortcuts
    p.add_argument("--phase9-c1", choices=["auto", "0", "1"], default="auto",
                   help="Phase 9 C1 multi_year rebalance (default: auto = on per cfg).")
    p.add_argument("--phase9-c2", choices=["auto", "0", "1"], default="auto",
                   help="Phase 9 C2 percentile thesis-gate (default: auto = on per cfg).")
    p.add_argument("--phase9-c3", choices=["auto", "0", "1"], default="auto",
                   help="Phase 9 C3 EPS turn-positive + still-loss-improving branches (default: auto = on per cfg).")
    return p.parse_args()


# ------------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------------

def check_prereqs(base_dir: Path) -> tuple[bool, list[str]]:
    """Return (ok, messages). If not ok, caller should exit 2."""
    msgs: list[str] = []

    # Python version
    # Note: refactor/phase-a allowed 3.9 after verifying engine imports + compiles
    # without 3.10 syntax. If walk-forward training crashes on 3.9, install Python
    # 3.12 via `winget install Python.Python.3.12` and re-run.
    if sys.version_info < (3, 9):
        msgs.append(f"ERROR: Python {sys.version_info[0]}.{sys.version_info[1]} too old (need 3.9+)")

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


def resolve_universe_mode(raw: Optional[str]) -> str:
    """Resolve CLI/env universe mode into the EngineConfig value."""
    value = (raw or os.environ.get("UNIVERSE_MODE") or "").strip()
    if not value:
        return ""
    # Historical docs used both spellings; keep both accepted but normalize.
    aliases = {
        "r1000+adr+phase14_off": "r1000+adr_phase14_off",
        "global-alpha": "global_alpha_universe",
        "global_alpha": "global_alpha_universe",
        "global+adr": "global_alpha_universe",
    }
    value = aliases.get(value, value)
    allowed = {
        "historical_snapshot_preferred",
        "current_constituents",
        "r1000",
        "r1000+adr",
        "global_alpha_universe",
        "adr",
        "r1000+adr_phase14_off",
    }
    if value not in allowed:
        raise ValueError(f"unsupported universe mode: {value!r}")
    return value


def resolve_backtest_years(raw: Optional[int]) -> Optional[int]:
    """Resolve CLI/env backtest window into an EngineConfig override."""
    if raw is not None:
        value = raw
    else:
        env_value = (os.environ.get("BACKTEST_YEARS") or "").strip()
        if not env_value:
            return None
        try:
            value = int(env_value)
        except ValueError as exc:
            raise ValueError(f"BACKTEST_YEARS must be an integer, got {env_value!r}") from exc
    if int(value) < 1:
        raise ValueError(f"backtest years must be >= 1, got {value!r}")
    return int(value)


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
        top_source = pf.copy()
        top_source["weight"] = pd.to_numeric(top_source["weight"], errors="coerce")
        top_source = top_source.dropna(subset=["weight"])
        if top_source.empty:
            print("  Top 10 by weight: n/a (no numeric position weights)")
        else:
            top = top_source.nlargest(10, "weight")
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

    # Phase 12D (2026-04-21): print lifetime metrics if available.
    # Connects backtest CAGR to live CAGR continuity (Phase 12C produces these).
    lifetime_metrics_path = out_dir / "lifetime_metrics.json"
    if lifetime_metrics_path.exists():
        try:
            lm = json.loads(lifetime_metrics_path.read_text(encoding="utf-8"))
            print("\n" + "=" * 70)
            print("LIFETIME PERFORMANCE (backtest + live, Phase 12D)")
            print("=" * 70)
            anchor = lm.get("anchor_date", "?")
            anchor_eq = lm.get("anchor_equity", float("nan"))
            l_cagr = lm.get("lifetime_cagr", float("nan"))
            l_total = lm.get("lifetime_total_return", float("nan"))
            l_years = lm.get("lifetime_years", float("nan"))
            l_method = lm.get("live_value_method", "n/a")
            l_only_ret = lm.get("live_only_return", float("nan"))
            l_only_days = lm.get("live_only_days", 0)
            print(f"  Backtest anchor: {anchor} at equity {anchor_eq:.4f}")
            if isinstance(l_cagr, (int, float)) and l_cagr == l_cagr:  # not NaN
                print(f"  Lifetime CAGR:   {l_cagr:.2%} over {l_years:.2f} years")
                print(f"  Lifetime total:  {l_total:.2%}")
                bt_cagr = CURRENT_BASELINE.get("cagr")
                if isinstance(bt_cagr, (int, float)):
                    delta_to_baseline = (l_cagr - bt_cagr) * 100
                    print(f"  vs baseline CAGR ({bt_cagr:.2%}): {delta_to_baseline:+.2f}pp")
            else:
                print(f"  Lifetime CAGR:   n/a (live extension inactive)")
            print(f"  Live extension:  method={l_method}, days={l_only_days}, "
                  f"return={(l_only_ret * 100):+.2f}%" if isinstance(l_only_ret, (int, float)) and l_only_ret == l_only_ret
                  else f"  Live extension:  method={l_method} (no live data yet)")
            if l_method == "no_live_data":
                print("  HINT: edit base_dir/manual_positions.yaml with real broker holdings")
                print("        (avg_cost, shares, entry_date) to activate lifetime CAGR.")
        except Exception as exc:
            print(f"  [Phase 12D] failed to read lifetime_metrics.json: {exc}")

    return 0


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

COMMON_CFG_OVERRIDES = {
    "sec_user_agent": "R1000InstitutionalBot (contact: andrewcha231@gmail.com)",
    # Prefer env var FRED_API_KEY; fallback to user's registered key 2026-04-24.
    "fred_api_key": os.environ.get("FRED_API_KEY", "dac25101c8dc447c12fa29c8bff99ba3"),
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
    try:
        universe_mode = resolve_universe_mode(args.universe_mode)
        backtest_years = resolve_backtest_years(args.backtest_years)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Phase toggles
    apply_phase_toggle("PHASE_PHASE9_C1_REBALANCE_ENABLED", args.phase9_c1)
    apply_phase_toggle("PHASE_PHASE9_THESIS_GATE_ENABLED", args.phase9_c2)
    apply_phase_toggle("PHASE_PHASE9_C3_TURNAROUND_ENABLED", args.phase9_c3)
    # Backward compatibility for the first Phase 14 GHA workflow wiring.
    if os.environ.get("PHASE14_HYBRID_ALPHA_ENABLED") and not os.environ.get("PHASE_PHASE14_HYBRID_ALPHA_ENABLED"):
        os.environ["PHASE_PHASE14_HYBRID_ALPHA_ENABLED"] = os.environ["PHASE14_HYBRID_ALPHA_ENABLED"]
    if universe_mode == "r1000+adr_phase14_off":
        os.environ["PHASE_PHASE14_HYBRID_ALPHA_ENABLED"] = "0"
    runtime_overrides = dict(COMMON_CFG_OVERRIDES)
    if universe_mode:
        runtime_overrides["universe_mode"] = universe_mode
    if backtest_years is not None:
        runtime_overrides["default_backtest_years"] = int(backtest_years)
        runtime_overrides["backtest_window_comparison_years"] = sorted({5, 8, int(backtest_years)})

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
    print(f"  universe_mode: {universe_mode or '(cfg default)'}")
    print(f"  backtest_years: {backtest_years or '(cfg default)'}")
    print(f"  collector:     {'skipped' if args.no_collector else 'run'}")
    print(f"  verdict_only:  {args.verdict_only}")
    print(f"  Phase 9 C1:    {args.phase9_c1}")
    print(f"  Phase 9 C2:    {args.phase9_c2}")
    print(f"  Phase 9 C3:    {args.phase9_c3}")
    print(f"  Phase 14:      {os.environ.get('PHASE_PHASE14_HYBRID_ALPHA_ENABLED', 'auto')}")
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
        collector_cfg.update(runtime_overrides)
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
    pipeline_cfg.update(runtime_overrides)
    pipeline_cfg["fast_mode"] = fast_mode if args.full else True
    if args.full:
        pipeline_cfg["reuse_existing_artifacts"] = True
        pipeline_cfg["resume_partial_walkforward"] = False
        pipeline_cfg["reuse_phase4_models_for_latest_recommendations"] = False
        pipeline_cfg["force_full_fund_panel_rebuild"] = False
        # Warm industry metadata cache on first FULL run
        pipeline_cfg["industry_metadata_max_new_per_run"] = 1200
        pipeline_cfg["industry_metadata_refresh_days"] = 60
    if args.ab_quick:
        # 2026-04-22: disable 7 comparison grids for fast-iter A/B runs.
        # Main backtest only. Set ab_quick_mode flag so apply_fast_mode honors
        # the override (otherwise apply_fast_mode forces concentrated back ON).
        pipeline_cfg["ab_quick_mode"] = True
        pipeline_cfg["run_portfolio_size_comparison"] = False
        pipeline_cfg["run_rebalance_interval_comparison"] = False
        pipeline_cfg["run_backtest_window_comparison"] = False
        pipeline_cfg["run_sleeve_regime_comparison"] = False
        pipeline_cfg["run_sleeve_cap_policy_comparison"] = False
        pipeline_cfg["run_standalone_sleeve_backtest_comparison"] = False
        pipeline_cfg["run_concentrated_backtest_comparison"] = False
        print(f"[{now_kst()}]   --ab-quick: ALL comparison grids DISABLED (main backtest only, ~2-5 min)")

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
