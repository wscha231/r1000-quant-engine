# Refactor Phase A — Stage 3d Execution Plan

**Branch**: `refactor/phase-a-module-split`
**Prerequisite**: Stage 1 rollup BYTE-EXACT MATCH confirmed via `verify.py`
**Target file**: `r1000_features.py` (currently 1,923 lines → expected ~4,000+ after 3d)
**Main engine before 3d**: 23,582 lines
**Main engine after 3d (estimated)**: ~20,500 lines

---

## 🟢 EXECUTION LOG (actual, 2026-04-20)

Sub-stages executed in order 3d-i-prep → 3d-i → 3d-ii-min → 3d-iii → 3d-iv.
Smoke tests 25/25 pass at every commit. Identity + scope checks verified
for each sub-stage.

| Commit | Sub-stage | Main delta | Notes |
|---|---|---|---|
| `2631e62` | 3d-i-prep | -32L | 4 CIK normalization helpers -> helpers.py (unblocks 3d-i) |
| `6b172a3` | 3d-i | -559L | `_flexible_lag` + `_cagr_from_lag` + `recompute_fund_panel_derived_columns` (458L). Phase 9 C3 nested `_sign_flip_pos` / `_loss_narrowing_rate` / `_under_loss_growth` scope PRESERVED. |
| `466ba27` | 3d-ii-min | -194L | `compute_event_regime_features` + `sector_indicator` + `compute_macro_interaction_features` (pure transforms). |
| `54986f7` | 3d-iii | -546L | 6 funcs: `compute_market_adaptation_features`, `compute_dynamic_leadership_features`, `load_manual_moat_overrides`, `apply_manual_ticker_overlays`, `compute_three_level_relative_strength`, `compute_crisis_sector_fit`. Nested `within_group_z` scope preserved. |
| `b2f4331` | 3d-iv | -1,246L | `compute_strategy_blueprint_columns` (926L), `compute_multidimensional_pillar_scores` (186L), `compute_minervini_momentum_overlay` (144L). Nested `sector_median` scope preserved. |

**Total 3d impact**: main 23,594 → 21,043 lines (-2,551 / -10.8% within Stage 3d).
Cumulative main engine reduction vs pre-refactor: **27,838 → 21,043 (-24.4%)**.
r1000_features.py: 1,923 → 4,598 lines.

### 3d-ii-b DEFERRED

The big macro builders (`load_fred_series`, `build_macro_regime_table` 417L,
`build_live_event_alert_table` 187L, merge helpers) were NOT moved in this
pass because they cascade into 5 main-file helpers that still need to
migrate to helpers.py first:

- `ensure_prices_cached_incremental` (95L) -> helpers or features (price fetch cascade)
- `load_px` (12L) -> helpers (price cache reader)
- `macro_cache_file` (2L) -> helpers (path helper)
- `price_close_series` (9L) -> helpers (close series extractor)
- `write_stage_coverage_report` (15L) -> helpers (IO report writer)

These in turn cascade into `load_fail_tickers` / `save_fail_tickers` /
`update_one_ticker_incremental` / `download_yf_price_batch` /
`merge_price_cache_frame` / `chunked` (already moved). Best tackled
as a dedicated "price cache cascade" prep commit before 3d-ii-b.

Estimated 3d-ii-b work: 1-2h. Main impact: -850L to -1,000L. Safe to defer
to post-verify since it doesn't block Stage 4 (signals) or Stage 5 (pipeline).

---

## Scope summary

Stage 3d completes the feature-engineering extraction by moving the remaining
`compute_*` / `add_*` / `build_*` / `merge_*` functions that produce
per-ticker per-rebalance-date feature columns. Splits into 4 micro-stages
(3d-i through 3d-iv) so bisection is cheap if any stage breaks byte-exact.

