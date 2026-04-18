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


def _engine_src() -> str:
    global _ENGINE_SRC
    if _ENGINE_SRC is None:
        _ENGINE_SRC = ENGINE_PATH.read_text(encoding="utf-8")
    return _ENGINE_SRC


@_test("structural.phase_columns_referenced_in_feature_store")
def test_phase_columns_in_keep_cols() -> None:
    """Every top-level PHASE*_COLUMNS constant must be spliced into build_feature_store.

    Regression for: Phase 2 keepcols-fix (commit 1d4fb40), Phase 1 keepcols-fix (4cd938e).
    """
    src = _engine_src()
    # Find all PHASE*_COLUMNS module-level constants
    constants = re.findall(r"^(PHASE\w+_COLUMNS)\s*=\s*\[", src, re.MULTILINE)
    assert constants, "no PHASE*_COLUMNS constants found -- regex or repo broken"

    # Extract build_feature_store body (up to the next top-level def)
    m = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        src,
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
    """
    src = _engine_src()
    keys = re.findall(r'phase_is_enabled\s*\(\s*["\'](\w+)["\']', src)
    assert keys, "no phase_is_enabled() calls found -- regex or repo broken"
    for key in set(keys):
        assert re.match(r"^[a-z][a-z0-9_]*$", key), (
            f"phase_is_enabled key must be snake_case: {key!r}"
        )


@_test("structural.engine_reuse_version_format")
def test_engine_reuse_version() -> None:
    """ENGINE_REUSE_VERSION must be YYYY-MM-DD-description -- bumping triggers FS rebuild."""
    src = _engine_src()
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
    """
    src = _engine_src()
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
    """
    src = _engine_src()
    # Constant exists and has the expected 8 names
    assert "PHASE9_C3_TURNAROUND_COLUMNS = [" in src, "PHASE9_C3_TURNAROUND_COLUMNS constant missing"
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
    # Extract the constant body
    m = re.search(r"PHASE9_C3_TURNAROUND_COLUMNS\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "Failed to parse PHASE9_C3_TURNAROUND_COLUMNS body"
    body = m.group(1)
    missing = [c for c in required if f'"{c}"' not in body]
    assert not missing, f"PHASE9_C3_TURNAROUND_COLUMNS missing names: {missing}"

    # Build feature store function body must reference the constant twice
    # (once in keep_cols, once in hard_sanitize call)
    fn = re.search(
        r"^def build_feature_store\b.*?(?=^def |\Z)",
        src,
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
    """
    src = _engine_src()
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
    """
    src = _engine_src()
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
    """
    src = _engine_src()
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
    """
    src = _engine_src()
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


@_test("regression.phase9_c3_gate_wired_in_early_scout")
def test_phase9_c3_gate_wired() -> None:
    """Phase 9 C2 early-scout gate must call _p9_c3_admit as an OR branch.

    Regression: without this wire-up, C3 toggle is dead code even when
    the feature-store columns are present.
    """
    src = _engine_src()
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
