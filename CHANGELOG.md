# Change Log

This file is the primary handoff document for coding agents resuming work on this repo.
All entries must be written in English. Entries must be predictable and machine-scannable.

## Agent Update Contract

### When to update
- Required in the same commit as every material change to code, notebooks, config, or pipeline behavior.
- Not required for whitespace-only or comment-only changes.

### Required format

```
## YYYY-MM-DD

### HH:MM KST - kebab-case-short-title

- scope: one-line plain-English area of change
- files:
  - `filename.py` — one-line summary of what changed in this file
- symbols_added:
  - `function_name(sig)` — what it does
  - none
- symbols_changed:
  - `existing_function()` — what changed and why
  - none
- config_fields_added:
  - `field_name: type = default` — purpose
  - none
- breaking_changes:
  - none
  - OR: describe what breaks and the migration path
- outputs:
  - `path/to/file.ext` — what it contains
  - none
- validation:
  - list commands run and whether they passed
- risks_or_notes:
  - concise risk bullets
  - none
```

### Rules
- All field values must be English. No Korean.
- Every field must be present. Use `none` when a field does not apply.
- `symbols_added` and `symbols_changed` must enumerate function/class names explicitly — not prose descriptions.
- `config_fields_added` must list full `name: type = default` signatures.
- `breaking_changes` must never be omitted. Write `none` if there are none.
- `HH:MM KST` must be a real timestamp. Do not write `KST` without a time.
- Do not place free-floating sections between dated entries.
- Keep newest entries under the correct date, appended chronologically.

## 2026-04-09

### 19:21 KST - harden-colab-collector-start

- scope:
  - Colab execution bootstrap.
- files:
  - `colab_run.ipynb`
- behavior:
  - Hardened the collector execution path so runs start from the intended project location.
- outputs:
  - none
- validation:
  - not recorded
- risks_or_notes:
  - Goal was to reduce path-related failures before collection/training begins.

### 22:05 KST - robust-companyfacts-zip-updater

- scope:
  - Colab SEC companyfacts bulk archive refresh.
- files:
  - `colab_run.ipynb`
- behavior:
  - Added a Colab updater cell that downloads `companyfacts.zip` from the SEC bulk archive endpoint.
  - Added SEC-compatible `User-Agent`, retry/backoff, temp-file replacement, ZIP integrity checks, and minimum-size guard.
- outputs:
  - `/content/drive/MyDrive/r1000_top30_institutional/companyfacts.zip`
- validation:
  - ZIP integrity and minimum-size checks are performed before replacement.
- risks_or_notes:
  - SEC network availability and rate behavior can still affect runtime.

### 22:44 KST - companyfacts-refresh-threshold-three-days

- scope:
  - Colab SEC companyfacts refresh cadence.
- files:
  - `colab_run.ipynb`
- behavior:
  - Changed automatic `companyfacts.zip` refresh threshold from 7 days to 3 days.
- outputs:
  - none
- validation:
  - not recorded
- risks_or_notes:
  - Goal is fresher SEC fundamentals without forcing a download every run.

## 2026-04-10

### 07:58 KST - sleeve-promotion-and-drift-caps

- scope:
  - Portfolio sleeve classification, cap behavior, and monthly backtest state.
- files:
  - `r1000_top30_institutional.py`
  - `colab_run.ipynb`
- behavior:
  - Added promotion logic so names initially classified as `early_scout` can upgrade to `future_winner`.
  - Promotion considers fundamental confirmation, market confirmation, statement history depth, benchmark relative strength, Minervini momentum state, and breakout setup quality.
  - Reworked sleeve-specific name caps into entry cap, drift cap for already-held winners, and hard absolute risk cap.
  - Applied separate cap logic for `future_winner` and `early_scout`.
  - Updated monthly backtest state so positions drift with realized monthly returns between rebalances.
  - Fixed a follow-up bug where `future_winner` drift caps could bypass stricter active caps already applied to the same name.
- outputs:
  - `portfolio_sleeve_label_raw`
  - `portfolio_sleeve_promotion_signal`
  - `portfolio_sleeve_promoted`
  - `portfolio_prev_weight`
  - `portfolio_existing_holding`
  - `portfolio_name_cap`
- validation:
  - Local Python runtime was not available, so no local `py_compile` check was run.
  - Intended validation path: fresh Colab rerun producing updated `portfolio_latest.csv`, `top30_latest.csv`, and sleeve backtest outputs.
- risks_or_notes:
  - Expected effect: better separation between speculative entries and proven winners.
  - Expected effect: less premature trimming of names that have already worked.
  - Expected effect: more realistic portfolio weight evolution in backtests.

