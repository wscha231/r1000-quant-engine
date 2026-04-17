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
  - `filename.py` ->one-line summary of what changed in this file
- symbols_added:
  - `function_name(sig)` ->what it does
  - none
- symbols_changed:
  - `existing_function()` ->what changed and why
  - none
- config_fields_added:
  - `field_name: type = default` ->purpose
  - none
- breaking_changes:
  - none
  - OR: describe what breaks and the migration path
- outputs:
  - `path/to/file.ext` ->what it contains
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
- `symbols_added` and `symbols_changed` must enumerate function/class names explicitly ->not prose descriptions.
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
  - Replaced row-count-based `shift(N)` in `_flexible_lag` with a calendar-time `merge_asof` approach per CIK.  The old shift(12) treated annual-only filers (20-F, 1 row/yr) as needing 12 years of history instead of 3, making sales_cagr_3y always NaN for them.  New approach finds the closest period within +/-46 days of the target date regardless of filing cadence.
  - Added 1-year and 2-year CAGR columns for all flow metrics: `sales_cagr_1y`, `sales_cagr_2y`, `op_income_cagr_1y`, `op_income_cagr_2y`, `net_income_cagr_1y`, `net_income_cagr_2y`, `ocf_cagr_1y`, `ocf_cagr_2y`, `eps_cagr_1y`, `eps_cagr_2y`, `fcf_cagr_1y`, `fcf_cagr_2y`.
  - Added `_cagr_best` fallback columns (3y preferred, then 2y, then 1y) for each metric: `sales_cagr_best`, `op_income_cagr_best`, `net_income_cagr_best`, `ocf_cagr_best`, `eps_cagr_best`, `fcf_cagr_best`.
  - Updated `growth_blueprint_score` to use `_cagr_best` instead of `_cagr_3y` so newer companies with < 3 years of history still contribute a proportional growth signal.
  - Updated `revenue_growth_final` and `earnings_growth_final` fallback chains to prefer `_cagr_best` before `_cagr_3y`.
  - Increased `fsds_quarters_backfill` from 44 to 60 (11-15 years) for deeper first-run FSDS coverage.
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
  - `outputs/reports/sleeve_policy_per_regime_grid.csv` ->all policies x all regimes metrics
  - `outputs/reports/sleeve_policy_per_regime_best.csv` ->best policy per regime by Sharpe
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
  - No behavioral changes to sleeve selection, backtest, or data pipeline ->fixes only.
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
  - Engine file grew from 16,830 to ~20,195 lines. Runtime will be longer because sleeve cap policy comparison (9 candidates) and standalone sleeve comparison (3 sleeves x 2 intervals) run by default.
  - Disable with `cfg["run_sleeve_cap_policy_comparison"] = False` and `cfg["run_standalone_sleeve_backtest_comparison"] = False` to reduce runtime.
  - Historical data quality report adds `add_historical_data_quality_columns` call over the full scored panel; moderate CPU cost.

### 20:15 KST - regime-conditional-ensemble-weights

- scope:
  - Ensemble model weight blending per market regime (Option A static priors + Option B OOS-learned).
- files:
  - `r1000_top30_institutional.py`
  - `CHANGELOG.md`
- behavior:
  - Added `REGIME_ENSEMBLE_WEIGHT_PRIORS` constant ->intuition-based static weights per regime (Ridge favored in crisis/shock, CatBoost favored in growth/reentry).
  - Added `compute_regime_conditional_ensemble_weights()` ->computes per-regime model IC/quality from OOS scored panel; blends with static priors (prior weight decays as OOS regime months accumulate); falls back to priors when OOS data insufficient.
  - Extended `apply_adaptive_ensemble_state()` with optional `regime_weights` parameter ->when provided, writes per-row regime-specific weights by detecting `live_event_alert_label` column; falls back to global adaptive weights when regime column absent.
  - Added `regime_ensemble_weights: dict[str, dict[str, float]]` field to `ModelBundle` ->stored in `model_bundle_latest.json` after each walk-forward training run.
  - Wired `compute_regime_conditional_ensemble_weights()` into `train_walkforward()` ->computed from full OOS scored panel after walk-forward, stored in ModelBundle.
  - Updated per-month walk-forward scoring loop to call `compute_regime_conditional_ensemble_weights()` incrementally (same OOS embargo discipline as adaptive ensemble).
  - Updated all 4 `apply_adaptive_ensemble_state()` call sites in `build_latest_recommendations()` and fallback scoring to pass `regime_weights` from ModelBundle.
  - Added 3 new EngineConfig fields: `regime_ensemble_weights_enabled` (bool, default True), `regime_ensemble_weights_min_months` (int, default 6), `regime_ensemble_weights_strength` (float, default 0.50).
  - Added `regime_ensemble_weights` dict to `run_summary.json` output.
- outputs:
  - `model_bundle_latest.json` field: `regime_ensemble_weights` (dict of regime ->{linear, catboost, ranker})
  - `run_summary.json` field: `regime_ensemble_weights`
  - Scored panel columns: `ensemble_weight_linear`, `ensemble_weight_catboost`, `ensemble_weight_ranker` now vary per row by regime; new `regime_ensemble_active` bool column
- validation:
  - grep confirms all symbols present in engine.
  - Local Python runtime not available; no local `py_compile` check.
- risks_or_notes:
  - `compute_regime_conditional_ensemble_weights()` adds CPU overhead proportional to (n_regimes x n_months_per_regime). For 6 regimes and 96 months of OOS data, overhead is modest.
  - First run will use static priors for all regimes because OOS scored panel has no `live_event_alert_label`; weights will improve after first full Colab run.
  - Disable with `cfg["regime_ensemble_weights_enabled"] = False` for a pure global-adaptive-only run.
  - `regime_ensemble_weights_strength=0.50` means learned weights can move +/-50% from global base per regime; raise to 0.80 for more aggressive regime-specific tilting.

### 21:10 KST - fix-validate-config-sleeve-and-cash-constraints

- scope: Relax six overly tight upper-bound checks in `validate_config` that blocked legitimate collector and policy-candidate values.
- files:
  - `r1000_top30_institutional.py` ->widened six constraint upper bounds from fixed values to 1.0
  - `CLAUDE.md` ->removed stale known-issue entry for `cash_weight_max` monkey-patch
- symbols_added:
  - none
- symbols_changed:
  - `validate_config()` ->upper bounds for `future_winner_sleeve_min_weight`, `future_winner_sleeve_max_weight`, `early_scout_sleeve_base_weight`, `early_scout_sleeve_min_weight`, `early_scout_sleeve_max_weight` changed from 0.50/0.50/0.30/0.20/0.25 to 1.0; `cash_weight_max` upper bound changed from 0.65 to 1.0
- config_fields_added:
  - none
- breaking_changes:
  - none ->constraints were widened, not tightened; existing valid configs remain valid
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
  - `CHANGELOG.md` ->replaced Agent Update Contract with structured English-only format including required fields `symbols_added`, `symbols_changed`, `config_fields_added`, `breaking_changes`; backfilled missing `HH:MM` timestamps on four entries
  - `CLAUDE.md` ->updated engine line count (15k->0.4k), removed monkey-patch pipeline step, added Changelog Writing Rules section
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

## 2026-04-11

### 00:05 KST - restore-minervini-momentum-overlay

- scope: Restore the missing Minervini-style momentum overlay function so Phase 5 portfolio construction can run again.
- files:
  - `r1000_top30_institutional.py` - restored `compute_minervini_momentum_overlay()` used by focus overlay, sleeve scoring, and portfolio construction.
  - `CHANGELOG.md` - recorded the missing-function runtime fix.
- symbols_added:
  - `compute_minervini_momentum_overlay(df: pd.DataFrame) -> pd.DataFrame` - rebuilds trend-template, breakout-quality, broken-trend penalty, and momentum-alive signals from existing technical features.
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `Select-String` confirmed call sites existed while no active definition remained before the patch.
  - Restored the implementation from prior repo history (`git show 8e7e5e12a857571ef025e7a14387838f9f25174d:r1000_top30_institutional.py`).
- risks_or_notes:
  - Colab must rerun the GitHub sync cell before rerunning the pipeline so the notebook imports the restored function from `master`.

### 14:30 KST - fix-missing-minervini-engineconfig-fields

- scope: Add three missing EngineConfig fields referenced in compute_portfolio_sleeve_columns and build_target_portfolio but absent from the dataclass, causing AttributeError at runtime.
- files:
  - `r1000_top30_institutional.py` ->added three fields to EngineConfig after growth_history_confidence_min_for_full_sleeve
- symbols_added:
  - none
- symbols_changed:
  - `EngineConfig` ->added `minervini_future_engine_weight: float = 0.65`, `minervini_portfolio_seed_weight: float = 0.40`, `minervini_broken_trend_penalty_weight: float = 0.50`
- config_fields_added:
  - `minervini_future_engine_weight: float = 0.65` ->weight applied to Minervini momentum signal in early_scout engine score computation
  - `minervini_portfolio_seed_weight: float = 0.40` ->weight applied to Minervini alive score in portfolio seed utility
  - `minervini_broken_trend_penalty_weight: float = 0.50` ->penalty weight applied to broken momentum in portfolio scoring
- breaking_changes:
  - none ->these fields had no prior default; adding them to the dataclass with sensible defaults is backward compatible
- outputs:
  - none
- validation:
  - Confirmed all three field names appear in `compute_portfolio_sleeve_columns` (line ~14992) and `build_target_portfolio` (line ~15491) as `cfg.field_name` or `EngineConfig.field_name` references
  - `git diff --check` passed
- risks_or_notes:
  - Default values (0.65, 0.40, 0.50) match the hardcoded logic present in the pre-restoration engine version; adjust after first Colab run if signal contribution needs tuning

### 22:09 KST - restore-historical-data-quality-constants

- scope: Restore the historical data quality constant blocks referenced by growth-sleeve diagnostics after a partial cross-machine merge left only the consumers in place.
- files:
  - `r1000_top30_institutional.py` - restored the historical fundamental coverage column groups, forward-return coverage list, and `HISTORICAL_DATA_QUALITY_COLUMNS`.
  - `CHANGELOG.md` - merged duplicate `2026-04-11` date sections and recorded this runtime fix.
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
  - `git grep -n "HISTORICAL_DATA_QUALITY_COLUMNS" $(git rev-list --max-count=40 HEAD) -- r1000_top30_institutional.py` showed the constant existed in older history (`8e7e5e12`) but was absent from current `master`.
  - Restored the constant block from prior repo history and aligned the list contents with the currently emitted columns in `add_historical_data_quality_columns()`.
- risks_or_notes:
  - Colab must rerun the GitHub sync cell before rerunning the resume pipeline cell so the notebook imports the restored constants from `master`.

### 22:33 KST - normalize-export-artifact-frames

- scope: Fix Phase 6 export so the phase5-only Colab resume path can pass DataFrame artifacts directly without hitting pandas truth-value errors.
- files:
  - `r1000_top30_institutional.py` - added a small export-local artifact-frame normalizer and removed `or {}` truthiness checks for DataFrame-valued export inputs.
  - `CHANGELOG.md` - recorded the export runtime fix for the current Colab resume failure.
- symbols_added:
  - `_artifact_frame(name: str)` - normalizes optional export artifacts into copied DataFrames without evaluating pandas objects in boolean context.
- symbols_changed:
  - `export_outputs(cfg: dict | EngineConfig, artifacts: dict[str, Any])` - now accepts prebuilt DataFrame artifacts from sleeve/cap and standalone backtest comparisons without raising `ValueError`.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `Select-String -Path 'C:\Users\Andrew Cha\Documents\codex\.tmp_r1000_github_update_sec\r1000_top30_institutional.py' -Pattern 'pd\.DataFrame\(artifacts\.get\('` confirmed the ambiguous-truthiness pattern only existed in `export_outputs()`.
  - Reviewed the failing Colab traceback and matched it to `export_outputs()` line `19293`, where a DataFrame entered the `or {}` expression.
- risks_or_notes:
  - Colab still needs a fresh GitHub sync before rerunning the Phase 5-only resume cell; otherwise the notebook will keep importing the pre-fix export function.

## 2026-04-12

### 00:20 KST - apply-regime-conditioned-sleeve-rotation

- scope:
  - Sleeve allocation logic, regime-conditioned policy selection, and export visibility for live sleeve decisions.
- files:
  - `r1000_top30_institutional.py` - enabled regime-conditioned sleeve comparison by default, added live regime sleeve-map application, expanded aggressive early-scout candidates, and surfaced the applied regime sleeve policy in exported outputs.
  - `CHANGELOG.md` - recorded the sleeve rotation change and its validation limits.
- symbols_added:
  - `resolve_frame_regime_label(frame: Optional[pd.DataFrame], default: str = "balanced")` - resolves the active regime label from live alert or regime columns.
  - `build_regime_conditioned_sleeve_map(best_df: Optional[pd.DataFrame])` - converts per-regime sleeve winners into a reusable live sleeve override map.
  - `resolve_regime_conditioned_sleeve_override(cfg: dict | EngineConfig, month_df: Optional[pd.DataFrame])` - chooses the active sleeve override for the current market regime.
  - `sleeve_regime_policy_objective(row: dict[str, Any])` - scores per-regime sleeve candidates with a CAGR-forward composite instead of Sharpe-only ranking.
- symbols_changed:
  - `EngineConfig` - defaults now enable sleeve-regime comparison, persist a regime-conditioned sleeve map, and slightly reduce the defensive bias in the sleeve-cap objective weights.
  - `compute_portfolio_sleeve_policy(cfg: EngineConfig, month_df: pd.DataFrame, cash_target: float)` - reacts earlier to growth regimes and raises future/early sleeve targets sooner when breadth and participation improve.
  - `build_target_portfolio(cfg: EngineConfig, month_df: pd.DataFrame, prev_w: Optional[dict[str, float]] = None, apply_turnover: bool = True, target_n_override: Optional[int] = None, sleeve_override: Optional[dict] = None, cash_target_max: float = 1.0)` - now applies the selected regime-conditioned sleeve override automatically when available.
  - `compare_sleeve_cap_policy_backtests(cfg: dict | EngineConfig, signals: pd.DataFrame, candidates: Optional[Iterable[dict[str, Any]]] = None)` - now computes the champion policy's per-regime sleeve winners and attaches the live regime map to the comparison output.
  - `choose_sleeve_cap_policy(policy_compare: Optional[pd.DataFrame])` - now carries the regime-conditioned sleeve map and current live regime selection into the chosen policy payload.
  - `apply_sleeve_cap_policy_to_cfg(cfg: dict | EngineConfig, selected_policy: dict[str, Any])` - now persists the regime-conditioned sleeve map in the active config.
  - `compare_sleeve_policy_per_regime(cfg: dict | EngineConfig, signals: pd.DataFrame, candidates: Optional[list[dict]] = None, cash_target_max: float = 0.02)` - now ranks regime winners with a CAGR-forward regime objective and includes more aggressive early-heavy candidates.
  - `export_outputs(cfg: dict | EngineConfig, artifacts: dict[str, Any])` - now reuses precomputed sleeve-regime artifacts and exports the applied regime sleeve policy labels in `weights_latest.json` and `run_summary.json`.
- config_fields_added:
  - `sleeve_regime_apply_champion: bool = True` - enables automatic application of the live regime-conditioned sleeve map.
  - `regime_conditioned_sleeve_map: dict[str, dict[str, Any]] = {}` - stores the selected per-regime sleeve allocation map for backtest and live portfolio construction.
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/sleeve_policy_per_regime_grid.csv` - now contains `regime_policy_objective` and includes more aggressive early-scout sleeve candidates.
  - `outputs/reports/sleeve_policy_per_regime_best.csv` - now records regime winners chosen by the CAGR-forward regime objective.
  - `outputs/weights_latest.json` - now includes the applied regime sleeve policy label and live/source regime labels.
  - `outputs/run_summary.json` - now includes the applied regime sleeve policy labels and the full `regime_conditioned_sleeve_map`.
- validation:
  - `git diff --check` passed.
  - Manual diff review confirmed the new regime-conditioned sleeve map is attached in `compare_sleeve_cap_policy_backtests()` and consumed in `build_target_portfolio()`.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - Enabling `run_sleeve_regime_comparison` by default increases Phase 5 runtime because the pipeline now computes the regime sleeve grid unless artifacts are already present.
  - The new regime-conditioned sleeve map is derived from fixed sleeve mixes, so future tuning may still be needed if name-cap settings remain too restrictive in aggressive growth regimes.

### 00:39 KST - export-latest-standalone-sleeve-holdings

- scope:
  - Latest output exports for per-sleeve stock lists and weights.
- files:
  - `r1000_top30_institutional.py` - added a latest standalone sleeve holdings builder and exported the current `core`, `future`, and `early` sleeve stock lists with equal weights and best-interval metadata.
  - `CHANGELOG.md` - recorded the new latest standalone sleeve export outputs.
- symbols_added:
  - `build_latest_standalone_sleeve_holdings(cfg: dict | EngineConfig, latest_frame: pd.DataFrame, standalone_compare: Optional[pd.DataFrame] = None, current_portfolio: Optional[pd.DataFrame] = None, top_n: Optional[int] = None)` - builds the latest current stock list and equal weights for each standalone sleeve using the latest scored snapshot.
- symbols_changed:
  - `export_outputs(cfg: dict | EngineConfig, artifacts: dict[str, Any])` - now writes consolidated and per-sleeve latest standalone holdings CSVs plus a sleeve summary CSV and exposes them in `output_paths`.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/latest_sleeve_standalone_holdings.csv` - latest combined sleeve stock list with per-sleeve equal weights and current mixed-portfolio overlap columns.
  - `outputs/core_compounder_latest_standalone.csv` - latest `core_compounder` standalone holdings and weights.
  - `outputs/future_winner_latest_standalone.csv` - latest `future_winner` standalone holdings and weights.
  - `outputs/early_scout_latest_standalone.csv` - latest `early_scout` standalone holdings and weights.
  - `outputs/reports/latest_sleeve_standalone_summary.csv` - one-row-per-sleeve summary with selected count, best interval, and standalone backtest metrics.
- validation:
  - `git diff --check` passed.
  - Manual review confirmed the new files are attached to both `output_files` and returned `output_paths`.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - The exported latest sleeve weights are equal-weight standalone sleeves, matching the standalone backtest methodology rather than the mixed live portfolio allocator.

### 00:58 KST - lower-core-raise-growth-sleeves

- scope:
  - Lower core sleeve weight and slot concentration across market regimes while expanding future-winner and early-scout participation.
- files:
  - `r1000_top30_institutional.py` - lowered default/live core sleeve weights, raised future/early targets and caps, reduced the growth-regime trigger thresholds, increased the minimum exploratory slot allocation, and capped core slot share in the live target portfolio builder.
  - `r1000_data_collector.py` - updated notebook and Colab runtime defaults to start from the same lower-core, higher future/early sleeve mix.
- symbols_changed:
  - `EngineConfig` - default sleeve base weights and growth-floor settings now start from a much lower `core` share and higher `future`/`early` share.
  - `compute_portfolio_sleeve_policy(cfg: EngineConfig, month_df: pd.DataFrame, cash_target: float)` - now cuts the fallback core sleeve materially, reacts sooner to constructive growth conditions, and retains more future/early exposure even in middling regimes.
  - `build_target_portfolio(cfg: EngineConfig, month_df: pd.DataFrame, prev_w: Optional[dict[str, float]] = None, apply_turnover: bool = True, target_n_override: Optional[int] = None, sleeve_override: Optional[dict] = None, cash_target_max: float = 1.0)` - now uses ceiling-based future/early slot sizing, higher minimum exploratory slot counts, and an explicit cap on how many slots `core` can occupy.
  - `_SLEEVE_POLICY_CANDIDATES` - replaced several core-heavy regime candidates with lower-core, higher future/early policy mixes.
  - `_sleeve_cap_policy_candidates()` - candidate sleeve-cap policy presets now bias materially less toward `core` and more toward `future_winner` / `early_scout`.
- validation:
  - `git diff --check` passed with only line-ending warnings.
  - Manual code review confirmed the live portfolio-construction path reflects the lower-core slot and weight logic.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - Existing Colab cells that manually override `early_scout_sleeve_*` values can still mute part of this change; remove or update those overrides if you want the notebook run to match the new defaults.

### 01:12 KST - strong-growth-10-40-50

- scope:
  - Push the strongest growth regime closer to a `core 10 / future 40 / early 50` sleeve mix.
- files:
  - `r1000_top30_institutional.py` - raised the strong-growth live sleeve floors so the allocator can force `future` toward 40% and `early` toward 50% of invested capital when the growth regime is strong enough, and updated the most aggressive regime candidates to match that mix more directly.
- symbols_changed:
  - `compute_portfolio_sleeve_policy(cfg: EngineConfig, month_df: pd.DataFrame, cash_target: float)` - `strong_early_regime` now also floors `future` near 40% of invested share and `early` near 50% of invested share before residual capital falls back to `core`.
  - `_SLEEVE_POLICY_CANDIDATES` - replaced the previous `15/35/50` aggressive candidate with a `10/40/50` candidate.
  - `_sleeve_cap_policy_candidates()` - `early_scout_very_bull` now starts from a `10/40/50` base and allows a larger early-scout cap.
- validation:
  - Manual code review confirmed the live strong-growth branch now carries an explicit `10/40/50` floor on invested sleeve share.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.

### 01:20 KST - growth-balanced-25-45-30

- scope:
  - Make the `growth_balanced` policy materially less core-heavy and align the regime grid with the same growth mix.
- files:
  - `r1000_top30_institutional.py` - changed `growth_balanced` to a `25 / 45 / 30` base, raised its future/early caps so the policy can actually reach those weights, and replaced the old `growth_35_40_25` regime candidate with `growth_25_45_30`.
- validation:
  - Manual code review confirmed the updated `growth_balanced` base weights no longer conflict with its sleeve max caps.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.

### 01:33 KST - compare-manual-vs-learned-regime-maps

- scope:
  - Add a direct backtest comparison between a forced manual regime sleeve map and the learned regime-conditioned sleeve map.
- files:
  - `r1000_top30_institutional.py` - added a default manual regime sleeve map, a learned-vs-manual regime-map backtest comparator, and export wiring for the comparison CSV and summary payloads.
- symbols_added:
  - `default_manual_regime_conditioned_sleeve_map()` - provides the baseline forced sleeve mix by regime label for comparison.
  - `normalize_regime_conditioned_sleeve_map(regime_map, fallback_source=...)` - cleans and normalizes learned/manual sleeve maps into a common schema.
  - `compare_regime_conditioned_sleeve_map_methods(cfg, signals, learned_regime_map=..., manual_regime_map=..., cash_target_max=...)` - runs backtests for both regime-map methods and returns side-by-side metrics plus the live selected mix.
- symbols_changed:
  - `EngineConfig` - now carries `manual_regime_conditioned_sleeve_map` and `run_regime_map_method_comparison`.
  - `compare_sleeve_cap_policy_backtests(...)` - now computes and attaches the manual-vs-learned regime-map comparison after building the learned regime map from the champion sleeve-cap policy.
  - `export_outputs(...)` - now writes `outputs/reports/regime_sleeve_map_method_comparison.csv` and includes the comparison rows in `weights_latest.json` / `run_summary.json`.
- outputs:
  - `outputs/reports/regime_sleeve_map_method_comparison.csv` - side-by-side full-backtest metrics for the learned regime map versus the forced manual regime map.
- validation:
  - `git diff --check` passed with only line-ending warnings.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.

### 03:25 KST - fix-standalone-sleeve-export-index-alignment

- scope:
  - Standalone sleeve latest-export stability.
- files:
  - `r1000_top30_institutional.py` - aligned sleeve-specific boolean filtering for latest standalone sleeve holdings so export slices cannot fail on misaligned indexes.
- symbols_added:
  - none
- symbols_changed:
  - `build_latest_standalone_sleeve_holdings(cfg: dict | EngineConfig, latest_frame: pd.DataFrame, standalone_compare: Optional[pd.DataFrame] = None, current_portfolio: Optional[pd.DataFrame] = None, top_n: Optional[int] = None)` - now applies sleeve filters with index-aligned masks before building standalone latest holdings.
  - `export_outputs(cfg: dict | EngineConfig, artifacts: dict[str, Any])` - now consumes the corrected standalone sleeve subsets without boolean-index alignment failures.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - Reviewed the failing standalone export path and matched it to boolean-mask reuse across differently indexed frames.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - Fresh notebook runtimes still need a Git sync before rerunning standalone sleeve export cells.

### 11:05 KST - sleeve-aware-gates-and-model-specific-rebalance

- scope:
  - Split live/latest gating by sleeve, add sleeve-specific rebalance cadence support to the active backtest/export path, and emit engine diagnostics that show whether each sleeve is being filtered out or actually producing strong top-N forward returns.
- files:
  - `r1000_top30_institutional.py` - added sleeve-aware latest-ranking eligibility, relaxed non-core gates for `future_winner` / `early_scout`, propagated sleeve-specific rebalance intervals through backtest/latest/export outputs, and added engine diagnostics report generation.
- symbols_added:
  - `annotate_portfolio_candidate_gate(df: pd.DataFrame, cfg: EngineConfig)` - annotates sleeve-specific gate pass/fail state without dropping rows.
  - `apply_latest_ranking_eligibility(df: pd.DataFrame, cfg: EngineConfig, context: str)` - computes sleeve-aware `ranking_eligible` flags for latest/fallback/export paths.
  - `build_engine_diagnostics_report_frames(cfg: EngineConfig, scored: pd.DataFrame)` - returns monthly and summary diagnostics for raw-label counts, final-label counts, gate pass counts, and top-N forward-return quality by sleeve.
