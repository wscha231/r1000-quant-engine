# Refactor Plan — r1000_top30_institutional.py (27k lines → modular)

**Date**: 2026-04-17
**Status**: PLANNED (execute AFTER Phase 8 FULL rebuild ships)
**Owner**: next coding session

---

## 1. Why refactor

The single-file engine `r1000_top30_institutional.py` has grown to 27,000+ lines. This is causing:

1. **Agent comprehension limit**: 27k lines exceeds typical agent context windows. Reviews fall back to grep, missing cross-cutting patterns. **Evidence**: the Phase 2 keepcols-fix (commit `1d4fb40`) and Phase 1 keepcols-fix (commit `4cd938e`) were the same class of silent bug discovered on separate occasions. A modular boundary would have forced the invariant explicitly.

2. **Review friction**: the Phase 8 pre-rebuild audit required two separate agent passes + manual grep. Each review takes 5-10 minutes just to triangulate the right code. A modular structure would make reviews mechanical.

3. **Cross-cutting bugs**: silently introduced in one area surface in another. Examples:
   - `row_mean` + `weighted_sleeve_composite` weight-0 dilution (caught in Phase 8 review by an agent)
   - `r_1m` lookahead bias in `hold_persistence_bonus` (caught by manual trace of column meaning)
   - env-var name mismatch (Phase 8 toggles vs. `phase_is_enabled()` key format; caught by toggle test)

4. **Phase 8e (r_12m ML) risk**: the deferred retrain-against-r_12m work requires walk-forward refactor. In a single file, identifying the touch surface is ambiguous. In a modular structure, it would be obvious which module owns what.

## 2. Scope

**In scope**:
- Physically split `r1000_top30_institutional.py` into a small number of domain-focused modules
- Preserve backward compatibility via a thin facade at the original path
- No behaviour changes (functions keep identical signatures and outputs)
- Verify byte-exact output via QUICK_RESCORE run before/after

**Out of scope**:
- Converting to object-oriented style (classes) — existing functional style stays
- Changing function signatures, renaming public symbols
- Bundling any new features with the refactor
- Restructuring `r1000_data_collector.py`, `r1000_portfolio_state.py`, `r1000_operator.py` (already reasonably sized)

## 3. Two-phase strategy

### Phase A — flat 5-module split (1-1.5 day, low risk)

Five files + one backward-compat facade. Natural domain boundaries. Easy to migrate because each function simply moves to a different file with identical signature.

```
r1000_config.py           EngineConfig + every PHASE_*_COLUMNS constant + DEFAULT_FEATURES +
                          module-level constants (ENGINE_REUSE_VERSION, CASH_PROXY_TICKER, etc)
                          ~2,500 lines

r1000_helpers.py          row_mean / weighted_sleeve_composite / rolling_robust_z /
                          cross_sectional_robust_z / winsorize / numeric_series_or_default /
                          hard_sanitize / phase_is_enabled / reuse_fingerprint
                          ~500 lines

r1000_features.py         compute_price_features + compute_fundamental_features +
                          add_fundamental_features + compute_valuation_columns +
                          compute_macro_interaction_features + compute_live_factor_columns +
                          compute_latest_flow_factor_columns + build_macro_regime_table +
                          compute_macro_regime_features + compute_event_regime_features +
                          compute_moat_proxy_features + compute_dynamic_leadership_features +
                          compute_three_level_relative_strength + compute_crisis_sector_fit
                          ~6,000 lines

r1000_signals.py          compute_strategy_blueprint_columns (Phase 1) +
                          Phase 2 industry helpers (attach_industry_metadata +
                          add_industry_relative_strength + compute_oneil_leadership_score +
                          add_industry_rotation_signal) +
                          add_sub_industry_leader_laggard_signals (Phase 5) +
                          compute_multidimensional_pillar_scores +
                          compute_minervini_momentum_overlay +
                          compute_portfolio_sleeve_columns (Phase 3/4/7a/8a/8b/8c/8d) +
                          compute_portfolio_sleeve_policy + resolve_regime_sleeve_multipliers
                          ~6,000 lines

r1000_pipeline.py         build_universe_monthly + build_feature_store +
                          train_walkforward + backtest_portfolio variants +
                          score_latest_month + prepare_latest_scored_data +
                          run_default_pipeline + write_stage_coverage_report +
                          all acceptance_checks helpers
                          ~8,000 lines

r1000_top30_institutional.py   THIN FACADE — re-exports every public symbol from the 5
                               modules so existing imports (`from r1000_top30_institutional
                               import X`) keep working. ~100 lines, 95% re-exports.
```