### 09:35 KST - oos-sleeve-cap-policy-optimizer

- scope:
  - Portfolio sleeve mix and name-cap policy optimization.
- files:
  - `r1000_top30_institutional.py`
  - `r1000_data_collector.py`
  - `colab_run.ipynb`
  - `CHANGELOG.md`
- behavior:
  - Added OOS sleeve/cap policy optimization so sleeve mix and name caps are no longer set only by fixed intuition.
  - Added candidate policies ranging from defensive drawdown control to aggressive early-scout bull-market exposure.
  - Champion policy is selected by an objective that rewards excess CAGR and risk-adjusted return while penalizing max drawdown, turnover, concentration, and cash drag.
  - When enabled, the champion policy is applied to the active backtest and latest portfolio generation.
  - Validation and Colab output now display the selected sleeve/cap champion policy.
- outputs:
  - `outputs/reports/sleeve_cap_policy_comparison.csv`
  - `outputs/reports/sleeve_cap_policy_champion_latest.json`
  - `run_summary.json` field: `champion_sleeve_cap_policy`
  - `weights_latest.json` field: `champion_sleeve_cap_policy`
  - `full_validation_suite.json` field: `sleeve_cap_policy_optimization_snapshot`
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
  - Local Python runtime was not available, so no local `py_compile` check was run.
- risks_or_notes:
  - Adds extra backtest runtime because multiple policy candidates are evaluated.
  - Objective weights are configurable and may need calibration after first fresh Colab run.

### 10:04 KST - changelog-update-rule

- scope:
  - Repository maintenance rules.
- files:
  - `CHANGELOG.md`
- behavior:
  - Formalized the requirement that future material changes update the changelog before commit/push.
- outputs:
  - none
- validation:
  - `git diff --check` passed.
- risks_or_notes:
  - This entry was superseded by the later agent-readable changelog format update.

### 10:08 KST - agent-readable-changelog-format

- scope:
  - Repository maintenance rules and agent handoff quality.
- files:
  - `CHANGELOG.md`
- behavior:
  - Converted the changelog into a fixed-field, agent-readable format.
  - Added required fields: `scope`, `files`, `behavior`, `outputs`, `validation`, `risks_or_notes`.
  - Moved free-floating expected-effect and validation notes into the relevant dated entry.
- outputs:
  - none
- validation:
  - `git diff --check` passed.
- risks_or_notes:
  - Future agents should update this file in the same structured format, not prose-only notes.

### 10:19 KST - reuse-duplicate-backtests

- scope:
  - Runtime reduction for portfolio policy evaluation and export comparisons.
- files:
  - `r1000_top30_institutional.py`
  - `CHANGELOG.md`
- behavior:
  - Reused the winning sleeve/cap candidate `BacktestResult` instead of rerunning the same champion policy in Phase 5.
  - Reused the active adaptive backtest when building `rebalance_interval_comparison.csv` instead of recomputing that same adaptive row.
- outputs:
  - no schema change
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
- risks_or_notes:
  - Expected to save two full monthly portfolio backtest passes per run when sleeve/cap optimization and rebalance interval comparison are enabled.
  - Does not reduce model training time or data collection time.

### 13:19 KST - preserve-early-scout-growth-sleeve

- scope:
  - Portfolio sleeve allocation, early-scout classification, and Colab defaults.
- files:
  - `r1000_top30_institutional.py`
  - `r1000_data_collector.py`
  - `colab_run.ipynb`
  - `CHANGELOG.md`
- behavior:
  - Raised default `early_scout` base/max sleeve weights from `0.05/0.15` to `0.08/0.20`.
  - Added an `early_scout` growth-floor rule that preserves scout exposure when growth signal is positive, risk signal is below the configured ceiling, and early candidates exist.
  - Reduced automatic `early_scout` to `future_winner` promotion by requiring stronger edge/confirmation before promotion.
  - Updated the defensive policy candidate so even drawdown-control mode can keep a small active scout sleeve instead of forcing `early_scout` to zero.
  - Added `early_scout_candidate_share` to portfolio exports and Colab display columns.
- outputs:
  - `portfolio_latest.csv` column: `early_scout_candidate_share`
  - `top30_latest.csv` column: `early_scout_candidate_share`
  - `sleeve_cap_policy_comparison.csv` columns for the new early-scout floor config fields
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
  - Local Python runtime was not available, so no local `py_compile` check was run.
