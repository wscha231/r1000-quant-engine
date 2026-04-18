# r1000 Quant Engine — Phase 1..6 Roadmap

> **⚠ DEPRECATED as of 2026-04-18** — this file only covers the original Phase 1-6 plan (2026-04-16).
> Phases 7 / 8 / 8a-8d / 9 / 9 C1 / 9 C2 / 9 C3 have landed since and are NOT reflected here.
>
> **Current roadmap sources (use these instead)**:
> 1. `SESSION_HANDOFF.md` — single-item inbox for the next immediate action (THE file to read first).
> 2. `REFACTOR_PLAN.md` §12 — 5-stage sequencing diagram (Verdict → C3-or-Refactor → complement → Subtractive → Phase 8e).
> 3. `EXECUTION_PLAN.md` — 4-stage roadmap with ceiling assessment.
> 4. `PHASE_9_C3_PROPOSAL.md` — Phase 9 C3 implementation design.
> 5. Latest `CHANGELOG.md` entries (since 2026-04-17 Phase 8-9).
>
> This file is kept for historical reference of the original Phase 1-6 invariants (phase toggle mechanism, env-var convention, feature_store keep_cols survival rule). Those invariants ARE still valid — but the outcome descriptions below are stale (e.g. Phase 3 "PLANNED" → actually REJECTED, Phase 5 "PLANNED" → REJECTED, Phase 6 "PLANNED" → 6a/6b SHIPPED dormant / 6c OPT-IN).

---

**Purpose** (original 2026-04-16): persistent memory of the six-phase alpha-improvement plan for the Russell 1000 Top 30 institutional engine.
This document was written so a fresh Claude / Codex / GPT chat session can pick up the work cold — without the prior conversation context.

**Always read this file first** when resuming phase work in a new chat session. Read `CLAUDE.md` for the project basics, read the newest `CHANGELOG.md` entries for the latest state, and only then start editing.

---

## 0. TL;DR for a cold-start agent

- Goal: beat S&P 500 in excess CAGR while keeping max drawdown controlled. Baseline (2026-04-15, pre Phase 1+2): CAGR 21.80%, Sharpe 0.73, MaxDD −36.86%, `selected_names=2`, weighting `conviction_curve`.
- Phases 1 and 2 are **already implemented and merged** to `origin/master` (see CHANGELOG entries for `2026-04-16 12:27 KST` and `12:36 KST`).
- Phases 3..6 are **planned but not yet implemented**.
- Every phase is gated behind an env-var toggle (`PHASE_<KEY>_ENABLED`). This lets us measure the **marginal contribution** of each phase by running the engine 2x (once with ON, once with OFF) and diffing `outputs/concentrated_backtest_metrics.json`.
- Full rebuild of features + walk-forward models takes ~1.5-4 hours in Colab. Use the **quick-rescore preset** (`pipeline_quick_rescore_cfg`) for iteration: ~15-25 min.

---

## 1. Fast-iteration workflow (ALWAYS use this while tuning)

### When to use QUICK_RESCORE_ONLY vs FULL REBUILD

| Change type | Mode | Runtime | Notes |
|---|---|---|---|
| Sleeve weight tuning (`compute_portfolio_sleeve_columns`) | QUICK | 15-25 min | feature store + models reused |
| Phase A/B env toggle measurement | QUICK | 15-25 min | feature store + models reused |
| Portfolio sleeve policy cap change | QUICK | 15-25 min | feature store + models reused |
| NEW feature column (any `build_*` / `add_*` signal formula change) | FULL | 1.5-4 h | feature store MUST be rebuilt |
| `ENGINE_REUSE_VERSION` bump | FULL | 1.5-4 h | forces full rebuild by design |
| Walk-forward / model / embargo change | FULL | 1.5-4 h | models must be retrained |
| Anything that alters the input schema | FULL | 1.5-4 h | feature store must be rebuilt |

### How to switch modes in `colab_run.ipynb` cell 2

```python
QUICK_RESCORE_ONLY = True   # <- flip to True for iteration
PHASE1_ALPHA_ENABLED = 'auto'       # 'auto' | '0' | '1'
PHASE2_INDUSTRY_ENABLED = 'auto'    # 'auto' | '0' | '1'
```

Cell 4 branches automatically on `QUICK_RESCORE_ONLY`:
- `True` → uses `pipeline_quick_rescore_cfg()` from `r1000_data_collector.py`
- `False` → uses `collector_lean_full_run_cfg()` (original full path)

### What the quick-rescore preset sets (in `r1000_data_collector.py :: pipeline_quick_rescore_cfg`)