### Phase B — granular sub-module split (optional, 1-2 day)

After Phase A ships and we have a stable baseline, evaluate whether individual files still feel too large (specifically `features`, `signals`, `pipeline` at 6-8k lines each). If yes, convert to packages:

```
r1000_quant/
├── __init__.py
├── config.py
├── helpers.py
├── features/
│   ├── price.py
│   ├── fundamental.py
│   ├── macro.py
│   ├── valuation.py
│   └── events.py
├── signals/
│   ├── blueprints.py        # Phase 1 + Multi-pillar
│   ├── industry.py          # Phase 2
│   ├── sub_industry.py      # Phase 5
│   ├── long_lookback.py     # Phase 8b
│   └── minervini.py
├── sleeves/
│   ├── composite.py         # Phase 3/4/7a/8a/8b/8c/8d
│   ├── labeling.py          # Phase 8c.1 megacap override
│   └── policy.py
└── pipeline/
    ├── universe.py
    ├── feature_store.py
    ├── walkforward.py
    ├── backtest.py
    ├── latest_scoring.py
    └── run_default.py
```

Trigger for Phase B:
- Any single file > 5,000 lines after Phase A stabilises
- OR a new phase (e.g. Phase 8e r_12m ML) would require cross-file refactor anyway

## 4. Non-goals (reject)

### 4a. Object-oriented conversion

Gemini's 2026-04-17 review suggested a `FeatureEngineer` class with `compute_technical_indicators`, `compute_sage_scores` etc. as methods. **Rejected.**