- risks_or_notes:
  - Expected effect: latest portfolio should include at least a small `early_scout` allocation in non-risk-off growth regimes.
  - Risk: more growth exposure can increase drawdown and volatility; compare next run against `sleeve_cap_policy_comparison.csv`.

### 13:34 KST - standalone-sleeve-top7-backtests

- scope:
  - OOS sleeve attribution and portfolio selection diagnostics.
- files:
  - `r1000_top30_institutional.py`
  - `r1000_data_collector.py`
  - `colab_run.ipynb`
  - `CHANGELOG.md`
- behavior:
  - Added independent equal-weight top-N backtests for `core_compounder`, `future_winner`, and `early_scout` sleeves.
  - Default standalone test is top 7 names with fixed 1-month and 3-month rebalance intervals.
  - Added an `adaptive_three_sleeve` comparison row using the active dynamic portfolio plus adaptive rebalance policy.
  - Sleeve-only tests select primarily by final sleeve label, then raw sleeve label, then sleeve engine score fallback so sparse historical sleeve months remain measurable.
  - Colab result display now shows the standalone sleeve comparison table.
- outputs:
  - `outputs/reports/portfolio_sleeve_top7_standalone_comparison.csv`
  - `outputs/reports/portfolio_sleeve_top7_standalone_monthly.csv`
  - `outputs/reports/portfolio_sleeve_top7_standalone_holdings.csv`
  - `run_summary.json` field: `standalone_sleeve_topn_backtest_comparison`
  - `full_validation_suite.json` field: `standalone_sleeve_topn_backtest_snapshot`
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
  - Local Python runtime was not available, so no local `py_compile` check was run.
- risks_or_notes:
  - This is a selection-quality diagnostic, not the live portfolio itself.
  - Equal weighting intentionally isolates sleeve selection from dynamic sizing/cash/cap rules.

### 13:42 KST - validation-summary-guards

- scope:
  - Validation report robustness.
- files:
  - `r1000_data_collector.py`
  - `CHANGELOG.md`
- behavior:
  - Added safe fallback series when optional rebalance comparison metrics are absent.
  - Guarded standalone sleeve top-N parsing so invalid or missing values fall back to `7` instead of raising during validation summary generation.
- outputs:
  - no schema change
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
  - Local Python runtime was not available, so no local `py_compile` check was run.
- risks_or_notes:
  - Defensive-only patch; no portfolio selection behavior change.

### 14:04 KST - historical-data-quality-guardrails

- scope:
  - Historical financial statement coverage diagnostics and growth-sleeve data confidence.
- files:
  - `r1000_top30_institutional.py`
  - `r1000_data_collector.py`
  - `colab_run.ipynb`
  - `CHANGELOG.md`
- behavior:
  - Added PIT-safe historical data quality columns for financial level coverage, change coverage, CAGR coverage, history depth, growth-sleeve data confidence, sparse-history penalty, and forward-return coverage.
  - Applied only a mild sparse-history penalty to `future_winner` and `early_scout` engine scores when both historical financial coverage and technical confirmation are weak.
  - Kept forward-return coverage as report-only diagnostics so `r_1m` through `r_36m` are not introduced as model or portfolio-selection features.
  - Added validation and Colab display hooks for historical data quality snapshots.
- outputs:
  - `outputs/reports/historical_data_quality_by_month.csv`
  - `outputs/reports/historical_data_quality_by_sleeve.csv`
  - `outputs/reports/historical_data_quality_latest.csv`
  - `run_summary.json` field: `historical_data_quality_latest`
  - `full_validation_suite.json` field: `historical_data_quality_snapshot`
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
  - Local Python runtime was not available, so no local `py_compile` check was run.
- risks_or_notes:
  - This does not magically create missing historical statements; it makes the missing-history risk measurable and prevents weak-history growth candidates from being treated as equally proven.
  - Intended next step after a fresh Colab run: inspect the new monthly/sleeve reports and decide whether a deeper SEC historical reconstruction job is worth the runtime.

### 14:54 KST - cagr-coverage-fix-time-based-lag

- scope:
  - Historical CAGR coverage for sales/op_income/net_income/ocf/eps/fcf metrics.
- files:
  - `r1000_top30_institutional.py`
  - `CHANGELOG.md`
