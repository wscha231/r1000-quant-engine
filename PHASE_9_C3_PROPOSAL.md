# Phase 9 C3 — EPS / Profitability Turn-Positive Flags

**Date**: 2026-04-17
**Status**: DESIGNED — awaiting Phase 9 C1+C2 verdict before implementation
**Blocker**: `afaa768` FULL REBUILD (started 08:10) must complete + SHIP verdict confirmed
**ENGINE_REUSE_VERSION bump**: REQUIRED (feature_store schema change → FULL rebuild needed)

---

## 1. Motivation

### 1.1 User definition of early sleeve

> "early 는 eps 적자거나 양전환 막 하거나" — early scouts are names that are still losing money OR that have just turned profitable this quarter.

### 1.2 Current state (post Phase 9 C2)

Phase 9 C2's `_p9_early_inflect` gate uses three continuous Z-scored composites as proxies for "just turned positive":

```python
# r1000_top30_institutional.py:19358-19362
_p9_early_inflect = (
    (_p9_turnaround  > _p9_early_inflect_thr)    # fundamental_turnaround_acceleration_score
    | (_p9_cf_inflect > _p9_early_inflect_thr)   # cashflow_inflection_under_loss_score
    | (_p9_value_infl > _p9_early_value_thr)     # value_inflection_score
)
```

These three scores each combine ~10 sub-factors (sign-flip flags, loss-narrowing rates, under-loss growth, revenue acceleration, etc.) into a single Z-score. The Q-over-Q sign transition is ONE of many inputs, diluted by 13+ other terms.

### 1.3 What's missing — direct Q-over-Q sign-transition flag

The engine already computes `_sign_flip_pos(series)` (line 12157) which returns **1.0 when current quarter > 0 AND prior quarter (Q-4) ≤ 0**. This is exactly "양전환 막 하거나" (just turned positive) — but the output columns (`ni_sign_flip_pos`, `ocf_sign_flip_pos`, `fcf_sign_flip_pos`, `op_income_sign_flip_pos`) stay inside `fund_panel` carry_cols and **never reach the feature_store whitelist**.

Verified empirically:

```
$ grep ni_sign_flip_pos  {CORE_FUNDAMENTAL_COLUMNS, PHASE1_ALPHA_COLUMNS, PHASE2_INDUSTRY_COLUMNS,
                         PHASE5_LEADER_LAGGARD_COLUMNS, PHASE8B_LONG_LOOKBACK_COLUMNS,
                         FUND_TTM_FALLBACK_COLUMNS}
→ 0 matches (confirmed not whitelisted)
```

The flags live at `fund_panel` layer but are dropped by `fs = universe[keep_cols].copy()` in `build_feature_store` (line 14335). They only contribute indirectly via being one of ~14 weighted inputs into `fundamental_turnaround_acceleration_score`.

### 1.4 Why this hurts early-scout gate quality

Because the sign-flip contribution to `fundamental_turnaround_acceleration_score` has weight 0.13 (line 9476: `0.13 * robust_z(op_flip_gated)`), a name that JUST turned profitable but has mediocre revenue-acceleration and margin-trend would NOT clear the `_p9_early_inflect_thr = 0.3` gate. The most informative event ("EPS just went positive after loss") gets averaged out.

Example: a biotech with first profitable quarter has `ni_sign_flip_pos = 1.0` but low `rev_growth_accel_4q` (unusual revenue pattern pre-commercial) → turnaround score could be ~0.1, below the 0.3 threshold → excluded from early sleeve. This contradicts the user's definition.

---

## 2. Scope

### 2.1 In-scope

1. **Expose 4 new feature-store columns**:
   - `profit_turn_positive_4q` — alias of `ni_sign_flip_pos` (net income flipped positive this quarter)
   - `cashflow_turn_positive_4q` — max of `ocf_sign_flip_pos`, `fcf_sign_flip_pos` (cash-flow flipped positive)
   - `roe_turn_positive_4q` — NEW: `_sign_flip_pos("roe_proxy")` (ROE flipped positive)
   - `any_profitability_turn_positive_4q` — OR of above three (union flag for convenience)

