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
import json
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
    """
    combined = _combined_src()
    # Find all PHASE*_COLUMNS module-level constants (main OR config file)
    constants = re.findall(r"^(PHASE\w+_COLUMNS)\s*=\s*\[", combined, re.MULTILINE)
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
    """Phase 15-R1 (2026-04-21): trailing stop config fields + safe defaults.

    The trailing stop extends the -25% hard stop with a peak-relative exit for
    early_scout. To keep it A/B-gated, the toggle (`trailing_stop_enabled`) must
    default to False — enabling happens only when both the cfg flag AND the
    PHASE_PHASE15_R1_TRAILING_ENABLED env var are on (dual-gate).

    This test locks: (a) the fields exist, (b) enable flag defaults to False,
    (c) future_winner pct defaults to 0.0 (i.e. only early_scout trails out of
    the box — A/B cell D has to opt-in).
    """
    src = _combined_src()
    # Field existence (check for the full typed declaration to catch typos)
    assert re.search(r"^\s*trailing_stop_enabled\s*:\s*bool\s*=\s*False",
                     src, re.MULTILINE), \
        "trailing_stop_enabled: bool = False missing from EngineConfig"
    assert re.search(r"^\s*trailing_stop_early_scout_pct\s*:\s*float\s*=",
                     src, re.MULTILINE), \
        "trailing_stop_early_scout_pct field missing"
    assert re.search(r"^\s*trailing_stop_future_winner_pct\s*:\s*float\s*=\s*0\.0",
                     src, re.MULTILINE), \
        "trailing_stop_future_winner_pct must default to 0.0 (opt-in for cell D)"


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


@_test("regression.paper_executor_workflow_yaml_valid")
def test_paper_executor_workflow() -> None:
    """The cloud workflow that runs r1000_paper_executor.py must exist with
    workflow_dispatch + schedule, properly wire ALPACA secrets, and call
    smoke_test as a pre-flight check.

    History:
      45d80f5 spam fix in data_alpaca
      this    paper_executor_dryrun.yml — cloud-side dry-run / execute

    Without this guard, a refactor that drops the workflow file silently
    disables cloud paper trading.
    """
    wf_path = ROOT / ".github" / "workflows" / "paper_executor_dryrun.yml"
    assert wf_path.exists(), "paper_executor_dryrun.yml workflow missing"
    wf = wf_path.read_text(encoding="utf-8")
    assert "workflow_dispatch" in wf, "manual trigger missing in paper_executor workflow"
    assert "secrets.ALPACA_API_KEY" in wf, "ALPACA_API_KEY secret not wired"
    assert "secrets.ALPACA_API_SECRET" in wf, "ALPACA_API_SECRET secret not wired"
    assert "tests/smoke_test.py" in wf, (
        "smoke_test pre-flight missing — workflow could ship code that fails guards"
    )
    assert "r1000_paper_executor.py" in wf, "paper_executor not actually invoked"
    assert "yfinance" in (ROOT / "requirements_github.txt").read_text(encoding="utf-8"), (
        "yfinance missing from requirements_github.txt — Layer 3 VIX fetch will fall back"
    )


@_test("regression.paper_executor_weekday_schedule")
def test_paper_executor_weekday() -> None:
    """paper_executor_dryrun.yml must have weekday schedule (Mon-Fri 23:30 KST)
    in addition to Saturday 15:00 KST. Phase 5 J — daily review enables user
    to see regime + plan via Telegram each weekday before --execute decision.
    """
    wf = (ROOT / ".github" / "workflows" / "paper_executor_dryrun.yml").read_text(encoding="utf-8")
    assert "30 14 * * 1-5" in wf, (
        "weekday Mon-Fri 14:30 UTC schedule missing in paper_executor_dryrun.yml"
    )
    assert "0 6 * * 6" in wf, (
        "Saturday 06:00 UTC schedule must remain"
    )


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
    """Phase 6 L: tools/monthly_ic_monitor.py + workflow must exist with
    monthly cadence (cron 0 2 1 * *) and Telegram alerting on threshold trips.

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

    wf = ROOT / ".github" / "workflows" / "monthly_ic_monitor.yml"
    assert wf.exists(), "monthly_ic_monitor.yml workflow missing"
    wf_src = wf.read_text(encoding="utf-8")
    for tok in ("0 2 1 * *", "monthly_ic_monitor.py", "TELEGRAM_BOT_TOKEN",
                "FRED_API_KEY", "tests/smoke_test.py"):
        assert tok in wf_src, f"monthly_ic_monitor.yml missing: {tok}"


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
    """layer4_monthly_swap.yml workflow runs Layer 4 swap on 5th of each month.
    Schedule + workflow_dispatch + ALPACA secrets + Telegram secrets must all
    be wired or the auto-apply doesn't actually happen.
    """
    wf_path = ROOT / ".github" / "workflows" / "layer4_monthly_swap.yml"
    assert wf_path.exists(), "layer4_monthly_swap.yml missing"
    wf = wf_path.read_text(encoding="utf-8")
    for token in (
        "schedule:",
        "0 14 5 * *",                  # 5th of month, 23:00 KST
        "workflow_dispatch:",
        "secrets.ALPACA_API_KEY",
        "secrets.TELEGRAM_BOT_TOKEN",
        "r1000_layer4_swap.py",
    ):
        assert token in wf, f"layer4_monthly_swap.yml missing: {token}"


@_test("regression.full_rebuild_workflow_exists")
def test_full_rebuild_workflow() -> None:
    """full_rebuild_manual.yml workflow must exist with workflow_dispatch
    inputs (universe_mode, skip_collector) and ENGINE_REUSE_VERSION
    sensitivity (it runs FULL rebuild = the only way to invalidate cache
    after a Phase 14 schema change).

    User mandate (2026-04-25): "둘 다" — both local + GitHub Actions paths
    for FULL rebuild so user PC isn't a single point of failure.
    """
    wf_path = ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"
    assert wf_path.exists(), "full_rebuild_manual.yml workflow missing"
    wf = wf_path.read_text(encoding="utf-8")
    for token in (
        "workflow_dispatch",
        "universe_mode",
        "skip_collector",
        "secrets.ALPACA_API_KEY",
        "secrets.FINNHUB_API_KEY",
        "tests/smoke_test.py",
        "ENGINE_REUSE_VERSION",
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
      adr_universe.yaml is the canonical whitelist (mcap>=$30B, NYSE/NASDAQ).
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