```python
cfg["reuse_existing_artifacts"] = True
cfg["resume_partial_walkforward"] = True
cfg["reuse_phase4_models_for_latest_recommendations"] = True
cfg["companyfacts_refresh_days"] = 99999
cfg["live_refresh_days"] = 99999
cfg["macro_refresh_days"] = 99999
cfg["industry_metadata_refresh_days"] = 99999
cfg["industry_metadata_max_new_per_run"] = 0
cfg["yf_quarterly_max_tickers_per_run"] = 0
cfg["run_comparison_backtests"] = False
cfg["run_portfolio_size_comparison"] = False
cfg["run_rebalance_interval_comparison"] = False
cfg["run_backtest_window_comparison"] = False
cfg["run_concentrated_backtest_comparison"] = True   # <- keep the measurement
cfg["fast_mode"] = True
```

**Caveat**: quick-rescore reuses the cached `feature_store/*.parquet`. If you change a signal formula (e.g. rewrite `compute_oneil_leadership_score`), quick-rescore will NOT see the new formula — the historical backtest continues to use the cached features. Only **sleeve-weight changes** and **phase-toggle env vars** are reflected. For any formula change, bump `ENGINE_REUSE_VERSION` and run a FULL rebuild once, then return to quick-rescore for downstream tuning.

### Phase toggle mechanism

The engine has a module-level helper right after `ENGINE_REUSE_VERSION` in `r1000_top30_institutional.py`:

```python
def phase_is_enabled(phase_key: str, default: bool = True) -> bool:
    """Check env var PHASE_{KEY}_ENABLED.  Returns `default` when unset."""
    env_name = f"PHASE_{phase_key.upper()}_ENABLED"
    raw = os.environ.get(env_name, "")
    val = str(raw).strip().lower()
    if val == "":
        return bool(default)
    if val in ("0", "false", "no", "off", "disabled"):
        return False
    if val in ("1", "true", "yes", "on", "enabled"):
        return True
    return bool(default)
```

Each phase-gated block looks like:

```python
if not phase_is_enabled("phase1_alpha", default=True):
    for col in ("fundamental_turnaround_acceleration_score", ...):
        if col in d.columns:
            d[col] = 0.0
```

**Why zero-out instead of skip**: downstream sleeve-composition code reads the columns unconditionally. Setting to 0.0 preserves schema while neutralizing the signal. New phases MUST follow this pattern so A/B toggling never raises KeyError.

### A/B measurement recipe

1. Run once with `PHASE_PHASE3_ENABLED=1` (your new phase ON) — record metrics.
2. Run once with `PHASE_PHASE3_ENABLED=0` — record metrics.
3. Diff `strategy_cagr`, `sharpe`, `max_dd` in `outputs/concentrated_backtest_metrics.json`.
4. A phase ships only if Δ CAGR ≥ +0.5pp AND Δ MaxDD ≤ +2pp (or better on at least one while neutral on the other).

---

## 2. Phase Catalog

### Phase 1 ✅ DONE (2026-04-16)

**Scope**: Turnaround / value-inflection / uptrend-continuation alpha at the single-name level.

