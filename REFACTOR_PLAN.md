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