**Out of scope for 3d** (reserved for Stage 4-5):
- `compute_portfolio_sleeve_columns` (1,028L) — sleeve composite + Phase 9 gate → Stage 4
- `compute_portfolio_sleeve_policy` (222L) — sleeve target weights → Stage 4
- `build_target_portfolio` (739L) — portfolio construction → Stage 4
- `compute_regime_portfolio_controls` (349L) — regime-conditional sleeve multipliers → Stage 4
- `compute_benchmark_beating_focus_overlay` (260L) — focus overlay → Stage 4
- `train_walkforward` (443L) — ML training → Stage 5
- `backtest_portfolio` (694L) — backtest loop → Stage 5
- `export_outputs` (1,622L) — IO → Stage 5
- `run_all`, `run_default_pipeline`, `run_last_n_years_backtest` — pipeline entry → Stage 5
- `build_feature_store` (224L) — orchestrator → Stage 5
- `build_universe_monthly` (321L) — orchestrator → Stage 5
- All `_legacy_unused_*` (~2,500L across 12 functions) → Stage 4 Subtractive pass (delete)

---

## Sub-stage breakdown

### Stage 3d-i — Fundamental panel builders (the Phase 9 C3-sensitive block)

**Size**: ~1,100 lines across 7 functions.
**Risk**: HIGHEST in Stage 3d. Contains Phase 9 C3 critical `_sign_flip_pos`,
`_loss_narrowing_rate`, `_under_loss_growth` nested helpers that drive the
early_scout gate. Move must preserve exact call graph + scope.

**Functions to move** (pre-move line numbers):

| Line | Function | Size | Notes |
|---|---|---|---|
| 7710 | `_flexible_lag` | 78L | Quarter-offset date helper used by CAGR computation |
| 7805 | `recompute_fund_panel_derived_columns` | **458L** | THE big one. 10+ nested helpers. Phase 9 C3 sign-flip lives here. |
| 8279 | `select_targeted_repair_ciks` | 82L | SEC repair targeting |
| 8394 | `attach_fund_panel_join_diagnostics` | 141L | Join diagnostics |
| 8537 | `write_fundamental_join_diagnostics` | 88L | IO report |
| 8627 | `write_fundamental_collection_audit` | 219L | IO report |
| 8848 | `build_fund_panel_for_ciks` | 68L | Companyfacts-derived builder |
| 8918 | `build_yfinance_quarterly_panel` | 103L | yfinance-derived builder |
| 9051 | `load_or_update_fund_panel` | 67L | Cache-or-build wrapper |
| 9120 | `asof_join_fundamentals` | 139L | Point-in-time asof merge |

**Dependency prep checks before move**:
1. Grep `_sign_flip_pos`, `_loss_narrowing_rate`, `_under_loss_growth`
   usages. All must be nested within `recompute_fund_panel_derived_columns`.
2. Verify no other module-level function references these nested helpers
   (they should be private scope only).
3. Check if `recompute_fund_panel_derived_columns` uses any helpers
   NOT yet in r1000_helpers.py — must import them or move the missing
   ones first.
4. `_flexible_lag` imports `pd.DateOffset`; already available.

**Sanity test after move** (BEFORE commit):
```python
import r1000_features as f
import r1000_helpers as h
import numpy as np, pandas as pd

# Synthetic fund_panel with 1 CIK going from loss to profit
d = pd.DataFrame({
    "cik": [1, 1, 1, 1] * 2,
    "quarter": list(range(1, 9)) * 1,
    "net_income_ttm": [-1, -0.5, 0.2, 0.8, 1.2, 1.5, 1.8, 2.0][:8],
    # ... fill other required columns ...
})
result = f.recompute_fund_panel_derived_columns(d)
# ni_sign_flip_pos should fire at quarter 3 (cur > 0, prev-4 < 0 via some lag)
# profit_turn_positive_4q (Phase 9 C3 alias) should equal ni_sign_flip_pos
# roe_sign_flip_pos should be computed from roe_proxy when equity present
```

**Rollback procedure** (if this breaks something):
```
git reset --hard HEAD~1   # roll back 3d-i only
py -3 tests/smoke_test.py # confirm smoke still passes
# Investigate what broke; try again with smaller scope
```

---

### Stage 3d-ii — Macro / event regime feature builders

**Size**: ~850 lines across 9 functions.
**Risk**: MEDIUM. Pure transforms on time-series data; no nested helpers
with subtle scope.