**Signals added** (cross-sectional columns on `monthly`):
- `fundamental_turnaround_acceleration_score` — loss→profit sign flip magnitude + loss-narrowing + under-loss cashflow growth
- `cashflow_inflection_under_loss_score` — OCF/FCF inflecting positive while NI still negative (Lynch/O'Neil leading indicator)
- `value_inflection_score` — cheap valuation + earnings catching up + price reversing from oversold / Stage-1→2 setup with quality floor
- `uptrend_continuation_score` — 52w-high + full MA-stack + intact momentum + intact earnings + compounding fundamentals
- `uptrend_breakdown_penalty` — fires when strong names lose MA50/MA200, gap down on earnings, see revisions rollover, or death-cross

**Integration**:
- `add_fundamental_features()` adds panel-level sign-flip / loss-narrowing / under-loss-growth helpers
- `compute_strategy_blueprint_columns()` implements the cross-sectional composites
- `compute_portfolio_sleeve_columns()` wires them into core / future / early sleeves with role-appropriate weights:
  - early: bottom-fishing emphasis (value_inflection + turnaround heavy)
  - core: uptrend defence emphasis (uptrend_continuation heavy + uptrend_breakdown_penalty)
  - future: balanced

**A/B toggle**: `PHASE_PHASE1_ALPHA_ENABLED=0` → all 5 columns forced to 0.0 post-hoc (in `compute_strategy_blueprint_columns`, right after `d["uptrend_breakdown_penalty"] = ...`).

**Commit refs**: `2026-04-16 12:27 KST - phase1-turnaround-value-uptrend-alpha` in CHANGELOG.md.

---

### Phase 2 ✅ DONE (2026-04-16)

**Scope**: Industry-level relative strength + O'Neil / IBD leadership + industry rotation signal. Moves the engine's RS taxonomy from 11-sector GICS down to ~24 industry-group buckets.

**Signals added** (cross-sectional columns):
- `industry`, `industry_group`, `subindustry` (from yfinance `info.industry` + `YF_INDUSTRY_TO_GICS_GROUP` bucket map)
- `rs_industry_{1,3,6,12}m`, `rs_industry_group_{1,3,6,12}m` — within-group demeaned momentum
- `industry_mom_mean_{3,6,12}m`, `industry_group_mom_mean_{3,6,12}m`
- `industry_breadth_above_ma200`, `industry_group_breadth_above_ma200`
- `industry_group_strength_score` — composite momentum × breadth × acceleration at the group level
- `industry_within_leader_rank` — percentile rank within the group
- `oneil_leadership_score` — **multiplicative**: leader-in-strong-group (not additive)
- `industry_rotation_signal` — z-scored composite of industry beating market on 3m, accelerating, with breadth recovering 50-80%

**Integration**:
- `ensure_industry_metadata()` lazy-fetches yfinance `info` for missing tickers, rate-limit budgeted via `industry_metadata_max_new_per_run`
- `cache_misc/yf_industry_metadata.parquet` persists the fetch across runs with `industry_metadata_refresh_days` TTL
- `build_universe_monthly()` calls the Phase 2 block right after the existing `rs_sector_*` block
- `compute_portfolio_sleeve_columns()` wires Phase 2 signals with sleeve-specific weights:
  - core: modest (oneil_leadership + group_strength)
  - future: highest (IBD playbook — all 5 signals)
  - early: industry_rotation_signal dominant + leadership + leader-rank + rs_industry_3m

**A/B toggle**: `PHASE_PHASE2_INDUSTRY_ENABLED=0` → the Phase 2 block in `build_universe_monthly` is skipped; a zero-column fallback ensures downstream sleeve code still finds the expected column names.

**Commit refs**:
- `2026-04-16 12:36 KST - phase2-industry-relative-strength-and-leadership`
- `2026-04-16 15:30 KST - phase2-fix-industry-cache-dtype-crash` (hotfix)
- `2026-04-16 18:08 KST - phase2-keepcols-survival-fix` (critical: Phase 2 columns were being dropped from feature_store before this fix — the 2026-04-16 runs prior to this timestamp did NOT actually benefit from Phase 2)

**Known gotcha**: first run after a fresh cache costs ~5-15 min for yfinance fetches (~1000-1200 tickers at 1s per 40 calls backoff). `colab_run.ipynb` cell 4 has a `OPTION_1_FULL_REBUILD and not QUICK_RESCORE_ONLY` guard to skip the fetch in quick-rescore mode.

**Survival bug history (2026-04-16 18:08)**: `build_feature_store` has an explicit `keep_cols` whitelist that silently dropped the 23 Phase 2 columns because they weren't listed. Phase 1 didn't hit this bug only because `compute_strategy_blueprint_columns` is re-invoked on `latest_df` in `score_latest_month` / `prepare_latest_scored_data`, which re-derives Phase 1 columns after the feature-store drop. Phase 2 has no such re-derivation — so the columns were missing from `feature_store_latest.parquet`, and the sleeve composites at `compute_dual_sleeve_composite_scores` silently collapsed to 0.0 for every walk-forward month. Fix adds `PHASE2_INDUSTRY_COLUMNS` constant and appends it to `keep_cols` + `hard_sanitize` (numeric subset). **Any pre-2026-04-16 18:08 run's "Phase 2 metrics" are actually "Phase 1 only + Phase 2 yfinance fetch wasted"** — true Phase 2 contribution measurement requires a FULL rebuild after this fix.

---

### Phase 3 ❌ REJECTED (2026-04-17) — Sleeve Weight Renormalization + Phase-Contribution Audit

**A/B outcome (commits `5b95e17` infra, `8b10bf4` hardening, `28e41fe` rejection)**:
- QUICK_RESCORE A/B on the 2026-04-16 FULL rebuild baseline showed regression on ALL THREE risk-adjusted axes:
  - Δ CAGR: −2.30pp (0.2010 → 0.1780)
  - Δ Sharpe: −0.1294 (1.0754 → 0.9460)
  - Δ MaxDD: −4.58pp (−0.2360 → −0.2818)
- Hypothesis falsified: `row_mean`'s N-averaging was providing natural regularisation. L1 normalisation doubles composite magnitude, increasing winsorize/clip saturation + amplifying sparse-history penalty ~2x → more weight on outliers and penalties.
- Infrastructure retained (`weighted_sleeve_composite` helper + diagnostic columns) for possible future re-evaluation with a different `l1_target` (e.g. per-sleeve N-based target). Default `sleeve_weight_renorm_enabled=False` stays.
- See CHANGELOG entry `2026-04-17 06:45 KST - phase3-ab-rejected-keep-off-default`.

**Why**: Phase 1 and 2 added signals to `compute_portfolio_sleeve_columns` additively (no existing weights were reduced). The relative weight of pre-existing factors (e.g. `long_hold_compounder_score`) therefore mechanically dilutes. We need to confirm (a) Phase 1+2 are net-positive vs the old weights, and (b) renormalize if the old signals are now overshadowed.

**Plan**:
1. **Measure**: run the 4 A/B combinations (P1 on/off × P2 on/off) end-to-end with the quick-rescore preset. Record `strategy_cagr`, `sharpe`, `max_dd`, `excess_cagr`, `ir`, `beat_month_ratio` for each. Check the full matrix for sleeve-contribution interactions.
2. **Decide**: if Phase 1+2 together beat baseline by ≥1pp CAGR with ≤2pp MaxDD regression, ship as-is. If the signals are diluting old factors (new CAGR < baseline CAGR), renormalize.
3. **Renormalize** (only if step 2 shows dilution):
   - Audit the sleeve composite weight distributions in `compute_portfolio_sleeve_columns` — print the sum of absolute weights per sleeve before and after Phase 1+2.
   - Rebalance to a target L1 norm (e.g. 1.0) by scaling pre-existing weights down proportionally.
   - Re-measure. Ship only if renormalized metrics dominate both the baseline and the un-renormalized version.
4. **Gate**: `PHASE_PHASE3_RENORM_ENABLED=1` enables the renormalization. Default OFF until validated.

**Files touched**: `r1000_top30_institutional.py :: compute_portfolio_sleeve_columns` (weight scaling block at the end). No new columns, no new config fields.

**Config fields to add**:
```python
sleeve_weight_l1_target: float = 1.0         # L1 norm target per sleeve
sleeve_weight_renorm_enabled: bool = False    # default OFF
```

**Expected impact**: +0.2 to +1.5pp CAGR if Phase 1+2 were diluting. Neutral if they weren't.

**Complexity**: LOW (~50 lines). Pure weight bookkeeping.

**Runtime**: QUICK rescore is sufficient for measurement.

**Acceptance criteria**: Δ CAGR ≥ +0.5pp AND MaxDD not worse by more than +1pp.

---

### Phase 4 ✅ DONE (2026-04-17, default OFF) — Regime-Conditional Dynamic Sleeve Weights

**Commit**: `6b790cb Add Phase 4 regime-conditional sleeve multipliers (default OFF)`
**Status**: Infrastructure landed, pending A/B measurement. Default OFF.
**Implementation**:
- Module constants `SLEEVE_FACTOR_REGIME_MULTIPLIERS` (6-regime table: `growth_reentry`, `balanced`, `stagflation`, `systemic_crisis`, `carry_unwind`, `war_oil_rate_shock`) and `SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP = (0.40, 1.60)`.
- Helper `resolve_regime_sleeve_multipliers()` with three-tier fallback (user override → built-in → identity) and clamp.
- `compute_portfolio_sleeve_columns()` multiplies final `core_score` / `future_score` / `early_score` by regime-keyed scalars AFTER Phase 3 composition AND penalty subtraction but BEFORE winsorize/clip.
- Four new diagnostic columns: `regime_sleeve_multiplier_{core,future,early}`, `regime_sleeve_weights_active`.
- Dual-gate toggle: `cfg.regime_dynamic_sleeve_weights_enabled=True` AND `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED=1` both required.
**Ship gate**: Δ CAGR ≥ +0.5pp AND Δ Sharpe ≥ +0.05.

**(Historical design notes — kept for reference, superseded by implementation above)**

**Why**: Today's sleeve composites use **static** factor weights across every regime. But the right weight for `uptrend_continuation_score` in a risk-on bull market is very different from the right weight in a systemic-crisis regime. The engine already has a regime label (`event_regime_label`) — it just doesn't use it to modulate sleeve weights.

**Plan**:
1. Add a regime→weight-multiplier table keyed on the confirmed regime label:
   ```python
   SLEEVE_FACTOR_REGIME_MULTIPLIERS = {
       "growth_reentry":      {"uptrend_continuation_score": 1.50, "value_inflection_score": 1.30, ...},
       "balanced":            {"uptrend_continuation_score": 1.00, "value_inflection_score": 1.00, ...},
       "stagflation":         {"uptrend_continuation_score": 0.70, "value_inflection_score": 1.20, ...},
       "systemic_crisis":     {"uptrend_continuation_score": 0.40, "value_inflection_score": 0.50,
                               "fundamental_turnaround_acceleration_score": 1.40, ...},
       "carry_unwind":        {...},
       "war_oil_rate_shock":  {...},
   }
   ```
2. Apply multipliers at the end of `compute_portfolio_sleeve_columns` per-row using the `event_regime_label` (or `confirmed_regime_label` from Phase 6 smoothing if/when implemented).
3. Keep the default multiplier table **learned or informed**: start from qualitative priors (growth signals up-weighted in growth_reentry, value signals up in stagflation, turnaround signals up in systemic_crisis), then grid-search a small number of permutations on the backtest.

**Files touched**: `r1000_top30_institutional.py :: compute_portfolio_sleeve_columns`. Possibly add a new helper `apply_regime_factor_multipliers(d, cfg)`.

**Config fields to add**:
```python
regime_dynamic_sleeve_weights_enabled: bool = False    # default OFF
regime_sleeve_multiplier_table: dict | None = None      # None = use built-in default
```

**Expected impact**: +0.5 to +2pp CAGR in mixed-regime periods. Biggest impact on Sharpe (regime-appropriate factor emphasis should reduce wrong-factor drag).

**Complexity**: MEDIUM (~100-200 lines + tuning). Core is straightforward; the multiplier table calibration requires A/B runs.

**Runtime**: QUICK rescore once the multiplier table is wired in. FULL rebuild only if new regime labels are introduced.

**Gate**: `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED`.

**Acceptance criteria**: Δ CAGR ≥ +0.5pp AND Sharpe improves ≥ +0.05.

**Dependencies**: Best combined with Phase 6 regime smoothing to avoid whipsaw in the multipliers.

---

### Phase 5 ✅ DONE (2026-04-17, default ON) — Sub-Industry Leader/Laggard Pair Signal

**Commit**: `0756636 Add Phase 5 sub-industry leader/laggard signals (default ON, bumps reuse version)`
**Status**: Infrastructure landed, default ON, awaiting FULL rebuild to bake Phase 5 columns into feature_store_latest.parquet.
**Implementation**:
- New module constant `PHASE5_LEADER_LAGGARD_COLUMNS` with 3 column names.
- New helper `add_sub_industry_leader_laggard_signals(monthly, min_group_size=6, gap_threshold=0.8)` computes `industry_leader_gap` = (top-quartile mean − median) / std per (rebalance_date, industry_group), plus `industry_leader_bonus_score` (top-quartile rows in strong groups with clear gap separation) and `industry_laggard_penalty_score` (bottom-quartile mirror).
- Wired into `build_universe_monthly` right after `compute_oneil_leadership_score` / `add_industry_rotation_signal`, with standard toggle/zero-fill fallback.
- Invariant #8: columns whitelisted in both `build_feature_store.keep_cols` and both `hard_sanitize` numeric lists.
- Sleeve composites: `(0.25, bonus)` + `(−0.15, penalty)` in future (highest), `(0.15, bonus)` in core, `(0.10, bonus)` in early.
- Dual-gate toggle: `cfg.sub_industry_leader_laggard_enabled=True` AND `PHASE_PHASE5_LEADER_LAGGARD_ENABLED=1`, both default ON.
- **`ENGINE_REUSE_VERSION` bumped to `"2026-04-17-phase5-leader-laggard"`** → forces FULL rebuild on next Colab run.
**Ship gate**: Δ CAGR ≥ +0.3pp AND future-sleeve hit-rate improves ≥ +2pp.

**(Historical design notes — kept for reference, superseded by implementation above)**

**Why**: Phase 2 gives us industry-level RS. The next refinement: within a leading industry, the strongest name should get a bonus AND the weakest name should get a penalty. Pairs-style logic captures "leaders pull away, laggards get left behind" — an IBD/O'Neil empirical regularity.

**Plan**:
1. Within each `industry_group` (or `industry` if N ≥ 6), rank names by `oneil_leadership_score` or `composite_score`.
2. Compute:
   - `industry_leader_rank_pct` — already exists as `industry_within_leader_rank`; reuse or extend.
   - `industry_leader_gap` — (top-quartile mean score − median score) / std of score in group. Large gap = clear leader separation.
   - `industry_leader_bonus_score` — positive multiplier for top-quartile names when `industry_leader_gap` is large AND industry is in top-half of `industry_group_strength_score`.
   - `industry_laggard_penalty_score` — mirror, negative multiplier for bottom-quartile names in the same strong industry (weakest name in a strong group is often about to catch down).
3. Wire into `compute_portfolio_sleeve_columns` with modest weight: `future` and `core` benefit more than `early` (early is already rotation-heavy, doesn't want to double-count).

**Files touched**: new helper `add_sub_industry_leader_laggard_signals(monthly)` in `r1000_top30_institutional.py`, called from `build_universe_monthly` right after `compute_oneil_leadership_score`. Schema change → **FULL rebuild required** the first time.

**Config fields to add**:
```python
sub_industry_leader_laggard_enabled: bool = True
sub_industry_min_group_size: int = 6
sub_industry_leader_gap_threshold: float = 0.8   # std units
```

**Expected impact**: +0.3 to +1.5pp CAGR from cleaner within-group picks. Biggest impact on hit-rate of the `future` sleeve.

**Complexity**: LOW-MEDIUM (~80 lines + one FULL rebuild to bake into cache).

**Runtime**: FULL rebuild once to populate the feature store; QUICK rescore thereafter.

**Gate**: `PHASE_PHASE5_LEADER_LAGGARD_ENABLED`.

**Acceptance criteria**: Δ CAGR ≥ +0.3pp AND `future` sleeve hit-rate improves ≥ +2pp.

---

### Phase 6 ✅ DONE (2026-04-17) — Risk-Off Tail Protection

**Three sub-proposals landed as separate commits**:
- **Phase 6a** ✅ (commit `b4c63c9`, default ON): 3-level drawdown circuit breaker. Thresholds −8%/−15%/−25% → cash floors 15%/35%/60% with equity-based recovery hysteresis (`dd_trigger_equity * (1 + 0.03)` overshoot required). Legacy single-threshold breaker preserved as fallback. 11 new EngineConfig fields. Three new `ret_rows` diagnostic columns: `dd_breaker_level`, `dd_trigger_equity`, `dd_breaker_multilevel_active`. Scale factor (0.9/0.7/0.4) read but not yet applied — cash floor alone drives defense via existing sleeve renormalisation. Ship gate: Δ MaxDD ≤ −3pp AND Δ CAGR ≥ −0.5pp.
- **Phase 6b** ✅ (commit `4c3274d`, default ON): VIX level hard guard. 4 tiers (22/28/35/45 → cash floors 10%/25%/40%/55%) applied inside `compute_regime_portfolio_controls()` right before the final `np.clip`. `vix_level` already in `MACRO_REGIME_COLUMNS` — no new data source needed. 9 new EngineConfig fields. Composes with Phase 6a via `max()`. Ship gate: Δ MaxDD ≤ −1pp in VIX-spike periods.
- **Phase 6c** ✅ (commit `ee93fa0`, **default OFF** per PROPOSAL §7): Volatility targeting. 6-month trailing realized vol × sqrt(12) vs 12% annualized target. Scale = clip(target/max(realized, target), 0.5, 1.0). Expressed as dynamic cash floor `1.0 − scale`, composing with Phase 6a/6b via `max()` chain. 5 new EngineConfig fields. Three new ret_rows diagnostics: `vol_target_active`, `vol_cash_floor_p6c`, `recent_returns_len`. Ship gate: Δ Sharpe ≥ +0.05 AND Δ CAGR ≥ −1pp.

**Follow-up `f7ec511`**: pre-rebuild audit spotted `getattr(cfg, ..., False)` mismatch vs EngineConfig default `True` for Phase 6a/6b. Fixed defensively. No behavior change in active paths (cfg is always populated).

**Skipped for Phase 6 (still open)**:
- `PROPOSAL_defensive_upgrades.md §2` (per-sleeve stop-loss) — defer.
- `PROPOSAL_defensive_upgrades.md §4` (yield curve inversion) — proposed as Phase 7c.
- `PROPOSAL_defensive_upgrades.md §5` (cross-asset confirmation) — proposed as Phase 7c.
- `PROPOSAL_defensive_upgrades.md §6` (regime transition smoothing) — defer.

**(Historical design notes — kept for reference, superseded by implementation above)**

**Why**: Baseline MaxDD is −36.86% — acceptable in a bull market but unsafe as a permanent profile. The single most asymmetric improvement is cutting tail drawdowns without sacrificing CAGR.

**Plan**: Implement the three highest-leverage proposals from `PROPOSAL_defensive_upgrades.md` (already written — **read that file first**). In order of impact-per-complexity:

1. **Portfolio drawdown circuit breaker** (PROPOSAL_defensive_upgrades.md §Proposal 1)
   - Ladder: −8% DD → 15% cash floor; −15% → 35%; −25% → 60%.
   - Recovery hysteresis: equity must overshoot the trigger by 3% before the ladder resets.
   - Insertion: inside `backtest_portfolio()` monthly loop, after `net_ret = month_ret - cost` and before `current_w = drift_weights_by_period_returns(...)`.
   - Expected: MaxDD improves 3-8pp; CAGR within ±0.5pp.

2. **VIX level hard guard** (PROPOSAL_defensive_upgrades.md §Proposal 3)
   - Tiered cash floor based on absolute VIX: 22→10%, 28→25%, 35→40%, 45→55%.
   - Insertion: inside `compute_regime_portfolio_controls()`, right before the final `cash_target = np.clip(...)`.
   - Expected: catches fast VIX spikes that the 63d z-score lags.
   - No new data — `vix_level` already in `month_df`.

3. **Volatility targeting** (PROPOSAL_defensive_upgrades.md §Proposal 7)
   - Scale all non-cash weights by `target_vol / max(realized_vol, target_vol)`, clipped to `[0.5, 1.0]`.
   - Rolling 6-month lookback; annualized target 12%.
   - Insertion: inside `backtest_portfolio()` after the drawdown breaker block.
   - **Default OFF** until measured — aggressive targeting can hurt returns in calm markets.

**Skipped for now** (Phase 6b if needed): per-sleeve stop-loss (Proposal 2), yield curve inversion signal (Proposal 4), cross-asset confirmation (Proposal 5), regime transition smoothing (Proposal 6). These are worth revisiting after Phase 6a lands.

**Files touched**: `r1000_top30_institutional.py :: backtest_portfolio` + `compute_regime_portfolio_controls`. The breaker + vol targeting need tracker state (`dd_peak_equity`, `recent_returns`) added right after `speculative_cum_ret` dict initialization.

**Config fields to add**: see `PROPOSAL_defensive_upgrades.md :: EngineConfig Summary`. Drawdown breaker = 11 fields, VIX guard = 9 fields, vol targeting = 5 fields.

**Expected impact**: MaxDD improves 5-10pp; Sharpe improves 0.05-0.15; CAGR ±0.5pp.

**Complexity**: MEDIUM (~300 lines across 3 sub-proposals). Each sub-proposal has a fully-worked design in the PROPOSAL doc — follow it exactly including the math / recovery-buffer sign fix called out on line 153.

**Runtime**: QUICK rescore IF the breaker / guard / vol targeting hooks are only used inside `backtest_portfolio` (they don't change feature_store content). **However**, backtest re-runs from first principles so it still takes ~1 hour even under quick-rescore. Verify empirically.

**Gate**: Each sub-proposal has its own `*_enabled` flag (see proposal doc). An umbrella `PHASE_PHASE6_DEFENSIVE_ENABLED` env toggle can group them for A/B.

**Acceptance criteria**: Δ MaxDD ≤ −3pp (i.e. improvement) AND Δ CAGR ≥ −0.5pp (i.e. not much worse) AND Δ Sharpe ≥ +0.05.

---

## 3. Implementation Order & PR Plan

**STATUS AS OF 2026-04-17 10:15 KST**: All PRs A..F landed. Phase 3 A/B ran and was REJECTED; Phase 4/5/6a/6b/6c infrastructure is in place. Next action is the FULL rebuild + per-phase A/B measurements described in `SESSION_HANDOFF.md` §2-§3.

| PR | Phase | Commit | Status | Files | Must-pass gate |
|---|---|---|---|---|---|
| A | Phase 3 audit + renorm | `5b95e17` + `8b10bf4` + `28e41fe` | ❌ A/B rejected | `r1000_top30_institutional.py` | Renorm ON ≥ Renorm OFF ≥ Phase 1+2 off |
| B | Phase 4 regime weights | `6b790cb` | ✅ landed, default OFF, A/B pending | `r1000_top30_institutional.py` | Δ CAGR ≥ +0.5, Δ Sharpe ≥ +0.05 |
| C | Phase 5 leader/laggard | `0756636` | ✅ landed, default ON, FULL rebuild pending | `r1000_top30_institutional.py` + ENGINE_REUSE_VERSION bump | Δ CAGR ≥ +0.3, future-sleeve hit-rate ↑ |
| D | Phase 6a DD breaker | `b4c63c9` | ✅ landed, default ON | `r1000_top30_institutional.py` (backtest_portfolio) | Δ MaxDD ≤ −3pp, Δ CAGR ≥ −0.5pp |
| E | Phase 6b VIX guard | `4c3274d` | ✅ landed, default ON | `r1000_top30_institutional.py` (regime_controls) | Δ MaxDD ≤ −1pp in VIX-spike periods |
| F | Phase 6c vol target | `ee93fa0` | ✅ landed, default OFF | `r1000_top30_institutional.py` (backtest_portfolio) | Δ Sharpe ≥ +0.05, Δ CAGR ≥ −1pp |
| G | Glue — notebook + handoff rotate | `33ed065` | ✅ landed | `colab_run.ipynb`, `SESSION_HANDOFF.md` | — |
| H | Audit-hardening getattr alignment | `f7ec511` | ✅ landed | `r1000_top30_institutional.py` | — |

Each PR:
1. Write code + env-var toggle (`PHASE_<KEY>_ENABLED`, default ON for A/B/C/D/E, default OFF for F).
2. Run A/B (ON vs OFF) with the quick-rescore preset.
3. Diff `outputs/concentrated_backtest_metrics.json`.
4. Write CHANGELOG entry (use the Agent Update Contract at the top of `CHANGELOG.md`).
5. Commit with a clear message. Push to `origin/master` only after A/B shows acceptance.

---

## 4. Baseline Reference (2026-04-15, pre-Phase 1+2)

From `outputs/concentrated_backtest_metrics.json`:

```json
{
  "portfolio_mode": "concentrated_alpha",
  "rebalance_date": "2026-04-15",
  "selected_names": 2,
  "weighting_mode": "conviction_curve",
  "recommended_rebalance_interval_months": 1,
  "strategy_cagr": 0.2180,
  "sharpe": 0.73,
  "max_dd": -0.3686,
  "comparison_objective": 0.1517
}
```

Use these as the dated baseline for every subsequent A/B comparison. Always copy the same JSON keys into CHANGELOG validation sections so comparisons are apples-to-apples.

---

## 5. Key Invariants a cold-start agent MUST preserve

1. **Schema stability**: if a phase is disabled, every column the downstream code depends on must still exist (zeroed out, not missing). Downstream sleeve code does not null-guard.
2. **Walk-forward embargo**: 126-day embargo is a hard no-lookahead requirement. Never feed future data into train folds.
3. **Point-in-time fundamentals**: SEC `accepted` timestamp gates fundamentals — never use `period_end`. Already enforced in `build_fundamental_panel`.
4. **Cache invalidation**: any signal-formula change must bump `ENGINE_REUSE_VERSION`. Infra changes (toggles, presets) do NOT need a bump.
5. **A/B toggle parity**: every new phase must zero out its columns on disable, not raise KeyError.
6. **CHANGELOG contract**: every commit touching code/notebooks must have a matching CHANGELOG entry in English with all fields populated (see top of `CHANGELOG.md`).
7. **Quick-rescore caveat**: sleeve-weight and toggle changes propagate; signal-formula changes DO NOT propagate through quick-rescore. Force FULL rebuild when in doubt.
8. **`build_feature_store.keep_cols` survival (2026-04-16 phase2-keepcols-fix)**: Any new phase column attached inside `build_universe_monthly` must ALSO be listed in a `PHASE<N>_<NAME>_COLUMNS` constant and appended to the `keep_cols` whitelist in `build_feature_store`. Otherwise the column is dropped from `feature_store_latest.parquet`, walk-forward sees NaN, the sleeve composite silently collapses to 0.0, and the phase contributes nothing while showing no error. Phase 1 hid this bug by accident (its columns are re-derived in `score_latest_month` / `prepare_latest_scored_data`); Phase 2 exposed it (no re-derivation). Match the pattern of `PHASE2_INDUSTRY_COLUMNS` when adding Phase 3..6.

---

## 6. Reference Files

- `PROPOSAL_defensive_upgrades.md` — full design for the Phase 6 sub-proposals (drawdown breaker, stop-loss, VIX, yield curve, cross-asset, regime smoothing, vol targeting). **Read this before starting Phase 6.**
- `PROPOSAL_growth_regime_offense_defense.md` — alternative architecture doc. Some ideas overlap with Phase 4; check for good material before writing the regime multiplier table.
- `CLAUDE.md` — project basics (paths, env, commands, known issues, current engine version, config presets).
- `CHANGELOG.md` — chronological decision log. **The newest entries are the single source of truth for the current state.** Always read the last ~10 entries when starting a new chat session.
- `colab_run.ipynb` — Colab runbook. Cell 2 = mount + phase toggles. Cell 3 = collector. Cell 4 = pipeline + validation (branches on `QUICK_RESCORE_ONLY`). Cells 9-11 = Phase 1+2 sanity checks + baseline delta.
- `r1000_data_collector.py` — collector + validation suite + config presets (`collector_full_run_cfg`, `collector_lean_full_run_cfg`, `collector_reuse_step2_cfg`, `pipeline_quick_rescore_cfg`).
- `r1000_top30_institutional.py` — main engine. ~25,600 lines. Key functions by name: `build_universe_monthly`, `compute_strategy_blueprint_columns`, `compute_portfolio_sleeve_columns`, `compute_regime_portfolio_controls`, `backtest_portfolio`, `train_walkforward`, `run_default_pipeline`.

---

## 7. Session-continuation checklist

When you pick this up in a new chat / new machine, do this in order:

1. **Read `SESSION_HANDOFF.md` FIRST** — single-item inbox for "last thing done + next action". This file is authoritative over everything else for the immediate next step.
2. Read `CLAUDE.md` (project basics).
3. Read the last ~200 lines of `CHANGELOG.md` (most recent decisions).
4. Read this file (PHASE_ROADMAP.md) to see what's planned.
5. Run `git log --oneline -5` to confirm you have the latest commit.
6. Check `outputs/concentrated_backtest_metrics.json` on Drive for the most recent baseline number to compare against.
7. Decide which phase is next based on the PR plan (§3). If Phase 3 is still pending, start there — BUT only if `SESSION_HANDOFF.md` says the previous phase was verified.
8. Work in QUICK_RESCORE_ONLY mode unless the change requires FULL rebuild (see §1 table).
9. Commit with CHANGELOG entry when A/B gate passes.
10. **When a phase ships: rewrite `SESSION_HANDOFF.md` with the new "last thing done + next action"**. Never accumulate multiple handoffs.