2. **Extend Phase 9 C2 early-scout gate** to include these flags as a THIRD eligibility branch:

   ```python
   _p9_eps_turn_positive = (
       (d["profit_turn_positive_4q"] > 0.5)
       | (d["cashflow_turn_positive_4q"] > 0.5)
       | (d["roe_turn_positive_4q"] > 0.5)
   )
   _p9_early_inflect = (
       (_p9_turnaround > _p9_early_inflect_thr)
       | (_p9_cf_inflect > _p9_early_inflect_thr)
       | (_p9_value_infl > _p9_early_value_thr)
       | _p9_eps_turn_positive          # ← NEW in C3
   )
   ```

3. **Add "still in loss" second branch** (the "eps 적자" half of user definition):

   ```python
   _p9_still_loss_but_improving = (
       (d["net_income_ttm"] < 0)
       & (
           (d["ocf_under_loss_growth"] > 0.3)
           | (d["fcf_under_loss_growth"] > 0.3)
           | (d["ni_loss_narrowing_4q"] > 0.3)
       )
   )
   ```

   Then: `_p9_early_elig = _p9_early_size & (_p9_early_inflect | _p9_early_breakout | _p9_still_loss_but_improving) & ...`

   **Gates the raw "still in loss" on improvement evidence** so we don't admit perpetual losers.

4. **Expose 3 loss-narrowing columns** so they're available to the gate: `ocf_under_loss_growth`, `fcf_under_loss_growth`, `ni_loss_narrowing_4q`. These are already computed in fund_panel (line 12200-12207) but not in feature_store whitelist.

5. **Diagnostic flags** (for post-run analysis):
   - `phase9_c3_turnaround_active` (0/1 row-level: whether new branch fired)
   - `phase9_c3_still_loss_branch_active` (0/1 row-level: whether still-loss branch fired)

### 2.2 Out-of-scope

- Changes to the Phase 1 turnaround composite itself (`fundamental_turnaround_acceleration_score` stays as-is)
- Changes to `_sign_flip_pos` formula (already correct)
- Training a new ML model on these flags (flags feed the sleeve GATE, not ML features)
- Changes to CORE / FUTURE gates (only EARLY gets the new signal)

### 2.3 Explicitly rejected alternatives

- **Use Phase 1 score with lower threshold**: lowering `_p9_early_inflect_thr` from 0.3 to 0.1 would admit many more names but also admit lots of noise (the composite weights non-flip factors at 87%). A dedicated flag is cleaner.
- **New 0.3-weighted sub-score within turnaround composite**: would dilute existing signal + force FULL rebuild anyway. Exposing the flag directly is simpler.
- **Use existing `any_profit_sign_flip_pos` (already in fund_panel)**: close, but it uses max(op/ocf/fcf/ni) not including ROE. We want to add ROE too, and we want explicit renaming for intent. Wrapping `any_profit_sign_flip_pos` as a 5-member variant is cleaner.

---

## 3. Implementation

### 3.1 File-level changes

| File | Change |
|---|---|
| `r1000_top30_institutional.py` | • Add `PHASE9_C3_TURNAROUND_COLUMNS` constant (~line 1080, near other PHASE constants)<br>• Add `d["roe_sign_flip_pos"] = _sign_flip_pos("roe_proxy")` in `recompute_fund_panel_derived_columns` (line ~12228 after `d["roe_proxy"] = ...` is computed)<br>• Add 4 new alias / composite columns in `recompute_fund_panel_derived_columns` (line ~12223 after `any_profit_sign_flip_pos`)<br>• Extend `carry_cols` list (line ~12358) with the 4 new columns + `roe_sign_flip_pos`<br>• Add `+ PHASE9_C3_TURNAROUND_COLUMNS` to `build_feature_store.keep_cols` (line 14327)<br>• Add same to `hard_sanitize()` call (line 14354)<br>• Extend Phase 9 C2 early-scout gate block (line ~19357) with C3 branches<br>• Bump `ENGINE_REUSE_VERSION` from `2026-04-17-phase8b-long-lookback-momentum` → `2026-04-17-phase9c3-turnaround-flags` |
| `colab_run.ipynb` | • Cell 2: add `PHASE9_C3_TURNAROUND = 'auto'` toggle<br>• Cell 2: add `_set_phase_env('PHASE_PHASE9_C3_TURNAROUND_ENABLED', PHASE9_C3_TURNAROUND)`<br>• Cell 2 print-loop: extend tuple with new env name<br>• Cell 9 (Phase 1/2/8 sanity check): add `phase9_c3_cols` list → verify coverage + non-zero share |
| `CHANGELOG.md` | Agent Update Contract entry (required fields) |
| `SESSION_HANDOFF.md` | §2 rewritten to show C3 run flow + expected outcome |