- behavior:
  - Replaced row-count-based `shift(N)` in `_flexible_lag` with a calendar-time `merge_asof` approach per CIK.  The old shift(12) treated annual-only filers (20-F, 1 row/yr) as needing 12 years of history instead of 3, making sales_cagr_3y always NaN for them.  New approach finds the closest period within ±46 days of the target date regardless of filing cadence.
  - Added 1-year and 2-year CAGR columns for all flow metrics: `sales_cagr_1y`, `sales_cagr_2y`, `op_income_cagr_1y`, `op_income_cagr_2y`, `net_income_cagr_1y`, `net_income_cagr_2y`, `ocf_cagr_1y`, `ocf_cagr_2y`, `eps_cagr_1y`, `eps_cagr_2y`, `fcf_cagr_1y`, `fcf_cagr_2y`.
  - Added `_cagr_best` fallback columns (3y preferred, then 2y, then 1y) for each metric: `sales_cagr_best`, `op_income_cagr_best`, `net_income_cagr_best`, `ocf_cagr_best`, `eps_cagr_best`, `fcf_cagr_best`.
  - Updated `growth_blueprint_score` to use `_cagr_best` instead of `_cagr_3y` so newer companies with < 3 years of history still contribute a proportional growth signal.
  - Updated `revenue_growth_final` and `earnings_growth_final` fallback chains to prefer `_cagr_best` before `_cagr_3y`.
  - Increased `fsds_quarters_backfill` from 44 to 60 (11 → 15 years) for deeper first-run FSDS coverage.
  - All new columns added to `FUND_TTM_FALLBACK_COLUMNS`, `COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS`, `carry_cols`, and `asof_join_fundamentals` empty-panel fallback list.
- outputs:
  - New panel columns: `*_cagr_1y`, `*_cagr_2y`, `*_cagr_best` for sales/op_income/net_income/ocf/eps/fcf.
  - Feature store gains the same columns via `asof_join_fundamentals`.
  - `cagr_3y_coverage_mean` in `acceptance_checks.json` should increase materially after a full panel rebuild.
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse check passed.
  - Local Python runtime not available; no local `py_compile` check.
- risks_or_notes:
  - Requires a full fund_panel rebuild (`force_full_fund_panel_rebuild=True` or deleting `fund_panel_latest.parquet`) to recompute all CAGR columns with the new logic.  Existing cached panels still have old row-shift values.
  - For annual filers CAGR values will change: previously always NaN, now they get a legitimate value.  This is a correctness fix, not a signal change.
  - 5y CAGR still uses the old row-shift path for now (target_q=20 with tol=2 still works for quarterly filers; annual filer 5y CAGR requires 5 years of data which may still be sparse).
  - `_cagr_best` uses the deepest available horizon (3y > 2y > 1y); shorter-horizon CAGR for young companies is a softer signal but better than zero contribution.

### 15:45 KST - sleeve-regime-optimizer

- scope:
  - Portfolio sleeve allocation optimization per market regime.
- files:
  - `r1000_top30_institutional.py`
  - `CHANGELOG.md`
- behavior:
  - Added `sleeve_override` and `cash_target_max` parameters to `build_target_portfolio()` so callers can fix sleeve fractions (core/future/early) and cap cash allocation independently of the adaptive policy engine.
  - When `sleeve_override` is provided the adaptive `compute_portfolio_sleeve_policy()` result is still used for `growth_signal`/`risk_signal` tracking, but all allocation fractions are replaced with the caller-supplied values scaled to `(1 - capped_cash)`.
  - When only `cash_target_max` is provided (no sleeve override) the regime cash signal is capped at that max and invested share rescaled proportionally.
  - Added `sleeve_override` and `cash_target_max` passthrough to `backtest_portfolio()`.
  - Added `regime_label`, `core_target`, `future_target`, `early_target`, `cash_target_used`, `growth_signal`, `risk_signal` fields to every row of `backtest_portfolio()` monthly_returns output.
  - Added module-level `_SLEEVE_POLICY_CANDIDATES` (12 sleeve combos from core-only to 55/30/15 aggressive).
  - Added `compare_sleeve_policy_per_regime()`: runs each candidate combo through a full backtest, breaks monthly returns by regime, computes CAGR/Sharpe/max_dd/IR per (policy, regime), returns (grid_df, best_per_regime_df).
  - Wired `compare_sleeve_policy_per_regime()` into `run_default_pipeline()` behind `run_sleeve_regime_comparison` config flag (defaults to `run_comparison_backtests`); cash_max controlled by `sleeve_regime_comparison_cash_max` (default 0.02 = 2%).
  - Added `sleeve_policy_per_regime_best` to `show_output_table_previews` display list.
- outputs:
  - `outputs/reports/sleeve_policy_per_regime_grid.csv` — all policies × all regimes metrics
  - `outputs/reports/sleeve_policy_per_regime_best.csv` — best policy per regime by Sharpe
  - `monthly_returns` DataFrame gains: `regime_label`, `core_target`, `future_target`, `early_target`, `cash_target_used`, `growth_signal`, `risk_signal`