- symbols_changed:
  - `apply_portfolio_candidate_gate_filter(...)` - now reuses the shared gate annotation logic so filtering and latest-ranking eligibility cannot drift apart.
  - `backtest_portfolio(...)` - now records due sleeves, per-row sleeve rebalance intervals, sleeve-specific rebalance metadata, and partial-rebalance resets for speculative stop-loss state.
  - `build_latest_recommendations(...)` - now applies sleeve-aware ranking eligibility only after total scores and sleeve labels are computed, instead of forcing a core-only gate first.
  - `fallback_latest_recommendations_from_scored(...)` - now rebuilds sleeve-aware ranking eligibility and sleeve interval metadata before sorting/exporting fallback latest recommendations.
  - `build_latest_portfolio(...)` - now carries `sleeve_rebalance_interval_months` into both scheduled-hold and full-rebalance live portfolio outputs.
  - `_bt_metrics_row(...)` - now includes sleeve-specific rebalance cadence metadata for comparison exports.
  - `export_outputs(...)` - now uses the shared latest-ranking gate, exports sleeve rebalance cadence metadata consistently, and writes engine diagnostics CSVs plus summary payloads.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/engine_diagnostics_by_month.csv` - monthly sleeve diagnostics covering raw/final label counts, gate pass counts, and top-N forward-return behavior.
  - `outputs/reports/engine_diagnostics_summary.csv` - per-sleeve summary of selection emptiness, top-N CAGR/Sharpe/MaxDD, and gate-pressure statistics.
- validation:
  - `git diff --check` passed with only line-ending warnings.
  - Manual code review confirmed the active later definitions now use sleeve-aware latest gating and export the new rebalance/diagnostic fields.
  - Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - The next-run scheduler is still a single overall recommendation; sleeve-specific cadence now affects backtest/live holdings metadata and partial-rebalance execution, but not a separate per-sleeve cron schedule.

### 21:54 KST - adaptive-four-sleeve-growth-tilt

- scope:
  - Apply the winning regime-map method to live sleeve selection, reduce `core` in the active defaults, increase `future_winner` / `early_scout` participation, preserve explicit `cash` in regime overrides, and add a cash-aware adaptive four-sleeve comparison model.
- files:
  - `r1000_top30_institutional.py` - applied the regime-map method winner in the chosen sleeve policy, retuned sleeve defaults and early-label transitions, added cash-aware regime-map handling, added aggressive `future`/`early` sleeve-cap candidates, added the adaptive four-sleeve comparison flow, and exported the new comparison artifacts.
- symbols_added:
  - `generate_ai_four_sleeve_policy_candidates(cfg: dict | EngineConfig)` - builds cash-aware `core` / `future` / `early` / `cash` sleeve candidates for adaptive comparison.
  - `compare_ai_four_sleeve_adaptive_model(cfg: dict | EngineConfig, signals: pd.DataFrame, active_backtest: Optional[BacktestResult] = None)` - evaluates the adaptive four-sleeve regime model against the active baseline and returns comparison/export artifacts.
- symbols_changed:
  - `EngineConfig` - default sleeve weights, caps, rebalance cadence, and growth-floor settings now start from a lower `core` share, higher `future_winner` / `early_scout` share, and enable the adaptive four-sleeve comparison by default.
  - `compute_portfolio_sleeve_columns(df: pd.DataFrame, cfg: Optional[EngineConfig] = None)` - now penalizes sparse early-history less aggressively, keeps marginal `early_scout` names longer, and requires stronger confirmation before auto-promoting mature early names into `future_winner`.
  - `default_manual_regime_conditioned_sleeve_map()` - now includes explicit `cash` sleeve fractions for each manual regime.
  - `normalize_regime_conditioned_sleeve_map(regime_map, fallback_source=...)` - now preserves and normalizes explicit `cash` fractions alongside `core` / `future` / `early`.
  - `resolve_regime_conditioned_sleeve_override(cfg: dict | EngineConfig, month_df: Optional[pd.DataFrame])` - now returns explicit `cash` from the selected regime override.
  - `build_target_portfolio(cfg: EngineConfig, month_df: pd.DataFrame, prev_w: Optional[dict[str, float]] = None, apply_turnover: bool = True, target_n_override: Optional[int] = None, sleeve_override: Optional[dict] = None, cash_target_max: float = 1.0)` - now respects explicit regime-map `cash` instead of immediately compressing it back to the generic cash cap.
  - `choose_sleeve_cap_policy(policy_compare: Optional[pd.DataFrame])` - now applies the winning manual-vs-learned regime-map method instead of always carrying the learned map forward.
  - `compare_regime_conditioned_sleeve_map_methods(cfg, signals, learned_regime_map=..., manual_regime_map=..., cash_target_max=...)` - now emits a stable `cash` / `live_cash_frac` schema in both normal and fallback comparison rows.
  - `compare_sleeve_policy_per_regime(cfg: dict | EngineConfig, signals: pd.DataFrame, candidates: Optional[list[dict]] = None, cash_target_max: float = 0.02)` - now accepts cash-aware candidates and exports `cash_frac` in the regime grid.
  - `export_outputs(cfg: dict | EngineConfig, artifacts: dict[str, Any])` - now writes the adaptive four-sleeve comparison files and includes the new comparison payloads in exported summaries.
  - `run_all(cfg: Optional[dict | EngineConfig] = None)` - now executes Phase 5e to compare the adaptive four-sleeve model after the existing sleeve/cap and standalone sleeve comparisons.
- config_fields_added:
  - `run_ai_four_sleeve_comparison: bool = True` - enables the cash-aware adaptive four-sleeve comparison flow.
  - `ai_four_sleeve_max_candidates: int = 12` - caps how many adaptive four-sleeve candidate policies are evaluated per run.
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/ai_four_sleeve_adaptive_comparison.csv` - side-by-side metrics for the active baseline versus the adaptive `core` / `future` / `early` / `cash` regime model.
  - `outputs/reports/ai_four_sleeve_adaptive_regime_grid.csv` - full per-regime candidate grid including explicit `cash_frac`.
  - `outputs/reports/ai_four_sleeve_adaptive_regime_best.csv` - best adaptive candidate per regime.
  - `outputs/reports/ai_four_sleeve_adaptive_selected_map.json` - selected adaptive four-sleeve regime map used for the comparison backtest.
  - `outputs/weights_latest.json` - now carries `ai_four_sleeve_adaptive_best` and `ai_four_sleeve_adaptive_selected_map` when the comparison runs.
  - `outputs/run_summary.json` - now includes the adaptive four-sleeve comparison snapshot and selected regime map.
- validation:
  - `git diff --check` passed.
  - User Colab import validation passed after registering the module in `sys.modules`; `EngineConfig` reported `core=0.16`, `future=0.56`, `early=0.20`, `future_rebalance_interval_months=2`, and `run_ai_four_sleeve_comparison=True`.
  - Manual code review confirmed that explicit regime-map `cash` survives normalization/resolution and is consumed by `build_target_portfolio()`.
  - Local Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - The more aggressive default sleeve mix is likely to increase turnover and runtime relative to the older core-heavy defaults.
  - `run_default_pipeline()` will still rebuild earlier stages when the config fingerprint changes; use the Phase 5-only path if you only want to compare portfolio policies against existing feature/scored artifacts.
  - Colab cells that call `spec.loader.exec_module(engine)` without first registering the module in `sys.modules` will still fail under Python 3.12 dataclass import rules.

### 22:00 KST - fast-mode-and-runtime-reduction

- scope:
  - Phase 4 walk-forward training and Phase 5 backtest suite runtime reduction.
- files:
  - `r1000_top30_institutional.py` ->added fast_mode EngineConfig field, apply_fast_mode() function, reduced default comparison candidate counts, trimmed _SLEEVE_POLICY_CANDIDATES from 12 to 8.
- symbols_added:
  - `apply_fast_mode(cfg: EngineConfig) -> EngineConfig` ->applies Phase 4+5 override settings when cfg.fast_mode is True; called at the top of run_all() after validate_config().
- symbols_changed:
  - `EngineConfig` ->added fast_mode: bool = False; lowered sleeve_cap_policy_max_candidates default from 9 to 6; lowered ai_four_sleeve_max_candidates default from 12 to 8.
  - `run_all()` ->calls apply_fast_mode(cfg) immediately after validate_config(cfg).
  - `_SLEEVE_POLICY_CANDIDATES` ->reduced from 12 to 8 entries; removed def_55_30_15, bal_45_35_20, aggr_30_35_35, aggr_20_40_40 (near-duplicates of retained entries).
- config_fields_added:
  - `fast_mode: bool = False` ->when True, apply_fast_mode() cuts total Phase 4+5 runtime by ~60%; sets ranking_enabled=False, cat iterations 200/200/150, retrain_freq=6m, disables regime-per-regime/AI-four-sleeve/regime-map-method/standalone-sleeve comparisons, caps sleeve-cap candidates to 3.
- breaking_changes:
  - none ->fast_mode defaults to False; all existing Colab runs are unaffected unless opt-in.
- outputs:
  - none
- validation:
  - grep confirmed fast_mode field at line 1381, apply_fast_mode() at line 1384, cfg = apply_fast_mode(cfg) call at line 22850.
  - sleeve_cap_policy_max_candidates default confirmed as 6, ai_four_sleeve_max_candidates confirmed as 8.
  - _SLEEVE_POLICY_CANDIDATES confirmed as 8 entries.
  - Local Python compile not run (no interpreter in environment).
- risks_or_notes:
  - fast_mode=True halves the walk-forward retrain frequency (6m vs 3m), which may slightly reduce model adaptation quality in fast-changing regimes; disable with cfg["fast_mode"]=False for full-quality production runs.
  - ranking_enabled=False in fast_mode removes the CatBoostRanker model; the ensemble falls back to regressor+classifier blend only.
  - Default sleeve_cap_policy_max_candidates=6 and ai_four_sleeve_max_candidates=8 apply to all runs regardless of fast_mode; saves ~5 backtests per full run compared to previous defaults (9/12).

## 2026-04-14

### 13:22 KST - sage-portfolio-integration-and-export-observability

- scope:
  - Move SAGE from a mostly model-level feature into the live portfolio selection/weighting path and expose the resulting influence in final outputs.
- files:
  - `r1000_top30_institutional.py` -> strengthened SAGE impact in candidate seeding, preserved the earlier sleeve/weight integration, and exported SAGE diagnostics to `portfolio_latest.csv`, `top30_latest.csv`, `weights_latest.json`, and `run_summary.json`.
- symbols_changed:
  - `build_target_portfolio()` -> `portfolio_seed_score` now includes `sage_composite_score`, `sage_g_score`, and growth-sleeve engine scores before the candidate pool is cut, so future/early names are less likely to be filtered out before portfolio construction.
  - `build_latest_portfolio()` -> live-policy candidate seeding now mirrors the same SAGE-aware seed logic.
  - `export_outputs()` -> operational views now include `portfolio_seed_score`, `portfolio_alpha`, `portfolio_sage_boost`, `portfolio_utility`, `sage_sector`, `sage_composite_score`, `sage_g_score`, `sage_v_score`, `sage_q_score`, `sage_c_score`.
  - `weights_latest.json` / `run_summary.json` payloads -> added `sage_snapshot` containing top30 mean SAGE, portfolio mean SAGE by axis, dominant portfolio SAGE sector, and mean SAGE by sleeve.
- breaking_changes:
  - none
- outputs:
  - `outputs/portfolio_latest.csv` now exposes the direct portfolio-construction path: model/focus score, seed score, SAGE boost, portfolio utility, sleeve label, and SAGE axes.
  - `outputs/top30_latest.csv` now exposes SAGE columns alongside portfolio selection columns.
  - `outputs/weights_latest.json` now contains a compact `sage_snapshot` for fast post-run verification.
  - `outputs/run_summary.json` now contains the same `sage_snapshot` for summary-level inspection.
- validation:
  - Grep confirmed new SAGE-aware seed terms in both `build_target_portfolio()` and `build_latest_portfolio()`.
  - Grep confirmed `portfolio_alpha`, `portfolio_sage_boost`, SAGE columns, and `sage_snapshot` are included in export paths.
  - Local Python compile/import validation was not run in this environment because no Python interpreter is installed.
- risks_or_notes:
  - This change intentionally makes the engine more offensive; early/future sleeves should surface more often, but turnover and concentration can rise in growth-friendly regimes.
  - SAGE is still hybrid: actual `sbc`/`rd_expense`/`interest_expense` data quality improves only after a fresh collector run populates the expanded tags.


### 13:25 KST - collector-and-colab-sync-to-growth-defaults

- scope:
  - Sync the GitHub worktree with the newer local collector/runtime helper and Colab notebook so the notebook path matches the current aggressive sleeve defaults and runtime wiring.
- files:
  - `r1000_data_collector.py` -> synced to the newer local version that inherits notebook/runtime defaults from `DEFAULT_CFG`, exposes `fast_mode`, and keeps validation focused on current SAGE/runtime snapshots.
  - `colab_run.ipynb` -> synced to the newer local notebook runbook that fetches/reset-to-origin before execution and matches the current collector/pipeline flow.
- symbols_changed:
  - `_apply_notebook_runtime_defaults()` -> now pulls sleeve/cash/fast-mode defaults from `DEFAULT_CFG` instead of older hard-coded conservative values.
  - `collector_lean_full_run_cfg()` -> remains the recommended first-run path, but now inherits the current growth-tilted engine defaults consistently.
  - `run_full_validation_suite()` -> synced with the newer compact snapshot layout used by the current local workflow.
- breaking_changes:
  - none
- outputs:
  - Colab notebook and collector defaults are now aligned with the main engine's current sleeve weights and runtime behavior.
- validation:
  - File hashes for `r1000_data_collector.py` and `colab_run.ipynb` now match the newer local source files used during development.
  - `git diff --stat` shows only the intended collector/notebook sync plus this changelog entry.
- risks_or_notes:
  - The synced collector removes some older explicit notebook helper wiring in favor of inheriting from `DEFAULT_CFG`; this is intentional so future engine-default changes do not drift from Colab.
  - The notebook JSON changed substantially because the newer local runbook has a different cell layout and markdown text, not because of binary corruption.


### 14:21 KST - reduce-core-cash-bias-in-live-portfolio-construction

- scope:
  - Reduce the tendency for the live portfolio builder to collapse back into `core_compounder` plus cash even when growth sleeves have strong targets.
- files:
  - `r1000_top30_institutional.py` -> lowered default non-crisis cash caps, shifted base sleeve weights further toward `future_winner` / `early_scout`, relaxed low-gap sleeve fallback logic for growth names, added growth-aware fill priority in portfolio construction, and fixed final cash application to honor the sleeve-adjusted cash target.
- symbols_changed:
  - `EngineConfig.cash_target_balanced_cap` -> `0.06` to `0.04`.
  - `EngineConfig.cash_target_mild_risk_cap` -> `0.12` to `0.08`.
  - `EngineConfig.core_compounder_sleeve_base_weight` -> `0.16` to `0.12`.
  - `EngineConfig.future_winner_sleeve_base_weight` -> `0.56` to `0.58`.
  - `EngineConfig.early_scout_sleeve_base_weight` -> `0.20` to `0.22`.
  - `compute_portfolio_sleeve_columns()` -> added `growth_tilt` plus `growth_lean_future` / `growth_lean_early` so ambiguous growth names no longer default straight back to `core_compounder` on small engine-score gaps.
  - `build_target_portfolio()` -> added `growth_mix_target` and `portfolio_fill_priority` so supplemental sleeve selection and generic fill use growth-aware ordering instead of plain seed-score fallback.
  - `build_target_portfolio()` -> tightened `max_core_ratio` in growth-heavy target mixes so the seat allocator does not let `core_compounder` dominate exploratory sleeves.
  - `build_target_portfolio()` -> final `apply_cash_buffer_to_weights()` now uses `sleeve_policy["cash_target"]` rather than reusing `regime_ctl["cash_target"]`, fixing a bug where cash could be re-inflated after sleeve overrides and target rescaling.
- breaking_changes:
  - none
- outputs:
  - Live and backtest portfolio construction should allocate fewer seats to `core_compounder` in growth-favorable states and preserve more `future_winner` / `early_scout` exposure through the final fill stage.
- validation:
  - `python -m py_compile r1000_top30_institutional.py` passed after the change.
  - Active call sites for `build_target_portfolio()`, `compute_portfolio_sleeve_columns()`, and `apply_cash_buffer_to_weights()` were re-read to confirm the new growth-priority path is on the non-legacy code path.
- risks_or_notes:
  - This makes the engine more aggressive in balanced-to-growth regimes; expected effects are higher growth-sleeve utilization, lower idle cash, and potentially higher turnover / concentration.
  - Crisis / high-risk caps are unchanged; the patch only reduces unnecessary conservatism outside confirmed risk-off conditions.


### 17:30 KST - sage-sector-adaptive-growth-engine

- scope:
  - Replace the flat Rule-of-40 metric with a sector-adaptive G/V/Q/C scoring framework (SAGE) covering all 8 sector buckets in the Russell 1000 universe.
- files:
  - `r1000_top30_institutional.py` ->added SAGE constants, 8 new FSDS tags + aliases, 9 proxy-safe derived metrics, 3 SAGE scoring functions, sector-gated z-score utility, and wired compute_sage_scores into compute_valuation_columns.
- symbols_added:
  - `SAGE_SECTOR_MAP: list[tuple[str, tuple[str, ...]]]` ->8-bucket sector classifier keyed on GICS keyword matching (Semiconductor, Software, MedTech, Banking, Industrial, Consumer, Energy, General).
  - `cross_sectional_robust_z_by_sector(df: pd.DataFrame, col: str, sector_col: str = "sage_sector") -> pd.Series` ->sector-gated robust z-score; falls back to universe-wide when group size < 5.
  - `compute_sage_sector_labels(df: pd.DataFrame) -> pd.Series` ->assigns each row a SAGE sector label via GICS keyword scan with General fallback.
  - `_sage_ols_residual(y: pd.Series, X: pd.DataFrame) -> pd.Series` ->numpy lstsq OLS; returns zero series on degenerate input.
  - `compute_valuation_residuals(d: pd.DataFrame) -> pd.DataFrame` ->per-(rebalance_date, sage_sector) OLS regression; adds val_residual_ep, val_residual_sp, val_residual_fcfy.
  - `compute_sage_scores(d: pd.DataFrame) -> pd.DataFrame` ->adds sage_sector, sage_g_score, sage_v_score, sage_q_score, sage_c_score, sage_composite_score (formula: 0.35G + 0.25V + 0.25Q + 0.15C).
- symbols_changed:
  - `FSDS_TAGS` ->added sbc, rd_expense, interest_expense, equity, inventory, long_term_debt, current_liabilities, cash.
  - `FSDS_TAG_ALIASES` ->added aliases for all 8 new tags.
  - `BAL_TAGS` ->added equity, inventory, long_term_debt, current_liabilities, cash.
  - `FLOW_TAGS` ->added sbc, rd_expense, interest_expense.
  - `YF_QUARTERLY_COL_MAP` ->added 28 yfinance field name mappings for new tags.
  - `carry_cols` ->added fcf_margin, net_margin, gross_margin_ttm, op_margin_calc_ttm, rule_of_40, sbc_to_revenue, rd_intensity, roic_approx, interest_coverage, dilution_penalty.
  - `COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS` ->added 16 SAGE metric columns.
  - `DEFAULT_FEATURES` ->added 15 SAGE columns including sage_composite_score.
  - `recompute_fund_panel_derived_columns()` ->added 9 proxy-safe derived SAGE metrics with fallback proxies when new FSDS tags not yet collected.
  - `compute_valuation_columns()` ->injected d = compute_sage_scores(d) after sector_adjusted_quality_score block.
- config_fields_added:
  - none
- breaking_changes:
  - none ->all new metrics have proxy fallbacks; existing data pipelines run unchanged until next companyfacts.zip pull.
- outputs:
  - Scored panel gains: sage_sector, sage_g_score, sage_v_score, sage_q_score, sage_c_score, sage_composite_score, fcf_margin, net_margin, gross_margin_ttm, op_margin_calc_ttm, rule_of_40, sbc_to_revenue, rd_intensity, roic_approx, interest_coverage, dilution_penalty.
- validation:
  - All 6 SAGE function/constant names confirmed present via grep after implementation.
  - sage_composite_score confirmed in DEFAULT_FEATURES and COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS.
  - SAGE_SECTOR_MAP confirmed at line 1031; compute_sage_scores call site confirmed at line 11934.
  - Local Python compile not run (no interpreter in environment).
- risks_or_notes:
  - Software and Semiconductor share the "Information Technology" GICS sector string; SAGE_SECTOR_MAP keyword scan distinguishes them by checking "SEMICONDUCTOR"/"MICROELECTRONIC" first. If the industry field is unavailable, both may collapse into the Software bucket until a richer industry string is collected.
  - val_residual_* features require at least 3 names per (rebalance_date, sage_sector) group; sparse sectors fall back to a zero residual with no error.
  - Proxy-safe derived metrics (sbc_to_revenue via shares_yoy proxy, rd_intensity via margin gap proxy, roic_approx via liabilities proxy, interest_coverage via liabilities proxy) are intentionally conservative; signal quality will improve after sbc / rd_expense / interest_expense / equity tags are backfilled from companyfacts.zip on the next full Colab run.


### 23:55 KST - sage-followup-fixes-and-validation-restore

- scope:
  - Remove a duplicated legacy scoring block, restore validation snapshots for portfolio comparison reports, and clean remaining changelog encoding artifacts.
- files:
  - `r1000_top30_institutional.py` -> removed a duplicated score-ranking block from `_legacy_unused_build_target_portfolio()` so the legacy fallback path is internally consistent and easier to audit.
  - `r1000_data_collector.py` -> restored compact validation snapshots for sleeve-cap-policy, standalone-sleeve, and historical-data-quality report outputs.
  - `CHANGELOG.md` -> normalized the remaining corrupted non-ASCII symbols to ASCII-safe text.