### 3.2 Code changes — exact snippets

#### 3.2.1 New constant (line ~1080)

```python
# Phase 9 C3 — EPS / profitability turn-positive flags exposed to feature store.
# Requires FULL rebuild because these columns did not exist in prior feature_store.
PHASE9_C3_TURNAROUND_COLUMNS = [
    "profit_turn_positive_4q",
    "cashflow_turn_positive_4q",
    "roe_turn_positive_4q",
    "any_profitability_turn_positive_4q",
    "roe_sign_flip_pos",          # raw (kept for diagnostic parity with op/ocf/fcf/ni)
    # Loss-improvement continuous scores (already in fund_panel carry_cols, now whitelisted)
    "ocf_under_loss_growth",
    "fcf_under_loss_growth",
    "ni_loss_narrowing_4q",
]
```

#### 3.2.2 fund_panel additions (after line 12228 — where `roe_proxy` is computed)

```python
# Phase 9 C3 — ROE sign-flip flag (parallel to op/ocf/fcf/ni)
d["roe_sign_flip_pos"] = _sign_flip_pos("roe_proxy")

# Phase 9 C3 — user-facing alias + composite columns
d["profit_turn_positive_4q"] = d["ni_sign_flip_pos"]
d["cashflow_turn_positive_4q"] = pd.concat(
    [d["ocf_sign_flip_pos"], d["fcf_sign_flip_pos"]], axis=1
).max(axis=1).fillna(0.0)
d["roe_turn_positive_4q"] = d["roe_sign_flip_pos"]
d["any_profitability_turn_positive_4q"] = pd.concat(
    [
        d["profit_turn_positive_4q"],
        d["cashflow_turn_positive_4q"],
        d["roe_turn_positive_4q"],
    ],
    axis=1,
).max(axis=1).fillna(0.0)
```

Extend `carry_cols` (line ~12358) by adding to the turnaround block:

```python
# Phase 9 C3 aliases + ROE flip (new)
"profit_turn_positive_4q",
"cashflow_turn_positive_4q",
"roe_turn_positive_4q",
"any_profitability_turn_positive_4q",
"roe_sign_flip_pos",
```

#### 3.2.3 feature_store whitelist (line 14327)

```python
keep_cols = list(dict.fromkeys([...]
    + PHASE2_INDUSTRY_COLUMNS
    + PHASE5_LEADER_LAGGARD_COLUMNS
    + PHASE1_ALPHA_COLUMNS
    + PHASE8B_LONG_LOOKBACK_COLUMNS
    + PHASE9_C3_TURNAROUND_COLUMNS          # ← NEW
    + [...]
))
```

Same addition to `hard_sanitize` call (line 14354).

#### 3.2.4 Phase 9 C2 gate extension (line 19357, replacing existing block)