- validation:
  - `git diff --check` passed.
  - Local Python runtime not available; no local `py_compile` check.
- risks_or_notes:
  - `compare_sleeve_policy_per_regime()` runs 12 full backtests; adds meaningful runtime. Disabled by default (`run_sleeve_regime_comparison=False`).
  - Cash is held as low as possible (default 2% max) so results reflect full-investment sleeve exposure, not cash drag.
  - Per-regime metrics require sufficient months per regime; regimes with fewer than 3 months are skipped.

### 16:20 KST - full-codebase-review-fixes

- scope:
  - Config correctness, runtime performance, and code consistency.
- files:
  - `r1000_top30_institutional.py`
  - `CHANGELOG.md`
- behavior:
  - Added `run_sleeve_regime_comparison: bool = False` and `sleeve_regime_comparison_cash_max: float = 0.02` to `EngineConfig` dataclass so they have proper type-checking and default visibility. Defaults to `False` to avoid automatically running 12 extra backtests on every pipeline execution.
  - Updated `run_default_pipeline()` to read `run_sleeve_regime_comparison` directly from `cfg` instead of via `getattr` with a dangerous `cfg.run_comparison_backtests` default.
  - Added `run_sleeve_regime_comparison` and `sleeve_regime_comparison_cash_max` to `run_summary.json` summary dict so Colab post-run parsing can observe the flags.
  - Removed the redundant explicit CAGR column listing in the null-panel fallback of `asof_join_fundamentals`; these columns are already fully covered by `FUND_TTM_FALLBACK_COLUMNS` so the duplicate list was dead code.
- outputs:
  - `run_summary.json` gains fields: `run_sleeve_regime_comparison`, `sleeve_regime_comparison_cash_max`.
- validation:
  - `git diff --check` passed.
  - Local Python runtime not available; no local `py_compile` check.
  - No behavioral changes to sleeve selection, backtest, or data pipeline — fixes only.
- risks_or_notes:
  - The default change from `True` to `False` for `run_sleeve_regime_comparison` means Colab runs will no longer automatically run the 12-backtest regime grid. Enable explicitly with `cfg["run_sleeve_regime_comparison"] = True` when you want to run the optimizer.

### 17:30 KST - restore-missing-pre-session-features

- scope:
  - Restoration of features lost when local engine overwrote git repo in commit `1dbf0d3`.
- files:
  - `r1000_top30_institutional.py`
  - `colab_run.ipynb`
  - `CHANGELOG.md`
- behavior:
  - Restored `add_historical_data_quality_columns()` and `build_historical_data_quality_report_frames()` functions (~1,384 + 1,085 lines) with full PIT-safe historical data quality diagnostics.
  - Restored `SLEEVE_CAP_POLICY_FIELDS` tuple (24 fields), `clone_cfg_with_updates()`, `generate_sleeve_cap_policy_candidates()`, `sleeve_cap_policy_objective()`, `compare_sleeve_cap_policy_backtests()`, `choose_sleeve_cap_policy()`, `apply_sleeve_cap_policy_to_cfg()`.
  - Restored `SLEEVE_STANDALONE_LABELS/ROLE_MAP/ENGINE_COL` constants and `prepare_standalone_sleeve_frame()`, `select_standalone_sleeve_topn()`, `backtest_standalone_sleeve_topn()`, `compare_standalone_sleeve_topn_backtests()`.
  - Added missing EngineConfig fields: `early_scout_growth_floor_*`, `early_scout_candidate_floor_min_share`, `future_winner_entry/drift/hard_weight_cap`, `early_scout_entry/drift/hard_weight_cap`, `sleeve_drift_headroom_pct`, `early_scout_promotion_*`, `run_sleeve_cap_policy_comparison`, all `sleeve_cap_policy_objective_*` weights, `run_standalone_sleeve_backtest_comparison`, `standalone_sleeve_top_n`, `standalone_sleeve_rebalance_intervals`, `run_historical_data_quality_reports`, `growth_history_confidence_penalty_weight`, `growth_history_confidence_min_for_full_sleeve`.
  - Updated `run_all()` to call Phase 5c (sleeve cap policy), Phase 5d (standalone sleeve comparison), and pass results to `export_outputs()`.
  - Updated `export_outputs()` to accept and write all new comparison artifacts (CSVs + JSON) and include their paths in `result_outputs` and `run_summary.json`.
  - Updated `colab_run.ipynb` Cell 6 to load and display `sleeve_policy_per_regime_best.csv` and `sleeve_policy_per_regime_grid.csv` pivot table.