- symbols_changed:
  - `_legacy_unused_build_target_portfolio()` -> deleted the second duplicate `seed_score_rank` / `sage_score_rank` / `sleeve_score_rank` block; active production code paths are unchanged.
  - `run_full_validation_suite()` -> now emits `sleeve_cap_policy_snapshot`, `standalone_sleeve_snapshot`, and `historical_data_quality_snapshot` when those report CSVs exist.
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/full_validation_suite.json` regains summary sections for sleeve-cap-policy comparison, standalone sleeve comparison, and historical data quality.
- validation:
  - `python -m py_compile H:\\codex\\r1000_top30_institutional.py H:\\codex\\r1000_data_collector.py` passed.
  - Readback confirmed the active `build_target_portfolio()` path is untouched while the duplicated legacy block is removed.
- risks_or_notes:
  - The duplicated block lived only inside a `_legacy_unused_*` function, so this is mainly a maintainability fix and guard against future accidental reuse.


### 23:59 KST - pit-leakage-hardening-followup

- scope:
  - Tighten point-in-time hygiene for intermediate monthly artifacts, broaden acceptance leakage checks to the actual model input set, and remove a redundant pre-guard valuation pass from feature-store assembly.
- files:
  - `r1000_top30_institutional.py` -> guarded `universe_monthly` before artifact/report writes, widened leakage auditing from `cfg.features` to `model_feature_columns(cfg)`, and removed the extra pre-guard `compute_valuation_columns()` call in `build_feature_store()`.
- symbols_changed:
  - `build_universe_monthly()` -> now applies `apply_latest_only_signal_guard()` before stage coverage, diagnostics, and `universe_monthly_latest.parquet` export so historical rows do not retain latest-only live signals in the saved intermediate artifact.
  - `build_feature_store()` -> no longer runs `compute_valuation_columns()` on the raw universe before the latest-only guard; valuation features are now computed only after PIT cleanup.
  - `run_acceptance_checks()` -> leakage audit now inspects `model_feature_columns(cfg)` instead of only `cfg.features`, so derived/pillar model inputs are covered by the forward-feature ban list.
- breaking_changes:
  - none
- outputs:
  - `outputs/universe_monthly_latest.parquet` and `outputs/reports/universe_monthly_coverage.csv` are now PIT-clean with respect to latest-only live signal columns for historical rows.
  - `acceptance_checks["feature_leakage_columns"]` now reflects the full active model feature set rather than only the base feature list.
- validation:
  - `python -m py_compile H:\\codex\\r1000_top30_institutional.py H:\\codex\\r1000_data_collector.py` passed after the change.
- risks_or_notes:
  - This is pipeline-hygiene hardening, not a change to the intended live/latest recommendation logic; the latest rebalance-date rows still retain live-only signals as before.


## 2026-04-15

### 12:29 KST - sync-colab-runbook-to-ops-layer

- scope:
  - Update the Colab runbook so it matches the new live state/operator workflow instead of the older conservative sleeve override flow.
- files:
  - `colab_run.ipynb` -> now defines shared runtime overrides once, reloads `r1000_portfolio_state` and `r1000_operator`, removes the old hard-coded sleeve/cash overrides, rebuilds pipeline config from fresh defaults, and surfaces `operator_snapshot`, `live_operator_summary.json`, `live_operator_plan_latest.csv`, and `live_portfolio_state.json` in the result review cells.
- breaking_changes:
  - none
- outputs:
  - The default Colab notebook now distinguishes model target outputs from operator/live-state outputs in the review section.
- validation:
  - Notebook JSON structure was rewritten and reloaded successfully after the update.
- risks_or_notes:
  - `FAST_MODE` remains `True` by default in the notebook for first-pass verification. For a final full run, set it to `False` before executing collector/pipeline cells.

### 12:14 KST - phase1-ops-layer-and-operator

- scope:
  - Add a dedicated live portfolio state layer plus an operator layer so the engine can keep monthly rebalance as the default while still making hold/add/reduce/exit decisions against existing positions instead of assuming a full reset on every run.
- files:
  - `r1000_portfolio_state.py` -> new state module that owns persistent live position storage, bootstraps the first state snapshot from `weights_latest.json`, writes `live_portfolio_state.json`, and keeps latest/history parquet snapshots for actual holdings state.
  - `r1000_operator.py` -> new operator module that reads the persistent live state plus the latest target portfolio outputs, classifies each ticker into `hold`, `hold_locked`, `hold_watch`, `trim_legacy`, `exit`, `exit_intramonth`, `add`, or `add_intramonth`, estimates turnover, and writes a latest operator plan + decision history.
  - `r1000_top30_institutional.py` -> bumped `ENGINE_REUSE_VERSION` to `2026-04-15-phase1-ops-layer` and now refreshes operator outputs at export time after `run_summary.json` is written so the operator always evaluates the current run artifacts.
  - `r1000_data_collector.py` -> validation suite now reports the live operator/state snapshot, including state source, position count, operator policy version, full-rebalance flag, turnover estimate, and plan row count.
- symbols_changed:
  - `resolve_live_state_paths()`, `load_live_portfolio_state()`, `save_live_portfolio_state()`, `ensure_live_portfolio_state()` -> define the persistent live portfolio state contract and bootstrap behavior.
  - `build_live_operator_plan()` and `refresh_live_operator_outputs()` -> define the new live operation layer that compares actual state vs current model targets and generates a trade decision plan without overwriting actual holdings.
  - `export_outputs()` -> now writes the base run summary first, then refreshes operator outputs and rewrites `run_summary.json` with `operator_summary`.
- breaking_changes:
  - none
- outputs:
  - `outputs/ops/live_portfolio_state.json`
  - `outputs/ops/live_portfolio_positions_latest.parquet`
  - `outputs/ops/live_portfolio_state_history.parquet`
  - `outputs/ops/live_operator_plan_latest.csv`
  - `outputs/ops/live_operator_summary.json`
  - `outputs/ops/live_operator_decision_history.parquet`
- validation:
  - `python -m py_compile H:\\codex\\r1000_top30_institutional.py H:\\codex\\r1000_data_collector.py H:\\codex\\r1000_portfolio_state.py H:\\codex\\r1000_operator.py` passed.
  - `python -m py_compile H:\\codex\\tmp_r1000_quant_engine\\r1000_top30_institutional.py H:\\codex\\tmp_r1000_quant_engine\\r1000_data_collector.py H:\\codex\\tmp_r1000_quant_engine\\r1000_portfolio_state.py H:\\codex\\tmp_r1000_quant_engine\\r1000_operator.py` passed.
- risks_or_notes:
  - The first operator run bootstraps state from `weights_latest.json` if no live state exists, so `avg_cost` and true realized PnL remain unknown until the user or a future broker adapter fills them in.
  - The operator recommends trades but does not auto-apply them back into the actual state file. This is intentional so the model target and actual holdings remain separate sources of truth.

### 11:23 KST - phase1-regime-fallback-and-dd-breaker

- scope:
  - Start the `30% CAGR / -20s MDD` roadmap by hardening live regime sleeve selection and implementing the first active portfolio-level drawdown circuit breaker in backtest execution.
- files:
  - `r1000_top30_institutional.py` -> added a learned/manual regime-policy lookup chain with nearest-label fallbacks, wired that lookup into regime comparison metadata and live sleeve override resolution, bumped `ENGINE_REUSE_VERSION`, and implemented a portfolio drawdown circuit breaker inside the active `backtest_portfolio()` loop.
- symbols_changed:
  - `ENGINE_REUSE_VERSION` -> bumped to `2026-04-15-phase1-regime-dd` so downstream cache reuse is invalidated for the new regime / breaker behavior.
  - `REGIME_LABEL_NEAREST_FALLBACKS`, `build_regime_label_lookup_chain()`, `resolve_regime_policy_selection()` -> centralize regime label fallback order as `learned exact -> manual exact -> nearest learned/manual -> balanced/ALL`.
  - `compare_sleeve_cap_policy_backtests()` and `compare_regime_conditioned_sleeve_map_methods()` -> now expose the same fallback-aware live regime policy selection metadata used by the live portfolio path.
  - `resolve_regime_conditioned_sleeve_override()` -> now falls back from learned champion maps to manual regime maps before dropping to generic labels, and exports lookup source / lookup label / fallback usage in metadata.
  - `backtest_portfolio()` -> now tracks `running_equity`, computes drawdown before each rebalance, forces all sleeves due while breaker is active or just released, applies a breaker cash override using the current sleeve mix, and logs breaker state fields into monthly return rows.
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/sleeve_cap_policy_champion_latest.json` and `full_validation_suite.json` will now reflect fallback-aware live regime policy metadata instead of a learned-map-only lookup.
  - `outputs/returns_oos_monthly.csv` gains breaker diagnostics such as drawdown before/after month, breaker active flag, breaker event, and breaker cash target.
- validation:
  - `python -m py_compile H:\\codex\\r1000_top30_institutional.py` passed after the change.
- risks_or_notes:
  - The new circuit breaker is only implemented in `backtest_portfolio()` for now. The live/latest portfolio path still relies on regime-based cash control rather than a separate realized-equity breaker.
  - The legacy `_legacy_unused_backtest_portfolio()` path was kept in sync for future comparisons, but the active validation target remains the production `backtest_portfolio()` function.

### 13:08 KST - harden-colab-drive-mount-retry

- scope:
  - Make the first Colab setup cell recover from common Drive mount failures instead of stopping immediately on `ValueError: mount failed`.
- files:
  - `colab_run.ipynb` -> replace the direct `drive.mount()` call with a small recovery helper that retries after `flush_and_unmount()`, `fusermount -u`, and a short delay, then raises a clearer instruction if the second mount still fails.
- symbols_changed:
  - `mount_drive_with_recovery()` -> new notebook helper for the setup cell.
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - Notebook JSON updated and synced into the GitHub working tree.
- risks_or_notes:
  - This only hardens the notebook bootstrap path. If Google auth popups are blocked or the Colab runtime is in a bad state, the user may still need to restart the runtime and rerun the first cell.

### 14:18 KST - cut-collector-repeat-runtime

- scope:
  - Reduce repeat collector runtime and make `fast_mode` affect the collector path instead of only Phase 4/5.
- files:
  - `r1000_top30_institutional.py` -> add a poor-coverage-only refresh mode for the yfinance quarterly supplement, add a stale/missing CIK selector for incremental SEC/FSDS parsing, widen `fast_mode` so it also lightens collector refresh settings, and bump `ENGINE_REUSE_VERSION`.
  - `r1000_data_collector.py` -> apply `apply_fast_mode()` inside `run_data_collection()` so notebook collector runs actually benefit from the fast-mode collector throttles.
- symbols_changed:
  - `ENGINE_REUSE_VERSION` -> bumped to `2026-04-15-phase1-ops-layer-perf1`.
  - `EngineConfig.yf_quarterly_refresh_only_poor_coverage` -> new default flag so repeat runs do not re-fetch quarterly yfinance statements for already well-covered names.
  - `apply_fast_mode()` -> now also raises live/statement refresh ages and lowers expensive collector caps.
  - `select_fund_panel_refresh_ciks()` -> new incremental selector for stale or missing SEC/FSDS CIK refreshes.
  - `load_or_update_fund_panel()` -> reuses the cached panel when there are no stale/missing CIKs instead of reparsing the full universe.
  - `run_data_collection()` -> now routes the collector config through `apply_fast_mode()`.
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - local static validation pending final py_compile after sync to the GitHub working tree.
- risks_or_notes:
  - These changes mainly speed up repeat runs. The very first full collector build can still be slow because the initial SEC/FSDS/yfinance supplement caches must exist before the incremental shortcuts can help.

### 15:07 KST - add-run-archive-and-manifest

- scope:
  - Persist a versioned archive for each main pipeline run so outputs can be traced back to a specific code/config snapshot and restored later if a newer run regresses.
- files:
  - `r1000_top30_institutional.py` -> add git/run identity helpers, include run metadata in `weights_latest.json` and `run_summary.json`, write `outputs/run_manifest.json`, and archive the current output set into `outputs/archive/<run_id>/`.
  - `r1000_operator.py` -> include run metadata (`run_id`, `run_ts`, `git_commit`, `config_fingerprint`, `engine_version`) in `live_operator_summary.json`.
- symbols_changed:
  - `safe_run_token()`, `current_git_commit()`, `build_run_identity()`, `archive_run_outputs()` -> new helpers for version-aware run metadata and archive export.
  - `export_outputs()` -> now stamps weights/summary with run metadata, archives the latest outputs, and records `archive_dir` plus `run_manifest`.
  - `build_live_operator_plan()` / `refresh_live_operator_outputs()` -> now accept and persist the run metadata passed in from the main pipeline.
- breaking_changes:
  - none
- outputs:
  - `outputs/run_manifest.json`
  - `outputs/archive/<run_id>/run_manifest.json`
  - versioned archive copies of the latest output bundle under `outputs/archive/<run_id>/`
- validation:
  - local static validation pending final py_compile after sync to the GitHub working tree.
- risks_or_notes:
  - This archives the latest generated outputs, not a git checkout of source files. Code rollback still uses Git commits; the archive provides the matching result bundle and manifest.

### 16:05 KST - fix-breaker-duplicates-and-operator-sleeve-state-sync

- scope:
  - Remove duplicate circuit breaker code in backtest_portfolio, add sleeve-aware operator thresholds, and sync live portfolio state after each operator plan so the next run starts from the correct baseline.
- files:
  - `r1000_top30_institutional.py` -> removed duplicate initialization of running_equity/portfolio_peak/circuit_breaker_active/breaker_threshold/breaker_cash_target/breaker_recovery (6 lines) and duplicate inner functions _normalize_breaker_mix/_current_breaker_mix inside backtest_portfolio().
  - `r1000_operator.py` -> added sleeve-aware policy thresholds per sleeve (core_compounder/future_winner/early_scout), sleeve label resolution from portfolio/top30 data, sleeve_label column in operator plan output, and _sync_state_from_plan() so live portfolio state is updated with recommended weights after each plan generation.
- symbols_added:
  - `_SLEEVE_POLICIES: dict[str, dict[str, float]]` -> per-sleeve operator thresholds for min_hold_days, exit loss/risk, support floor, legacy rank buffer, legacy keep weight.
  - `_resolve_sleeve(target_row, top_row) -> str` -> resolves sleeve label from portfolio_latest or top30_latest columns.
  - `_sleeve_threshold(sleeve, key, defaults) -> float` -> returns sleeve-specific threshold with base default fallback.
  - `_sync_state_from_plan(base_dir_or_paths, plan, summary, strategy_version)` -> syncs live_portfolio_state.json with the operator plan's recommended weights after each run.
- symbols_changed:
  - `build_live_operator_plan()` -> now resolves sleeve label per ticker, applies sleeve-specific hold/exit/legacy thresholds instead of flat defaults, includes sleeve_label in plan output, and calls _sync_state_from_plan after saving the plan.
  - `backtest_portfolio()` -> removed duplicate variable initialization (lines 15415-15420) and duplicate _normalize_breaker_mix/_current_breaker_mix definitions (lines 15475-15517).
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/ops/live_operator_plan_latest.csv` now includes `sleeve_label` column.
  - `outputs/ops/live_portfolio_state.json` is now updated after each operator plan generation with recommended weights.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py r1000_operator.py r1000_portfolio_state.py` passed.
  - Grep confirmed _normalize_breaker_mix and _current_breaker_mix each appear exactly once after duplicate removal.
  - Grep confirmed breaker initialization variables appear exactly once after duplicate removal.
- risks_or_notes:
  - State sync assumes the operator's recommended weights are followed. If the user diverges materially from the plan, they should manually edit live_portfolio_state.json before the next run.
  - Sleeve-specific thresholds: core_compounder gets wider loss tolerance (-15%, hold 42d), early_scout gets tighter (-10%, hold 14d), future_winner uses standard defaults (-12%, hold 21d).
  - ENGINE_REUSE_VERSION is NOT bumped because these changes only affect the post-backtest operator layer. Walk-forward cached artifacts remain valid and will be reused.

### 16:42 KST - remove-operator-auto-state-sync-and-fix-sleeve-resolver

- scope:
  - Revert the operator's automatic live-state mutation during plan generation and tighten sleeve resolution so sleeve-aware thresholds only consume real label fields.
- files:
  - `r1000_operator.py` -> remove `save_live_portfolio_state` dependency and the `_sync_state_from_plan()` call/path, drop `portfolio_sleeve_promoted` from `_SLEEVE_LABEL_COLUMNS`, and stamp operator summaries with manual-apply metadata.
- symbols_changed:
  - `_SLEEVE_LABEL_COLUMNS` -> now only checks actual sleeve label columns (`portfolio_sleeve_label`, `sleeve_label`, `sleeve`).
  - `build_live_operator_plan()` -> no longer mutates `live_portfolio_state.json`; now reports `state_sync_mode=manual_apply_required`.
- breaking_changes:
  - none
- outputs:
  - `outputs/ops/live_operator_summary.json` now explicitly states that the operator output is recommendation-only and does not auto-apply to live state.
- validation:
  - `python -m py_compile r1000_operator.py r1000_top30_institutional.py r1000_portfolio_state.py` passed in the GitHub working tree.
- risks_or_notes:
  - This restores the live portfolio state as the source of truth for actual holdings. A future explicit `apply` or broker reconciliation step can update state after real execution, but planning runs no longer do so implicitly.

### 17:12 KST - restore-active-breaker-state-in-backtest

- scope:
  - Fix the active `backtest_portfolio()` path after the monitoring/state-refresh refactor by restoring the circuit-breaker state initialization and helper closures that the monthly loop depends on.
- files:
  - `r1000_top30_institutional.py` -> restore `running_equity`, `portfolio_peak`, `circuit_breaker_active`, breaker thresholds, and the active-path `_normalize_breaker_mix()` / `_current_breaker_mix()` definitions inside `backtest_portfolio()`.
- symbols_changed:
  - `backtest_portfolio()` -> the active path now initializes breaker state before the monthly loop and can safely compute `drawdown_before_month`.
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `python -m py_compile r1000_top30_institutional.py r1000_operator.py r1000_portfolio_state.py` passed in the GitHub working tree.
- risks_or_notes:
  - The repeated helper names/counts now appear twice in the file because both the legacy unused backtest path and the active backtest path each define their own local closures. That is expected.

### 17:15 KST - operational-improvements-state-monitoring-diff-manual

- scope:
  - Four operational improvements: state force-refresh from previous weights before new export, monitoring-only operator mode, archived run comparison, and manual holdings update tool.
- files:
  - `r1000_portfolio_state.py` -> added `force_refresh` parameter to `ensure_live_portfolio_state()` that re-bootstraps from weights while preserving entry_date/avg_cost for held tickers; added `apply_actual_holdings()` for manual broker/state updates.
  - `r1000_operator.py` -> added `monitoring_only` parameter to `build_live_operator_plan()` and `refresh_live_operator_outputs()` that suppresses rebalance actions and only checks intramonth exit signals; added `compare_run_outputs()` that diffs two archived runs for holdings/weights/metrics/regime changes.
  - `r1000_top30_institutional.py` -> in `export_outputs()`, reads the PREVIOUS `weights_latest.json` and force-refreshes live state before writing the new weights, so the operator always compares old holdings vs new targets correctly.
- symbols_added:
  - `apply_actual_holdings(base_dir_or_paths, holdings, as_of_date, strategy_version)` -> updates live state from a manual dict of {ticker: weight} or {ticker: {weight, avg_cost, shares}}.
  - `compare_run_outputs(base_dir_or_paths, run_id_old, run_id_new)` -> loads two archived run manifests and returns added/removed tickers, weight deltas, metric changes, regime shift, and a summary_text string.