**Functions to move**:

| Line | Function | Size | Notes |
|---|---|---|---|
| 3132 | `load_fred_series` | 70L | FRED API data fetch (already Stage 3b-adjacent; keep for 3d-ii to bundle with macro) |
| 3213 | `load_cnn_fear_greed_table` | 56L | CNN fear-greed scraper |
| 3474 | `merge_benchmark_relative_features` | 34L | benchmark-relative RS merger |
| 3510 | `attach_benchmark_forward_returns` | 32L | forward-return sanity attach |
| 3544 | `compute_event_regime_features` | 144L | systemic crisis / carry_unwind / war_oil_rate scoring |
| 3690 | `build_live_event_alert_table` | 187L | live event regime alert composer |
| 3879 | `merge_live_event_alert_features` | 33L | event feature merger |
| 3947 | `build_macro_regime_table` | **417L** | macro regime scoring table (M2/fed_assets/etc. → regime labels) |
| 4366 | `merge_macro_regime_features` | 33L | macro feature merger |
| 4407 | `compute_macro_interaction_features` | 53L | macro-interactive feature composer |

**Dependency prep**:
- `load_fred_series` uses `requests` (stdlib), `_robust_retry` (helpers),
  `MACRO_FRED_SERIES` (config).
- `build_macro_regime_table` uses many stats helpers (`rolling_robust_z`,
  `robust_z`, `winsorize`) — already in r1000_helpers.
- `compute_event_regime_features` uses `numeric_series_or_default` and
  `cross_sectional_robust_z`.

---

### Stage 3d-iii — Market + dynamic-leadership + crisis features

**Size**: ~650 lines across 6 functions.
**Risk**: LOW. Pure transforms, no tricky nested scope.

**Functions to move**:

| Line | Function | Size | Notes |
|---|---|---|---|
| 4462 | `compute_market_adaptation_features` | 157L | market breadth + sector participation scoring |
| 4621 | `compute_dynamic_leadership_features` | 180L | dominant-leader / emerging-leader composite |
| 4803 | `load_manual_moat_overrides` | 51L | YAML manual override loader |
| 4856 | `apply_manual_ticker_overlays` | 87L | user-supplied overlay applier |
| 4945 | `compute_three_level_relative_strength` | 38L | 3-tier RS (ticker vs industry vs market) |
| Also: any small compute_* surrounding these | ~100L total | | |

---

### Stage 3d-iv — Strategy blueprint + pillar + minervini composites

**Size**: ~1,400 lines across 3 functions (but 1 of these is 926 lines!).
**Risk**: MEDIUM. Phase 1 `compute_strategy_blueprint_columns` is THE place
where turnaround/value/uptrend scores are computed. Phase 9 C3 doesn't
depend on this directly (C3 uses fund_panel sign-flip flags, not blueprint
scores), but Phase 1 still ships to early_scout gate as one of the three
admission criteria.

**Functions to move**:

| Line | Function | Size | Notes |
|---|---|---|---|
| 5016 | `compute_strategy_blueprint_columns` | **926L** | Phase 1 turnaround + value + uptrend alpha scoring. Largest single feature function. |
| 5944 | `compute_multidimensional_pillar_scores` | 186L | pillar composite (fundamental/technical/event/macro/compounder) |
| 6745 | `compute_minervini_momentum_overlay` | 144L | Minervini trend template + momentum overlay |

**Sanity test after move**:
```python
import r1000_features as f
import pandas as pd, numpy as np

# Synthetic frame with 3 tickers, 5 rebalance months
d = pd.DataFrame({
    "ticker": ["AAA"] * 5 + ["BBB"] * 5 + ["CCC"] * 5,
    "rebalance_date": pd.date_range("2024-01-01", periods=5, freq="ME").repeat(3)[:15],
    # ... ~80 required columns for compute_strategy_blueprint_columns ...
})
# Actually this is complex to mock — instead:
# Just verify import + identity with main engine
import r1000_top30_institutional as r
assert r.compute_strategy_blueprint_columns is f.compute_strategy_blueprint_columns
```