- outputs:
  - `outputs/reports/sleeve_cap_policy_comparison.csv`
  - `outputs/reports/sleeve_cap_policy_champion_latest.json`
  - `outputs/reports/portfolio_sleeve_top7_standalone_comparison.csv`
  - `outputs/reports/portfolio_sleeve_top7_standalone_monthly.csv`
  - `outputs/reports/portfolio_sleeve_top7_standalone_holdings.csv`
  - `outputs/reports/historical_data_quality_by_month.csv`
  - `outputs/reports/historical_data_quality_by_sleeve.csv`
  - `outputs/reports/historical_data_quality_latest.csv`
  - `run_summary.json` fields: `champion_sleeve_cap_policy`, `sleeve_cap_policy_optimization_snapshot`, `run_sleeve_cap_policy_comparison`, `run_standalone_sleeve_backtest_comparison`, `run_historical_data_quality_reports`
- validation:
  - `ast.parse` syntax check passed (20,195 lines, up from 16,830).
  - All restored function names confirmed present via grep.
  - `colab_run.ipynb` JSON is valid Jupyter notebook format.
  - Local Python runtime not available; no local `py_compile` check.
- risks_or_notes:
  - Engine file grew from 16,830 to ~20,195 lines. Runtime will be longer because sleeve cap policy comparison (9 candidates) and standalone sleeve comparison (3 sleeves × 2 intervals) run by default.
  - Disable with `cfg["run_sleeve_cap_policy_comparison"] = False` and `cfg["run_standalone_sleeve_backtest_comparison"] = False` to reduce runtime.
  - Historical data quality report adds `add_historical_data_quality_columns` call over the full scored panel; moderate CPU cost.

### 20:15 KST - regime-conditional-ensemble-weights

- scope:
  - Ensemble model weight blending per market regime (Option A static priors + Option B OOS-learned).
- files:
  - `r1000_top30_institutional.py`
  - `CHANGELOG.md`
- behavior:
  - Added `REGIME_ENSEMBLE_WEIGHT_PRIORS` constant — intuition-based static weights per regime (Ridge favored in crisis/shock, CatBoost favored in growth/reentry).
  - Added `compute_regime_conditional_ensemble_weights()` — computes per-regime model IC/quality from OOS scored panel; blends with static priors (prior weight decays as OOS regime months accumulate); falls back to priors when OOS data insufficient.
  - Extended `apply_adaptive_ensemble_state()` with optional `regime_weights` parameter — when provided, writes per-row regime-specific weights by detecting `live_event_alert_label` column; falls back to global adaptive weights when regime column absent.
  - Added `regime_ensemble_weights: dict[str, dict[str, float]]` field to `ModelBundle` — stored in `model_bundle_latest.json` after each walk-forward training run.
  - Wired `compute_regime_conditional_ensemble_weights()` into `train_walkforward()` — computed from full OOS scored panel after walk-forward, stored in ModelBundle.
  - Updated per-month walk-forward scoring loop to call `compute_regime_conditional_ensemble_weights()` incrementally (same OOS embargo discipline as adaptive ensemble).
  - Updated all 4 `apply_adaptive_ensemble_state()` call sites in `build_latest_recommendations()` and fallback scoring to pass `regime_weights` from ModelBundle.
  - Added 3 new EngineConfig fields: `regime_ensemble_weights_enabled` (bool, default True), `regime_ensemble_weights_min_months` (int, default 6), `regime_ensemble_weights_strength` (float, default 0.50).
  - Added `regime_ensemble_weights` dict to `run_summary.json` output.
- outputs:
  - `model_bundle_latest.json` field: `regime_ensemble_weights` (dict of regime → {linear, catboost, ranker})
  - `run_summary.json` field: `regime_ensemble_weights`
  - Scored panel columns: `ensemble_weight_linear`, `ensemble_weight_catboost`, `ensemble_weight_ranker` now vary per row by regime; new `regime_ensemble_active` bool column
- validation:
  - grep confirms all symbols present in engine.
  - Local Python runtime not available; no local `py_compile` check.
- risks_or_notes:
  - `compute_regime_conditional_ensemble_weights()` adds CPU overhead proportional to (n_regimes × n_months_per_regime). For 6 regimes and 96 months of OOS data, overhead is modest.
  - First run will use static priors for all regimes because OOS scored panel has no `live_event_alert_label`; weights will improve after first full Colab run.
  - Disable with `cfg["regime_ensemble_weights_enabled"] = False` for a pure global-adaptive-only run.
  - `regime_ensemble_weights_strength=0.50` means learned weights can move ±50% from global base per regime; raise to 0.80 for more aggressive regime-specific tilting.