Reasons:
- Current code is 100% functional at module level. Every `compute_*(df, cfg)` signature is stateless.
- OO wrap would change every call site from `compute_price_features(...)` to `FeatureEngineer(cfg).compute_price_features(...)` — touches hundreds of call sites.
- Python modules ALREADY act as namespaces; `from r1000_features import compute_price_features` gives the same grouping without class overhead.
- Zero functional benefit: no shared mutable state between these functions that a class would encapsulate.
- "New feature extension" argument (Gemini's pitch) is equivalently satisfied by adding a function to the relevant module.

Verdict: keep functions as functions; modules serve as the grouping.

### 4b. Premature granularity

Gemini's 4-module suggestion is close to Phase A but lumps configs into features. Our Phase A slightly differs: separates `config.py` and `helpers.py` so pure helpers don't drag in EngineConfig.

Our 14-module proposal (earlier version) is premature — jumping from 1 file to 14 is too risky for a first pass. Phase A (5 files) is the right starting point. Phase B granularity comes later, DATA-DRIVEN (only if modules actually feel too big in practice).

## 5. Timing

DO NOT refactor until ALL these conditions hold:

1. **Phase 8 FULL rebuild CAGR verdict is known**: ship / partial-ship / regression.
2. **Baseline is documented**: if Phase 8 ships, the post-Phase-8 `backtest_metrics.json` is committed as the new baseline reference.
3. **No Phase 8 regression remediation in flight**: if CAGR regresses < 18% and we're mid-investigation, defer.
4. **User is free for 1-1.5 days**: refactor is best done in a single uninterrupted session to catch migration issues.

Estimated earliest start: ~24-48h after Phase 8 rebuild finishes, assuming CAGR ships ≥ 25%.

## 6. Execution checklist (Phase A)

### Pre-flight
- [ ] Confirm Phase 8 baseline CAGR committed to CHANGELOG
- [ ] Run a QUICK_RESCORE on master, capture `scored_latest.csv` SHA256 as reference
- [ ] Create branch `refactor/phase-a-module-split`

### Migration order
1. [ ] Create `r1000_config.py` — move EngineConfig + all `PHASE_*_COLUMNS` + DEFAULT_FEATURES + module constants
2. [ ] Create `r1000_helpers.py` — move pure helpers (no cfg dependency)
3. [ ] Update original file: `from r1000_config import *; from r1000_helpers import *` at top
4. [ ] `py_compile` + `import` + QUICK_RESCORE smoke test; expect byte-exact output
5. [ ] Create `r1000_features.py` — move price / fundamental / macro / valuation / events
6. [ ] `py_compile` + `import` + QUICK_RESCORE smoke test
7. [ ] Create `r1000_signals.py` — move blueprints / industry / sub_industry / long_lookback / sleeve composition
8. [ ] `py_compile` + `import` + QUICK_RESCORE smoke test
9. [ ] Create `r1000_pipeline.py` — move build_universe_monthly / build_feature_store / walkforward / backtest / scoring / run_default
10. [ ] `py_compile` + `import` + QUICK_RESCORE smoke test
11. [ ] Reduce `r1000_top30_institutional.py` to facade: `from r1000_config import *; from r1000_helpers import *; ...`
12. [ ] QUICK_RESCORE **on the facade-only entry point** — output must byte-exact match pre-refactor
13. [ ] `scored_latest.csv` SHA256 comparison — MUST match reference

### Byte-exact verification
Run pipeline with identical config pre-refactor and post-refactor. Diff outputs:
- `outputs/scored_latest.csv` — identical SHA256
- `outputs/backtest_metrics.json` — identical content (float equality up to 1e-10)
- `outputs/portfolio_latest.csv` — identical SHA256
- `feature_store/feature_store_latest.parquet` — may differ in metadata but row data identical

If byte-exact check fails: find the divergence via `diff` + `pd.testing.assert_frame_equal`, fix, retest.

### Post-flight
- [ ] CHANGELOG entry under Agent Update Contract format
- [ ] SESSION_HANDOFF.md rewrite §2 pointing at new module map
- [ ] CLAUDE.md "Key Files" section updated
- [ ] PHASE_ROADMAP.md Invariants #8 restated: "Any new phase column constant MUST be in `r1000_config.py` AND imported into `r1000_pipeline.py.build_feature_store` keep_cols"
- [ ] Merge branch → master

## 7. Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Import cycle after split | MED | Dependency order: config → helpers → features → signals → pipeline. Each layer imports only from prior layers. |
| Forgotten helper function left in original file | LOW | `python -c "from r1000_top30_institutional import *; print(dir())"` before/after diff |
| Hidden module-level state (e.g. cache dicts) gets duplicated | LOW | grep for module-level assignments that aren't constants; ensure each is owned by exactly one new module |
| Byte-exact test fails due to ordering non-determinism | LOW | If dicts introduced in any layer, use `sorted()` to enforce key order |
| User starts a new feature mid-refactor | MED | Lock in: refactor happens in a focused session. No concurrent feature work. |
| Regression not caught by QUICK_RESCORE (tests only latest-scoring path) | LOW | Also run FULL rebuild on a small universe subset (e.g. `universe_size=50`) for walk-forward integrity check |

## 8. What this unblocks

Once Phase A completes:

1. **Phase 8e (r_12m ML training)**: now isolated to `r1000_pipeline.py::train_walkforward`. Add a parallel r_12m model bundle alongside the r_1m one. Blend scores in `score_latest_month`.

2. **Phase 8f (factor cluster consolidation)**: the "industry cluster has 6 overlapping signals" finding would be addressed by adding a `compute_industry_composite()` helper in `r1000_signals.py::industry`.

3. **Unit tests**: add `tests/test_features.py`, `tests/test_signals.py` — at last possible because each module has < 10 public functions.

4. **Agent-driven feature work**: a single agent can read `r1000_signals.py` (~6k lines) fully and reason about sleeve composition coherently. Not possible today with 27k lines.

5. **Merge conflict reduction**: if someone ever joins, file-level locks replace 27k-line-file-level conflicts.

## 9. Reference — alternative views

- **Gemini 2026-04-17 review**: suggested 4 modules (config / features / models / backtest) + OO `FeatureEngineer` class. OO idea rejected (see §4a); 4-module count increased to 5 by separating `config.py` and `helpers.py`.
- **Initial Claude proposal (same day)**: 14 modules in `r1000_quant/` package. Deferred to Phase B; we start flat first.

## 10. Single biggest lesson

The bugs we caught during Phase 8 audit (weight-0 dilution, r_1m lookahead, env-name `_ENABLED` missing suffix) were caught by:
- Agent review (weight-0)
- Manual trace of data meaning (r_1m)
- Toggle functional test (env name)

A modular structure wouldn't have automatically caught those — but it **would have surfaced the code locations faster** and made the fix surface smaller. The real win isn't bug *prevention* but bug *localisation*.

Refactor ROI = time saved on all future reviews × number of future reviews. On a 2-year horizon, 1.5 days of refactor pays back ~20x.

---

## 11. Observability & Attribution — diagnose WHICH module broke

Splitting files alone is half the win. The other half is building **fault-isolation infrastructure** so that when CAGR drops or a run crashes, we know **within seconds** which module is responsible instead of grep-bisecting across the codebase.

This section adds six observability primitives that ship AS PART of the refactor (Phase A), not as a follow-up.

### 11.1 Module boundary decorator — error containment + identity

Every public function of every module is wrapped in a standard decorator that:

1. Tags exceptions with the module identity (stack trace still intact, but error message leads with `[module_name] raised KeyError: ...`).
2. Records entry/exit timing + row counts.
3. Optionally returns a safe fallback (zero-fill) when `PHASE_SAFE_DEGRADE=1` is set.

```python
# r1000_helpers.py
import functools, time, logging

def module_boundary(module_name: str, *, safe_degrade_fallback=None):
    """Wrap every module's public function with identity + timing + optional fallback.
    
    Usage:
      @module_boundary("signals.industry")
      def compute_oneil_leadership_score(monthly): ...
    
    On failure: re-raises with prepended `[signals.industry]` tag.
    On PHASE_SAFE_DEGRADE=1: returns safe_degrade_fallback(*args, **kwargs) if provided.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                out = fn(*args, **kwargs)
                dt = time.perf_counter() - t0
                # Log on debug mode only
                if os.environ.get("PHASE_DEBUG_MODULE_TRACE") == "1":
                    n_rows = len(out) if hasattr(out, "__len__") else "-"
                    n_cols = len(out.columns) if hasattr(out, "columns") else "-"
                    logging.info(f"[{module_name}] {fn.__name__} -> {n_rows}x{n_cols} in {dt*1000:.1f}ms")
                return out
            except Exception as e:
                dt = time.perf_counter() - t0
                tagged = f"[{module_name}] {fn.__name__} raised {type(e).__name__} after {dt*1000:.1f}ms: {e}"
                if os.environ.get("PHASE_SAFE_DEGRADE") == "1" and safe_degrade_fallback is not None:
                    logging.error(tagged + " — returning safe fallback (PHASE_SAFE_DEGRADE=1)")
                    return safe_degrade_fallback(*args, **kwargs)
                raise type(e)(tagged) from e
        return wrapper
    return decorator
```

**Effect when something breaks**:
```
BEFORE refactor:
  KeyError: 'oneil_leadership_score'
  File "r1000_top30_institutional.py", line 18499, in compute_portfolio_sleeve_columns
    (0.55, cross_sectional_robust_z(d, "oneil_leadership_score")),
  ... (unclear which upstream module failed to produce it)

AFTER refactor + boundary:
  KeyError: [signals.industry] compute_oneil_leadership_score raised KeyError after 0.3ms: 
  'rs_industry_6m' — upstream industry metadata missing for row 472 (TSLA 2019-05)
  File "r1000_quant/signals/industry.py", line 145, in compute_oneil_leadership_score
```

Instantly points at `signals.industry` instead of `sleeves.composite`.

### 11.2 Per-module health check — validate outputs before return

Each module ships a `_validate_<fn>_output(df)` function that runs coverage + range + schema checks. Called automatically on return when `PHASE_STRICT_VALIDATION=1`:

```python
# r1000_quant/features/macro.py
def _validate_macro_regime_output(macro: pd.DataFrame) -> None:
    """Assert the macro frame shape + coverage + range + schema."""
    # Schema: all MACRO_REGIME_COLUMNS present
    missing = [c for c in MACRO_REGIME_COLUMNS if c not in macro.columns]
    assert not missing, f"[features.macro] missing {len(missing)} columns: {missing[:5]}"
    # Coverage: at least 80% of rows in recent 5y should have non-NaN
    recent = macro[macro["macro_date"] >= "2021-01-01"]
    for col in ["stagflation_score", "growth_liquidity_reentry_score"]:
        cov = recent[col].notna().mean()
        assert cov > 0.80, f"[features.macro] {col} coverage {cov:.1%} < 80%"
    # Range: z-score style columns stay in [-6, 6] after macro clamp
    for col in ["stagflation_score", "labor_softening_score"]:
        abs_max = macro[col].abs().max()
        assert abs_max <= 6.1, f"[features.macro] {col} abs_max={abs_max:.2f} exceeds clamp [-6,6]"
```

**Effect**: the 2024-06 `labor_softening_score = -2e14` bug would have been caught at the module boundary instead of propagating silently to every stock score. Validation cost: microseconds. Benefit: catastrophic bugs localised on the spot.

### 11.3 Column ownership registry — "who wrote this column?"

A central dict in `r1000_config.py`:

```python
# r1000_config.py
COLUMN_OWNERSHIP = {
    # Price features (features.price)
    "mom_1m": "features.price",
    "mom_3m": "features.price",
    "mom_18m": "features.price",
    "mom_24m": "features.price",
    "mom_36m": "features.price",
    "dist_ma200": "features.price",
    # Fundamentals (features.fundamental)
    "ep_ttm": "features.fundamental",
    "fcfy_ttm": "features.fundamental",
    "sp_ttm": "features.fundamental",
    "roe_proxy": "features.fundamental",
    # Phase 1 blueprint (signals.blueprints)
    "fundamental_turnaround_acceleration_score": "signals.blueprints",
    "value_inflection_score": "signals.blueprints",
    "uptrend_continuation_score": "signals.blueprints",
    # Phase 2 industry (signals.industry)
    "industry_group_strength_score": "signals.industry",
    "oneil_leadership_score": "signals.industry",
    "industry_rotation_signal": "signals.industry",
    "rs_industry_6m": "signals.industry",
    # Phase 5 (signals.sub_industry)
    "industry_leader_gap": "signals.sub_industry",
    # Phase 8b (signals.long_lookback)
    "multi_year_winner_score": "signals.long_lookback",
    "persistence_trend_24m": "signals.long_lookback",
    # Phase 8a/b/c/d diagnostic flags (sleeves.composite)
    "hold_persistence_bonus": "sleeves.composite",
    "long_horizon_alpha_composite": "sleeves.composite",
    "phase8a_hold_persistence_active": "sleeves.composite",
    "phase8b_long_lookback_active": "sleeves.composite",
    "phase8c_megacap_override_active": "sleeves.composite",
    "phase8d_ic_reweight_active": "sleeves.composite",
    "phase8d_long_horizon_alpha_active": "sleeves.composite",
    # ... (all columns mapped)
}

def owning_module(column: str) -> str:
    """Return the module responsible for producing `column`, or 'unknown'."""
    return COLUMN_OWNERSHIP.get(column, "unknown")
```

**Benefits**:
- Debug: "why is `ep_ttm` zero for 40% of rows?" → `owning_module("ep_ttm")` = `features.fundamental` → look there
- Automated check at pipeline end: warn if a column with a known owner is MISSING or has < 50% coverage
- Cross-module boundary check: each module can only WRITE columns it OWNS (enforced by test)

### 11.4 Performance attribution — which phase added or subtracted CAGR

At the end of `backtest_portfolio`, generate `outputs/reports/module_contribution_report.csv`:

```
module              factor_count  avg_monthly_contribution  cum_return_impact  rank
features.fundamental        14                     0.0046          +0.0850    1
signals.blueprints           5                     0.0038          +0.0620    2
signals.industry            11                     0.0015          +0.0240    3
signals.long_lookback        5                     0.0024          +0.0385    4  (Phase 8b)
sleeves.composite (p8a.4)    1                     0.0018          +0.0290    5  (hold persistence)
sleeves.composite (p8c.1)    1                    -0.0003          -0.0048    6  (megacap override net-negative)
features.macro               8                    -0.0009          -0.0150    7
signals.sub_industry         3                     0.0001          +0.0015    8  (Phase 5 — near-zero)
signals.industry rotation    1                    -0.0012          -0.0196   ❌  (industry_rotation_signal — already dropped by 8a.1)
```

Computation: for each ticker-month, attribute the final `score` decomposition to source modules (via `COLUMN_OWNERSHIP`). Aggregate across backtest.

**Effect**: post-run, one CSV shows **exactly which module added how much CAGR**. If next iteration CAGR drops 3pp, diff two reports → find the module that lost contribution.

### 11.5 Debug verbose mode — per-row per-module trace

Environment variable `PHASE_DEBUG_MODULE_TRACE=1` activates:

- Every module function logs entry/exit with runtime + row/col count (11.1 already has this)
- `build_feature_store` emits `outputs/reports/module_trace.csv` with:
  ```
  module              rows_in  rows_out  cols_added  cols_dropped  runtime_ms  memory_delta_mb
  features.price        51100    51100          25             0       1250               +8.4
  features.fundamental  51100    48200          42             3      15200              +22.1
  features.macro        48200    48200          49             0       3100               +4.2
  signals.blueprints    48200    48200          34             0       8900              +12.3
  signals.industry      48200    48200          24             0       6200               +9.8
  ...
  ```
- `score_latest_month` emits `outputs/reports/latest_score_module_trace.csv` with per-name per-module contribution

Cost: ~5% runtime overhead when ON, zero when OFF. Default OFF.

### 11.6 Module-level smoke tests — CI-ready unit tests

`tests/` directory ships with the refactor:

```
tests/
├── test_helpers.py           # rolling_robust_z edge cases, weight-0 skip, etc.
├── test_features_price.py    # mom_* computation on synthetic price series
├── test_features_fundamental.py
├── test_features_macro.py    # macro clamp, 1e14 corruption regression test
├── test_signals_blueprints.py  # Phase 1 signals on 3-ticker synthetic fundamentals
├── test_signals_industry.py    # O'Neil + rotation on synthetic industry groups
├── test_signals_long_lookback.py  # Phase 8b composites
├── test_sleeves_composite.py   # Phase 3/4/7a/8a/b/c/d toggle interactions
├── test_pipeline_universe.py   # build_universe_monthly on tiny synthetic universe
├── test_pipeline_backtest.py   # Phase 6a/b/c on synthetic equity curve
└── test_integration.py          # full mini-run, asserts no schema regressions
```

Each test ~50-200 lines. Total ~2,000 lines of test code. Runs in < 30s (synthetic data, no actual fetches).

**Regression tests** pinned to known bugs:
- `test_helpers::test_weighted_sleeve_composite_skips_weight_zero` — the Phase 8 agent-caught bug
- `test_features_macro::test_rolling_robust_z_survives_near_zero_mad` — the 2024-06 bug
- `test_sleeves_composite::test_hold_persistence_uses_mom_1m_not_r_1m` — the lookahead bug

### 11.7 Execution addition — what changes in §6 checklist

Add to the Phase A execution checklist (between step 11 and 12):

```
11.5 [ ] Add @module_boundary to every public function in each new module
11.6 [ ] Add _validate_<fn>_output() for every public function
11.7 [ ] Populate COLUMN_OWNERSHIP in r1000_config.py
11.8 [ ] Wire module_contribution_report.csv into backtest_portfolio end
11.9 [ ] Create tests/ directory with 10 smoke test files + regression pins
11.10[ ] Verify PHASE_DEBUG_MODULE_TRACE=1 produces module_trace.csv
11.11[ ] Verify PHASE_SAFE_DEGRADE=1 on a simulated module failure returns zero-fill
```

### 11.8 Return on investment — why this is the real win

| Scenario | Without observability | With observability |
|---|---|---|
| Pipeline crashes mid-run | Traceback + manual grep to find owning module (10-30 min) | `[signals.industry]` tag in error message (instant) |
| CAGR drops 3pp on next A/B | Manual bisect across phases (hours) | Diff two `module_contribution_report.csv` (minutes) |
| One column has 50% NaN | Grep across file to find who wrote it (15 min) | `owning_module(col)` lookup (seconds) |
| New phase adds dilution bug | Caught only by lucky agent review | Weight-0 unit test catches it on first commit |
| Silent NaN propagation from macro | Surfaces in final backtest numbers | Module health check catches at module boundary |

Expected payoff: **5-10x faster debugging on every future regression**. 1-1.5 day refactor + observability pays back within the FIRST post-refactor bug.

### 11.9 Why bundle this with the refactor (not add later)

- Adding `@module_boundary` AFTER the split requires touching every function again. **4x more work.**
- `COLUMN_OWNERSHIP` is natural to populate while moving code (you know which module you just wrote).
- Test stubs are cheap to write WHILE the function is in front of you, not months later.
- `PHASE_DEBUG_MODULE_TRACE` requires wiring once at split time; retrofitting means touching the whole pipeline again.

**Rule**: observability scaffolding ships in the same commit as the module split. No exceptions.
