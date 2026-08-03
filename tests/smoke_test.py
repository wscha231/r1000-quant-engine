#!/usr/bin/env python3
"""Pre-commit smoke test for r1000 Quant Engine.

Catches ~80% of bugs BEFORE the Colab round-trip. Target runtime: <15s.

Usage:
    py -3 tests/smoke_test.py                # all groups
    py -3 tests/smoke_test.py --quick        # skip import-heavy (Group 3+)
    py -3 tests/smoke_test.py --verbose      # print every test

Exit codes:
    0 = all tests pass (safe to commit + push)
    1 = at least one test failed (fix before pushing)
    2 = test framework itself crashed (file path / repo layout issue)

Test groups:
    1. syntax      -- ast.parse + JSON-valid, no imports (<100ms)
    2. structural  -- regex patterns over source (<200ms)
    3. import      -- engine module loads cleanly (~3-5s)
    4. logic       -- small synthetic fixtures exercise real functions (~1-2s)
    5. regression  -- pinned tests for historical bugs (~1-2s)

Design philosophy:
    - NO pytest dependency. Pure stdlib + numpy/pandas (required by engine anyway).
    - Each test is a single @_test-decorated function. Add more below as new
      phases ship. Keep each test <30 lines.
    - Regression tests MUST include a CHANGELOG entry reference so future
      readers know why the assertion matters.

Add a new test:
    @_test("<group>.<short_name>")
    def test_my_thing():
        ...  # AssertionError on failure; any other exception also counted as failure

Ship criteria (before merging a new feature):
    py -3 tests/smoke_test.py
    (exit 0 required)
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = ROOT / "r1000_top30_institutional.py"
CONFIG_PATH = ROOT / "r1000_config.py"  # Refactor Phase A Stage 1a onwards
HELPERS_PATH = ROOT / "r1000_helpers.py"  # Refactor Phase A Stage 2a onwards
FEATURES_PATH = ROOT / "r1000_features.py"  # Refactor Phase A Stage 3a onwards
SIGNALS_PATH = ROOT / "r1000_signals.py"  # Refactor Phase A Stage 4a onwards
PIPELINE_PATH = ROOT / "r1000_pipeline.py"  # Refactor Phase A Stage 5 onwards
COLLECTOR_PATH = ROOT / "r1000_data_collector.py"
TACTICAL_PATH = ROOT / "r1000_tactical_alpha.py"
ALPHAOPS_REPORTING_PATH = ROOT / "r1000_alphaops_reporting.py"
NOTEBOOK_PATH = ROOT / "colab_run.ipynb"

# --- tiny test framework ---

_results: list[tuple[str, bool, float, str | None]] = []
_args = argparse.Namespace(quick=False, verbose=False)


def _test(name: str) -> Callable[[Callable], Callable]:
    def decorator(fn: Callable) -> Callable:
        def wrapper() -> None:
            t0 = time.perf_counter()
            try:
                fn()
                dt = time.perf_counter() - t0
                _results.append((name, True, dt, None))
                if _args.verbose:
                    print(f"  PASS  {name:48s}  ({dt*1000:>5.0f}ms)")
            except AssertionError as e:
                dt = time.perf_counter() - t0
                _results.append((name, False, dt, str(e)))
                print(f"  FAIL  {name:48s}  ({dt*1000:>5.0f}ms)")
                print(f"        assertion: {e}")
            except Exception as e:
                dt = time.perf_counter() - t0
                _results.append((name, False, dt, f"{type(e).__name__}: {e}"))
                print(f"  ERROR {name:48s}  ({dt*1000:>5.0f}ms)")
                print(f"        {type(e).__name__}: {e}")

        wrapper._test_name = name  # type: ignore[attr-defined]
        wrapper._test_group = name.split(".", 1)[0]  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ======================================================================
# Group 1: syntax -- no imports, <100ms total
# ======================================================================

@_test("syntax.engine_py_parses")
def test_engine_syntax() -> None:
    src = ENGINE_PATH.read_text(encoding="utf-8")
    ast.parse(src)


@_test("syntax.collector_py_parses")
def test_collector_syntax() -> None:
    src = COLLECTOR_PATH.read_text(encoding="utf-8")
    ast.parse(src)


@_test("syntax.run_local_py_parses")
def test_run_local_syntax() -> None:
    src = (ROOT / "run_local.py").read_text(encoding="utf-8")
    ast.parse(src)


@_test("syntax.tactical_alpha_py_parses")
def test_tactical_alpha_syntax() -> None:
    src = TACTICAL_PATH.read_text(encoding="utf-8")
    ast.parse(src)


@_test("syntax.alphaops_reporting_py_parses")
def test_alphaops_reporting_syntax() -> None:
    src = ALPHAOPS_REPORTING_PATH.read_text(encoding="utf-8")
    ast.parse(src)


@_test("syntax.notebook_json_valid")
def test_notebook_json() -> None:
    nb = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    assert isinstance(nb.get("cells"), list), "notebook missing 'cells' list"
    assert len(nb["cells"]) >= 10, f"unexpectedly few cells: {len(nb['cells'])}"
    # Each cell has source (str or list of str)
    for i, cell in enumerate(nb["cells"]):
        src = cell.get("source", "")
        assert isinstance(src, (str, list)), f"cell {i} source has wrong type"


# ======================================================================
# Group 2: structural -- regex over source, <200ms total
# ======================================================================

_ENGINE_SRC: str | None = None
_CONFIG_SRC: str | None = None
_HELPERS_SRC: str | None = None
_FEATURES_SRC: str | None = None
_SIGNALS_SRC: str | None = None
_PIPELINE_SRC: str | None = None


def _engine_src() -> str:
    global _ENGINE_SRC
    if _ENGINE_SRC is None:
        _ENGINE_SRC = ENGINE_PATH.read_text(encoding="utf-8")
    return _ENGINE_SRC


def _config_src() -> str:
    """Refactor Phase A Stage 1a onwards: PHASE*_COLUMNS + other pure-data
    constants live in r1000_config.py. Returns empty string if file absent
    so tests run on pre-refactor commits too."""
    global _CONFIG_SRC
    if _CONFIG_SRC is None:
        _CONFIG_SRC = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
    return _CONFIG_SRC


def _helpers_src() -> str:
    """Refactor Phase A Stage 2a onwards: pure utility helpers live in
    r1000_helpers.py (phase_is_enabled, log, hard_sanitize, etc.).
    Returns empty string if file absent."""
    global _HELPERS_SRC
    if _HELPERS_SRC is None:
        _HELPERS_SRC = HELPERS_PATH.read_text(encoding="utf-8") if HELPERS_PATH.exists() else ""
    return _HELPERS_SRC


def _features_src() -> str:
    """Refactor Phase A Stage 3a onwards: feature engineering funcs live in
    r1000_features.py (industry RS, alpha_vantage/yfinance fetchers, fund
    panel derivators incl. recompute_fund_panel_derived_columns + carry_cols).
    Returns empty string if file absent."""
    global _FEATURES_SRC
    if _FEATURES_SRC is None:
        _FEATURES_SRC = FEATURES_PATH.read_text(encoding="utf-8") if FEATURES_PATH.exists() else ""
    return _FEATURES_SRC


def _signals_src() -> str:
    """Refactor Phase A Stage 4a onwards: sleeve composition + portfolio
    construction live in r1000_signals.py (compute_portfolio_sleeve_columns
    with Phase 9 C1+C2+C3 gate, compute_portfolio_sleeve_policy target weights).
    Returns empty string if file absent."""
    global _SIGNALS_SRC
    if _SIGNALS_SRC is None:
        _SIGNALS_SRC = SIGNALS_PATH.read_text(encoding="utf-8") if SIGNALS_PATH.exists() else ""
    return _SIGNALS_SRC


def _pipeline_src() -> str:
    """Refactor Phase A Stage 5 onwards: pipeline orchestration (train_walkforward,
    backtest_portfolio, export_outputs, run_all, validate_config, concentrated
    grid, sleeve_cap_policy comparison) lives in r1000_pipeline.py.
    Returns empty string if file absent."""
    global _PIPELINE_SRC
    if _PIPELINE_SRC is None:
        _PIPELINE_SRC = PIPELINE_PATH.read_text(encoding="utf-8") if PIPELINE_PATH.exists() else ""
    return _PIPELINE_SRC


def _combined_src() -> str:
    """Engine + config + helpers + features + signals + pipeline sources combined
    for regex searches that should look across all refactored files (e.g.
    PHASE*_COLUMNS constant existence, hard_sanitize body, cfg field definitions,
    carry_cols membership, Phase 9 gate wiring, CE cap lifts in backtest_concentrated).

    Section separators use comment headers that cannot appear inside the
    actual source (the `# === r1000_*.py ===` pattern) so regex anchored
    to ^def or ^class can still find real definitions without capturing
    the header text as spurious matches.
    """
    return (
        _engine_src()
        + "\n\n# === r1000_config.py ===\n\n"
        + _config_src()
        + "\n\n# === r1000_helpers.py ===\n\n"
        + _helpers_src()
        + "\n\n# === r1000_features.py ===\n\n"
        + _features_src()
        + "\n\n# === r1000_signals.py ===\n\n"
        + _signals_src()
        + "\n\n# === r1000_pipeline.py ===\n\n"
        + _pipeline_src()
    )


@_test("structural.phase_columns_referenced_in_feature_store")
def test_phase_columns_in_keep_cols() -> None:
    """Every top-level PHASE*_COLUMNS constant must be spliced into build_feature_store.

    Regression for: Phase 2 keepcols-fix (commit 1d4fb40), Phase 1 keepcols-fix (4cd938e).

    Phase A Stage 1a (2026-04-20): PHASE*_COLUMNS moved to r1000_config.py.
    Phase A Stage 5 (2026-04-20): build_feature_store moved to r1000_pipeline.py.
    This test now greps combined sources for both the constants and the
    build_feature_store body.

    Exception: forward-only/latest-only phase columns must not enter the
    historical feature store. Those columns need their own neutrality smoke.
    """
    latest_only_phase_columns = {
        "PHASE18_ESTIMATE_REVISION_COLUMNS",
    }
    combined = _combined_src()
    # Find all PHASE*_COLUMNS module-level constants (main OR config file)
    constants = [
        c
        for c in re.findall(r"^(PHASE\w+_COLUMNS)\s*=\s*\[", combined, re.MULTILINE)
        if c not in latest_only_phase_columns
    ]
    assert constants, "no PHASE*_COLUMNS constants found -- regex or repo broken"

    # Extract build_feature_store body (up to the next top-level def)
    m = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        combined,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "build_feature_store function not found"
    fn_body = m.group(0)

    missing = [c for c in constants if c not in fn_body]
    assert not missing, (
        f"PHASE*_COLUMNS not referenced in build_feature_store: {missing}. "
        "New phase columns must be added to keep_cols and hard_sanitize whitelist."
    )


@_test("structural.phase_is_enabled_keys_snake_case")
def test_phase_is_enabled_keys() -> None:
    """phase_is_enabled() keys must be snake_case -- env name derives from uppercasing.

    Regression for: env-name mismatch bugs in Phase 8 toggle wiring.

    Phase A Stage 5 (2026-04-20): phase_is_enabled() calls now live across
    pipeline.py + signals.py + features.py; grep combined sources.
    """
    src = _combined_src()
    keys = re.findall(r'phase_is_enabled\s*\(\s*["\'](\w+)["\']', src)
    assert keys, "no phase_is_enabled() calls found -- regex or repo broken"
    for key in set(keys):
        assert re.match(r"^[a-z][a-z0-9_]*$", key), (
            f"phase_is_enabled key must be snake_case: {key!r}"
        )


@_test("structural.engine_reuse_version_format")
def test_engine_reuse_version() -> None:
    """ENGINE_REUSE_VERSION must be YYYY-MM-DD-description -- bumping triggers FS rebuild.

    Phase A Stage 1d-i (2026-04-20): ENGINE_REUSE_VERSION moved to r1000_config.py.
    Grep combined sources so test works whether constant lives in main or config.
    """
    src = _combined_src()
    m = re.search(r'^ENGINE_REUSE_VERSION\s*=\s*["\'](.*?)["\']', src, re.MULTILINE)
    assert m, "ENGINE_REUSE_VERSION constant not found"
    val = m.group(1)
    assert re.match(r"^\d{4}-\d{2}-\d{2}-[\w-]+$", val), (
        f"ENGINE_REUSE_VERSION malformed: {val!r} (expected YYYY-MM-DD-description)"
    )


@_test("structural.hard_sanitize_has_dedup_guard")
def test_hard_sanitize_dedup() -> None:
    """hard_sanitize() body must dedup `cols` to prevent ValueError.

    Regression for: commit d87160d -- FULL rebuild crashed with
    'ValueError: Columns must be same length as key' when DEFAULT_FEATURES and
    PHASE*_COLUMNS overlapped. Fix: `cols = [c for c in dict.fromkeys(cols) ...]`.

    Phase A Stage 2c (2026-04-20): hard_sanitize moved to r1000_helpers.py;
    grep combined sources so test finds it in either location.
    """
    src = _combined_src()
    m = re.search(
        r"^def hard_sanitize\b.*?(?=^def |\Z)",
        src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "hard_sanitize function not found"
    body = m.group(0)
    assert "dict.fromkeys" in body, (
        "hard_sanitize must use dict.fromkeys(cols) to dedup "
        "(regression: commit d87160d)"
    )


@_test("structural.phase9_c3_turnaround_columns_in_keep_cols")
def test_phase9_c3_columns_in_keep_cols() -> None:
    """PHASE9_C3_TURNAROUND_COLUMNS must be spliced into build_feature_store keep_cols + hard_sanitize.

    Regression guard: Phase 9 C3 adds 8 feature-store columns that would
    silently disappear without the whitelist (same trap as Phase 1/2 keepcols-fix).

    Phase A Stage 1a (2026-04-20): constant now lives in r1000_config.py.
    Phase A Stage 5 (2026-04-20): build_feature_store now lives in r1000_pipeline.py.
    """
    combined = _combined_src()
    # Constant exists (main or config) and has the expected 8 names
    assert "PHASE9_C3_TURNAROUND_COLUMNS = [" in combined, "PHASE9_C3_TURNAROUND_COLUMNS constant missing"
    required = [
        "profit_turn_positive_4q",
        "cashflow_turn_positive_4q",
        "roe_turn_positive_4q",
        "any_profitability_turn_positive_4q",
        "roe_sign_flip_pos",
        "ocf_under_loss_growth",
        "fcf_under_loss_growth",
        "ni_loss_narrowing_4q",
    ]
    # Extract the constant body from wherever it lives
    m = re.search(r"PHASE9_C3_TURNAROUND_COLUMNS\s*=\s*\[(.*?)\]", combined, re.DOTALL)
    assert m, "Failed to parse PHASE9_C3_TURNAROUND_COLUMNS body"
    body = m.group(1)
    missing = [c for c in required if f'"{c}"' not in body]
    assert not missing, f"PHASE9_C3_TURNAROUND_COLUMNS missing names: {missing}"

    # Build feature store function body (now in r1000_pipeline.py) must reference
    # the constant twice (once in keep_cols, once in hard_sanitize call)
    fn = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        combined,
        re.DOTALL | re.MULTILINE,
    )
    assert fn, "build_feature_store function not found"
    fn_body = fn.group(0)
    count = fn_body.count("PHASE9_C3_TURNAROUND_COLUMNS")
    assert count >= 2, (
        f"PHASE9_C3_TURNAROUND_COLUMNS referenced only {count} time(s) in build_feature_store; "
        "expected >=2 (keep_cols + hard_sanitize)."
    )


@_test("structural.sign_flip_pos_preserves_semantics")
def test_sign_flip_pos_pattern() -> None:
    """_sign_flip_pos formula must stay: (cur>0) & (prev<=0) & prev.notna().

    Phase 9 C3 (PHASE_9_C3_PROPOSAL.md) exposes these flags to feature_store
    via alias columns. Any change to this pattern silently breaks C3's gate.

    Phase A Stage 3d-i (2026-04-20): recompute_fund_panel_derived_columns
    (which contains _sign_flip_pos) moved to r1000_features.py; grep combined
    sources.
    """
    src = _combined_src()
    # Find _sign_flip_pos definition (nested inside recompute_fund_panel_derived_columns)
    m = re.search(
        r"def _sign_flip_pos\b.*?return flip\.fillna\(0\.0\)",
        src,
        re.DOTALL,
    )
    assert m, "_sign_flip_pos function body not found"
    body = m.group(0)
    # The exact comparison pattern that defines "flipped positive this quarter"
    assert re.search(r"cur\s*>\s*0\.0", body), "missing `cur > 0.0` check"
    assert re.search(r"prev_num\s*<=\s*0\.0", body), "missing `prev_num <= 0.0` check"
    assert "prev_num.notna()" in body, "missing `.notna()` guard -- would flip for first-reporting firms"


@_test("structural.phase9_keys_have_dual_gate_cfg")
def test_phase9_dual_gate() -> None:
    """Phase 8a.4+ and Phase 9 use dual-gate pattern: cfg field + env toggle.

    Earlier phases (1-7) are env-only by design. Later phases added the
    `phase*_enabled: bool` cfg field so programmatic callers can override
    without touching os.environ. This test locks in the dual-gate invariant
    for phases that intentionally adopt it.

    Phase A Stage 1d-ii (2026-04-20): EngineConfig moved to r1000_config.py;
    grep combined sources so test works whether cfg fields live in main or config.
    """
    src = _combined_src()
    cfg_fields = set(re.findall(r"^\s*(phase\w+_enabled)\s*:\s*bool", src, re.MULTILINE))
    # These are the phases we expect to have BOTH a cfg field AND a
    # phase_is_enabled call (dual-gate pattern established in Phase 8+).
    expected_dual = {
        "phase8a_hold_persistence_enabled",
        "phase8b_long_lookback_enabled",
        "phase8c_growth_adj_valuation_enabled",
        "phase8d_ic_reweight_enabled",
        "phase8d_long_horizon_alpha_enabled",
        "phase9_c1_rebalance_enabled",
        "phase9_thesis_gate_enabled",
        "phase9_c3_turnaround_enabled",
    }
    missing = expected_dual - cfg_fields
    assert not missing, (
        f"Dual-gate cfg fields missing: {missing}. "
        "Phase 8+/9 must keep `phase*_enabled: bool` fields in EngineConfig."
    )


@_test("structural.phase15_r2_revision_break_cfg_fields")
def test_phase15_r2_cfg() -> None:
    """Phase 15-R2 revision break exit: default OFF + env-overrides-cfg.

    Locks: cfg fields exist with default False, gate uses env override
    pattern (phase_is_enabled with default=cfg_value), tracker dict and
    streak threshold are wired in backtest_portfolio.
    """
    src = _combined_src()
    assert re.search(r"^\s*revision_break_exit_enabled\s*:\s*bool\s*=\s*False",
                     src, re.MULTILINE), \
        "revision_break_exit_enabled missing or not default False"
    assert re.search(r"^\s*revision_break_consecutive_months\s*:\s*int\s*=\s*\d+",
                     src, re.MULTILINE), \
        "revision_break_consecutive_months field missing"
    assert 'phase_is_enabled("phase15_r2_revision_break"' in src, \
        "phase15_r2_revision_break gate must be wired via phase_is_enabled"
    assert "revision_break_streak" in src, \
        "revision_break_streak tracker dict must exist in backtest_portfolio"


@_test("structural.phase15_r3_rs_break_cfg_fields")
def test_phase15_r3_cfg() -> None:
    """Phase 15-R3 stock RS break exit: default OFF + env-overrides-cfg."""
    src = _combined_src()
    assert re.search(r"^\s*rs_break_exit_enabled\s*:\s*bool\s*=\s*False",
                     src, re.MULTILINE), \
        "rs_break_exit_enabled missing or not default False"
    assert re.search(r"^\s*rs_break_min_peak_pctile\s*:\s*float\s*=",
                     src, re.MULTILINE), \
        "rs_break_min_peak_pctile field missing"
    assert re.search(r"^\s*rs_break_drop_to_pctile\s*:\s*float\s*=",
                     src, re.MULTILINE), \
        "rs_break_drop_to_pctile field missing"
    assert 'phase_is_enabled("phase15_r3_rs_break"' in src, \
        "phase15_r3_rs_break gate must be wired via phase_is_enabled"
    assert "rs_break_max_pctile" in src, \
        "rs_break_max_pctile tracker dict must exist in backtest_portfolio"


@_test("structural.phase15_r1_trailing_stop_cfg_fields")
def test_phase15_r1_trailing_stop_cfg() -> None:
    """Phase 15-R1 (2026-04-21): trailing stop config fields + per-sleeve thresholds.

    Phase 15-C (2026-04-28) update: default flipped from False -> True after
    backtest validation. The 3 per-sleeve thresholds must still exist and be
    non-negative, but absolute values are now config-driven (early_scout 0.15,
    future_winner 0.18, core_compounder 0.22 default — let winners run).

    This test locks: (a) all 3 sleeve fields exist with non-negative defaults,
    (b) enable flag exists (value can be True or False — operators can toggle).
    """
    src = _combined_src()
    # Field existence (check for the full typed declaration to catch typos)
    assert re.search(r"^\s*trailing_stop_enabled\s*:\s*bool\s*=\s*(True|False)",
                     src, re.MULTILINE), \
        "trailing_stop_enabled: bool field missing from EngineConfig"
    assert re.search(r"^\s*trailing_stop_early_scout_pct\s*:\s*float\s*=",
                     src, re.MULTILINE), \
        "trailing_stop_early_scout_pct field missing"
    assert re.search(r"^\s*trailing_stop_future_winner_pct\s*:\s*float\s*=",
                     src, re.MULTILINE), \
        "trailing_stop_future_winner_pct field missing"
    assert re.search(r"^\s*trailing_stop_core_compounder_pct\s*:\s*float\s*=",
                     src, re.MULTILINE), \
        "trailing_stop_core_compounder_pct field missing (Phase 15-C added)"


@_test("structural.phase15_a1_drop_negative_features_dual_gate")
def test_phase15_a1_dual_gate() -> None:
    """Phase 15-A1 (2026-04-22): dual-gate for dropping 3 negative-IR features.

    From research/phase15_selection_deep_audit_report.md: macro_hedge_score,
    focus_defensive_regime_score, focus_live_event_defensive_score have
    IR_3m in the -0.33 to -0.40 range AND are used with positive weights
    downstream (raw negative alpha bleeds into composites). Gated at source
    so downstream math stays intact — just multiplied by 0 when active.

    Locks: cfg field default=False, env-overrides-cfg pattern at both source
    sites (r1000_features.py macro_hedge_score; r1000_signals.py focus_*).
    """
    src = _combined_src()
    assert re.search(r"^\s*phase15_a1_drop_negative_features_enabled\s*:\s*bool\s*=\s*False",
                     src, re.MULTILINE), \
        "phase15_a1_drop_negative_features_enabled: bool = False missing (must default False pre-ship)"
    # Gate must use env-overrides-cfg (Phase 11 pattern, 980aed9)
    assert src.count('phase_is_enabled("phase15_a1_drop_negative_features"') >= 2, \
        "phase15_a1 gate must be applied at BOTH source sites (features + signals)"
    # macro_hedge_score must be multiplied by a phase15_a1 multiplier at source
    assert re.search(r'd\["macro_hedge_score"\]\s*=\s*\(\s*_phase15_a1_mult_feat\s*\*', src), \
        "macro_hedge_score computation must be gated by _phase15_a1_mult_feat"


@_test("structural.phase15_s1a_future_prune_dual_gate")
def test_phase15_s1a_dual_gate() -> None:
    """Phase 15-S1a (2026-04-21): dual-gate for future_winner composite prune.

    The IC audit (research/phase15_s1_future_winner_factor_ic.csv) flagged
    three factors with negative IR at BOTH 1m and 3m horizons. Removing them
    requires both the cfg flag `phase15_s1a_future_prune_enabled` AND the env
    var PHASE_PHASE15_S1A_FUTURE_PRUNE_ENABLED (dual-gate pattern, same as
    phase8a_neg_ic_drop and phase9_c1).

    This test locks:
      (a) cfg field present with default=False (pre-ship, no production impact)
      (b) the three future-only weight variables exist in r1000_signals.py
          and are gated via _phase15_s1a_active
      (c) phase_is_enabled("phase15_s1a_future_prune", ...) wired into signals
    """
    src = _combined_src()
    assert re.search(r"^\s*phase15_s1a_future_prune_enabled\s*:\s*bool\s*=\s*False",
                     src, re.MULTILINE), \
        "phase15_s1a_future_prune_enabled: bool = False missing (must default False pre-ship)"
    # Gate variables — ablation refactor (2026-04-21 PM) splits master toggle
    # into three per-factor sub-toggles (_drop_ft / _drop_cf / _drop_ub) so
    # individual factors can be dropped independently for A/B analysis.
    # Master toggle still works: _phase15_s1a_active feeds each sub-toggle as
    # default, so PHASE_PHASE15_S1A_FUTURE_PRUNE_ENABLED=1 drops all three.
    for weight_var, drop_var in [
        ("_w_fund_turnaround_future", "_drop_ft"),
        ("_w_cashflow_inflection_future", "_drop_cf"),
        ("_w_uptrend_breakdown_future", "_drop_ub"),
    ]:
        assert re.search(rf"{weight_var}\s*=\s*0\.0\s+if\s+{drop_var}", src), \
            f"Phase 15-S1a gate variable {weight_var} must be gated on {drop_var} " \
            "(ablation sub-toggle; default = _phase15_s1a_active for backward compat)"
    # Each sub-toggle must use env-overrides-cfg pattern inheriting master default
    for key in ("phase15_s1a_drop_ft", "phase15_s1a_drop_cf", "phase15_s1a_drop_ub"):
        assert re.search(rf'phase_is_enabled\("{key}",\s*default=_phase15_s1a_active\)', src), \
            f"Phase 15-S1a sub-toggle {key} must inherit master default via " \
            f"phase_is_enabled(\"{key}\", default=_phase15_s1a_active)"
    # Master toggle itself must still use env-overrides-cfg (Phase 11 fix 980aed9)
    assert re.search(r'phase_is_enabled\("phase15_s1a_future_prune",\s*default=_phase15_s1a_cfg\)', src), \
        "phase15_s1a master gate must use env-overrides-cfg pattern " \
        "(phase_is_enabled(\"phase15_s1a_future_prune\", default=_phase15_s1a_cfg)), not AND"


# ======================================================================
# Group 3: import -- requires numpy/pandas load, ~3-5s
# ======================================================================


_ENGINE_MODULE = None  # module-level cache so logic + regression tests share one import


def _import_engine():
    """Import the engine module once per smoke-test run. Subsequent calls
    return the cached module (avoids 15s reload per test in Groups 3-5)."""
    global _ENGINE_MODULE
    if _ENGINE_MODULE is not None:
        return _ENGINE_MODULE
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import r1000_top30_institutional  # noqa: F401
    _ENGINE_MODULE = sys.modules["r1000_top30_institutional"]
    return _ENGINE_MODULE


@_test("import.pandas_version_below_3")
def test_pandas_version() -> None:
    """pandas 3.x breaks the engine with `MergeError: incompatible merge keys
    dtype('<M8[us]') and dtype('<M8[ns]')` during Phase 1/2 fund_panel merge.

    Regression: 2026-04-18 14:37 KST local FULL REBUILD crashed under
    pandas 3.0.2 after 1.5h. Downgrade to pandas 2.3.x (Colab-compatible)
    fixed it. Keep this test until engine is explicitly pandas-3-safe.
    """
    if _args.quick:
        return
    import pandas
    major = int(pandas.__version__.split(".", 1)[0])
    assert major < 3, (
        f"pandas {pandas.__version__} detected — engine requires pandas 2.x "
        f"(pandas 3 strict datetime64 dtype check breaks fund_panel merges). "
        f"Run: `py -3 -m pip install 'pandas>=2.3,<3.0'`"
    )


@_test("import.engine_loads_cleanly")
def test_engine_import() -> None:
    if _args.quick:
        return  # skipped in --quick mode
    eng = _import_engine()
    assert hasattr(eng, "ENGINE_REUSE_VERSION"), "ENGINE_REUSE_VERSION not exported"
    assert hasattr(eng, "ENGINE_COMMIT_SHA"), "ENGINE_COMMIT_SHA not exported (commit afaa768)"
    assert hasattr(eng, "PHASE1_ALPHA_COLUMNS"), "PHASE1_ALPHA_COLUMNS not exported"
    assert hasattr(eng, "PHASE2_INDUSTRY_COLUMNS"), "PHASE2_INDUSTRY_COLUMNS not exported"
    assert hasattr(eng, "PHASE8B_LONG_LOOKBACK_COLUMNS"), "PHASE8B_LONG_LOOKBACK_COLUMNS not exported"
    assert hasattr(eng, "PHASE9_C3_TURNAROUND_COLUMNS"), "PHASE9_C3_TURNAROUND_COLUMNS not exported (Phase 9 C3)"
    assert hasattr(eng, "weighted_sleeve_composite"), "weighted_sleeve_composite not exported"
    assert hasattr(eng, "phase_is_enabled"), "phase_is_enabled not exported"
    assert hasattr(eng, "hard_sanitize"), "hard_sanitize not exported"


@_test("import.engine_reuse_version_bumped_for_c3")
def test_engine_reuse_version_c3() -> None:
    """After Phase 9 C3 ships, ENGINE_REUSE_VERSION must reflect the FS schema change.

    Regression guard: if someone reverts C3 but forgets to revert the
    version bump, cached feature_stores from pre-C3 will be reused with
    post-C3 code paths — silent schema mismatch.
    """
    if _args.quick:
        return
    eng = _import_engine()
    ver = eng.ENGINE_REUSE_VERSION
    assert "phase9c3" in ver.lower() or ver >= "2026-04-18", (
        f"ENGINE_REUSE_VERSION {ver!r} doesn't reflect Phase 9 C3 feature-store schema change"
    )


# ======================================================================
# Group 4: logic -- small synthetic fixtures exercise real functions
# ======================================================================


@_test("logic.weighted_sleeve_composite_skips_weight_zero")
def test_weighted_sleeve_zero_weight() -> None:
    """weight=0 must be SKIPPED, not diluting row_mean denominator.

    Regression: Phase 8 agent-caught bug. Without the skip, phase toggles
    that "drop a factor" by setting weight=0 would paradoxically dilute
    other factors' effective weight by ~1/N.
    Fix site: r1000_top30_institutional.py line ~7275
    """
    if _args.quick:
        return
    import numpy as np
    import pandas as pd
    eng = _import_engine()
    wsc = eng.weighted_sleeve_composite
    idx = pd.RangeIndex(5)
    a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
    b = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0], index=idx)
    result_with_zero = wsc([(1.0, a), (0.0, b)], idx)
    result_no_zero = wsc([(1.0, a)], idx)
    assert np.allclose(result_with_zero.values, result_no_zero.values), (
        f"weight-0 caused dilution: with-zero={list(result_with_zero)} "
        f"vs no-zero={list(result_no_zero)}"
    )


@_test("logic.hard_sanitize_dedups_overlapping_cols")
def test_hard_sanitize_overlap() -> None:
    """hard_sanitize must tolerate duplicate column names in `cols` argument.

    Regression: commit d87160d -- FULL run crashed when DEFAULT_FEATURES and
    PHASE1_ALPHA_COLUMNS both listed `fundamental_turnaround_acceleration_score`.
    """
    if _args.quick:
        return
    import numpy as np
    import pandas as pd
    eng = _import_engine()
    df = pd.DataFrame({
        "a": [1.0, 2.0, np.inf, -np.inf, 1e15],
        "b": [10.0, 20.0, 30.0, 40.0, 50.0],
    })
    # Duplicate 'a' in cols -- must not crash
    result = eng.hard_sanitize(df, ["a", "b", "a", "a"], clip=1e12)
    assert "a" in result.columns and "b" in result.columns
    # Inf must be removed and large values clipped
    assert result["a"].isin([np.inf, -np.inf]).sum() == 0
    assert result["a"].abs().max() <= 1e12


@_test("logic.defensive_rotation_trims_stale_broad_leaders")
def test_defensive_rotation_trims_stale_broad_leaders() -> None:
    """Former leaders should be reduced when relative leadership breaks,
    while confirmed new monster leaders remain eligible.
    """
    if _args.quick:
        return
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_signals import compute_defensive_monster_rotation_overlay

    cfg = EngineConfig()
    df = pd.DataFrame(
        {
            "ticker": ["OLD", "NEW", "WEAK_NO_BREAK"],
            "portfolio_sleeve_label": ["core_compounder", "core_compounder", "core_compounder"],
            "market_cap_live": [300_000_000_000.0, 200_000_000_000.0, 300_000_000_000.0],
            "mktcap": [300_000_000_000.0, 200_000_000_000.0, 300_000_000_000.0],
            "rs_acceleration_score": [-0.80, 1.25, -0.90],
            "relative_strength_composite": [0.70, 5.0, 0.70],
            "near_52w_high_pct": [-0.20, 0.01, -0.20],
            "oneil_leadership_score": [-0.20, 1.5, -0.20],
            "industry_group_strength_score": [-0.25, 3.0, -0.25],
            "price_above_ma50": [0.0, 1.0, 1.0],
            "price_above_ma200": [0.0, 1.0, 1.0],
            "trend_template_relaxed": [0.0, 1.0, 1.0],
            "portfolio_future_winner_engine_score": [0.0, 1.0, 0.0],
            "portfolio_early_scout_engine_score": [0.0, 0.8, 0.0],
            "selection_confirmation_score": [0.0, 1.0, 0.0],
            "risk_penalty": [0.0, 0.0, 0.0],
            "broken_momentum_penalty": [0.8, 0.0, 0.0],
            "breakout_setup_quality_score": [0.0, 1.0, 0.0],
        }
    )
    out = compute_defensive_monster_rotation_overlay(df, cfg)
    old = out.loc[out["ticker"].eq("OLD")].iloc[0]
    new = out.loc[out["ticker"].eq("NEW")].iloc[0]
    weak_no_break = out.loc[out["ticker"].eq("WEAK_NO_BREAK")].iloc[0]
    assert float(old["portfolio_stale_mega_leader_score"]) > 0.0
    assert str(old["portfolio_defensive_rotation_action"]) == "rotate_out_stale_core"
    assert str(old["portfolio_stale_leader_reason"]) == "broad_relative_breakdown"
    assert float(new["portfolio_stale_mega_leader_score"]) == 0.0
    assert str(new["portfolio_defensive_rotation_action"]) == "promote_monster_early"
    assert float(weak_no_break["portfolio_stale_mega_leader_score"]) == 0.0
    assert str(weak_no_break["portfolio_defensive_rotation_action"]) != "rotate_out_stale_core"


@_test("logic.leader_rescue_latest_only_filters_historical_proxy")
def test_leader_rescue_latest_only_filter() -> None:
    """Leader rescue latest_only must not leak today's broad constituents
    into historical OOS months, while full_proxy keeps them for research.
    """
    if _args.quick:
        return
    import tempfile
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_helpers import get_paths
    from r1000_pipeline import apply_leader_rescue_backtest_mode_filter

    monthly = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2026-03-31", "2026-04-30", "2026-03-31", "2026-04-30", "2026-03-31"]),
            "ticker": ["RSQ", "RSQ", "HW", "HW", "BASE"],
            "universe_source": [
                "leader_rescue_sp500",
                "leader_rescue_sp500",
                "strategic_global_hardware",
                "strategic_global_hardware",
                "current_constituents_proxy+leader_rescue_sp500",
            ],
        }
    )
    with tempfile.TemporaryDirectory() as td:
        cfg = EngineConfig(base_dir=td)
        cfg.leader_rescue_backtest_mode = "latest_only"
        out = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert set(out["ticker"]) == {"RSQ", "HW", "BASE"}
        assert len(out[out["ticker"].eq("RSQ")]) == 1
        assert pd.Timestamp(out[out["ticker"].eq("RSQ")]["rebalance_date"].iloc[0]) == pd.Timestamp("2026-04-30")
        assert len(out[out["ticker"].eq("HW")]) == 1
        assert pd.Timestamp(out[out["ticker"].eq("HW")]["rebalance_date"].iloc[0]) == pd.Timestamp("2026-04-30")

        cfg.leader_rescue_backtest_mode = "full_proxy"
        out_full = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert len(out_full) == 5

        cfg.leader_rescue_backtest_mode = "off"
        out_off = apply_leader_rescue_backtest_mode_filter(cfg, get_paths(cfg), monthly)
        assert set(out_off["ticker"]) == {"BASE"}


@_test("logic.strategic_global_hardware_universe_loader")
def test_strategic_global_hardware_universe_loader() -> None:
    """Strategic hardware overlay is a data-backed universe source, not a
    portfolio instruction, and must include the missing-name diagnostics set.
    """
    if _args.quick:
        return
    from r1000_config import EngineConfig
    from r1000_pipeline import load_strategic_global_hardware_universe_frame
    from aggressive.universe import load_strategic_global_hardware_universe

    out = load_strategic_global_hardware_universe_frame(EngineConfig())
    tickers = set(out["ticker"].astype(str).str.upper().tolist())
    for ticker in ("INTC", "AMD", "ARM", "ASML", "STX", "SNDK", "WDC", "LITE", "CIEN"):
        assert ticker in tickers, ticker
    assert set(out["universe_source"].astype(str)) == {"strategic_global_hardware"}
    aggressive_tickers, aggressive_meta = load_strategic_global_hardware_universe()
    aggressive_set = set(aggressive_tickers)
    for ticker in ("INTC", "AMD", "ARM", "ASML", "STX", "SNDK", "WDC", "LITE", "CIEN"):
        assert ticker in aggressive_set, ticker
    assert aggressive_meta


@_test("logic.cycle_play_power_materials_universe_loader")
def test_cycle_play_power_materials_universe_loader() -> None:
    """Cycle overlay must include power/materials names that may be outside R1000.

    These are not buy instructions; they keep nuclear fuel-cycle, fuel-cell,
    renewable equipment, and critical-mineral candidates visible for scoring
    and theme-relative-strength diagnostics.
    """
    if _args.quick:
        return
    from aggressive.universe import load_cycle_play_universe

    tickers, meta = load_cycle_play_universe()
    ticker_set = set(tickers)
    for ticker in ("LEU", "SMR", "OKLO", "GTLS", "FLNC", "NXT", "MP", "LAC"):
        assert ticker in ticker_set, ticker
    assert meta


@_test("logic.phase_is_enabled_env_precedence")
def test_phase_is_enabled_env() -> None:
    """phase_is_enabled honours PHASE_{KEY}_ENABLED env var overrides.

    Regression: early Phase 8 bug where env var name was computed without
    .upper() transform, so env overrides silently no-op'd.
    """
    if _args.quick:
        return
    import os
    eng = _import_engine()
    key = "smoke_test_synthetic_phase"
    env_name = f"PHASE_{key.upper()}_ENABLED"

    # clean start
    os.environ.pop(env_name, None)
    assert eng.phase_is_enabled(key, default=True) is True
    assert eng.phase_is_enabled(key, default=False) is False

    # env=0 forces OFF regardless of default
    os.environ[env_name] = "0"
    assert eng.phase_is_enabled(key, default=True) is False
    os.environ[env_name] = "false"
    assert eng.phase_is_enabled(key, default=True) is False

    # env=1 forces ON regardless of default
    os.environ[env_name] = "1"
    assert eng.phase_is_enabled(key, default=False) is True
    os.environ[env_name] = "on"
    assert eng.phase_is_enabled(key, default=False) is True

    os.environ.pop(env_name, None)


@_test("logic.mktcap_percentile_cross_sectional")
def test_mktcap_percentile() -> None:
    """Phase 9 C2 uses `mktcap.rank(pct=True)` for cross-sectional gate -- verify semantics.

    Important because: user explicitly rejected absolute $ thresholds
    (`$500B could be small in 10 years`). The percentile approach must stay
    cross-sectional within rebalance_date frame.
    """
    if _args.quick:
        return
    import pandas as pd
    mktcap = pd.Series([1e9, 5e9, 50e9, 100e9, 1e12])
    pct = mktcap.rank(pct=True, method="average")
    # Smallest gets pct=0.2 (1/5), largest gets 1.0
    assert abs(pct.iloc[0] - 0.2) < 0.01, f"smallest pct wrong: {pct.iloc[0]}"
    assert abs(pct.iloc[-1] - 1.0) < 0.01, f"largest pct wrong: {pct.iloc[-1]}"
    # Monotonic
    assert list(pct) == sorted(pct), "percentile rank must be monotonic"


@_test("logic.adr_mktcap_proxy_normalizes_adr_ratio")
def test_adr_mktcap_proxy_normalizes_adr_ratio() -> None:
    """ADR price times ordinary-share count must not inflate market cap.

    Regression: TSM ADR px * Taiwan ordinary shares made TSM appear larger
    than NVDA. ADR rows must be normalized to USD company marketCap proxy.
    """
    if _args.quick:
        return
    import pandas as pd
    from r1000_config import EngineConfig
    import r1000_pipeline as pipe

    original = pipe.ensure_mktcap_proxy
    try:
        pipe.ensure_mktcap_proxy = lambda cfg, paths, tickers, max_new=500: pd.DataFrame(
            {"ticker": ["TSM"], "mktcap_proxy": [2.0e12], "updated_at": ["2026-04-29T00:00:00"]}
        )
        df = pd.DataFrame(
            {
                "rebalance_date": pd.to_datetime(["2026-04-29", "2026-04-29"]),
                "ticker": ["TSM", "NVDA"],
                "universe_source": ["adr_whitelist", "current_constituents_proxy"],
                "mktcap": [1.0e13, 5.0e12],
            }
        )
        out = pipe.apply_adr_usd_mktcap_proxy(df, EngineConfig(), {})
    finally:
        pipe.ensure_mktcap_proxy = original

    tsm = out.loc[out["ticker"].eq("TSM")].iloc[0]
    nvda = out.loc[out["ticker"].eq("NVDA")].iloc[0]
    assert abs(float(tsm["mktcap"]) - 2.0e12) < 1e6, f"TSM mktcap not normalized: {tsm['mktcap']}"
    assert abs(float(nvda["mktcap"]) - 5.0e12) < 1e6, "non-ADR mktcap should not change"
    assert str(tsm["mktcap_source"]) == "adr_yf_usd_proxy_ratio"


@_test("logic.adr_mktcap_proxy_cache_dates_are_normalized")
def test_adr_mktcap_proxy_cache_dates_are_normalized() -> None:
    """Legacy ISO-string cache rows must coexist with new Timestamp rows.

    Regression: GitHub full rebuild 25182904974 crashed while sorting
    `yf_mktcap_proxy.parquet` because `updated_at` contained both strings and
    pandas Timestamps after a cache refresh.
    """
    if _args.quick:
        return
    import tempfile

    import pandas as pd
    from pandas.api.types import is_datetime64_any_dtype

    from r1000_config import EngineConfig
    import r1000_pipeline as pipe

    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = Path(tmp)
        paths = {"cache_misc": cache_dir}
        seed = pd.DataFrame(
            {
                "ticker": ["TSM"],
                "mktcap_proxy": [2.0e12],
                "updated_at": [pd.Timestamp.utcnow().tz_localize(None)],
            }
        )
        seed.to_parquet(cache_dir / "yf_mktcap_proxy.parquet", index=False)

        original = pipe.fetch_mktcap_proxy
        try:
            pipe.fetch_mktcap_proxy = lambda ticker: {
                "ticker": ticker,
                "mktcap_proxy": 1.5e12,
                "price_currency": "USD",
                "financial_currency": "USD",
                "shares_outstanding_proxy": 1.0e9,
                "implied_shares_outstanding_proxy": 1.0e9,
                "updated_at": "2026-04-30T00:00:00",
            }
            out = pipe.ensure_mktcap_proxy(EngineConfig(), paths, ["TSM", "ASML"], max_new=5)
        finally:
            pipe.fetch_mktcap_proxy = original

    assert set(out["ticker"].astype(str)) == {"TSM", "ASML"}
    assert is_datetime64_any_dtype(out["updated_at"]), out["updated_at"].dtype


@_test("logic.adr_valuation_uses_adr_equivalent_shares")
def test_adr_valuation_uses_adr_equivalent_shares() -> None:
    """ADR EPS/share math should use mktcap/ADR price, not ordinary local shares."""
    if _args.quick:
        return
    import pandas as pd
    from r1000_config import EngineConfig
    import r1000_pipeline as pipe

    df = pd.DataFrame(
        {
            "ticker": ["TSM"],
            "universe_source": ["adr_whitelist"],
            "mktcap": [2.0e12],
            "px": [400.0],
            "shares": [25.0e9],
            "net_income_ttm": [40.0e9],
        }
    )
    out = pipe.compute_valuation_columns(df, EngineConfig())
    row = out.iloc[0]
    assert abs(float(row["shares_effective"]) - 5.0e9) < 1e3, row["shares_effective"]
    assert abs(float(row["forward_pe_final"]) - 50.0) < 1e-6, row["forward_pe_final"]


@_test("logic.companyfacts_prefers_usd_units")
def test_companyfacts_prefers_usd_units() -> None:
    """When SEC companyfacts exposes USD and local currency, choose USD."""
    if _args.quick:
        return
    import r1000_pipeline as pipe

    payload = {
        "facts": {
            "ifrs-full": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "TWD": [
                            {
                                "end": "2026-03-31",
                                "filed": "2026-04-20",
                                "form": "20-F",
                                "val": 3000.0,
                            }
                        ],
                        "USD": [
                            {
                                "end": "2026-03-31",
                                "filed": "2026-04-20",
                                "form": "20-F",
                                "val": 100.0,
                            }
                        ],
                    }
                }
            }
        }
    }
    out = pipe.extract_companyfacts_records(payload, "1046179", "revenues")
    assert len(out) == 1, out
    assert str(out.iloc[0]["unit"]) == "USD", out
    assert abs(float(out.iloc[0]["value"]) - 100.0) < 1e-9, out


# ======================================================================
# Group 5: regression pins -- historical bugs must stay fixed
# ======================================================================


@_test("regression.phase1_alpha_columns_non_empty")
def test_phase1_alpha_columns() -> None:
    """PHASE1_ALPHA_COLUMNS must contain the 5 turnaround/value/uptrend score names.

    Regression: Phase 1 keepcols-fix (4cd938e) -- if these are dropped,
    fundamental_turnaround_acceleration_score silently returns 0 via the
    NaN→0 cascade in cross_sectional_robust_z.
    """
    if _args.quick:
        return
    eng = _import_engine()
    required = {
        "fundamental_turnaround_acceleration_score",
        "cashflow_inflection_under_loss_score",
        "value_inflection_score",
        "uptrend_continuation_score",
    }
    actual = set(eng.PHASE1_ALPHA_COLUMNS)
    missing = required - actual
    assert not missing, (
        f"PHASE1_ALPHA_COLUMNS missing required names: {missing}. "
        f"Present: {actual}"
    )


@_test("regression.phase8b_long_lookback_columns")
def test_phase8b_columns() -> None:
    """PHASE8B_LONG_LOOKBACK_COLUMNS must expose mom_18m/24m/36m and multi_year_winner_score.

    Regression: Phase 8b.1 (commit 3e44d35). These drive the Phase 9 C2
    future_winner sleeve eligibility (mom_24m check).
    """
    if _args.quick:
        return
    eng = _import_engine()
    required = {"mom_18m", "mom_24m", "mom_36m", "multi_year_winner_score"}
    actual = set(eng.PHASE8B_LONG_LOOKBACK_COLUMNS)
    missing = required - actual
    assert not missing, f"PHASE8B_LONG_LOOKBACK_COLUMNS missing: {missing}"


@_test("regression.sign_flip_pos_flags_in_fund_panel_carry_cols")
def test_sign_flip_cols_carried() -> None:
    """ni/ocf/fcf/op_income_sign_flip_pos must be in fund_panel carry_cols.

    Regression: without this they'd be dropped during ffill. Phase 9 C3
    (PHASE_9_C3_PROPOSAL.md) depends on these as the underlying flags for
    profit_turn_positive_4q / cashflow_turn_positive_4q aliases.

    Phase A Stage 3d-i (2026-04-20): carry_cols lives inside
    recompute_fund_panel_derived_columns (now in r1000_features.py);
    grep combined sources.
    """
    src = _combined_src()
    # The carry_cols block in recompute_fund_panel_derived_columns
    m = re.search(r"carry_cols\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "carry_cols list not found"
    carry_block = m.group(1)
    required = [
        "ni_sign_flip_pos",
        "ocf_sign_flip_pos",
        "fcf_sign_flip_pos",
        "op_income_sign_flip_pos",
        "any_profit_sign_flip_pos",
    ]
    missing = [c for c in required if f'"{c}"' not in carry_block]
    assert not missing, f"fund_panel carry_cols missing sign-flip flags: {missing}"


@_test("regression.phase9_c3_alias_cols_in_carry_cols")
def test_phase9_c3_cols_carried() -> None:
    """Phase 9 C3 alias columns must be in fund_panel carry_cols so they ffill forward.

    Regression: without carry_cols membership, these columns exist at
    quarter boundaries but vanish between quarters — keep_cols whitelist
    alone isn't enough because build_universe_monthly merges fund_panel
    using the ffilled columns.

    Phase A Stage 3d-i (2026-04-20): carry_cols lives inside
    recompute_fund_panel_derived_columns (now in r1000_features.py);
    grep combined sources.
    """
    src = _combined_src()
    m = re.search(r"carry_cols\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "carry_cols list not found"
    carry_block = m.group(1)
    required = [
        "profit_turn_positive_4q",
        "cashflow_turn_positive_4q",
        "roe_turn_positive_4q",
        "any_profitability_turn_positive_4q",
        "roe_sign_flip_pos",
    ]
    missing = [c for c in required if f'"{c}"' not in carry_block]
    assert not missing, f"fund_panel carry_cols missing Phase 9 C3 aliases: {missing}"


@_test("regression.concentrated_expansion_caps_lifted")
def test_ce_caps_lifted() -> None:
    """Phase 9 CE (2026-04-18): 5 hard caps on concentrated N≤3 must stay lifted.

    Regression story:
      v1 (commit f93a4a2) lifted 3 OUTER caps. First FULL REBUILD showed
      N=3/4/5/7/10 producing IDENTICAL metrics because 2 inner clamps were
      missed inside select_concentrated_portfolio_topk + backtest_concentrated_portfolio.
      v2 lifts those 2 inner caps. All 5 must stay lifted.
    Fix sites:
      - EngineConfig validator: upper bound 3 -> 30
      - compare_concentrated_portfolio_backtests clean_top_n: min(x, 3) -> min(x, 30)
      - build_latest_concentrated_holdings: min(3, ...) -> min(30, ...)
      - select_concentrated_portfolio_topk (line ~24207): min(int(top_n), 3) -> 30
      - backtest_concentrated_portfolio (line ~24310): min(int(top_n), 3) -> 30

    Phase A Stage 5 (2026-04-20): validate_config + concentrated backtest
    funcs moved to r1000_pipeline.py; grep combined sources.
    """
    src = _combined_src()
    # Validator must reject > 30, NOT > 3
    assert "must be between 1 and 30" in src, (
        "EngineConfig validator still says `must be between 1 and 3` — CE cap not lifted."
    )
    # No `min(int(x), 3)` or `min(int(top_n), 3)` anywhere
    assert src.count("min(int(x), 3)") == 0, (
        "grid search loop still has `min(int(x), 3)` clamp — CE cap not lifted."
    )
    assert src.count("min(int(top_n), 3)") == 0, (
        "inner select/backtest still has `min(int(top_n), 3)` clamp — CE v2 cap not lifted. "
        "Without this, every N>3 grid point silently reports the N=3 backtest."
    )
    assert src.count("min(3, safe_float") == 0, (
        "build_latest_concentrated_holdings still has `min(3, safe_float` clamp — CE cap not lifted."
    )


@_test("regression.concentrated_expansion_defaults_widened")
def test_ce_defaults_widened() -> None:
    """Phase 9 CE cfg defaults must include N>3 options, multi-month intervals, score_power.

    Protects against someone reverting the EngineConfig default_factory
    lambdas without lifting the caps (or vice versa).
    """
    if _args.quick:
        return
    eng = _import_engine()
    cfg = eng.EngineConfig()
    assert max(cfg.concentrated_top_n_candidates) > 3, (
        f"concentrated_top_n_candidates max is {max(cfg.concentrated_top_n_candidates)}; "
        f"CE expects at least N=5 in default."
    )
    assert len(cfg.concentrated_rebalance_intervals) > 1, (
        f"concentrated_rebalance_intervals is {cfg.concentrated_rebalance_intervals}; "
        f"CE expects multiple intervals tested."
    )
    assert "score_power" in cfg.concentrated_weighting_modes, (
        f"concentrated_weighting_modes missing score_power; CE expects 3 modes."
    )


@_test("logic.concentrated_entry_quality_allows_continuation_winner")
def test_concentrated_entry_quality_continuation_override() -> None:
    """Phase 15-D2b: concentrated must not reject every extended winner.

    Low entry_quality_score blocks weak/broken chase entries, but a high-rank
    continuation winner with intact trend and low exit risk should remain
    selectable for the CAGR-max sleeve.
    """
    if _args.quick:
        return
    import pandas as pd
    import r1000_pipeline as pipe
    from r1000_config import EngineConfig

    cfg = EngineConfig()
    original_prepare = pipe.prepare_standalone_sleeve_frame
    pipe.prepare_standalone_sleeve_frame = lambda _cfg, frame: frame.copy()
    try:
        base = {
            "portfolio_sleeve_label": "future_winner",
            "portfolio_sleeve_label_raw": "future_winner",
            "selection_confirmation_score": 1.0,
            "portfolio_future_winner_engine_score": 1.0,
            "portfolio_early_scout_engine_score": 1.0,
            "sage_composite_score": 1.0,
            "breakout_setup_quality_score": 1.0,
            "relative_strength_composite": 1.0,
            "score_future_winner_model": 1.0,
            "future_winner_scout_score": 1.0,
            "trend_template_full": 1.0,
            "price_above_ma50": 1.0,
            "price_above_ma200": 1.0,
            "portfolio_hold_policy_exit_risk": 0.0,
            "broken_momentum_penalty": 0.0,
        }
        rows = [
            {"ticker": "CONT", "score": 10.0, "entry_quality_score": 0.0, **base},
            {
                "ticker": "BROKEN",
                "score": 9.0,
                "entry_quality_score": 0.0,
                "trend_template_full": 0.0,
                "price_above_ma50": 0.0,
                "portfolio_hold_policy_exit_risk": 0.80,
                "broken_momentum_penalty": 0.80,
                **{k: v for k, v in base.items() if k not in {
                    "trend_template_full",
                    "price_above_ma50",
                    "portfolio_hold_policy_exit_risk",
                    "broken_momentum_penalty",
                }},
            },
            {"ticker": "GOOD", "score": 3.0, "entry_quality_score": 0.70, **base},
        ]
        selected = pipe.select_concentrated_portfolio_topk(cfg, pd.DataFrame(rows), 2)
    finally:
        pipe.prepare_standalone_sleeve_frame = original_prepare

    tickers = set(selected["ticker"].astype(str))
    assert "CONT" in tickers, "continuation winner was blocked by entry_quality hard gate"
    assert "BROKEN" not in tickers, "broken low-quality chase entry bypassed the gate"
    cont = selected.set_index("ticker").loc["CONT"]
    assert bool(cont.get("concentrated_entry_quality_override", False)), (
        "continuation winner should be marked as entry-quality override"
    )


@_test("logic.concentrated_leader_gate_filters_lagging_defensives")
def test_concentrated_leader_gate_filters_lagging_defensives() -> None:
    """Concentrated leader gate is opt-in and filters lagging defensive rebounds."""
    if _args.quick:
        return
    import pandas as pd
    import r1000_pipeline as pipe
    from r1000_config import EngineConfig

    cfg = EngineConfig()
    cfg.portfolio_defensive_rotation_enabled = False
    cfg.concentrated_risk_candidate_filter_enabled = False
    cfg.concentrated_monster_early_min_slots = 0
    cfg.concentrated_min_entry_quality = 0.0
    original_prepare = pipe.prepare_standalone_sleeve_frame
    old_env = os.environ.get("PHASE_LEADER_GATE_ENABLED")
    pipe.prepare_standalone_sleeve_frame = lambda _cfg, frame: frame.copy()
    try:
        base = {
            "portfolio_sleeve_label": "future_winner",
            "portfolio_sleeve_label_raw": "future_winner",
            "selection_confirmation_score": 1.0,
            "portfolio_future_winner_engine_score": 1.0,
            "portfolio_early_scout_engine_score": 1.0,
            "entry_quality_score": 0.8,
            "breakout_setup_quality_score": 0.8,
            "relative_strength_composite": 1.0,
            "trend_template_full": 1.0,
            "price_above_ma50": 1.0,
            "price_above_ma200": 1.0,
        }
        rows = [
            {"ticker": "ETR", "score": 100.0, "rs_spy_3m": -0.08, "rs_qqq_3m": -0.10, "rs_spy_6m": -0.03, "rs_qqq_6m": -0.05, **base},
            {"ticker": "WDC", "score": 10.0, "rs_spy_3m": 0.08, "rs_qqq_3m": 0.06, "rs_spy_6m": 0.12, "rs_qqq_6m": 0.10, **base},
        ]
        os.environ.pop("PHASE_LEADER_GATE_ENABLED", None)
        off = pipe.select_concentrated_portfolio_topk(cfg, pd.DataFrame(rows), 1)
        os.environ["PHASE_LEADER_GATE_ENABLED"] = "1"
        on = pipe.select_concentrated_portfolio_topk(cfg, pd.DataFrame(rows), 1)
    finally:
        pipe.prepare_standalone_sleeve_frame = original_prepare
        if old_env is None:
            os.environ.pop("PHASE_LEADER_GATE_ENABLED", None)
        else:
            os.environ["PHASE_LEADER_GATE_ENABLED"] = old_env

    assert off["ticker"].astype(str).tolist() == ["ETR"], "leader gate default OFF should preserve old score ranking"
    assert on["ticker"].astype(str).tolist() == ["WDC"], "leader gate ON should reject lagging ETR fixture"
    row = on.iloc[0]
    assert row.get("leader_tier") == "DUAL_LEADER"
    assert bool(row.get("concentrated_leader_gate_pass", False))


@_test("logic.concentrated_cycle_recovery_requires_leadership_when_enabled")
def test_concentrated_cycle_recovery_requires_leadership_when_enabled() -> None:
    """Cycle recovery boost stays opt-in masked, preserving true cyclical leaders."""
    if _args.quick:
        return
    import pandas as pd
    import r1000_pipeline as pipe
    from r1000_config import EngineConfig

    cfg = EngineConfig()
    cfg.portfolio_defensive_rotation_enabled = False
    original_prepare = pipe.prepare_standalone_sleeve_frame
    old_env = os.environ.get("PHASE_CYCLE_LEADERSHIP_MASK_ENABLED")
    pipe.prepare_standalone_sleeve_frame = lambda _cfg, frame: frame.copy()
    try:
        base = {
            "portfolio_sleeve_label": "future_winner",
            "portfolio_sleeve_label_raw": "future_winner",
            "selection_confirmation_score": 1.0,
            "portfolio_future_winner_engine_score": 1.0,
            "portfolio_early_scout_engine_score": 1.0,
            "entry_quality_score": 0.8,
            "cycle_recovery_score": 1.0,
        }
        rows = [
            {"ticker": "DUK", "score": 10.0, "rs_spy_3m": -0.04, "rs_qqq_3m": -0.07, "rs_spy_6m": -0.02, "rs_qqq_6m": -0.04, **base},
            {"ticker": "AMKR", "score": 10.0, "rs_spy_3m": 0.04, "rs_qqq_3m": 0.03, "rs_spy_6m": 0.06, "rs_qqq_6m": 0.05, **base},
        ]
        os.environ["PHASE_CYCLE_LEADERSHIP_MASK_ENABLED"] = "1"
        scored = pipe.prepare_concentrated_frame(cfg, pd.DataFrame(rows)).set_index("ticker")
    finally:
        pipe.prepare_standalone_sleeve_frame = original_prepare
        if old_env is None:
            os.environ.pop("PHASE_CYCLE_LEADERSHIP_MASK_ENABLED", None)
        else:
            os.environ["PHASE_CYCLE_LEADERSHIP_MASK_ENABLED"] = old_env

    assert bool(scored.loc["AMKR", "cycle_leadership_mask_pass"])
    assert not bool(scored.loc["DUK", "cycle_leadership_mask_pass"])
    assert float(scored.loc["AMKR", "cycle_recovery_score_leader_masked"]) == 1.0
    assert float(scored.loc["DUK", "cycle_recovery_score_leader_masked"]) == 0.0


@_test("logic.alphaops_vnext_concentrated_leader_gate_blocks_nonleaders")
def test_alphaops_vnext_concentrated_leader_gate_blocks_nonleaders() -> None:
    """AlphaOps vNext concentrated leader gate also covers top7/emerging bypass lanes."""
    if _args.quick:
        return
    import pandas as pd
    from tools import run_alphaops_vnext_policy_replay as vnext

    old_env = os.environ.get("PHASE_LEADER_GATE_ENABLED")
    try:
        frame = pd.DataFrame(
            [
                {"ticker": "ETR", "primary_lane": "TOP7_MANAGER_DISCOVERY", "leader_tier": "LAGGING"},
                {"ticker": "WDC", "primary_lane": "TOP7_MANAGER_DISCOVERY", "leader_tier": "DUAL_LEADER"},
                {"ticker": "MU", "primary_lane": "TOP7_MANAGER_DISCOVERY", "leader_tier": "DUAL_LEADER"},
                {"ticker": "LITE", "primary_lane": "TOP7_MANAGER_DISCOVERY", "leader_tier": "DUAL_LEADER"},
            ]
        )
        os.environ.pop("PHASE_LEADER_GATE_ENABLED", None)
        off_frame = vnext.apply_concentrated_leader_gate_annotations(frame, "concentrated", 5)
        rec_off = off_frame[off_frame["ticker"].eq("ETR")].iloc[0].to_dict()
        ok_off, reason_off = vnext.allowed_candidate(rec_off, "concentrated", 0, is_new_buy=True)
        os.environ["PHASE_LEADER_GATE_ENABLED"] = "1"
        on_frame = vnext.apply_concentrated_leader_gate_annotations(frame, "concentrated", 5)
        rec_on = on_frame[on_frame["ticker"].eq("ETR")].iloc[0].to_dict()
        ok_on, reason_on = vnext.allowed_candidate(rec_on, "concentrated", 0, is_new_buy=True)
        rec_dual = on_frame[on_frame["ticker"].eq("WDC")].iloc[0].to_dict()
        ok_dual, reason_dual = vnext.allowed_candidate(rec_dual, "concentrated", 0, is_new_buy=True)
    finally:
        if old_env is None:
            os.environ.pop("PHASE_LEADER_GATE_ENABLED", None)
        else:
            os.environ["PHASE_LEADER_GATE_ENABLED"] = old_env

    assert ok_off, f"default OFF should preserve existing top7/emerging bypass path: {reason_off}"
    assert not ok_on and "concentrated_leader_gate" in reason_on
    assert ok_dual, f"DUAL_LEADER should pass the opt-in vNext leader gate: {reason_dual}"


@_test("logic.alphaops_vnext_cycle_mask_recomputes_primary_lane")
def test_alphaops_vnext_cycle_mask_recomputes_primary_lane() -> None:
    """AlphaOps vNext cycle mask removes nonleader cyclical lane wins without touching true leaders."""
    if _args.quick:
        return
    import pandas as pd
    from tools import run_alphaops_vnext_policy_replay as vnext

    frame = pd.DataFrame(
        [
            {
                "ticker": "DUK",
                "quality_compounder_lane_score": 0.0,
                "market_leader_lane_score": 0.10,
                "emerging_tenbagger_lane_score": 0.0,
                "top7_manager_discovery_lane_score": 0.0,
                "cyclical_recovery_lane_score": 1.0,
                "crisis_beneficiary_lane_score": 0.0,
                "top7_support_boost": 0.0,
                "top7_standalone_blocked": False,
                "rs_spy_3m": -0.04,
                "rs_qqq_3m": -0.06,
                "rs_spy_6m": -0.02,
                "rs_qqq_6m": -0.03,
            },
            {
                "ticker": "AMKR",
                "quality_compounder_lane_score": 0.0,
                "market_leader_lane_score": 0.10,
                "emerging_tenbagger_lane_score": 0.0,
                "top7_manager_discovery_lane_score": 0.0,
                "cyclical_recovery_lane_score": 1.0,
                "crisis_beneficiary_lane_score": 0.0,
                "top7_support_boost": 0.0,
                "top7_standalone_blocked": False,
                "rs_spy_3m": 0.04,
                "rs_qqq_3m": 0.03,
                "rs_spy_6m": 0.05,
                "rs_qqq_6m": 0.05,
            },
        ]
    ).set_index("ticker", drop=False)
    out = vnext.apply_cycle_leadership_mask_to_lanes(frame)

    assert not bool(out.loc["DUK", "cycle_leadership_mask_pass"])
    assert bool(out.loc["AMKR", "cycle_leadership_mask_pass"])
    assert float(out.loc["DUK", "cyclical_recovery_lane_score_leader_masked"]) == 0.0
    assert float(out.loc["AMKR", "cyclical_recovery_lane_score_leader_masked"]) == 1.0
    assert out.loc["DUK", "primary_lane"] != "CYCLICAL_RECOVERY"
    assert out.loc["AMKR", "primary_lane"] == "CYCLICAL_RECOVERY"


@_test("regression.phase9_c3_gate_wired_in_early_scout")
def test_phase9_c3_gate_wired() -> None:
    """Phase 9 C2 early-scout gate must call _p9_c3_admit as an OR branch.

    Regression: without this wire-up, C3 toggle is dead code even when
    the feature-store columns are present.

    Phase A Stage 4a (2026-04-20): compute_portfolio_sleeve_columns (which
    owns the Phase 9 early-scout gate) moved to r1000_signals.py; grep
    combined sources.
    """
    src = _combined_src()
    # _p9_c3_admit must appear in the _p9_early_elig definition
    m = re.search(
        r"_p9_early_elig\s*=\s*\([^)]*_p9_c3_admit[^)]*\)",
        src,
        re.DOTALL,
    )
    assert m, (
        "_p9_c3_admit not found inside _p9_early_elig expression. "
        "Phase 9 C3 code exists but gate not wired — disable=no-op."
    )
    # And _phase9_c3_active must gate the compute block
    assert "_phase9_c3_active = bool(" in src, "_phase9_c3_active toggle variable missing"
    assert 'phase9_c3_turnaround_enabled' in src, "cfg field phase9_c3_turnaround_enabled missing"


@_test("regression.phase11_config_fields_exported")
def test_phase11_cfg_fields() -> None:
    """Phase 11 multibagger sleeve requires 5 cfg fields + 1 column constant.

    Regression guard: EngineConfig must expose phase11_* fields so run_local.py
    / colab_run.ipynb / operator can A/B toggle this sleeve programmatically.
    """
    combined = _combined_src()
    required_fields = [
        "phase11_multibagger_sleeve_enabled",
        "phase11_sleeve_size",
        "phase11_allocation_pct",
        "phase11_p_entry_threshold",
        "phase11_p_takeprofit_threshold",
        "phase11_p_stoploss_threshold",
        "phase11_quality_min_mcap",
        "phase11_quality_min_revenue",
        "phase11_weighting_mode",
    ]
    missing = [f for f in required_fields if f not in combined]
    assert not missing, f"EngineConfig missing Phase 11 fields: {missing}"
    assert "PHASE11_MULTIBAGGER_COLUMNS = [" in combined, (
        "PHASE11_MULTIBAGGER_COLUMNS list constant missing from config"
    )


@_test("regression.phase11_columns_in_feature_store")
def test_phase11_columns_whitelisted() -> None:
    """PHASE11_MULTIBAGGER_COLUMNS must appear in build_feature_store keep_cols
    and hard_sanitize call. Without this the 3 prediction columns (p_entry,
    p_tp, p_sl) get silently dropped from feature_store_latest.parquet --
    same Phase 2 keepcols-survival regression that Phase 1 bug taught us.
    """
    combined = _combined_src()
    # Must be referenced at least twice (keep_cols list + hard_sanitize list)
    count = combined.count("PHASE11_MULTIBAGGER_COLUMNS")
    assert count >= 3, (
        f"PHASE11_MULTIBAGGER_COLUMNS referenced only {count} times across modules; "
        "expected >=3 (constant def + keep_cols whitelist + hard_sanitize whitelist)."
    )


@_test("regression.phase11_sleeve_label_in_build_target_portfolio")
def test_phase11_sleeve_wired_in_portfolio() -> None:
    """build_target_portfolio must define multibagger_target_n + have a
    multibagger selection block. Without this, even if sleeve_label is set
    to 'multibagger_watch' by compute_portfolio_sleeve_columns, the allocation
    never materializes in the final portfolio.
    """
    combined = _combined_src()
    assert "multibagger_target_n" in combined, (
        "multibagger_target_n missing -- Phase 11 count calc not wired"
    )
    assert "multibagger_sel" in combined, (
        "multibagger_sel missing -- Phase 11 selection block not wired"
    )
    assert '"multibagger_watch"' in combined, (
        "multibagger_watch sleeve label string missing"
    )


@_test("regression.pattern_miner_excludes_forward_returns")
def test_pattern_miner_no_forward_return_leakage() -> None:
    """ML pattern miner must exclude r_*m / bench_r_*m as features.

    History (commit c13fa6a, 2026-04-25): r_12m/24m/36m in feature_store
    are FORWARD-return labels, not past momentum. Original miner kept them
    as features -> decile spread inflated 15.07%, fake CAGR 76.3%. After
    fix, decile spread = 0.00% (real ML edge: ~zero). User question
    "leakage 있는거 아니야?" saved production deploy.

    This guard prevents the regression by enforcing that:
      1. r_<N>[mdy] horizons are in EXCLUDE_EXACT
      2. defensive regex r_\\d+[mdy] still present
      3. bench_r_* prefix exclusion present
    """
    miner_path = ROOT / "r1000_pattern_miner.py"
    assert miner_path.exists(), "r1000_pattern_miner.py missing"
    src = miner_path.read_text(encoding="utf-8")

    for col in ("r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m"):
        assert f'"{col}"' in src, (
            f'"{col}" missing from EXCLUDE_EXACT in r1000_pattern_miner.py — '
            f"forward-return leakage protection regressed (commit c13fa6a)"
        )
    assert "r_\\d+[mdy]" in src, (
        "defensive regex r_\\d+[mdy] missing in r1000_pattern_miner.py — "
        "any newly-named forward-return column would leak again"
    )
    assert "bench_r_" in src, (
        "bench_r_* exclusion missing in r1000_pattern_miner.py "
        "(benchmark forward returns are also leakage)"
    )


@_test("regression.paper_executor_runs_layer3_preflight")
def test_paper_executor_layer3_preflight() -> None:
    """r1000_paper_executor.py must run Layer 3 regime pre-flight on every
    invocation (unless --skip-regime-check). When --execute and HALT_NEW
    fires, must refuse without --override-regime-halt.

    History:
      Layer 3 logic shipped in c8b5773 (Phase 2)
      data bridge shipped in 6540ec6 (regime_data)
      paper_executor wiring shipped in this commit

    Without this guard, Layer 3 silently disconnects again if someone
    refactors paper_executor.main().
    """
    pe_src = (ROOT / "r1000_paper_executor.py").read_text(encoding="utf-8")
    assert "from r1000_regime_data import" in pe_src, (
        "paper_executor missing import of r1000_regime_data — Layer 3 disconnected"
    )
    assert "current_regime" in pe_src, (
        "paper_executor not calling current_regime() — Layer 3 disconnected"
    )
    assert "HALT_NEW" in pe_src, (
        "paper_executor not handling HALT_NEW Layer 3 action"
    )
    assert "override-regime-halt" in pe_src, (
        "paper_executor missing --override-regime-halt escape flag"
    )
    assert "skip-regime-check" in pe_src, (
        "paper_executor missing --skip-regime-check escape flag"
    )
    assert "allow-legacy-execute" in pe_src, (
        "paper_executor missing --allow-legacy-execute lock for old Alpaca executor"
    )


@_test("regression.after_close_daily_workflow_yaml_valid")
def test_paper_executor_workflow() -> None:
    """The consolidated daily cloud workflow must run paper execution
    dry-runs plus scanner, tactical, macro, ETF, explosive, and Layer 4
    review surfaces.
    """
    wf_path = ROOT / ".github" / "workflows" / "after_close_daily.yml"
    assert wf_path.exists(), "after_close_daily.yml workflow missing"
    wf = wf_path.read_text(encoding="utf-8")
    assert "workflow_dispatch" in wf, "manual trigger missing in paper_executor workflow"
    assert "secrets.ALPACA_API_KEY" in wf, "ALPACA_API_KEY secret not wired"
    assert "secrets.ALPACA_API_SECRET" in wf, "ALPACA_API_SECRET secret not wired"
    assert "tests/smoke_test.py --quick" in wf, (
        "smoke_test pre-flight missing — workflow could ship code that fails guards"
    )
    assert "r1000_paper_executor.py" in wf, "paper_executor not actually invoked"
    for token in (
        "tests/audit_features.py --no-runtime",
        "aggressive/scanner.py",
        "tools/macro_daily_snapshot.py",
        "tools/etf_leadership_snapshot.py",
        "tools/run_theme_leadership_tape.py",
        "tools/explosive_mover_scan_daily.py",
        "r1000_tactical_alpha.py",
        "r1000_layer4_swap.py",
    ):
        assert token in wf, f"after_close_daily.yml missing: {token}"
    assert "yfinance" in (ROOT / "requirements_github.txt").read_text(encoding="utf-8"), (
        "yfinance missing from requirements_github.txt — Layer 3 VIX fetch will fall back"
    )


@_test("regression.after_close_daily_schedule")
def test_paper_executor_weekday() -> None:
    """after_close_daily.yml must have weekday after-close schedule plus a
    Saturday review pass. Live execution remains manual only.
    """
    wf = (ROOT / ".github" / "workflows" / "after_close_daily.yml").read_text(encoding="utf-8")
    assert "45 22 * * 1-5" in wf, "weekday after-close schedule missing"
    assert "0 6 * * 6" in wf, (
        "Saturday 06:00 UTC schedule must remain"
    )
    assert "execute=true" in wf, "manual live execution guard not documented"


@_test("regression.tactical_after_close_workflow")
def test_tactical_after_close_workflow() -> None:
    """Daily tactical alpha review must remain in the after-close workflow and
    call the separate tactical engine, not the core monthly rebuild.
    """
    wf_path = ROOT / ".github" / "workflows" / "after_close_daily.yml"
    assert wf_path.exists(), "after_close_daily.yml workflow missing"
    wf = wf_path.read_text(encoding="utf-8")
    assert "45 22 * * 1-5" in wf, "after-close weekday schedule missing"
    assert "r1000_tactical_alpha.py" in wf, "tactical workflow does not invoke tactical engine"
    assert "--mirror-cloud-results" in wf, "tactical results are not mirrored to cloud_results"
    req = (ROOT / "requirements_github.txt").read_text(encoding="utf-8")
    assert "pandas_market_calendars" in req, "NYSE holiday calendar dependency missing"


@_test("regression.advisor_v3_reads_cloud_scanner")
def test_advisor_v3_cloud_scanner_fallback() -> None:
    """Phase 5 K: advisor v3 load_scanner_rankings must check cloud_results/scanner/
    as fallback when local aggressive/state/scanner/ is empty (CI environment).
    """
    src = (ROOT / "r1000_rebalance_advisor_v3.py").read_text(encoding="utf-8")
    assert "cloud_results/scanner" in src, (
        "advisor v3 missing cloud_results/scanner fallback — "
        "scanner output won't reach advisor in CI"
    )


@_test("regression.advisor_v3_surfaces_layer4_suggestions")
def test_advisor_v3_layer4_info() -> None:
    """Phase 5 M: advisor v3 prints Layer 4 swap suggestions (informational
    only — does not auto-apply). Lets user see swap candidates in same review
    as advisor diff.
    """
    src = (ROOT / "r1000_rebalance_advisor_v3.py").read_text(encoding="utf-8")
    assert "from r1000_layer4_swap import layer4_swap_suggestions" in src, (
        "advisor v3 missing Layer 4 suggestions import"
    )
    assert "LAYER 4 SWAP suggestions" in src, (
        "advisor v3 missing Layer 4 print section"
    )


@_test("regression.monthly_ic_monitor_exists")
def test_monthly_ic_monitor() -> None:
    """Phase 6 L: tools/monthly_ic_monitor.py must remain wired through the
    consolidated monthly research workflow.

    User mandate (2026-04-25): "1-2개월 cadence가 훨씬 합리적".
    Threshold trips: ADR avg IC < 0.01, China-IC > US-IC by 0.05+.
    """
    script = ROOT / "tools" / "monthly_ic_monitor.py"
    assert script.exists(), "tools/monthly_ic_monitor.py missing"
    src = script.read_text(encoding="utf-8")
    for tok in ("compute_rank_ic", "telegram_send", "fetch_macro_series",
                "ALL_ADR_AVG_IC_THRESHOLD", "NEW_FEATURE_IC_DELTA_THRESHOLD",
                "load_adr_universe"):
        assert tok in src, f"monthly_ic_monitor.py missing: {tok}"

    wf = ROOT / ".github" / "workflows" / "monthly_research.yml"
    assert wf.exists(), "monthly_research.yml workflow missing"
    wf_src = wf.read_text(encoding="utf-8")
    for tok in ("45 22 15 * *", "monthly_ic_monitor.py", "TELEGRAM_BOT_TOKEN",
                "FRED_API_KEY", "tests/smoke_test.py --quick",
                "refresh_cycle_play_universe.py", "r1000_tactical_backtest.py",
                "build_explosive_pattern_db.py", "train_explosion_classifier.py"):
        assert tok in wf_src, f"monthly_research.yml missing: {tok}"


@_test("regression.workflow_topology_consolidated")
def test_workflow_topology_consolidated() -> None:
    """Scheduled automation is compressed by cadence so future system changes
    update one owner workflow instead of several stale duplicates.
    """
    wf_dir = ROOT / ".github" / "workflows"
    expected = {
        "after_close_daily.yml",
        "weekly_data_refresh.yml",
        "monthly_research.yml",
        "quarterly_auto_learning.yml",
        "full_rebuild_manual.yml",
        "unified_monthly.yml",
        "layer4_monthly_swap.yml",
        "gdrive_smoke_test.yml",
        "pr_validation.yml",
    }
    missing = sorted(name for name in expected if not (wf_dir / name).exists())
    assert not missing, f"missing consolidated workflows: {missing}"

    retired = {
        "daily_review.yml",
        "paper_executor_dryrun.yml",
        "tactical_after_close.yml",
        "macro_daily_snapshot.yml",
        "etf_leadership_daily.yml",
        "explosive_mover_daily.yml",
        "finnhub_weekly.yml",
        "theme_discovery.yml",
        "cycle_play_refresh.yml",
        "monthly_ic_monitor.yml",
        "tactical_backtest_monthly.yml",
        "explosive_pattern_train_monthly.yml",
        "quarterly_trade_insights.yml",
        "auto_feature_gate_proposal_quarterly.yml",
    }
    still_present = sorted(name for name in retired if (wf_dir / name).exists())
    assert not still_present, f"retired duplicate workflows still present: {still_present}"

    strategy = ROOT / "AUTOMATION_STRATEGY.md"
    assert strategy.exists(), "AUTOMATION_STRATEGY.md missing"
    text = strategy.read_text(encoding="utf-8")
    for token in ("Cadence Matrix", "after_close_daily.yml", "full_rebuild_manual.yml",
                  "update `tests/smoke_test.py`"):
        assert token in text, f"AUTOMATION_STRATEGY.md missing: {token}"


@_test("regression.helpers_imports_requests")
def test_helpers_imports_requests() -> None:
    """r1000_helpers.py:_http_get_inner uses requests.Response + requests.get
    but module-level `import requests` was missing in early refactor commits.

    Symptom: first cloud full_rebuild run with no historical_universe_membership
    cache hit IWB live fetch path -> http_get -> _http_get_inner -> NameError
    on `requests.Response`. Universe build failed, pipeline crashed, only logs
    were committed.

    Fixed 2026-04-26 by adding `import requests` at top of r1000_helpers.py.
    """
    src = (ROOT / "r1000_helpers.py").read_text(encoding="utf-8")
    assert re.search(r"^import requests\b", src, re.MULTILINE), (
        "r1000_helpers.py missing 'import requests' — _http_get_inner will "
        "NameError when called. Symptom seen on cloud full_rebuild first run."
    )


@_test("regression.workflows_pip_cache_dependency_path")
def test_workflows_pip_cache_path() -> None:
    """All workflows using actions/setup-python@v5 with cache:'pip' MUST also
    declare cache-dependency-path pointing to requirements_github.txt.

    Bug history (2026-04-26):
      Without this, setup-python tries default '**/requirements.txt or
      **/pyproject.toml' which doesn't exist in this repo (we use
      requirements_github.txt). All 8 workflows failed at "Setup Python"
      step with "No file matched" error before the user could even run
      the actual job logic.

    This guard ensures any future workflow added to .github/workflows/
    declares the right cache-dependency-path.
    """
    wf_dir = ROOT / ".github" / "workflows"
    if not wf_dir.exists():
        return
    bad = []
    for wf in sorted(wf_dir.glob("*.yml")):
        src = wf.read_text(encoding="utf-8")
        if "cache: 'pip'" in src:
            if "cache-dependency-path: requirements_github.txt" not in src:
                bad.append(wf.name)
    assert not bad, (
        f"Workflows use cache:'pip' but missing cache-dependency-path "
        f"(setup-python will fail): {bad}"
    )


@_test("regression.sync_cloud_to_drive_helper_exists")
def test_sync_cloud_to_drive() -> None:
    """tools/sync_cloud_to_drive.py bridges the gap between cloud_results/
    (where full_rebuild_manual.yml writes) and the local Drive mirror
    (where advisor / paper_executor / layer4_swap read by default).

    Without this helper, user must manually copy files after each cloud
    rebuild — which is error-prone and easy to skip.
    """
    p = ROOT / "tools" / "sync_cloud_to_drive.py"
    assert p.exists(), "tools/sync_cloud_to_drive.py missing"
    src = p.read_text(encoding="utf-8")
    for tok in ("DEFAULT_DRIVE_BASE", "SYNC_FILES", "--dry-run", "--drive-base",
                "scored_unified.csv", "concentrated_portfolio_latest.csv",
                "latest_"):
        assert tok in src, f"sync_cloud_to_drive.py missing: {tok}"


@_test("regression.full_rebuild_commits_portfolio_csvs")
def test_full_rebuild_commits_portfolios() -> None:
    """full_rebuild_manual.yml must commit the actual portfolio CSVs (not just
    scored + metrics). Without portfolio_latest.csv + concentrated_portfolio_latest.csv
    in cloud_results, paper_executor with --advisor concentrated/core can't run
    after cloud rebuild.

    Also asserts the latest_<mode> pointer directory creation so sync helper
    can find files without knowing exact date.
    """
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    for needed in (
        "portfolio_latest.csv",
        "concentrated_portfolio_latest.csv",
        "scored_unified.csv",
    ):
        assert needed in wf, f"full_rebuild_manual.yml missing: {needed}"
    assert (
        "latest_${{ inputs.universe_mode }}" in wf or "latest_$INPUT_UNIVERSE_MODE" in wf
    ), "full_rebuild_manual.yml missing latest_<universe_mode> pointer handling"


@_test("regression.full_rebuild_preserves_auto_learning_artifacts")
def test_full_rebuild_preserves_auto_learning_artifacts() -> None:
    """Phase 20: full rebuild must preserve the training substrate for
    automatic learning. If trade_journal/insights or the candidate gate YAML
    disappear after a cloud run, challenger promotion has no data to learn from.
    """
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    for needed in (
        "outputs/trade_journal/",
        "outputs/auto_learning/",
        "auto_feature_gates_candidate.yaml",
        "tools/trade_insights.py",
        'tools/feature_gate_proposal.py --gates-out "$CANDIDATE_GATES"',
        'tools/auto_learning_promote.py --dry-run --candidate-gates "$CANDIDATE_GATES"',
        "copy_if_exists",
    ):
        assert needed in wf, f"full_rebuild_manual.yml missing auto-learning artifact token: {needed}"


@_test("regression.full_rebuild_pushes_results_to_dispatch_branch")
def test_full_rebuild_pushes_results_to_dispatch_branch() -> None:
    """Full rebuild result commits must target the dispatched branch.

    The Phase 20 branch rebuild succeeded but its cloud_results commit failed
    because the workflow retried by rebasing a branch run onto master. That is
    wrong for branch validation and can also mask the failure because the step
    is intentionally best-effort.
    """
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert 'RESULT_BRANCH="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME:-}}"' in wf
    assert "refs/heads/${RESULT_BRANCH}:refs/remotes/origin/${RESULT_BRANCH}" in wf
    assert 'git push origin "HEAD:$RESULT_BRANCH"' in wf
    commit_section = wf.split("Commit verdict + portfolio CSVs", 1)[-1]
    assert "git fetch origin master" not in commit_section
    assert "git pull --rebase origin master" not in commit_section


@_test("regression.phase18c_auto_learning_gate_wired")
def test_phase18c_auto_learning_gate_wired() -> None:
    """Phase 20: learned gates apply only when a separately reviewed active
    YAML exists; no YAML remains a no-op. scored_latest must keep
    explosion/regime audit columns even when they are all zero.
    """
    pipe_src = _pipeline_src()
    for token in (
        "apply_phase18c_gates_to_frame",
        "explosion_entry_score",
        "explosion_exit_score",
        "explosion_net_score",
        "applied_gates_count",
        "pattern_blocked",
    ):
        assert token in pipe_src, f"r1000_pipeline.py missing auto-learning wiring: {token}"
    promote = ROOT / "tools" / "auto_learning_promote.py"
    assert promote.exists(), "tools/auto_learning_promote.py missing"
    promote_src = promote.read_text(encoding="utf-8")
    for token in (
        "candidate_gates",
        "active_gates",
        "concentrated_cagr_floor",
        "min_trades",
        '"automatic_promotion_allowed": False',
        '"proposal_only": True',
        '"promoted": False',
    ):
        assert token in promote_src, f"auto_learning_promote.py missing gate token: {token}"
    assert "shutil.copy2" not in promote_src
    for workflow_name in ("quarterly_auto_learning.yml", "full_rebuild_manual.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "promote_live" not in workflow
        assert "auto_learning_promote.py --dry-run" in workflow


@_test("regression.alphaops_report_only_outputs_wired")
def test_alphaops_report_only_outputs_wired() -> None:
    """AlphaOps Stage 0-2 must remain report-only.

    The reports provide baseline registry, config audit, and orchestrator shadow
    targets for A/B governance. They must be exported and preserved by the full
    rebuild workflow, but they must not replace portfolio_latest.csv.
    """
    reporting = ALPHAOPS_REPORTING_PATH.read_text(encoding="utf-8")
    for token in (
        "write_baseline_registry",
        "write_config_audit",
        "write_orchestrator_shadow_outputs",
        "write_alphaops_report_pack",
        "active_auto_feature_gates_exists",
    ):
        assert token in reporting, f"r1000_alphaops_reporting.py missing: {token}"

    orchestrator = (ROOT / "r1000_orchestrator.py").read_text(encoding="utf-8")
    for token in ("write_orchestrator_output_bundle", "orchestrator_result_to_frame", "row_type"):
        assert token in orchestrator, f"r1000_orchestrator.py missing CSV bundle token: {token}"

    pipe_src = _pipeline_src()
    assert "write_alphaops_report_pack" in pipe_src, "pipeline does not write AlphaOps reports"
    assert "portfolio_latest.to_csv" not in reporting, "AlphaOps reporting must not write production portfolio_latest.csv"

    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    for token in (
        "outputs/orchestrator/",
        "outputs/reports/baseline_registry.*",
        "outputs/reports/config_audit.*",
        "outputs/orchestrator",
    ):
        assert token in wf, f"full_rebuild_manual.yml missing AlphaOps artifact token: {token}"


@_test("logic.alphaops_adr_diagnostics_detect_universe_source")
def test_alphaops_adr_diagnostics() -> None:
    """AlphaOps baseline registry must count ADR rows from universe_source.

    Cloud scored_latest currently exposes ADR membership through
    universe_source=adr_whitelist and adr_global_alpha_fallback_pass, not a
    generic is_adr column.
    """
    import pandas as pd
    from r1000_alphaops_reporting import _scored_diagnostics

    scored = pd.DataFrame({
        "ticker": ["TSM", "NVDA", "ZTO"],
        "universe_source": ["adr_whitelist", "current_constituents_proxy", "adr_whitelist"],
        "adr_global_alpha_fallback_pass": [True, False, True],
        "regime_state": ["neutral", "neutral", "neutral"],
    })
    portfolio = pd.DataFrame({"ticker": ["TSM", "NVDA"], "weight": [0.08, 0.12]})
    diag = _scored_diagnostics(scored, portfolio)
    assert diag["adr_rows"] == 2, diag
    assert diag["adr_selected_count"] == 1, diag
    assert "adr_global_alpha_fallback_pass" in diag["adr_indicator_columns"], diag


@_test("regression.regime_low_support_growth_prefers_learned_fallback")
def test_regime_low_support_growth_prefers_learned_fallback() -> None:
    """Low-sample learned growth winners fall back to high-support learned maps.

    Regression: a 7-month growth_reentry_alert sample learned core_only and
    overrode the manual growth map, cutting future/early exposure in live runs.
    The exact learned map is too small to trust, but the untested manual growth
    map should not beat a high-support learned balanced fallback.
    """
    import r1000_pipeline as pipe
    from r1000_config import EngineConfig, default_manual_regime_conditioned_sleeve_map

    cfg = EngineConfig()
    assert int(cfg.regime_conditioned_min_learned_months) >= 12
    learned = {
        "growth_reentry_alert": {
            "core": 1.0,
            "future": 0.0,
            "early": 0.0,
            "cash": 0.0,
            "policy_label": "core_only",
            "months": 7,
        },
        "balanced": {
            "core": 0.35,
            "future": 0.30,
            "early": 0.35,
            "cash": 0.0,
            "policy_label": "aggr_35_30_35",
            "months": 64,
        },
        "ALL": {
            "core": 0.35,
            "future": 0.30,
            "early": 0.35,
            "cash": 0.0,
            "policy_label": "aggr_35_30_35",
            "months": 83,
        },
    }
    selected, meta = pipe.resolve_regime_policy_selection(
        "growth_reentry_alert",
        learned_regime_map=learned,
        manual_regime_map=default_manual_regime_conditioned_sleeve_map(),
        min_learned_months=cfg.regime_conditioned_min_learned_months,
    )
    assert selected is not None
    assert str(selected["policy_label"]) == "aggr_35_30_35", selected
    assert meta["lookup_source"] == "learned", meta
    assert meta["lookup_label"] == "balanced", meta
    assert meta["manual_fallback_deferred"], meta


@_test("regression.regime_low_support_risk_uses_manual_safety")
def test_regime_low_support_risk_uses_manual_safety() -> None:
    """Risk-off labels keep manual safety maps when learned samples are thin."""
    import r1000_pipeline as pipe
    from r1000_config import EngineConfig, default_manual_regime_conditioned_sleeve_map

    cfg = EngineConfig()
    learned = {
        "risk_off_alert": {
            "core": 0.40,
            "future": 0.40,
            "early": 0.20,
            "cash": 0.0,
            "policy_label": "growth_40_40_20",
            "months": 9,
        },
        "balanced": {
            "core": 0.35,
            "future": 0.30,
            "early": 0.35,
            "cash": 0.0,
            "policy_label": "aggr_35_30_35",
            "months": 64,
        },
    }
    selected, meta = pipe.resolve_regime_policy_selection(
        "risk_off_alert",
        learned_regime_map=learned,
        manual_regime_map=default_manual_regime_conditioned_sleeve_map(),
        min_learned_months=cfg.regime_conditioned_min_learned_months,
    )
    assert selected is not None
    assert str(selected["policy_label"]).startswith("manual_riskoff"), selected
    assert meta["lookup_source"] == "manual", meta
    assert meta["lookup_label"] == "risk_off_alert", meta


@_test("regression.regime_guardrail_treats_cash_as_separate_sleeve")
def test_regime_guardrail_treats_cash_as_separate_sleeve() -> None:
    """Guardrails operate on equity sleeve fractions, not equity * (1-cash)."""
    import r1000_pipeline as pipe
    from r1000_config import default_manual_regime_conditioned_sleeve_map

    manual = pipe.normalize_regime_conditioned_sleeve_map(
        default_manual_regime_conditioned_sleeve_map(),
        fallback_source="manual",
    )
    selected = manual["growth_reentry_alert"]
    guarded, meta = pipe.apply_regime_policy_guardrails("growth_reentry_alert", selected)
    assert guarded is not None
    assert not meta["guardrail_applied"], (guarded, meta)
    assert abs(float(guarded["core"]) - float(selected["core"])) < 1e-12
    assert abs(float(guarded["future"]) - float(selected["future"])) < 1e-12
    assert abs(float(guarded["early"]) - float(selected["early"])) < 1e-12
    assert abs(float(guarded["cash"]) - float(selected["cash"])) < 1e-12


@_test("regression.run_local_full_defers_broker_verdict_to_sidecar")
def test_run_local_full_defers_broker_verdict_to_sidecar() -> None:
    """`run_local.py --full` must NOT enforce broker verdicts inline.

    Failure-class regression guard (run 27445937281, 2026-06-13): in full-run
    workflow the broker-replay sidecar runs as a SEPARATE step AFTER
    run_local.py exits. Run 28074476465 showed the same false-failure mode when
    restored cache left stale broker metrics on disk: path-existence checks
    allowed print_broker_verdict to run too early and fail the "Run FULL
    rebuild" step under set -o pipefail. The deferral block must:
      - only activate under --full (verdict-only and QUICK_RESCORE still gate)
      - return 0 unconditionally for --full after the pipeline completes
      - print an informational DEFERRED banner, not silently swallow real
        verdict output
    """
    src = (ROOT / "run_local.py").read_text(encoding="utf-8")
    assert "BROKER-LEDGER VERDICT -- DEFERRED TO SIDECAR STEP" in src, (
        "deferral banner missing; verdict cannot be deferred without it"
    )
    # The block must gate on args.full so QUICK_RESCORE and --verdict-only
    # still enforce the broker gate. All three broker-evidence paths must be
    # checked together — partial presence (e.g. only main metrics) must still
    # defer rather than fail.
    verdict_start = src.index("# ---------- Step 3: verdict ----------")
    verdict_end = src.index(
        "return print_verdict(base_dir, gate_mode=args.gate_mode)",
        verdict_start,
    )
    deferral_block = src[verdict_start:verdict_end]
    assert "if args.full:" in deferral_block, "deferral must be gated on args.full"
    assert "return 0" in deferral_block, "full-run deferral must return success"
    assert "all(p.exists() for p in broker_paths)" not in deferral_block, (
        "full-run deferral must not depend on stale broker path existence"
    )


@_test("regression.operating_minimal_builds_long_crisis_substrate")
def test_operating_minimal_builds_long_crisis_substrate() -> None:
    """`operating_minimal` sidecar profile must build crisis substrate before
    AlphaOps vNext production runs.

    Crisis-defense regression guard (run 27445937281, 2026-06-13): without
    `outputs/crisis_signals/daily_features.parquet` and
    `outputs/long_crisis_learning/best_thresholds.json` on disk before
    `run_alphaops_vnext_policy_replay.py` executes, the vNext builder writes
    `long_crisis_score=0.0` / `cash_gate_reason='missing_long_crisis_features'`
    into `daily_crisis_state.csv` for every date through COVID and 2022. The
    2-confirmation cash-raise gate (price stress + at least one of
    liquidity/trend/credit) cannot open with all confirmation signals at 0.0,
    so broker-replay MaxDD stays on the unhedged path.

    The sidecar script must:
      - build crisis_signals/daily_features.parquet (if missing) BEFORE vnext
      - invoke build_long_crisis_inputs BEFORE run_alphaops_vnext_production
      - do all of the above inside the operating_minimal branch, not only the
        official branch
    """
    src = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    # Find the operating_minimal/official branch.
    branch_marker = 'if [ "$SIDECAR_PROFILE" = "operating_minimal" ] || [ "$SIDECAR_PROFILE" = "official" ]; then'
    assert branch_marker in src, "operating_minimal/official combined branch missing"
    branch_idx = src.index(branch_marker)
    # Find the vnext CALL inside the operating_minimal/official branch — not
    # the function definition near the top of the file ("run_alphaops_vnext_production() {").
    import re
    vnext_call_match = re.search(
        r"^\s*run_alphaops_vnext_production\s*$",
        src[branch_idx:],
        flags=re.MULTILINE,
    )
    assert vnext_call_match, "run_alphaops_vnext_production call missing after operating_minimal branch"
    vnext_idx = branch_idx + vnext_call_match.start()
    csig_idx = src.find("run_crisis_signal_builder.py", branch_idx, vnext_idx)
    long_idx = src.find("build_long_crisis_inputs", branch_idx, vnext_idx)
    assert csig_idx != -1, (
        f"crisis_signal_builder must run between operating_minimal branch start "
        f"({branch_idx}) and run_alphaops_vnext_production call ({vnext_idx})"
    )
    assert long_idx != -1, (
        f"build_long_crisis_inputs must run between operating_minimal branch start "
        f"({branch_idx}) and run_alphaops_vnext_production call ({vnext_idx})"
    )
    # Both substrate steps must be inside the COMBINED branch (so
    # operating_minimal benefits), not only inside the inner official-only block.
    inner_official_marker = 'if [ "$SIDECAR_PROFILE" = "official" ]; then'
    inner_official_idx = src.find(inner_official_marker, branch_idx + len(branch_marker))
    if inner_official_idx != -1:
        assert csig_idx < inner_official_idx, "crisis_signal_builder leaked into official-only branch"
        assert long_idx < inner_official_idx, "build_long_crisis_inputs leaked into official-only branch"


@_test("regression.operating_minimal_runs_daily_stop_position_risk_replay")
def test_operating_minimal_runs_daily_stop_position_risk_replay() -> None:
    """Daily-stop next-close ledger must run in `operating_minimal`, not only
    `official` (Family A option-a, daily position stop).

    `run_broker_position_risk_replay.py` walks daily closes between monthly
    rebalances and fires hard/trailing/relative stops, then fills risk exits at
    the next close. Its MaxDD is the production-grade, directly-comparable
    counterpart to the plain `broker_replay` (monthly next-close) MaxDD. It used
    to be gated behind `SIDECAR_PROFILE = official`, so the fast A/B arms we run
    (operating_minimal) never produced it and the daily-stop drawdown reduction
    could not be measured. It must now run in the combined operating_minimal/
    official branch BEFORE the inner official-only block, with stop levels driven
    by env overrides (R1000_DAILY_STOP_*) so challenger runs can sweep tightness.
    The parabolic variant stays official-only.
    """
    src = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    branch_marker = 'if [ "$SIDECAR_PROFILE" = "operating_minimal" ] || [ "$SIDECAR_PROFILE" = "official" ]; then'
    branch_idx = src.index(branch_marker)
    inner_official_marker = 'if [ "$SIDECAR_PROFILE" = "official" ]; then'
    inner_official_idx = src.find(inner_official_marker, branch_idx + len(branch_marker))
    assert inner_official_idx != -1, "inner official-only block missing"

    # The main+concentrated default-param position-risk replays must appear
    # inside the combined branch but BEFORE the inner official-only gate.
    main_call = src.find(
        "run_broker_position_risk_replay.py --target-book outputs/reports/operating_main_target_book.csv",
        branch_idx,
    )
    assert main_call != -1, "main broker_position_risk_replay call missing"
    assert main_call < inner_official_idx, (
        "main broker_position_risk_replay must run in operating_minimal, not "
        "only official"
    )
    conc_call = src.find(
        "run_broker_position_risk_replay.py --target-book outputs/reports/operating_concentrated_target_book.csv",
        branch_idx,
    )
    assert conc_call != -1, "concentrated broker_position_risk_replay call missing"
    assert conc_call < inner_official_idx, (
        "concentrated broker_position_risk_replay must run in operating_minimal"
    )

    # Stop levels must be env-overridable so experiment_env_json can sweep them.
    for env_key in (
        "R1000_DAILY_STOP_HARD_STOP",
        "R1000_DAILY_STOP_TRAILING_STOP",
        "R1000_DAILY_STOP_TRAILING_ACTIVATION",
    ):
        assert env_key in src, f"daily-stop env override {env_key} missing"

    # The parabolic stress variant must stay official-only (it intentionally
    # disables the real stops; promoting it to minimal would pollute the
    # comparison).
    parabolic_call = src.find("main_broker_parabolic_risk_replay")
    assert parabolic_call != -1, "parabolic variant missing"
    assert parabolic_call > inner_official_idx, (
        "parabolic variant must stay inside the official-only block"
    )


@_test("logic.concentrated_gross_cap_override_is_default_inert")
def test_concentrated_gross_cap_override_is_default_inert() -> None:
    """Working Family-B lever: relax the concentrated benchmark-guard gross cap.

    `benchmark_guard_signal` throttles concentrated gross ~15pp harder than main
    at every benchmark-risk tier, which is the real source of concentrated's
    ~42% average cash (not the dead `concentrated_regime_cash_vix_threshold`).
    `concentrated_gross_cap_override` exposes R1000_CONC_GROSS_CAP_FLOOR / _SCALE
    so a challenger can lift the concentrated gross schedule via
    experiment_env_json. Defaults must be inert, overrides must clamp to [0, 1],
    and the wiring must apply to concentrated only (main untouched).
    """
    import importlib
    import os as _os

    mle = importlib.import_module("r1000_market_leader_engine")
    keys = ("R1000_CONC_GROSS_CAP_FLOOR", "R1000_CONC_GROSS_CAP_SCALE")
    saved = {k: _os.environ.get(k) for k in keys}
    try:
        for k in keys:
            _os.environ.pop(k, None)
        # default inert: pass-through, clamped to [0, 1]
        assert mle.concentrated_gross_cap_override(0.55) == 0.55
        assert mle.concentrated_gross_cap_override(1.0) == 1.0
        assert mle.concentrated_gross_cap_override(0.25) == 0.25

        # floor raises only the tiers below it; tiers at/above are untouched
        _os.environ["R1000_CONC_GROSS_CAP_FLOOR"] = "0.70"
        assert abs(mle.concentrated_gross_cap_override(0.25) - 0.70) < 1e-9
        assert abs(mle.concentrated_gross_cap_override(0.55) - 0.70) < 1e-9
        assert abs(mle.concentrated_gross_cap_override(0.85) - 0.85) < 1e-9
        assert abs(mle.concentrated_gross_cap_override(1.0) - 1.0) < 1e-9
        _os.environ.pop("R1000_CONC_GROSS_CAP_FLOOR", None)

        # scale multiplies, clamped at 1.0
        _os.environ["R1000_CONC_GROSS_CAP_SCALE"] = "1.2"
        assert abs(mle.concentrated_gross_cap_override(0.70) - 0.84) < 1e-9
        assert mle.concentrated_gross_cap_override(0.90) == 1.0  # 1.08 clamped
        _os.environ.pop("R1000_CONC_GROSS_CAP_SCALE", None)

        # malformed values fall back to inert defaults
        _os.environ["R1000_CONC_GROSS_CAP_FLOOR"] = "not_a_number"
        assert mle.concentrated_gross_cap_override(0.55) == 0.55
    finally:
        for k, v in saved.items():
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v

    # Wiring: the override must apply to concentrated only, after the gross
    # schedule is chosen and before the signal dict is returned.
    src = (ROOT / "r1000_market_leader_engine.py").read_text(encoding="utf-8")
    guard_idx = src.find("def benchmark_guard_signal(")
    assert guard_idx != -1, "benchmark_guard_signal missing"
    wire_idx = src.find('if portfolio_kind == "concentrated":', guard_idx)
    call_idx = src.find("concentrated_gross_cap_override(gross)", guard_idx)
    ret_idx = src.find('"gross_exposure_cap": gross', guard_idx)
    assert wire_idx != -1 and call_idx != -1, "concentrated gross override not wired"
    assert wire_idx < call_idx < ret_idx, "override must run before the returned gross"


@_test("logic.lever_sweep_builds_isolated_commands")
def test_lever_sweep_builds_isolated_commands() -> None:
    """The lever-sweep harness measures a grid in one run (efficiency fix).

    conc-gross floor and daily-stop levers act only at the target-book/replay
    stage, so `run_lever_sweep.py` reuses one rebuild's scored output to score a
    whole grid instead of paying a ~3-4h rebuild per value. Verify the pure
    command builders: parsing dedups/sanitizes, conc-gross runs vNext in
    shadow_only (never replace_operating) and points the broker replay at the
    produced concentrated variant book, and daily-stop only passes --hard-stop /
    --trailing-stop when a non-default pair is given.
    """
    import importlib
    from pathlib import Path as _Path

    sweep = importlib.import_module("tools.run_lever_sweep")

    assert sweep.parse_float_list("0.0, 0.7, 0.7, 0.8") == [0.0, 0.7, 0.8]
    grid = sweep.parse_daily_stop_grid("default,-0.10:-0.15,default")
    assert grid[0] == ("default", None, None)
    assert grid[1][1] == -0.10 and grid[1][2] == -0.15
    assert len(grid) == 2, "duplicate labels must be dropped"

    vnext_cmd, broker_cmd, book = sweep.conc_gross_commands(
        0.7,
        latest_run="outputs",
        candidate_book="outputs/reports/candidate_replay_book.csv",
        price_cache="cache_prices",
        out_dir=_Path("outputs/lever_sweep/conc_gross_floor_0p7"),
        concentrated_target_n=5,
        cost_bps=25.0,
        max_fill_lag_days=7,
    )
    assert "--production-output-mode" in vnext_cmd
    assert vnext_cmd[vnext_cmd.index("--production-output-mode") + 1] == "shadow_only"
    assert "replace_operating" not in vnext_cmd, "sweep must never replace operating books"
    assert "concentrated_N5_target_book.csv" in book
    assert book in broker_cmd, "broker replay must score the produced variant book"
    assert broker_cmd[broker_cmd.index("--portfolio-kind") + 1] == "concentrated"
    control_env = sweep.conc_gross_env({"PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED": "1"}, 0.0)
    assert control_env["R1000_CONC_GROSS_CAP_FLOOR"] == "0.0"
    assert control_env["PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED"] == "0", "control arm must not inherit enabled phase"
    assert control_env["PHASE_BULL_FLOOR_ENABLED"] == "0"
    tuned_env = sweep.conc_gross_env({}, 0.7)
    assert tuned_env["R1000_CONC_GROSS_CAP_FLOOR"] == "0.7"
    assert tuned_env["PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED"] == "1", "non-control floor arm must enable vNext bull floor"
    assert tuned_env["PHASE_BULL_FLOOR_ENABLED"] == "0"

    default_cmd = sweep.daily_stop_command(
        "default", None, None,
        portfolio_kind="main", target_book="outputs/reports/operating_main_target_book.csv",
        price_cache="cache_prices", out_dir=_Path("outputs/lever_sweep/daily_stop_default"),
        cost_bps=25.0, max_fill_lag_days=7,
    )
    assert "--hard-stop" not in default_cmd and "--trailing-stop" not in default_cmd
    tuned_cmd = sweep.daily_stop_command(
        "t", -0.10, -0.15,
        portfolio_kind="concentrated", target_book="outputs/reports/operating_concentrated_target_book.csv",
        price_cache="cache_prices", out_dir=_Path("outputs/lever_sweep/daily_stop_t"),
        cost_bps=25.0, max_fill_lag_days=7,
    )
    assert tuned_cmd[tuned_cmd.index("--hard-stop") + 1] == "-0.1"
    assert tuned_cmd[tuned_cmd.index("--trailing-stop") + 1] == "-0.15"

    # missing metrics file must not raise
    assert sweep.read_metrics(_Path("does/not/exist.json"))["status"] == "missing"

    # sidecar wiring: opt-in only, never on by default
    src = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    assert 'if [ "${R1000_LEVER_SWEEP:-0}" = "1" ]; then' in src, "lever sweep must be opt-in"
    assert "tools/run_lever_sweep.py" in src

    # delivery plumbing: sweep results must be committed to cloud_results (not
    # only stranded in the blob-hosted artifact), and concurrent same-day A/B
    # arms must not clobber each other's dated dir.
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert 'copy_dir_clean outputs/lever_sweep "$DEST/lever_sweep"' in wf, "lever_sweep must be copied into committed cloud_results"
    assert "${GITHUB_RUN_ID}_$INPUT_UNIVERSE_MODE" in wf, "dated cloud_results dir must include run id (concurrent A/B clobber guard)"

    # fail-loud guard: a silent no-op (R1000_LEVER_SWEEP=1 but no output) must be
    # surfaced in the log, not swallowed by `|| true`.
    assert "[lever-sweep][guard]" in src, "sidecar must emit a fail-loud guard line for the lever sweep"

    # robustness: main() must always leave a summary.json behind — even with no
    # arms — so a killed harness is never a silent no-op. Exercise via --dry-run
    # (no subprocess, no real data needed) in an isolated temp output dir.
    import json as _json
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as _td:
        rc = sweep.main([
            "--output-dir", str(_Path(_td) / "ls"),
            "--conc-gross-floors", "0.0,0.8",
            "--daily-stop-grid", "default,-0.10:-0.15",
            "--dry-run",
        ])
        assert rc == 0
        _summary_path = _Path(_td) / "ls" / "summary.json"
        assert _summary_path.is_file(), "main() must always write summary.json"
        _s = _json.loads(_summary_path.read_text(encoding="utf-8"))
        assert _s["status"] == "ok", f"dry-run status should be ok, got {_s.get('status')}"
        assert _s.get("errors") == {}, "dry-run must record no errors"
        assert len(_s["conc_gross_floor"]) == 2 and len(_s["daily_stop"]) == 2

        # no-arm run still leaves a valid summary (never an empty dir)
        rc2 = sweep.main([
            "--output-dir", str(_Path(_td) / "ls2"),
            "--skip-conc-gross", "--skip-daily-stop", "--dry-run",
        ])
        assert rc2 == 0
        assert (_Path(_td) / "ls2" / "summary.json").is_file(), "no-arm run must still write summary.json"


@_test("regression.replay_cache_start_covers_official_window")
def test_replay_cache_start_covers_official_window() -> None:
    """The replay price cache must start early enough to realize a >=7.0y window.

    Root cause of the broker-ledger 6.965y < 7.0y acceptance-gate miss: the cache
    auto-start was min_dt(books)-14d (~2019-06-14), so the first monthly fill
    snapped to 2019-07-01. build_replay_price_cache now floors the auto-start to
    OFFICIAL_BACKTEST_START_DATE - warmup so the first month-end rebalance is
    2019-05-31 -> fill ~2019-06-03 -> ~7.04y, inside the [7.0, 7.05] band that
    also keeps the pit-universe-label gate moot.
    """
    import importlib
    import pandas as pd

    b = importlib.import_module("tools.build_replay_price_cache")
    floor = pd.Timestamp(b._OFFICIAL_BACKTEST_START_DATE).normalize() - pd.Timedelta(days=b.OFFICIAL_START_WARMUP_DAYS)
    # must cover the official start with warmup, and not overshoot past the band
    # that re-triggers the pit gate (start <= 2019-04-30 -> ~7.13y).
    assert floor <= pd.Timestamp("2019-05-31"), "cache must cover the 2019-05-31 first rebalance"
    assert floor > pd.Timestamp("2019-04-30"), "cache start must not overshoot into the >7.05y pit-gate band"
    # an incremental run (recent book min_dt) must snap back to the official floor
    derived = pd.Timestamp("2019-06-28") - pd.Timedelta(days=14)
    assert min(derived, floor) == floor, "incremental cache build must floor to the official window"
    # a fresh 8y run must be unaffected (its derived start is earlier than the floor)
    fresh = (pd.Timestamp("2026-06-23") - pd.DateOffset(years=8)) - pd.Timedelta(days=14)
    assert min(fresh, floor) == fresh, "fresh 8y cache build must be unaffected"


@_test("logic.latest_month_mktcap_starvation_guard")
def test_latest_month_mktcap_starvation_guard() -> None:
    """Universe-collapse guard for the latest snapshot (run 27337807588).

    A cold-cache full rebuild joined shares for historical months but left the
    latest month ~98% NaN mktcap, collapsing the scored universe to 4 names.
    `latest_month_mktcap_coverage` must report the latest-month mask and its
    coverage separately so build_universe_monthly can retry the bounded Yahoo
    proxy / fall back to dollar-vol ranking for that month only.
    """
    if _args.quick:
        return
    import pandas as pd
    import r1000_pipeline as pipe

    starved = pd.DataFrame(
        {
            "rebalance_date": ["2026-05-29"] * 4 + ["2026-06-11"] * 4,
            "ticker": ["A", "B", "C", "D"] * 2,
            "mktcap": [1e10, 2e10, 3e10, 4e10, None, None, None, 5e10],
        }
    )
    mask, cov = pipe.latest_month_mktcap_coverage(starved)
    assert int(mask.sum()) == 4, f"latest-month mask wrong: {int(mask.sum())}"
    assert abs(cov - 0.25) < 1e-9, f"starved coverage wrong: {cov}"
    assert set(starved.loc[mask, "rebalance_date"]) == {"2026-06-11"}

    healthy = starved.copy()
    healthy["mktcap"] = 1e10
    _, cov_healthy = pipe.latest_month_mktcap_coverage(healthy)
    assert cov_healthy == 1.0, f"healthy coverage wrong: {cov_healthy}"

    empty_mask, empty_cov = pipe.latest_month_mktcap_coverage(pd.DataFrame())
    assert empty_cov == 1.0 and int(empty_mask.sum()) == 0

    # The guard must be wired into build_universe_monthly: proxy retry for the
    # starved latest month plus a dollar-vol fallback that keeps the month
    # rankable instead of dropping it.
    src = (ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    assert "latest_month_mktcap_coverage(monthly)" in src, "guard not wired into build_universe_monthly"
    assert "latest_month_dollar_vol_fallback" in src, "dollar-vol fallback for starved latest month missing"
    assert "mktcap_available = mktcap_available | latest_month_mask" in src, (
        "base_mask must keep latest-month rows when the dollar-vol fallback is active"
    )


@_test("regression.paper_executor_advisor_path_fallbacks")
def test_paper_executor_path_fallbacks() -> None:
    """ADVISOR_PATHS for concentrated/core must accept fallback paths so the
    cloud workflow can find files without relying on user's local Drive mount.
    """
    src = (ROOT / "r1000_paper_executor.py").read_text(encoding="utf-8")
    # Must be a list-of-paths structure now, with cloud_results fallback
    assert "cloud_results/full_rebuild/latest_" in src, (
        "paper_executor missing cloud_results fallback for concentrated/core advisor"
    )
    assert '"core":' in src and '"concentrated":' in src, "paper_executor advisor entries missing"


@_test("regression.compare_adr_backtest_helper_exists")
def test_compare_adr_backtest() -> None:
    """tools/compare_adr_backtest.py provides A/B verdict against ship gate
    for r1000+adr universe runs vs R1000-only baseline.

    Used to validate Phase 14 + ADR universe before rotating CURRENT_BASELINE
    in run_local.py.
    """
    p = ROOT / "tools" / "compare_adr_backtest.py"
    assert p.exists(), "tools/compare_adr_backtest.py missing"
    src = p.read_text(encoding="utf-8")
    for tok in ("SHIP_GATE", "delta_cagr_min_pp", "delta_sharpe_min",
                "delta_max_dd_min_pp", "def verdict", "use-pinned-baseline"):
        assert tok in src, f"compare_adr_backtest.py missing: {tok}"


@_test("regression.layer4_executor_safety_guards")
def test_layer4_executor_guards() -> None:
    """r1000_layer4_swap.py --execute path must have all safety guards:
      - 30-day throttle (HISTORY_PATH state file)
      - swap_max_per_cycle cap (already in RiskConfig)
      - refuse on small portfolio (<5 positions)
      - Telegram alert pre + post execute
      - --confirm bypass for CI

    User mandate (2026-04-25): "B = max 2 swap/month + 즉시 자동 실행 (paper only)".
    """
    src = (ROOT / "r1000_layer4_swap.py").read_text(encoding="utf-8")
    assert "THROTTLE_DAYS" in src, "30-day throttle constant missing"
    assert "_filter_throttled" in src, "throttle filter function missing"
    assert "_telegram_send" in src, "Telegram alert helper missing"
    assert "def execute_swaps" in src, "execute_swaps() function missing"
    assert "--execute" in src and "--confirm" in src, "execute/confirm CLI flags missing"
    # Must check portfolio size before executing
    assert "len(existing) < 5" in src or "portfolio too small" in src, (
        "portfolio size guard missing — could swap on dangerously concentrated book"
    )


@_test("regression.layer4_monthly_workflow_exists")
def test_layer4_monthly_workflow() -> None:
    """layer4_monthly_swap.yml must stay proposal/dry-run by default, while
    preserving manual execution wiring.
    """
    wf_path = ROOT / ".github" / "workflows" / "layer4_monthly_swap.yml"
    assert wf_path.exists(), "layer4_monthly_swap.yml missing"
    wf = wf_path.read_text(encoding="utf-8")
    for token in (
        "schedule:",
        "45 22 5 * *",
        "workflow_dispatch:",
        "default: false",
        "secrets.ALPACA_API_KEY",
        "secrets.TELEGRAM_BOT_TOKEN",
        "r1000_layer4_swap.py",
    ):
        assert token in wf, f"layer4_monthly_swap.yml missing: {token}"


@_test("regression.full_rebuild_workflow_exists")
def test_full_rebuild_workflow() -> None:
    """full_rebuild_manual.yml must be manual-only and fail closed before
    spending runner time unless exact approval evidence is supplied.  It must
    retain the existing engine inputs and ENGINE_REUSE_VERSION sensitivity.

    User mandate (2026-04-25): "둘 다" — both local + GitHub Actions paths
    for FULL rebuild so user PC isn't a single point of failure.
    """
    wf_path = ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"
    assert wf_path.exists(), "full_rebuild_manual.yml workflow missing"
    wf = wf_path.read_text(encoding="utf-8")
    trigger_block = wf.split("permissions:", 1)[0]
    for forbidden_trigger in ("schedule:", "cron:", "workflow_call:", "workflow_run:", "repository_dispatch:"):
        assert forbidden_trigger not in trigger_block, (
            f"full rebuild automatic trigger must stay removed: {forbidden_trigger}"
        )
    approval_inputs = trigger_block.split("universe_mode:", 1)[0]
    assert approval_inputs.count("required: true") == 5, "all five pre-universe approval inputs must be required"
    decision_input = trigger_block.split("decision_time_utc:", 1)[1].split(
        "backtest_years:", 1
    )[0]
    assert "required: true" in decision_input, "decision_time_utc must be required"
    assert wf.index("Validate explicit fullrun approval") < wf.index("Free disk space on runner"), (
        "fullrun approval must be checked before any material runner work"
    )
    for token in (
        "workflow_dispatch",
        "approval_token",
        "FULLRUN_APPROVED",
        "approved_commit_sha",
        "approved_source_manifest_sha256",
        "approved_source_manifest_path",
        "expected_cost_minutes",
        "INPUT_DECISION_TIME_UTC",
        "decision_time_utc cannot be in the future",
        "Validate explicit fullrun approval",
        "Resolve approved fullrun market session",
        "run_daily_market_session_gate.py",
        '--end-date "$LAST_NYSE_SESSION_DATE"',
        "--target-book-scope operating",
        "approved_commit_sha does not match the dispatched GITHUB_SHA",
        "production portfolio policy is outside the approved research scope",
        "github.event_name == 'workflow_dispatch'",
        "group: full-rebuild-manual",
        "default: integrated_shadow",
        "universe_mode",
        "backtest_years",
        "skip_collector",
        "leader_rescue_mode",
        "UNIVERSE_MODE",
        "BACKTEST_YEARS",
        "LEADER_RESCUE_MODE",
        "PHASE_PHASE14_HYBRID_ALPHA_ENABLED",
        "secrets.ALPACA_API_KEY",
        "secrets.FINNHUB_API_KEY",
        "tests/smoke_test.py",
        "ENGINE_REUSE_VERSION",
        "leader_rescue_backtest_filter_summary.json",
        "run_local.py --full",
    ):
        assert token in wf, f"full_rebuild_manual.yml missing required token: {token}"


@_test("regression.phase14_hybrid_alpha_in_default_features")
def test_phase14_in_default_features() -> None:
    """PHASE14_HYBRID_ALPHA_COLUMNS must be in cfg.DEFAULT_FEATURES so the
    walk-forward ML model trains on these signals.

    History (2026-04-25):
      - 6 columns: rs_acceleration_score (T4 +10%), h1_oversold_value_score
        (Opus H1 +8.67%), h6_dynamic_leader_score (Opus H6 +7.38%),
        stage2_overext_penalty (T1 -2.5% protection),
        theme_phase_multiplier_{primary,max} (themes.yaml phase classifier).
      - ENGINE_REUSE_VERSION must reflect the schema change so cache
        invalidation triggers FULL rebuild.
    """
    src = _config_src()
    assert "PHASE14_HYBRID_ALPHA_COLUMNS" in src, (
        "PHASE14_HYBRID_ALPHA_COLUMNS constant missing in r1000_config.py"
    )
    # All 6 expected columns must be in the constant
    for col in (
        "rs_acceleration_score", "h1_oversold_value_score",
        "h6_dynamic_leader_score", "stage2_overext_penalty",
        "theme_phase_multiplier_primary", "theme_phase_multiplier_max",
    ):
        assert f'"{col}"' in src, f"PHASE14 column missing from r1000_config: {col}"
    # DEFAULT_FEATURES must include the constant (via + concatenation)
    assert "+ PHASE14_HYBRID_ALPHA_COLUMNS" in src, (
        "PHASE14_HYBRID_ALPHA_COLUMNS not appended to DEFAULT_FEATURES — "
        "ML model will not see the new signals"
    )
    # Version bump must reflect Phase 14
    assert "phase14" in src.lower(), (
        "ENGINE_REUSE_VERSION not bumped for Phase 14 — cache will not invalidate"
    )


@_test("regression.phase14_columns_in_pipeline_keep_cols")
def test_phase14_in_pipeline() -> None:
    """build_universe_monthly must call all 5 Phase 14 compute_* functions
    AND keep_cols/hard_sanitize must include PHASE14_HYBRID_ALPHA_COLUMNS,
    or feature_store_latest.parquet will silently drop them
    (the same Phase 2 keepcols-survival regression we've fixed 4 times).
    """
    src = _pipeline_src()
    if not src:
        return
    # Functions called in build_universe_monthly
    for fn in (
        "compute_rs_acceleration_score(",
        "compute_h1_oversold_value_score(",
        "compute_h6_dynamic_leader_score(",
        "compute_stage2_overext_penalty(",
        "compute_theme_phase_features(",
    ):
        assert fn in src, f"r1000_pipeline.py does not call {fn} — Phase 14 dormant"
    # Whitelist + sanitize references (must appear at least 3 times: import +
    # keep_cols list + hard_sanitize list)
    count = src.count("PHASE14_HYBRID_ALPHA_COLUMNS")
    assert count >= 3, (
        f"PHASE14_HYBRID_ALPHA_COLUMNS referenced only {count} times in pipeline; "
        "expected >=3 (import + keep_cols + hard_sanitize)"
    )


@_test("regression.theme_aggregates_robust_to_empty_data")
def test_theme_aggregates_empty_robust() -> None:
    """compute_theme_aggregates + attach_per_ticker_theme_features must
    survive all-NaN / sparse / theme-less universe slices without KeyError.

    History (2026-04-26): pre-flight test of Phase 14 surfaced KeyError
    'theme_rs_benchmark_12m_mean' on all-NaN slices, AND KeyError 'theme_phase'
    on sparse universe. Both fixed in r1000_themes.py with column-existence
    guards before sort + map.

    Without these, FULL rebuild's early historical rebalance dates (where
    Finnhub fundamental coverage is sparse) would crash compute_theme_phase_features.
    """
    src = (ROOT / "r1000_themes.py").read_text(encoding="utf-8")
    # Defensive sort guard
    assert "if sort_col in out.columns" in src, (
        "compute_theme_aggregates missing column-existence guard before sort_values"
    )
    # Defensive map guard
    assert '"theme_name" in theme_aggregates.columns' in src, (
        "attach_per_ticker_theme_features missing theme_name column-existence guard"
    )
    assert '"theme_phase" in theme_aggregates.columns' in src, (
        "attach_per_ticker_theme_features missing theme_phase column-existence guard"
    )


@_test("regression.theme_phase_multiplier_constant_present")
def test_theme_phase_multiplier_constant() -> None:
    """r1000_themes.THEME_PHASE_MULTIPLIER must define the 5+1 phase mapping
    to numeric multipliers used by compute_theme_phase_features.

    Without this constant, Phase 14 H wiring would produce NaN multipliers
    that ML treats as unknown signal and silently zero out.
    """
    src = (ROOT / "r1000_themes.py").read_text(encoding="utf-8")
    assert "THEME_PHASE_MULTIPLIER" in src, (
        "THEME_PHASE_MULTIPLIER constant missing in r1000_themes.py"
    )
    for phase in ("early", "maturing", "peaking", "ending", "dead", "unknown"):
        assert f'"{phase}"' in src, f"THEME_PHASE_MULTIPLIER missing phase: {phase}"


@_test("regression.theme_policy_metadata_surface")
def test_theme_policy_metadata_surface() -> None:
    """Theme metadata must distinguish structural growth from short-cycle events.

    This guards the chameleon/lifecycle replay route: commodity/event themes
    should be reviewed faster, while structural growth themes can tolerate
    valid shakeouts in research-only replays.
    """
    from r1000_themes import attach_per_ticker_theme_features, load_themes
    import pandas as pd

    themes = load_themes(ROOT / "themes.yaml")
    assert themes["oil_gas_services"]["theme_horizon"] == "commodity_cycle"
    assert themes["ai_compute"]["theme_horizon"] == "structural_growth"
    assert "LEU" in themes["nuclear_fuel_cycle"]["tickers"]
    assert themes["nuclear_fuel_cycle"]["theme_horizon"] == "structural_growth"
    assert themes["fuel_cell_distributed_power"]["theme_horizon"] == "product_cycle"
    assert themes["critical_minerals_rare_earths"]["theme_horizon"] == "commodity_cycle"
    df = pd.DataFrame(
        [
            {"ticker": "FTI", "mom_6m": 0.20},
            {"ticker": "NVDA", "mom_6m": 0.10},
            {"ticker": "LEU", "mom_6m": 0.30},
            {"ticker": "BE", "mom_6m": 0.15},
            {"ticker": "MP", "mom_6m": 0.05},
        ]
    )
    out = attach_per_ticker_theme_features(df, themes)
    by_ticker = {row["ticker"]: row for row in out.to_dict("records")}
    assert by_ticker["FTI"]["theme_event_risk_sensitivity_max"] >= 0.75
    assert by_ticker["FTI"]["theme_short_cycle_flag_max"] >= 0.5
    assert by_ticker["NVDA"]["theme_structural_growth_max"] >= 0.85
    assert by_ticker["LEU"]["theme_structural_growth_max"] >= 0.85
    assert by_ticker["BE"]["theme_event_risk_sensitivity_max"] >= 0.55
    assert by_ticker["MP"]["theme_short_cycle_flag_max"] >= 0.5


@_test("regression.market_style_regime_router")
def test_market_style_regime_router() -> None:
    """Market style router must expose breakout/turnaround/cash preferences."""
    from r1000_features import compute_market_style_regime_features
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "rebalance_date": "2024-01-31",
                "market_regime_score": 0.8,
                "liquidity_regime_score": 0.8,
                "growth_liquidity_reentry_score": 0.7,
                "macro_risk_off_score": 0.1,
                "market_breadth_regime_score": 0.7,
                "market_sector_participation": 0.6,
                "bench_above_ma200": 1.0,
                "qqq_rel_spy_1m": 0.05,
                "breakout_fresh_20d": 1.0,
                "post_breakout_hold_score": 0.8,
                "h6_dynamic_leader_score": 0.8,
                "near_52w_high_pct": -0.03,
            },
            {
                "ticker": "BBB",
                "rebalance_date": "2024-01-31",
                "market_regime_score": 0.2,
                "liquidity_regime_score": 0.7,
                "growth_liquidity_reentry_score": 0.6,
                "macro_risk_off_score": 0.2,
                "market_breadth_regime_score": 0.2,
                "market_sector_participation": 0.2,
                "bench_above_ma200": 1.0,
                "value_inflection_score": 1.0,
                "fundamental_turnaround_acceleration_score": 0.8,
                "h1_oversold_value_score": 0.7,
                "industry_rotation_signal": 0.6,
            },
        ]
    )
    out = compute_market_style_regime_features(df)
    assert "market_style_regime_label" in out.columns
    assert out.loc[0, "style_row_breakout_fit"] > out.loc[0, "style_row_turnaround_fit"]
    assert out.loc[1, "style_row_turnaround_fit"] > out.loc[1, "style_row_breakout_fit"]
    assert out.loc[0, "style_calendar_month"] == 1
    assert out.loc[0, "style_calendar_weekday"] == 2


@_test("regression.main_v2_style_aware_selector")
def test_main_v2_style_aware_selector() -> None:
    """Main v2 must use style regime metadata in research-only selection."""
    from r1000_main_v2 import compose_main_sleeve_portfolio

    breakout_rows = [
        {
            "ticker": "BREAK",
            "score": 1.5,
            "portfolio_future_winner_engine_score": 0.8,
            "future_winner_scout_score": 0.8,
            "multi_year_winner_score": 0.5,
            "oneil_leadership_score": 0.8,
            "industry_group_strength_score": 0.8,
            "portfolio_monster_early_score": 0.4,
            "portfolio_risk_entry_block_score": 0.1,
            "price_above_ma200": 1,
            "price_above_ma50": 1,
            "market_style_regime_label": "breakout_growth",
            "style_row_breakout_fit": 0.85,
            "style_row_turnaround_fit": 0.05,
            "style_row_compounder_fit": 0.2,
            "style_breakout_preference": 0.85,
            "style_turnaround_preference": 0.1,
            "style_quality_compounder_preference": 0.2,
            "style_cash_defense_preference": 0.05,
        }
    ]
    breakout = compose_main_sleeve_portfolio(breakout_rows, regime_state="bull")
    assert breakout["audit"]["style_aware_selection_enabled"] is True
    assert breakout["style_regime"] == "breakout_growth"
    assert breakout["audit"]["style_adjusted_capacity_by_sleeve"]["future"] > breakout["audit"]["base_capacity_by_sleeve"]["future"]
    assert any(row["ticker"] == "BREAK" for row in breakout["selected_by_sleeve"]["future"])

    turnaround_rows = [
        {
            "ticker": "TURN",
            "score": 0.5,
            "portfolio_early_scout_engine_score": 0.7,
            "profitability_inflection_score": 0.8,
            "cashflow_inflection_under_loss_score": 0.8,
            "profit_turn_positive_4q": 1,
            "cashflow_turn_positive_4q": 1,
            "ni_loss_narrowing_4q": 1,
            "any_profit_sign_flip_pos": 1,
            "rs_acceleration_score": -0.05,
            "h1_oversold_value_score": 0.8,
            "fundamental_reliability_score": 0.8,
            "portfolio_risk_entry_block_score": 0.1,
            "price_above_ma200": 0,
            "price_above_ma50": 0,
            "market_style_regime_label": "turnaround_accumulation",
            "style_row_breakout_fit": 0.05,
            "style_row_turnaround_fit": 0.9,
            "style_row_compounder_fit": 0.2,
            "style_breakout_preference": 0.1,
            "style_turnaround_preference": 0.9,
            "style_quality_compounder_preference": 0.3,
            "style_cash_defense_preference": 0.1,
            "theme_event_risk_sensitivity_max": 0.2,
        }
    ]
    turnaround = compose_main_sleeve_portfolio(turnaround_rows, regime_state="neutral")
    assert turnaround["style_regime"] == "turnaround_accumulation"
    assert turnaround["audit"]["style_adjusted_capacity_by_sleeve"]["early"] > turnaround["audit"]["base_capacity_by_sleeve"]["early"]
    assert any(row["ticker"] == "TURN" for row in turnaround["selected_by_sleeve"]["early"])


@_test("regression.main_v2_opportunity_cost_replacement")
def test_main_v2_opportunity_cost_replacement() -> None:
    """Main v2 must reward superior new leaders and penalize stale event-cycle names."""
    from r1000_main_v2 import compose_main_sleeve_portfolio

    rows = [
        {
            "ticker": "NEW",
            "score": 1.2,
            "portfolio_future_winner_engine_score": 0.95,
            "portfolio_early_scout_engine_score": 0.85,
            "future_winner_scout_score": 1.2,
            "portfolio_monster_early_score": 0.58,
            "portfolio_risk_entry_block_score": 0.12,
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "event_revision_pillar_score": 1.2,
            "event_reaction_score": 3.0,
            "eps_revision_score": 1.0,
            "live_event_growth_reentry_score": 0.8,
            "macro_semis_cycle_interaction": 0.9,
            "style_row_breakout_fit": 0.8,
            "style_row_turnaround_fit": 0.2,
            "style_row_compounder_fit": 0.3,
            "market_style_regime_label": "breakout_growth",
            "style_breakout_preference": 0.8,
            "theme_structural_growth_max": 0.9,
            "theme_event_risk_sensitivity_max": 0.15,
            "industry_group_strength_score": 1.2,
            "oneil_leadership_score": 0.7,
            "sub_industry_rs_score": 0.9,
        },
        {
            "ticker": "OLD",
            "score": 2.4,
            "portfolio_future_winner_engine_score": 0.65,
            "future_winner_scout_score": 0.2,
            "portfolio_monster_early_score": 0.2,
            "portfolio_risk_entry_block_score": 0.55,
            "portfolio_stale_mega_leader_score": 0.9,
            "price_above_ma50": 1,
            "price_above_ma200": 1,
            "event_revision_pillar_score": 0.0,
            "event_reaction_score": 0.0,
            "eps_revision_score": 0.0,
            "rs_acceleration_score": -2.0,
            "risk_penalty": 1.0,
            "stage2_overext_penalty": 0.5,
            "style_row_breakout_fit": 0.1,
            "market_style_regime_label": "breakout_growth",
            "style_breakout_preference": 0.8,
            "theme_event_risk_sensitivity_max": 0.85,
            "theme_structural_growth_max": 0.2,
        },
    ]
    out = compose_main_sleeve_portfolio(rows, regime_state="bull")
    future = out["selected_by_sleeve"]["future"]
    assert any(row["ticker"] == "NEW" for row in future)
    assert not any(row["ticker"] == "OLD" for row in future)
    new_row = next(row for row in future if row["ticker"] == "NEW")
    assert new_row["main_v2_replacement_score"] > 0.60
    assert new_row["main_v2_replacement_catalyst_score"] > new_row["main_v2_replacement_decay_score"]


@_test("regression.scanner_has_stage2_breakout_guard")
def test_stage2_breakout_guard() -> None:
    """aggressive/scanner.py compute_opus_h1_h6_multiplier must include the
    Stage 2 breakout overextension penalty.

    Backtest finding (commit 1d04f78, 2026-04-25):
      "T1 Stage 2 breakout: -2.5% alpha (chase 52w high underperforms)"

    The penalty fires only when ALL four conditions hold:
      near_52w_high > 0.95 AND RSI > 72 AND no earnings catalyst AND weak fund
    Single-factor breakouts (just 52w high alone) are NOT penalized — real
    leaders pass through high RSI + 52w high regularly. The combination is
    what backtested poorly.

    Without this guard, the scanner would auto-promote chase-the-top names
    that historically underperform.
    """
    src = (ROOT / "aggressive" / "scanner.py").read_text(encoding="utf-8")
    assert "STAGE2_OVEREXTENSION_PENALTY" in src, (
        "STAGE2_OVEREXTENSION_PENALTY constant missing from scanner.py"
    )
    assert "Stage2-overext" in src, (
        "Stage2-overext warning text missing — penalty may not be wired"
    )
    # Verify the four-condition compound check is in place
    for cond in ("near_52w >", "rsi_now >", "no_catalyst", "weak_fund"):
        assert cond in src, (
            f"Stage 2 breakout compound check missing condition: {cond}"
        )


@_test("regression.adr_universe_yaml_valid")
def test_adr_universe_yaml() -> None:
    """adr_universe.yaml must exist with curated ADR list and watchlist.

    History (2026-04-25):
      User requested ASML/TSM + ADRs to compete fairly with R1000 names.
      adr_universe.yaml is the canonical whitelist (mcap>=$8B, NYSE/NASDAQ).
      themes.yaml was updated to include the same ADRs in semi/pharma themes.

    This guard ensures the file exists, parses cleanly, has minimum coverage,
    and includes the SK Hynix watchlist entry (Oct 2026 expected listing).
    """
    yaml_path = ROOT / "adr_universe.yaml"
    assert yaml_path.exists(), "adr_universe.yaml missing"
    try:
        import yaml as _yaml
    except ImportError:
        return  # CI may run without yaml; skip silently
    payload = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), "adr_universe.yaml not a mapping"
    core = payload.get("adr_universe", [])
    assert isinstance(core, list) and len(core) >= 20, (
        f"adr_universe must have >=20 entries, got {len(core)}"
    )
    # Required marquee ADRs
    tickers = {str(r.get("ticker", "")).upper() for r in core if isinstance(r, dict)}
    required = {"TSM", "ASML", "BABA", "NVO", "TM"}
    missing = required - tickers
    assert not missing, f"adr_universe missing required tickers: {missing}"
    # Watchlist must include SK Hynix entry (user explicitly asked about it)
    watchlist = payload.get("adr_watchlist", [])
    assert any(
        "Hynix" in str(r.get("name", "")) for r in watchlist if isinstance(r, dict)
    ), "SK Hynix entry missing from adr_watchlist (user mandate 2026-04-25)"


@_test("regression.themes_yaml_no_boolean_tickers")
def test_themes_yaml_string_tickers() -> None:
    """themes.yaml: every ticker MUST parse as a string, not bool.

    YAML 1.1 implicit conversion: ON, OFF, YES, NO, TRUE, FALSE all become
    bool unless quoted. ON Semiconductor (NASDAQ:ON) was silently parsed as
    True before 2026-04-25 fix, breaking any code iterating theme tickers.

    Also catches similar future regressions for any new YES/NO/ON tickers.
    """
    yaml_path = ROOT / "themes.yaml"
    if not yaml_path.exists():
        return
    try:
        import yaml as _yaml
    except ImportError:
        return
    payload = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    themes = (payload or {}).get("themes", {}) or {}
    bad: list[tuple[str, object]] = []
    for theme_name, rec in themes.items():
        if not isinstance(rec, dict):
            continue
        for tk in rec.get("tickers", []) or []:
            if not isinstance(tk, str):
                bad.append((theme_name, tk))
    assert not bad, (
        f"themes.yaml has {len(bad)} non-string tickers (YAML 1.1 boolean trap): {bad[:5]} — "
        f"quote them like \"ON\", \"YES\", \"NO\""
    )


@_test("regression.universe_supports_r1000_plus_adr")
def test_universe_r1000_plus_adr() -> None:
    """aggressive/universe.py must expose load_adr_universe() and accept
    source='r1000+adr' / source='adr' modes.

    Without this, ADR additions are unreachable from scanner / advisor and
    the curated whitelist becomes dead code.
    """
    src = (ROOT / "aggressive" / "universe.py").read_text(encoding="utf-8")
    assert "def load_adr_universe" in src, (
        "load_adr_universe() missing from aggressive/universe.py"
    )
    assert '"r1000+adr"' in src or "'r1000+adr'" in src, (
        "r1000+adr source mode not handled in load_universe()"
    )
    assert '"adr"' in src or "'adr'" in src, (
        "adr-only source mode not handled in load_universe()"
    )


@_test("regression.main_engine_adr_universe_mode_wired")
def test_main_engine_adr_universe_mode_wired() -> None:
    """full_rebuild_manual.yml universe_mode must reach the main engine.

    History (2026-04-27):
      Phase 14 verdict run used universe_mode=r1000+adr, but scored_latest.csv
      had 0/26 ADRs because only aggressive/universe.py knew how to load ADRs.
      run_local.py ignored UNIVERSE_MODE and main build_candidate_universe()
      always fell back to historical R1000 membership.
    """
    run_src = (ROOT / "run_local.py").read_text(encoding="utf-8")
    pipe_src = _pipeline_src()
    wf_src = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")

    for token in (
        "--universe-mode",
        "def resolve_universe_mode",
        "UNIVERSE_MODE",
        'runtime_overrides["universe_mode"] = universe_mode',
    ):
        assert token in run_src, f"run_local.py missing universe-mode wiring: {token}"

    for token in (
        "def load_adr_universe_frame",
        "from aggressive.universe import load_adr_universe",
        "adr_whitelist",
        "adr_universe_min_mcap_usd_b",
        "adr_global_alpha_fallback_pass",
        "adr_global_alpha_fallback",
        "include_adr =",
        "Skipping historical membership auto-archive for global alpha / ADR-augmented universe run",
    ):
        assert token in pipe_src, f"r1000_pipeline.py missing ADR universe wiring: {token}"

    for token in (
        "external_universe_mask",
        "external_after_merge",
        "summarize_universe_source",
    ):
        assert token in pipe_src, (
            f"r1000_pipeline.py membership filter can still drop ADR rows: {token}"
        )

    assert 'phase_is_enabled("phase14_hybrid_alpha"' in pipe_src, (
        "Phase 14 compute block must honor phase_is_enabled() for control runs"
    )
    assert "PHASE_PHASE14_HYBRID_ALPHA_ENABLED" in wf_src, (
        "full_rebuild_manual.yml must set the env var name consumed by phase_is_enabled()"
    )
    assert not re.search(r"^\s*PHASE14_HYBRID_ALPHA_ENABLED:", wf_src, re.MULTILINE), (
        "workflow still uses legacy Phase 14 env var name; control run will not disable Phase 14"
    )


@_test("logic.adr_global_alpha_fallback_gate")
def test_adr_global_alpha_fallback_gate() -> None:
    """Sparse-fundamental ADRs can enter via price/RS confirmation instead
    of being killed as unassigned by the Phase 9 thesis gate.
    """
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_pipeline import annotate_portfolio_candidate_gate

    df = pd.DataFrame(
        {
            "ticker": ["ADR1", "US1"],
            "universe_source": ["adr_whitelist", "current_constituents_proxy"],
            "portfolio_sleeve_label": ["unassigned", "unassigned"],
            "score": [3.0, 2.0],
            "mom_6m": [0.2, 0.2],
            "mom_12m": [0.3, 0.3],
            "rs_benchmark_6m": [0.1, 0.1],
            "relative_strength_composite": [1.0, 1.0],
            "price_above_ma50": [1, 1],
            "price_above_ma200": [1, 1],
            "trend_template_relaxed": [1, 1],
            "dynamic_leader_score": [1, 1],
        }
    )
    out = annotate_portfolio_candidate_gate(df, EngineConfig())
    adr = out.loc[out["ticker"].eq("ADR1")].iloc[0]
    us = out.loc[out["ticker"].eq("US1")].iloc[0]
    assert bool(adr["portfolio_candidate_minimum_pass"])
    assert str(adr["portfolio_sleeve_label"]) == "future_winner"
    assert str(adr["portfolio_candidate_gate_label"]) == "adr_global_alpha_fallback"
    assert not bool(us["portfolio_candidate_minimum_pass"])


@_test("regression.global_alpha_universe_window_audit_wired")
def test_global_alpha_universe_window_audit_wired() -> None:
    """The shared global-alpha universe, official 8-year execution path, and
    5/8/10-year sleeve audit outputs must be wired through entrypoints.
    """
    cfg_src = _config_src()
    run_src = (ROOT / "run_local.py").read_text(encoding="utf-8")
    pipe_src = _pipeline_src()
    wf_src = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")

    for token in (
        "global_alpha_universe",
        "--backtest-years",
        "--leader-rescue-mode",
        "BACKTEST_YEARS",
        "LEADER_RESCUE_MODE",
        'runtime_overrides["default_backtest_years"]',
        'runtime_overrides["backtest_window_comparison_years"]',
        'runtime_overrides["leader_rescue_backtest_mode"]',
    ):
        assert token in run_src, f"run_local.py missing global-alpha/window wiring: {token}"

    for token in (
        "default_backtest_years: int = 8",
        'leader_rescue_backtest_mode: str = "latest_only"',
        "strategic_global_hardware_universe_enabled: bool = True",
        "compact_universe_train_sample_relax_enabled: bool = True",
        "compact_universe_min_train_samples: int = 800",
        "[5, 8, 10]",
    ):
        assert token in cfg_src, f"r1000_config.py missing 8y default or 5/8/10 comparison token: {token}"

    for token in (
        "global_alpha_universe",
        "build_global_alpha_sleeve_audit_frames",
        "global_alpha_sleeve_audit_by_month.csv",
        "global_alpha_sleeve_audit_summary.csv",
        "apply_leader_rescue_backtest_mode_filter",
        "load_strategic_global_hardware_universe_frame",
        "strategic_global_hardware",
        "leader_rescue_backtest_filter_summary.json",
        "effective_min_train_samples",
        "No OOS rows were generated in walk-forward training.",
    ):
        assert token in pipe_src, f"r1000_pipeline.py missing global-alpha audit wiring: {token}"

    for token in (
        "global_alpha_universe",
        "backtest_years",
        "leader_rescue_mode",
        "BACKTEST_YEARS",
        "LEADER_RESCUE_MODE",
        "--backtest-years",
        "--leader-rescue-mode",
        "outputs/reports/global_alpha_sleeve_audit_*.csv",
        "outputs/reports/leader_rescue_backtest_filter_summary.json",
    ):
        assert token in wf_src, f"full_rebuild_manual.yml missing global-alpha/window token: {token}"


@_test("regression.layer4_swap_bridge_wired")
def test_layer4_swap_bridge() -> None:
    """r1000_layer4_swap.py must exist and provide layer4_swap_suggestions()
    that bridges portfolio CSV + scored CSV into Layer 4 of risk_sensing.

    Layer 4 RS-based swap (weak rs<0 + held>=60d -> strong rs>=30 candidate)
    is dormant in production until this bridge feeds it data.

    History:
      c8b5773 Layer 4 logic shipped (evaluate_layer4_swap)
      this    Layer 4 bridge — reads portfolio_latest.csv + scored_unified.csv

    This guard prevents the bridge from being silently removed.
    """
    swap_path = ROOT / "r1000_layer4_swap.py"
    assert swap_path.exists(), "r1000_layer4_swap.py missing — Layer 4 has no data feed"
    src = swap_path.read_text(encoding="utf-8")
    for sym in ("def layer4_swap_suggestions", "def build_position_list",
                "def build_candidate_pool", "evaluate_layer4_swap"):
        assert sym in src, f"{sym} missing from r1000_layer4_swap.py"
    # Cross-check evaluator still exists
    rs_src = (ROOT / "r1000_risk_sensing.py").read_text(encoding="utf-8")
    assert "def evaluate_layer4_swap" in rs_src, (
        "evaluate_layer4_swap renamed/removed — Layer 4 bridge will break"
    )


@_test("regression.layer3_regime_fetcher_wired")
def test_layer3_regime_data_module() -> None:
    """r1000_regime_data.py must exist and provide current_regime() +
    layer3_actions_for_snapshot() that bridge live data into Layer 3 of
    r1000_risk_sensing.evaluate_layer3_regime.

    Without this bridge, Layer 3 (VIX>=30 halt + SPY<200MA cash buffer)
    has logic but no data, and acts as a no-op even when conditions trigger.

    This guard prevents the bridge from being silently removed or renamed
    in a way that would re-disconnect Layer 3 from production.
    """
    regime_path = ROOT / "r1000_regime_data.py"
    assert regime_path.exists(), "r1000_regime_data.py missing — Layer 3 has no data feed"
    src = regime_path.read_text(encoding="utf-8")
    for sym in ("def current_regime", "def fetch_vix",
                "def fetch_spy_with_ma200", "def layer3_actions_for_snapshot",
                "RegimeSnapshot"):
        assert sym in src, f"{sym} missing from r1000_regime_data.py"
    # Cross-check: the Layer 3 evaluator name still matches the bridge import
    rs_src = (ROOT / "r1000_risk_sensing.py").read_text(encoding="utf-8")
    assert "def evaluate_layer3_regime" in rs_src, (
        "evaluate_layer3_regime renamed/removed — regime_data bridge will break"
    )


@_test("regression.advisor_v4_marked_deprecated")
def test_advisor_v4_deprecated() -> None:
    """advisor v4's "+75.7% alpha" was leakage-driven (c13fa6a / 6c0a496).
    The honest assessment commit explicitly stated:
      'v4 ML-primary advisor empirically deprecated'

    This guard ensures the deprecation marker stays in place so future
    contributors can't silently re-promote v4 as production.

    Required markers:
      - r1000_rebalance_advisor_v4.py docstring contains 'DEPRECATED'
      - paper_executor refuses --advisor v4 without --allow-deprecated-v4 ack
    """
    v4_path = ROOT / "r1000_rebalance_advisor_v4.py"
    assert v4_path.exists(), "r1000_rebalance_advisor_v4.py missing"
    v4_src = v4_path.read_text(encoding="utf-8")
    assert "DEPRECATED" in v4_src[:2000], (
        "DEPRECATED marker missing from r1000_rebalance_advisor_v4.py docstring "
        "(must reference commit c13fa6a leakage finding)"
    )

    pe_path = ROOT / "r1000_paper_executor.py"
    assert pe_path.exists(), "r1000_paper_executor.py missing"
    pe_src = pe_path.read_text(encoding="utf-8")
    assert "allow-deprecated-v4" in pe_src, (
        "paper_executor missing --allow-deprecated-v4 gate for v4 advisor"
    )


@_test("regression.production_acceptance_check_bans_all_forward_returns")
def test_production_exact_banned_full_coverage() -> None:
    """run_acceptance_checks.exact_banned must include ALL forward-return
    horizons (r_1m..r_36m) + bench_r_*m, not just r_1m/3m/6m.

    Commit 6c0a496 (2026-04-25) audit explicitly noted:
      'Defensive gap noted: exact_banned only {r_1m,r_3m,r_6m} but
       cfg.features has none of those anyway'

    cfg.features doesn't currently contain r_12m/24m/36m, so this is a
    defensive guard against future feature additions silently re-introducing
    leakage. The acceptance gate must catch all forward-return horizons,
    not just the subset that happen to be banned in pattern_miner.
    """
    src = _pipeline_src()
    if not src:
        return  # pre-Refactor-Phase-A skip
    # Locate the exact_banned definition inside run_acceptance_checks
    m = re.search(r"exact_banned\s*=\s*\{([^}]*)\}", src)
    assert m is not None, (
        "exact_banned set not found in r1000_pipeline.py — "
        "run_acceptance_checks leakage gate missing"
    )
    body = m.group(1)
    required = ["r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m"]
    missing = [c for c in required if f'"{c}"' not in body]
    assert not missing, (
        f"exact_banned in r1000_pipeline.py missing {missing} — "
        f"defensive gap from audit 6c0a496 still open. "
        f"Forward returns 12m/24m/36m would silently pass leakage check."
    )


@_test("regression.short_rs_trap_columns_wired")
def test_short_rs_trap_columns_wired() -> None:
    """SHORT_RS_TRAP_COLUMNS must be exported + spliced into build_feature_store.

    Adds protection for the 2026-05-13 PLTR/IONQ-class fix: short-term RS
    breakdown + chase-extension penalty. The 4 columns must all reach the
    feature_store_latest.parquet keep_cols + hard_sanitize whitelist, AND
    the constant must be exported from r1000_features.py.
    """
    features_src = _features_src() if "_features_src" in globals() else _combined_src()
    pipeline_src = _pipeline_src() if "_pipeline_src" in globals() else _combined_src()
    combined = _combined_src()

    expected = [
        "rs_short_score",
        "rs_long_score",
        "rs_short_breakdown_penalty",
        "short_extension_risk_penalty",
    ]

    # Constant must exist
    assert "SHORT_RS_TRAP_COLUMNS" in combined, (
        "SHORT_RS_TRAP_COLUMNS constant not found in r1000_features.py"
    )
    # All 4 columns must be in the constant list
    m = re.search(r"SHORT_RS_TRAP_COLUMNS\s*=\s*\[(.*?)\]", combined, re.DOTALL)
    assert m, "SHORT_RS_TRAP_COLUMNS list literal not found"
    body = m.group(1)
    missing = [c for c in expected if f'"{c}"' not in body]
    assert not missing, (
        f"SHORT_RS_TRAP_COLUMNS missing expected names: {missing}"
    )
    # Must be wired into build_feature_store
    fs_m = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        pipeline_src,
        re.DOTALL | re.MULTILINE,
    )
    assert fs_m, "build_feature_store not found"
    assert "SHORT_RS_TRAP_COLUMNS" in fs_m.group(0), (
        "SHORT_RS_TRAP_COLUMNS not referenced inside build_feature_store keep_cols"
    )


@_test("regression.short_rs_trap_compute_fns_invoked")
def test_short_rs_trap_compute_fns_invoked() -> None:
    """compute_rs_short_long_scores + compute_short_extension_risk_penalty
    must be invoked in build_feature_store body.
    """
    pipeline_src = _pipeline_src() if "_pipeline_src" in globals() else _combined_src()
    m = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        pipeline_src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "build_feature_store not found"
    body = m.group(0)
    assert "compute_rs_short_long_scores" in body, (
        "compute_rs_short_long_scores() not invoked in build_feature_store"
    )
    assert "compute_short_extension_risk_penalty" in body, (
        "compute_short_extension_risk_penalty() not invoked in build_feature_store"
    )


@_test("regression.strategic_turnaround_pass_wired")
def test_strategic_turnaround_pass_wired() -> None:
    """add_core_fundamental_minimum_flags must include strategic_turnaround_pass
    as a 5th lane in core_fundamental_minimum_pass.

    Without this, INTC-class megacap turnaround candidates (negative NI but
    profitability_turn_positive / ni_loss_narrowing trending up) get cut at
    the gate and never reach scoring.
    """
    pipeline_src = _pipeline_src() if "_pipeline_src" in globals() else _combined_src()
    m = re.search(
        r"^def add_core_fundamental_minimum_flags\b.*?(?=^def |\Z)",
        pipeline_src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "add_core_fundamental_minimum_flags not found"
    body = m.group(0)
    assert "strategic_turnaround_pass" in body, (
        "strategic_turnaround_pass not defined in add_core_fundamental_minimum_flags"
    )
    # Must be unioned into the final core_fundamental_minimum_pass
    final_line_m = re.search(
        r'd\["core_fundamental_minimum_pass"\]\s*=\s*\(?\s*([^)\n]+)',
        body,
    )
    assert final_line_m, "core_fundamental_minimum_pass assignment not found"
    assert "strategic_turnaround_pass" in final_line_m.group(1), (
        "core_fundamental_minimum_pass does not union strategic_turnaround_pass — "
        "INTC-class turnaround bypass disabled"
    )


@_test("structural.short_rs_trap_weight_cfg_fields")
def test_short_rs_trap_weight_cfg_fields() -> None:
    """3 new EngineConfig fields must exist: w_rs_short_score,
    w_rs_short_breakdown_penalty, w_short_extension_penalty.
    """
    src = _combined_src()
    for field in [
        "w_rs_short_score",
        "w_rs_short_breakdown_penalty",
        "w_short_extension_penalty",
    ]:
        assert re.search(rf"\b{field}\s*:\s*float\s*=", src), (
            f"EngineConfig field {field} not declared with float default"
        )


@_test("regression.sec_evidence_columns_wired")
def test_sec_evidence_columns_wired() -> None:
    """SEC_EVIDENCE_COLUMNS must include both 13F + Form 4 columns and be
    spliced into build_feature_store keep_cols.

    Without this wiring, sec_13f_quarterly_refresh.yml + sec_form4_daily_refresh
    .yml workflows produce signals that never reach feature_store_latest, so the
    score overlay would be permanently zero even when the cron runs successfully.
    """
    src = _combined_src()
    assert "SEC_EVIDENCE_COLUMNS" in src, "SEC_EVIDENCE_COLUMNS constant not found"
    m = re.search(r"SEC_EVIDENCE_COLUMNS\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "SEC_EVIDENCE_COLUMNS list literal not found"
    body = m.group(1)
    # Spot-check both 13F + Form 4 signal columns are present
    for required in [
        "sec_13f_smart_money_score",
        "institutional_evidence_score",
        "sec_form4_cluster_buy_score",
        "early_evidence_score",
    ]:
        assert f'"{required}"' in body, (
            f"SEC_EVIDENCE_COLUMNS missing {required} — overlay incomplete"
        )
    # Must be wired into build_feature_store
    pipeline_src = _pipeline_src() if "_pipeline_src" in globals() else src
    fs_m = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        pipeline_src,
        re.DOTALL | re.MULTILINE,
    )
    assert fs_m, "build_feature_store not found"
    assert "SEC_EVIDENCE_COLUMNS" in fs_m.group(0), (
        "SEC_EVIDENCE_COLUMNS not referenced inside build_feature_store keep_cols"
    )


@_test("regression.sec_evidence_score_overlay_wired")
def test_sec_evidence_score_overlay_wired() -> None:
    """add_total_score_columns must include the SEC institutional + insider
    overlays (score_sec_institutional_overlay + score_sec_insider_overlay).

    Without this, the 13F manager-tracking + Form 4 insider-buying signals
    are computed by the SEC pipelines but never reach shadow evidence fusion
    diagnostics.
    """
    pipeline_src = _pipeline_src() if "_pipeline_src" in globals() else _combined_src()
    m = re.search(
        r"^def add_total_score_columns\b.*?(?=^def |\Z)",
        pipeline_src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "add_total_score_columns not found"
    body = m.group(0)
    assert "score_sec_institutional_overlay" in body, (
        "score_sec_institutional_overlay not added in add_total_score_columns"
    )
    assert "score_sec_insider_overlay" in body, (
        "score_sec_insider_overlay not added in add_total_score_columns"
    )
    assert "w_sec_institutional_evidence" in body, (
        "w_sec_institutional_evidence cfg field not read in add_total_score_columns"
    )
    assert "evidence_fusion_score" in body, (
        "evidence_fusion_score not computed in add_total_score_columns"
    )
    assert "evidence_fusion_apply_to_live_score" in body, (
        "SEC/ETF evidence must be live-score gated by evidence_fusion_apply_to_live_score"
    )


@_test("regression.sec_evidence_loader_matches_workflow_outputs")
def test_sec_evidence_loader_matches_workflow_outputs() -> None:
    """The loader must read the actual filenames emitted by SEC workflows.

    The 13F/Form 4 refresh jobs currently emit ``13f_latest`` and
    ``form4_latest`` files. If the full rebuild only looks for a generic
    ``signals_latest`` name, SEC overlay scores silently zero-fill.
    """
    features_src = _features_src() if "_features_src" in globals() else _combined_src()
    m = re.search(
        r"^def load_sec_evidence_overlay\b.*?(?=^def |\Z)",
        features_src,
        re.DOTALL | re.MULTILINE,
    )
    assert m, "load_sec_evidence_overlay not found"
    body = m.group(0)
    for required in [
        "13f_latest.parquet",
        "13f_latest.csv",
        "form4_latest.parquet",
        "form4_latest.csv",
        "form4_transactions.parquet",
    ]:
        assert required in body, f"SEC overlay loader missing workflow output {required}"


@_test("structural.sec_evidence_weight_cfg_fields")
def test_sec_evidence_weight_cfg_fields() -> None:
    """2 new EngineConfig fields must exist: w_sec_institutional_evidence,
    w_sec_insider_evidence. Both default to 0.30 / 0.20 respectively.
    """
    src = _combined_src()
    for field in [
        "w_sec_institutional_evidence",
        "w_sec_insider_evidence",
    ]:
        assert re.search(rf"\b{field}\s*:\s*float\s*=", src), (
            f"EngineConfig field {field} not declared with float default"
        )


@_test("regression.sec_13f_manager_universe_csv_present")
def test_sec_13f_manager_universe_csv_present() -> None:
    """managers.csv must exist + contain at least 30 managers + verified
    Whale Rock / Atreides (user-requested high-conviction picks).
    """
    import csv

    repo_root = Path(__file__).resolve().parent.parent
    csv_path = repo_root / "research" / "sec_13f_manager_universe_20260519" / "managers.csv"
    assert csv_path.exists(), f"managers.csv missing at {csv_path}"
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 30, f"managers.csv has only {len(rows)} entries; expected >= 30"
    labels = {r["label"].upper() for r in rows}
    for expected in ["WHALEROCK", "ATREIDES", "SITUATIONAL", "DUQUESNE"]:
        assert expected in labels, (
            f"managers.csv missing required entry: {expected}"
        )
    by_label = {r["label"].upper(): r for r in rows}
    assert by_label["WHALEROCK"]["cik10"] == "0001387322", "Whale Rock/Alex Sacerdote SEC CIK must be current"
    assert by_label["ATREIDES"]["cik10"] == "0001777813", "Atreides/Gavin Baker SEC CIK must be current"


@_test("regression.sec_13f_workflow_uses_manager_universe")
def test_sec_13f_workflow_uses_manager_universe() -> None:
    """13F refresh must not silently fall back to a BRK-only manager list."""
    repo_root = Path(__file__).resolve().parent.parent
    wf = (repo_root / ".github" / "workflows" / "sec_13f_quarterly_refresh.yml").read_text(encoding="utf-8")
    assert "tools/build_sec_13f_manager_universe.py" in wf
    assert "tools/build_sec_13f_cusip_ticker_map.py" in wf
    assert "--cusip-map data_pit/sec/cusip_ticker_map.parquet" in wf
    assert "outputs/sec_institutional_signals/mapping_audit.json" in wf
    assert "refusing to run BRK-only fallback" in wf
    assert "BRK:0001067983' }}" not in wf


@_test("regression.etf_holdings_overlay_wired")
def test_etf_holdings_overlay_wired() -> None:
    """Dynamic ETF holdings must have a PIT data lake, loader, and workflow."""
    src = _combined_src()
    for required in [
        "ETF_HOLDINGS_EVIDENCE_COLUMNS",
        "EVIDENCE_FUSION_COLUMNS",
        "etf_holdings_score",
        "evidence_fusion_score",
    ]:
        assert required in src, f"ETF/evidence fusion wiring missing {required}"
    repo_root = Path(__file__).resolve().parent.parent
    assert (repo_root / "tools" / "run_etf_holdings_refresh.py").exists()
    assert (repo_root / ".github" / "workflows" / "etf_holdings_monthly_refresh.yml").exists()
    assert (repo_root / "research" / "etf_holdings_universe_20260520" / "thematic_etfs.yaml").exists()


@_test("regression.plan_c_v35_kill_switch_defaults")
def test_plan_c_v35_kill_switch_defaults() -> None:
    """CHANGELOG 2026-05-21: SEC/ETF/PDA live-score gates default OFF."""
    from r1000_config import EngineConfig

    cfg = EngineConfig()
    assert cfg.evidence_fusion_apply_to_live_score is False
    assert cfg.pda_apply_to_live_score is False
    assert cfg.evidence_fusion_bonus_cap == 0.20
    assert cfg.pda_bonus_cap == 0.15
    assert cfg.w_pda_13f == cfg.w_pda_form4 == cfg.w_pda_13d == cfg.w_pda_etf == 0.0


@_test("regression.plan_c_v35_evidence_switch_off_blocks_score")
def test_plan_c_v35_evidence_switch_off_blocks_score() -> None:
    """CHANGELOG 2026-05-21: switch OFF keeps score unchanged but shadows live."""
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_pipeline import add_total_score_columns

    df = pd.DataFrame({"ticker": ["BASE"], "institutional_evidence_score": [0.0]})
    rich = pd.DataFrame({"ticker": ["BASE"], "institutional_evidence_score": [1.0],
                         "institutional_evidence_confidence_score": [1.0],
                         "early_evidence_score": [1.0], "evidence_confidence_score": [1.0],
                         "etf_holdings_score": [1.0], "etf_evidence_confidence": [1.0]})
    cfg = EngineConfig(evidence_fusion_apply_to_live_score=False)
    base_out = add_total_score_columns(df, cfg)
    rich_out = add_total_score_columns(rich, cfg)
    assert float(rich_out["evidence_fusion_score"].iloc[0]) > float(base_out["evidence_fusion_score"].iloc[0])
    assert float(rich_out["score_evidence_fusion_overlay"].iloc[0]) == 0.0
    assert abs(float(rich_out["score"].iloc[0]) - float(base_out["score"].iloc[0])) < 1e-12


@_test("regression.plan_c_v35_evidence_switch_on_cap")
def test_plan_c_v35_evidence_switch_on_cap() -> None:
    """CHANGELOG 2026-05-21: switch ON applies only capped evidence bonus."""
    import pandas as pd
    from r1000_config import EngineConfig
    from r1000_pipeline import add_total_score_columns

    df = pd.DataFrame({"ticker": ["X"], "institutional_evidence_score": [1.0],
                       "institutional_evidence_confidence_score": [1.0],
                       "early_evidence_score": [1.0], "evidence_confidence_score": [1.0],
                       "etf_holdings_score": [1.0], "etf_evidence_confidence": [1.0]})
    off = add_total_score_columns(df, EngineConfig(evidence_fusion_apply_to_live_score=False))
    on = add_total_score_columns(df, EngineConfig(evidence_fusion_apply_to_live_score=True,
                                                  evidence_fusion_bonus_cap=0.20,
                                                  w_evidence_fusion_score=10.0))
    delta = float(on["score"].iloc[0] - off["score"].iloc[0])
    cap = 0.20 * abs(float(off["score"].iloc[0]))
    assert abs(delta - float(on["score_evidence_fusion_overlay"].iloc[0])) < 1e-12
    assert 0.0 <= delta <= cap + 1e-12


@_test("regression.universe_collapse_guard_counts_r1000_base")
def test_universe_collapse_guard_counts_r1000_base() -> None:
    """Full Rebuild #82 regression: count_r1000_base_names must count only the
    R1000 base sources (live IWB proxy or committed membership), so a starved
    whitelist-only universe scores 0 and trips the guard."""
    import pandas as pd
    from r1000_pipeline import count_r1000_base_names, MIN_R1000_BASE_NAMES

    # Healthy: ~693 R1000-base names (incl. combined-source labels) + whitelists
    healthy = pd.DataFrame({
        "universe_source": (
            ["current_constituents_proxy"] * 690
            + ["current_constituents_proxy+strategic_global_hardware"] * 3
            + ["adr_whitelist"] * 28
            + ["cycle_play_whitelist"] * 5
        )
    })
    assert count_r1000_base_names(healthy) == 693
    assert count_r1000_base_names(healthy) >= MIN_R1000_BASE_NAMES

    # Starved (the #82 collapse): NO R1000 base, only static whitelists
    starved = pd.DataFrame({
        "universe_source": (
            ["adr_whitelist"] * 28
            + ["strategic_global_hardware"] * 22
            + ["cycle_play_whitelist"] * 8
        )
    })
    assert count_r1000_base_names(starved) == 0
    assert count_r1000_base_names(starved) < MIN_R1000_BASE_NAMES

    # Committed historical membership also counts as a healthy base
    hist = pd.DataFrame({"universe_source": ["historical_membership_file"] * 500})
    assert count_r1000_base_names(hist) == 500

    # Robust to empty / missing-column frames
    assert count_r1000_base_names(pd.DataFrame()) == 0
    assert count_r1000_base_names(pd.DataFrame({"ticker": ["AAPL"]})) == 0


@_test("regression.universe_collapse_guard_floor_threshold")
def test_universe_collapse_guard_floor_threshold() -> None:
    """The R1000 base floor must sit well above the 58-name starved collapse and
    safely below the ~693 healthy base, so transient IWB failures fail loud."""
    from r1000_pipeline import MIN_R1000_BASE_NAMES

    assert 58 < MIN_R1000_BASE_NAMES < 693, (
        f"MIN_R1000_BASE_NAMES={MIN_R1000_BASE_NAMES} must be between the 58-name "
        f"starved collapse and the ~693 healthy base"
    )


@_test("regression.iwb_static_seed_fallback_is_broad_base")
def test_iwb_static_seed_fallback_is_broad_base() -> None:
    """A tracked IWB seed keeps full rebuilds usable when live iShares/Wikipedia
    fetches are blocked, while the universe-collapse guard still enforces a
    broad R1000 base."""
    from r1000_pipeline import MIN_R1000_BASE_NAMES, count_r1000_base_names, load_iwb_seed_universe_frame

    seed_path = ROOT / "data_static" / "iwb_holdings_seed.csv"
    assert seed_path.exists(), "tracked IWB seed missing"
    with seed_path.open(newline="", encoding="utf-8") as fh:
        seed_tickers = {row.get("ticker", "").strip().upper() for row in csv.DictReader(fh)}
    assert len(seed_tickers - {""}) >= MIN_R1000_BASE_NAMES, "tracked IWB seed is too narrow"

    seed = load_iwb_seed_universe_frame({"data_raw": ROOT / ".tmp_missing_data_raw"})
    assert count_r1000_base_names(seed) >= MIN_R1000_BASE_NAMES
    assert "current_constituents_proxy_static_seed" in set(seed["universe_source"].astype(str))


@_test("structural.full_rebuild_workflow_blocks_starved_universe")
def test_full_rebuild_workflow_blocks_starved_universe() -> None:
    """full_rebuild_manual.yml must gate the latest_ baseline rotation on a
    universe-health check (UNIVERSE_HEALTHY) so a starved run cannot overwrite
    the shipped baseline (Full Rebuild #82 regression)."""
    wf = (ROOT / ".github/workflows/full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert "UNIVERSE_HEALTHY" in wf, "universe-health gate missing from full rebuild workflow"
    assert "current_constituents_proxy" in wf, "workflow gate must inspect R1000 base source"
    # The validity gate that selects DEST + rotation must include UNIVERSE_HEALTHY
    assert '[ "$UNIVERSE_HEALTHY" = "yes" ]' in wf, (
        "RUN_ARTIFACT_VALID must require UNIVERSE_HEALTHY=yes"
    )
    assert "INVALID_UNIVERSE" in wf, "workflow must mark starved runs INVALID_UNIVERSE"
    assert "aggressive/cache/universe" in wf, "workflow must cache the offline IWB universe fallback"


@_test("syntax.user_current_and_sync_tools_parse")
def test_user_current_and_sync_tools_parse() -> None:
    for rel in [
        "tools/run_user_current_report.py",
        "tools/build_gdrive_sync_manifest.py",
        "tools/crisis_state_engine.py",
        "tools/run_daily_crisis_monitor.py",
        "tools/build_crisis_governed_target_books.py",
        "tools/run_full_rebuild_sidecars.py",
        "tools/run_execution_lag_review.py",
        "tools/run_position_risk_review.py",
        "tools/run_concentrated_broker_variant_review.py",
        "tools/run_position_cleanup_review.py",
        "tools/run_patch_application_manifest.py",
        "tools/run_alphaops_vnext_policy_replay.py",
        "tools/create_healthy_baseline_lock.py",
        "tools/run_market_leader_challenger.py",
        "tools/run_shakeout_disclosure_reversal_study.py",
        "tools/run_pit_top_manager_follow_study.py",
        "r1000_market_leader_engine.py",
    ]:
        ast.parse((ROOT / rel).read_text(encoding="utf-8"))


@_test("structural.workflow_profiles_operating_minimal_skip_research")
def test_workflow_profiles_operating_minimal_skip_research() -> None:
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    sidecar_tool = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    for token in ["sidecar_profile:", "artifact_profile:", "gdrive_sync_mode:", "operating_minimal", "research_full"]:
        assert token in wf, f"full_rebuild_manual.yml missing profile token {token}"
    assert "run_full_rebuild_sidecars.py" in wf
    assert 'if [ "$SIDECAR_PROFILE" = "operating_minimal" ] || [ "$SIDECAR_PROFILE" = "official" ]; then' in sidecar_tool
    assert "heavy research sidecars skipped" in sidecar_tool
    assert "run_user_current_report.py" in sidecar_tool
    assert "run_daily_crisis_monitor.py" in sidecar_tool
    assert 'if [ "$SIDECAR_PROFILE" = "official" ]; then' in sidecar_tool
    assert "run_execution_lag_review.py" in sidecar_tool
    assert "run_position_risk_review.py" in sidecar_tool
    assert "run_concentrated_broker_variant_review.py" in sidecar_tool
    assert "run_position_cleanup_review.py" in sidecar_tool
    assert "run_patch_application_manifest.py" in sidecar_tool
    assert "create_healthy_baseline_lock.py" in sidecar_tool
    assert "run_market_leader_challenger.py" in sidecar_tool
    assert "outputs/broker_position_risk_replay/" in wf
    assert "outputs/broker_parabolic_risk_replay/" in wf
    assert "outputs/legacy_monthly_broker_replay/" in wf
    assert "outputs/broker_execution_policy_replay/" in wf
    assert "outputs/operator_review/" in wf
    assert "outputs/baseline_lock/" in wf
    assert "outputs/market_leader_challenger/" in wf
    assert "alphaops_vnext_production" in wf
    assert "tools/run_alphaops_vnext_policy_replay.py" in sidecar_tool
    assert "outputs/alphaops_vnext/" in wf


@_test("structural.pit_top_manager_follow_study_is_research_only")
def test_pit_top_manager_follow_study_is_research_only() -> None:
    src = (ROOT / "tools" / "run_pit_top_manager_follow_study.py").read_text(encoding="utf-8")
    sidecar = (ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(encoding="utf-8")
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    post_wf = (ROOT / ".github" / "workflows" / "post_disclosure_alpha_pipeline.yml").read_text(encoding="utf-8")
    manifest = (ROOT / "tools" / "build_gdrive_sync_manifest.py").read_text(encoding="utf-8")
    for token in [
        "completed post-disclosure labels",
        "label_completion_ts",
        "production_activation_allowed",
        "score_total_changed",
        "cohort_refresh_months",
        "ranking_lookback_days",
        "top_n",
    ]:
        assert token in src, f"PIT top-manager follow study missing {token}"
    assert "run_pit_top_manager_follow_study.py" in sidecar
    assert "outputs/pit_top_manager_follow_study/" in wf
    assert "Run PIT top-manager follow study" in post_wf
    assert "data_pit/sec/pit_top_manager_cohorts.*" in post_wf
    assert "outputs/pit_top_manager_follow_study" in post_wf
    assert "pit_top_manager_follow_study/bucket_performance.csv" in manifest


@_test("structural.user_current_contains_no_research_metrics")
def test_user_current_contains_no_research_metrics() -> None:
    tool = (ROOT / "tools" / "run_user_current_report.py").read_text(encoding="utf-8")
    for required in [
        "01_current_holdings.csv",
        "02_target_weights.csv",
        "03_order_preview.csv",
        "03_period_returns.csv",
        "04_official_metrics.json",
        "06_benchmark_comparison.csv",
        "07_name_rationales.csv",
        "07_research_sidecar_context.json",
        "08_rebalance_decision.json",
        "current simulated broker-ledger holdings only",
    ]:
        assert required in tool, f"user_current report missing {required}"
    forbidden = ["portfolio_latest.csv", "concentrated_portfolio_latest.csv", "candidate_replay_book.csv"]
    readme_block = re.search(r"def write_readme\b.*?def build_report", tool, re.DOTALL)
    assert readme_block, "write_readme block not found"
    for token in forbidden:
        assert token not in readme_block.group(0), f"user_current README should not expose {token}"


@_test("structural.gdrive_manifest_marks_deprecated_research")
def test_gdrive_manifest_marks_deprecated_research() -> None:
    src = (ROOT / "tools" / "build_gdrive_sync_manifest.py").read_text(encoding="utf-8")
    for token in [
        "semantic_type",
        "production_valid",
        "weight_level_research_deprecated",
        "USER_CURRENT_FILES",
        "strict-primary",
        "gdrive_sync_manifest.json",
        "execution_lag_review.json",
        "position_risk_review.json",
        "concentrated_broker_variant_review.json",
        "position_cleanup_review.json",
        "dust_positions_report.csv",
        "patch_application_manifest.json",
        "MINIMAL_ANALYSIS_FILES",
        "broker_replay/main/trades.csv",
        "broker_replay/concentrated/cash_ledger.csv",
        "reports/operating_main_target_book.csv",
    ]:
        assert token in src, f"gdrive manifest tool missing {token}"
    wf = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert "build_gdrive_sync_manifest.py" in wf
    assert "rclone copyto" in wf
    assert "outputs/gdrive_sync_files.tsv" in wf


@_test("structural.period_returns_include_mdd_and_benchmarks")
def test_period_returns_include_mdd_and_benchmarks() -> None:
    src = (ROOT / "tools" / "run_user_current_report.py").read_text(encoding="utf-8")
    for token in ["max_drawdown", "BENCHMARKS = (\"SPY\", \"QQQ\")", "\"YTD\"", "\"2Y\"", "realized_volatility"]:
        assert token in src, f"period return implementation missing {token}"


@_test("structural.action_status_review_when_cash_policy_flag_present")
def test_action_status_review_when_cash_policy_flag_present() -> None:
    src = (ROOT / "tools" / "run_user_current_report.py").read_text(encoding="utf-8")
    assert "cash_policy_flag" in src
    assert "REVIEW_REQUIRED" in src
    assert "DO_NOT_USE" in src
    assert "official_metric_mode" in src
    assert "broker_ledger_next_close" in src


@_test("structural.evidence_nonzero_is_not_enough_without_selection_impact")
def test_evidence_nonzero_is_not_enough_without_selection_impact() -> None:
    src = (ROOT / "tools" / "audit_evidence_readiness.py").read_text(encoding="utf-8")
    for token in [
        "impact_audit",
        "selection_impact",
        "broker_impact",
        "evidence_nonzero_ticker_count",
        "Nonzero evidence is necessary but not sufficient",
    ]:
        assert token in src, f"evidence readiness audit missing {token}"


@_test("structural.phase_g_requires_broker_ledger_official_metrics")
def test_phase_g_requires_broker_ledger_official_metrics() -> None:
    wf_path = ROOT / ".github" / "workflows" / "phase_g_crisis_evidence_liquidity_replay.yml"
    assert wf_path.exists(), "Phase G crisis evidence liquidity workflow missing"
    wf = wf_path.read_text(encoding="utf-8")
    tool = (ROOT / "tools" / "build_crisis_governed_target_books.py").read_text(encoding="utf-8")
    for token in ["--run-broker-replay", "cost_bps", "phase_g_crisis_evidence_liquidity", "--require-learned-thresholds"]:
        assert token in wf, f"Phase G workflow missing broker-ledger token {token}"
    for token in ["decision_summary.json", "crisis_governed_broker_metrics.csv", "promotion_allowed_without_human_approval", "broker_ledger_next_close", "next_close", "learned_thresholds_required_but_missing"]:
        assert token in tool, f"Phase G decision output missing {token}"


@_test("structural.sec_13f_refresh_uses_historical_submissions")
def test_sec_13f_refresh_uses_historical_submissions() -> None:
    wf = (ROOT / ".github" / "workflows" / "sec_13f_quarterly_refresh.yml").read_text(encoding="utf-8")
    collector = (ROOT / "tools" / "run_sec_submissions_collector.py").read_text(encoding="utf-8")
    for token in ["--include-older-submissions", "history_start", "2018-01-01", "max_filings", "1500"]:
        assert token in wf, f"SEC 13F workflow missing historical backfill token {token}"
    for token in ["SUBMISSIONS_ARCHIVE_URL", "filings.files", "include_older_submissions", "history_start"]:
        assert token in collector, f"SEC submissions collector missing historical archive token {token}"


@_test("structural.daily_crisis_monitor_uses_canonical_state_and_shakeout_guard")
def test_daily_crisis_monitor_uses_canonical_state_and_shakeout_guard() -> None:
    src = (ROOT / "tools" / "run_daily_crisis_monitor.py").read_text(encoding="utf-8")
    engine = (ROOT / "tools" / "crisis_state_engine.py").read_text(encoding="utf-8")
    policy = (ROOT / "tools" / "run287_crisis_policy.py").read_text(encoding="utf-8")
    wf = (ROOT / ".github" / "workflows" / "daily_crisis_monitor.yml").read_text(encoding="utf-8")
    for token in [
        "GREEN",
        "WATCH",
        "DEFENSE",
        "CRISIS",
        "REENTRY_STAGE_1",
        "REENTRY_STAGE_2",
        "REENTRY_STAGE_3",
        "DEGRADED_DATA",
        "VIX-only cash raise is forbidden",
        "single_name_shakeout_cash_raise_forbidden",
        "long_crisis_daily_features.parquet",
        "best_thresholds.json",
    ]:
        assert token in src, f"daily crisis monitor missing {token}"
    for token in ["future_labels_excluded", "observable_feature_frame", "build_historical_daily_crisis_state"]:
        assert token in engine, f"shared crisis state engine missing {token}"
    for token in ["transition_state", "apply_selective_defense", "component_availability"]:
        assert token in policy, f"canonical crisis policy missing {token}"
    assert "cron:" in wf and "run_daily_crisis_monitor.py" in wf
    assert "outputs/long_crisis_learning" in wf and "data_pit/macro" in wf


# ======================================================================
# main
# ======================================================================


def main() -> int:
    global _args
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="skip import-heavy tests (Groups 3-5)")
    parser.add_argument("--verbose", "-v", action="store_true", help="print every test (default: failures only)")
    _args = parser.parse_args()

    # Discover all @_test-decorated functions in this module, preserve declaration order
    tests = [
        fn for name, fn in globals().items()
        if callable(fn) and hasattr(fn, "_test_name") and name.startswith("test_")
    ]

    if _args.quick:
        tests = [fn for fn in tests if fn._test_group in ("syntax", "structural")]  # type: ignore[attr-defined]

    print("=" * 70)
    mode = "QUICK (syntax + structural only)" if _args.quick else "FULL (all groups)"
    print(f"r1000 Quant Engine -- smoke test  [{mode}]")
    print("=" * 70)

    t_start = time.perf_counter()
    current_group = None
    for fn in tests:
        group = fn._test_group  # type: ignore[attr-defined]
        if group != current_group:
            print(f"\n[{group}]")
            current_group = group
        fn()
    total = time.perf_counter() - t_start

    print()
    print("=" * 70)
    passed = sum(1 for _, ok, _, _ in _results if ok)
    failed = len(_results) - passed
    print(f"Results: {passed}/{len(_results)} passed, {failed} failed   ({total*1000:.0f}ms)")

    if failed:
        print()
        print("FAILED TESTS:")
        for name, ok, _, err in _results:
            if not ok:
                print(f"  - {name}")
                print(f"      {err}")
        print()
        print("Fix the failures before committing. Run `py -3 tests/smoke_test.py -v` for details.")
        return 1

    print("OK -- all smoke tests pass. Safe to commit + push.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"\nsmoke test framework crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