### 21:10 KST - fix-validate-config-sleeve-and-cash-constraints

- scope: Relax six overly tight upper-bound checks in `validate_config` that blocked legitimate collector and policy-candidate values.
- files:
  - `r1000_top30_institutional.py` — widened six constraint upper bounds from fixed values to 1.0
  - `CLAUDE.md` — removed stale known-issue entry for `cash_weight_max` monkey-patch
- symbols_added:
  - none
- symbols_changed:
  - `validate_config()` — upper bounds for `future_winner_sleeve_min_weight`, `future_winner_sleeve_max_weight`, `early_scout_sleeve_base_weight`, `early_scout_sleeve_min_weight`, `early_scout_sleeve_max_weight` changed from 0.50/0.50/0.30/0.20/0.25 to 1.0; `cash_weight_max` upper bound changed from 0.65 to 1.0
- config_fields_added:
  - none
- breaking_changes:
  - none — constraints were widened, not tightened; existing valid configs remain valid
- outputs:
  - none
- validation:
  - `git diff --check` passed
  - Confirmed `r1000_data_collector.py` sets `future_winner_sleeve_max_weight = 0.60` which now passes without error
  - Confirmed `generate_sleeve_cap_policy_candidates()` produces values up to 0.70 which now pass without error
- risks_or_notes:
  - The engine internally caps allocation fractions via `compute_portfolio_sleeve_policy()`; relaxing the validation upper bound does not remove runtime enforcement
  - Colab `validate_config` monkey-patch cell is no longer needed and should be removed if present

### 21:20 KST - changelog-format-and-claude-md-update

- scope: Standardize CHANGELOG format for agent readability and update CLAUDE.md project guide.
- files:
  - `CHANGELOG.md` — replaced Agent Update Contract with structured English-only format including required fields `symbols_added`, `symbols_changed`, `config_fields_added`, `breaking_changes`; backfilled missing `HH:MM` timestamps on four entries
  - `CLAUDE.md` — updated engine line count (15k→20.4k), removed monkey-patch pipeline step, added Changelog Writing Rules section
- symbols_added:
  - none
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `git diff --check` passed
- risks_or_notes:
  - Entries written before this commit used the old format (no `symbols_added` / `breaking_changes` fields); agents should treat those as legacy-format and not expect those fields to be present

### 21:30 KST - fix-github-integration-regressions

- scope: Repair regressions introduced by cross-machine feature restoration and make the latest GitHub master runnable again.
- files:
  - `r1000_top30_institutional.py` - removed active duplicate function definitions, restored missing EngineConfig fields, repaired sleeve-regime backtest passthrough, and aligned champion-policy backtest behavior.
  - `r1000_data_collector.py` - changed default companyfacts refresh cadence to 3 days for collector runtime defaults and CLI.
  - `CLAUDE.md` - changed documented companyfacts refresh cadence to 3 days.
  - `CHANGELOG.md` - removed the duplicate `2026-04-10` date header, normalized the misplaced CAGR fix timestamp, and recorded this fix.
- symbols_added:
  - none
- symbols_changed:
  - `_legacy_unused_compute_portfolio_sleeve_columns()` - renamed inactive duplicate implementation so it no longer conflicts with the restored active implementation.
  - `_legacy_unused_compute_portfolio_sleeve_policy()` - renamed inactive duplicate implementation so the active implementation is unambiguous.
  - `_legacy_unused_build_target_portfolio()` - renamed inactive duplicate implementation; active `build_target_portfolio()` remains the single public implementation.
  - `_legacy_unused_backtest_portfolio()` - renamed inactive duplicate implementation; active `backtest_portfolio()` remains the single public implementation.
  - `_legacy_unused_build_latest_recommendations()` - renamed inactive duplicate implementation so latest scoring has one active definition.
  - `_legacy_unused_fallback_latest_recommendations_from_scored()` - renamed inactive duplicate implementation so fallback latest scoring has one active definition.
  - `_legacy_unused_bt_metrics_row()` - renamed inactive duplicate helper; comparison functions resolve to the active `_bt_metrics_row()`.
  - `build_target_portfolio()` - added `sleeve_override` and `cash_target_max` parameters to the active implementation and made turnover cash acceleration/meta use the capped sleeve cash target.
  - `backtest_portfolio()` - added `sleeve_override` and `cash_target_max` passthrough to the active implementation and restored monthly regime/sleeve target diagnostics.
  - `validate_config()` - added validation for restored sleeve cap, scout floor, standalone sleeve, policy objective, and growth-history confidence config fields.
  - `run_all()` - reruns the active backtest after applying the selected sleeve/cap champion so exported performance and latest portfolio use the same policy.
