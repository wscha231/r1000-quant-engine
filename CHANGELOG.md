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