```python
# Gate toggle
_phase9_c3_active = bool(
    (getattr(cfg, "phase9_c3_turnaround_enabled", True) if cfg is not None else True)
    and phase_is_enabled("phase9_c3_turnaround", default=True)
)

# Existing size gate (unchanged)
_p9_early_size = (_p9_mktcap_pct < _p9_early_hi_pct)

# Existing inflection / breakout branches (unchanged)
_p9_early_inflect = (
    (_p9_turnaround > _p9_early_inflect_thr)
    | (_p9_cf_inflect > _p9_early_inflect_thr)
    | (_p9_value_infl > _p9_early_value_thr)
)
_p9_early_breakout = (
    (_p9_golden > _p9_early_gc_thr)
    | ((_p9_breakout > _p9_early_breakout_thr) & (_p9_above_ma200 > 0))
)

# Phase 9 C3 NEW branches
if _phase9_c3_active:
    _p9_ni_ttm = numeric_series_or_default(d, "net_income_ttm", 0.0)
    _p9_profit_turn = numeric_series_or_default(d, "profit_turn_positive_4q", 0.0)
    _p9_cf_turn = numeric_series_or_default(d, "cashflow_turn_positive_4q", 0.0)
    _p9_roe_turn = numeric_series_or_default(d, "roe_turn_positive_4q", 0.0)
    _p9_ocf_under_loss = numeric_series_or_default(d, "ocf_under_loss_growth", 0.0)
    _p9_fcf_under_loss = numeric_series_or_default(d, "fcf_under_loss_growth", 0.0)
    _p9_ni_narrow = numeric_series_or_default(d, "ni_loss_narrowing_4q", 0.0)

    _p9_c3_loss_narrow_thr = float(getattr(cfg, "phase9_c3_loss_narrowing_threshold", 0.3))

    _p9_eps_turn_positive = (
        (_p9_profit_turn > 0.5) | (_p9_cf_turn > 0.5) | (_p9_roe_turn > 0.5)
    )
    _p9_still_loss_but_improving = (
        (_p9_ni_ttm < 0)
        & (
            (_p9_ocf_under_loss > _p9_c3_loss_narrow_thr)
            | (_p9_fcf_under_loss > _p9_c3_loss_narrow_thr)
            | (_p9_ni_narrow > _p9_c3_loss_narrow_thr)
        )
    )
    _p9_c3_admit = _p9_eps_turn_positive | _p9_still_loss_but_improving
else:
    _p9_c3_admit = pd.Series(False, index=d.index)
    _p9_eps_turn_positive = pd.Series(False, index=d.index)
    _p9_still_loss_but_improving = pd.Series(False, index=d.index)

# Final eligibility now unions C2 + C3 branches
_p9_early_elig = (
    _p9_early_size
    & (_p9_early_inflect | _p9_early_breakout | _p9_c3_admit)
    & (~_p9_core_elig) & (~_p9_future_elig)
)

# Diagnostic flags (row-level)
d["phase9_c3_turnaround_active"] = float(_phase9_c3_active)
d["phase9_c3_eps_turn_positive"] = _p9_eps_turn_positive.astype(float).values
d["phase9_c3_still_loss_branch"] = _p9_still_loss_but_improving.astype(float).values
```

### 3.3 New cfg fields

Add to EngineConfig dataclass (near other phase9_* fields, ~line 2360):

```python
phase9_c3_turnaround_enabled: bool = True
phase9_c3_loss_narrowing_threshold: float = 0.3
```

### 3.4 Colab notebook

Cell 2 — add:
```python
PHASE9_C3_TURNAROUND = 'auto'    # Phase 9 C3 EPS turn-positive flag + still-loss-improving branch
```

Bind env + extend print-loop.

Cell 9 — add sanity check cols:
```python
phase9_c3_cols = [
    'profit_turn_positive_4q', 'cashflow_turn_positive_4q',
    'roe_turn_positive_4q', 'any_profitability_turn_positive_4q',
    'roe_sign_flip_pos', 'ocf_under_loss_growth', 'fcf_under_loss_growth',
    'ni_loss_narrowing_4q',
    # diagnostic flags from sleeve layer
    'phase9_c3_turnaround_active', 'phase9_c3_eps_turn_positive',
    'phase9_c3_still_loss_branch',
]
phase9_c3_summary = _summarise(phase9_c3_cols, 'Phase 9 C3 - turnaround flags + diagnostics')
```

---

## 4. Expected impact

### 4.1 Early-sleeve count

Phase 9 C2 (pre-C3) produced ≈55 early_scout eligible names on 610-name universe (9.0%).

C3 additions:
- `_p9_eps_turn_positive`: empirically (from sign_flip_pos frequency in a typical quarter), ~5-15 names trip this per rebalance date
- `_p9_still_loss_but_improving`: stricter gate (requires both still-loss AND improvement evidence) — ~3-10 names per rebalance

Expected new early_scout count: **60-75** (vs 55 post-C2). If SHIP: +5-15% early sleeve fill rate.

### 4.2 Portfolio composition

C3 does NOT touch CORE or FUTURE. Only EARLY sleeve admissibility widens. Expect:
- More small/mid-cap inflection names in early sleeve
- Possibly 1-3 names moving from UNASSIGNED → early_scout
- Zero effect on mega-cap / growth names (they were already core/future)

### 4.3 Backtest expectations

Early sleeve currently has ~10-15% portfolio weight (per sleeve targets). Adding 5-15 more candidates primarily affects WHICH inflection names get ranked, not the total early sleeve notional. Expected metric effect: **small (±0.3pp CAGR, ±0.02 Sharpe)** — this is a selection-refinement change, not a regime shift.