---

## Total Stage 3d impact

| Metric | Before 3d | After 3d-i | After 3d-ii | After 3d-iii | After 3d-iv |
|---|---|---|---|---|---|
| Main engine lines | 23,582 | 22,480 | 21,630 | 20,980 | 19,580 |
| r1000_features.py lines | 1,923 | 3,025 | 3,875 | 4,525 | 5,925 |
| % main reduction vs pre-refactor | 15.3% | 19.2% | 22.3% | 24.6% | 29.6% |

After Stage 3d complete:
- Main engine ~19,500 lines (from 27,838 → **-30%**)
- `r1000_features.py` ~5,900 lines (largest post-refactor module)
- Remaining in main: pipeline (Stage 5) + sleeve/portfolio (Stage 4) +
  legacy dead code (Stage 4 subtractive) + facade re-exports

---

## Execution rules (recap)

1. **Pure move only** — zero logic change. Every moved function byte-identical except
   import-context.
2. **Incremental commits** — one sub-stage (3d-i, 3d-ii, 3d-iii, 3d-iv) per commit.
3. **Post-move test**:
   - `py -3 -c "import r1000_top30_institutional as r, r1000_features as f;
      assert r.<FN> is f.<FN>"` for each moved name
   - `py -3 tests/smoke_test.py` 25/25 passed
   - Identity + spot-behavior sanity on 2-3 sample functions per stage
4. **Pipeline verify deferred**: do ONE verify.py run at end of Stage 3d
   (or at end of Stage 3 + 4 + 5 — TBD based on time budget).
5. **If mismatch**: `git reset --hard HEAD~1` → try smaller scope.

---

## Risk register

### HIGH: `_sign_flip_pos` scope (3d-i)
`recompute_fund_panel_derived_columns` defines these nested:
```python
def _sign_flip_pos(series_name: str) -> pd.Series:
    ...  # Phase 9 C3 depends on this producing correct flags
```
Scope is preserved when function moved intact. But if anyone accidentally
pulls `_sign_flip_pos` OUT of the enclosing function during editing (e.g.
to "share" it with other features), Phase 9 C3 breaks silently. Prevention:
move `recompute_fund_panel_derived_columns` as a SINGLE `str` slice, no
editing of body.

### MEDIUM: `compute_strategy_blueprint_columns` 926 lines (3d-iv)
Risk of missing closing `}` / `return` during move if script boundary
is off by one. Prevention: verify start + end anchors explicitly
(`def compute_strategy_blueprint_columns(` at start, whatever last line
`return d` at end).

### LOW: import cascade
Each sub-stage adds imports to r1000_features.py. Running total:
- 3d-i needs: `load_previous_live_weights` (helpers?), `_flexible_lag` (same module)
- 3d-ii needs: `requests`, `MACRO_FRED_SERIES` / `MACRO_PRICE_TICKERS`
- 3d-iii needs: YAML parser for moat overrides (already in stdlib? check)
- 3d-iv needs: many stats helpers (already in helpers)

If any import is missing after a move, Python raises `NameError` at import
time — smoke test catches it immediately. Fix: add the missing import.

---

## Entry conditions (must hold before starting 3d-i)

- [ ] Stage 1 rollup `verify.py` reports BYTE-EXACT MATCH
  (confirms pure-move refactor works end-to-end)
- [ ] `git status` clean on `refactor/phase-a-module-split`
- [ ] `py -3 tests/smoke_test.py` → 25/25 pass
- [ ] User has reviewed this plan and approved the 4-sub-stage split

## Exit criteria (Stage 3d complete)

- [ ] All 4 sub-stages committed + pushed
- [ ] Main engine ~19,500 lines
- [ ] r1000_features.py ~5,900 lines
- [ ] `py -3 tests/smoke_test.py` → 25/25 pass
- [ ] `py -3 run_local.py --no-collector` → outputs byte-identical to baseline
- [ ] CHANGELOG entry per Agent Update Contract
- [ ] SESSION_HANDOFF.md §2 rewritten pointing at Stage 4