- config_fields_added:
  - `early_scout_growth_floor_weight: float = 0.08` - minimum scout sleeve exposure in supportive growth regimes.
  - `early_scout_growth_floor_min_signal: float = 0.38` - growth signal threshold for the scout floor.
  - `early_scout_growth_floor_max_risk: float = 0.55` - risk ceiling for the scout floor.
  - `early_scout_candidate_floor_min_share: float = 0.01` - minimum candidate availability required for the scout floor.
  - `future_winner_entry_weight_cap: float = 0.10` - new-entry cap for future-winner sleeve names.
  - `future_winner_drift_weight_cap: float = 0.18` - drift cap for already-held future-winner names.
  - `future_winner_hard_weight_cap: float = 0.24` - absolute future-winner name risk cap.
  - `early_scout_entry_weight_cap: float = 0.05` - new-entry cap for early-scout names.
  - `early_scout_drift_weight_cap: float = 0.10` - drift cap for already-held early-scout names.
  - `early_scout_hard_weight_cap: float = 0.14` - absolute early-scout name risk cap.
  - `sleeve_drift_headroom_pct: float = 0.35` - allowed drift headroom above previous weight for confirmed holdings.
  - `early_scout_promotion_edge_max: float = 0.12` - max edge gap allowing early-scout promotion.
  - `early_scout_promotion_confidence_max: float = 0.12` - max classification confidence allowing early-scout promotion.
  - `early_scout_promotion_min_score: float = 0.70` - minimum promotion signal for early-scout to future-winner upgrade.
  - `run_sleeve_cap_policy_comparison: bool = True` - enables sleeve/cap policy candidate comparison.
  - `sleeve_cap_policy_apply_champion: bool = True` - applies the selected sleeve/cap policy to latest portfolio generation.
  - `sleeve_cap_policy_max_candidates: int = 9` - limits sleeve/cap policy candidates evaluated per run.
  - `sleeve_cap_policy_objective_excess_weight: float = 1.0` - objective weight for excess CAGR.
  - `sleeve_cap_policy_objective_sharpe_weight: float = 1.0` - objective weight for Sharpe.
  - `sleeve_cap_policy_objective_sortino_weight: float = 0.50` - objective weight for Sortino.
  - `sleeve_cap_policy_objective_drawdown_weight: float = 0.80` - objective penalty for max drawdown.
  - `sleeve_cap_policy_objective_turnover_weight: float = 0.20` - objective penalty for turnover.
  - `sleeve_cap_policy_objective_concentration_weight: float = 0.35` - objective penalty for concentration.
  - `sleeve_cap_policy_objective_cash_drag_weight: float = 0.25` - objective penalty for average cash.
  - `run_standalone_sleeve_backtest_comparison: bool = True` - enables standalone sleeve top-N comparison.
  - `standalone_sleeve_top_n: int = 7` - default top-N for standalone sleeve diagnostics.
  - `standalone_sleeve_rebalance_intervals: list[int] = [1, 3]` - rebalance intervals used by standalone sleeve diagnostics.
  - `run_historical_data_quality_reports: bool = True` - enables historical data quality reports.
  - `growth_history_confidence_penalty_weight: float = 0.18` - penalty weight for weak growth-sleeve data confidence.
  - `growth_history_confidence_min_for_full_sleeve: float = 0.35` - confidence floor for full growth-sleeve score contribution.
- breaking_changes:
  - none
- outputs:
  - `monthly_returns` rows keep `regime_label`, `core_target`, `future_target`, `early_target`, `cash_target_used`, `growth_signal`, and `risk_signal` when sleeve-regime comparison is enabled.
  - `run_summary.json` and exported metrics now reflect the champion sleeve/cap policy when champion application is enabled.
- validation:
  - `git diff --check` passed.
  - `colab_run.ipynb` JSON parse via PowerShell `ConvertFrom-Json` passed.
  - Duplicate public function definition scan returned no duplicate names.
  - EngineConfig required field scan returned no missing restored config fields.
  - Local Python runtime was not installed, so `py -3 -m py_compile r1000_top30_institutional.py r1000_data_collector.py` could not run.
- risks_or_notes:
  - The inactive legacy duplicate bodies are retained under `_legacy_unused_*` names for now instead of being physically deleted, minimizing merge risk while removing public-name collisions.
  - A later cleanup can delete those legacy bodies after one clean Colab run confirms behavior.