If the Phase 9 C2 verdict was SHIP (CAGR ≥ +0.5pp vs Phase 8 baseline 21.86%), C3 is a natural completion. If PARTIAL or REGRESS on C2, C3 should be deferred — fixing C2 first.

---

## 5. Validation

### 5.1 Post-implementation sanity

- `Cell 9`: verify `phase9_c3_cols` coverage > 95%, non-zero share reasonable (profit_turn_positive should be >5% nonzero, roe_turn >3%)
- `concentrated_backtest_metrics.json`: strategy_cagr delta should be within ±1pp of Phase 9 C2 baseline
- `top30_latest.csv`: `phase9_c3_eps_turn_positive` should mark 3-8 names; `phase9_c3_still_loss_branch` should mark 2-6 names

### 5.2 A/B toggle test

Run 2 FULL rebuilds (since FS schema changes):
1. `PHASE_PHASE9_C3_TURNAROUND_ENABLED=0` → expect byte-exact Phase 9 C2 output (gate falls back to C2-only)
2. `PHASE_PHASE9_C3_TURNAROUND_ENABLED=1` (default) → expect wider early sleeve, different metrics

Ship gate: same as Phase 9 C2 (ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp AND early_count ≥ 4 vs Phase 9 C2 baseline).

### 5.3 Regression protection

After the ENGINE_REUSE_VERSION bump, the feature_store_latest.parquet will be regenerated. Verify:
- `PHASE9_C3_TURNAROUND_COLUMNS` all present in parquet schema
- No other columns dropped (compare schema diff vs prior parquet)
- `hard_sanitize` correctly clipped the new columns to [-1e12, 1e12] (they should all be in [0, 1])

---

## 6. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| ROE flip signal is noisy because roe_proxy depends on assets - liabilities | MED | Defensive: `_sign_flip_pos` already handles NaN via `prev_num.notna()` mask. Additional guard: skip ROE flip in gate if roe_proxy not finite. |
| "Still in loss + improving" admits perpetual losers because loss-narrowing threshold is loose | MED | Threshold `phase9_c3_loss_narrowing_threshold = 0.3` is tunable. Monitor `phase9_c3_still_loss_branch` count per rebalance. If > 20% of early sleeve, tighten to 0.5. |
| Feature store size grows by ~8 columns × 611 rows × 25 years × monthly = small (~1MB) | LOW | Ignore. |
| `_sign_flip_pos` 4-quarter lag requires ≥4 historical fund_panel rows | LOW | Names with < 4 quarters of fundamentals (IPOs) naturally get 0.0 flip — correct behavior. |
| Double-counting with existing Phase 1 turnaround composite | LOW | No: C3 is an ADDITIONAL admission branch (OR), not a replacement. Existing composite stays intact. |
| FULL rebuild 2-3h blocks iteration | HIGH | ENGINE_REUSE_VERSION bump is unavoidable for FS schema. Only one rebuild needed; subsequent A/B can QUICK_RESCORE. |

---

## 7. Timing

### 7.1 Prerequisites

1. **Phase 9 C1+C2 FULL REBUILD must complete** (currently in progress, commit `33581bc`, started 08:10 KST).
2. **Phase 9 C1+C2 verdict confirmed SHIP**: CAGR ≥ +0.5pp above Phase 8 baseline (21.86%). Expected verdict time: ~3h from 08:10 = 11:10 KST (already past → user to paste results).
3. If verdict PARTIAL or REGRESS → defer C3, focus on C1/C2 A/B isolation first (per EXECUTION_PLAN.md Stage 1).

### 7.2 Implementation session

Assuming SHIP verdict:
- **Session A (20 min)**: implement the 4 code changes above, commit, push.
- **Colab FULL rebuild** (2-3h): trigger from fresh checkout. The SHA banner (`commit=<sha>`) added in `afaa768` will self-identify the run.
- **Session B (10 min)**: paste Cell 9 C3 sanity check + backtest metrics → verdict.
- **If SHIP**: proceed to Refactor Phase A per REFACTOR_PLAN.md.
- **If PARTIAL**: isolate C3 via A/B (disable with `PHASE_PHASE9_C3_TURNAROUND_ENABLED=0`).

Total wall-clock time for C3: ~3.5h (mostly the FULL rebuild).

---

## 8. Dependencies