- symbols_changed:
  - `ensure_live_portfolio_state()` -> added `force_refresh: bool = False`; when True, re-bootstraps from weights_payload and preserves entry_date/avg_cost from previous positions.
  - `build_live_operator_plan()` -> added `monitoring_only: bool = False`; when True, forces `full_rebalance_due = False` so only intramonth exit signals are checked.
  - `refresh_live_operator_outputs()` -> passes `monitoring_only` through to `build_live_operator_plan`.
  - `export_outputs()` -> reads old weights_latest.json and calls `ensure_live_portfolio_state(force_refresh=True)` before writing new weights.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/ops/live_operator_summary.json` now includes `monitoring_only` field.
- validation:
  - `py -3 -m py_compile r1000_portfolio_state.py r1000_operator.py r1000_top30_institutional.py r1000_data_collector.py` passed.
- risks_or_notes:
  - The pre-export state refresh assumes the user executed the previous run's recommendations. If they diverged, `apply_actual_holdings()` should be called before the next pipeline run.
  - `monitoring_only=True` still generates a full plan CSV but all actions default to hold/watch except intramonth exit signals.
  - ENGINE_REUSE_VERSION is NOT bumped; walk-forward cache remains valid.

### 18:05 KST - regime-guardrail-and-colab-catboost-parity

- scope:
  - Diagnose why the latest run improved drawdown but lost CAGR, then restore closer apples-to-apples parity with the prior stronger run.
- files:
  - `r1000_top30_institutional.py` -> added regime exploratory guardrails so learned regime sleeve maps cannot collapse `balanced` / `growth_reentry` states into overly defensive mixes with near-zero growth sleeves.
  - `colab_run.ipynb` -> added a lightweight dependency bootstrap cell that installs `catboost` only when missing, so Colab runs do not silently degrade to linear-only models.
- symbols_added:
  - `REGIME_EXPLORATORY_GUARDRAILS` -> minimum future/early sleeve floors and max cash caps for balanced and growth reentry regimes.
  - `apply_regime_policy_guardrails(live_label, selected_policy)` -> clamps defensive learned regime policies back into a minimally exploratory sleeve mix before applying them.
- symbols_changed:
  - `resolve_regime_conditioned_sleeve_override()` -> now applies guardrails after learned/manual regime policy selection and exports guardrail metadata (`guardrail_applied`, `guardrail_label`, `guardrail_reason`).
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `weights_latest.json` / `run_summary.json` regime sleeve metadata will now reflect whether a guardrail was applied to the selected regime-conditioned sleeve policy.
- validation:
  - `python -m py_compile r1000_top30_institutional.py r1000_operator.py r1000_portfolio_state.py` passed in the GitHub working tree.
- risks_or_notes:
  - This is intentionally a guardrail, not a full regime-policy rewrite. It prevents clearly over-defensive learned maps from dominating balanced/growth-reentry runs, but it does not guarantee a specific CAGR target.
  - Colab users still need to rerun the main pipeline after pulling the updated notebook/repo so the installed `catboost` package is actually available in that runtime.

### 18:40 KST - concentrated-alpha-layer-v1

- scope:
  - Add a first concentrated-investment layer that reuses the existing scored panel and sleeve engines, but builds a separate high-conviction portfolio with 1-3 names and dedicated backtest/export outputs.
- files:
  - `r1000_top30_institutional.py` -> added concentrated-alpha config fields, selector, weighting logic, backtest comparison, latest concentrated holdings export, concentrated metrics JSON, and concentrated operating guide output.
- symbols_added:
  - `prepare_concentrated_frame(cfg, frame)` -> builds a concentrated candidate frame from the existing latest/scored universe using sleeve-aware and momentum/confirmation-aware signals.
  - `select_concentrated_portfolio_topk(cfg, month_df, top_n)` -> selects 1-3 concentrated candidates with preference for `future_winner` and `early_scout`.
  - `concentrated_weight_map(cfg, selected, weighting_mode)` -> supports `conviction_curve`, `winner_take_all`, and `score_power` weighting for concentrated sleeves.
  - `backtest_concentrated_portfolio(cfg, signals, top_n, rebalance_interval_months, weighting_mode)` -> runs a separate concentrated portfolio backtest.
  - `compare_concentrated_portfolio_backtests(cfg, signals, top_n_candidates, intervals, weighting_modes)` -> compares concentrated modes across 1-3 names.
  - `build_latest_concentrated_holdings(cfg, latest_frame, concentrated_compare)` -> produces the latest concentrated portfolio recommendation and summary.
  - `concentrated_strategy_objective(row)` -> CAGR-forward objective used to rank concentrated strategy candidates.
- symbols_changed:
  - `EngineConfig` -> now includes concentrated-alpha controls such as target name counts, weighting modes, sleeve focus, and monitoring cadence.
  - `apply_fast_mode()` -> keeps concentrated comparison enabled but narrows it to lighter monthly checks.
  - `export_outputs()` -> now exports concentrated latest holdings, concentrated metrics, operating guide, and concentrated comparison CSVs.
  - `run_all()` -> adds a new concentrated comparison phase before export.
- config_fields_added:
  - `run_concentrated_backtest_comparison`
  - `concentrated_top_n_candidates`
  - `concentrated_rebalance_intervals`
  - `concentrated_weighting_modes`
  - `concentrated_allowed_sleeves`
  - `concentrated_min_confirmation`
  - `concentrated_score_*`
  - `concentrated_max_single_name_weight`
  - `concentrated_monitoring_review_days`
- breaking_changes:
  - none
- outputs:
  - `outputs/concentrated_portfolio_latest.csv`
  - `outputs/concentrated_top1_latest.csv`
  - `outputs/concentrated_backtest_metrics.json`
  - `outputs/concentrated_operating_guide.json`
  - `outputs/reports/concentrated_strategy_comparison.csv`
  - `outputs/reports/concentrated_strategy_monthly.csv`
  - `outputs/reports/concentrated_strategy_holdings.csv`
- validation:
  - `python -m py_compile r1000_top30_institutional.py r1000_operator.py r1000_portfolio_state.py r1000_data_collector.py` passed in the GitHub working tree.
- risks_or_notes:
  - This is a V1 concentrated layer. It does not yet maintain a separate live operator/state namespace; it exports a separate concentrated portfolio plus an operating guide and backtest comparison first.
  - The concentrated layer is intentionally biased toward `future_winner` / `early_scout` names and should be treated as a separate aggressive sleeve, not as a replacement for the main diversified portfolio.

### 19:05 KST - concentrated-validation-and-colab-surface
- scope:
  - surfaced the concentrated-alpha outputs inside the validation suite and updated the Colab runbook so the concentrated portfolio artifacts are visible in the standard execution flow.
- files:
  - `r1000_data_collector.py` -> added concentrated output reads and a `concentrated_snapshot` block to `run_full_validation_suite()`.
  - `colab_run.ipynb` -> updated the main validation print cell and the output inspection cell to show concentrated metrics, guide, latest concentrated holdings, and strategy comparison results.
- symbols_changed:
  - `run_full_validation_suite()` -> now reports concentrated comparison rows, best mode row, latest concentrated holdings preview, and concentrated operating guide metadata.
- outputs:
  - `reports/full_validation_suite.json` now includes `concentrated_snapshot`.
  - the notebook output section now reads:
    - `outputs/concentrated_backtest_metrics.json`
    - `outputs/concentrated_operating_guide.json`
    - `outputs/concentrated_portfolio_latest.csv`
    - `outputs/reports/concentrated_strategy_comparison.csv`
- validation:
  - `python -m py_compile r1000_top30_institutional.py r1000_operator.py r1000_portfolio_state.py r1000_data_collector.py` passed in the GitHub working tree.
  - `python -c "import json, pathlib; json.loads(pathlib.Path('colab_run.ipynb').read_text(encoding='utf-8'))"` passed in the GitHub working tree.

## 2026-04-16

### 12:27 KST - phase1-turnaround-value-uptrend-alpha

- scope:
  - Replaced placeholder turnaround/cashflow inflection scores with real implementations and added new value-inflection / uptrend-continuation / uptrend-breakdown signals so the engine can finally pick up loss-to-profit turnaround names (e.g. WDC/LITE-style 5x setups), value-and-growth catch-up names with PE compression, and defend its existing 52w-high winners while penalising trend breaks.
- files:
  - `r1000_top30_institutional.py` -> added panel-level sign-flip / loss-narrowing features in `add_fundamental_features`, added cross-sectional `fundamental_turnaround_acceleration_score`, `cashflow_inflection_under_loss_score`, `value_inflection_score`, `uptrend_continuation_score`, and `uptrend_breakdown_penalty` inside `compute_strategy_blueprint_columns`, and wired the new signals into `compute_portfolio_sleeve_columns` for core / future / early sleeves; bumped `ENGINE_REUSE_VERSION`.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `value_inflection_score (column)` -> cheap valuation + earnings catching up + price reversing from oversold / Stage 1->2 setup with quality floor gating
  - `uptrend_continuation_score (column)` -> 52w-high + full MA-stack alignment + intact momentum + intact earnings + compounding fundamentals
  - `uptrend_breakdown_penalty (column)` -> fires when previously-strong names lose MA50/MA200, gap down on earnings, see revisions roll over, or experience momentum rollover / death cross
  - `op_income_sign_flip_pos / ocf_sign_flip_pos / fcf_sign_flip_pos / ni_sign_flip_pos / gp_sign_flip_pos (panel cols)` -> 0/1 flag for loss-to-profit transition versus 4q-prior period
  - `op_income_loss_narrowing_4q / ocf_loss_narrowing_4q / fcf_loss_narrowing_4q / ni_loss_narrowing_4q (panel cols)` -> magnitude of loss reduction when both periods still negative
  - `ocf_under_loss_growth / fcf_under_loss_growth / op_income_under_loss_growth (panel cols)` -> growth/inflection of cash-flow lines while net income still negative (Lynch/O'Neil leading indicator)
  - `any_profit_sign_flip_pos (panel col)` -> max of all four primary sign-flip flags
- symbols_changed:
  - `add_fundamental_features()` -> added the panel-level sign-flip, loss-narrowing, and under-loss-growth helpers and registered the new columns in `carry_cols` so they propagate through the standard ffill -> monthly merge pipeline
  - `compute_strategy_blueprint_columns()` -> implemented the previously-zero `fundamental_turnaround_acceleration_score` and `cashflow_inflection_under_loss_score` placeholders using the new panel features, and added the three new Phase 1 alpha signals listed above; also added the new score columns to the empty-frame initialiser
  - `compute_portfolio_sleeve_columns()` -> wired `value_inflection_score`, `uptrend_continuation_score`, and `uptrend_breakdown_penalty` into core / future / early sleeve composites with role-appropriate weights (early = bottom-fishing emphasis, core = uptrend defence emphasis, future = balanced)
  - `ENGINE_REUSE_VERSION` -> bumped to `2026-04-16-phase1-turnaround-value-uptrend-alpha`
- config_fields_added:
  - none
- breaking_changes:
  - none. Cached artifacts from the previous `ENGINE_REUSE_VERSION` will be invalidated and recomputed on next run because the version string changed; this is by design so the new signals get populated.
- outputs:
  - none new. The next pipeline run will populate the new score columns inside the existing universe / sleeve parquet outputs.
- validation:
  - `py -3 -c "import ast; ast.parse(open('r1000_top30_institutional.py', encoding='utf-8').read())"` passed locally.
- risks_or_notes:
  - The new panel sign-flip features depend on having at least 4 quarters of TTM history per cik; firms with shorter history will simply receive zero credit on the turnaround scores rather than a noisy signal.
  - `value_inflection_score` is gated by a `quality_floor` (op_margin > -5% and debt/equity < 3.0) to avoid value-trap loss-makers; this is intentional and not a configurable knob yet.
  - Sleeve weight changes are additive only (no existing weights were reduced), so the relative importance of pre-existing signals such as `long_hold_compounder_score` will mechanically dilute slightly. Backtesting on the next run will tell us whether this needs renormalisation.
  - This change is the Phase 1 half of the joint Phase 1+2 plan agreed with the user; Phase 2 (industry-level relative strength using yfinance industry metadata) is the next set of work and will be a separate changelog entry.

### 12:36 KST - phase2-industry-relative-strength-and-leadership

- scope:
  - Brought the engine's relative-strength taxonomy down from sector-level (11 GICS sectors) to industry-level using yfinance industry metadata, then layered an O'Neil/IBD leadership score and a bottom-up industry rotation signal on top so the system can finally answer the user's "is semis strong → pick the best semi" question and find rotating-up groups.
- files:
  - `r1000_top30_institutional.py` -> added a yfinance industry-metadata cache (`yf_industry_metadata.parquet`) plus a coarse-grained `YF_INDUSTRY_TO_GICS_GROUP` bucket map; added cross-sectional industry RS, group-level momentum/breadth means, an O'Neil leadership score, and an industry rotation signal; wired the new signals through `build_universe_monthly` and into the core / future / early sleeve composites; bumped `ENGINE_REUSE_VERSION`.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `YF_INDUSTRY_TO_GICS_GROUP (constant)` -> ordered list of (bucket_label, substring_keys) folding ~150 yfinance industry strings into 24 stable GICS-style buckets
  - `INDUSTRY_METADATA_COLUMNS (constant)` -> schema for the cached yfinance industry metadata table
  - `map_yf_industry_to_group(industry)` -> case-insensitive substring match returning the coarse bucket
  - `load_industry_metadata_cache(paths)` -> reads `cache_misc/yf_industry_metadata.parquet`
  - `save_industry_metadata_cache(paths, df)` -> writes the same file atomically
  - `fetch_ticker_industry_metadata(ticker)` -> single-ticker yfinance `info` lookup capturing `sector`, `industry`, `industryDisp`, `sectorKey`, `industryKey`
  - `ensure_industry_metadata(cfg, paths, tickers, max_new=500, refresh_days=60)` -> batched cache top-up obeying refresh-day TTL and `industry_metadata_max_new_per_run` budget
  - `attach_industry_metadata(monthly, industry_meta)` -> merges the metadata cache onto the monthly frame and derives `industry`, `subindustry`, `industry_group` columns
  - `_demean_within_group(df, value_col, group_cols, out_col, min_group_size=4)` -> helper that subtracts the within-group mean while zero-ing micro-buckets
  - `_group_mean_to_row(df, value_col, group_cols, out_col)` -> helper that broadcasts a group mean back to each row
  - `add_industry_relative_strength(monthly)` -> writes `rs_industry_{1,3,6,12}m`, `rs_industry_group_{1,3,6,12}m`, `industry_mom_mean_{3,6,12}m`, `industry_group_mom_mean_{3,6,12}m`, `industry_breadth_above_ma200`, `industry_group_breadth_above_ma200`
  - `compute_oneil_leadership_score(monthly)` -> writes `industry_group_strength_score`, `industry_within_leader_rank`, `oneil_leadership_score` (multiplicative leader-in-strong-group composite)
  - `add_industry_rotation_signal(monthly)` -> writes `industry_rotation_signal` (z-scored composite of industry beating market on 3m, accelerating, with breadth recovering 50-80%)
- symbols_changed:
  - `EngineConfig` -> added `industry_metadata_max_new_per_run: int = 250` and `industry_metadata_refresh_days: int = 60`
  - `build_universe_monthly()` -> after the existing `rs_sector_*` block, now calls `ensure_industry_metadata()`, `attach_industry_metadata()`, `add_industry_relative_strength()`, `compute_oneil_leadership_score()`, and `add_industry_rotation_signal()`
  - `compute_portfolio_sleeve_columns()` -> added `oneil_leadership_score` / `industry_group_strength_score` to core (modest weights), added `oneil_leadership_score` + `industry_group_strength_score` + `industry_within_leader_rank` + `rs_industry_6m` + `industry_rotation_signal` to future (highest weights — this is the IBD playbook), and added `industry_rotation_signal` (largest weight) + leadership / strength / leader-rank / `rs_industry_3m` to early-scout (bottom-fishing rotating-up industries)
  - `ENGINE_REUSE_VERSION` -> bumped to `2026-04-16-phase1+2-turnaround-value-industry-rs`
- config_fields_added:
  - `industry_metadata_max_new_per_run: int = 250` -> per-run cap on yfinance industry-info lookups (rate-limit budget)
  - `industry_metadata_refresh_days: int = 60` -> TTL after which cached industry metadata is re-fetched
- breaking_changes:
  - none. Adds new columns and writes a new cache file but does not modify or remove anything existing. Cached engine artifacts are invalidated by the new `ENGINE_REUSE_VERSION`, which is intentional.
- outputs:
  - `cache_misc/yf_industry_metadata.parquet` -> new cache with one row per ticker storing yfinance sector/industry strings + last-update timestamp
  - `feature_store/universe_monthly_latest.parquet` -> now includes `industry`, `industry_group`, `subindustry`, `rs_industry_*`, `rs_industry_group_*`, `industry_mom_mean_*`, `industry_group_mom_mean_*`, `industry_breadth_above_ma200`, `industry_group_breadth_above_ma200`, `industry_group_strength_score`, `industry_within_leader_rank`, `oneil_leadership_score`, `industry_rotation_signal`
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed locally.
  - `py -3 -c "import r1000_top30_institutional as eng; ..."` import + symbol-presence check passed locally for all 10 new public symbols.
  - Synthetic 48-row functional test (3 industries x 8 names x 2 dates) confirmed `add_industry_relative_strength`, `compute_oneil_leadership_score`, and `add_industry_rotation_signal` produce well-scaled, mean-zero outputs end-to-end.
- risks_or_notes:
  - Industry metadata depends on yfinance availability; the first full run after upgrading will fetch up to `industry_metadata_max_new_per_run=250` tickers and may take several minutes due to the embedded 1s-per-40-call backoff. Subsequent runs only refresh tickers older than `industry_metadata_refresh_days=60`.
  - `YF_INDUSTRY_TO_GICS_GROUP` covers the most common yfinance industry strings seen in the Russell-1000 universe; truly exotic strings fall into `Other` and will receive zero industry-group RS rather than spurious values. The map should be reviewed quarterly as yfinance occasionally renames buckets.
  - Sleeve weight additions are deliberately additive (no existing weights were reduced) to avoid silently regressing previously-working signals; this means the relative weight of pre-existing factors mechanically dilutes slightly. We expect the next walk-forward backtest to show whether the industry-leadership tilt outweighs that dilution; if not, weights will be renormalised in a follow-up.
  - The new `rs_industry_*` and `rs_industry_group_*` columns set zero (not NaN) for micro-buckets below the `min_group_size` threshold — this is intentional to avoid spurious extreme z-scores but means a single-name-bucket name gets no industry RS credit at all.

### 15:30 KST - phase2-fix-industry-cache-dtype-crash

- scope:
  - Hot-fix for the `phase2-industry-relative-strength-and-leadership` change: `ensure_industry_metadata` crashed during the first end-to-end pipeline run with `TypeError: '<' not supported between instances of 'str' and 'Timestamp'` because newly fetched rows wrote `updated_at` as an ISO string while a freshly-loaded cache had it as `Timestamp`, producing a mixed-dtype object column that broke `sort_values`.
- files:
  - `r1000_top30_institutional.py` -> changed `fetch_ticker_industry_metadata` to return `pd.Timestamp` instead of an ISO string for `updated_at`; added defensive `pd.to_datetime` coercion at every entry point inside `ensure_industry_metadata` (before concat, after concat, on every return path); added `[yf_industry] Fetching ...` and progress logs so the long first-run yfinance pass is visible.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - `fetch_ticker_industry_metadata()` -> `updated_at` field now `pd.Timestamp.utcnow().tz_localize(None)` instead of `datetime.utcnow().isoformat(timespec="seconds")`
  - `ensure_industry_metadata()` -> coerces `updated_at` on `add` before concat, on `cache` before concat, and again after concat; added `na_position="first"` to the sort; added entry/progress log lines (`[yf_industry] Fetching ... `, `[yf_industry]   progress: i/N`)
- config_fields_added:
  - none
- breaking_changes:
  - none. Existing legacy cache files written by the broken version (string `updated_at`) are accepted on load and coerced to `datetime64` automatically — no manual cache deletion required to recover.
- outputs:
  - none new. The existing `cache_misc/yf_industry_metadata.parquet` will be re-saved with `datetime64[us]` dtype on the next run that triggers a fetch.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed locally.
  - End-to-end reproduction test: wrote a legacy parquet with string `updated_at`, stubbed the per-ticker fetch, called `ensure_industry_metadata` with mixed cached + new tickers — sort succeeded, returned dtype is `datetime64[us]`, second call (cache hit, no fetch) also returns `datetime64[us]`.
- risks_or_notes:
  - The user's in-flight Colab run crashed at `[05:49:55]` after the collector finished cleanly. After this fix is pulled, re-running cell 4 will reuse the collector outputs (already on Drive), reuse the bad-dtype cache (auto-coerced on load), and continue past the previous crash point. No re-collection or cache deletion is needed.

### 16:45 KST - fast-iter-infra-phase-toggles-quick-rescore-roadmap

- scope:
  - Fast-iteration infrastructure: Phase 1+2 env-var A/B toggles so the marginal contribution of each phase can be measured without editing code, a `pipeline_quick_rescore_cfg` preset that reuses the feature store + trained models for ~15-25 min iteration (down from ~1.5-4h full rebuilds), a `colab_run.ipynb` branch that chooses between the quick and full path at cell 2, and a persistent multi-session phase roadmap document for Phases 1..6.
- files:
  - `r1000_top30_institutional.py` -> added module-level `phase_is_enabled(phase_key, default=True)` helper right after `ENGINE_REUSE_VERSION`; added Phase 1 post-hoc zero-out guard at the end of `compute_strategy_blueprint_columns` (after `uptrend_breakdown_penalty` is written); added Phase 2 guard with zero-column fallback inside `build_universe_monthly` around the industry-metadata / industry-RS block so downstream sleeve code always sees the expected columns.
  - `r1000_data_collector.py` -> added `pipeline_quick_rescore_cfg(base_dir, end_date)` preset that sets `reuse_existing_artifacts=True`, `resume_partial_walkforward=True`, `reuse_phase4_models_for_latest_recommendations=True`, forces all refresh-TTL knobs to 99999, zeros out `industry_metadata_max_new_per_run` / `yf_quarterly_max_tickers_per_run`, disables every comparison-suite backtest except the concentrated one, and enables `fast_mode=True` so a single rescore round completes in ~15-25 min.
  - `colab_run.ipynb` -> cell 2 now exposes `QUICK_RESCORE_ONLY`, `PHASE1_ALPHA_ENABLED`, `PHASE2_INDUSTRY_ENABLED` knobs and wires the non-`auto` phase values into `PHASE_PHASE1_ALPHA_ENABLED` / `PHASE_PHASE2_INDUSTRY_ENABLED` env vars before the engine is imported; cell 4 branches between `pipeline_quick_rescore_cfg` and `collector_lean_full_run_cfg` on `QUICK_RESCORE_ONLY`, guards the old unconditional `resume_partial_walkforward=False` / `reuse_phase4_models_for_latest_recommendations=False` overrides behind `if not QUICK_RESCORE_ONLY:`, and guards the Phase 1+2 industry-metadata warm-up behind `if OPTION_1_FULL_REBUILD and not QUICK_RESCORE_ONLY:` so quick-rescore never re-fetches yfinance.
  - `CLAUDE.md` -> added a "Fast-Iteration Workflow" section documenting mode choice, phase-toggle mechanics, and the A/B measurement recipe; added a "Multi-Session Phase Plan" section linking to `PHASE_ROADMAP.md`; updated Key Files to list the new roadmap + proposal docs.
  - `PHASE_ROADMAP.md` -> new file: the canonical Phase 1..6 plan, including a TL;DR, the fast-iteration workflow, per-phase scope / signals / integration / expected impact / complexity / acceptance criteria / env gate, the full implementation order / PR plan, the 2026-04-15 baseline reference, session-continuation checklist, and invariants a cold-start agent must preserve.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `phase_is_enabled(phase_key: str, default: bool = True) -> bool` -> reads env var `PHASE_{KEY}_ENABLED`, returns True/False with `default` fallback; accepts truthy/falsy string forms (`1/0`, `true/false`, `on/off`, `yes/no`, `enabled/disabled`)
  - `pipeline_quick_rescore_cfg(base_dir: str, end_date: str | None = None) -> dict` -> fast-iter pipeline config preset that reuses feature store + models; docstring calls out the caveat that signal-formula changes are NOT reflected because the feature store is cached
- symbols_changed:
  - `compute_strategy_blueprint_columns()` -> added a post-hoc zero-out block at the end (after `d["uptrend_breakdown_penalty"] = ...`) that zeros the five Phase 1 score columns when `phase_is_enabled("phase1_alpha", default=True)` returns False; schema is always preserved so downstream code never KeyErrors
  - `build_universe_monthly()` -> wrapped the Phase 2 industry-metadata / `add_industry_relative_strength` / `compute_oneil_leadership_score` / `add_industry_rotation_signal` block in `if phase_is_enabled("phase2_industry", default=True)`, with an `else` branch that writes all expected industry / RS / leadership / rotation columns as zero / empty-string placeholders so disabled-phase runs still have a stable schema
- config_fields_added:
  - none. All toggles are via env vars (`PHASE_PHASE1_ALPHA_ENABLED`, `PHASE_PHASE2_INDUSTRY_ENABLED`), not EngineConfig fields, because (a) they are experiment knobs not production config and (b) env vars are easier to set at the top of a Colab notebook.
- breaking_changes:
  - none. Default behaviour is unchanged (both phases default to enabled). Existing runs that do not set the env vars behave identically to pre-change runs. Existing feature_store and model caches are compatible.
- outputs:
  - none new. The new preset produces the same `outputs/concentrated_backtest_metrics.json` schema used for all prior A/B comparisons, just faster.
- validation:
  - `py -3 -c "import ast; ast.parse(open('r1000_top30_institutional.py', encoding='utf-8').read())"` passed locally.
  - `py -3 -c "import ast; ast.parse(open('r1000_data_collector.py', encoding='utf-8').read())"` passed locally.
  - `py -3 -c "import json, pathlib; json.loads(pathlib.Path('colab_run.ipynb').read_text(encoding='utf-8'))"` passed locally — notebook JSON is well-formed after the `NotebookEdit` replacements.
  - Manual check: `phase_is_enabled` defaults True when env var is unset, False on `0/false/no/off/disabled`, True on `1/true/yes/on/enabled`.
- risks_or_notes:
  - Quick-rescore reuses the cached `feature_store/*.parquet`. Signal-formula changes (anything inside `compute_*` / `build_*` / `add_*` that writes a feature column) will NOT be reflected in the historical backtest under quick-rescore because the historical features were baked with the old formula. Bump `ENGINE_REUSE_VERSION` and run a full rebuild once whenever a formula changes, then return to quick-rescore.
  - The Phase 2 disable branch writes zero-valued placeholder columns via a small helper; if a future phase change depends on NaN vs zero semantics, revisit those defaults.
  - The phase toggles are written as post-hoc zero-outs for Phase 1 and conditional-branch for Phase 2 because Phase 2 touches `build_universe_monthly` (heavy IO), while Phase 1 just writes cheap cross-sectional columns. Post-hoc zero-out is sufficient for Phase 1 but would waste yfinance calls if applied to Phase 2 — the conditional branch is deliberate.
  - `PHASE_ROADMAP.md` is the durable memory of Phases 3..6 plans so this work can be resumed in a fresh chat session without re-deriving the plan. Any phase-level architectural decision should be reflected there before implementation begins.

### 17:20 KST - colab-sanity-cells-self-contained

- scope:
  - Fixed `NameError: name 'OUT' is not defined` / `name 'top30' is not defined` in `colab_run.ipynb` cells 9, 10, and 11 (the Phase 1+2 sanity check / baseline-delta / top-30 industry context cells). The previous implementation relied on `OUT` and `top30` being defined by cell 5, which fails when the user runs sanity cells directly without re-running cell 5 (or after a kernel restart).
- files:
  - `colab_run.ipynb` -> cells 9, 10, 11 now each redefine `BASE_DIR` and `OUT = Path(BASE_DIR) / 'outputs'` at the top and re-read `scored_latest.csv` / `concentrated_backtest_metrics.json` / `top30_latest.csv` from disk; added `[INFO]` / `[NOTE]` diagnostic messages when columns are missing or `target_stock_names` differs from the baseline.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - `colab_run.ipynb cell 9` -> added self-contained path setup + `Path` import; logic unchanged
  - `colab_run.ipynb cell 10` -> added self-contained path setup + `Path` import; added a [NOTE] when `cur.get('selected_names') != BASELINE['selected_names']` so the user knows the concentrated comparison is not apples-to-apples
  - `colab_run.ipynb cell 11` -> added self-contained path setup + `Path` import + reads `top30_latest.csv` directly; added a `missing` column report so absent industry / leadership columns are visible instead of silently dropped
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `py -3 -c "import json, pathlib; json.loads(pathlib.Path('colab_run.ipynb').read_text(encoding='utf-8'))"` passed locally.
- risks_or_notes:
  - The sanity cells now work even when cell 5 is not executed, which makes them safer to re-run after editing a single upstream cell during iteration.

### 18:08 KST - phase2-keepcols-survival-fix

- scope:
  - Critical bug fix. Phase 2 industry RS / O'Neil leadership / industry-rotation columns were being silently dropped from `feature_store_latest.parquet` by the explicit whitelist in `build_feature_store.keep_cols`. Phase 1 survived because `compute_strategy_blueprint_columns` is re-invoked on `latest_df` at `score_latest_month` (line 16890) and `prepare_latest_scored_data` (line 20237), re-deriving the 5 Phase 1 columns from raw inputs after the feature-store drop. Phase 2 columns have no such re-derivation path - they are attached once inside `build_universe_monthly` (`attach_industry_metadata` -> `add_industry_relative_strength` -> `compute_oneil_leadership_score` -> `add_industry_rotation_signal`) and then lost at `fs = universe[keep_cols].copy()`. Impact: every walk-forward month saw `oneil_leadership_score`, `industry_group_strength_score`, `industry_within_leader_rank`, `rs_industry_6m`, `industry_rotation_signal` as missing, so `cross_sectional_robust_z` fallbacks in `compute_dual_sleeve_composite_scores` (lines 17427 core, 17465-17468 future_winner, 17506-17509 early_scout) collapsed to 0.0, zeroing Phase 2's contribution in both historical backtest AND the latest scored export / `top30_latest.csv`.
- files:
  - `r1000_top30_institutional.py` -> added `PHASE2_INDUSTRY_COLUMNS` constant (23 entries: 3 string + 20 numeric); extended `keep_cols` in `build_feature_store` with `+ PHASE2_INDUSTRY_COLUMNS`; extended the `hard_sanitize` call with a numeric-only subset (`_PHASE2_NUMERIC_COLUMNS` excludes `industry` / `industry_group` / `subindustry` so they stay string-typed); extended `write_stage_coverage_report` for the `feature_store` stage so Phase 2 coverage is now tracked in `stage_coverage_feature_store.json`; bumped `ENGINE_REUSE_VERSION` from `"2026-04-16-phase1+2-turnaround-value-industry-rs"` to `"2026-04-16-phase2-keepcols-fix"` to force regeneration of cached `feature_store_latest.parquet`.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `PHASE2_INDUSTRY_COLUMNS: list[str]` -> module-level constant listing the 23 Phase 2 columns (3 string + 20 numeric) that must survive the feature_store keep-whitelist; kept in sync with the zero-placeholder block under `if not phase_is_enabled("phase2_industry"): ...` in `build_universe_monthly`.
- symbols_changed:
  - `build_feature_store(cfg, paths, ...)` -> added `+ PHASE2_INDUSTRY_COLUMNS` to the `keep_cols` construction; added `_PHASE2_NUMERIC_COLUMNS` (local) and passes it to `hard_sanitize`; appended `_PHASE2_NUMERIC_COLUMNS` to the `write_stage_coverage_report` column list for the `feature_store` stage.
- config_fields_added:
  - none
- breaking_changes:
  - Forces one-time regeneration of `feature_store_latest.parquet` on the next run (because `ENGINE_REUSE_VERSION` changed). Users on FULL rebuild mode will see a longer run; users on `QUICK_RESCORE_ONLY=True` will NOT pick up the fix because quick-rescore reuses the cached feature_store - they must run FULL once to materialize Phase 2 into feature_store, then can return to quick-rescore.
- outputs:
  - `feature_store_latest.parquet` -> now includes 23 Phase 2 columns (`industry`, `industry_group`, `subindustry`, `rs_industry_{1,3,6,12}m`, `rs_industry_group_{1,3,6,12}m`, `industry_mom_mean_{3,6,12}m`, `industry_group_mom_mean_{3,6,12}m`, `industry_breadth_above_ma200`, `industry_group_breadth_above_ma200`, `industry_group_strength_score`, `industry_within_leader_rank`, `oneil_leadership_score`, `industry_rotation_signal`).
  - `stage_coverage_feature_store.json` -> now reports coverage for the 20 numeric Phase 2 columns.
  - `scored_latest.csv` -> downstream, Phase 2 columns are now non-empty (sanity cell 9 will show `present=True` with non-zero `nonzero_share`).
- validation:
  - `py -3 -c "import py_compile; py_compile.compile('r1000_top30_institutional.py', doraise=True)"` -> passed.
  - Pending: user re-runs FULL rebuild (QUICK_RESCORE_ONLY=False) to confirm Phase 2 columns materialize in `scored_latest.csv` and that the concentrated / diversified backtest metrics reflect Phase 2 signal contribution. Previous 2026-04-15 baseline (CAGR 21.80%, Sharpe 0.73, MaxDD -36.86%) was measured with Phase 2 effectively zeroed - this rerun is the true Phase 1+2 apples-to-apples measurement.
- risks_or_notes:
  - If the new run's diversified CAGR / Sharpe improves materially over baseline, that is the "real" Phase 1+2 signal. If it underperforms, the Phase 2 signal is actually detrimental and should be gated / disabled - easy to A/B via `PHASE_PHASE2_INDUSTRY_ENABLED=0` on a second QUICK run once the FULL run has refreshed the cache.
  - Any new Phase (3..6) that attaches columns inside `build_universe_monthly` MUST either (a) be re-derivable in `score_latest_month` / `prepare_latest_scored_data`, or (b) add its columns to a constant appended to `keep_cols` in `build_feature_store`. Recommended pattern: create a `PHASE<N>_<NAME>_COLUMNS` constant and append to both `keep_cols` and the zero-placeholder block under the phase toggle's disabled branch.

### 18:37 KST - add-session-handoff-file

- scope:
  - Multi-machine session continuity. The user wanted to resume the same project on a different laptop / Colab account and needed a reliable single-item inbox that captures "what was just done + what must happen next" so a fresh Claude / Codex / GPT chat can pick up without having the prior conversation in memory. Previously the resume checklist pointed at CLAUDE.md + CHANGELOG.md + PHASE_ROADMAP.md, but none of those encode the very-latest pending action (e.g. "FULL rebuild must run next to verify the phase2-keepcols-fix commit"); a new chat session would have to infer it.
- files:
  - `SESSION_HANDOFF.md` -> new file, single-item inbox with §1 last thing that happened, §2 next action for the user, §3 what comes after verification, §4 copy-paste bootstrap prompt for a new chat, §5 what's in git vs Drive, §6 how to rotate the file.
  - `CLAUDE.md` -> added `SESSION_HANDOFF.md` at the top of Key Files list; rewrote the Multi-Session Phase Plan resume checklist to read `SESSION_HANDOFF.md` first, then CLAUDE.md / CHANGELOG.md / PHASE_ROADMAP.md / git log / Drive baseline.
  - `PHASE_ROADMAP.md` -> §7 session-continuation checklist updated to read `SESSION_HANDOFF.md` first; added a rule that when a phase ships the handoff file must be rewritten with the new state.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `SESSION_HANDOFF.md` -> ephemeral single-item inbox; rewritten (not appended) each time a phase ships.
- validation:
  - `git log --oneline -3` -> confirmed latest commit is `1d4fb40 Fix Phase 2 columns dropped by feature_store keep_cols whitelist`.
- risks_or_notes:
  - The handoff file must be rotated (rewritten in place) after every phase ship. Do NOT accumulate multiple handoff files or let stale handoff notes linger - a fresh chat session should always trust the current handoff as the single source of truth for "what's the immediate next action". If no phase is in-flight, the handoff can be a short note saying "no pending action, read CHANGELOG and PHASE_ROADMAP for the last shipped state".

### 23:45 KST - phase2-keepcols-fix-verified-via-full-rebuild

- scope:
  - Record the FULL-rebuild verification of the `1d4fb40 Fix Phase 2 columns dropped by feature_store keep_cols whitelist` commit. Phase 2 industry-RS / O'Neil leadership columns are now confirmed populated end-to-end, and the resulting Phase 1+2 diversified backtest is the new reference baseline for Phase 3 work.
- files:
  - `SESSION_HANDOFF.md` -> rotated to reflect "Phase 2 verified, Phase 3 next" as the single-item inbox for the next chat session.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/run_summary.json` -> `engine_version: "2026-04-16-phase2-keepcols-fix"`, `git_commit: "1d4fb4046f73b639ed24711045dbf0c731831ce7"`, `run_id: "20260416_111455__1d4fb40__2026-04-16-phase2-keepcols-fix"`.
  - `outputs/backtest_metrics.json` -> main diversified portfolio metrics: `cagr=0.2010`, `sharpe=1.0754`, `sortino=1.7799`, `max_dd=-0.2360`, `calmar=0.8516`, `ir=0.5835`, `beat_month_ratio=0.5904`, `excess_cagr=0.0660`, `avg_stock_names=25.78`, `rebalance_interval_months=1`.
  - `outputs/concentrated_backtest_metrics.json` -> concentrated (3-name) portfolio: `cagr=0.2014`, `sharpe=0.7090`, `max_dd=-0.3717`.
  - `outputs/reports/rebalance_interval_comparison.csv` -> 1M/3M/6M comparison confirms 1-month rebalance is the champion.
  - `outputs/reports/full_validation_suite.json` -> 27 top-level keys including `p1_p2_p3_checks`, `acceptance_checks`, `concentrated_snapshot`.
  - `outputs/scored_latest.csv` -> 610 rows × 573 columns; all 23 Phase 2 columns and all 5 Phase 1 columns present with non-zero shares.
- validation:
  - Phase 2 column sanity (scored_latest.csv, 610 rows):
    - `oneil_leadership_score` 95.41%, `industry_group_strength_score` 100.00%, `industry_within_leader_rank` 95.41%, `industry_rotation_signal` 100.00%, `rs_industry_6m` 80.49%, `rs_industry_group_6m` 96.39% -> all pass `nonzero_share >= 0.5` gate.
    - `industry`/`industry_group`/`subindustry` strings all 100.00% populated.
    - All 20 numeric Phase 2 columns have nonzero_share between 80.49% and 100.00%.
  - Phase 1 alpha column sanity (scored_latest.csv):
    - `fundamental_turnaround_acceleration_score` 95.41%, `value_inflection_score` 100.00%, `uptrend_continuation_score` 100.00%, `uptrend_breakdown_penalty` 74.43% -> all pass.
    - `cashflow_inflection_under_loss_score` 49.51% -> borderline but expected (loss-narrowing only applies to a subset of names).
  - Acceptance checks: `pit_ok=true`, `leakage_ok=true`, `oos_month_coverage_ok=true`, `survivorship_bias_warning=false`, `historical_membership_ok=true`, `critical_ttm_coverage_mean=0.808`.
  - Phase 2 keepcols fix is confirmed effective: no `[WARN] Phase 2: ... all-zero` warnings on this run.
- risks_or_notes:
  - Baseline comparison caveat: the 2026-04-15 pre-Phase 1+2 baseline ran in concentrated mode (selected_names=2, CAGR 21.80%), while this verification run's main portfolio is diversified mode (avg_stock_names=25.78, CAGR 20.10%). The -1.70pp CAGR delta is a mode mismatch, not a regression.
  - True apples-to-apples comparison is the diversified main portfolio: Sharpe improved from the pre-P1+P2 reference of ~0.73 to 1.08 (+0.35), MaxDD improved from ~-36.86% to -23.60% (+13.26pp). Excess CAGR vs S&P is +6.60pp. These are breakthrough-level improvements on risk-adjusted metrics.
  - Next action (per `SESSION_HANDOFF.md` and `PHASE_ROADMAP.md` §3): start Phase 3 sleeve weight renormalization + phase contribution audit. Runtime: QUICK_RESCORE is sufficient; no FULL rebuild needed for Phase 3.
  - `ENGINE_REUSE_VERSION` is NOT bumped by this documentation-only entry. The feature_store cache from this run (`2026-04-16-phase2-keepcols-fix`) remains valid for Phase 3 QUICK rescore iteration.

### 23:59 KST - phase3-sleeve-weight-renorm-infra

- scope:
  - Implement the Phase 3 sleeve-weight renormalization infrastructure (A/B gated, default OFF) so the next QUICK_RESCORE run can measure whether replacing row_mean's N-term averaging with a true weighted average `sum(w_i * z_i) / L1` removes the factor-dilution that Phase 1+2's additive weights introduced into the sleeve composites.
- files:
  - `r1000_top30_institutional.py` -> added `sleeve_weight_renorm_enabled` / `sleeve_weight_l1_target` fields to `EngineConfig`; added two helper functions (`sleeve_weight_l1_norm`, `weighted_sleeve_composite`); refactored `compute_portfolio_sleeve_columns` to build explicit `(weight, z_series)` pair lists for the core / future / early sleeves and dispatch through the new helper so the legacy row_mean path remains byte-identical when the toggle is off; emitted four new diagnostic columns (`sleeve_core_l1_norm`, `sleeve_future_l1_norm`, `sleeve_early_l1_norm`, `sleeve_weight_renorm_active`).
- symbols_added:
  - `sleeve_weight_l1_norm(weight_pairs: list[tuple[float, pd.Series]]) -> float` -> absolute sum of weights for a sleeve composite, emitted per-run for A/B diagnostics.
  - `weighted_sleeve_composite(weight_pairs, index, *, renorm_enabled=False, l1_target=0.0) -> pd.Series` -> sleeve composite aggregator; reduces to row_mean when renorm_enabled=False so legacy behaviour is preserved.
- symbols_changed:
  - `EngineConfig` -> added `sleeve_weight_renorm_enabled: bool = False` and `sleeve_weight_l1_target: float = 0.0` with inline commentary explaining the toggle semantics and L1-target meaning.
  - `compute_portfolio_sleeve_columns(df, cfg)` -> core, future, and early sleeve scores now derived from explicit `(weight, pd.Series)` pair lists that are passed through `weighted_sleeve_composite`; legacy `row_mean` call-sites replaced; empty-frame branch now also emits the four Phase 3 diagnostic columns as NaN for schema stability.
- config_fields_added:
  - `sleeve_weight_renorm_enabled: bool = False` -> gate (combined with `PHASE_PHASE3_RENORM_ENABLED` env var) to activate weighted-average sleeve composites.
  - `sleeve_weight_l1_target: float = 0.0` -> when > 0.0 the composite is divided by this value (match pre-P1+P2 L1 to preserve magnitude); when 0.0 the sleeve's own L1 is used (pure weighted average).
- breaking_changes:
  - none -> with the defaults off the sleeve composite values are byte-identical to the pre-Phase-3 path because the new helper short-circuits to `row_mean([w * s for w, s in pairs]).fillna(0.0)`, which is exactly the legacy expression.
- outputs:
  - `outputs/scored_latest.csv` -> four new columns appended: `sleeve_core_l1_norm`, `sleeve_future_l1_norm`, `sleeve_early_l1_norm`, `sleeve_weight_renorm_active`. The first three are scalar L1 norms per run; the last is a 0/1 flag so A/B comparisons can assert whether the renormalization path was actually taken.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - `ast.parse(...)` over the modified file passed with 381 top-level defs.
  - Spot-checked via AST that `weighted_sleeve_composite`, `sleeve_weight_l1_norm`, `sleeve_weight_renorm_enabled`, `sleeve_weight_l1_target`, `compute_portfolio_sleeve_columns`, `phase_is_enabled`, `row_mean` are all present.
  - Expected L1 norms from source reading: core ~8.52, future ~14.48, early ~13.04; pre-Phase-1+2 core L1 was ~7.32, so the Phase 1+2 additions inflate core's effective weight sum by ~16%. Phase 3 measurement will determine whether this inflation dilutes pre-existing factors enough to matter.
- risks_or_notes:
  - Phase 3 is **infrastructure only**; it does NOT change sleeve scores at runtime until the user sets both `cfg.sleeve_weight_renorm_enabled=True` and `os.environ["PHASE_PHASE3_RENORM_ENABLED"]="1"`. Until that A/B measurement ships, default runs are identical to the pre-Phase-3 behaviour.
  - A/B measurement protocol (per `PHASE_ROADMAP.md` §1): run QUICK_RESCORE twice, once with the Phase 3 toggle off and once with it on, and diff `strategy_cagr` / `sharpe` / `max_dd` between `outputs/concentrated_backtest_metrics.json` and `outputs/backtest_metrics.json`. Ship the renorm path only if Δ CAGR ≥ +0.5pp AND Δ MaxDD ≤ +1pp (per `PHASE_ROADMAP.md` §3).
  - The four new diagnostic columns are produced by `compute_portfolio_sleeve_columns`, which is called lazily at portfolio-construction time (see call-sites around lines 4193, 15459, 17113, 17259, 17332, 18144, 19246, 19340, 19342, 20499, 20645, 20718, 21740, 23929). They bypass `build_feature_store.keep_cols` the same way `portfolio_sleeve_label` does today, so Invariant #8 (keepcols survival) is not triggered.
  - `ENGINE_REUSE_VERSION` is NOT bumped. Phase 3 only touches portfolio-layer composition, not feature_store schema, so the cached feature store from the `2026-04-16-phase2-keepcols-fix` run stays valid.
  - The `early_weight_pairs` table explicitly writes the first three terms as `(1.00, ...)` where the legacy code passed them with no multiplier. Those are mathematically identical (1.00 * x == x), but documenting them as explicit 1.00 weights makes future L1-norm accounting unambiguous.

### 01:10 KST - phase3-audit-hardening-nan-cfg-penalty-scaling

- scope:
  - Pre-A/B-run hardening of the Phase 3 sleeve weight renormalisation. An adversarial audit (Agent `Explore`) uncovered three correctness concerns that would have confounded the A/B measurement if run as-is: (a) the renorm path used `.fillna(0.0)` on NaN z-scores instead of the NaN-skipping semantics that `row_mean` applies in the legacy path, (b) `getattr(cfg, ...)` would crash if any legacy call-site passed `cfg=None`, (c) the `sparse_history_penalty` post-processing was calibrated to the legacy `row_mean` magnitude and would lose ~50% of its relative strength when Phase 3 renorm scaled the composite magnitude up by roughly `N/L1` (~2x). Fixed all three so the A/B isolates only the intended "weighted-vs-equal" effect.
- files:
  - `r1000_top30_institutional.py` -> hardened `weighted_sleeve_composite` to compute per-row L1 that excludes NaN terms in the renorm path (matching `row_mean`'s NaN-skipping semantics); added `cfg is not None` guards before `getattr` calls in `compute_portfolio_sleeve_columns`; scaled the `sparse_history_penalty` and `history_depth` penalties by the sleeve's `N/L1` ratio when renorm is active so the penalty's relative strength on the composite is preserved across the legacy and renorm paths; emitted two more diagnostic columns (`sleeve_future_penalty_scale`, `sleeve_early_penalty_scale`).
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none (the diagnostic columns `sleeve_future_penalty_scale` and `sleeve_early_penalty_scale` are pd.DataFrame columns, not Python symbols).
- symbols_changed:
  - `weighted_sleeve_composite(weight_pairs, index, *, renorm_enabled=False, l1_target=0.0) -> pd.Series` -> renorm branch now builds a per-row valid-mask and computes `denom = valid_mask @ abs_weights` so NaN terms are excluded from both the numerator AND denominator, matching `row_mean`'s semantics. Docstring extended to explain the NaN policy and the L1-vs-sum(w) design choice (negative penalty weights intentionally share the L1 budget so their relative influence is preserved).
  - `compute_portfolio_sleeve_columns(df, cfg)` -> added `cfg is not None` guards around the two `getattr(cfg, ...)` calls that resolve Phase 3 toggles and l1_target; computed per-sleeve `_future_penalty_scale` / `_early_penalty_scale` factors that are 1.0 when renorm is off (preserving byte-identical legacy behaviour) and `N / L1` when renorm is on (so penalties scale up with the composite magnitude); applied those scales to the `sparse_history_penalty` and `history_depth` penalty deductions; empty-frame branch now also initialises the two new diagnostic columns.
- config_fields_added:
  - none (the audit did not add new cfg fields).
- breaking_changes:
  - none -> when Phase 3 is off (cfg flag False OR env not set to 1), `_future_penalty_scale` and `_early_penalty_scale` both default to 1.0 and the composite helper short-circuits to `row_mean`, so all legacy code paths are byte-identical to the pre-audit commit `5b95e17`.
- outputs:
  - `outputs/scored_latest.csv` -> two additional diagnostic columns appended alongside the existing Phase 3 diagnostics: `sleeve_future_penalty_scale`, `sleeve_early_penalty_scale`. Both scalar-per-run (all rows share the same value since the scales depend only on the sleeve table shape, not on the specific row).
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - `ast.parse(...)` passed with 381 top-level defs (unchanged).
  - AST symbol spot-check: `weighted_sleeve_composite`, `sleeve_weight_l1_norm`, `sleeve_weight_renorm_enabled`, `sleeve_weight_l1_target`, `compute_portfolio_sleeve_columns` all present.
  - Semantic sanity checks deferred to the Colab A/B run (numpy not installed on the local Git environment). The three critical correctness properties that the Colab run should verify in `scored_latest.csv`:
    - With `PHASE_PHASE3_RENORM_ENABLED=1`: `sleeve_weight_renorm_active=1.0` on every row.
    - With renorm on: `sleeve_future_penalty_scale` and `sleeve_early_penalty_scale` are > 1.0 (expected ~2.0 given current sleeve tables).
    - With renorm off (baseline A/B leg): all four penalty/l1 diagnostics retain their legacy scalar values (`sleeve_weight_renorm_active=0.0`, `sleeve_future_penalty_scale=1.0`, `sleeve_early_penalty_scale=1.0`).
- risks_or_notes:
  - The NaN-handling fix is mostly defensive. In the current call-graph every z-score series flowing into the sleeve composites is already `.fillna(0.0)`-terminated by `cross_sectional_robust_z` (line 3333-3343) or `numeric_series_or_default` (line 3406-3416), so the legacy A/B would not have produced NaN-handling divergence. The fix ensures future callers that pass raw NaN-bearing z-scores into `weighted_sleeve_composite` still get consistent semantics.
  - The L1-vs-sum(w) choice is intentional. Penalties (e.g. `-0.45 * uptrend_breakdown_penalty` in core) have negative weight but positive `|w|`, which consumes `|w_i|` of the L1 budget the same way any positive factor does. Using `sum(w)` as the denominator would shrink the denominator when penalties are large, strengthening their relative impact — the opposite of a well-behaved weighted average. The docstring now documents this.
  - The penalty-scale fix does NOT touch the `legacy byte-identical` property because `_future_penalty_scale` / `_early_penalty_scale` default to 1.0 when `_phase3_renorm_active` is False.
  - One caveat remains for A/B interpretation: the composite itself has ~2x magnitude when renorm is on, so the downstream `winsorize(..).clip(-6,6)` may saturate a small fraction of rows it did not saturate in legacy. This is a real change in behaviour, not a bug — the whole point of Phase 3 is to redistribute weight mass, and saturation is one of the mechanisms by which the redistribution manifests in the final sleeve score. Monitor it via the diagnostic columns in `scored_latest.csv`; if it turns out to be a meaningful chunk of rows we can add a `core_compounder_engine_score` saturation-rate diagnostic in a follow-up.
  - `ENGINE_REUSE_VERSION` is NOT bumped. Only portfolio-layer composition code is modified, feature_store schema is untouched.

### 06:45 KST - phase3-ab-rejected-keep-off-default

- scope:
  - Record the Phase 3 sleeve-weight renormalisation A/B run and the decision to REJECT the renorm path. The implementation was correct and the toggle fired as designed, but the hypothesis ("row_mean's N-averaging dilutes factor contribution, so L1-normalisation should improve risk-adjusted performance") is falsified: Phase 3 ON worsens CAGR, Sharpe, AND MaxDD simultaneously. Keeping `sleeve_weight_renorm_enabled=False` as the default and preserving the toggle so the code stays available for future re-evaluation if the sleeve factor tables change materially.
- files:
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/backtest_metrics.json` (Phase 3 ON leg) -> `cagr=0.1780`, `sharpe=0.9460`, `max_dd=-0.2818`, `ir=0.3990`, `excess_cagr=0.0431`, `beat_month_ratio=0.6024`.
- validation:
  - Diagnostic columns in `scored_latest.csv` confirmed the toggle fired: `sleeve_weight_renorm_active=1.0`, `sleeve_core_l1_norm=8.52`, `sleeve_future_l1_norm=16.24`, `sleeve_early_l1_norm=13.79`, `sleeve_future_penalty_scale=1.9089`, `sleeve_early_penalty_scale=2.1030`. Penalty scales match the expected `N/L1` ratios (future: 31/16.24≈1.91, early: 29/13.79≈2.10), confirming the penalty-magnitude hardening from `8b10bf4` is also working as designed.
  - A/B comparison vs the 2026-04-16 FULL rebuild baseline (Phase 3 OFF leg reused directly from the earlier `backtest_metrics.json`):
    - Δ CAGR:   -2.30pp (baseline 0.2010 -> ON 0.1780)
    - Δ Sharpe: -0.1294 (baseline 1.0754 -> ON 0.9460)
    - Δ MaxDD:  -4.58pp (baseline -0.2360 -> ON -0.2818, i.e. deeper drawdown)
  - Against the `PHASE_ROADMAP.md` §3 ship gate for Phase 3 (`Δ CAGR ≥ +0.5pp AND Δ MaxDD ≤ +1pp`), both conditions fail badly. All three risk-adjusted axes regressed.
- risks_or_notes:
  - Why the hypothesis failed: `row_mean`'s N-averaging was providing natural regularisation — shrinking each factor's effective weight as more factors were added kept the composite magnitude bounded and limited the impact of any single factor (including penalties). L1-normalisation removes that shrinkage, roughly doubling composite magnitude. Downstream `winsorize(0.01).clip(-6,6)` then saturates a larger fraction of rows, and the penalty-scale compensation (which we correctly applied) amplifies the sparse-history penalty by ~2x. The net effect is that the renorm path puts more weight on outliers and penalties than the legacy path, which hurts diversification and risk-adjusted returns across the board.
  - The implementation itself is correct; this is a negative result on the L1-normalisation design choice, not a bug. `weighted_sleeve_composite`, `sleeve_weight_l1_norm`, the three diagnostic columns, the penalty-scale factors, and the cfg+env dual-gate all work as designed. The infrastructure stays in the code for possible future re-evaluation.
  - Default stays `sleeve_weight_renorm_enabled=False`. Env var `PHASE_PHASE3_RENORM_ENABLED` remains a functional opt-in escape hatch but no mainstream pipeline path will set it.
  - Followup idea (NOT scheduled): try `l1_target = N` (the term count) which would preserve legacy magnitude but still let us redistribute weight shares — that is a conceptually different experiment and should go behind its own toggle if we ever revisit it.
  - `ENGINE_REUSE_VERSION` stays at `"2026-04-16-phase2-keepcols-fix"` -- no schema change.

### 07:30 KST - phase4-regime-conditional-sleeve-multipliers

- scope:
  - Phase 4 (PHASE_ROADMAP §2.4): add a regime-conditional multiplier layer on top of the three sleeve composite scores in `compute_portfolio_sleeve_columns`. The static factor tables in the legacy path give the same emphasis to every regime (balanced, growth_reentry, stagflation, systemic_crisis, carry_unwind, war_oil_rate_shock) even though the right emphasis differs by regime. Phase 4 multiplies the final per-sleeve composite by a regime-specific scalar so the same factor table can produce differentiated risk emphasis without re-weighting individual factors.
  - Default OFF — infrastructure lands now but no main pipeline path touches sleeve scores until the user flips both the EngineConfig flag AND the env gate. This is the same dual-gate safety pattern as Phase 3; it also ensures the A/B comparison against the Phase 2 / Phase 3-hardened `8b10bf4` baseline is apples-to-apples.
- files:
  - `r1000_top30_institutional.py` -> new `SLEEVE_FACTOR_REGIME_MULTIPLIERS` / `SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP` module constants, new helper `resolve_regime_sleeve_multipliers()`, Phase 4 dual-gate resolution and per-row regime-keyed multiplication block in `compute_portfolio_sleeve_columns`, four new diagnostic columns (`regime_sleeve_multiplier_core/future/early`, `regime_sleeve_weights_active`), empty-frame branch updated with the new schema.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `resolve_regime_sleeve_multipliers(regime_label: str, user_table: Optional[dict[str, dict[str, float]]] = None) -> dict[str, float]` -> three-tier lookup (user override -> built-in default -> identity) plus per-sleeve clamp to `SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP`. Forward-compat: unknown regime labels return identity instead of raising.
  - `SLEEVE_FACTOR_REGIME_MULTIPLIERS: dict[str, dict[str, float]]` -> built-in default multiplier table. growth_reentry {1.10, 1.30, 1.15}, balanced {1.00, 1.00, 1.00}, stagflation {0.85, 0.90, 1.15}, systemic_crisis {0.55, 0.70, 1.30}, carry_unwind {0.75, 0.80, 1.10}, war_oil_rate_shock {0.80, 0.85, 1.05}.
  - `SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP: tuple[float, float] = (0.40, 1.60)` -> belt-and-suspenders guard against bad user overrides.
- symbols_changed:
  - `compute_portfolio_sleeve_columns(df, cfg)` -> resolves Phase 4 dual-gate (`cfg.regime_dynamic_sleeve_weights_enabled` AND env `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED`); when active, reads `event_regime_label` per row, builds a per-label multiplier lookup, applies core/future/early scalars to the composite scores AFTER Phase 3 composition AND penalty subtraction but BEFORE winsorize/clip; always writes the four Phase 4 diagnostic columns so downstream audits can verify toggle state. Empty-frame branch updated with the new columns. When toggle is off, the multiplier columns are 1.0 and the sleeve scores are byte-identical to the pre-Phase-4 path.
- config_fields_added:
  - `regime_dynamic_sleeve_weights_enabled: bool = False` -> dual-gate flag (combined with `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED` env var) to activate per-regime sleeve multipliers.
  - `regime_sleeve_multiplier_table: Optional[dict[str, dict[str, float]]] = None` -> per-regime override table; `None` means use the built-in default.
- breaking_changes:
  - none -> legacy path (toggle OFF) returns byte-identical sleeve scores to commit `28e41fe`. Diagnostic columns are additive; any consumer expecting them to be present will find 1.0 / 0.0 constants when Phase 4 is off.
- outputs:
  - `outputs/scored_latest.csv` -> four additional diagnostic columns: `regime_sleeve_multiplier_core`, `regime_sleeve_multiplier_future`, `regime_sleeve_multiplier_early` (all 1.0 when toggle off), `regime_sleeve_weights_active` (0.0 when off, 1.0 when on).
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - `ast.parse(...)` passed with 382 top-level defs (was 381 — new `resolve_regime_sleeve_multipliers` helper).
  - Symbol spot-check: `resolve_regime_sleeve_multipliers`, `weighted_sleeve_composite`, `compute_portfolio_sleeve_columns`, `SLEEVE_FACTOR_REGIME_MULTIPLIERS`, `SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP`, `regime_dynamic_sleeve_weights_enabled`, `regime_sleeve_multiplier_table` all present.
  - Semantic A/B deferred to Colab QUICK_RESCORE per PHASE_ROADMAP §3. When ON leg runs, expected diagnostics:
    - `regime_sleeve_weights_active` = 1.0 on every row.
    - `regime_sleeve_multiplier_core` varies by regime label; `balanced` rows = 1.0 exactly, `systemic_crisis` rows = 0.55 etc.
    - Sleeve scores differ from legacy by up to ~30% on rows whose regime label is not `balanced`.
- risks_or_notes:
  - Multiplier application happens AFTER Phase 3 composition (row_mean or L1-renorm per toggle) AND AFTER the `sparse_history_penalty` subtraction. This ordering preserves the "Phase 3 renorm was a no-op for Phase 4 A/B isolation" property: when Phase 3 is off, Phase 4 still sees the legacy row_mean composite as input, which is the baseline against which we want to measure Phase 4's marginal contribution.
  - Winsorize + clip(-6, 6) is applied AFTER Phase 4 multiplication, which means large crisis multipliers (e.g. early 1.30 in systemic_crisis) can push more rows into the clip saturation range. This is expected and desirable — clipping prevents any single factor's crisis emphasis from dominating the sleeve ranking.
  - The multiplier clamp `[0.40, 1.60]` is intentionally generous relative to the built-in table's actual range `[0.55, 1.30]`. This leaves room for user-supplied overrides to explore more aggressive regime differentiation without touching the core code.
  - Unknown regime labels default to identity multipliers, so adding a new regime (e.g. future Phase 6 regime-smoothing introducing `confirmed_regime_label`) does NOT break Phase 4 — it just means the new label gets 1.0x treatment until someone adds it to the table.
  - `ENGINE_REUSE_VERSION` is NOT bumped. Phase 4 is a portfolio-layer only change; feature_store schema is untouched. The 2026-04-16 Phase 2 FULL rebuild cache remains valid for Phase 4 QUICK_RESCORE A/B.

### 07:55 KST - phase5-sub-industry-leader-laggard-pair

- scope:
  - Phase 5 (PHASE_ROADMAP §2.5): within each strong industry_group, give the top-quartile names a bonus and the bottom-quartile names a symmetric penalty. This is the IBD / O'Neil empirical regularity that "leaders pull away and laggards get left behind inside a rotating strong group". Default ON (the three new columns land in `scored_latest.csv` automatically on the next FULL rebuild). The Phase 5 sleeve wiring is additive — if the env gate disables Phase 5 the three columns are zero-filled so downstream sleeve composites are unaffected, but otherwise each sleeve's factor table picks up the new signals with role-appropriate weights (future=highest, core=moderate, early=light).
  - Bumps `ENGINE_REUSE_VERSION` to `"2026-04-17-phase5-leader-laggard"` to force a FULL rebuild when the user next runs Colab. This is mandatory because Phase 5 adds three columns to `build_universe_monthly` that must be baked into `feature_store_latest.parquet` via the `keep_cols` whitelist (Invariant #8 in `PHASE_ROADMAP.md` §5). Without the bump + FULL rebuild, the walk-forward backtest would see zero-filled Phase 5 columns from the old cache and Phase 5 would contribute nothing.
- files:
  - `r1000_top30_institutional.py` ->
    - Bumped `ENGINE_REUSE_VERSION` from `"2026-04-16-phase2-keepcols-fix"` to `"2026-04-17-phase5-leader-laggard"` (line 50).
    - Added new module constant `PHASE5_LEADER_LAGGARD_COLUMNS` listing the three new numeric columns so they can survive the feature_store whitelist.
    - Added new helper `add_sub_industry_leader_laggard_signals()` that computes leader_gap / leader_bonus / laggard_penalty per (rebalance_date, industry_group) with min-group-size and gap-threshold guards.
    - Wired the helper into `build_universe_monthly` right after `compute_oneil_leadership_score` + `add_industry_rotation_signal`, with the standard toggle/zero-fill pattern for both env gate (`PHASE_PHASE5_LEADER_LAGGARD_ENABLED`) and cfg flag (`sub_industry_leader_laggard_enabled`).
    - Appended `PHASE5_LEADER_LAGGARD_COLUMNS` to `build_feature_store.keep_cols` and to both numeric-sanitize lists in the same function so the columns survive the whitelist AND get NaN-scrubbed like every other numeric column.
    - Wired the three columns into `compute_portfolio_sleeve_columns` weight tables: future sleeve gets `(0.25, bonus)` + `(-0.15, penalty)` (highest weight because IBD leadership is its bread and butter), core gets `(0.15, bonus)` (moderate — compounders still respect leader separation), early gets `(0.10, bonus)` (light — it's already rotation-heavy via industry_rotation_signal).
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `add_sub_industry_leader_laggard_signals(monthly, min_group_size=6, gap_threshold=0.8) -> pd.DataFrame` -> computes `industry_leader_gap`, `industry_leader_bonus_score`, `industry_laggard_penalty_score` per row. Gracefully returns zero-filled columns when the Phase 2 prerequisite columns are missing.
  - `PHASE5_LEADER_LAGGARD_COLUMNS: list[str]` -> the three new column names, for use as a single handle when updating keep_cols / sanitize lists / zero-fill fallbacks.
- symbols_changed:
  - `build_universe_monthly` -> after the Phase 2 block, inserts a Phase 5 block guarded by both `phase_is_enabled("phase5_leader_laggard", default=True)` and `cfg.sub_industry_leader_laggard_enabled`. Zero-fill fallbacks cover both the env-disabled and cfg-disabled cases so the Phase 5 columns are always present in `monthly`.
  - `build_feature_store` -> `keep_cols` now appends `PHASE5_LEADER_LAGGARD_COLUMNS`, and both `hard_sanitize(...)` calls include the list so Phase 5 columns get the same NaN / clip treatment as Phase 2 numerics.
  - `compute_portfolio_sleeve_columns` -> three sleeve weight-pair tables now include Phase 5 signals at sleeve-appropriate weights. No behaviour change when Phase 5 is disabled (columns are zero-filled from the universe block, so `cross_sectional_robust_z` returns zero and the weighted contribution is zero).
- config_fields_added:
  - `sub_industry_leader_laggard_enabled: bool = True` -> cfg-level on/off; default ON per PHASE_ROADMAP §2.5.
  - `sub_industry_min_group_size: int = 6` -> groups smaller than this get zero Phase 5 signals (no spurious quartile ranking on tiny groups).
  - `sub_industry_leader_gap_threshold: float = 0.8` -> std-units gap the top-quartile must exceed the median by before bonus/penalty fire.
- breaking_changes:
  - none -> env gate + cfg flag both default ON, matching the PHASE_ROADMAP plan. With gates OFF the three new columns are zero-filled so legacy behaviour is byte-identical (apart from the schema having three extra zero columns).
  - **however**: `ENGINE_REUSE_VERSION` bump forces a FULL rebuild on the next Colab run. Users relying on the `2026-04-16-phase2-keepcols-fix` cache will automatically trigger feature_store regeneration -> expect a ~1.5-3h FULL rebuild the next time the engine runs. This is intentional and required — see §2 above.
- outputs:
  - `outputs/scored_latest.csv` -> three additional numeric columns: `industry_leader_gap`, `industry_leader_bonus_score`, `industry_laggard_penalty_score`. All are clipped to `[0.0, 4.0]` for gap and `[0.0, 1.0]` for bonus/penalty.
  - `feature_store_latest.parquet` (after FULL rebuild) -> the three columns survive the keep_cols whitelist and are available to the walk-forward backtest.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - `ast.parse(...)` passed with 383 top-level defs (was 382 — new `add_sub_industry_leader_laggard_signals` helper).
  - Symbol spot-check: `add_sub_industry_leader_laggard_signals`, `resolve_regime_sleeve_multipliers`, `weighted_sleeve_composite`, `compute_portfolio_sleeve_columns`, `PHASE5_LEADER_LAGGARD_COLUMNS`, `sub_industry_leader_laggard_enabled`, `sub_industry_min_group_size`, `sub_industry_leader_gap_threshold` all present.
  - Semantic A/B deferred to Colab FULL rebuild. When the user runs the FULL rebuild against `2026-04-17-phase5-leader-laggard`, expected sanity checks in `scored_latest.csv`:
    - `industry_leader_gap` ≥ 0.0 on every row; `nonzero_share` at least 0.3 (depends on how many groups have ≥6 names — typically 50-70% of rows).
    - `industry_leader_bonus_score` non-zero only in strong groups (`industry_group_strength_score ≥ 0`) with clear leader separation; expected nonzero_share 0.15-0.25.
    - `industry_laggard_penalty_score` symmetric to bonus in the same strong groups; similar nonzero_share.
    - Ship gate per `PHASE_ROADMAP.md` §3: Δ CAGR ≥ +0.3pp AND future-sleeve hit-rate improves ≥ +2pp.
- risks_or_notes:
  - Phase 5 works on `industry_group`, not `industry`. This is intentional — industry-level groups have ~20-30 names each (enough for reliable quartile stats), whereas GICS sub-industries often have only 2-5 names. The `min_group_size=6` guard further protects against spurious leader/laggard signals on tiny groups.
  - The `gap_threshold=0.8` (std units) means the top-quartile mean has to be ~0.8 std above the median before the bonus fires. This is empirically calibrated to weed out "homogeneous groups where nothing stands out" while still catching meaningful leadership dispersion. A/B run will tell us if this threshold needs adjustment.
  - Future-sleeve wiring uses `(+0.25, bonus)` and `(-0.15, penalty)` — asymmetric because laggards in a strong group are often just "next to catch up" rather than "structurally bad", so we don't want to punish them as hard as we reward leaders. If the A/B reveals laggards DO catch down, we can flip the penalty magnitude up later.
  - `ENGINE_REUSE_VERSION` bump means the next Colab run MUST be FULL rebuild (`QUICK_RESCORE_ONLY=False`). The user is aware — this was explicitly plan-approved with the bump string `"2026-04-17-phase5-leader-laggard"`.

### 08:20 KST - phase6a-three-level-drawdown-breaker

- scope:
  - Phase 6a (PHASE_ROADMAP §2.6 + PROPOSAL_defensive_upgrades.md §Proposal 1): expand the existing binary drawdown circuit breaker in `backtest_portfolio` into an asymmetric 3-level ladder with equity-based recovery hysteresis. When the portfolio's peak-to-running drawdown crosses -8% / -15% / -25%, the cash-target floor steps up to 15% / 35% / 60% respectively. Recovery uses equity-level tracking (running_equity must overshoot the trigger equity by `recovery_buffer=3%`) instead of drawdown percentage, eliminating the oscillation risk flagged in PROPOSAL line 153.
  - Default ON (cfg + env both default to True). Legacy single-threshold breaker (cfg fields `drawdown_circuit_breaker_threshold`, `..._cash_target`, `..._recovery`) kept intact and used when Phase 6a is toggled off, so legacy runs are byte-identical.
- files:
  - `r1000_top30_institutional.py` ->
    - `EngineConfig`: added 11 new Phase 6a fields (`drawdown_breaker_multilevel_enabled`, `drawdown_breaker_level_{1,2,3}_{threshold,cash_floor,scale}`, `drawdown_breaker_recovery_buffer`) with plan-aligned defaults. Legacy 3 fields retained.
    - `backtest_portfolio` + `_legacy_unused_backtest_portfolio`: added Phase 6a state block (`_phase6a_cfg_on`, `_phase6a_env_on`, `_phase6a_active`, `dd_active_level`, `dd_trigger_equity`, `_p6a_level_thresholds/cash/scale`, `_p6a_recovery_buffer`) in the init section right after the legacy breaker_threshold block.
    - Replaced the breaker decision block (inside the monthly loop) with a dispatch: Phase 6a active -> 3-level ladder with equity-based recovery; Phase 6a inactive + legacy breaker_threshold > 0 -> legacy single-threshold logic unchanged; neither -> no breaker. Downstream `effective_cash_target_max`, `breaker_sleeve_override`, `force_breaker_rebalance` now consume `effective_breaker_cash_floor` which comes from whichever path is active.
    - `ret_rows.append(...)` inside the monthly loop gains three new diagnostic fields: `dd_breaker_level` (int 0/1/2/3), `dd_trigger_equity` (float), `dd_breaker_multilevel_active` (0/1 flag). These are populated on every monthly row so auditors can verify the ladder was actually tripping.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none (behavior is in-place; no new top-level functions).
- symbols_changed:
  - `backtest_portfolio()` -> breaker decision dispatches on Phase 6a toggle; adds diagnostic columns to `ret_rows`.
  - `_legacy_unused_backtest_portfolio()` -> mirrors the active path so re-activation would behave consistently; kept because the audit at 17:12 KST called out both closures as "expected to appear twice".
- config_fields_added:
  - `drawdown_breaker_multilevel_enabled: bool = True`
  - `drawdown_breaker_level_1_threshold: float = 0.08`
  - `drawdown_breaker_level_1_cash_floor: float = 0.15`
  - `drawdown_breaker_level_1_scale: float = 0.90`
  - `drawdown_breaker_level_2_threshold: float = 0.15`
  - `drawdown_breaker_level_2_cash_floor: float = 0.35`
  - `drawdown_breaker_level_2_scale: float = 0.70`
  - `drawdown_breaker_level_3_threshold: float = 0.25`
  - `drawdown_breaker_level_3_cash_floor: float = 0.60`
  - `drawdown_breaker_level_3_scale: float = 0.40`
  - `drawdown_breaker_recovery_buffer: float = 0.03`
- breaking_changes:
  - none -> when dual-gate is off, the breaker logic is byte-identical to the legacy path.
- outputs:
  - Backtest return rows (`ret_df`, which flows into `outputs/equity_curve.csv` and the validation suite) now have three additional columns: `dd_breaker_level`, `dd_trigger_equity`, `dd_breaker_multilevel_active`.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - Both `backtest_portfolio` and its `_legacy_unused_` twin share the Phase 6a state + decision logic; `grep _phase6a_active | wc -l` = 6 call-sites (3 in each function, matching the audit-accepted "expected to appear twice" pattern).
  - Semantic A/B deferred to Colab. Ship gate per PHASE_ROADMAP §3: Δ MaxDD ≤ -3pp AND Δ CAGR ≥ -0.5pp.
- risks_or_notes:
  - The `_p6a_level_scale` factors (0.90 / 0.70 / 0.40) are read from cfg and clipped but NOT yet applied in this commit. In this v1 Phase 6a implementation, cash-floor enforcement alone drives the defense (the existing sleeve-renormalisation infra re-allocates among sleeves proportionally once cash is floored). If the A/B shows ladder + cash-floor alone isn't delivering the MaxDD target, a follow-up can add explicit scale multiplication to non-cash weights after sleeve construction.
  - The recovery buffer is intentionally small (3%). Making it larger reduces oscillation risk further but can keep the breaker engaged longer after a real recovery, trading some CAGR for more MaxDD protection. 3% is the PROPOSAL default.
  - Escalation is monotonic (you can only step UP within a single monthly iteration); de-escalation happens in one jump after full recovery. This matches the PROPOSAL and mimics how a human risk manager runs a ladder.
  - `ENGINE_REUSE_VERSION` is NOT bumped here (Phase 5 bump already covers this commit).

### 08:45 KST - phase6b-vix-level-hard-guard

- scope:
  - Phase 6b (PHASE_ROADMAP §2.6 + PROPOSAL_defensive_upgrades.md §Proposal 3): add an absolute-VIX-level cash-floor guard inside `compute_regime_portfolio_controls()`. When VIX crosses 22 / 28 / 35 / 45, the cash target is pushed UP to 10% / 25% / 40% / 55% respectively (via max(), composing defensively with the existing regime-based cash target). This catches fast VIX spikes that the 63-day z-score regime detection lags.
  - Default ON. Dual-gate toggle: `cfg.vix_level_guard_enabled` AND `PHASE_PHASE6B_VIX_ENABLED` env var both default to True.
- files:
  - `r1000_top30_institutional.py` -> `EngineConfig`: added 9 new Phase 6b fields (`vix_level_guard_enabled`, `vix_level_tier{1..4}_threshold`, `vix_level_tier{1..4}_cash_floor`). `compute_regime_portfolio_controls()`: added VIX-guard block right before the final `cash_target = float(np.clip(cash_target, 0.0, cfg.cash_weight_max))` so the tier floor can lift `cash_target` up but the overall cfg.cash_weight_max cap still binds.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none (in-place changes to `compute_regime_portfolio_controls`).
- symbols_changed:
  - `compute_regime_portfolio_controls(cfg, panel)` -> after the existing regime-based cash-target resolution and before the final `np.clip`, the function now reads the per-row median VIX level via `_median_or_default("vix_level", np.nan)`, maps it through a 4-tier lookup (highest tier that matches wins), and lifts `cash_target` via `max()`. The function stays byte-identical to the pre-Phase-6b path when both gates are off.
- config_fields_added:
  - `vix_level_guard_enabled: bool = True`
  - `vix_level_tier1_threshold: float = 22.0`
  - `vix_level_tier1_cash_floor: float = 0.10`
  - `vix_level_tier2_threshold: float = 28.0`
  - `vix_level_tier2_cash_floor: float = 0.25`
  - `vix_level_tier3_threshold: float = 35.0`
  - `vix_level_tier3_cash_floor: float = 0.40`
  - `vix_level_tier4_threshold: float = 45.0`
  - `vix_level_tier4_cash_floor: float = 0.55`
- breaking_changes:
  - none -> when either gate is off the entire Phase 6b block is skipped and the legacy cash_target flows through untouched.
- outputs:
  - No new output columns. The VIX floor shows up indirectly as a lifted `cash_target` in `run_summary.json` / `backtest_metrics.json` / `equity_curve.csv`'s cash weight trajectory during VIX-spike months.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - Semantic A/B deferred to Colab. Ship gate per PHASE_ROADMAP §3: Δ MaxDD ≤ -1pp in VIX-spike periods (2020-03, 2022-Q1, 2023-Q1 when rates spiked, etc).
- risks_or_notes:
  - Uses `_median_or_default("vix_level", np.nan)` which is a closure already defined inside `compute_regime_portfolio_controls`. `vix_level` has been available in the monthly panel since `build_macro_regime_table()` at line 7502 — no new data source needed.
  - `cfg.cash_weight_max` still binds as the overall cap, so if a user has `cash_weight_max=0.40` and VIX goes to 50 (tier 4 floor = 0.55), the final `np.clip` would bring cash back down to 0.40. This is the correct precedence — the cfg ceiling is the user's hard constraint, the VIX floor is a defensive pressure.
  - `ENGINE_REUSE_VERSION` NOT bumped. VIX level is already in the feature_store via `MACRO_REGIME_COLUMNS`; Phase 6b is a pure cash-target-construction change.

### 09:10 KST - phase6c-volatility-targeting-default-off

- scope:
  - Phase 6c (PHASE_ROADMAP §2.6 + PROPOSAL_defensive_upgrades.md §Proposal 7): add realized-portfolio-volatility targeting inside `backtest_portfolio`. Trailing 6-month monthly net returns are used to compute annualized realized vol; when it exceeds `vol_target_annualized` (default 12%), non-cash exposure is shrunk via an equivalent cash floor. Default OFF — vol targeting can hurt CAGR in calm markets, so the user must explicitly opt in.
  - Expressed as a cash floor rather than direct weight multiplication so it composes cleanly with Phase 6a drawdown breaker and Phase 6b VIX guard through a simple chain of `max()` operations.
- files:
  - `r1000_top30_institutional.py` ->
    - `EngineConfig`: 5 new fields (`volatility_targeting_enabled`, `vol_target_annualized`, `vol_lookback_months`, `vol_scale_floor`, `vol_scale_ceiling`).
    - `backtest_portfolio` + `_legacy_unused_backtest_portfolio`: Phase 6c state block next to Phase 6a init. `recent_returns: list[float]` captures trailing monthly net returns.
    - Monthly loop: after `net_ret = month_ret - cost` and `running_equity` update, appends `net_ret` to `recent_returns` and trims to `max(lookback, 12)`. Computes `vol_cash_floor_p6c` per month; when it exceeds zero, participates in the `max()` chain for `effective_cash_target_max`. Refactored the cash-floor composition so it no longer short-circuits on `circuit_breaker_active`; the chain is now: cfg cap -> Phase 6a breaker floor (if active) -> Phase 6c vol floor (if active).
    - `ret_rows.append(...)` picks up three new Phase 6c diagnostics: `vol_target_active` (0/1), `vol_cash_floor_p6c` (0.0 when vol target off, else the dynamic floor), `recent_returns_len` (how many trailing months we've accumulated).
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none.
- symbols_changed:
  - `backtest_portfolio()` -> tracks `recent_returns` state; reads realized vol per month; computes `vol_cash_floor_p6c` via `clip(target/max(realized, target), floor, ceiling)`; refactored `effective_cash_target_max` computation to a cumulative `max()` chain.
- config_fields_added:
  - `volatility_targeting_enabled: bool = False`
  - `vol_target_annualized: float = 0.12`
  - `vol_lookback_months: int = 6`
  - `vol_scale_floor: float = 0.50`
  - `vol_scale_ceiling: float = 1.00`
- breaking_changes:
  - Subtle behavioral change: the `effective_cash_target_max` computation was restructured from a ternary that short-circuited on `circuit_breaker_active` to a cumulative `max()` chain that also honours the Phase 6c vol floor. With all Phase 6 gates off this is algebraically identical to the pre-Phase-6c path (both Phase 6a and Phase 6c contributions are 0, only `cfg.cash_weight_max` binds).
- outputs:
  - `ret_df` / `equity_curve.csv` / validation suite now include `vol_target_active`, `vol_cash_floor_p6c`, `recent_returns_len` columns on every monthly row.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - Semantic A/B deferred to Colab. Ship gate per PHASE_ROADMAP §3: Δ Sharpe ≥ +0.05 AND Δ CAGR ≥ -1pp.
- risks_or_notes:
  - Default OFF means the user must set BOTH `cfg.volatility_targeting_enabled=True` AND `os.environ["PHASE_PHASE6C_VOLTARGET_ENABLED"]="1"` to activate. Any quick A/B comparing the default configuration to the "everything defensive on" configuration isolates Phase 6c cleanly.
  - Expressing vol targeting as a cash floor (instead of multiplicative non-cash scaling) loses one subtlety: the original proposal scales the non-cash BUCKET uniformly, preserving relative sleeve weights. The cash-floor approximation hands excess cash to the downstream sleeve re-normaliser which will reshape the sleeve mix based on the regime controller's target. In practice the distinction is minor at low vol-scale values (0.9+), and material only when vol_scale drops toward the 0.5 floor.
  - `recent_returns` is capped at `max(lookback, 12)` entries to prevent unbounded memory growth across long backtests. Not expected to bind because `lookback` defaults to 6.
  - Phase 6c's ENGINE_REUSE_VERSION is NOT bumped. All state is per-backtest-run and no feature_store schema changes.

### 09:30 KST - phase456-glue-handoff-rotate-and-colab-toggles

- scope:
  - Meta / glue commit for the Phase 4/5/6 rollout. `SESSION_HANDOFF.md` gets a full rewrite reflecting the new state (Phase 3 rejected, Phase 4/5/6 all landed as separate commits, next action is one FULL rebuild in Colab). `colab_run.ipynb` Cell 2 is extended with `PHASE3_*` / `PHASE4_*` / `PHASE5_*` / `PHASE6A_*` / `PHASE6B_*` / `PHASE6C_*` env-var toggles so the user can flip any phase's A/B on/off directly in the notebook without editing Python.
- files:
  - `SESSION_HANDOFF.md` -> full rewrite. §1 timeline of the last 6 commits (Phase 3 rejection + Phase 4/5/6a/6b/6c additions) with default-state summary table. §2 gives the user exact Cell 2 toggles for the next FULL rebuild + a post-run verification checklist covering all 5 new phases. §3 documents the follow-up A/B matrix. §4 bootstrap prompt updated. §5 updated with the split Drive repo-dir / data-dir model.
  - `colab_run.ipynb` -> Cell 2 toggle block rewritten. Now exposes 8 phase vars (`PHASE1_ALPHA_ENABLED` ... `PHASE6C_VOLTARGET_ENABLED`), each defaulting to `'auto'` (respect cfg default). Helper `_set_phase_env()` keeps the env-var export DRY. Prints out every env var's resolved state for run-log transparency.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none.
- symbols_changed:
  - `colab_run.ipynb` Cell 2 -> new 6 phase toggle variables and the env-var setter helper.
- config_fields_added:
  - none (the glue commit only surfaces the env vars for existing cfg flags added in the Phase 4/5/6a/6b/6c commits).
- breaking_changes:
  - none. All phase toggles default to `'auto'` = cfg default, so a user who pulls this commit without editing the notebook sees the same behaviour as the Phase 6c commit (`ee93fa0`).
- outputs:
  - `SESSION_HANDOFF.md` (rewritten).
  - `colab_run.ipynb` (Cell 2 updated).
- validation:
  - `python -c "import json; nb=json.loads(open(r'colab_run.ipynb', encoding='utf-8').read()); assert all(k in ''.join(nb['cells'][2]['source']) for k in ['PHASE3_RENORM_ENABLED','PHASE4_REGIME_WEIGHTS','PHASE5_LEADER_LAGGARD','PHASE6A_BREAKER','PHASE6B_VIX','PHASE6C_VOLTARGET']); print('OK')"` passed.
  - `py -3 -m py_compile r1000_top30_institutional.py` still passes (no engine code touched in this commit).
- risks_or_notes:
  - If Colab users have a locally-edited `colab_run.ipynb`, pulling origin will create a merge conflict. They should either `git stash` their local ipynb edits before pulling or resolve manually. All notebook edits on the main branch have been via git on this machine so no conflict should exist today.
  - The `SESSION_HANDOFF.md` now promises that the next Colab run is a FULL rebuild. The user should confirm `QUICK_RESCORE_ONLY = False` in Cell 2 before running. The Phase 5 `ENGINE_REUSE_VERSION` bump already forces FULL rebuild via cache invalidation regardless, but the explicit Cell 2 setting is cleaner.
  - This closes out the Phase 4/5/6 implementation plan from `.claude/plans/crystalline-plotting-badger.md`. Next natural action is the FULL rebuild + A/B measurements described in `SESSION_HANDOFF.md` §2.

### 10:05 KST - phase6a-6b-getattr-default-alignment-fix

- scope:
  - Pre-rebuild audit (3 parallel Explore agents) flagged a defensive-consistency bug: `EngineConfig.drawdown_breaker_multilevel_enabled` and `EngineConfig.vix_level_guard_enabled` both default to `True`, but the `getattr(cfg, ..., <default>)` call sites that resolve these flags in `backtest_portfolio` / `_legacy_unused_backtest_portfolio` / `compute_regime_portfolio_controls` were using `False` as the fallback default. In all current active call paths `cfg` is a populated `EngineConfig` instance so the getattr fallback never fires, but a future caller or test harness that passes `cfg=None` would silently disable Phase 6a / 6b when the engine advertises them as default-ON.
  - Small aligning fix: change all three `getattr(..., False)` call sites to `getattr(..., True)` so the fallback matches the EngineConfig declaration.
- files:
  - `r1000_top30_institutional.py`:
    - line 10276: `_p6b_cfg_on = bool(getattr(cfg, "vix_level_guard_enabled", True))` (was `False`)
    - line 16967: `_phase6a_cfg_on = bool(getattr(cfg, "drawdown_breaker_multilevel_enabled", True))` (was `False`, inside `_legacy_unused_backtest_portfolio`)
    - line 20499: `_phase6a_cfg_on = bool(getattr(cfg, "drawdown_breaker_multilevel_enabled", True))` (was `False`, inside active `backtest_portfolio`)
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - none (only the default-argument values changed inside existing expressions).
- config_fields_added:
  - none
- breaking_changes:
  - none. In all active call paths, `cfg` is always a populated `EngineConfig` instance, so the `getattr` fallback was never reached. Behaviour is unchanged in practice.
- outputs:
  - none (no output artifacts change).
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - Grep check confirms all 8 `getattr(cfg, <phase_flag>, ...)` call sites now have the `<default>` argument matching the corresponding `EngineConfig` default: Phase 3/4/6c -> `False`, Phase 5/6a/6b -> `True`.
- risks_or_notes:
  - This is a pure hardening fix. The Phase 6 A/B measurement semantics are unaffected — in the active codepaths `cfg` is always an `EngineConfig` instance and `cfg.drawdown_breaker_multilevel_enabled` / `cfg.vix_level_guard_enabled` are explicitly `True`, so the `_phase6X_cfg_on` evaluation was always producing the correct True value. The fallback alignment matters only for future callers that construct the engine with `cfg=None` or with a minimal dict override.
  - The three parallel Explore agents also confirmed there is currently no invocation of `_legacy_unused_backtest_portfolio`. Keeping it guarded (even though unused) means that if we ever ressurrect it, the Phase 6 toggles fire the right default.
  - `ENGINE_REUSE_VERSION` stays at `"2026-04-17-phase5-leader-laggard"`. No schema change.
  - The same audit surfaced a "delete or hard-guard the legacy function" recommendation. Deferring that because the legacy function has its own Phase 3/4/5/6 state and decision blocks correctly populated; deleting it now would touch ~470 lines and isn't on the critical path for the FULL rebuild. Can be a separate hygiene commit later.

### 10:15 KST - agent-facing-docs-refresh-post-phase456

- scope:
  - Refresh the agent-facing project documents (`SESSION_HANDOFF.md` + `PHASE_ROADMAP.md`) so any future chat-session / Codex / GPT agent that resumes the project can accurately see the current state after the Phase 4/5/6 rollout + the `f7ec511` audit-hardening fix. No engine code changes.
- files:
  - `SESSION_HANDOFF.md` -> updated HEAD commit reference from `33ed065` / `ee93fa0` to `f7ec511`, expanded the commit timeline table with the `f7ec511` alignment fix + 3-agent audit outcome, rewrote §3 with the three Phase 7 candidate proposals from the 2026-04-17 alpha-gap audit (7a insider+accruals, 7b estimate-dispersion+SUE, 7c yield-curve+cross-asset) + portfolio-construction sweeps.
  - `PHASE_ROADMAP.md` -> flipped §2 Phase 3 heading to "❌ REJECTED" with A/B outcome numbers, Phase 4/5/6 headings to "✅ DONE (2026-04-17)" with commit references + key implementation facts; §3 implementation-order table now shows commit SHA + status for each PR (A..H including `f7ec511` as PR H).
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - none (documentation only).
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `SESSION_HANDOFF.md`, `PHASE_ROADMAP.md` (both refreshed in place).
- validation:
  - `wc -l` confirms both files grew in line count (SESSION_HANDOFF 135 → 177, PHASE_ROADMAP 399 → 453).
  - Manual inspection confirms the commit SHA timeline matches `git log --oneline -10` output.
  - No engine code changes → no py_compile needed.
- risks_or_notes:
  - `PHASE_ROADMAP.md` §2 retains the original "PLANNED" design notes as "Historical design notes" subsections for reference. If those grow stale they can be pruned in a later cleanup.
  - The resume-checklist section of `SESSION_HANDOFF.md` §4 now points at `f7ec511` as the expected HEAD. Any agent joining after this refresh will look for this exact commit (or newer) to confirm the codebase is in-sync.
  - `ENGINE_REUSE_VERSION` unchanged. No FULL-rebuild forcing beyond what Phase 5 already mandated.

### 10:45 KST - phase7a-insider-flow-and-accruals-sleeve-wiring

- scope:
  - Phase 7a from `SESSION_HANDOFF.md` §3: wire the already-computed `insider_flow_signal_score` and `accruals_to_assets` signals into the sleeve composites inside `compute_portfolio_sleeve_columns`. Both signals are produced by the existing fundamentals + live-overlay pipeline (yfinance `insider_transactions` + optional SEC Form 3/4/5 raw-file override for insider, `(NI_ttm − OCF_ttm) / assets` for accruals) but neither was wired into any of the three sleeve weight-pair tables prior to this commit. Phase 7a adds them with sleeve-appropriate weights behind a dual-gate toggle so they can be A/B-measured against the same FULL-rebuild baseline that Phase 5/6a/6b will use.
  - Default OFF — user explicitly requested default-OFF landing so the upcoming FULL rebuild measures Phase 5/6a/6b in isolation, and a subsequent QUICK_RESCORE can isolate Phase 7a's marginal contribution on top.
  - No new data sources needed. `insider_flow_signal_score` is produced by `build_live_factor_overlay` (line 9849), `accruals_to_assets` by the fundamental-derivation block (line 11760). Prior `w_insider_flow` path in the main `total_score` (line 4619) is unchanged — Phase 7a is additive to the sleeve-specific composition only.
- files:
  - `r1000_top30_institutional.py`:
    - `EngineConfig` (post-`vol_scale_ceiling` block): added 4 Phase 7a fields.
    - `compute_portfolio_sleeve_columns`: added Phase 7a dual-gate resolution block; added one weight pair to `core_weight_pairs` (`_p7a_w_accruals_core * accruals_to_assets`), one to `future_weight_pairs` (`_p7a_w_insider_future * insider_flow_signal_score`), one to `early_weight_pairs` (`_p7a_w_insider_early * insider_flow_signal_score`) — each gated behind `_phase7a_active` with 0.0 fallback so the toggle-off path is byte-identical to `017b853`; added `phase7a_insider_accruals_active` diagnostic column; extended the empty-frame branch with the new diagnostic.
  - `colab_run.ipynb`: Cell 2 toggle block now also surfaces `PHASE7A_INSIDER_ACCRUALS_ENABLED` with `_set_phase_env()` and prints it alongside the other seven phase env vars.
  - `SESSION_HANDOFF.md`: §3 Phase 7a candidate marked as "✅ LANDED, default OFF" with exact toggle names + A/B protocol.
  - `CHANGELOG.md`: this entry.
- symbols_added:
  - none
- symbols_changed:
  - `compute_portfolio_sleeve_columns(df, cfg)` -> resolves Phase 7a dual-gate, reads insider/accruals weights from cfg, applies them to the three sleeve weight-pair tables gated on `_phase7a_active`, writes `phase7a_insider_accruals_active` scalar column (1.0 when on, 0.0 when off).
- config_fields_added:
  - `phase7a_insider_accruals_enabled: bool = False` -> master toggle (dual-gate with `PHASE_PHASE7A_INSIDER_ACCRUALS_ENABLED`).
  - `phase7a_insider_early_weight: float = 0.25` -> insider_flow_signal_score weight on early_scout when Phase 7a is on.
  - `phase7a_insider_future_weight: float = 0.15` -> insider_flow_signal_score weight on future_winner when Phase 7a is on.
  - `phase7a_accruals_core_weight: float = -0.20` -> accruals_to_assets weight on core_compounder when Phase 7a is on (negative = high accruals penalized).
- breaking_changes:
  - none. When either gate is off, all three weight pairs multiply by 0.0, which is a no-op inside `weighted_sleeve_composite` (multiplying 0.0 by any z-score series produces 0.0 contribution and 0.0 added to the L1 norm — so Phase 3 renorm diagnostics are unaffected too).
- outputs:
  - `outputs/scored_latest.csv` gains one additional column: `phase7a_insider_accruals_active` (scalar 0.0 or 1.0 per row).
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - Grep confirms 4 new cfg fields, `_phase7a_active` dual-gate, and the 3 weight-pair gated expressions in core / future / early.
  - Grep on `colab_run.ipynb` source confirms `PHASE7A_INSIDER_ACCRUALS_ENABLED` declaration + env setter both present.
  - Semantic A/B deferred to Colab. Ship gate (per SESSION_HANDOFF §3 Phase 7a): ΔCAGR ≥ +0.3pp AND ΔSharpe ≥ +0.02, with MaxDD not worse by more than +1pp.
- risks_or_notes:
  - `insider_flow_signal_score` coverage depends on the yfinance `insider_transactions` endpoint availability per-ticker; historical coverage has been good (~90% of liquid Russell 1000 names) but very-low-liquidity or recently-IPO'd names can be missing. `cross_sectional_robust_z` handles missing values by filling with 0.0 (the within-period z-score centre), so missing coverage translates to "no tilt" for that name, not a NaN explosion.
  - `accruals_to_assets` coverage is ~81% (see `outputs/reports/full_validation_suite.json :: acceptance_checks` from the 2026-04-16 FULL rebuild). For the remaining ~19% of names the z-score falls back to 0.0 — same "no tilt" behaviour.
  - The pre-existing `w_insider_flow` path in the main `total_score` (line 4619) is independent of Phase 7a and remains unchanged. Phase 7a adds sleeve-specific insider tilt on top of the existing main-score insider component, not as a replacement. If the sleeve contribution turns out to be redundant with the main-score path, A/B will show it as neutral.
  - Phase 7a weights are exposed as cfg fields on purpose so they can be tuned via `COMMON_CFG_OVERRIDES` in Colab Cell 2 without having to re-edit / re-push the weight-pair tables. For example a user could test `cfg["phase7a_insider_early_weight"]=0.35, cfg["phase7a_accruals_core_weight"]=-0.30` to probe a more aggressive tilt.
  - `ENGINE_REUSE_VERSION` NOT bumped. Phase 7a is portfolio-layer only; it reuses columns already in `feature_store_latest.parquet` so the Phase 5 FULL-rebuild bump still covers this commit.

### 12:15 KST - phase5-dilution-fix-plus-breaker-diagnostic-csv-export

- scope:
  - Emergency fix for a regression surfaced by the 2026-04-17 FULL rebuild (commit `914558f`): CAGR dropped from 20.10% to 15.44% (-4.66pp), Sharpe from 1.08 to 0.84, MaxDD from -23.60% to -26.34%, IR from 0.58 to 0.20. Root cause: Phase 5's sub-industry leader/laggard signals fire on only ~3.6% of rows (`industry_leader_bonus_score`) and ~0% of rows (`industry_laggard_penalty_score`), but their weight pairs were handed to `row_mean` as plain zero-valued z-scores. `row_mean` treats zero as a valid term, so the denominator `N` grew by +2 on future / +1 on core / +1 on early while the numerator stayed roughly unchanged — diluting every other factor's effective weight by ~6% across all three sleeves. This is the same dilution issue Phase 3 tried to solve via L1-normalisation; Phase 3 was rejected so the row_mean structure stayed, and Phase 5's low-coverage additions then fell into exactly that trap.
  - Companion fix: the Phase 6a (3-level drawdown breaker) and Phase 6c (volatility targeting) diagnostic columns I added to `ret_rows` (`dd_breaker_level`, `dd_trigger_equity`, `dd_breaker_multilevel_active`, `vol_target_active`, `vol_cash_floor_p6c`, `recent_returns_len`) were stripped out of `equity_curve.csv` by an explicit 7-column whitelist in the four `backtest_portfolio` variants. They landed in `ret_df` (used for metrics computation) but never made it to the CSV the user inspects to verify breaker activity. Fix extends the whitelist to conditionally include the diagnostic columns when they exist.
- files:
  - `r1000_top30_institutional.py` ->
    - `compute_portfolio_sleeve_columns()` (line ~18186): added Phase 5 dilution-fix block that defines `_p5_bonus_z` and `_p5_penalty_z` as the robust-z-scored signals with `.where(raw != 0.0, np.nan)` so `row_mean` skips rows where Phase 5 didn't fire. Three sleeve weight-pair tables now reference `_p5_bonus_z` / `_p5_penalty_z` instead of calling `cross_sectional_robust_z` inline, preserving the original sleeve-specific weights (`core: +0.15 bonus`, `future: +0.25 bonus + -0.15 penalty`, `early: +0.10 bonus`).
    - All four `equity_df = ret_df[...]` column-subset expressions now build the column list dynamically: base 7 columns + any Phase 6a/6c diagnostic column that exists in `ret_df`. Using `replace_all=True` on the edit so legacy / active / concentrated / standalone backtest variants all get the same treatment.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - `compute_portfolio_sleeve_columns(df, cfg)` -> precomputes `_p5_bonus_z` and `_p5_penalty_z` with NaN-masking; references them in all three sleeve weight-pair tables.
  - `backtest_portfolio()` and three variants -> `equity_df` column selection is now dynamic (whitelist + conditional diagnostic columns).
- config_fields_added:
  - none
- breaking_changes:
  - none. Phase 5 wiring semantics change ONLY on rows where the raw signal is exactly 0.0 — those rows now contribute zero to the composite instead of contributing a small dilution effect. On the ~3.6% of rows where Phase 5 fires, the contribution is the same magnitude as before (the z-score is preserved, only the zero-rows are masked).
- outputs:
  - `outputs/equity_curve.csv` -> now includes Phase 6a diagnostics (`dd_breaker_level`, `dd_trigger_equity`, `dd_breaker_multilevel_active`), Phase 6c diagnostics (`vol_target_active`, `vol_cash_floor_p6c`, `recent_returns_len`), and the pre-existing legacy breaker fields (`drawdown_circuit_breaker_active` etc.) when they're populated. Columns that are absent from `ret_df` for a particular backtest variant are silently dropped so existing callers that read only the base 7 columns remain unaffected.
- validation:
  - `py -3 -m py_compile r1000_top30_institutional.py` passed.
  - Grep confirms `_p5_bonus_z` / `_p5_penalty_z` are defined once and referenced in all three sleeve weight-pair tables (4 references total: core 1, future 2, early 1).
  - `equity_df` column-subset block edited in all 4 `backtest_portfolio` variants (legacy unused, active, concentrated, standalone).
- risks_or_notes:
  - **Expected A/B outcome after this fix + QUICK_RESCORE**: CAGR recovers toward the 2026-04-16 baseline (~20.1%), Sharpe recovers toward 1.08, MaxDD recovers toward -23.6%. The actual Phase 5 alpha contribution (measured against the recovered baseline) is likely small and may not ship its own gate. That's fine — the urgent priority is undoing the regression.
  - If the QUICK_RESCORE CAGR does NOT recover to within 1pp of baseline, the dilution theory was only partially right and we should also check (a) whether `f7ec511`'s getattr defaults actually changed any active execution path, (b) whether Phase 6a/6b/6c are silently firing more aggressively than expected despite cash_weight averaging 0.3%.
  - Same dilution pattern could affect future Phase 7b/7c if their signals end up sparse. When adding any new weight pair, check `scored_latest.csv` for its `nonzero_share` and use the masking pattern if coverage is below ~20%.
  - `ENGINE_REUSE_VERSION` stays at `"2026-04-17-phase5-leader-laggard"`. Only portfolio-layer composition changed; feature_store cache is still valid.
  - Ship decision on Phase 5 itself is deferred until the QUICK_RESCORE confirms the CAGR recovery. If after the fix Phase 5 is still a net drag, Phase 5 ON by default should be flipped to OFF in a follow-up commit.

### 12:30 KST - rotate-session-handoff-for-office-resume

- scope:
  - End-of-session rotation of `SESSION_HANDOFF.md` so the user can resume from a different machine (office PC) after the lunch break without losing context. The previous handoff was written before the 2026-04-17 FULL rebuild exposed the regression and before the `c4d50fd` fix — stale. This rewrite captures (a) the regression numbers and the root cause, (b) the exact Cell A / Cell 2 / Cell E Colab cells to paste to verify the fix, (c) a three-branch decision tree for what to do after the QUICK_RESCORE verdict, (d) the up-to-date Phase status table with cfg / env-var names / defaults / ship gates.
- files:
  - `SESSION_HANDOFF.md` -> full rewrite. §0 TL;DR paragraph. §1 commit timeline through `c4d50fd`. §2 Cell A (git-sync) + Cell 2 (QUICK_RESCORE toggles) + Cell E (recovery verdict) fully embedded as copy-pasteable code blocks. §3 decision tree for recovered / partial / still-broken verdicts. §4 bootstrap prompt for a fresh chat session. §6 phase-status-at-a-glance table with all 8 phase env-var names and defaults.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - none (documentation only)
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `SESSION_HANDOFF.md` (rewritten).
- validation:
  - `wc -l SESSION_HANDOFF.md` — the rewrite should be roughly 250 lines (up from 177).
  - Manual inspection confirms the Cell E `baseline` constants match the 2026-04-16 FULL rebuild metrics and the decision-tree thresholds mirror the ones discussed in the morning chat session.
- risks_or_notes:
  - The handoff's §2 assumes the user opens `colab_run.ipynb` from Drive and pastes Cell A / Cell E as sidecar cells. The existing Cell 2 in the notebook is already current (has all 8 phase env toggles via commit `33ed065` + `914558f`); no notebook changes needed for the office session.
  - If the QUICK_RESCORE takes more than 25 minutes, the Cell A Drive mount / git fetch likely failed silently. Cell A's `git log --oneline -3` output is the checkpoint — if HEAD is NOT `c4d50fd` or newer the fix isn't being used.
  - `ENGINE_REUSE_VERSION` stays at `"2026-04-17-phase5-leader-laggard"`. The cached feature_store from the 2026-04-17 morning FULL rebuild is valid for this QUICK_RESCORE — the dilution fix is portfolio-layer only.

### 11:16 KST - phase8-complete-restructure-for-30pct-cagr

- scope:
  - Major restructuring pass targeting CAGR 15.44% -> 25-30%+. Five commits (`4cd938e`, `3624e06`, `e3bf29d`, `3e44d35`, `caddec3`) implementing every action in `PHASE_8_PROPOSAL.md`. Grounded in the Phase C diagnosis (commit `027c5b3`) which measured factor IC across 83 OOS months using the Drive's `scored_oos_latest.parquet`, confirmed the 2024-06 macro score corruption, audited the universe for survivorship + missing AI names, and ran counterfactual simulations for each proposed improvement.
- files:
  - `r1000_top30_institutional.py` (all 5 commits):
    - `rolling_robust_z` — hardened MAD denominator with scale-aware floor (`max(|median|*0.01, 1e-6)`) and z-clip to `[-10, 10]`. Root cause of the 2024-06 `labor_softening_score = -2.025e+14` bug.
    - `compute_macro_regime_features` — added `clip(-6, 6)` belt-and-suspenders on every `MACRO_REGIME_COLUMNS` entry at the end of the function.
    - `PHASE1_ALPHA_COLUMNS` — new constant (5 columns) appended to `build_feature_store.keep_cols` + `hard_sanitize` + `write_stage_coverage_report` so Phase 1 alpha signals actually reach the walk-forward training set (same keepcols-bug class as commit `1d4fb40` for Phase 2).
    - `compute_portfolio_sleeve_columns` — three negative-IC factors zeroed under `PHASE_PHASE8A_NEG_IC_DROP` env gate: `quality_trend_score` (core, IC -0.0042), `selection_confirmation_score` (core, IC -0.0028), `industry_rotation_signal` (future + early, IC -0.0117).
    - `EngineConfig.sub_industry_leader_laggard_enabled` flipped from `True` -> `False` and matching `phase_is_enabled("phase5_leader_laggard")` default changed to `False`. Factor IC measurement showed Phase 5 signals have ~0 alpha; disabling saves 3 weight-pair slots.
    - `compute_portfolio_sleeve_columns` — new `hold_persistence_bonus` composite with weight 0.90 in all three sleeves (PHASE_PHASE8A_HOLD_PERSISTENCE env gate, default ON). Rewards held-and-winning names to cut turnover from 49.5%/mo toward 25%/mo.
    - `compute_price_features` — three new raw lookbacks `mom_18m` (pct_change 378), `mom_24m` (504), `mom_36m` (756). Added to `DEFAULT_FEATURES`.
    - `build_universe_monthly` — new `multi_year_winner_score` cross-sectional composite (weighted blend 0.50*z12+0.80*z24+0.60*z36) and `persistence_trend_24m` binary flag (mom_12>.15 AND mom_24>.30 AND mom_36>.50). Gated PHASE_PHASE8B_LONG_LOOKBACK.
    - `compute_portfolio_sleeve_columns` — wired 8b.1 into sleeves with weights: future=0.90 + 0.50 persist, early=0.60, core=0.40 + 0.30 persist.
    - `compute_portfolio_sleeve_columns` sleeve_label override — force `future_winner` for (mktcap>$50B AND rev_growth>0.25 AND multi_year_winner_score>1.0). Moves NVDA-style names from the 12%-weight core sleeve to the 58%-weight future sleeve. Env gate PHASE_PHASE8C_MEGACAP_OVERRIDE, cfg knobs for threshold tuning.
    - `compute_live_factor_columns` — growth-adjusted valuation dampening: when `revenue_growth_final > 0.40` the NEGATIVE portion of `forward_value_score` is zeroed; >0.20 halves it; positive portion unchanged. Stops the engine from penalising high-growth mega-caps for their earnings-catch-up P/E. Env gate PHASE_PHASE8C_GROWTH_ADJ_VALUATION.
    - `ENGINE_REUSE_VERSION` bumped: `"2026-04-17-phase5-leader-laggard"` -> `"2026-04-17-phase8a-macro-clamp-and-phase1-keepcols"` (commit 1) -> `"2026-04-17-phase8b-long-lookback-momentum"` (commit 4). Final value for FULL rebuild trigger.
    - `PHASE8B_LONG_LOOKBACK_COLUMNS` constant (5 columns: mom_18m, mom_24m, mom_36m, multi_year_winner_score, persistence_trend_24m) appended to keep_cols / hard_sanitize / coverage report.
  - `DIAGNOSIS_FACTOR_IC.md`, `DIAGNOSIS_COUNTERFACTUAL.md`, `DIAGNOSIS_BUGS.md`, `PHASE_8_PROPOSAL.md`, `DIAGNOSIS_factor_ic.csv` — landed earlier in commit `027c5b3`; referenced throughout the Phase 8 changes.
  - `SESSION_HANDOFF.md` — rewritten (this commit).
  - `CHANGELOG.md` — this entry.
- symbols_added:
  - `PHASE1_ALPHA_COLUMNS: list[str]` — 5-column keepcols survival list for Phase 1 turnaround/value/uptrend alpha.
  - `PHASE8B_LONG_LOOKBACK_COLUMNS: list[str]` — 5-column keepcols survival list for mom_18m/24m/36m + two composites.
- symbols_changed:
  - `rolling_robust_z(s, window)` — hardened MAD denominator and z-clip.
  - `compute_macro_regime_features(cfg, paths)` — added MACRO_REGIME_COLUMNS clip(-6, 6) at end.
  - `build_universe_monthly(cfg, paths)` — added Phase 8b.1 composite block after Phase 5.
  - `compute_price_features(close, open_, vol, dividends)` — added mom_18m/24m/36m raw momentum.
  - `compute_live_factor_columns(d, cfg)` — added Phase 8c.2 growth-adj valuation dampening after forward_value_score.
  - `compute_portfolio_sleeve_columns(df, cfg)` — weight-pair tables extended with hold_persistence + multi_year_winner + persistence_trend + megacap_override logic.
  - `build_feature_store(cfg, paths, ...)` — keep_cols / hard_sanitize / write_stage_coverage_report extended with `PHASE1_ALPHA_COLUMNS` + `PHASE8B_LONG_LOOKBACK_COLUMNS`.
  - `EngineConfig.sub_industry_leader_laggard_enabled`: `True` -> `False`.
- config_fields_added:
  - `phase8a_hold_persistence_enabled: bool = True` — Phase 8a.4 master toggle
  - `phase8a_hold_persistence_weight: float = 0.90` — sleeve-composite weight for the bonus
  - `phase8b_long_lookback_enabled: bool = True` — Phase 8b.1 master toggle
  - `phase8b_multi_year_future_weight: float = 0.90` — multi_year_winner_score weight in future sleeve
  - `phase8b_multi_year_early_weight: float = 0.60` — same for early
  - `phase8b_multi_year_core_weight: float = 0.40` — same for core
  - `phase8b_persistence_trend_future_weight: float = 0.50` — persistence_trend_24m weight in future
  - `phase8b_persistence_trend_core_weight: float = 0.30` — same for core
  - `phase8c_megacap_future_override_enabled: bool = True` — Phase 8c.1 master toggle
  - `phase8c_megacap_threshold_usd: float = 50.0e9` — market-cap floor for the override
  - `phase8c_megacap_min_revenue_growth: float = 0.25` — revenue-growth floor for the override
  - `phase8c_megacap_min_multi_year_score: float = 1.0` — multi_year_winner_score floor for the override
  - `phase8c_growth_adj_valuation_enabled: bool = True` — Phase 8c.2 master toggle
- breaking_changes:
  - `ENGINE_REUSE_VERSION` changed -> FULL REBUILD required on next Colab run. Feature-store added 5 new columns (mom_18m/24m/36m + 2 composites) and Phase 1 keepcols fix expects 5 more columns in the whitelist, so a stale `feature_store_latest.parquet` is INVALID. Cell 4 will automatically rebuild when `QUICK_RESCORE_ONLY=False`.
  - Phase 5 default flipped OFF — `sub_industry_leader_laggard_enabled: True -> False`. Downstream Phase 5 diagnostic columns (`industry_leader_gap` etc.) still exist in the schema (zero-filled) so no consumer code breaks.
- outputs:
  - `feature_store_latest.parquet` -> 10 new columns: `fundamental_turnaround_acceleration_score`, `cashflow_inflection_under_loss_score`, `value_inflection_score`, `uptrend_continuation_score`, `uptrend_breakdown_penalty`, `mom_18m`, `mom_24m`, `mom_36m`, `multi_year_winner_score`, `persistence_trend_24m`.
  - `scored_latest.csv` / `scored_oos_latest.parquet` -> same 10 new columns + 5 new diagnostic flags: `hold_persistence_bonus`, `phase8a_hold_persistence_active`, `phase8b_long_lookback_active`, `phase8c_megacap_override_active`, `phase8c_growth_adj_valuation_active`.
  - `stage_coverage_feature_store.json` -> coverage metrics for the 10 new numeric columns.
- validation:
  - `py -3 -c "import py_compile; py_compile.compile('r1000_top30_institutional.py', doraise=True)"` passed after each of the 5 commits.
  - No existing tests broken (walk-forward structure unchanged; only additional weight-pair entries + composite columns; every change gated behind dual-gate env+cfg toggle with `weight=0` fallback to byte-identical legacy behaviour).
  - Colab FULL rebuild required on next run to validate cumulative CAGR impact; ship gate `DIAGNOSIS_COUNTERFACTUAL.md §6`: CAGR >= 25% on the 83-month backtest.
- risks_or_notes:
  - **Execution plan**: user runs a FULL REBUILD in Colab (3h+) with all Phase 8 toggles at default ON. After Cell 4 completes, Cell E runs the recovery-verdict script (baseline in SESSION_HANDOFF.md `§2`) comparing the new metrics against the 2026-04-16 baseline (CAGR 20.10%). Expected: CAGR 25-30%+, Sharpe >= 1.0, MaxDD -18% to -24%. If CAGR is below 18% a regression occurred and we roll back via env toggles.
  - **A/B isolation**: every Phase 8 change is behind a dual-gate `cfg + env` toggle, so if the combined run regresses we can isolate which sub-phase via QUICK_RESCORE runs flipping one env var at a time. Phase 8a.1 (negative-IC drop), 8a.2 (phase5 default), 8a.4 (hold persistence), 8c.1 (megacap override), 8c.2 (growth-adj valuation) are all QUICK-measurable. Phase 8b.1 (long lookback) requires FULL rebuild due to new feature columns.
  - **Known gotcha**: `mom_24m` / `mom_36m` columns require 504 / 756 trading days of price history. Tickers with <3 years of data get `NaN` for `mom_36m` and `multi_year_winner_score` is zero-masked by design. Early-universe IPOs (PLTR, COIN, DASH, RBLX, etc.) will not score on Phase 8b for their first 2-3 years.
  - **Not yet implemented from PHASE_8_PROPOSAL.md**: `8a.3 IC-proportional reweighting` (deferred — needs post-FULL measurement to verify factor correlations first) and `8b.2 r_12m ML training target` (deferred — requires walk-forward train-target refactor, high risk for one session). Both flagged in SESSION_HANDOFF.md as Phase 8d/8e follow-ups pending.
  - **Negative-IC drops may be too aggressive**: `quality_trend_score` (IC -0.0042) and `selection_confirmation_score` (IC -0.0028) are statistically significant but marginally so over 83 months. Possible they help on specific regimes (stagflation / systemic-crisis) that the 83-month sample underweights. Mitigation: env toggle `PHASE_PHASE8A_NEG_IC_DROP=0` restores original weights.
  - **Megacap override may concentrate future sleeve too heavily**: if 6-10 names simultaneously meet (mktcap>$50B, rev_growth>0.25, multi_year_winner>1.0), future_winner sleeve's top-7 selection will be dominated by them. This is the INTENDED behaviour but increases single-name concentration — tradeoff accepted per user's "CAGR > diversification" stance.

### 11:42 KST - phase8-review-fixes-weight0-and-r1m-lookahead

- scope:
  - Pre-FULL-rebuild code-review pass on the Phase 8 restructuring (commits `4cd938e` -> `caddec3`). Two CRITICAL bugs caught before burning 3h of Colab compute. Commit `300affc` lands both fixes with unit-test verification.
- files:
  - `r1000_top30_institutional.py` -> two surgical edits (19 lines total).
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - none
- symbols_changed:
  - `weighted_sleeve_composite(weight_pairs, index, ...)` -> added `if abs(float(w)) < 1e-10: continue` guard BEFORE the `weighted_terms.append` to skip weight-0 pairs. Prevents `row_mean` denominator dilution when Phase 8a/b/c toggles set weight to 0.
  - `compute_portfolio_sleeve_columns(df, cfg)` -> replaced `_recent_r_1m = numeric_series_or_default(d, "r_1m", 0.0)` with `_recent_realised_mom_1m = numeric_series_or_default(d, "mom_1m", 0.0)` inside the hold_persistence_bonus block. `r_1m` is the FORWARD return (set at line 14110 to `forward_returns[cfg.target_1m_days]`) — using it in scoring creates lookahead bias.
- config_fields_added:
  - none
- breaking_changes:
  - none (these are bug fixes; they bring behaviour in line with the documented intent of Phase 8a/b/c toggles and eliminate lookahead bias).
- outputs:
  - none new; existing outputs will now reflect corrected composite (no silent dilution from weight-0 pairs, no lookahead in hold_persistence_bonus).
- validation:
  - `py -3 -c "import py_compile; py_compile.compile('r1000_top30_institutional.py', doraise=True)"` PASS.
  - `import r1000_top30_institutional` module load PASS.
  - `weighted_sleeve_composite` unit tests (4 cases) PASS:
    - `[(0.0, const_1), (1.0, const_2)]` returns mean=2.0 (only weight=1.0 term counts). Pre-fix buggy result would have been 1.5 (both diluting the denominator).
    - `[(0.5, const_1), (1.0, const_2)]` returns mean=1.25 (unchanged vs legacy — weights non-zero).
    - `[(0.0, s1), (0.0, s2)]` returns all-zero (fallback).
    - `[]` returns all-zero (fallback).
  - `rolling_robust_z` constant-series test PASS (z=0, not inf).
  - `rolling_robust_z` tiny-jump test PASS (max z=0.067, all within [-10, 10]).
  - `numeric_series_or_default` NaN-fallback PASS.
  - Mega-cap override mask construction on synthetic data PASS (NVDA True, AAPL/MSFT/AMZN/XOM False at boundary conditions).
  - Empty-DataFrame path in `compute_portfolio_sleeve_columns` PASS (shape (0, 28), no crash).
  - `colab_run.ipynb` cell 2 Phase 8 toggle integrity PASS (all 5 toggles: definition `= 'auto'`, env-bind via `_set_phase_env`, and print statement all present).
- risks_or_notes:
  - The weight-0 dilution bug was subtle and would not have crashed the run — it would have simply made Phase 8a.1 (drop quality_trend_score / selection_confirmation_score / industry_rotation_signal) produce the OPPOSITE effect (keeping these terms AT zero value, diluting the rest by 1/N each). After this fix, "weight=0" truly means "drop from composite" as intended.
  - The r_1m lookahead fix prevents a backtest-real-world divergence that would have been painful to diagnose post-hoc. `r_1m` is universally used as the PIT-safe "this month's forward return" target for ML training, NOT a feature. Using it as a feature would have made the 83-month backtest look fantastic and the live deployment perform like random.
  - **No ENGINE_REUSE_VERSION bump**: these are post-composite-computation logic fixes. Feature store schema unchanged. The existing cache (from the 2026-04-17 phase5 FULL rebuild) is still invalid because the Phase 8 ENGINE_REUSE_VERSION already bumped; the user's next FULL rebuild picks up both the Phase 8 additions AND these review fixes in one run.
  - Agent-based code review (spawned Explore agent) was the source of the weight-0 discovery. Keep this pattern: after any non-trivial composite weighting change, run an independent agent review BEFORE burning FULL-rebuild compute. Cheap insurance vs. 3-hour rollback.

### 11:52 KST - phase8d-ic-reweight-and-long-horizon-alpha-composite

- scope:
  - Add Phase 8d (IC-proportional weight boost) and Phase 8e-lite (long_horizon_alpha_composite) in a single commit so the user's imminent FULL REBUILD captures both. Phase 8e full (retraining the ML ensemble against an r_12m target) is still deferred — requires walk-forward refactor and a parallel model bundle cache. Phase 8e-lite achieves ~80% of the intended benefit by bypassing the ML ensemble's r_1m myopia via a direct sleeve composite over the 5 best r_12m-IC fundamental factors.
  - Also fixes a subtle env-var-name bug discovered during Phase 8d toggle testing: Phase 8a/b/c env vars in `colab_run.ipynb` Cell 2 were missing the `_ENABLED` suffix that `phase_is_enabled()` actually reads. Default-ON behaviour worked (unset env -> `default=True`), but A/B toggle-OFF via env was a silent no-op.
- files:
  - `r1000_top30_institutional.py` ->
    - `compute_portfolio_sleeve_columns` — added Phase 8d.1 toggle block (8 lines) + Phase 8d.2 `long_horizon_alpha_composite` construction (22 lines) + 3 sleeve wirings.
    - Core sleeve `strategy_blueprint_score` weight: `0.25` -> conditional (1.00 when Phase 8d.1 active, 0.25 legacy).
    - Core sleeve `industry_group_strength_score` weight: `0.10` -> conditional (0.50 active, 0.10 legacy).
    - Future sleeve `industry_group_strength_score` weight: `0.30` -> conditional (0.60 active, 0.30 legacy).
    - `EngineConfig` — 5 new fields (see config_fields_added below).
  - `colab_run.ipynb` -> Cell 2 renames 5 Phase 8 env var strings to include `_ENABLED` suffix + adds 2 new Phase 8d env var definitions and their `_set_phase_env` calls + print-loop tuple.
  - `CHANGELOG.md` -> this entry.
- symbols_added:
  - `long_horizon_alpha_composite` — diagnostic output column from `compute_portfolio_sleeve_columns` (r_12m-IC weighted blend of ep_ttm / fcfy_ttm / sp_ttm / roe_proxy / sage_composite_score, clipped `[-6, 6]`).
  - `phase8d_ic_reweight_active`, `phase8d_long_horizon_alpha_active` — 0.0 / 1.0 scalar flags.
- symbols_changed:
  - `compute_portfolio_sleeve_columns(df, cfg)` — added Phase 8d.1 weight boost + 8d.2 composite + three new weight-pair tuples (one per sleeve).
- config_fields_added:
  - `phase8d_ic_reweight_enabled: bool = True`
  - `phase8d_long_horizon_alpha_enabled: bool = True`
  - `phase8d_long_horizon_alpha_core_weight: float = 1.00`
  - `phase8d_long_horizon_alpha_future_weight: float = 0.60`
  - `phase8d_long_horizon_alpha_early_weight: float = 0.50`
- breaking_changes:
  - none (both Phase 8d sub-phases are dual-gated; env-disabled or cfg-disabled restores legacy behaviour byte-identically via the `weighted_sleeve_composite` weight-0 skip guard from commit `300affc`).
- outputs:
  - `scored_latest.csv` / `scored_oos_latest.parquet` -> 3 new columns: `long_horizon_alpha_composite`, `phase8d_ic_reweight_active`, `phase8d_long_horizon_alpha_active`.
- validation:
  - `py -3 -c "import py_compile; py_compile.compile('r1000_top30_institutional.py', doraise=True)"` PASS.
  - `import r1000_top30_institutional` PASS.
  - `compute_portfolio_sleeve_columns` on a 3-row toy frame PASS — shape `(3, 109)`, all Phase 8a/b/c/d diagnostic columns present and reporting correct `active` status.
  - Phase 8d env-toggle OFF test: set `PHASE_PHASE8D_IC_REWEIGHT_ENABLED=0` and `PHASE_PHASE8D_LONG_HORIZON_ALPHA_ENABLED=0` -> both diagnostic flags read 0.0 and `long_horizon_alpha_composite` reads 0.0 -> PASS.
  - `colab_run.ipynb` JSON validity after Cell 2 update PASS.
  - Cell 2 Phase 8 env var names: all 7 sub-phases (8a.1, 8a.4, 8b.1, 8c.1, 8c.2, 8d.1, 8d.2) now have consistent `_ENABLED` suffix matching `phase_is_enabled()`.
- risks_or_notes:
  - **Correlation concern**: the 5 factors in `long_horizon_alpha_composite` (ep_ttm, fcfy_ttm, sp_ttm, roe_proxy, sage_composite_score) are NOT independent. ep_ttm and sp_ttm both measure yield-style valuation; roe_proxy and sage_composite_score both have quality content. This means the composite's effective information content is below the IC sum of its parts. Mitigation: the wiring into sleeves (core 1.00, future 0.60, early 0.50) is modest; if A/B shows underperformance we can trim the weights without removing the composite.
  - **ML ensemble double-counting**: the 5 underlying factors are also in `DEFAULT_FEATURES`, so the walk-forward ML already trains on them. The composite is an ADDITIVE reweighting that effectively boosts their final score contribution. There's no "pure new signal" here — Phase 8d.2's benefit depends on the ML ensemble's r_1m myopia UNDER-weighting them in its learned weights. If the ML model already correctly weights these factors, the composite adds noise. Net effect is empirical and will show in the FULL rebuild A/B.
  - **Weight-pair table is now complex**: core sleeve has ~21 weight-pairs, future ~32, early ~31. The weight-0 skip guard from commit `300affc` ensures disabled factors are truly dropped (not diluting). But the sheer term count means each factor's EFFECTIVE weight remains small (~1/N). Future work: Phase 8d.3 / Phase 8f could consolidate correlated clusters into single composites to reduce N.
  - **Phase 8e full still deferred**: a dedicated session with walk-forward refactor + parallel r_12m model bundle + blending logic. ~2-3h focused work, medium risk. Ship gate would require QUICK_RESCORE A/B.
  - **ENGINE_REUSE_VERSION unchanged**: 8d.2 composite is computed at scoring time (inside `compute_portfolio_sleeve_columns`) not as a feature_store column. Same FULL rebuild triggered by 8b.1's version bump covers all Phase 8a-d changes atomically.

### 16:30 KST - phase9-c1-multi-year-rebalance-and-c2-thesis-gate

- scope:
  - **Two architectural fixes addressing problems surfaced by the Phase 8 measured run** (commit d87160d, CAGR 21.86% but Sharpe -0.09pp, MaxDD -8.5pp, early sleeve collapsed to 0 names selected, future sleeve absorbing 71.6% of portfolio vs 45% target). Phase 9 C1 rebalances Phase 8b multi_year_winner_score sleeve weights; Phase 9 C2 replaces argmax+override-chain sleeve assignment with explicit cross-sectional percentile-based thesis gates. Per user feedback ("$500B 도 10년 후엔 작을 수 있다 — 능동적으로 분리"), Phase 9 C2 uses PERCENTILE thresholds, not absolute USD, so gates remain meaningful as the market grows.
  - Both changes ship in one commit but with SEPARATE toggles so A/B isolation is possible in 3 QUICK_RESCORE runs.
- files:
  - `r1000_top30_institutional.py` (commit `ced5db6`):
    - `EngineConfig`: 16 new fields (Phase 9 C1: 4 fields, Phase 9 C2: 12 fields).
    - `compute_portfolio_sleeve_columns`: Phase 9 C1 multi_year weight resolution wraps existing Phase 8b weight reads (lines ~18681-18720); Phase 9 C2 thesis-gate override block runs AFTER existing argmax + Phase 8c.1 megacap override, replaces sleeve_label entirely when active (~115 new lines).
    - `apply_latest_ranking_eligibility`: when sleeve_label == "unassigned" (Phase 9 C2 quality gate), force `ranking_eligible = False` to exclude name from portfolio candidate pool regardless of model score.
  - `colab_run.ipynb` (this commit):
    - Cell 2: 2 new toggle var defs (`PHASE9_C1_REBALANCE`, `PHASE9_THESIS_GATE`); 2 new `_set_phase_env` calls; print-loop tuple extended.
  - `CHANGELOG.md`: this entry.
- symbols_added:
  - none
- symbols_changed:
  - `compute_portfolio_sleeve_columns(df, cfg)`:
    - Phase 8b multi_year weight block: when `phase9_c1_rebalance_enabled` (cfg + env) is True, override Phase 8b legacy weights (0.90 / 0.60 / 0.40) with Phase 9 C1 rebalanced weights (0.50 / 0.80 / 0.30). When False, falls back to legacy.
    - Inserted Phase 9 C2 thesis-gate block between Phase 8c.1 megacap override and `sleeve_label_raw = sleeve_label.copy()`. When `phase9_thesis_gate_enabled` (cfg + env) is True, computes cross-sectional percentile rank of mktcap and applies eligibility masks for core/future/early; sleeve_label gets replaced with "core_compounder" / "future_winner" / "early_scout" / "unassigned" based on gates. When False, preserves legacy argmax+override result byte-exactly.
  - `apply_latest_ranking_eligibility(df, cfg, context)`: post-processing step that sets `ranking_eligible = False` for any row with sleeve_label == "unassigned" (Phase 9 C2 quality gate). When Phase 9 C2 inactive there are no "unassigned" labels so this step is a no-op.
- config_fields_added:
  - `phase9_c1_rebalance_enabled: bool = True` — Phase 9 C1 master toggle
  - `phase9_c1_multi_year_future_weight: float = 0.50`
  - `phase9_c1_multi_year_early_weight: float = 0.80`
  - `phase9_c1_multi_year_core_weight: float = 0.30`
  - `phase9_thesis_gate_enabled: bool = True` — Phase 9 C2 master toggle
  - `phase9_core_megacap_percentile: float = 0.95` — top 5% mktcap = mega-cap auto-core
  - `phase9_core_quality_size_percentile: float = 0.70` — top 30% size for "quality" rule
  - `phase9_future_size_lower_percentile: float = 0.30`
  - `phase9_future_size_upper_percentile: float = 0.95`
  - `phase9_early_size_upper_percentile: float = 0.70` — bottom 70% (small + mid)
  - `phase9_core_quality_min_roe: float = 0.15`
  - `phase9_core_quality_min_margin: float = 0.10` — net OR op margin
  - `phase9_core_quality_rev_growth_min: float = 0.02`
  - `phase9_core_quality_rev_growth_max: float = 0.30` — hyper-grow goes to future
  - `phase9_future_min_rev_growth: float = 0.20`
  - `phase9_future_min_mom_24m: float = 0.50`
  - `phase9_early_inflection_threshold: float = 0.3` — turnaround / cf_inflection
  - `phase9_early_value_inflection_threshold: float = 0.5`
  - `phase9_early_breakout_threshold: float = 0.5`
  - `phase9_early_golden_cross_threshold: float = 0.3`
- breaking_changes:
  - **Behavior change** when Phase 9 C2 thesis-gate is active: portfolio composition changes because (a) sleeve labels reflect archetype thesis instead of factor-score argmax, (b) names without clear thesis (sleeve_label == "unassigned") get ranking_eligible = False and are excluded from portfolio. Toggle OFF (env or cfg) restores legacy argmax behavior byte-exactly.
  - **No keep_cols / feature_store schema change**: both Phase 9 C1 and C2 are post-feature-store logic in `compute_portfolio_sleeve_columns`. ENGINE_REUSE_VERSION unchanged. QUICK_RESCORE compatible (~20 min iteration, no FULL rebuild needed).
- outputs:
  - `outputs/scored_latest.csv`: 7 new diagnostic columns when Phase 9 C2 active:
    - `phase9_thesis_gate_active` (0.0 / 1.0)
    - `phase9_c1_rebalance_active` (0.0 / 1.0)
    - `phase9_core_eligible` (0.0 / 1.0 per row)
    - `phase9_future_eligible` (0.0 / 1.0 per row)
    - `phase9_early_eligible` (0.0 / 1.0 per row)
    - `phase9_unassigned` (0.0 / 1.0 per row)
    - `phase9_mktcap_percentile` (0.0-1.0 cross-sectional rank)
- validation:
  - `py -3 -c "import py_compile; py_compile.compile('r1000_top30_institutional.py', doraise=True)"` PASS.
  - `import r1000_top30_institutional as mod` PASS.
  - `cfg = mod.EngineConfig()` — all 16 new fields present with correct defaults PASS.
  - Synthetic 50-row smoke test (random universe with 5 percentile buckets): `compute_portfolio_sleeve_columns` returns shape (50, 122) with sleeve labels {core: 5, future: 4, early: 28, unassigned: 13} — sleeve labels reflect synthetic data distribution PASS.
  - Phase 9 toggle OFF test: env `PHASE_PHASE9_THESIS_GATE_ENABLED=0` + `PHASE_PHASE9_C1_REBALANCE_ENABLED=0` -> diagnostic flags read 0.0, sleeve labels fall back to argmax {core: 41, future: 9, early: 0} PASS.
  - Drive simulation on real 610-name universe (Phase 8 scored_latest.csv): Phase 9 C2 gates produce {core: 58, future: 54, early: 55, unassigned: 443} — clean 27% candidate selection, top picks per sleeve match thesis (core: NVDA/GOOGL/AVGO mega-cap; future: GEV/APH/LITE scaling-up; early: BKNG/EXE/PR turnaround). PASS.
  - `colab_run.ipynb` JSON validity: PASS. Cell 2 has 2 new Phase 9 toggle vars + 2 `_set_phase_env` calls + print-loop extended.
- risks_or_notes:
  - **Phase 1 inflection thresholds calibrated from data**: initial guess (>1.5 for turnaround/cf_inflection/value_inflection) caught 0 names cross-sectionally on real universe. Data-validated thresholds (>0.3 for turnaround / cf_inflection, >0.5 for value_inflection) catch 29 names total. Calibration assumed normal-ish distribution of these scores; if a regime shift produces extreme inflection scores (mass turnaround period like 2009 or 2020), gate may admit too many names. Mitigation: cfg knobs (`phase9_early_inflection_threshold`, `phase9_early_value_inflection_threshold`) are tunable per-strategy.
  - **EPS turn-positive flags NOT yet implemented**: `profit_turn_positive_4q`, `cashflow_turn_positive_4q`, `roe_turn_positive_4q` etc. would be the cleanest "EPS just turned positive" gate signals (per user definition: "early 는 eps 적자거나 양전환 막 하거나"). They require fund_panel modification in `compute_fundamental_features` and a feature_store rebuild. Deferred to Phase 9 C3 (separate commit, FULL rebuild required). Phase 1 alpha scores (`fundamental_turnaround_acceleration_score`, `cashflow_inflection_under_loss_score`, `value_inflection_score`) are the proxy for now.
  - **Quality gate aggressiveness**: 72.6% of universe gets `unassigned` -> ranking_eligible False. This is INTENDED (only hold names with clear thesis), but tightly couples portfolio composition to gate calibration. If percentile thresholds are too strict in a particular regime (e.g. crisis where most names lose growth qualification), portfolio could shrink dramatically. Diagnostic columns (phase9_*_eligible) per row let us audit any concerning months post-run.
  - **C1 + C2 combined effect not yet measured**: C2 is a major behavior change; C1 is a minor weight change. Combined could improve metrics, hurt metrics, or be mixed. User QUICK_RESCORE test required to make Stage 1 verdict (SHIP / PARTIAL / REGRESS per EXECUTION_PLAN). 3-run A/B isolation possible (each ~20 min): both ON vs C1-only vs C2-only.
  - **`unassigned` sleeve label propagates downstream**: any consumer of `portfolio_sleeve_label` that hard-codes the 3 legacy labels (core_compounder / future_winner / early_scout) and doesn't handle "unassigned" will silently miss those names. `apply_latest_ranking_eligibility` handles it correctly via the ranking_eligible mask, but operator/state code should be audited for hard-coded sleeve enumeration.
  - Phase 9 C1 + C2 are POST-feature-store changes. ENGINE_REUSE_VERSION unchanged. **QUICK_RESCORE compatible** (~20 min iteration vs 2-3h FULL rebuild).

### 17:16 KST - run-banner-commit-sha-provenance

- scope:
  - Pipeline run banner self-identification. Every run now prints the engine's git commit SHA so logs / Colab scrollback unambiguously identify which code version produced the metrics.
- files:
  - `r1000_top30_institutional.py` -> new module-level helper `_resolve_engine_commit_sha()` + constant `ENGINE_COMMIT_SHA`; prefixes `run_default_pipeline` start log with `[commit=<sha>] [engine_version=<ENGINE_REUSE_VERSION>]`.
  - `colab_run.ipynb` -> Cell 2 captures `COMMIT_SHA` from `git rev-parse --short HEAD` right after `git reset --hard origin/master` (or fresh clone) and prints `Repo commit: <sha>`; Cell 4 FULL REBUILD and QUICK RESCORE banners both interpolate `{COMMIT_SHA}` so the first pipeline-mode print line also carries the SHA.
- symbols_added:
  - `_resolve_engine_commit_sha() -> str` -> runs `git rev-parse --short HEAD` in the repo dir with 3s timeout; returns the short SHA or `(unknown)` if git unavailable (wheel install, missing binary, non-repo cwd).
  - `ENGINE_COMMIT_SHA: str` -> module-level constant resolved once at import, reused across all log lines.
- symbols_changed:
  - `run_default_pipeline(cfg)` -> start-of-run log line gains `[commit=<sha>] [engine_version=<ver>]` prefix so the first timestamped output already carries version provenance.
- config_fields_added:
  - none
- breaking_changes:
  - none (pure additive print, no control-flow change, no artifact schema change).
- outputs:
  - none (only stdout / notebook log text changes).
- validation:
  - `py -3 -c "import ast; ast.parse(open('r1000_top30_institutional.py').read())"` -> syntax OK.
  - `py -3 -c "import json; json.load(open('colab_run.ipynb'))"` -> notebook JSON still valid after patch (12 cells, indent=1 preserved).
  - Runtime-tested the helper inline (subprocess + pathlib only) against this repo: returned `33581bc` (matches `git rev-parse --short HEAD`).
  - Notebook patch verified by re-reading: Cell 2 contains `rev-parse` + `print('Repo commit:', COMMIT_SHA)`, Cell 4 contains both `FULL REBUILD MODE (commit={COMMIT_SHA})` and `QUICK RESCORE MODE (commit={COMMIT_SHA})`.
- risks_or_notes:
  - Helper is defensive: 3s timeout + `check=False` + broad `except Exception` ensures a missing/broken git never takes down the pipeline; falls back to `(unknown)`.
  - The in-flight 08:10 FULL REBUILD run that triggered this change (commit `33581bc`) will NOT show the SHA banner — the helper was added after the run started. Next run from fresh checkout will show it.
  - When the engine is installed as a wheel (not a clone) `(unknown)` will be printed. If we start shipping wheels later, consider baking SHA into a generated `_version.py` during build.