- `_sign_flip_pos` helper (line 12157, existing) — reused unchanged
- `roe_proxy` column (line 12228, existing) — required input for new `roe_sign_flip_pos`
- Phase 9 C2 block (line 19305, existing) — extended with C3 branches
- `numeric_series_or_default` helper — used for defensive column access
- `phase_is_enabled` + `getattr(cfg, ...)` dual-gate pattern — same as other phase toggles

No new external libraries, no new data fetches.

---

## 9. Interaction with Refactor Phase A

Per REFACTOR_PLAN.md §11.3 (COLUMN_OWNERSHIP registry), C3 adds 8 columns that would be owned by `features.fundamental`:

```python
COLUMN_OWNERSHIP.update({
    "profit_turn_positive_4q": "features.fundamental",
    "cashflow_turn_positive_4q": "features.fundamental",
    "roe_turn_positive_4q": "features.fundamental",
    "any_profitability_turn_positive_4q": "features.fundamental",
    "roe_sign_flip_pos": "features.fundamental",
    "ocf_under_loss_growth": "features.fundamental",      # already exists, wasn't in registry
    "fcf_under_loss_growth": "features.fundamental",      # already exists, wasn't in registry
    "ni_loss_narrowing_4q": "features.fundamental",       # already exists, wasn't in registry
    # Sleeve-layer diagnostics
    "phase9_c3_turnaround_active": "sleeves.composite",
    "phase9_c3_eps_turn_positive": "sleeves.composite",
    "phase9_c3_still_loss_branch": "sleeves.composite",
})
```

C3 is a natural test of refactor robustness: the feature-store keep_cols survival rule (CLAUDE.md §"Phase 2 keepcols-fix") would be automatically enforced by the post-refactor module boundary (`r1000_features.py` owns `fund_panel` columns, `r1000_pipeline.py::build_feature_store` must import the phase constants).

**Recommendation**: C3 ships BEFORE refactor if SHIP on C2 (tightens sleeve taxonomy first, then refactor locks in observability). If refactor ships first, C3 becomes mechanically easier (single-file change in `r1000_signals.py` + config constant in `r1000_config.py`).

---

## 10. Open questions

1. **Continuous Z-score vs binary flag in gate?** Current proposal uses binary thresholds (`> 0.5`). Alternative: feed `profit_turn_positive_4q` into a new composite score and threshold at Z > 0. Going with binary because sign-flip is a discrete event, not a continuous signal. **Decision**: binary.

2. **Lookback window — 4Q or shorter?** `_sign_flip_pos` uses 4-quarter lag (Q vs Q-4). User's "막 양전환" could mean 1-2 quarters too. **Decision**: stay with 4Q (matches existing infrastructure, matches "trailing 12 months flipped positive" framing). Shorter lag would be noisier.

3. **Should C3 widen CORE or FUTURE gates too?** CORE requires mature ROE > 15% — a just-turned-positive ROE doesn't qualify. FUTURE requires revenue growth > 20% — turnaround names often have lower growth. **Decision**: C3 only widens EARLY (consistent with user's definition).

4. **Separate C3 from "still loss + improving" branch?** Proposed bundling. Could split into C3a (turn-positive) + C3b (still-loss-improving) with independent toggles. **Decision**: bundle under single C3 toggle for simplicity; if the two branches behave differently in A/B, split in C3.1.

---

## 11. Summary

Phase 9 C3 adds 4 clean, intent-revealing feature-store columns (`profit_turn_positive_4q`, `cashflow_turn_positive_4q`, `roe_turn_positive_4q`, `any_profitability_turn_positive_4q`) by exposing existing internal `_sign_flip_pos` flags + adding one new (`roe_sign_flip_pos`) + whitelisting 3 loss-narrowing scores. The Phase 9 C2 early-scout gate gains two new admission branches (`_p9_eps_turn_positive`, `_p9_still_loss_but_improving`) that directly answer the user's definition of early sleeve.

Scope is minimal: ~40 lines of engine code, 1 constant list, 2 cfg fields, 1 ENGINE_REUSE_VERSION bump, 1 FULL rebuild. Expected marginal CAGR effect is small (±0.3pp) — this is a taxonomy refinement, not a regime shift. The real value is alignment between the code's sleeve definitions and the user's mental model.

**Next action**: await Phase 9 C1+C2 SHIP verdict from FULL REBUILD currently in progress.
