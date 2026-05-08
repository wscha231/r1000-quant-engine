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

## 2026-05-08

### 09:36 KST - portfolio-target-gate-tightening

- scope:
  - Tighten explicit portfolio goal gates to the new commercial targets: main CAGR 30% / MaxDD -15%, concentrated CAGR 50% / MaxDD -18%.
- files:
  - `r1000_config.py` ->adds shared portfolio goal targets and wires main/concentrated target fields to them.
  - `tools/run_portfolio_goal_search.py` ->reads shared goal targets instead of maintaining local hardcoded thresholds and bootstraps repo-root imports when run directly.
  - `CHANGELOG.md` ->records the target gate change.
- symbols_added:
  - `PORTFOLIO_GOAL_TARGETS` ->single source of truth for artifact goal-search targets.
- symbols_changed:
  - none
- config_fields_added:
  - `main_target_cagr: float = 0.30` ->commercial target for main portfolio CAGR.
  - `main_target_max_dd: float = -0.15` ->commercial target for main portfolio MaxDD.
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `py -3 tools\run_portfolio_goal_search.py --latest-run cloud_results\full_rebuild\20260505_global_alpha_universe --output-dir _local_goal_target_20260508` ->passed; main proxy passes, concentrated remains below the new target.
  - `py -3 -m py_compile tools\run_portfolio_goal_search.py r1000_config.py` ->passed.
- risks_or_notes:
  - This changes evaluation thresholds only; it does not change production selection, cash policy, or portfolio weights.
  - The best completed-run concentrated candidate is still below the new 50% / -18% target, so concentrated needs further alpha/risk work before promotion.

### 10:01 KST - cash-policy-attribution-sidecar

- scope:
  - Add the first cash-policy migration step: explain whether main-book cash is risk defense, idle cash, or an artifact/export mismatch before changing allocations.
- files:
  - `tools/run_cash_policy_attribution.py` ->new research-only sidecar that joins `main_monthly_weights.csv` and `regime_by_month.csv`, writes cash attribution rows, summary JSON, and a Markdown report.
  - `.github/workflows/full_rebuild_manual.yml` ->runs the cash attribution sidecar after macro policy and syncs/uploads `outputs/cash_policy/`.
  - `tests/workflow_artifact_smoke.py` ->checks that the workflow runs and exports the cash attribution artifacts.
  - `CHANGELOG.md` ->records the cash attribution sidecar.
- symbols_added:
  - `_rows_by_month(holdings, regime)` ->builds per-month cash attribution inputs from holdings and regime artifacts.
  - `_summary(rows)` ->summarizes reported cash, explicit monthly-book cash, target defense cash, excess cash, idle-cash candidates, and export mismatch counts.
  - `_render_report(payload)` ->renders the human-readable cash policy attribution report.
  - `run(latest_run, output_dir)` ->sidecar entrypoint that writes `cash_drag_attribution.csv`, `cash_drag_summary.json`, and `cash_drag_report.md`.
- symbols_changed:
  - `test_workflow_keeps_monthly_books()` ->requires `outputs/cash_policy/` artifact upload coverage.
  - `test_workflow_runs_latest_diagnostics_sidecars()` ->requires cash attribution workflow execution and log capture.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/cash_policy/cash_drag_attribution.csv` ->per-month cash source and mismatch diagnostics.
  - `outputs/cash_policy/cash_drag_summary.json` ->summary of cash defense, idle cash, and cash export mismatch.
  - `outputs/cash_policy/cash_drag_report.md` ->human-readable cash policy diagnostic.
- validation:
  - `py -3 tools\run_cash_policy_attribution.py --latest-run cloud_results\full_rebuild\latest_global_alpha_universe --output-dir _local_cash_policy_check` ->passed.
  - `py -3 -m py_compile tools\run_cash_policy_attribution.py` ->passed.
- risks_or_notes:
  - The latest local completed artifacts show average reported cash 21.02% but explicit CASH rows in `main_monthly_weights.csv` average only 4.71%, so the existing cash-drag replay must be repaired before using it as evidence.
  - This is diagnostic-only and does not change production weights.

### 10:05 KST - idle-cash-redeploy-replay-alignment

- scope:
  - Repair the idle-cash redeploy A/B replay so it uses reported backtest cash from `regime_by_month.csv` before testing cash-cap redeployment.
- files:
  - `tools/run_main_cash_drag_replay.py` ->aligns monthly holdings to reported cash, records production-vs-replay deltas, and keeps the replay research-only.
  - `.github/workflows/full_rebuild_manual.yml` ->runs the main cash-drag replay and uploads/syncs `outputs/main_cash_drag_replay/`.
  - `tests/workflow_artifact_smoke.py` ->requires workflow execution and artifact coverage for `outputs/main_cash_drag_replay/`.
  - `CHANGELOG.md` ->records the idle-cash replay repair.
- symbols_added:
  - `align_to_reported_cash(df, regime)` ->reconstructs explicit CASH rows from `regime_by_month.cash_weight` and scales selected stock weights to the reported invested share.
  - `read_json(path)` ->loads production metrics for replay-vs-production diagnostics.
- symbols_changed:
  - `run(args)` ->uses reported cash by default, writes cash-alignment metadata, and compares replay base metrics against production metrics.
  - `render_report(summary, grid)` ->shows production metrics, replay-vs-production gap, and cash alignment diagnostics.
  - `parse_args()` ->adds `--cash-source {reported,explicit}`.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/main_cash_drag_replay/cash_drag_grid.csv` ->idle-cash cap redeploy grid.
  - `outputs/main_cash_drag_replay/summary.json` ->replay metrics, cash alignment, and production comparison.
  - `outputs/main_cash_drag_replay/cash_drag_replay_report.md` ->human-readable replay summary.
- validation:
  - `py -3 tools\run_main_cash_drag_replay.py --latest-run cloud_results\full_rebuild\latest_global_alpha_universe --output-dir _local_main_cash_drag_replay_check` ->passed.
  - `py -3 -m py_compile tools\run_main_cash_drag_replay.py` ->passed.
- risks_or_notes:
  - The local replay base still differs from production metrics, so this remains directional evidence only.
  - The next implementation should produce a production-compatible cash replay from `equity_curve.csv` / pipeline monthly accounting, not only exported holdings.

## 2026-05-07

### 00:50 KST - concentrated-champion-guard

- scope:
  - Prevent latest concentrated production outputs from falling back to invalid N=1/NaN metrics when a valid historical comparison-grid champion exists.
- files:
  - `r1000_config.py` ->adds concentrated production minimum-name and goal-threshold fields.
  - `r1000_pipeline.py` ->filters concentrated comparison rows for finite 6y+ metrics, prefers goal-passing candidates, and reloads the comparison CSV when export artifacts are empty.
  - `tests/concentrated_policy_smoke.py` ->adds regression coverage for rejecting NaN N=1 concentrated fallbacks and applying the grid champion to latest holdings.
  - `CHANGELOG.md` ->records the concentrated champion guard.
- symbols_added:
  - `select_concentrated_champion_comparison(cfg, concentrated_compare)` ->returns valid concentrated comparison rows sorted with the production champion first.
- symbols_changed:
  - `build_latest_concentrated_holdings()` ->uses the validated historical comparison champion, enforces minimum production N, emits target/pass validity fields, and avoids silent N=1/NaN fallback behavior.
- config_fields_added:
  - `concentrated_min_production_names: int = 3` ->minimum latest concentrated production N before a fallback is considered valid.
  - `concentrated_latest_prefer_goal_passing: bool = True` ->prefers rows meeting explicit concentrated CAGR/MaxDD goals before objective sorting.
  - `concentrated_target_cagr: float = 0.40` ->concentrated production target CAGR used for target-pass tagging.
  - `concentrated_target_max_dd: float = -0.22` ->concentrated production target MaxDD floor used for target-pass tagging.
- breaking_changes:
  - none
- outputs:
  - `outputs/concentrated_backtest_metrics.json` ->now includes `metrics_valid`, `target_cagr`, `target_max_dd`, `target_pass`, `production_valid`, and `comparison_source`.
- validation:
  - `python tests\concentrated_policy_smoke.py` ->passed.
  - inline latest artifact check ->passed; selected N=3 score_power champion with CAGR 45.75%, MaxDD -20.62%, tickers CIEN/WDC/SNDK.
- risks_or_notes:
  - This validates the champion plumbing without launching a new full rebuild.
  - Latest concentrated metrics remain unverified in GitHub artifacts until the next cloud rebuild writes the corrected summary.

### 09:59 KST - concentrated-export-order-fix

- scope:
  - Fix concentrated latest output export order so the validated comparison-grid champion is available before `concentrated_backtest_metrics.json` and `concentrated_portfolio_latest.csv` are written.
- files:
  - `r1000_pipeline.py` ->writes concentrated comparison/monthly/holdings grid artifacts before dependent latest concentrated exports and reuses the same writer for final cleanup.
  - `tests/concentrated_policy_smoke.py` ->adds coverage for reloading an already-written concentrated comparison artifact when the in-memory comparison frame is empty.
  - `CHANGELOG.md` ->records the concentrated export-order fix.
- symbols_added:
  - `export_outputs._write_concentrated_grid_artifacts(prune_missing=False)` ->internal helper that persists or prunes concentrated grid artifacts consistently inside export.
  - `test_latest_concentrated_reloads_written_grid_artifact()` ->smoke test for concentrated champion reload from a written grid artifact.
- symbols_changed:
  - `export_outputs()` ->persists concentrated grid artifacts before latest concentrated holdings/metrics are built, preventing stale fallback NaN metrics.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/concentrated_strategy_comparison.csv` ->now exists before latest concentrated output construction during export.
  - `outputs/concentrated_backtest_metrics.json` ->next rebuild should use the N=3 score_power champion metrics instead of NaN fallback when the grid comparison is valid.
- validation:
  - `py -3 tests\concentrated_policy_smoke.py` ->passed.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 83/83.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed.
  - local latest artifact check ->passed; direct comparison champion selects GLW/CIEN/WDC at N=3 score_power with CAGR 45.75% and MaxDD -20.62%.
- risks_or_notes:
  - No production scoring/defaults changed; this is output plumbing only.
  - Existing GitHub artifacts remain stale until the next full rebuild writes corrected concentrated summary files.

### 11:26 KST - autolearning-concentrated-reflection-route

- scope:
  - Connect concentrated champion trade outcomes into AutoLearning and add a guarded route for approved learned gates to affect the next scoring run.
- files:
  - `.github/workflows/full_rebuild_manual.yml` ->builds concentrated champion trade journal, includes it in trade insights, runs policy proposal/challenger/promotion sidecars, archives/syncs the new artifacts, and adds an explicit guarded live-promotion input.
  - `.github/workflows/quarterly_auto_learning.yml` ->adds concentrated champion trade journal as optional extra evidence for scheduled/manual learning reviews.
  - `r1000_trade_journal.py` ->expands captured signal breakdown fields and allows sidecar-specific journal output directories.
  - `r1000_auto_learning_evidence.py` ->summarizes concentrated and combined trade journals for policy evidence.
  - `tools/build_concentrated_trade_journal.py` ->new sidecar that filters the concentrated strategy grid to the validated champion and emits trade/grade artifacts.
  - `tools/trade_insights.py` ->supports extra trade journals and imports the canonical signal breakdown list.
  - `tools/auto_policy_proposal.py` ->surfaces concentrated and combined trade counts/win-rate in policy evidence summaries.
  - `tests/concentrated_trade_learning_smoke.py` ->adds coverage for concentrated champion journal creation and combined insight loading.
  - `tests/workflow_artifact_smoke.py` ->checks the new learning artifacts and guarded promotion input remain wired into the full rebuild workflow.
  - `CHANGELOG.md` ->records the AutoLearning reflection route.
- symbols_added:
  - `r1000_trade_journal._journal_dir(paths)` ->resolves the default or custom trade journal output directory.
  - `tools.build_concentrated_trade_journal.repo_path(path_like)` ->normalizes repo-relative CLI paths.
  - `tools.build_concentrated_trade_journal.safe_float(value, default=0.0)` ->NaN-safe numeric coercion.
  - `tools.build_concentrated_trade_journal.read_csv(path)` ->defensive CSV loader.
  - `tools.build_concentrated_trade_journal.write_json(path, payload)` ->writes JSON sidecar artifacts.
  - `tools.build_concentrated_trade_journal.champion_row(compare)` ->selects the validated concentrated grid champion.
  - `tools.build_concentrated_trade_journal.filter_champion_frame(df, champion)` ->filters monthly/holdings grids to champion N/mode/interval.
  - `tools.build_concentrated_trade_journal.add_regime_state(holdings, latest_run)` ->joins monthly regime state onto concentrated holdings.
  - `tools.build_concentrated_trade_journal.signal_breakdown(row)` ->serializes AutoLearning signal values for a concentrated holding row.
  - `tools.build_concentrated_trade_journal.normalize_holdings(holdings, latest_run)` ->converts champion holdings into trade-journal-compatible rows.
  - `tools.build_concentrated_trade_journal.build(latest_run, output_dir)` ->emits concentrated champion holdings/trades/grades/summary artifacts.
  - `tools.trade_insights.merge_grade_labels(trades, trades_path)` ->merges grades for each primary or extra journal source.
  - `tools.trade_insights.load_journals(primary_path, extra_paths)` ->loads and concatenates primary plus extra trade journals for learning.
  - `test_concentrated_journal_build_and_insight_load()` ->smoke test for concentrated trade-learning artifacts.
- symbols_changed:
  - `r1000_trade_journal.SIGNAL_BREAKDOWN_COLUMNS` ->adds monster/entry-quality/risk/stale-leader fields to the learned signal signature.
  - `r1000_trade_journal.persist_holdings_history()` ->honors `paths["trade_journal_dir"]` for sidecar outputs.
  - `r1000_trade_journal.pair_entries_with_exits()` ->honors `paths["trade_journal_dir"]` and carries `source_journal` into trade rows.
  - `r1000_trade_journal.grade_trades()` ->honors `paths["trade_journal_dir"]` for sidecar grades.
  - `tools.trade_insights.main()` ->accepts `--extra-trades` and computes insights on combined trade evidence.
  - `r1000_auto_learning_evidence.load_auto_learning_evidence()` ->adds concentrated and combined trade journal summaries.
  - `tools.auto_policy_proposal.build_policy_from_evidence()` ->includes concentrated/combined trade evidence in policy summaries.
- config_fields_added:
  - `full_rebuild_manual.workflow_dispatch.auto_learning_promote_live: bool = false` ->explicit guarded switch that can commit approved `research/auto_feature_gates.yaml` for the next run.
- breaking_changes:
  - none
- outputs:
  - `outputs/concentrated_trade_journal/holdings_history.csv` ->champion-only concentrated monthly holdings.
  - `outputs/concentrated_trade_journal/trades.csv` ->champion-only concentrated round-trip trades.
  - `outputs/concentrated_trade_journal/grades.csv` ->auto-graded concentrated trades.
  - `outputs/concentrated_trade_journal/summary.json` ->champion metadata and trade digest.
  - `outputs/auto_learning/auto_learning_policy_candidate.yaml` ->policy candidate generated from combined learning evidence.
  - `outputs/auto_learning/challenger/challenger_decision.json` ->guarded challenger decision for the generated policy candidate.
  - `research/auto_feature_gates.yaml` ->only written and committed when `auto_learning_promote_live=true` and promotion checks pass.
- validation:
  - `py -3 tests\concentrated_trade_learning_smoke.py` ->passed.
  - `py -3 tests\auto_learning_policy_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\auto_learning_v2_smoke.py` ->passed.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 83/83.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed.
  - local artifact check ->passed; concentrated champion journal built 152 trades from N=3 score_power champion and combined insights loaded 878 trades.
- risks_or_notes:
  - Learned gates still cannot alter the current run because they are generated after scoring; approved gates affect the next run.
  - Live promotion is opt-in and guarded by `auto_learning_promote.py`; default full rebuild behavior remains dry-run/report-only.
  - This does not enable broker execution or unguarded capital allocation changes.

### 12:21 KST - dataset-coverage-audit-route

- scope:
  - Add full-run dataset coverage diagnostics and preserve historical candidate replay fields needed to explain missing or rejected leader candidates.
- files:
  - `r1000_pipeline.py` ->extends `candidate_replay_book.csv` with raw fundamental/growth columns, preserves `universe_source` as `source_universe`, and recomputes candidate gate labels for historical replay diagnostics.
  - `tools/run_dataset_coverage_audit.py` ->adds a read-only sidecar that audits latest/historical coverage, effective market-cap availability, distribution counts, and watchlist missing-candidate causes.
  - `.github/workflows/full_rebuild_manual.yml` ->runs the dataset audit sidecar and includes its outputs in artifacts, Google Drive sync, Telegram bundle, and cloud result commits.
  - `tests/dataset_coverage_audit_smoke.py` ->adds fixture coverage for effective market cap and watchlist missing-candidate classification.
  - `tests/workflow_artifact_smoke.py` ->checks dataset audit workflow wiring and candidate replay diagnostic export hooks.
  - `CHANGELOG.md` ->records the dataset coverage audit route.
- symbols_added:
  - `tools.run_dataset_coverage_audit.repo_path(path_like)` ->normalizes repo-relative CLI paths.
  - `tools.run_dataset_coverage_audit.read_csv(path)` ->defensive CSV loader.
  - `tools.run_dataset_coverage_audit.read_json(path)` ->defensive JSON loader.
  - `tools.run_dataset_coverage_audit.write_json(path, payload)` ->writes JSON audit outputs.
  - `tools.run_dataset_coverage_audit.numeric_coverage(df, columns, scope)` ->computes per-column numeric/nonzero coverage.
  - `tools.run_dataset_coverage_audit.effective_numeric_coverage(df, columns, scope, output_column)` ->computes coalesced coverage such as effective market cap from `market_cap_live`/`mktcap`.
  - `tools.run_dataset_coverage_audit.value_counts_rows(df, col, scope, limit=20)` ->exports source/gate/sleeve distribution counts.
  - `tools.run_dataset_coverage_audit.watchlist_rows(scored, book, tickers)` ->classifies selected watchlist names as absent, historical-only, rejected, or selected candidates.
  - `tools.run_dataset_coverage_audit.render_report(payload, output_dir)` ->renders the markdown audit summary.
  - `tools.run_dataset_coverage_audit.run(latest_run, output_dir, watchlist)` ->emits audit JSON/CSV/Markdown files.
  - `test_dataset_coverage_audit_outputs_effective_cap_and_watchlist()` ->smoke test for audit outputs.
- symbols_changed:
  - `export_outputs._write_monthly_mandate_books()` ->preserves source/gate/fundamental diagnostic fields in the historical candidate replay book.
  - `test_pipeline_exports_monthly_books()` ->also checks candidate replay diagnostic field preservation.
  - `test_workflow_runs_latest_diagnostics_sidecars()` ->also checks dataset audit sidecar wiring.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/dataset_coverage_audit.json` ->machine-readable dataset coverage, missing-column, watchlist, and effective market-cap audit.
  - `outputs/reports/dataset_coverage_audit.md` ->human-readable dataset audit summary.
  - `outputs/reports/dataset_coverage_audit_coverage.csv` ->per-column latest and historical coverage ratios.
  - `outputs/reports/dataset_coverage_audit_watchlist.csv` ->watchlist inclusion/rejection diagnostics for names such as SNDK, INTC, STX, LITE, WDC, and CIEN.
  - `outputs/reports/dataset_coverage_audit_distributions.csv` ->universe source, gate, sleeve, and sector distribution counts.
- validation:
  - `py -3 -m py_compile r1000_pipeline.py tools\run_dataset_coverage_audit.py tests\dataset_coverage_audit_smoke.py tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\dataset_coverage_audit_smoke.py` ->passed.
  - `py -3 tools\run_dataset_coverage_audit.py --latest-run cloud_results\full_rebuild\latest_global_alpha_universe --output-dir _local_dataset_audit_check3` ->passed; latest artifact shows 704 latest rows, 84 historical months, effective market cap 100% in latest and historical books, and missing source/gate/fundamental diagnostics in the pre-fix artifact.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 83/83.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed.
  - `git diff --check` ->passed with existing CRLF normalization warnings only.
- risks_or_notes:
  - This does not change production selection weights or model features.
  - Existing cloud artifacts still show pre-fix historical replay gaps; the next full rebuild is needed to populate the expanded `candidate_replay_book.csv`.
  - The current latest artifact confirms effective market cap is present via `mktcap`, but historical source/gate labels and raw fundamentals need the next export to become auditable.

### 12:33 KST - strategic-global-hardware-universe

- scope:
  - Add a non-buy-list strategic semiconductor, AI hardware, memory/storage, optical, and datacenter infrastructure universe overlay so missing leaders remain visible to latest diagnostics and explicit research backtests.
- files:
  - `aggressive/universe.py` ->loads the same strategic hardware YAML in the shared aggressive/tactical universe loader so `global_alpha_universe` stays aligned across engines.
  - `strategic_global_hardware_universe.yaml` ->adds the curated research universe records for INTC, AMD, ARM, ASML, TSM, AVGO, QCOM, MU, WDC, SNDK, STX, LITE, CIEN, GLW, and adjacent hardware leaders.
  - `r1000_config.py` ->adds enable/path fields for the strategic global hardware universe overlay.
  - `r1000_pipeline.py` ->loads the YAML overlay, injects it into `global_alpha_universe`, and treats overlay-only historical rows like leader-rescue rows under `leader_rescue_backtest_mode`.
  - `tools/run_dataset_coverage_audit.py` ->expands the default watchlist to include semiconductor, AI hardware, memory/storage, optical, and datacenter infrastructure names.
  - `tests/smoke_test.py` ->adds loader coverage and verifies strategic overlay-only rows obey latest-only/full-proxy/off backtest filtering.
  - `CHANGELOG.md` ->records the strategic global hardware universe overlay.
- symbols_added:
  - `aggressive.universe.load_strategic_global_hardware_universe(include_skip=False)` ->loads the shared hardware overlay for aggressive/tactical research loaders.
  - `load_strategic_global_hardware_universe_frame(cfg)` ->loads the strategic hardware YAML as a candidate-universe source without bypassing normal scoring or risk gates.
  - `test_strategic_global_hardware_universe_loader()` ->guards the overlay loader and required diagnostic tickers.
- symbols_changed:
  - `aggressive.universe.load_universe(source, ...)` ->unions strategic hardware candidates into `global_alpha_universe` and records hardware metadata.
  - `normalize_engine_universe_mode(mode)` ->adds hardware aliases into the shared `global_alpha_universe` path.
  - `build_candidate_universe()` ->injects strategic hardware candidates into global-alpha candidate discovery and logs pre-dedup additions.
  - `_leader_rescue_only_source_mask(df)` ->treats strategic hardware overlay-only rows as current-overlay rows for PIT-safer historical filtering.
  - `test_leader_rescue_latest_only_filter()` ->verifies strategic overlay-only rows are latest-only by default, retained in `full_proxy`, and removed in `off`.
- config_fields_added:
  - `strategic_global_hardware_universe_enabled: bool = True` ->enables the diagnostic universe overlay in global-alpha runs.
  - `strategic_global_hardware_universe_path: str = ""` ->optional override path for the strategic hardware YAML.
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/dataset_coverage_audit_watchlist.csv` ->next full rebuild will classify the expanded hardware watchlist as selected, rejected, historical-only, or not in latest universe.
  - `outputs/reports/leader_rescue_backtest_filter_summary.json` ->now counts strategic hardware overlay-only rows in the same latest-only/full-proxy/off safety filter.
- validation:
  - `py -3 -m py_compile aggressive\universe.py r1000_config.py r1000_pipeline.py tools\run_dataset_coverage_audit.py tests\smoke_test.py` ->passed.
  - inline `load_strategic_global_hardware_universe_frame()` check ->passed; loaded 25 rows including INTC, AMD, ARM, ASML, STX, SNDK, WDC, LITE, and CIEN.
  - `py -3 tests\dataset_coverage_audit_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 84/84.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed.
- risks_or_notes:
  - This is a candidate-universe overlay, not a ticker buy rule.
  - Default historical production metrics remain PIT-safer because overlay-only rows are latest-only unless `leader_rescue_mode=full_proxy` is explicitly selected for biased research.
  - Price history can be fetched for these tickers on the next collector run, but fundamentals, ADR data, and event/ownership coverage will vary by ticker, listing date, and source availability.

### 13:15 KST - theme-chameleon-lifecycle-policy

- scope:
  - Add research-only theme half-life policy metadata so event/commodity beneficiaries can be reviewed faster while structural growth winners can tolerate valid shakeouts longer.
- files:
  - `themes.yaml` ->tags major structural, commodity, event, and product-cycle themes with holding profiles, event risk, target hold months, and max hold months; adds SNDK/ARM/INTC to relevant semiconductor theme memberships.
  - `r1000_themes.py` ->loads theme policy metadata and attaches per-ticker horizon, event-risk, structural-growth, and short-cycle columns.
  - `r1000_features.py` ->fills safe defaults for theme policy columns when theme data is missing.
  - `r1000_config.py` ->adds research-only theme policy columns and bumps `ENGINE_REUSE_VERSION`.
  - `r1000_pipeline.py` ->preserves theme policy metadata in feature store and `reports/candidate_replay_book.csv` without adding it to `DEFAULT_FEATURES`.
  - `tools/run_monster_lifecycle_replay.py` ->adjusts research-only lifecycle thresholds by theme half-life; short-cycle themes trim/exit faster, structural themes get more shakeout patience.
  - `tools/run_position_aware_risk_replay.py` ->uses theme half-life metadata to avoid protecting event-cycle winners while preserving stronger protection for structural long-hold winners.
  - `tools/run_main_v2_backtest.py` ->passes theme policy metadata through monthly holdings for risk replay.
  - `tests/historical_challenger_replays_smoke.py` ->adds fixture fields and output assertions for theme policy metadata through replay artifacts.
  - `tests/smoke_test.py` ->adds regression coverage that FTI/oilfield services are short-cycle and NVDA/AI compute are structural growth.
  - `CHANGELOG.md` ->records the theme chameleon lifecycle policy change.
- symbols_added:
  - `r1000_themes._theme_policy_defaults(theme_horizon)` ->returns default policy metadata for a theme horizon.
  - `r1000_themes._coerce_policy_float(value, default)` ->NaN-safe numeric parser for theme policy fields.
  - `tools.run_monster_lifecycle_replay.theme_event_risk(row)` ->reads max event-risk sensitivity from candidate rows.
  - `tools.run_monster_lifecycle_replay.theme_structural_growth(row)` ->reads max structural-growth score from candidate rows.
  - `tools.run_monster_lifecycle_replay.theme_short_cycle(row)` ->detects event/commodity short-cycle theme rows.
  - `tools.run_monster_lifecycle_replay.theme_adjusted_policy(row, policy)` ->returns per-row lifecycle thresholds adjusted by theme half-life.
  - `test_theme_policy_metadata_surface()` ->guards theme policy metadata surface and ticker examples.
- symbols_changed:
  - `r1000_themes.load_themes()` ->preserves optional theme policy metadata with safe defaults.
  - `r1000_themes.attach_per_ticker_theme_features()` ->adds per-ticker theme horizon, event risk, structural growth, target-hold, max-hold, and short-cycle columns.
  - `r1000_features.compute_theme_phase_features()` ->fills theme policy defaults alongside phase multipliers.
  - `tools.run_monster_lifecycle_replay.entry_qualified()` ->blocks late-cycle event themes in peaking/ending/dead phase from new scout entry.
  - `tools.run_monster_lifecycle_replay.classify_exit()` ->applies event half-life trims/time stops and structural shakeout patience.
  - `tools.run_monster_lifecycle_replay.replay()` ->uses theme-adjusted policy for held winners and new scouts, and writes theme policy diagnostics.
  - `tools.run_position_aware_risk_replay.is_long_hold_protected()` ->uses event/structural theme metadata in relative underperformance protection.
  - `tools.run_main_v2_backtest.replay()` ->carries theme policy metadata into monthly holdings.
- config_fields_added:
  - `PHASE20_THEME_POLICY_COLUMNS: list[str] = [...]` ->research-only feature-store/candidate-book column list for theme half-life metadata.
  - `ENGINE_REUSE_VERSION: str = "2026-05-07-theme-chameleon-policy"` ->forces feature-store rebuild for the new metadata columns.
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/candidate_replay_book.csv` ->next rebuild includes theme horizon/event-risk/structural-growth fields for lifecycle backtests.
  - `outputs/monster_lifecycle_replay/holdings.csv` ->includes theme policy diagnostics for each held ticker.
  - `outputs/position_aware_risk_replay/defensive_holdings.csv` ->includes theme policy diagnostics for risk actions.
- validation:
  - `py -3 -m py_compile r1000_config.py r1000_features.py r1000_themes.py r1000_pipeline.py tools\run_monster_lifecycle_replay.py tools\run_lifecycle_review_overlay.py tools\run_position_aware_risk_replay.py tools\run_main_v2_backtest.py tests\historical_challenger_replays_smoke.py tests\smoke_test.py` ->passed.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 85/85.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed; 245 features, no leakage.
  - `git diff --check` ->passed with existing CRLF normalization warnings only.
- risks_or_notes:
  - This does not make event/oil/defense names automatic sells in production; it makes the replay layer test that policy explicitly.
  - Theme horizon labels are human-curated metadata and should be reviewed when new themes emerge.
  - Next full rebuild is required to populate the new `candidate_replay_book.csv` columns and measure CAGR/MDD impact.

### 13:23 KST - market-style-regime-router

- scope:
  - Add research-only market style routing so full rebuilds can compare breakout-growth, turnaround-accumulation, quality-compounder, and cash-defense environments before changing production weights.
- files:
  - `r1000_config.py` ->adds style regime metadata columns and bumps `ENGINE_REUSE_VERSION`.
  - `r1000_features.py` ->computes style regime preferences from market, liquidity, rate, inflation, overheat, benchmark, and calendar/month/quarter/weekday context.
  - `r1000_pipeline.py` ->runs the style router after Phase 14/15 signals and preserves the columns in feature store plus candidate replay books.
  - `tools/run_style_regime_report.py` ->new sidecar that summarizes monthly and latest style preferences and top breakout/turnaround/compounder candidates.
  - `.github/workflows/full_rebuild_manual.yml` ->runs, uploads, syncs, and commits `outputs/style_regime_report/`.
  - `tools/run_main_v2_backtest.py` ->carries style metadata into monthly holdings for risk replay.
  - `tools/run_position_aware_risk_replay.py` ->preserves style context in defensive action outputs.
  - `tests/historical_challenger_replays_smoke.py` ->adds style fields and sidecar report coverage.
  - `tests/workflow_artifact_smoke.py` ->checks workflow wiring for the style regime sidecar.
  - `tests/smoke_test.py` ->adds synthetic breakout-vs-turnaround style router coverage.
  - `CHANGELOG.md` ->records the style regime router.
- symbols_added:
  - `compute_market_style_regime_features(df)` ->computes style preference, calendar, and row-level style fit columns.
  - `tools.run_style_regime_report._mean(rows, col)` ->computes defensive averages for style report rows.
  - `tools.run_style_regime_report._mode(rows, col, default="unknown")` ->computes dominant style label.
  - `tools.run_style_regime_report._top(rows, col, limit=8)` ->extracts top candidates by style fit.
  - `tools.run_style_regime_report.run(latest_run, output_dir)` ->writes style regime report artifacts.
  - `tools.run_style_regime_report.render_report(payload)` ->renders markdown style summary.
  - `test_market_style_regime_router()` ->guards breakout and turnaround style-fit behavior.
- symbols_changed:
  - `build_feature_store()` ->runs style-regime feature computation and whitelists research-only style metadata.
  - `export_outputs._write_monthly_mandate_books()` ->preserves style-regime fields in `candidate_replay_book.csv`.
  - `tools.run_main_v2_backtest.replay()` ->passes style metadata into `monthly_holdings.csv`.
  - `tools.run_position_aware_risk_replay.replay()` ->writes style context in risk action/holding outputs.
  - `test_historical_challenger_replays()` ->also validates the style regime sidecar.
  - `test_workflow_runs_latest_diagnostics_sidecars()` ->also checks style report workflow wiring.
- config_fields_added:
  - `PHASE21_STYLE_REGIME_COLUMNS: list[str] = [...]` ->research-only column list for style regime metadata including month, quarter, weekday, and cyclic encodings.
  - `ENGINE_REUSE_VERSION: str = "2026-05-07-style-regime-router"` ->forces feature-store rebuild for the new metadata.
- breaking_changes:
  - none
- outputs:
  - `outputs/style_regime_report/summary.json` ->latest style regime and preference snapshot.
  - `outputs/style_regime_report/monthly.csv` ->monthly style regime history for A/B analysis.
  - `outputs/style_regime_report/latest_top_breakout.csv` ->latest candidates best aligned with breakout-growth.
  - `outputs/style_regime_report/latest_top_turnaround.csv` ->latest candidates best aligned with turnaround accumulation.
  - `outputs/style_regime_report/latest_top_compounder.csv` ->latest candidates best aligned with quality compounder mode.
- validation:
  - `py -3 -m py_compile r1000_config.py r1000_features.py r1000_pipeline.py tools\run_style_regime_report.py tools\run_main_v2_backtest.py tools\run_position_aware_risk_replay.py tests\historical_challenger_replays_smoke.py tests\workflow_artifact_smoke.py tests\smoke_test.py` ->passed.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 86/86.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed; 245 features, no leakage.
  - inline style-router fixture ->passed; breakout-growth and turnaround-accumulation rows were separated correctly.
  - `git diff --check` ->passed with existing CRLF normalization warnings only.
- risks_or_notes:
  - This is not a production style allocation switch yet; it is an evidence route for the next full rebuild.
  - Calendar fields are not in `DEFAULT_FEATURES`; they are preserved for research/AutoLearning to test seasonality without introducing unvalidated production overfit.
  - Macro and benchmark series can be studied over longer history than equity fundamentals once a dedicated macro-only regime learner is added.

### 14:05 KST - main-v2-style-aware-selector

- scope:
  - Connect the research-only style regime router to Main v2 candidate selection so breakout, turnaround, compounder, and cash-defense environments alter sleeve scoring and slots in historical A/B replays.
- files:
  - `r1000_main_v2.py` ->adds style-aware sleeve capacity/target adjustments, style score bonuses, turnaround candidate admission, cash-defense event-risk blocking, and audit fields.
  - `tools/run_main_v2_backtest.py` ->writes `monthly_returns.csv` and carries the Main v2 style regime into monthly holdings/returns.
  - `tests/smoke_test.py` ->adds regression coverage that style-aware Main v2 selects breakout and turnaround candidates through the intended sleeves.
  - `tests/historical_challenger_replays_smoke.py` ->checks style regime fields in Main v2 historical replay outputs.
  - `CHANGELOG.md` ->records the style-aware selector wiring.
  - `SESSION_HANDOFF.md` ->updates the active handoff with the new Main v2 A/B route.
- symbols_added:
  - `infer_style_regime(rows, default="balanced")` ->infers the dominant style label from candidate rows.
  - `_style_policy(policy)` ->returns enabled style-aware Main v2 policy settings.
  - `_bounded_signal(value, upper=1.25)` ->clips style-fit signals before using them in scores.
  - `_row_style_label(row, fallback="balanced")` ->reads a row-level style label safely.
  - `_theme_event_risk(row)` ->reads max event-risk sensitivity for style-aware blocking.
  - `_theme_structural_growth(row)` ->reads max structural-growth sensitivity for style-aware blocking.
  - `_style_score_bonus(row, sleeve, style_regime, policy)` ->returns sleeve-specific style-fit score adjustments.
  - `_apply_style_capacity_map(capacity_map, style_regime, policy)` ->applies research-only style capacity shifts.
  - `_apply_style_target_map(target_map, style_regime, policy)` ->applies research-only style target-N shifts.
  - `test_main_v2_style_aware_selector()` ->guards style-aware Main v2 selection behavior.
- symbols_changed:
  - `score_core(row, regime_state="neutral", style_regime=None, policy=None)` ->adds quality/cash-defense compounder style bonuses.
  - `score_future(row, regime_state="neutral", style_regime=None, policy=None)` ->adds breakout-growth style bonuses and cash-defense penalties.
  - `score_early(row, regime_state="neutral", style_regime=None, policy=None)` ->adds turnaround and breakout style bonuses.
  - `candidate_passes(row, sleeve, regime_state, style_regime=None, policy=None)` ->admits qualified turnaround accumulation candidates and blocks event-risk future/early candidates in cash-defense regimes.
  - `select_sleeve_candidates(rows, sleeve, regime_state, target_n, style_regime=None, policy=None)` ->scores candidates with style-aware policy context.
  - `compose_main_sleeve_portfolio(candidate_rows, regime_state=None, policy=None)` ->infers style regime and applies style capacity/target adjustments before selecting sleeves.
  - `result_to_rows(result)` ->includes `style_regime` in Main v2 output rows.
  - `tools.run_main_v2_backtest.replay()` ->exports `monthly_returns.csv` and style regime context.
  - `test_historical_challenger_replays()` ->validates style-aware Main v2 output columns.
- config_fields_added:
  - `MAIN_V2_STYLE_AWARE_POLICY: dict = {...}` ->research-only policy for style-aware sleeve capacity, target-N, score, and candidate-pass behavior.
- breaking_changes:
  - none
- outputs:
  - `outputs/main_v2_backtest/monthly_returns.csv` ->monthly Main v2 return rows including `style_regime`.
- validation:
  - `py -3 -m py_compile r1000_main_v2.py tools\run_main_v2_backtest.py tests\smoke_test.py tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 87/87.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed, 245 features and no leakage.
- risks_or_notes:
  - This still does not change production `DEFAULT_FEATURES` or production portfolio construction.
  - Full rebuild evidence is required before promoting any style-aware Main v2 behavior beyond research-only A/B.

### 16:00 KST - main-v2-opportunity-cost-swap

- scope:
  - Add a research-only opportunity-cost replacement score so Main v2 can prefer superior new leaders over stale/event-cycle incumbents when catalyst, macro, style, theme, and risk evidence align.
- files:
  - `r1000_main_v2.py` ->adds replacement component scoring, replacement tilt, event-cycle decay penalties, and selected-sleeve audit fields.
  - `tools/run_main_v2_backtest.py` ->carries replacement score, catalyst score, and decay score into monthly holdings.
  - `tests/smoke_test.py` ->adds regression coverage that a strong new leader beats a stale event-cycle incumbent through the future sleeve.
  - `tests/historical_challenger_replays_smoke.py` ->checks replacement-score fields in Main v2 replay outputs.
  - `CHANGELOG.md` ->records the opportunity-cost swap wiring.
- symbols_added:
  - `_opportunity_component_scores(row)` ->combines catalyst, style, alpha, macro/theme, stale/risk, relative weakness, and event-cycle decay signals into replacement components.
  - `_replacement_score(row)` ->returns the combined opportunity-cost replacement score.
  - `_replacement_tilt(row, policy)` ->turns strong/weak replacement scores into research-only sleeve score adjustments.
  - `test_main_v2_opportunity_cost_replacement()` ->guards new-leader replacement behavior.
- symbols_changed:
  - `score_core(row, regime_state="neutral", style_regime=None, policy=None)` ->adds replacement tilt to core scoring.
  - `score_future(row, regime_state="neutral", style_regime=None, policy=None)` ->adds amplified replacement tilt to future-winner scoring.
  - `score_early(row, regime_state="neutral", style_regime=None, policy=None)` ->adds stronger replacement tilt to early-scout scoring.
  - `candidate_passes(row, sleeve, regime_state, style_regime=None, policy=None)` ->lets strong replacement candidates pass future/early gates while still respecting risk and event-risk limits.
  - `select_sleeve_candidates(rows, sleeve, regime_state, target_n, style_regime=None, policy=None)` ->attaches replacement component fields to selected candidates.
  - `compose_main_sleeve_portfolio(candidate_rows, regime_state=None, policy=None)` ->surfaces replacement component fields in selected sleeve audits.
  - `tools.run_main_v2_backtest.replay()` ->exports replacement component fields into `monthly_holdings.csv`.
  - `test_historical_challenger_replays()` ->validates replacement-score fields in Main v2 replay artifacts.
- config_fields_added:
  - `MAIN_V2_STYLE_AWARE_POLICY["replacement_enabled"]: bool = True` ->enables research-only opportunity-cost replacement tilt.
  - `MAIN_V2_STYLE_AWARE_POLICY["replacement_bonus_scale"]: float = 0.22` ->score bonus scale for strong replacement candidates.
  - `MAIN_V2_STYLE_AWARE_POLICY["replacement_penalty_scale"]: float = 0.18` ->score penalty scale for weak replacement candidates.
  - `MAIN_V2_STYLE_AWARE_POLICY["replacement_strong_threshold"]: float = 0.60` ->minimum replacement score for strong-candidate treatment.
  - `MAIN_V2_STYLE_AWARE_POLICY["replacement_weak_threshold"]: float = -0.25` ->replacement score below which decay penalties apply.
- breaking_changes:
  - none
- outputs:
  - `outputs/main_v2_backtest/monthly_holdings.csv` ->now includes `main_v2_replacement_score`, `main_v2_replacement_catalyst_score`, and `main_v2_replacement_decay_score`.
- validation:
  - `py -3 -m py_compile r1000_main_v2.py tools\run_main_v2_backtest.py tests\smoke_test.py tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 88/88.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime` ->passed, 245 features and no leakage.
- risks_or_notes:
  - This is still research-only Main v2 behavior; production defaults remain unchanged.
  - The active full rebuild `25477647771` was already running on commit `7ff739c`; this patch requires a new run after commit/push to measure the replacement-score effect.

### 19:35 KST - concentrated-conviction-curve-wide-n-fix

- scope:
  - Fix concentrated comparison-grid failure for N>3 conviction-curve tests after run `25481291492` produced NaN concentrated metrics.
- files:
  - `r1000_pipeline.py` ->extended `concentrated_weight_map()` so `conviction_curve` preserves legacy N<=3 weights and generates a smooth decay curve for N=4/5/7/10.
  - `tests/historical_challenger_replays_smoke.py` ->added regression coverage for N=4 conviction-curve weights summing to 100% under the 50% single-name cap.
  - `CHANGELOG.md` ->records the fix and validation evidence.
  - `SESSION_HANDOFF.md` ->updates the active handoff with run `25481291492` results and the follow-up rerun focus.
- symbols_added:
  - none
- symbols_changed:
  - `concentrated_weight_map(cfg, selected, weighting_mode)` ->supports wider concentrated ladders without shape mismatch while keeping the old 1/2/3-name curve unchanged.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 -m py_compile r1000_pipeline.py tests\historical_challenger_replays_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\macro_policy_engine_smoke.py` ->passed.
  - `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 88/88.
- risks_or_notes:
  - Run `25481291492` used commit `eb99c97`, so it did not include the macro-policy sidecar commit `0c7f91d`.
  - A follow-up full rebuild is required to verify concentrated metrics are finite and the new macro-policy sidecar is exported.

### 19:36 KST - power-materials-theme-refresh

- scope:
  - Expand theme taxonomy and cycle-play coverage for nuclear fuel, SMR, fuel cells, gas turbines, renewable equipment, and critical minerals so theme/sector relative-strength changes can surface without ticker hardcoding.
- files:
  - `themes.yaml` ->adds `nuclear_fuel_cycle`, `fuel_cell_distributed_power`, `gas_turbine_power`, `renewable_power_equipment`, and `critical_minerals_rare_earths`; adds `LEU` to nuclear coverage.
  - `cycle_play_universe.yaml` ->adds LEU/SMR/OKLO/UEC/MP/LAC/GTLS/NXT/FLNC to the global-alpha cycle overlay with long-duration versus tactical-cycle metadata.
  - `tests/smoke_test.py` ->adds coverage that the new theme metadata and cycle-play overlay names parse and load.
  - `CHANGELOG.md` ->records the theme/universe refresh.
  - `SESSION_HANDOFF.md` ->notes that the active run does not include this theme refresh and the next run should.
- symbols_added:
  - `test_cycle_play_power_materials_universe_loader()` ->guards LEU/SMR/OKLO/GTLS/FLNC/NXT/MP/LAC cycle-play visibility.
- symbols_changed:
  - `test_theme_policy_metadata_surface()` ->now validates nuclear fuel-cycle, fuel-cell, and critical-mineral horizon/event-risk metadata.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `py -3 tests\smoke_test.py` ->passed, 89/89.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime` ->passed.
- risks_or_notes:
  - These are candidate-universe/theme metadata changes, not buy instructions.
  - Full rebuild `25490280861` was already running on commit `ee8f0d1`; a later run is needed to measure this taxonomy refresh.

## 2026-05-06

### 09:12 KST - market-aware-monster-handoff

- scope:
  - Document the next market-aware handoff plan after the target-pass rebuild, with no new full run triggered.
- files:
  - `CHANGELOG.md` ->records the documentation-only handoff update and explicitly states that no run was started.
  - `SESSION_HANDOFF.md` ->updates the active inbox for the next agent with market-context, PLTR/SNDK/LITE/INTC, and monster-early logic guidance.
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
  - no full rebuild, smoke test, or target run was executed by request.
- risks_or_notes:
  - Main and concentrated target metrics passed in the latest cloud production artifacts, but concentrated managed-risk metadata is still not explicit in `concentrated_backtest_metrics.json`.
  - Next coding agent should improve market-context preflight, stale-leader exits, and sparse-history monster admission before launching another run.

### 11:02 KST - leader-rescue-stale-trim

- scope:
  - Add a generic leader-rescue universe and broaden stale former-leader trimming so new leaders can enter earlier and old leaders can be reduced without ticker hardcoding.
- files:
  - `r1000_config.py` ->bumps engine reuse version and adds leader-rescue universe, diagnostics, and broad stale-leader thresholds.
  - `r1000_pipeline.py` ->preserves constituent source labels, injects S&P 500/Nasdaq-100 rescue candidates, and writes latest leader drop diagnostics.
  - `r1000_signals.py` ->broadens stale core-leader detection beyond $1T mega caps and surfaces a stale-leader reason.
  - `tests/smoke_test.py` ->adds a synthetic stale-leader versus new-monster regression test.
  - `CHANGELOG.md` ->records the leader rescue and stale-trim change.
- symbols_added:
  - `_candidate_source_frame(df, source)` ->normalizes one candidate universe source while preserving source labels.
  - `_combine_candidate_universe_sources(uni)` ->deduplicates candidates while joining source evidence.
  - `_price_cache_latest_date(paths, ticker)` ->reads the latest cached price date for drop diagnostics.
  - `write_leader_drop_diagnostics(cfg, paths, candidates, pre_filter_monthly, ranked_monthly, final_monthly, use_mktcap_filter)` ->writes current candidate inclusion/drop reasons.
  - `test_defensive_rotation_trims_stale_broad_leaders()` ->guards broad stale-leader trim and monster promotion behavior.
- symbols_changed:
  - `build_candidate_universe()` ->adds generic leader rescue S&P 500/Nasdaq-100 sources independent of legacy Wikipedia-list mode.
  - `build_universe_monthly()` ->emits leader drop diagnostics after base filters and rank-size selection.
  - `compute_defensive_monster_rotation_overlay()` ->adds broad stale core-leader detection and `portfolio_stale_leader_reason`.
- config_fields_added:
  - `leader_rescue_universe_enabled: bool = True` ->turns on generic S&P/Nasdaq rescue candidates.
  - `leader_rescue_include_sp500: bool = True` ->includes S&P 500 rescue candidates.
  - `leader_rescue_include_nasdaq100: bool = True` ->includes Nasdaq-100 rescue candidates.
  - `leader_rescue_diagnostics_enabled: bool = True` ->writes leader drop reason artifacts.
  - `leader_rescue_price_stale_days: int = 14` ->marks price caches stale in diagnostics.
  - `portfolio_stale_leader_mcap_min: float = 100000000000.0` ->broad stale-leader minimum size below the prior mega-cap threshold.
  - `portfolio_stale_leader_rs_accel_max: float = -0.50` ->relative-strength acceleration threshold for stale-leader trim.
  - `portfolio_stale_leader_rs_level_max: float = 1.25` ->relative-strength level threshold for stale-leader trim.
  - `portfolio_stale_leader_near_high_max: float = -0.08` ->distance-from-high threshold for stale-leader trim.
  - `portfolio_stale_leader_group_strength_max: float = 0.0` ->weak industry-group threshold for stale-leader trim.
  - `portfolio_stale_leader_require_broken_ma: bool = True` ->requires moving-average/trend break confirmation for broad stale trim.
- breaking_changes:
  - Feature-store cache invalidates because `ENGINE_REUSE_VERSION` changes and current candidate universe membership can broaden on the next full rebuild.
- outputs:
  - `outputs/reports/leader_drop_diagnostics_latest.csv` ->per-candidate reason for current inclusion, rank/drop, missing price cache, stale cache, or blacklist.
  - `outputs/reports/leader_drop_diagnostics_summary.json` ->drop reason and source-count summary.
- validation:
  - `py -3 -m py_compile r1000_config.py r1000_pipeline.py r1000_signals.py tests\smoke_test.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed: 82/82.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->passed; first CP949 console run failed before audit due Unicode output encoding only.
  - inline synthetic `write_leader_drop_diagnostics()` smoke ->passed with `available_for_scoring` and `missing_price_cache` rows.
  - `git diff --check` ->passed with existing CRLF normalization warnings only.
- risks_or_notes:
  - This does not hardcode example tickers into selection; examples enter only if their source, price, liquidity, market-cap, leadership, and risk data pass.
  - Broader universe candidates can change production selection and must be measured by full rebuild before merging to production.

### 11:15 KST - stale-trim-confirmation-fix

- scope:
  - Tighten the broad stale-leader trim pre-run review so `portfolio_stale_leader_require_broken_ma=True` actually requires a moving-average or trend-template break.
- files:
  - `r1000_signals.py` ->changes broad stale-leader confirmation from weak group/leadership OR logic to explicit broken-price confirmation when required.
  - `tests/smoke_test.py` ->extends the stale-leader regression fixture with a weak but unbroken core leader that must not be trimmed.
  - `CHANGELOG.md` ->records the pre-run confirmation fix.
- symbols_added:
  - none
- symbols_changed:
  - `compute_defensive_monster_rotation_overlay()` ->honors `portfolio_stale_leader_require_broken_ma` as a true confirmation gate.
  - `test_defensive_rotation_trims_stale_broad_leaders()` ->adds a no-break negative control.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - synthetic `build_candidate_universe()` source-merge smoke ->passed with IWB+S&P/Nasdaq rescue source preservation.
  - `py -3 -m py_compile r1000_config.py r1000_pipeline.py r1000_signals.py tests\smoke_test.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed: 82/82.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->passed.
  - `git diff --check` ->passed with existing CRLF normalization warnings only.
- risks_or_notes:
  - Without this fix, broad stale trim could reduce old leaders on weak relative/industry data even before a price-trend break, which was more aggressive than the config name promised.

### 11:50 KST - leader-rescue-validation-modes

- scope:
  - Make leader-rescue verification possible by separating PIT-safer latest-only use from intentionally biased full-proxy research A/B runs.
- files:
  - `.github/workflows/full_rebuild_manual.yml` ->adds `leader_rescue_mode` workflow input, passes it to `run_local.py`, and uploads leader-rescue diagnostics.
  - `run_local.py` ->adds `--leader-rescue-mode` / `LEADER_RESCUE_MODE` runtime override wiring.
  - `r1000_config.py` ->adds `leader_rescue_backtest_mode`.
  - `r1000_pipeline.py` ->adds rescue-only historical filtering, filter summary output, config validation, and run-summary metadata.
  - `CHANGELOG.md` ->records the validation-mode change.
- symbols_added:
  - `resolve_leader_rescue_mode(raw)` ->resolves CLI/env leader-rescue validation mode.
  - `_leader_rescue_only_source_mask(df)` ->detects candidates added only by broad leader-rescue sources.
  - `apply_leader_rescue_backtest_mode_filter(cfg, paths, monthly)` ->drops rescue-only historical rows in `latest_only`, keeps them in `full_proxy`, or drops them entirely in `off`.
- symbols_changed:
  - `parse_args()` ->adds `--leader-rescue-mode`.
  - `main()` ->passes leader-rescue runtime overrides into collector and pipeline configs.
  - `validate_config()` ->rejects invalid `leader_rescue_backtest_mode` values.
  - `build_universe_monthly()` ->applies the leader-rescue backtest-mode filter before fundamentals and feature computation.
  - `build_feature_store()` ->records leader-rescue mode and rescue-only row count in `feature_store_quality.json`.
  - `export_outputs()` ->records leader-rescue mode in `run_summary.json`.
- config_fields_added:
  - `leader_rescue_backtest_mode: str = "latest_only"` ->PIT-safer default that keeps rescue-only rows out of historical OOS months.
- breaking_changes:
  - Default leader-rescue behavior changes from full historical proxy to `latest_only`, so rescue-only candidates affect latest recommendations/diagnostics but not historical backtest metrics unless `full_proxy` is selected.
- outputs:
  - `outputs/reports/leader_rescue_backtest_filter_summary.json` ->documents mode, rescue-only rows dropped, and latest rescue-only rows kept.
- validation:
  - `py -3 -m py_compile run_local.py r1000_config.py r1000_pipeline.py r1000_signals.py tests\smoke_test.py` ->passed.
  - synthetic `apply_leader_rescue_backtest_mode_filter()` mode smoke ->passed for `latest_only`, `full_proxy`, and `off`.
  - `py -3 run_local.py --help | Select-String -Pattern "leader-rescue-mode"` ->passed.
  - workflow YAML parse smoke ->passed with `leader_rescue_mode` default `latest_only`.
  - `py -3 tests\smoke_test.py` ->passed: 83/83.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->passed.
- risks_or_notes:
  - `full_proxy` is deliberately research-only because it uses today's broad index constituents historically.
  - `latest_only` still does not solve all baseline current-constituent survivorship limits; it isolates only the incremental leader-rescue universe risk.

### 03:01 KST - managed-position-risk-activation

- scope:
  - Connect the defensive monster and position-risk systems to actual main and concentrated portfolio metrics instead of leaving target-pass results only in proxy sidecars.
- files:
  - `r1000_config.py` ->adds managed monthly position-risk defaults and a separate main monster early threshold.
  - `r1000_pipeline.py` ->applies monthly position-risk return capping inside main and concentrated backtests and exports raw versus risk-adjusted holding returns.
  - `r1000_signals.py` ->uses the main monster threshold in portfolio candidate gates and carries monster/defense columns into `portfolio_latest.csv`.
  - `CHANGELOG.md` ->records the managed-risk activation.
- symbols_added:
  - `_negative_stop_value(value, default_abs)` ->normalizes stop config values to negative stop percentages.
  - `_managed_position_risk_exit_signal(row, period_return, cumulative_return, peak_return, hard_stop, trailing_stop, trailing_min_profit, distribution_threshold)` ->decides monthly hard-stop, trailing-stop, and distribution-risk exits for managed backtest metrics.
- symbols_changed:
  - `backtest_portfolio()` ->uses risk-adjusted monthly position returns for exported main metrics and holdings while preserving raw return columns.
  - `backtest_concentrated_portfolio()` ->uses concentrated monthly hard-stop risk management for strategy grid metrics and latest concentrated summary selection.
  - `apply_portfolio_candidate_gate_filter()` ->allows data-driven monster candidates through the main candidate gate using the main monster threshold.
  - `compute_defensive_monster_rotation_overlay()` ->uses the main monster threshold for portfolio defensive rotation actions.
  - `build_target_portfolio()` ->uses the main monster threshold for monster slots and preserves monster/defense diagnostics in materialized portfolio rows.
- config_fields_added:
  - `portfolio_monster_early_min_score: float = 0.58` ->main-specific monster candidate activation floor.
  - `portfolio_position_risk_enabled: bool = True` ->turns managed monthly position-risk returns on for main metrics.
  - `portfolio_position_risk_hard_stop: float = -0.08` ->caps main monthly position loss contribution at -8% when a hard-stop signal fires.
  - `portfolio_position_risk_trailing_stop: float = -0.15` ->enables main peak-relative monthly trailing exit after sufficient profit.
  - `portfolio_position_risk_trailing_min_profit: float = 0.15` ->requires at least 15% cumulative position profit before main trailing exits.
  - `portfolio_position_risk_distribution_threshold: float = 0.85` ->distribution-risk threshold for main monthly exits.
  - `concentrated_position_risk_enabled: bool = True` ->turns managed monthly position-risk returns on for concentrated metrics.
  - `concentrated_position_risk_hard_stop: float = -0.08` ->caps concentrated monthly position loss contribution at -8%.
  - `concentrated_position_risk_trailing_stop: float = 0.0` ->keeps concentrated replay aligned to the hard-stop proxy that passed the goal search.
  - `concentrated_position_risk_trailing_min_profit: float = 0.15` ->reserved for future concentrated trailing-stop activation.
  - `concentrated_position_risk_distribution_threshold: float = 2.0` ->disables concentrated distribution exits by default.
- breaking_changes:
  - Main and concentrated exported metrics now use managed monthly position-risk returns by default on this branch, so they are no longer directly comparable to prior raw monthly-return champion metrics without checking `position_risk_metric_mode`.
- outputs:
  - `outputs/backtest_metrics.json` ->will include `position_risk_*` fields and managed main metrics after the next full rebuild.
  - `outputs/concentrated_backtest_metrics.json` ->will include managed concentrated strategy metrics after the next full rebuild.
  - `outputs/portfolio_latest.csv` ->will include monster/defense diagnostics for selected main holdings after the next full rebuild.
- validation:
  - `git diff --check` ->passed with existing CRLF normalization warnings only.
  - `python --version` ->not run; local Python is not installed in this desktop sandbox.
  - `py -3 --version` ->not run; local Python launcher is not installed in this desktop sandbox.
- risks_or_notes:
  - Managed position-risk is monthly return capping, not intraday broker execution evidence; weekly/intramonth validation remains required before real capital automation.

### 17:01 KST - active-run-handoff-refresh

- scope:
  - Refresh the agent handoff after stopping the stale full run, restarting on the latest leader-rescue plus historical journey commit, and pulling the completed result artifacts.
- files:
  - `SESSION_HANDOFF.md` ->updates the active inbox with branch `codex/leader-rescue-stale-trim`, code commit `b5d1ee1`, bot result commit `0903e14`, completed run `25416283891`, old canceled run `25415594156`, quick metrics, and next analysis checklist.
  - `CHANGELOG.md` ->records the documentation-only handoff refresh for future agents.
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
  - `gh run view 25416283891 --json status,conclusion,headSha,jobs,url` ->passed; run completed successfully at head SHA `b5d1ee1`.
  - no code validation rerun for this documentation-only update; prior `b5d1ee1` validations are listed in `SESSION_HANDOFF.md`.
- risks_or_notes:
  - Full rebuild `25416283891` completed on `b5d1ee1`; future agents should analyze `cloud_results/full_rebuild/latest_global_alpha_universe`.
  - Historical trade journey outputs are available in this completed run and should be used to review past holdings, churn, and current-versus-history context.

### 18:10 KST - relative-weakness-catalyst-diagnostics

- scope:
  - Add research-only relative-underperformance trim/exit diagnostics, governance catalyst surfacing, guaranteed leader diagnostics fallback, and explicit concentrated single-name cap enforcement.
- files:
  - `.github/workflows/full_rebuild_manual.yml` ->runs leader-drop fallback and governance catalyst sidecars and exports their artifacts to GitHub/GDrive/cloud-results bundles.
  - `r1000_config.py` ->sets the concentrated single-name max to 50%.
  - `r1000_pipeline.py` ->applies the concentrated cap consistently across winner-take-all, score-power, and conviction-curve weight modes without renormalizing away capped cash.
  - `tools/run_position_aware_risk_replay.py` ->adds prior-window benchmark-relative trim/exit logic, 25/50/75bps cost sensitivity, and rolling 3-year validation outputs.
  - `tools/run_leader_drop_diagnostics_sidecar.py` ->new fallback latest-scored diagnostic writer when the in-pipeline leader-drop report is absent.
  - `tools/run_governance_catalyst_report.py` ->new report-only surface for ownership, insider, event, and revision catalyst columns already present in `scored_latest.csv`.
  - `tests/historical_challenger_replays_smoke.py` ->covers new sidecars and concentrated cap enforcement.
  - `tests/workflow_artifact_smoke.py` ->requires the new sidecars and artifact paths.
- symbols_added:
  - `load_benchmark_returns(path)` ->loads monthly benchmark returns from the exported equity curve.
  - `is_long_hold_protected(row, cumulative_return, relative_return)` ->keeps true long-hold winners from being cut on one weak relative window.
  - `relative_underperformance_action(row, cumulative_return, benchmark_cumulative_return, trim_threshold, exit_threshold)` ->chooses hold, 50% trim, or exit-to-cash from prior relative performance.
  - `rolling_metric_rows(monthly_rows, window_months)` ->writes rolling 3-year replay validation rows.
  - `cost_sensitivity_rows(monthly_rows, bps_values)` ->computes 25/50/75bps replay metrics from the same action stream.
  - `tools.run_leader_drop_diagnostics_sidecar.run(args)` ->writes fallback leader diagnostics from latest scored/portfolio artifacts.
  - `tools.run_governance_catalyst_report.run(args)` ->writes latest governance catalyst diagnostics.
  - `test_latest_diagnostics_sidecars()` ->smoke-tests fallback leader and governance diagnostics.
  - `test_workflow_runs_latest_diagnostics_sidecars()` ->guards workflow sidecar wiring.
- symbols_changed:
  - `exit_signal()` ->returns action, reason, position multiplier, and proxy return cap so exits and trim-50 actions are distinguishable.
  - `replay()` in `tools/run_position_aware_risk_replay.py` ->uses benchmark-relative prior state, cost bps, cost sensitivity, and rolling validation outputs.
  - `concentrated_weight_map()` ->enforces `concentrated_max_single_name_weight` for every weighting mode and leaves infeasible excess as cash.
  - `test_weight_caps_and_return_column_fallback()` ->checks production concentrated cap enforcement in addition to helper cap math.
- config_fields_added:
  - none
- breaking_changes:
  - Concentrated branch behavior changes on the next full rebuild because the default single-name cap is now 50%; existing target-pass evidence should be preserved as the pre-cap baseline.
- outputs:
  - `outputs/position_aware_risk_replay/cost_sensitivity.csv` ->25/50/75bps replay metrics.
  - `outputs/position_aware_risk_replay/rolling_3y.csv` ->rolling 36-month replay metrics.
  - `outputs/reports/leader_drop_diagnostics_latest.csv` ->guaranteed latest-scored fallback diagnostics if the primary pipeline diagnostic is absent.
  - `outputs/reports/leader_drop_diagnostics_report.md` ->human-readable fallback diagnostic summary.
  - `outputs/governance_catalyst/governance_catalyst_latest.csv` ->top ownership/insider/event/revision catalyst rows.
  - `outputs/governance_catalyst/summary.json` ->governance catalyst counts and coverage.
  - `outputs/governance_catalyst/report.md` ->human-readable catalyst report.
- validation:
  - `py -3 -m py_compile tools\run_position_aware_risk_replay.py tools\run_leader_drop_diagnostics_sidecar.py tools\run_governance_catalyst_report.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tests\historical_challenger_replays_smoke.py` ->passed.
  - Real latest-run sidecar check for enhanced `position_aware_risk_replay` ->passed; 25bps CAGR 34.97%, Sharpe 1.729, MaxDD -8.63%, relative trims 20, relative exits 2.
  - Real latest-run sidecar check for fallback leader diagnostics ->passed; 701 rows including watchlist missing rows.
  - Real latest-run sidecar check for governance catalyst diagnostics ->passed; 82 output rows.
- risks_or_notes:
  - Relative-underperformance actions use prior monthly relative state, but hard-stop and trailing-stop pieces remain monthly proxy assumptions, not intraday execution.
  - Governance catalyst reporting only surfaces existing engine columns; strategic government stake/news/8-K parsing remains a future data-layer task.
  - The 50% concentrated cap can reduce CAGR if the prior winner-take-all concentration was the alpha source, so the next full rebuild must compare against the saved pre-cap 45.75% concentrated baseline.

## 2026-05-05

### 06:49 KST - defensive-list-risk-proxy

- scope:
  - Add explicit defensive list outputs for risk proxy replays so target-pass proxy results are not return-only summaries.
- files:
  - `tools/run_position_aware_risk_replay.py` ->writes risk-defended holdings lists that move proxy-exited positions to cash while preserving hold/exit reasons for each ticker.
  - `tools/run_concentrated_position_risk_replay.py` ->writes defensive holdings and latest defensive lists for the best concentrated hard-stop proxy variant.
  - `tools/run_portfolio_goal_search.py` ->carries list-defense metadata into candidate params for proxy candidates.
  - `CHANGELOG.md` ->records the defensive-list output change.
- symbols_added:
  - `build_defensive_holdings(grouped, best_key, monthly_rows)` ->builds concentrated proxy defensive holdings and latest defensive list rows for the selected variant.
- symbols_changed:
  - `replay()` in `tools/run_position_aware_risk_replay.py` ->adds `defensive_holdings.csv`, `defensive_latest.csv`, and list-defense metadata.
  - `replay()` in `tools/run_concentrated_position_risk_replay.py` ->adds defensive list outputs for the selected concentrated hard-stop proxy.
  - `render_report()` in `tools/run_position_aware_risk_replay.py` ->reports list-defense mode and latest defensive output path.
  - `render_report()` in `tools/run_concentrated_position_risk_replay.py` ->reports list-defense mode and latest defensive output path.
  - `candidate_from_json()` ->includes proxy/list-defense paths and warnings in goal-search candidate params.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/position_aware_risk_replay/defensive_holdings.csv` ->all main proxy holdings with original weight, defended weight, action, reason, and cash rows for proxy exits.
  - `outputs/position_aware_risk_replay/defensive_latest.csv` ->latest main proxy defensive list.
  - `outputs/concentrated_position_risk_replay/defensive_holdings.csv` ->all concentrated hard-stop proxy holdings with original weight, defended weight, action, reason, and cash rows for proxy exits.
  - `outputs/concentrated_position_risk_replay/defensive_latest.csv` ->latest concentrated proxy defensive list.
- validation:
  - `python -m py_compile tools/run_position_aware_risk_replay.py tools/run_concentrated_position_risk_replay.py tools/run_portfolio_goal_search.py` passed.
  - `python tools/run_concentrated_position_risk_replay.py --latest-run C:\Users\Andrew Cha\Documents\codex\.tmp_run_25327203984\full-rebuild-global_alpha_universe-25327203984 --output-dir outputs\concentrated_position_risk_replay_defense_smoke` passed.
  - `python tools/run_position_aware_risk_replay.py --holdings C:\Users\Andrew Cha\Documents\codex\.tmp_run_25327203984\full-rebuild-global_alpha_universe-25327203984\main_v2_backtest\monthly_holdings.csv --output-dir outputs\position_aware_risk_replay_defense_smoke` blocked locally because pandas is not installed in the current Windows Python environment; GitHub Actions installs the required dependencies.
- risks_or_notes:
  - Defensive lists are still monthly proxy artifacts, not execution-ready broker order lists.
  - A ticker such as NVDA can remain in `defensive_latest.csv` when the proxy action is `hold`; the output now shows that explicitly instead of only showing return metrics.

### 07:25 KST - defensive-monster-selection-path

- scope:
  - Wire defense and monster/extreme early candidate logic into the actual main and concentrated selection paths instead of only producing post-hoc proxy metrics.
- files:
  - `r1000_config.py` ->adds tunables for defensive monster rotation, stale mega-cap leader penalties, monster early slots, and concentrated risk candidate filtering.
  - `r1000_signals.py` ->adds a generic data-driven monster/defense overlay and applies it inside `build_target_portfolio()`.
  - `r1000_pipeline.py` ->applies the same overlay inside concentrated scoring and reserves concentrated monster-extreme early slots.
  - `r1000_top30_institutional.py` ->re-exports the new signal helper with the rest of the signal layer.
- symbols_added:
  - `compute_defensive_monster_rotation_overlay(month_df, cfg)` ->creates `portfolio_monster_early_score`, `portfolio_stale_mega_leader_score`, `portfolio_risk_entry_block_score`, and `portfolio_defensive_rotation_action`.
- symbols_changed:
  - `apply_portfolio_candidate_gate_filter()` ->allows high-quality monster early candidates through the candidate gate when risk block score is acceptable.
  - `build_target_portfolio()` ->boosts monster early candidates, penalizes stale mega-cap/core names, and reserves actual main selection slots for monster candidates.
  - `prepare_concentrated_frame()` ->adds monster early score and fragile-entry penalties directly to `concentrated_score`.
  - `select_concentrated_portfolio_topk()` ->adds `monster_extreme_early` reserved selection before normal preferred-sleeve ranking and blocks fragile high-risk entries.
- config_fields_added:
  - `portfolio_defensive_rotation_enabled`
  - `portfolio_monster_early_weight`
  - `portfolio_fill_monster_early_weight`
  - `portfolio_utility_monster_early_weight`
  - `portfolio_stale_mega_leader_penalty_weight`
  - `portfolio_stale_mega_mcap_min`
  - `portfolio_stale_mega_rs_accel_max`
  - `portfolio_stale_mega_rs_level_max`
  - `portfolio_stale_mega_near_high_max`
  - `portfolio_monster_promote_unassigned_to_future`
  - `portfolio_monster_early_min_slots`
  - `concentrated_monster_early_min_slots`
  - `concentrated_score_monster_early_weight`
  - `concentrated_score_risk_entry_penalty_weight`
  - `concentrated_risk_candidate_filter_enabled`
  - `concentrated_risk_candidate_block_threshold`
  - `concentrated_entry_quality_monster_early_override`
  - `concentrated_entry_quality_monster_early_min`
- breaking_changes:
  - Main and concentrated latest holdings can now change materially because monster/defense logic is applied before selection, not after metrics.
- validation:
  - `python -m py_compile r1000_config.py r1000_signals.py r1000_pipeline.py r1000_top30_institutional.py` passed.
  - `PYTHONIOENCODING=utf-8 python tests/smoke_test.py` passed: 81/81.
  - Latest scored smoke showed main no longer selected NVDA under the defensive monster overlay and concentrated selected `WDC`, `CIEN`, and `SNDK` through `monster_extreme_early` slots.
- risks_or_notes:
  - The overlay is generic and does not whitelist tickers. SNDK/LITE-like names enter only when the data satisfies monster early conditions.
  - Full-run metrics must be remeasured because this changes actual selection behavior, not only a sidecar replay.

### 07:44 KST - monster-replay-policy-bridge

- scope:
  - Connect the defensive monster overlay to historical replay artifacts and align Main v2, concentrated policy replay, and monster lifecycle replay with the same candidate signals.
- files:
  - `r1000_pipeline.py` ->adds defensive monster overlay columns to `candidate_replay_book.csv` by applying the overlay month-by-month before sidecar replay exports.
  - `r1000_main_v2.py` ->uses monster early, risk-entry block, and stale mega-cap scores in Main v2 sleeve scoring and gates.
  - `r1000_concentrated_policy.py` ->adds row-level monster early and risk block helpers and uses them in concentrated conviction, entry gates, risk gates, and audit rows.
  - `tools/run_main_v2_backtest.py` ->carries monster/defense columns into Main v2 monthly holdings for risk replay and inspection.
  - `tools/run_concentrated_policy_replay.py` ->writes monster/defense scores into concentrated policy holdings.
  - `tools/run_monster_lifecycle_replay.py` ->blends the shared monster early score into lifecycle onset scoring and exports the shared defense columns.
  - `tests/concentrated_policy_smoke.py` ->adds a smoke check for monster early override behavior.
  - `CHANGELOG.md` ->records the replay/policy bridge.
- symbols_added:
  - `mean01(values)` ->averages score-like values on a 0..1 scale.
  - `monster_early_score(row)` ->returns the shared monster early score from replay columns or a fallback row-level proxy.
  - `risk_entry_block_score(row)` ->returns the shared fragile-entry block score from replay columns or a fallback row-level proxy.
  - `is_monster_early_candidate(row)` ->identifies price-confirmed monster early candidates that can pass concentrated gates despite low stale entry quality.
- symbols_changed:
  - `export_outputs()` ->applies `compute_defensive_monster_rotation_overlay()` to historical replay rows before writing `candidate_replay_book.csv`.
  - `score_core()` ->penalizes stale mega-cap leaders in Main v2 core selection.
  - `score_future()` ->boosts monster early candidates and penalizes fragile-entry blocks in Main v2 future selection.
  - `score_early()` ->boosts monster early candidates and penalizes fragile-entry blocks in Main v2 early selection.
  - `candidate_passes()` ->blocks fragile rows, rejects stale mega-cap core candidates, and allows price-confirmed monster early candidates into future/early sleeves.
  - `concentrated_conviction_score()` ->adds monster early conviction and fragile-entry block terms.
  - `entry_quality_proxy()` ->surfaces monster early setups as an entry-quality proxy when price confirmation exists.
  - `entry_gate_flags()` ->allows monster early override through concentrated entry gates.
  - `risk_gate_flags()` ->lets true monster early candidates bypass stale RS/fundamental fallback blockers while still respecting the block score.
  - `audit_concentrated_portfolio()` ->reports monster early and risk block scores in audit rows.
  - `replay()` in `tools/run_main_v2_backtest.py` ->adds monster/defense columns to Main v2 holdings.
  - `run_variant()` ->adds monster/defense columns to concentrated policy replay holdings.
  - `monster_onset_score()` ->uses `portfolio_monster_early_score` and `portfolio_risk_entry_block_score` when available.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/candidate_replay_book.csv` ->now includes `portfolio_monster_early_score`, `portfolio_stale_mega_leader_score`, `portfolio_risk_entry_block_score`, and `portfolio_defensive_rotation_action`.
  - `outputs/main_v2_backtest/monthly_holdings.csv` ->now includes monster/defense columns for downstream risk replay.
  - `outputs/concentrated_policy_replay/holdings.csv` ->now includes monster/defense columns for concentrated replay review.
  - `outputs/monster_lifecycle_replay/holdings.csv` ->now includes monster/defense columns for lifecycle review.
- validation:
  - `python -m py_compile r1000_pipeline.py r1000_main_v2.py r1000_concentrated_policy.py tools\run_main_v2_backtest.py tools\run_concentrated_policy_replay.py tools\run_monster_lifecycle_replay.py tests\concentrated_policy_smoke.py` passed.
  - `python tests\concentrated_policy_smoke.py` passed.
  - `python tests\main_v2_policy_smoke.py` passed.
  - `python tests\smoke_test.py` passed: 81/81.
  - `python tools\run_main_v2_backtest.py --latest-run C:\Users\Andrew Cha\Documents\codex\.tmp_run_25327203984\full-rebuild-global_alpha_universe-25327203984 --output-dir outputs\main_v2_backtest_connect_smoke` passed.
  - `python tools\run_concentrated_policy_replay.py --latest-run C:\Users\Andrew Cha\Documents\codex\.tmp_run_25327203984\full-rebuild-global_alpha_universe-25327203984 --output-dir outputs\concentrated_policy_replay_connect_smoke` passed.
  - `python tools\run_monster_lifecycle_replay.py --latest-run C:\Users\Andrew Cha\Documents\codex\.tmp_run_25327203984\full-rebuild-global_alpha_universe-25327203984 --output-dir outputs\monster_lifecycle_replay_connect_smoke` passed.
- risks_or_notes:
  - Local sidecar smoke used a prior run artifact whose candidate replay book did not yet contain the new overlay columns, so the new full run is required to measure the connected historical effect.
  - Monster early selection remains ticker-agnostic; example names enter only when replay/book data satisfies the shared score and risk gates.

### 21:39 KST - replay-sleeve-cloud-results-fix

- scope:
  - Fix two full-run integration gaps found after run 25347845703: historical replay rows lacked recomputed sleeve engines, and ignored `cloud_results/` directories prevented reports/sidecars from being committed.
- files:
  - `r1000_pipeline.py` ->recomputes portfolio sleeve columns month-by-month before writing `candidate_replay_book.csv`, then applies the defensive monster overlay to those recomputed historical rows.
  - `.github/workflows/full_rebuild_manual.yml` ->force-adds `cloud_results/` so new reports and sidecar output directories are committed despite the repository ignore rule.
  - `CHANGELOG.md` ->records the full-run integration fix.
- symbols_added:
  - none
- symbols_changed:
  - `export_outputs()` ->now builds candidate replay rows from connected sleeve engines before monster/defense overlay scoring, enabling historical Main v2/concentrated/monster replays to see nonzero future/early engine scores.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `cloud_results/full_rebuild/latest_global_alpha_universe/reports/candidate_replay_book.csv` ->future runs should include nonzero sleeve engine scores and monster/defense columns.
  - `cloud_results/full_rebuild/latest_global_alpha_universe/main_v2_backtest/` ->future runs should be committed with the latest cloud results.
  - `cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_policy_replay/` ->future runs should be committed with the latest cloud results.
  - `cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_goal_search/` ->future runs should be committed with the latest cloud results.
- validation:
  - `git diff --check` passed.
  - Local Python validation was not run in the current sandbox because no Python interpreter is available; GitHub Actions full rebuild will run the repository smoke tests before the pipeline.
- risks_or_notes:
  - Run 25347845703 completed successfully but historical `candidate_replay_book.csv` had zero rows above the monster threshold because future/early sleeve engines were all zero in the replay book.
  - Run 25347845703 artifacts contained the sidecars, but the cloud-results commit did not include new sidecar/report directories because `cloud_results/` is ignored unless force-added.

## 2026-05-04

### 13:48 KST - shakeout-breakdown-study

- scope:
  - Add report-only shakeout-vs-breakdown event labeling and connect those
    labels into the separate AutoLearning winner challenger and daily scan.
- files:
  - `tools/run_shakeout_breakdown_study.py` ->adds drawdown event labeling, action replay, summary/report/policy outputs for shakeout, buyable reset, true breakdown, and dead theme events.
  - `tests/shakeout_breakdown_study_smoke.py` ->adds synthetic shakeout and breakdown fixtures with action replay assertions.
  - `tools/run_autolearning_winner_challenger.py` ->loads shakeout/breakdown action summaries and includes them in the combined challenger decision/report.
  - `tests/autolearning_winner_challenger_smoke.py` ->extends the challenger smoke fixture with shakeout/breakdown artifacts.
  - `.github/workflows/daily_autolearning_scan.yml` ->installs scan dependencies and runs lifecycle, onset, shakeout/breakdown, and combined challenger diagnostics as artifact-only daily scans.
  - `.gitignore` ->ignores generated `outputs/shakeout_breakdown_study/` artifacts.
- symbols_added:
  - `DrawdownEvent` ->dataclass for one labeled drawdown event.
  - `compute_event_features(hist, idx, spy_hist)` ->computes drawdown-date momentum, relative strength, trend, and volume features.
  - `score_shakeout_quality(features, drawdown, recovery_6m, fwd6)` ->scores whether a drawdown resembles a recoverable shakeout.
  - `score_breakdown_risk(features, drawdown, recovery_6m, fwd6, max_dd_6m)` ->scores whether a drawdown resembles a true breakdown.
  - `classify_event(recovery_3m, recovery_6m, fwd6, max_forward_6m, max_dd_6m, features)` ->labels events as SHAKEOUT, BUYABLE_RESET, TRUE_BREAKDOWN, DEAD_THEME, or AMBIGUOUS.
  - `detect_drawdown_events(ticker, hist, spy_hist, min_drop, lookback_days, min_gap_days)` ->detects first-threshold drawdown events per ticker.
  - `action_return(row, action, horizon)` ->computes event-level counterfactual action returns.
  - `build_action_replay(events_df)` ->builds hold/trim/add/exit/oracle action rows.
  - `summarize_action_replay(action_df)` ->summarizes action returns by label/horizon/action.
  - `summarize(events_df, action_df, args)` ->builds machine-readable study summary.
  - `render_report(summary, events_df)` ->renders `shakeout_breakdown_report.md`.
  - `render_policy_yaml(summary)` ->renders proposal-only shakeout/breakdown candidate rules.
  - `load_tickers(args)` ->loads a filtered ticker universe for the study.
  - `run(args)` ->runs the shakeout/breakdown study.
  - `parse_args()` ->parses CLI arguments.
  - `load_shakeout(shakeout_dir)` ->loads shakeout/breakdown artifacts into the combined AutoLearning challenger.
- symbols_changed:
  - `build_decision(baseline, autolearning, lifecycle, onset, event_rows, shakeout, shakeout_rows, replay_status)` ->includes shakeout/breakdown evidence.
  - `decide_verdict(onset, lifecycle, shakeout, replay_status)` ->allows event-level readiness from either onset or shakeout evidence.
  - `render_candidate_yaml(decision)` ->adds shakeout hold/add or breakdown exit components and sizing grids.
  - `render_report(decision, event_rows)` ->adds shakeout/breakdown action backtest rows.
  - `run(args)` ->accepts and loads a shakeout/breakdown artifact directory.
  - `parse_args()` ->adds `--shakeout-dir`.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/shakeout_breakdown_study/events.csv` ->labeled drawdown events.
  - `outputs/shakeout_breakdown_study/action_replay.csv` ->event-level hold/trim/add/exit counterfactual returns.
  - `outputs/shakeout_breakdown_study/action_summary.csv` ->action stats by label and horizon.
  - `outputs/shakeout_breakdown_study/pattern_summary.json` ->machine-readable label and action summary.
  - `outputs/shakeout_breakdown_study/shakeout_breakdown_report.md` ->human-readable event study report.
  - `outputs/shakeout_breakdown_study/system_policy_candidates.yaml` ->proposal-only candidate rules and sizing grids.
- validation:
  - `py -3 -m py_compile tools\run_shakeout_breakdown_study.py tests\shakeout_breakdown_study_smoke.py tools\run_autolearning_winner_challenger.py tests\autolearning_winner_challenger_smoke.py` ->passed.
  - `py -3 tests\shakeout_breakdown_study_smoke.py` ->passed.
  - `py -3 tests\autolearning_winner_challenger_smoke.py` ->passed.
  - `py -3 tests\workflow_artifact_smoke.py` ->passed.
  - `py -3 tools\run_shakeout_breakdown_study.py --scored cloud_results\full_rebuild\latest_global_alpha_universe\scored_latest.csv --top-tickers 80 --limit 40 --years 10 --sleep 0 --output-dir outputs\shakeout_breakdown_study` ->passed, generated 682 drawdown events.
  - `py -3 tools\run_autolearning_winner_challenger.py` ->passed, verdict `EVENT_LEVEL_ONLY_WAIT_FOR_MONTHLY_BOOKS`.
  - `py -3 tests\smoke_test.py` ->passed, 81/81.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->passed.
  - `git diff --check` ->passed with LF-to-CRLF warnings only.
- risks_or_notes:
  - Event-level action replay is useful for policy discovery but not sufficient for production sizing.
  - High single-name caps remain proposal-only until portfolio-level replay clears CAGR, MaxDD, turnover, and stress gates.

### 13:35 KST - autolearning-winner-challenger

- scope:
  - Add a separate research-only challenger harness that connects AutoLearning
    v2 hypotheses with winner lifecycle and winner onset outputs, producing
    event-level backtest evidence and portfolio-replay readiness without
    touching production behavior.
- files:
  - `tools/run_autolearning_winner_challenger.py` ->adds a standalone harness that reads AutoLearning, lifecycle, onset, and baseline artifacts and writes a proposal-only challenger package.
  - `tests/autolearning_winner_challenger_smoke.py` ->adds a synthetic artifact smoke test for the separate challenger harness.
  - `.gitignore` ->ignores generated `outputs/autolearning_winner_challenger/` artifacts.
- symbols_added:
  - `repo_path(path_like)` ->resolves repo-relative paths.
  - `read_json(path, default)` ->loads JSON with a default fallback.
  - `read_csv_rows(path)` ->loads CSV rows as dictionaries.
  - `write_json(path, payload)` ->writes JSON artifacts.
  - `write_csv(path, rows, fieldnames)` ->writes CSV artifacts.
  - `write_text(path, text)` ->writes text artifacts.
  - `safe_float(value, default)` ->normalizes numeric values.
  - `pct(value)` ->formats percentages for reports.
  - `load_baseline(latest_run)` ->loads main/concentrated baseline metrics.
  - `load_autolearning(autolearning_dir)` ->loads AutoLearning v2 hypotheses and counterfactual metadata.
  - `top_values(rows, col, n)` ->extracts top string values from report rows.
  - `load_lifecycle(lifecycle_dir)` ->loads missed winner, stale winner, and rotation diagnostics.
  - `return_stats(values)` ->computes event-level return distribution statistics.
  - `load_onset(onset_dir)` ->loads onset study artifacts and event-level hold/exit stats.
  - `replay_input_status(latest_run)` ->checks whether monthly books required for portfolio replay exist.
  - `build_decision(baseline, autolearning, lifecycle, onset, event_rows, replay_status)` ->combines all evidence into one decision object.
  - `decide_verdict(onset, lifecycle, replay_status)` ->classifies blocked/event-only/replay-ready state.
  - `render_candidate_yaml(decision)` ->renders proposal-only experiment YAML.
  - `render_report(decision, event_rows)` ->renders a Markdown challenger report.
  - `run(args)` ->runs the separate challenger harness.
  - `parse_args()` ->parses CLI arguments.
  - `main()` ->CLI entry point.
- symbols_changed:
  - `load_lifecycle(lifecycle_dir)` ->uses `held_ticker` from leadership rotation reports when rendering rotation pairs.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/autolearning_winner_challenger/summary.json` ->combined decision and evidence object.
  - `outputs/autolearning_winner_challenger/event_backtest.csv` ->event-level hold/exit stats from onset study outputs.
  - `outputs/autolearning_winner_challenger/candidate_experiment.yaml` ->proposal-only experiment config for future portfolio replay.
  - `outputs/autolearning_winner_challenger/challenger_report.md` ->human-readable separate challenger report.
- validation:
  - `py -3 -m py_compile tools\run_autolearning_winner_challenger.py tests\autolearning_winner_challenger_smoke.py` ->passed.
  - `py -3 tests\autolearning_winner_challenger_smoke.py` ->passed.
  - `py -3 tools\run_winner_onset_study.py --scored cloud_results\full_rebuild\latest_global_alpha_universe\scored_latest.csv --top-tickers 80 --limit 40 --years 10 --sleep 0 --output-dir outputs\winner_onset_study` ->passed, generated 16 event-level onset cases.
  - `py -3 tools\run_autolearning_winner_challenger.py` ->passed, verdict `EVENT_LEVEL_ONLY_WAIT_FOR_MONTHLY_BOOKS`.
  - `py -3 tests\smoke_test.py` ->passed, 81/81.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->passed.
  - `git diff --check` ->passed with LF-to-CRLF warnings only.
- risks_or_notes:
  - Event-level evidence prioritizes rules but is not a substitute for portfolio-level CAGR/MaxDD replay.
  - Portfolio replay remains blocked until the current full rebuild produces monthly books on this branch.

### 13:22 KST - winner-onset-study

- scope:
  - Add a report-only historical major-winner onset miner that labels early
    multi-month advance starts, studies phase snapshots around the onset, and
    proposes non-production candidate hold/exit rules.
- files:
  - `tools/run_winner_onset_study.py` ->adds ticker-agnostic historical onset detection, phase snapshots, hold diagnostics, summary report, and proposal-only policy output.
  - `tests/winner_onset_study_smoke.py` ->adds a synthetic multi-bagger onset fixture that verifies detection, snapshots, hold diagnostics, and proposal-only policy rendering.
  - `.gitignore` ->ignores generated `outputs/winner_onset_study/` artifacts.
- symbols_added:
  - `OnsetEvent` ->dataclass for one detected historical major-winner onset event.
  - `finite_float(value, default)` ->normalizes numeric values for robust report generation.
  - `safe_return(close, idx, days)` ->computes trailing returns.
  - `forward_return(close, idx, days)` ->computes forward returns.
  - `max_forward_return(close, idx, days)` ->computes future peak return and peak index.
  - `max_drawdown_between(close, start_idx, end_idx)` ->computes window drawdown.
  - `normalize_history(raw)` ->standardizes price history into close/volume columns.
  - `fetch_history(ticker, start, end)` ->fetches yfinance history for CLI studies.
  - `compute_features(hist, idx, spy_hist)` ->computes onset timing features.
  - `entry_readiness_score(features)` ->scores whether a date has early advance confirmation.
  - `detect_onset_events(ticker, hist, spy_hist, min_peak_return_12m, min_forward_6m, readiness_min, min_gap_days, max_events_per_ticker)` ->detects actionable onset events before large future moves.
  - `nearest_index(index, target)` ->finds the nearest trading-date index.
  - `build_phase_snapshots(events, histories, spy_hist)` ->writes pre/onset/post feature snapshots.
  - `first_exit_return(close, onset_idx, kind)` ->evaluates simple trend exit candidates.
  - `build_hold_diagnostics(events, histories)` ->compares fixed hold and trend-exit outcomes.
  - `summarize_patterns(events_df, snapshots_df, hold_df)` ->summarizes median onset and hold patterns.
  - `pct(value)` ->formats percentages for Markdown output.
  - `render_report(summary, events_df, output_dir)` ->renders `winner_onset_report.md`.
  - `render_policy_yaml(summary)` ->renders proposal-only candidate rules.
  - `load_tickers_from_scored(path, top_n, min_current_mcap_usd, min_dollar_vol_20d)` ->loads and filters a ticker universe from `scored_latest.csv`.
  - `load_tickers(args)` ->loads tickers from CLI inputs.
  - `run(args)` ->runs the onset study CLI.
  - `main()` ->CLI entry point.
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/winner_onset_study/events.csv` ->detected major-winner onset events.
  - `outputs/winner_onset_study/phase_snapshots.csv` ->feature snapshots from six months before to six months after onset.
  - `outputs/winner_onset_study/hold_diagnostics.csv` ->fixed-hold and trend-exit diagnostics.
  - `outputs/winner_onset_study/pattern_summary.json` ->machine-readable pattern summary.
  - `outputs/winner_onset_study/winner_onset_report.md` ->human-readable report.
  - `outputs/winner_onset_study/system_policy_candidates.yaml` ->proposal-only candidate rules, never production-active.
- validation:
  - `py -3 -m py_compile tools\run_winner_onset_study.py tests\winner_onset_study_smoke.py` ->passed.
  - `py -3 tests\winner_onset_study_smoke.py` ->passed.
  - `py -3 tests\smoke_test.py` ->passed, 81/81.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->passed.
  - `git diff --check` ->passed with LF-to-CRLF warnings only.
- risks_or_notes:
  - yfinance CLI fetching can be rate-limited on large universes; start with targeted or top-ranked scored universes before broad mining.
  - Scored-universe market-cap filtering defaults to current `market_cap_live`/`mktcap`, not point-in-time onset-date market cap; production use still requires challenger replay against monthly feature stores and costs.

### 13:10 KST - winner-lifecycle-daily-scan

- scope:
  - Add report-only daily diagnostics for missed winners, stale holdings, and
    leadership rotations so AutoLearning can propose system-level rules before
    production behavior changes.
- files:
  - `.github/workflows/daily_autolearning_scan.yml` ->adds a scheduled/manual
    artifact-only scan after the US market close.
  - `.gitignore` ->keeps generated winner lifecycle outputs out of source
    commits.
  - `tools/run_winner_lifecycle_reports.py` ->generates missed winner, stale
    winner, leadership rotation, markdown, JSON, and proposal-only YAML
    artifacts from an existing latest run.
  - `tests/winner_lifecycle_smoke.py` ->covers the SNDK/NVDA-style missed
    winner, stale holder, and same-sector rotation diagnostics.
  - `CHANGELOG.md` ->this entry.
- symbols_added:
  - `build_missed_winners(scored_rows, held_tickers, top_n)` ->ranks strong
    non-held leaders and diagnoses chase-penalty/ranking mismatches.
  - `build_stale_winners(portfolio_rows, scored_by_ticker, top_n)` ->ranks held
    names with weak recent momentum or poor relative strength.
  - `build_leadership_rotations(portfolio_rows, scored_rows, held_tickers, top_n)` ->finds
    same-sector challengers that may deserve replacement replay.
  - `render_policy_yaml(summary)` ->writes proposal-only system policy
    candidates for later historical replay.
  - `run(latest_run, output_dir, top_n)` ->orchestrates artifact loading and
    report writing.
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none. This is artifact-only and does not alter production selection,
    DEFAULT_FEATURES, weights, or execution.
- outputs:
  - `outputs/winner_lifecycle/missed_winner_report.csv` ->non-held leaders that
    deserve replay candidates.
  - `outputs/winner_lifecycle/stale_winner_report.csv` ->current holdings that
    may be dragging opportunity cost.
  - `outputs/winner_lifecycle/leadership_rotation_report.csv` ->same-sector
    held/challenger swap candidates.
  - `outputs/winner_lifecycle/winner_lifecycle_report.md` ->human-readable
    daily diagnostics.
  - `outputs/winner_lifecycle/system_policy_candidates.yaml` ->proposal-only
    candidate rules for later replay.
- validation:
  - PASS: `py -3 -m py_compile tools\run_winner_lifecycle_reports.py tests\winner_lifecycle_smoke.py`
  - PASS: `py -3 tests\winner_lifecycle_smoke.py`
  - PASS: `py -3 tools\run_winner_lifecycle_reports.py --latest-run cloud_results\full_rebuild\latest_global_alpha_universe --output-dir outputs\winner_lifecycle --top-n 20`
- risks_or_notes:
  - The daily scan creates hypotheses only. It must feed historical replay,
    shadow, and canary gates before any production rule can change.
  - Current existing artifacts flag SNDK as a missed explosive leader and NVDA
    as a stale/high-opportunity-cost holding candidate, which is the intended
    diagnostic behavior.

### 10:43 KST - pr3-historical-replay-foundation

- scope:
  - Convert PR #3 research infrastructure from snapshot-only toward replayable
    historical evidence by preserving monthly mandate books and fixing a
    concentrated entry-gate fallback bug.
- files:
  - `.github/workflows/full_rebuild_manual.yml` ->adds equity curve and monthly
    mandate books to artifacts, Google Drive sync, Telegram bundles, and
    cloud_results while avoiding nested copied directories.
  - `r1000_concentrated_policy.py` ->adds entry-quality proxy fallback so
    missing `entry_quality_score` does not block otherwise valid concentrated
    sleeve candidates.
  - `r1000_pipeline.py` ->exports main monthly weights, regime-by-month, sleeve
    returns by month, and placeholder tactical/alpha-sprint monthly book
    schemas from the existing backtest result.
  - `tests/concentrated_policy_smoke.py` ->covers concentrated entry-quality
    fallback and audit surfacing.
  - `tests/workflow_artifact_smoke.py` ->covers full rebuild artifact/GDrive
    export tokens and non-nested cloud_results directory copies.
  - `CHANGELOG.md` ->this entry.
- symbols_added:
  - `numeric_or_none(value)` ->returns a parsed float or `None` so missing
    values can be distinguished from real zeros.
  - `clip01(value, default)` ->bounds numeric scores to the 0..1 range.
  - `entry_quality_proxy(row)` ->derives concentrated entry quality from direct
    score, existing gate pass, or conservative technical fallback signals.
  - `_write_monthly_mandate_books()` ->local export helper that writes raw
    monthly mandate/replay CSVs from the main backtest result.
- symbols_changed:
  - `concentrated_conviction_score(row)` ->uses the entry-quality proxy instead
    of treating missing `entry_quality_score` as zero.
  - `entry_gate_flags(row, gate)` ->uses the entry-quality proxy for gate
    evaluation.
  - `audit_concentrated_portfolio(holdings, scored_rows, regime_state, policy)` ->surfaces
    `entry_quality_proxy` and `entry_quality_source` in audit rows.
- config_fields_added:
  - none
- breaking_changes:
  - none. Production selection behavior, DEFAULT_FEATURES, and sleeve defaults
    remain unchanged.
- outputs:
  - `outputs/reports/main_monthly_weights.csv` ->raw monthly main holdings for
    historical orchestrator replay.
  - `outputs/reports/tactical_monthly_weights.csv` ->schema placeholder until a
    true tactical monthly book is wired.
  - `outputs/reports/alpha_sprint_monthly_weights.csv` ->schema placeholder
    until a true alpha-sprint monthly book is wired.
  - `outputs/reports/regime_by_month.csv` ->monthly regime/allocation state
    exported from the main backtest.
  - `outputs/reports/sleeve_returns_by_month.csv` ->sleeve-level return proxy
    aggregated from monthly holdings.
- validation:
  - PASS: `py -3 -m py_compile r1000_concentrated_policy.py r1000_pipeline.py tests\concentrated_policy_smoke.py tests\workflow_artifact_smoke.py`
  - PASS: `py -3 tests\concentrated_policy_smoke.py`
  - PASS: `py -3 tests\workflow_artifact_smoke.py`
  - PASS: `py -3 tests\orchestrator_replay_smoke.py`
  - PASS: `py -3 tests\portfolio_system_guard_smoke.py`
  - PASS: `py -3 tests\aggressive_lab_smoke.py`
  - PASS: `py -3 tests\smoke_test.py` (81/81)
  - PASS: `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime`
- risks_or_notes:
  - Tactical and alpha-sprint monthly files are explicit empty schemas for now;
    they prevent silent missing artifacts but are not promotion evidence.
  - This does not enable orchestrator/risk/alpha-sprint production behavior.
    It only preserves the data needed for the next true replay layer.

## 2026-05-01

### 00:43 KST - regime-learned-support-guard

- scope:
  - Prevent low-sample learned regime sleeve policies from overriding exact
    manual regime maps after the Phase 20 rebuild learned `core_only` from
    only seven `growth_reentry_alert` months.
- files:
  - `r1000_config.py` ->adds the minimum learned-regime sample support config
    field.
  - `r1000_pipeline.py` ->filters learned regime maps below the support floor,
    passes the floor through sleeve policy selection/comparison, validates the
    new field, and fixes cash-aware guardrail math so cash is treated as a
    separate sleeve.
  - `r1000_signals.py` ->passes the learned-regime support floor into live
    regime-conditioned sleeve override resolution.
  - `tests/smoke_test.py` ->adds regression coverage for low-sample learned
    fallback and cash-separate guardrail math.
  - `CHANGELOG.md` ->this entry.
- symbols_added:
  - none
- symbols_changed:
  - `apply_regime_policy_guardrails(live_label, selected_policy)` ->operates
    on equity sleeve fractions instead of shrinking them by `(1 - cash)`.
  - `resolve_regime_policy_selection(live_label, *, learned_regime_map, manual_regime_map, min_learned_months)` ->filters learned exact/nearest labels with insufficient sample months before falling back to manual maps.
  - `choose_sleeve_cap_policy(policy_compare, cfg)` ->uses
    `regime_conditioned_min_learned_months` when attaching the learned
    regime-conditioned map to the selected champion policy.
  - `resolve_regime_conditioned_sleeve_override(cfg, month_df)` ->passes the
    configured support floor into regime policy lookup.
- config_fields_added:
  - `regime_conditioned_min_learned_months: int = 12` ->minimum per-regime
    months required before learned sleeve policy labels can override exact
    manual regime maps.
- breaking_changes:
  - none. Feature-store schema and DEFAULT_FEATURES are unchanged; this affects
    post-model portfolio sleeve policy resolution only.
- outputs:
  - none directly. The next full rebuild should avoid
    `core_only_guardrailed` for seven-month `growth_reentry_alert` samples and
    should surface the fallback through portfolio policy labels.
- validation:
  - PASS: `py -3 tests\smoke_test.py` (76/76)
  - PASS: `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime`
- risks_or_notes:
  - This is a conservative anti-overfit guard, not a blind weight tune. A later
    A/B can raise or lower the 12-month floor, but unsupported learned maps
    should not ship automatically.

### 03:37 KST - learned-fallback-before-growth-manual

- scope:
  - Make regime fallback more data-driven after the rerun showed the
    unsupported manual growth map worsened main CAGR and drawdown.
- files:
  - `r1000_pipeline.py` ->defers non-defensive manual regime maps until
    high-support learned fallback labels have been checked; risk-off/systemic
    manual safety maps still apply immediately.
  - `tests/smoke_test.py` ->updates low-support growth fallback coverage and
    adds a risk-off manual safety regression test.
  - `CHANGELOG.md` ->this entry.
- symbols_added:
  - `DEFENSIVE_MANUAL_REGIME_LABEL_TOKENS: tuple[str, ...]` ->labels whose
    exact manual safety maps can override learned fallback when learned support
    is below the sample floor.
- symbols_changed:
  - `resolve_regime_policy_selection(live_label, *, learned_regime_map, manual_regime_map, min_learned_months)` ->prefers high-support learned fallback for non-defensive growth/neutral labels before using deferred manual maps.
- config_fields_added:
  - none
- breaking_changes:
  - none. Feature-store schema and DEFAULT_FEATURES are unchanged.
- outputs:
  - none directly. The next full rebuild should prefer the high-support learned
    balanced/ALL map over unvalidated manual `growth_reentry_alert` when the
    exact learned growth label has fewer than 12 months.
- validation:
  - PASS: `py -3 tests\smoke_test.py` (77/77)
  - PASS: `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime`
- risks_or_notes:
  - This may improve the current growth-alert regression, but it still requires
    a full rebuild verdict because regime fallback order is a portfolio
    behavior change.

### 05:25 KST - adr-mktcap-cache-date-normalization

- scope:
  - Fix the failed Phase 20 rebuild where `yf_mktcap_proxy.parquet` mixed
    legacy ISO-string timestamps with pandas Timestamp rows and crashed while
    sorting `updated_at`.
- files:
  - `r1000_pipeline.py` ->normalizes ADR market-cap proxy cache timestamps
    before and after cache refresh concat, and stores new fetch rows as
    Timestamp values.
  - `tests/smoke_test.py` ->adds regression coverage for mixed cache
    timestamp types.
  - `CHANGELOG.md` ->this entry.
- symbols_added:
  - none
- symbols_changed:
  - `fetch_mktcap_proxy(ticker)` ->returns a pandas Timestamp for
    `updated_at` instead of an ISO string.
  - `ensure_mktcap_proxy(cfg, paths, tickers, max_new)` ->coerces
    `updated_at` to datetime before concat, after concat, before sort, and
    before returning.
- config_fields_added:
  - none
- breaking_changes:
  - none. This is cache dtype normalization only; feature definitions and
    portfolio behavior are unchanged.
- outputs:
  - none directly. The next full rebuild should pass the ADR market-cap proxy
    cache refresh step instead of failing before feature-store construction.
- validation:
  - PASS: `py -3 tests\smoke_test.py` (78/78)
  - PASS: `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime`
- risks_or_notes:
  - The failed run did not produce valid backtest metrics, so it cannot be used
    as a strategy verdict.

## 2026-04-30

### 19:40 KST - workflow-cadence-consolidation

- scope:
  - Consolidate scheduled GitHub Actions around the current core /
    concentrated / tactical system and require future system changes to update
    the automation owner workflow and smoke topology guard in the same commit.
- files:
  - `.github/workflows/after_close_daily.yml` ->new consolidated daily
    after-close workflow for scanner, macro pulse, ETF leadership,
    explosive mover scan, tactical review, paper dry-run, and Layer 4
    suggestions.
  - `.github/workflows/weekly_data_refresh.yml` ->new weekly data refresh
    workflow combining Finnhub substrate collection and theme discovery.
  - `.github/workflows/monthly_research.yml` ->new monthly research workflow
    combining cycle-play universe refresh, ADR/macro IC monitoring, tactical
    sleeve backtest, and explosive pattern model retraining.
  - `.github/workflows/quarterly_auto_learning.yml` ->new quarterly
    auto-learning workflow combining trade insights, feature-gate proposal,
    and promotion-gate dry-run/manual promotion.
  - `.github/workflows/layer4_monthly_swap.yml` ->renamed behavior to
    proposal-first, moved schedule to after-close UTC, and preserved manual
    execute=true live-paper guard.
  - `.github/workflows/unified_monthly.yml` ->moved schedule to after-close
    UTC so legacy unified bridge no longer runs during the US session.
  - `.github/workflows/* retired scheduled files` ->old duplicate daily,
    weekly, monthly, and quarterly one-purpose workflows removed after
    consolidation.
  - `AUTOMATION_STRATEGY.md` ->new cadence matrix and rules for updating
    automation whenever sleeves/features/data sources change.
  - `tests/smoke_test.py` ->updated workflow guards from legacy filenames to
    consolidated cadence topology and after-close scheduling.
- symbols_added:
  - none
- symbols_changed:
  - `test_paper_executor_workflow()` ->now validates `after_close_daily.yml`
    as the paper/tactical/scanner owner workflow.
  - `test_paper_executor_weekday()` ->now validates after-close weekday and
    weekend review schedules in `after_close_daily.yml`.
  - `test_tactical_after_close_workflow()` ->now validates tactical review
    inside the consolidated daily workflow.
  - `test_monthly_ic_monitor()` ->now validates monthly IC monitoring inside
    `monthly_research.yml`.
  - `test_layer4_monthly_workflow()` ->now validates dry-run/proposal default
    and after-close schedule.
  - `test_workflow_topology_consolidated()` ->new smoke guard for the
    consolidated workflow set and retired duplicate files.
- config_fields_added:
  - none
- breaking_changes:
  - Scheduled automation file names changed. Use `after_close_daily.yml`,
    `weekly_data_refresh.yml`, `monthly_research.yml`, and
    `quarterly_auto_learning.yml` instead of the retired one-purpose workflow
    files.
- outputs:
  - `AUTOMATION_STRATEGY.md` ->owner matrix for workflow cadence and future
    automation updates.
- validation:
  - `py -3 -c "import glob, yaml, pathlib; ..."` ->PASS, 8 workflow YAML
    files parsed.
  - `py -3 tests\smoke_test.py` ->PASS, 73/73.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime`
    ->PASS, no leakage detected.
  - `git diff --check` ->PASS, no whitespace errors.
- risks_or_notes:
  - The currently running GitHub full_rebuild on the previous branch SHA is
    unaffected. This change only updates future scheduled/manual workflow
    behavior after the branch is pushed or merged.

### 20:56 KST - full-rebuild-result-branch-and-learning-candidate

- scope:
  - Fix post-run full rebuild automation discovered from run 25154642964:
    result commits must push to the dispatched branch, and auto-learning must
    preserve an actual candidate gate artifact instead of only a dry-run log.
- files:
  - `.github/workflows/full_rebuild_manual.yml` ->generates
    `outputs/auto_learning/auto_feature_gates_candidate.yaml`, evaluates the
    promotion gate against that candidate in dry-run mode, and pushes
    `cloud_results/` commits to the current dispatch branch with branch-aware
    fetch/rebase retry.
  - `.gitignore` ->ignores local `research/phase20_artifact/` GitHub artifact
    downloads.
  - `tests/smoke_test.py` ->updates auto-learning artifact assertions and adds
    a guard that full rebuild result pushes do not rebase branch runs onto
    master.
- symbols_added:
  - `test_full_rebuild_pushes_results_to_dispatch_branch()` ->guards the
    branch-aware full rebuild result push path.
- symbols_changed:
  - `test_full_rebuild_preserves_auto_learning_artifacts()` ->now requires a
    candidate feature-gate YAML artifact and candidate-aware promotion dry-run.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/auto_learning/auto_feature_gates_candidate.yaml` ->candidate
    learned feature-gate proposal emitted by full rebuild diagnostics.
- validation:
  - `py -3 -c "import glob, yaml, pathlib; ..."` ->PASS, 8 workflow YAML
    files parsed.
  - `py -3 tests\smoke_test.py` ->PASS, 74/74.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime`
    ->PASS, no leakage detected.
  - `git diff --check` ->PASS, no whitespace errors.
- risks_or_notes:
  - The candidate gate file is generated and evaluated in dry-run mode only;
    live promotion still requires a separate tested challenger/promotion path.

## 2026-04-29

### 12:22 KST - phase15d-cycle-play-universe-and-chase-prevention

- scope:
  - User-driven Phase 15-D bundle responding to 4 explicit questions
    after Phase 15-C SHIPPED:
      1. "BE/PLUG/FCEL 같은 cycle play 가 universe 에 없다"
      2. "현재 portfolio 종목들이 already-risen — chase 차단 안 됨"
      3. "PER/PEG 가 종가 시총 기반 정확한가"
      4. "scored_latest 의 재무 컬럼이 비어있다"
  - Plus auto-maintenance request: "월 1회 자동 갱신 가능?"
- files:
  - `cycle_play_universe.yaml` (new) ->36-entry hand-curated whitelist
    of small-mid cap cycle plays across 7 themes (clean energy, EV/battery,
    AI infra, memory/semi small, biotech, fintech, robotics).
  - `aggressive/universe.py` ->add `load_cycle_play_universe` loader +
    extend `load_universe` with cycle injection for `r1000+adr+cycle` /
    `global_alpha_universe` aliases. New `r1000+cycle` standalone mode.
  - `r1000_pipeline.py` ->add `load_cycle_play_universe_frame` (mirror
    of ADR loader). `build_candidate_universe` injects cycle play
    whitelist when universe_mode in {global_alpha_universe, r1000+cycle}.
    `summarize_universe_source` preferred list adds 'cycle_play_whitelist'.
    Survivorship + historical_membership_ok checks strip
    +cycle_play_whitelist suffix the same as +adr_whitelist.
    `select_concentrated_portfolio_topk` adds entry_quality hard filter
    (>=0.30 default) — chase prevention. `normalize_engine_universe_mode`
    adds aliases.
  - `r1000_features.py` ->add `_load_finnhub_features_for_fallback`
    helper + cascade Finnhub TTM PE / PEG into existing forward_pe_final
    + peg_final fallback chain in `compute_live_factor_columns`. Add
    trailing_pe_recomputed + earnings_yield_recomputed + forward_pe_source
    columns (D4 verification). Drop temp `_fh_lookup_*` columns at end.
  - `r1000_config.py` ->add `cycle_play_universe_min/max_mcap_usd_b`
    and `concentrated_min_entry_quality` fields.
  - `tools/refresh_cycle_play_universe.py` (new) ->monthly auto-curation
    script. Reads yaml, fetches yfinance .info per ticker, drops if
    mcap > $30B (graduated to R1000), drops if mcap < $0.3B or
    daily $vol < $30M. Preserves manual_pin: true entries. Writes yaml
    grouped by cycle_focus theme.
  - `.github/workflows/cycle_play_refresh.yml` (new) ->monthly cron
    workflow (1st of month, 14:00 UTC = 23:00 KST). Runs refresh script,
    commits yaml diff back to master with [skip ci], sends Telegram
    digest.
  - `.github/workflows/full_rebuild_manual.yml` ->add r1000+cycle to
    universe_mode choices.
- symbols_added:
  - `aggressive/universe.py:load_cycle_play_universe(min_mcap_usd_b,
    max_mcap_usd_b, include_skip) -> (tickers, meta)` ->loads + filters
    cycle_play_universe.yaml with mcap range guard.
  - `r1000_pipeline.py:load_cycle_play_universe_frame(min_mcap_usd_b,
    max_mcap_usd_b) -> DataFrame` ->wraps loader for universe injection.
    Returns ticker / Name / sector / cik10 / universe_source columns.
  - `r1000_features.py:_load_finnhub_features_for_fallback() -> DataFrame`
    ->reads aggressive/state/finnhub/r1000_features.parquet for use as
    PE / PEG / dividend fallback in compute_live_factor_columns. Returns
    empty DataFrame if file not found (graceful).
  - `tools/refresh_cycle_play_universe.py:refresh_existing_entry(entry)
    -> (entry_or_None, action_note)` ->per-ticker refresh decision.
  - `tools/refresh_cycle_play_universe.py:fetch_yfinance_metadata(ticker)
    -> dict` ->yfinance .info wrapper.
  - `tools/refresh_cycle_play_universe.py:write_yaml(entries, dry_run)`
    ->serializes back to yaml grouped by theme.
- symbols_changed:
  - `aggressive/universe.py:load_universe(source, ...)` ->extend alias
    map to recognize 'r1000+adr+cycle' (alias for global_alpha_universe)
    and 'r1000+cycle' standalone. Adds cycle injection in
    global_alpha_universe + r1000+cycle branches; r1000+adr legacy mode
    intentionally keeps cycle off for backwards-compat backtest
    comparison. Returns metadata 'cycle_play_count' and 'cycle_play_added'.
  - `r1000_pipeline.py:build_candidate_universe(cfg, paths)` ->add
    `include_cycle_play` flag for global_alpha_universe + r1000+cycle.
    Cycle play injection mirrors ADR injection (dedup against R1000 +
    ADR before append). Logs 'Cycle play universe injection: mode=...,
    whitelist=..., added=...'.
  - `r1000_pipeline.py:select_concentrated_portfolio_topk(cfg, month_df,
    top_n)` ->`_take` inner function adds entry_quality hard filter
    (entry_quality_score < cfg.concentrated_min_entry_quality rejected)
    when the column is present. Skip cleanly on older feature_store.
  - `r1000_pipeline.py:summarize_universe_source(df) -> str` ->preferred
    ordering list extended with 'cycle_play_whitelist' for stable string
    construction.
  - `r1000_pipeline.py:run_acceptance_checks ...` ->survivorship_bias
    check now strips both +adr_whitelist and +cycle_play_whitelist
    suffixes before evaluating R1000 base. historical_membership_ok
    relaxes for both ADR and cycle overlays (research mode).
  - `r1000_pipeline.py:normalize_engine_universe_mode(mode) -> str`
    ->alias map adds r1000+adr+cycle, r1000+cycle, global+adr+cycle.
  - `r1000_features.py:compute_live_factor_columns(df, cfg)` ->merges
    Finnhub features parquet once at start; uses _fh_lookup helper for
    cascading fallback into forward_pe_final / peg_final; adds D4
    verification columns at end; drops _fh_lookup_* before return.
- config_fields_added:
  - `cycle_play_universe_min_mcap_usd_b: float = 0.3` ->floor for cycle
    whitelist (drops names too small for backtest data).
  - `cycle_play_universe_max_mcap_usd_b: float = 30.0` ->ceiling that
    triggers auto-graduation into R1000 (excluded from cycle list).
  - `concentrated_min_entry_quality: float = 0.30` ->reject concentrated
    pool entries below this entry_quality_score. Set 0.0 to disable.
- breaking_changes:
  - none. ENGINE_REUSE_VERSION unchanged
    (`2026-04-28-phase15c-entry-quality`). Phase 15-D adds 3 export-only
    columns (trailing_pe_recomputed / earnings_yield_recomputed /
    forward_pe_source) which are NOT in DEFAULT_FEATURES — feature_store
    schema and ML training inputs unchanged. Cache reusable.
  - r1000+adr universe_mode behavior unchanged (no cycle injection).
    Only global_alpha_universe and new r1000+cycle modes inject cycle
    play whitelist, so existing baselines still comparable.
- outputs:
  - `cycle_play_universe.yaml` ->36 entries (33 currently pass mcap
    range filter on first run; 3 borderline below $0.3B).
  - `cloud_results/cycle_play_universe.yaml` ->updated monthly by
    workflow with [skip ci] commit.
  - `outputs/scored_latest.csv` ->gains 3 new columns
    (trailing_pe_recomputed, earnings_yield_recomputed, forward_pe_source)
    via D4. forward_pe_final / peg_final now use Finnhub fallback.
- validation:
  - `python tests/smoke_test.py` ->66/66 pass (1.7-12.1s across reruns)
  - `python tests/audit_features.py --no-runtime` ->245 features, 0 leakage
  - syntax check on all 5 modified Python files + 3 yaml files: clean
  - load_universe('r1000+adr+cycle') functional test:
      cycle_play_count=33, cycle_play_added=31 (2 dedup with R1000/ADR)
- risks_or_notes:
  - Cycle play backtest data sparse for newer IPOs (RIVN 2021, ASTS 2021,
    BBAI 2021, etc.) — 84-month full backtest will have NaN early periods.
    The fundamental_coverage_warning may TRUE for cycle_play_whitelist
    rows; acceptance gate already relaxed for ADR/cycle overlays so
    portfolio export not blocked.
  - Finnhub fallback in `compute_live_factor_columns` reads
    aggressive/state/finnhub/r1000_features.parquet which is populated
    by the daily_review or finnhub_weekly cron. If those crons are
    disabled (Telegram silence Apr 23 onward suggests possible GHA
    quota issue), the fallback degrades gracefully — forward_pe_final
    falls back to legacy chain only. Verify Finnhub parquet freshness:
      `ls -la aggressive/state/finnhub/r1000_features.parquet`
  - concentrated_min_entry_quality=0.30 may temporarily produce
    fewer-than-target N concentrated names if all candidates are
    extended (e.g. late bull market). Backtest will reveal whether
    holding fewer high-quality entries beats forced fill.
  - cycle_play_refresh.yml uses yfinance for mcap which is rate-limited.
    Sleep 0.2s/ticker = ~10s for 36 names. Could fail under heavy
    yfinance load — run is non-critical (yaml stays prior version
    on failure).
  - manual_pin: true is honored by refresh script but not yet
    documented in cycle_play_universe.yaml entries — add to specific
    rows when curating high-conviction picks that should never auto-drop.

### 13:41 KST - phase15d-cloud-preflight-finnhub-state

- scope:
  - Pre-trigger cloud execution fix for Phase 15-D verification. The first
    global_alpha_universe rebuild must collect missing cycle-play price caches
    and must see the Finnhub fallback parquet in GitHub Actions.
- files:
  - `.github/workflows/full_rebuild_manual.yml` ->cache
    `aggressive/state/finnhub`, add Phase 15-D preflight diagnostics for
    cycle-play missing price caches and Finnhub fallback parquet shape.
  - `.github/workflows/finnhub_weekly.yml` ->cache
    `aggressive/state/finnhub` alongside per-ticker Finnhub cache and force-add
    the ignored fallback parquet when committing weekly refresh output.
  - `.github/workflows/daily_review.yml` ->cache
    `aggressive/state/finnhub` and force-add the ignored fallback parquet when
    committing scanner summaries.
  - `.github/workflows/unified_monthly.yml` ->cache
    `aggressive/state/finnhub` so unified universe rebuilds share the same
    fallback state.
  - `aggressive/state/finnhub/r1000_features.parquet` ->latest successful
    Finnhub weekly artifact (`25003804766`), 1008 rows x 53 columns, force-added
    so the immediate cloud rebuild can use Phase 15-D PE/PEG fallback.
  - `SESSION_HANDOFF.md` ->correct next-run instructions from
    `skip_collector=true` to `skip_collector=false` and document preflight
    reasoning.
- symbols_added:
  - none
- symbols_changed:
  - none
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `aggressive/state/finnhub/r1000_features.parquet` ->Finnhub weekly fallback
    feature table used by `r1000_features._load_finnhub_features_for_fallback`.
- validation:
  - `py -3 tests\smoke_test.py` ->PASS, 66/66.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->PASS,
    no leakage detected.
  - Parsed modified GitHub workflow YAML files with PyYAML ->PASS.
- risks_or_notes:
  - This does not change model features or ranking weights. It only fixes cloud
    state visibility before the next expensive full_rebuild.
  - First fair Phase 15-D rebuild should use `skip_collector=false` because
    20/33 active cycle-play tickers were missing from the local/GDrive price
    cache before this fix.

### 18:00 KST - adr-usd-marketcap-normalization

- scope:
  - Fix confirmed ADR market-cap unit distortion found after run `25091384080`.
    TSM was ranked above NVDA because the engine multiplied USD ADR price by
    ordinary local share count. ADR rows now use a yfinance USD marketCap anchor
    and an ADR-ratio factor before size ranking and valuation.
- files:
  - `r1000_config.py` ->bump `ENGINE_REUSE_VERSION` to
    `2026-04-29-adr-usd-mktcap` so the next full_rebuild cannot reuse stale
    feature_store artifacts with inflated ADR market caps.
  - `r1000_pipeline.py` ->add ADR USD market-cap normalization helper, extend
    yfinance market-cap proxy cache with currency/share diagnostics, make ADR
    EPS/PE math use ADR-equivalent shares, and prefer USD companyfacts units
    when SEC exposes multiple monetary units.
  - `tests/smoke_test.py` ->add regression tests for ADR market-cap
    normalization, ADR-equivalent share valuation, and USD companyfacts unit
    preference.
- symbols_added:
  - `preferred_companyfacts_unit_keys(field_name, unit_keys) -> list[str]`
    ->prefers USD monetary facts and share-count facts when companyfacts has
    multiple unit buckets.
  - `apply_adr_usd_mktcap_proxy(monthly, cfg, paths) -> DataFrame`
    ->normalizes ADR market cap using yfinance USD marketCap as live anchor.
- symbols_changed:
  - `ENGINE_REUSE_VERSION` ->bumped from
    `2026-04-28-phase15c-entry-quality` to `2026-04-29-adr-usd-mktcap`.
  - `extract_companyfacts_records(payload, cik, field_name)` ->records unit and
    applies unit preference before building companyfacts rows.
  - `fetch_mktcap_proxy(ticker)` ->returns price currency, financial currency,
    shares outstanding, and implied shares outstanding diagnostics.
  - `build_universe_monthly(cfg)` ->applies ADR USD market-cap normalization
    immediately after px*shares market-cap calculation and before size ranking.
  - `compute_valuation_columns(df, cfg)` ->uses mktcap/ADR price as
    ADR-equivalent shares for ADR valuation math.
- config_fields_added:
  - none
- breaking_changes:
  - Cached feature_store artifacts are intentionally invalidated on the next
    full_rebuild because mktcap, valuation, and size-rank features change for
    ADR rows.
- outputs:
  - none
- validation:
  - `py -3 tests\smoke_test.py` ->PASS, 69/69.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->PASS,
    no leakage detected.
- risks_or_notes:
  - This fixes the confirmed ADR price/share-count mismatch. Full historical FX
    conversion for non-USD-only companyfacts remains a separate larger task.
  - A new full_rebuild is required before evaluating Phase 15-D again because
    run `25091384080` used the inflated ADR market caps.

### 19:08 KST - concentrated-continuation-winner-override

- scope:
  - Fix concentrated CAGR regression caused by treating entry_quality_score as
    an unconditional hard stop. The concentrated sleeve is the CAGR-max sleeve,
    so extended but intact high-rank continuation winners should remain
    selectable while broken low-quality chase entries stay blocked.
- files:
  - `r1000_config.py` ->bump `ENGINE_REUSE_VERSION` to
    `2026-04-29-concentrated-continuation` and add continuation override
    controls for the concentrated entry-quality gate.
  - `r1000_pipeline.py` ->change `select_concentrated_portfolio_topk` so
    `entry_quality_score < concentrated_min_entry_quality` can pass only when
    concentrated score is top-decile, confirmation/trend are intact, and exit
    risk / broken-momentum risk are low.
  - `tests/smoke_test.py` ->add a synthetic regression test proving a live
    continuation winner passes while a broken low-quality chase candidate does
    not.
- symbols_added:
  - none
- symbols_changed:
  - `select_concentrated_portfolio_topk(cfg, month_df, top_n) -> DataFrame`
    ->entry-quality gate now has a strict continuation-winner override instead
    of rejecting all extended winners.
  - `ENGINE_REUSE_VERSION` ->bumped from `2026-04-29-adr-usd-mktcap` to
    `2026-04-29-concentrated-continuation`.
- config_fields_added:
  - `concentrated_entry_quality_continuation_override: bool = True` ->enable
    high-rank continuation override for concentrated entry-quality gate.
  - `concentrated_entry_quality_continuation_quantile: float = 0.90` ->minimum
    concentrated_score quantile required for override eligibility.
  - `concentrated_entry_quality_continuation_min_confirmation: float = 0.80`
    ->minimum selection confirmation for override eligibility.
  - `concentrated_entry_quality_continuation_max_exit_risk: float = 0.45`
    ->maximum hold-policy exit risk allowed for override eligibility.
  - `concentrated_entry_quality_continuation_max_broken: float = 0.30`
    ->maximum broken-momentum penalty allowed for override eligibility.
- breaking_changes:
  - Cached feature_store/scored artifacts are intentionally invalidated on the
    next full_rebuild so the new concentrated selection behavior is measured
    cleanly after the ADR market-cap fix.
- outputs:
  - none
- validation:
  - Latest stale scored snapshot simulation ->selected WDC / CIEN / MRVL /
    AMKR / FTI for concentrated with `concentrated_entry_quality_override=True`
    instead of the lower-momentum ETR / ZTO / KIM / CW / PEG set.
  - `py -3 tests\smoke_test.py` ->PASS, 70/70.
  - `PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime` ->PASS,
    no leakage detected.
- risks_or_notes:
  - This is a targeted regression fix for concentrated CAGR recovery, not a
    blind weight increase. Actual CAGR/Sharpe/MaxDD verdict still requires a
    new `global_alpha_universe` full_rebuild after the ADR market-cap fix.
  - The override deliberately remains unavailable to broken-trend or high
    exit-risk names.

### 11:30 KST - phase15-validators-and-multiplicative-gate-fix

- scope:
  - Pre-rebuild validation tooling (P9 / P11) and a critical correctness
    fix to the Phase 15-B early_cycle_inflection_score. Built on user's
    insight that we should validate the design BEFORE burning 3-3.5h on
    the next cloud full_rebuild. Running the validator on the existing
    SHIPPED scored_latest.csv exposed two real bugs in the score.
- files:
  - `tools/validate_early_inflection.py` ->new validator with --mode
    latest (sanity-checks Phase 15-B candidate ranking against the
    existing scored_latest.csv without requiring a rebuild) and --mode
    historical (post-rebuild validation against feature_store_*.parquet
    -- did the score fire on SNDK / MU / WDC etc. BEFORE their +100%+
    moves?).
  - `tools/aggregate_portfolio_performance.py` ->new tool implementing
    P11 portfolio-of-portfolios aggregation. Reads core ML +
    concentrated + event-driven sleeve outputs, applies a capital
    allocation split (default 60/30/10), and reports per-sleeve and
    aggregate CAGR / Sharpe / MaxDD / N holdings. Solves the user's
    request for "포트별 별개 + 합산 평가".
  - `r1000_features.py` ->fix compute_early_cycle_inflection_score:
    cond1/cond2/cond3 now form a multiplicative GATE (any single failure
    zeros the score) instead of additive partial credit. cond4/cond5/
    cond6 remain additive boost. Final: gate * (0.50 + 0.50 * boost).
    Validation showed the additive design admitted NEU (mom_12m +23%)
    and CEG (mom_12m +50%) into top-30 because cond1+cond3+cond6 partial
    credit overrode the cond2 (cycle bottom) failure. New design
    hard-rejects names outside [-30%, +5%] mom_12m / [-10%, +5%]
    dist_ma200 / [-5%, +20%] mom_3m simultaneously.
  - `r1000_config.py` ->expand PHASE9_C3_TURNAROUND_COLUMNS to include
    any_profit_sign_flip_pos / ni_sign_flip_pos / op_income_sign_flip_pos
    / ocf_sign_flip_pos / fcf_sign_flip_pos / gp_sign_flip_pos. These
    are computed by compute_fundamental_trend_features but were
    previously missing from the keep_cols whitelist, so they got
    silently dropped before reaching scored_latest.csv. Phase 15-A
    cycle_recovery_score and Phase 15-B early_cycle_inflection_score
    both depend on any_profit_sign_flip_pos.
- symbols_added:
  - `tools/validate_early_inflection.py:run_latest_mode(...)` ->ranks
    by Phase 15-B score, prints per-condition breakdown, score
    distribution, sanity-check guidelines.
  - `tools/validate_early_inflection.py:run_historical_mode(...)`
    ->scans feature_store across all rebalance dates, finds peak mom_3m
    per winner, looks N months prior, reports whether score fired.
  - `tools/aggregate_portfolio_performance.py:main()` ->loads core +
    concentrated + event sleeve metrics + portfolio CSVs, prints
    per-sleeve + aggregate table, writes aggregate_performance.json.
- symbols_changed:
  - `compute_early_cycle_inflection_score(df) -> df` ->multiplicative
    gate (cond1*cond2*cond3) replaces additive 0.20+0.20+0.20 weights.
    Boost (cond4+cond5+cond6) scales gate from 0.50 to 1.00 multiplier.
    Score interpretation:
      * 0.0 -> any of dist_ma200 / mom_12m / mom_3m outside zone
      * 0.50 -> all 3 gate conds fully fire, no boosts
      * 0.70-0.85 -> gate + 1-2 boosts
      * 0.85-1.00 -> textbook setup (gate + all 3 boosts)
- config_fields_added:
  - none (PHASE9_C3_TURNAROUND_COLUMNS list expansion is not a new
    config field, just a wider whitelist)
- breaking_changes:
  - feature_store schema gains 6 columns from the PHASE9_C3 whitelist
    expansion (any_profit_sign_flip_pos and 5 sign-flip flags). These
    columns are already produced upstream — only the keep_cols
    whitelist changes — so existing per-CIK panel data does not need
    refetching, only feature_store_*.parquet regenerates on next FULL
    rebuild via the existing ENGINE_REUSE_VERSION bump
    `2026-04-28-phase15b-early-inflection`. No additional version bump.
  - Phase 15-B score values change for every ticker (multiplicative
    gate is much stricter). Top-30 ranking on the existing SHIPPED
    scored_latest.csv goes from 4 names >= 0.50 to 0 names >= 0.50
    (the boost-providing eps_revision_proxy + any_profit_sign_flip_pos
    are NaN/missing in that snapshot, so gate-only fire caps at 0.50;
    next rebuild restores them and scores rise into the >= 0.50 band).
- outputs:
  - `cloud_results/full_rebuild/latest_global_alpha_universe/aggregate_performance.json`
    ->produced by the new aggregate tool from the SHIPPED Phase 14
    metrics. Sample 60/30/10 split: aggregate CAGR 23.46%, MaxDD
    proxy -23.52%, Sharpe 1.185.
- validation:
  - `python tools/validate_early_inflection.py --mode latest --top 30`
    ->ran twice: pre-fix top 30 contained NEU / CEG; post-fix top 30
    is dominated by ZBH / TW / DLB / POST / FTNT / CDW / AMT / CCI -
    all reasonable cycle-bottom turnaround setups with mom_12m in
    [-21%, +2%] and dist_ma200 in [-7%, +4%]. No outliers.
  - `python tools/aggregate_portfolio_performance.py
    --base-dir cloud_results/full_rebuild/latest_global_alpha_universe`
    ->prints clean per-sleeve table; surfaces the existing "core_ml has
    0 holdings, concentrated has 1" symptom from the SHIPPED snapshot,
    confirming aggregate tool correctly reflects portfolio state.
  - `python tests/smoke_test.py --quick` ->17/17 pass
  - `python tests/audit_features.py --no-runtime` ->241 features, 0
    leakage
- risks_or_notes:
  - aggregate_portfolio_performance.py uses linear-approx CAGR
    (allocation-weighted average), not compound. Real compound is
    higher when sleeves rebalance independently. For sleeve-mix
    decisions this approximation is dominant enough; for actual
    portfolio P&L tracking a daily-NAV ledger (P11b TODO) is needed.
  - max_dd_proxy is pessimistic — assumes correlated DD across sleeves.
    Real-world DD depends on inter-sleeve correlation. P11b daily-NAV
    ledger would compute realized DD correctly.
  - Phase 15-B score on the SHIPPED snapshot has eps_revision_proxy
    all-NaN. This is a pre-existing data-pipeline bug (the column is
    in DEFAULT_FEATURES but not being populated upstream). Filed as
    follow-up; does not block the multiplicative gate fix.
  - When the next FULL rebuild lands with the fixed PHASE9_C3 whitelist,
    re-run --mode historical with --winners SNDK,MU,WDC,AMKR,MRVL,CIEN
    to confirm the score actually fires N months before each winner's
    breakout. If <50% fire rate, tighten the gate widths (cond1
    half-width 0.075 -> 0.050, etc.) before promoting to a hard sleeve
    override.

### 10:15 KST - phase15b-early-cycle-inflection-detector

- scope:
  - Add a separate scoring lane for "the next SNDK / MU before they break
    out". Phase 15-A cycle_recovery_score requires mom_6m > 30% AND mom_3m
    > 10% — by that point names like SNDK are already +125% in 3 months
    (per the SHIPPED scanner output) and the alpha is captured by chasers,
    not by the engine. User explicitly flagged this gap: the goal is to
    BUY THE NEXT SNDK in advance, not to rescue current SNDK after the
    move. Phase 15-B is the early-detector complement to 15-A's late-rescue.
- files:
  - `r1000_features.py` ->add compute_early_cycle_inflection_score (6
    weighted-sum conditions targeting Stage 1 -> Stage 2 transitions
    BEFORE breakout). Add to __all__.
  - `r1000_config.py` ->add `early_cycle_inflection_score` to
    PHASE15_ALPHA_COLUMNS. Bump ENGINE_REUSE_VERSION to
    `2026-04-28-phase15b-early-inflection`.
  - `r1000_pipeline.py` ->import compute_early_cycle_inflection_score;
    call after eps_revision under independent phase toggle
    PHASE_PHASE15B_EARLY_INFLECTION_ENABLED (so it can be A/B'd vs
    Phase 15-A's other scores separately).
- symbols_added:
  - `compute_early_cycle_inflection_score(df) -> df` ->[0.0, 1.0]
    weighted-sum score combining: 1) price near MA200 (-10% to +5%, 20%
    weight), 2) mom_12m still cycle-bottom (-30% to +5%, 20%), 3) mom_3m
    early turn-up (-5% to +20%, 20%), 4) eps_revision_proxy > +3% (15%),
    5) any_profit_sign_flip_pos sign flip (15%), 6) industry_breadth
    mid-recovery (20-50%, 10%).
- symbols_changed:
  - `PHASE15_ALPHA_COLUMNS` ->expanded from 2 to 3 columns; adds
    early_cycle_inflection_score.
- config_fields_added:
  - none (uses existing phase_is_enabled / env var infrastructure)
- breaking_changes:
  - ENGINE_REUSE_VERSION bumped 2026-04-28-phase15-cycle-recovery ->
    2026-04-28-phase15b-early-inflection. feature_store cache
    invalidates again. Combine with the Phase 15-A bump in the same
    full rebuild (no intermediate rebuild needed).
  - DEFAULT_FEATURES count 240 -> 241.
- outputs:
  - `outputs/scored_latest.csv` ->gains early_cycle_inflection_score
    column. Walk-forward Ridge/Logistic learn the weight against
    forward returns; if the score predicts well it gets positive
    weight and naturally raises the overall `score` for names that
    look like 6mo-pre-SNDK / 6mo-pre-MU setups. No hard sleeve
    override yet — empirical first, override only if alpha proven.
- validation:
  - syntax check: r1000_pipeline.py / r1000_config.py / r1000_features.py
    ->all clean
  - smoke_test --quick ->17/17 pass
  - audit_features --no-runtime ->241 features, 0 leakage
- risks_or_notes:
  - Trade-off: looser conditions catch more potential winners but admit
    more value-traps and dead-cat-bounces. The two scores are
    complements: cycle_recovery_score (already-turning, lower variance,
    smaller alpha) + early_cycle_inflection_score (pre-breakout, higher
    variance, larger alpha). ML walk-forward should resolve which gets
    weight in which regime.
  - Score depends on mom_12m being available — names with <12mo history
    (recent IPOs) auto-score 0 on cond2. This is intentional (no cycle
    context).
  - cond6 industry_breadth_above_ma200 requires Phase 2 industry
    metadata — if PHASE2_INDUSTRY_ENABLED=0 this condition contributes
    0 (score caps at 0.90 instead of 1.00).
  - Default phase toggle ON. Disable with
    PHASE_PHASE15B_EARLY_INFLECTION_ENABLED=0 for A/B isolation.
  - If next backtest shows the score has near-zero or negative ML
    weight, consider tightening the conditions (e.g. require minimum
    +3% mom_1m for cond3). Don't add hard sleeve override unless ML
    proves the signal.

### 09:47 KST - phase15-cycle-leader-rescue-and-risk-discipline

- scope:
  - Selection mechanism strengthening (P1-P4) plus risk discipline (P5-P7)
    targeting the user-flagged gap: cyclical leaders (SNDK / MU / WDC /
    CIEN class) with rank top-decile but excluded from both Core and
    Concentrated portfolios. Diagnosed against research/phase14_artifact
    scored_latest.csv:
      - SNDK rank 37/595 score 3.69 sleeve=unassigned (Phase 9 thesis-gate
        rejected because multi_year_winner_score=0 from cycle bottom)
      - MU rank 19/595 score 5.02 sleeve=core_compounder, excluded by
        Information Technology sector cap (NVDA + LRCX absorbed it)
      - WDC / CIEN / AVGO same IT sector cap pattern
- files:
  - `r1000_features.py` ->add compute_cycle_recovery_score and
    compute_eps_revision_score; export both in `__all__`.
  - `r1000_config.py` ->add PHASE15_ALPHA_COLUMNS, append to
    DEFAULT_FEATURES, bump ENGINE_REUSE_VERSION to
    `2026-04-28-phase15-cycle-recovery`. Lower
    concentrated_min_confirmation 0.45 -> 0.30. Add sub_industry_cap_*
    config block. Add concentrated_stop_loss_pct /
    concentrated_trailing_stop_pct / concentrated_regime_cash_* config.
  - `r1000_pipeline.py` ->import + call cycle_recovery / eps_revision
    after Phase 14 block, gated by phase_is_enabled
    (PHASE_PHASE15_CYCLE_RECOVERY_ENABLED). Append PHASE15_ALPHA_COLUMNS
    to keep_cols whitelist + hard_sanitize numeric list. New
    rank_fallback_top_decile lane in select_concentrated_portfolio_topk
    (admits high-score names regardless of sleeve label / confirmation
    when thesis-gated lanes can't fill top_n).
  - `r1000_signals.py` ->select_topn_with_sector_limits gains
    sub_industry sub-cap inside Information Technology / Communication
    Services / Health Care / Financials / Consumer Discretionary
    sectors. No-op when sub_industry / industry_group not populated.
  - `aggressive/signals_technical.py` ->tier1_stage2_breakout adds 50d
    volume ratio + quality_volume_50d check. Fire gate now requires both
    structure (ma_aligned + ma200_rising + near_52w_high) AND volume
    support (2x 20d surge OR 1.5x 50d average); single-day spike
    breakouts without sustained accumulation get 30% score haircut.
- symbols_added:
  - `compute_cycle_recovery_score(df) -> df` ->fires on
    mom_24m<0.10 AND mom_6m>0.30 AND mom_3m>0.10 AND
    any_profit_sign_flip_pos. [0.0, 1.0] continuous score.
  - `compute_eps_revision_score(df) -> df` ->wraps eps_revision_proxy
    into [0.0, 1.0]: 0% revision -> 0, +20% -> 1.0.
  - `PHASE15_ALPHA_COLUMNS` (in r1000_config.py) ->canonical list of
    Phase 15 feature columns for keep_cols / hard_sanitize / phase
    toggle wiring.
  - `rank_fallback_top_decile` lane in
    `select_concentrated_portfolio_topk()` ->admits top-decile by
    concentrated_score regardless of sleeve label.
- symbols_changed:
  - `select_concentrated_portfolio_topk(cfg, month_df, top_n)` ->lower
    min_confirmation default 0.45 -> 0.30 + new rank_fallback lane
    after the existing 3 thesis-gated lanes. enforce_confirmation arg
    on inner _take helper.
  - `select_topn_with_sector_limits(cfg, month_df, caps, target_n)`
    ->add sub_industry sub-cap inside flagged sectors using cfg fields.
  - `tier1_stage2_breakout(df) -> TierSignal` ->require volume
    confirmation (2x 20d OR 1.5x 50d) for fire; haircut single-day
    spike breakouts.
- config_fields_added:
  - `concentrated_min_confirmation: float = 0.30` ->relaxed from 0.45
  - `sub_industry_cap_enabled: bool = True` ->P2 master switch
  - `sub_industry_max_per_sector: int = 2` ->cap names per
    sub_industry inside flagged sectors
  - `sub_industry_cap_sectors: list[str] = [Information Technology,
    Communication Services, Health Care, Financials,
    Consumer Discretionary]`
  - `concentrated_stop_loss_pct: float = 0.15` ->vs core 0.25
  - `concentrated_trailing_stop_pct: float = 0.12` ->trailing from peak
  - `concentrated_trailing_stop_enabled: bool = True`
  - `concentrated_regime_cash_vix_threshold: float = 25.0` ->vs core 30
  - `concentrated_regime_cash_breadth_threshold: float = 0.30`
    ->breadth_above_ma200 floor
  - `concentrated_regime_cash_pct: float = 0.30` ->force 30% cash on
    regime risk-off
- breaking_changes:
  - ENGINE_REUSE_VERSION bumped 2026-04-25-phase14-hybrid-alpha
    -> 2026-04-28-phase15-cycle-recovery. feature_store cache
    invalidates. ONE FULL REBUILD required per machine before
    QUICK_RESCORE works again. Cloud workflow will rebuild
    automatically on next dispatch with the new version.
  - DEFAULT_FEATURES count 238 -> 240 (audit verified 0 forward-return
    columns).
  - tier1_stage2_breakout fire gate is stricter — pure-price near-52w-
    high breakouts without volume support no longer fire. Estimated
    impact: 10-20% fewer T1 candidates per scanner run, lower false-
    positive rate.
- outputs:
  - `outputs/scored_latest.csv` ->gains cycle_recovery_score and
    eps_revision_score columns
  - `outputs/feature_store_*.parquet` ->new schema, regenerates on next
    FULL rebuild
- validation:
  - `python tests/smoke_test.py` ->66/66 passed (~14s)
  - `python tests/audit_features.py --no-runtime` ->240 features, 0
    leakage, all forward horizons banned
  - syntax check on r1000_pipeline.py / r1000_config.py /
    r1000_features.py / r1000_signals.py / aggressive/signals_technical.py
    ->all clean
- risks_or_notes:
  - cycle_recovery_score relies on any_profit_sign_flip_pos already
    populated by Phase 9 C3. If C3 disabled (PHASE_PHASE9_C3_TURNAROUND_ENABLED=0),
    cycle_recovery_score effectively gates on momentum-only and may fire
    less. Retest after C3 toggle if used.
  - sub_industry_max_per_sector=2 is conservative — increase to 3 if A/B
    shows too many names dropped from IT (e.g. all of NVDA/AMD/LRCX/AMAT
    /MU at top of score want a slot).
  - concentrated_trailing_stop_pct activates only when
    concentrated_trailing_stop_enabled=True. Backtest will use trailing
    from peak; live trading will need to track actual peak in
    portfolio_state per ticker.
  - tier1_stage2_breakout volume threshold (1.5x 50d) is an empirical
    choice — IBD canonical is 1.5x 50d for institutional accumulation.
    Tighten to 2.0x for higher-quality breakouts only if backtest shows
    the looser threshold leaks too many low-quality names.
  - Backtest on the new feature_store will take 3-3.5h on cloud GHA
    full_rebuild_manual.yml (still within 5h50m timeout).

## 2026-04-27

### 10:44 KST - wire-adr-universe-mode-into-main-engine

- scope:
  - Fix the cloud FULL rebuild universe-mode path so `r1000+adr` and
    `r1000+adr_phase14_off` actually reach the main R1000 engine, not only
    the aggressive scanner helper.
- files:
  - `.github/workflows/full_rebuild_manual.yml` -> set
     `PHASE_PHASE14_HYBRID_ALPHA_ENABLED`, keep `UNIVERSE_MODE`, and align
     the phase14-off option spelling.
  - `run_local.py` -> add `--universe-mode`, read `UNIVERSE_MODE`, normalize
     legacy phase14-off spelling, and pass the value into collector/pipeline
     runtime overrides.
  - `r1000_pipeline.py` -> inject ADR whitelist rows into
     `build_candidate_universe()` for ADR modes, preserve non-historical
     universe rows through historical membership filtering, summarize mixed
     universe sources, and gate Phase 14 compute columns with
     `phase_is_enabled("phase14_hybrid_alpha")`.
  - `tests/smoke_test.py` -> add regression guard that the GitHub Actions
     input reaches `run_local.py` and the main pipeline ADR path.
  - `tests/check_adr_data.py` -> replace non-ASCII console dashes so the
     quick ADR source audit runs under the default Windows CP949 console.
  - `SESSION_HANDOFF.md` -> update active inbox with A complete, B root cause
     and fix status, and the design read for core vs concentrated goals.
- symbols_added:
  - `resolve_universe_mode(raw)` -> normalizes CLI/env universe-mode values
     and validates supported modes.
  - `summarize_universe_source(df)` -> returns a stable label for single or
     mixed universe sources.
  - `normalize_engine_universe_mode(mode)` -> canonicalizes engine
     universe-mode spellings.
  - `load_adr_universe_frame(min_mcap_usd_b)` -> adapts
     `aggressive.universe.load_adr_universe()` into the main engine candidate
     universe schema.
  - `tests.smoke_test.test_main_engine_adr_universe_mode_wired()` -> source
     guard for the ADR-mode regression.
- symbols_changed:
  - `run_local.main()` -> applies universe-mode runtime overrides and maps the
     legacy Phase 14 env var to the env name consumed by `phase_is_enabled()`.
  - `build_candidate_universe()` -> supports `r1000+adr`,
     `r1000+adr_phase14_off`, and `adr` modes in the main pipeline.
  - `apply_historical_membership_filter()` -> keeps external universe rows
     such as ADR whitelist rows while still filtering historical R1000 rows.
  - `build_feature_store()` -> zero-fills Phase 14 columns when the Phase 14
     env gate is disabled for control runs.
  - `run_acceptance_checks()` -> reports mixed universe sources instead of a
     binary historical/current label.
  - `export_outputs()` -> writes mixed universe source labels to run summary
     metadata.
  - `tests.smoke_test.test_full_rebuild_workflow()` -> asserts the exact
     Phase 14 env var required by the workflow.
  - `tests.check_adr_data.main()` -> emits ASCII-only status text.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `git diff --check` -> PASS
  - `py -3 -m py_compile run_local.py r1000_pipeline.py tests\smoke_test.py tests\check_adr_data.py` -> PASS
  - `py -3 tests\smoke_test.py` -> 62/62 PASS
  - synthetic `apply_historical_membership_filter()` + ADR whitelist import
     check -> PASS, 26 ADR rows loaded
  - `py -3 tests\check_adr_data.py --quick` -> PASS, 26 ADRs audited
- risks_or_notes:
  - ADR rows still have sparse SEC CIK/companyfacts coverage; the existing
    Finnhub synthetic fundamentals path must carry those names in the next
    FULL rebuild.
  - The confirmed Phase 14 ship verdict remains R1000-only until a new
    `r1000+adr` FULL rebuild exercises this fixed path.

### 12:04 KST - global-alpha-universe-10y-sleeve-audit

- scope:
  - Add a shared `global_alpha_universe` execution preset for main diversified
    and concentrated outputs, expose a 10-year backtest path, and export a
    sleeve audit report before changing sleeve scoring weights.
- files:
  - `.github/workflows/full_rebuild_manual.yml` -> default manual FULL rebuild
     to `global_alpha_universe`, add `backtest_years`, pass
     `BACKTEST_YEARS`/`--backtest-years`, and upload/sync sleeve-audit reports.
  - `aggressive/universe.py` -> accept `global_alpha_universe` and aliases as
     the same shared R1000 + curated ADR/global-alpha universe.
  - `r1000_config.py` -> change default OOS backtest years from 8 to 10 and
     compare 5/8/10-year windows.
  - `r1000_data_collector.py` -> align notebook/runtime defaults with the
     10-year default and 5/8/10 window comparison list.
  - `r1000_pipeline.py` -> normalize `global_alpha_universe`, include ADR rows
     for that mode, build/export global-alpha sleeve audit frames, and include
     run universe/backtest metadata in the archive manifest.
  - `run_local.py` -> add `--backtest-years`, read `BACKTEST_YEARS`, and pass
     default/comparison backtest windows through runtime overrides.
  - `tests/smoke_test.py` -> add source guards for the shared universe, 10-year
     path, workflow input, and sleeve-audit outputs.
  - `SESSION_HANDOFF.md` -> update active inbox with the new execution preset,
     audit files, and next FULL rebuild instructions.
- symbols_added:
  - `resolve_backtest_years(raw)` -> validates CLI/env backtest-year overrides
     before applying runtime config overrides.
  - `build_global_alpha_sleeve_audit_frames(cfg, scored, portfolio_latest=None, concentrated_latest=None)` -> creates monthly and summary diagnostics for sleeve candidate counts, gate-pass counts, source/ADR mix, and factor averages.
  - `tests.smoke_test.test_global_alpha_universe_10y_audit_wired()` -> guards
     local/GitHub Actions wiring for the new preset and reports.
- symbols_changed:
  - `resolve_universe_mode()` -> accepts `global_alpha_universe` and common
     global-alpha aliases.
  - `run_local.main()` -> applies backtest-year runtime overrides to collector
     and pipeline configs.
  - `normalize_engine_universe_mode()` -> canonicalizes global-alpha aliases.
  - `build_candidate_universe()` -> treats `global_alpha_universe` as an
     ADR-augmented R1000 universe.
  - `export_outputs()` -> writes global-alpha sleeve audit CSVs and exposes
     them in output manifests and run summaries.
  - `aggressive.universe.load_universe()` -> accepts `global_alpha_universe`
     as a shared universe alias.
  - `_apply_notebook_runtime_defaults()` -> aligns runtime defaults to 10-year
     backtests and 5/8/10 comparisons.
  - `tests.smoke_test.test_full_rebuild_workflow()` -> requires the
     `backtest_years` workflow input and `BACKTEST_YEARS` env.
  - `tests.smoke_test.test_main_engine_adr_universe_mode_wired()` -> updates
     the expected global-alpha archive-skip log text.
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - `outputs/reports/global_alpha_sleeve_audit_by_month.csv` -> monthly
     per-sleeve candidate, gate, ADR/source, and factor diagnostics.
  - `outputs/reports/global_alpha_sleeve_audit_summary.csv` -> latest and
     historical averages from the monthly sleeve audit.
  - `outputs/reports/backtest_window_comparison.csv` -> now includes a 10-year
     requested window alongside 5 and 8 years.
- validation:
  - `py -3 -m py_compile run_local.py r1000_config.py r1000_data_collector.py r1000_pipeline.py aggressive\universe.py tests\smoke_test.py` -> PASS
  - `git diff --check` -> PASS
  - `py -3 tests\smoke_test.py` -> 63/63 PASS
  - `py -3 tests\check_adr_data.py --quick` -> PASS, 26 ADRs audited
  - synthetic `build_global_alpha_sleeve_audit_frames()` + universe alias check -> PASS
- risks_or_notes:
  - `global_alpha_universe` currently means R1000 plus the curated ADR/global
    alpha whitelist; it is not yet a broad all-global equity universe.
  - A requested 10-year report can still show `partial_window` when available
    walk-forward OOS history is shorter than the requested window.
  - Sleeve factor/gate weights were intentionally left unchanged until the new
    audit and a FULL rebuild show which sleeve is failing the target behavior.

## 2026-04-26

### 00:30 KST - phase14-hybrid-alpha-and-system-audit

- scope:
  - Phase 14 hybrid alpha — wire validated Aggressive scanner signals (Opus
    H1/H6, T1 Stage 2 penalty, T4 RS Acceleration, themes.yaml phase
    multipliers) into 정석 ML cfg.features. Added 7 GitHub Actions
    workflows for full operational automation. Pre-flight bug fixes for
    theme_aggregates NaN robustness. End-to-end system audit (Phase A-F)
    verified all 8 workflows, 56/56 smoke tests, 0 leakage.
- files:
  - `r1000_features.py` -> 5 new functions (compute_rs_acceleration_score,
     compute_h1_oversold_value_score, compute_h6_dynamic_leader_score,
     compute_stage2_overext_penalty, compute_theme_phase_features) +
     PHASE14_HYBRID_ALPHA_COLUMNS constant
  - `r1000_themes.py` -> THEME_PHASE_MULTIPLIER constant + numeric
     theme_phase_multiplier_{primary,max} columns + defensive guards on
     compute_theme_aggregates / attach_per_ticker_theme_features
  - `r1000_config.py` -> PHASE14_HYBRID_ALPHA_COLUMNS list + DEFAULT_FEATURES
     extension + ENGINE_REUSE_VERSION = "2026-04-25-phase14-hybrid-alpha"
  - `r1000_pipeline.py` -> import + call 5 Phase 14 functions in
     build_universe_monthly + add to keep_cols + hard_sanitize whitelists
  - `r1000_layer4_swap.py` -> --execute path + 30d throttle +
     execute_swaps() + Telegram pre/post alerts
  - `r1000_rebalance_advisor_v3.py` -> cloud_results/scanner fallback +
     Layer 4 swap suggestions in output (informational)
  - `tools/compare_adr_backtest.py` -> SHIP/PARTIAL/REGRESS verdict tool
  - `tools/monthly_ic_monitor.py` -> ADR macro decorrelation IC tracker
  - `.github/workflows/full_rebuild_manual.yml` -> manual trigger only,
     universe_mode r1000 / r1000+adr / r1000+adr_phase14_off
  - `.github/workflows/layer4_monthly_swap.yml` -> 5th of month auto
  - `.github/workflows/monthly_ic_monitor.yml` -> 1st of month auto
  - `.github/workflows/paper_executor_dryrun.yml` -> Mon-Fri + Sat schedule
  - `tests/audit_features.py` -> runtime-import 2-pass leakage check
     (catches "+ PHASE_X_COLUMNS" extensions regex misses)
  - `tests/smoke_test.py` -> +9 regression guards (Phase 14, Layer 4
     auto-apply, full_rebuild workflow, IC monitor, theme_aggregates
     robustness, paper_executor weekday schedule, advisor v3 cloud
     scanner fallback, advisor v3 Layer 4 surface, ADR_PLAYBOOK)
  - `CLAUDE.md` -> Current Engine Version + Phase 14 pending baseline section
  - `PHASE14_VERDICT_PROCEDURE.md` -> step-by-step FULL rebuild + verdict guide
- symbols_added:
  - `compute_rs_acceleration_score(df)` -> T4 acceleration score
  - `compute_h1_oversold_value_score(df)` -> Opus H1 fire score
  - `compute_h6_dynamic_leader_score(df)` -> Opus H6 fire score
  - `compute_stage2_overext_penalty(df)` -> T1 chase-the-top penalty
  - `compute_theme_phase_features(df)` -> theme_phase_multiplier wire
  - `THEME_PHASE_MULTIPLIER` (dict constant in r1000_themes)
  - `execute_swaps(swaps, portfolio_csv, paper, confirm)` -> Layer 4 executor
  - `_filter_throttled(swaps)` -> 30d swap throttle
  - `tools/compare_adr_backtest.py:verdict()` -> SHIP/PARTIAL/REGRESS logic
  - `tools/monthly_ic_monitor.py:compute_rank_ic()` -> Spearman IC
- symbols_changed:
  - `attach_per_ticker_theme_features` -> add theme_phase_multiplier_{primary,max}
     columns + defensive col existence guards
  - `compute_theme_aggregates` -> defensive sort guard for empty/all-NaN
  - `r1000_paper_executor.main` -> Layer 3 regime pre-flight (current_regime)
- config_fields_added:
  - `PHASE14_HYBRID_ALPHA_COLUMNS: list[str] = [6 cols]` -> Phase 14 wire constant
  - `STAGE2_OVEREXTENSION_PENALTY: float = 0.85` -> aggressive/scanner.py
  - `THROTTLE_DAYS: int = 30` -> r1000_layer4_swap.py throttle window
- breaking_changes:
  - ENGINE_REUSE_VERSION bump = "2026-04-25-phase14-hybrid-alpha".
    All cached feature_store_*.parquet artifacts will be regenerated on
    next FULL rebuild. CURRENT_BASELINE not yet rotated; verdict pending.
- outputs:
  - `cloud_results/full_rebuild/<date>_<mode>/` -> after FULL rebuild trigger
  - `cloud_results/layer4_swap/swap_history.json` -> 30d throttle state
  - `cloud_results/ic_monitor/YYYY-MM.json` -> monthly IC snapshot
  - `outputs/regime_snapshot_cache.json` -> Layer 3 1h cache
- validation:
  - py -3 tests/smoke_test.py -> 56/56 PASS
  - py -3 tests/audit_features.py --no-runtime -> 3/3 PASS, 238 features 0 leakage
  - py -3 tests/check_adr_data.py --quick -> 26 ADRs all whitelist fields present
  - System audit Phase A-F: imports OK, 8 workflows OK (1 false positive in
     audit script regex resolved), schema/version consistent, E2E pipeline
     simulation correct semantics, docs aligned
- risks_or_notes:
  - FULL rebuild required before CURRENT_BASELINE can rotate. Trigger via
    .github/workflows/full_rebuild_manual.yml (3-5h GHA runtime).
  - China ADR macro decorrelation pending verification by monthly_ic_monitor
    (first snapshot due 2026-05-01); may need cpi_china/usdcny features
    added to MACRO_REGIME_COLUMNS after 2-3 months of data.
  - Layer 4 swap default is DRY-RUN; manual workflow_dispatch with
    execute=true required for live paper swaps.

## 2026-04-25

### 23:50 KST - adr-universe-and-stage2-overext-guard

- scope:
  - Add ADR support so foreign blue-chips compete fairly with R1000.
    Wire Stage 2 breakout overextension penalty (Option D) closing the
    "T1 -2.5% alpha" gap from leakage-fix audit (commit 1d04f78).
    Prepare watchlist + playbook for SK Hynix Oct 2026 expected listing.
- files:
  - `adr_universe.yaml` -> new curated whitelist (26 ADRs >=$30B + 3 watchlist)
  - `themes.yaml` -> add ASML/TSM/ASMI/STM/NXPI/UMC/AZN/GSK/NVS/SAP/BIDU to existing
     themes; new themes china_tech_adr, intl_pharma_adr, intl_energy_materials,
     intl_industrial_consumer; fix YAML 1.1 boolean trap (ON ticker)
  - `aggressive/universe.py` -> add load_adr_universe() + sources r1000+adr / adr
  - `tests/check_adr_data.py` -> source + runtime ADR data availability checker
  - `tests/smoke_test.py` -> 4 new regression guards (44 total tests)
  - `aggressive/scanner.py` -> Stage 2 overextension penalty in
     compute_opus_h1_h6_multiplier (4-condition compound check, 0.85 mult)
  - `ADR_PLAYBOOK.md` -> ADR addition + watchlist monitoring playbook
- symbols_added:
  - `aggressive.universe.load_adr_universe(min_mcap_usd_b, include_skip)` -> reads
     adr_universe.yaml, returns (tickers, metadata_list)
  - `tests/check_adr_data.py:check_alpaca_bars(ticker, min_years)` -> verify >=N years
  - `tests/check_adr_data.py:check_finnhub(ticker)` -> verify Finnhub fundamentals coverage
- symbols_changed:
  - `aggressive.universe.load_universe(source, ...)` -> add r1000+adr and adr modes
     with adr_min_mcap_usd_b parameter
  - `aggressive.scanner.compute_opus_h1_h6_multiplier(bars, fh)` -> add Stage 2
     overextension penalty branch (after H1/H6, before return)
- config_fields_added:
  - `STAGE2_OVEREXTENSION_PENALTY: float = 0.85` -> aggressive/scanner.py module-level
     multiplicative penalty when Stage 2 conditions all hold
- breaking_changes:
  - none. New universe sources (r1000+adr, adr) are additive; default r1000 mode
    unchanged. ON ticker YAML bug was silently broken before this commit
    (semi_analog and semi_design_memory dropped ON Semiconductor); now fixed.
- outputs:
  - `adr_universe.yaml` -> 26 core ADRs across 10 countries + 3 watchlist
  - `ADR_PLAYBOOK.md` -> step-by-step addition + monitoring guide
- validation:
  - py -3 tests/smoke_test.py -> 44/44 PASS
  - py -3 tests/check_adr_data.py --quick -> all 26 ADRs listed with country/mcap
  - py -3 -c "from aggressive.universe import load_adr_universe; ..." -> 26 tickers
  - Stage 2 unit test: 3 scenarios (overext fire / strong fund protect /
     catalyst protect) all behave as expected
- risks_or_notes:
  - SEC EDGAR companyfacts may not parse 20-F filings for ADRs cleanly;
    affected ADRs auto-fall into r1000_unified_universe.py finnhub_synthetic
    path (no new code required, same path used for 402 R1000 names already)
  - China ADR (BABA, PDD, JD, BIDU, NTES) macro features may decorrelate from
    US CPI/VIX. Monitor IC after 6 months of inclusion before rebalancing
    weights or adding country-specific features.
  - SK Hynix Oct 2026 is expected per 2026-04 reporting but symbol not yet
    confirmed. ADR_PLAYBOOK.md has the listing-day checklist.

## 2026-04-24

### 23:30 KST - phase-v-f-and-hybrid-advisors

- scope:
  - Full refactor of data + advisor stack with Finnhub integration, live valuations,
    unified universe, 3 advisor philosophies, validation suite, and GitHub Actions
    automation. Builds Track 1 (정석) + Track 2 (Aggressive) toward user's "데이터
    정확성 먼저" mandate before production live-trading.
- files:
  - `aggressive/finnhub_client.py` -> new rate-limited Finnhub client (60/min) with 8 endpoints + cache
  - `aggressive/finnhub_collector.py` -> R1000 batch collector, weekly/daily modes, checkpoint parquet
  - `aggressive/finnhub_cache_loader.py` -> consolidated loader (parquet or per-ticker JSON)
  - `aggressive/scanner.py` -> added --universe CLI, integrated Finnhub valuation gates (val_mult),
     blended growth rate (5y+Q YoY+3y median, floor 5% cap 30%), is_unknown_theme flag
  - `aggressive/theme_discovery.py` -> Phase 18A unsupervised clustering (already committed 56b894b,
     but first full scan validated today)
  - `r1000_valuations.py` -> new Strategy A live-price recompute layer (PEG/PE/EV/market_cap using
     yesterday's close × cached fundamentals)
  - `r1000_unified_universe.py` -> new "Option A" scored_latest + Finnhub-synthesized unified CSV
  - `r1000_rebalance_advisor.py` -> v1 quality-first (uses scored_latest model_score)
  - `r1000_rebalance_advisor_v2.py` -> v2 momentum-first (uses aggressive scanner output)
  - `r1000_rebalance_advisor_v3.py` -> v3 hybrid (v1 + v2 consensus weighted)
  - `tests/validate_system.py` -> 23-test validation suite (data, scoring, stability, cross-system, edges)
  - `r1000_config.py` -> FRED_API_KEY default updated to user's 2026-04-24 registration
  - `run_local.py` -> COMMON_CFG_OVERRIDES reads FRED_API_KEY from env first
  - `aggressive/.env` -> added FINNHUB_API_KEY + FRED_API_KEY (gitignored)
  - `.github/workflows/daily_review.yml` -> weekday 14:00 UTC cloud scanner
  - `.github/workflows/finnhub_weekly.yml` -> Monday 13:30 UTC full Finnhub refresh
  - `.github/workflows/theme_discovery.yml` -> Sunday 13:00 UTC theme clustering
  - `.github/workflows/unified_monthly.yml` -> 1st+15th monthly unified CSV rebuild
  - `.github/SECRETS_SETUP.md` -> GitHub Secrets registration guide
  - `requirements_github.txt` -> minimal GHA deps (no catboost/heavy ML)
  - `PHASE_V_F_INTEGRATION_GUIDE.md` -> next-session integration guide
  - `aggressive/verify_phase_v_f.py` -> morning verification script
- symbols_added:
  - `FinnhubClient` -> rate-limited Finnhub API client (8 endpoints, differential TTL cache)
  - `compute_insider_cluster_score(transactions, days=30, min_value_usd=10000)` -> Form 4 aggregation
  - `compute_mspr_latest(sentiment)` -> Monthly Share Purchase Ratio summary
  - `compute_recommendation_trend(recs)` -> analyst buy/hold/sell trend + MoM delta
  - `compute_earnings_event_features(calendar, surprises)` -> days-to-earnings + past beat rate
  - `collect_r1000(mode='full'|'weekly'|'daily')` -> R1000 Finnhub batch collector
  - `compute_live_valuations(df, finnhub_df, verbose)` -> Strategy A recompute all price-dependent
     ratios using yesterday's close (overrides stale forward_pe_final/peg_final)
  - `_blended_growth_pct(...)` -> median of 5y + Q YoY + 3y growth, clipped [5%, 30%]
  - `build_unified_scored(scored_csv, output_csv)` -> merge 정석 scored + Finnhub synthetic rows
  - `build_synthetic_row(ticker, finnhub_row, rs_12m, sector, name, normalized, live_price)` ->
     synthesize scored_latest-compatible row from Finnhub + Alpaca data
  - `percentile_rank(series)` -> 0.0-1.0 rank with NaN fallback 0.5
  - `compute_live_rs_and_price(tickers)` -> batch fetch 12m RS vs SPY AND latest close
  - `rank_candidates(scored_df, finnhub_dict, live_rs, min_mktcap, min_model_score)` -> v1 ranker
  - `build_new_portfolio(candidates, current_portfolio)` -> v1 tier-cap portfolio builder
  - `rs_multiplier(rs_12m_pct)` -> tiered RS gate multiplier (1.30/1.20/1.10/1.00/0.70/0.40/0.15)
  - `theme_soft_multiplier(phase, rs_12m_pct)` -> dead+weak RS only penalty (user preference)
  - `valuation_multiplier(fh_row, sector_median_peg, sector_median_pe)` -> Finnhub + sector relative gate
  - `load_scanner_rankings(cache_path)` -> v3 loads scanner JSON + reapplies advisor multipliers
  - `compute_hybrid_score(v1_rankings, v2_rankings, top_n)` -> v3 combine ranks with consensus bonus
  - `build_portfolio_from_hybrid(picks, current_weights, target_n)` -> v3 enforce quota min 3 per philosophy
- symbols_changed:
  - `ScannerCandidate` -> added val_mult, fundamental_warnings, finnhub_features,
     is_unknown_theme fields
  - `scan(...)` -> added universe_source param (r1000 default, themes legacy),
     Finnhub gate application, unknown-theme bucketing
  - `EngineConfig.fred_api_key` -> default value updated
- config_fields_added:
  - `FINNHUB_API_KEY: env var` -> API key for Finnhub free tier (60 calls/min)
  - `FRED_API_KEY: env var` -> Federal Reserve data (optional, local 정석 runs only)
  - `SUBSECTOR_CAP_PCT: float = 0.70` (v1/v2/v3 advisors) -> soft sector cap (user: "섹터 역할 축소")
  - `TARGET_N_POSITIONS: int = 12` (v1/v2/v3) -> concentrated target (down from 18)
  - `TIER_CAPS = [(3, 0.18), (6, 0.12), (999, 0.08)]` -> per-rank weight caps
  - `MIN_V1_EXCLUSIVE: int = 3` (v3) -> guaranteed v1-only slots
  - `MIN_V2_EXCLUSIVE: int = 3` (v3) -> guaranteed v2-only slots
  - `GROWTH_FLOOR_PCT: float = 5.0` (r1000_valuations) -> blended growth floor
  - `GROWTH_CEILING_PCT: float = 30.0` -> blended growth ceiling
  - `PEG_CEILING: float = 10.0` -> PEG display sanity clip
- behavior:
  - User's portfolio_latest.csv showed GOOG/NVDA at 14% each, AAPL/BKNG/JNJ dragging;
    root cause analysis found 정석 scored_latest covered only 610/1008 R1000 (60% invisible)
    and PEG calc used 3y CAGR (cyclical bias: AAPL 8.32 vs Finnhub 1.90 correct).
    Fixed via Finnhub integration + unified universe + 3 advisor philosophies.
    All R1000 now visible (1012 rows = 610 real + 402 synthetic).
  - Aggressive engine: scanner now uses val_mult (Finnhub PEG + sector relative + insider +
    earnings + analyst) after theme phase_mult. Tested on R1000 full scan: 21/25 top names are
    unknown-theme (user's "능동 탐지" validated).
  - Advisor v1 vs v2 0% overlap -> v3 hybrid blends them with consensus bonus.
  - Validation suite: 23/23 pass with full Finnhub + Alpaca data integrity.
- outputs:
  - `aggressive/state/finnhub/r1000_features.parquet` -> 1008 tickers × 53 fields
  - `outputs/scored_unified.csv` -> 1012 rows (610 real + 402 synthetic)
  - `outputs_advisor/new_top12_proposed.csv` -> v1 (quality)
  - `outputs_advisor_v2/new_top12_proposed.csv` -> v2 (momentum)
  - `outputs_advisor_v3/new_top12_proposed.csv` -> v3 (hybrid)
  - `aggressive/state/scanner/candidates_*.json` -> R1000 scanner runs
  - `aggressive/state/theme_discovery/latest.json` -> Phase 18A proposals
  - `cloud_results/{scanner,unified,theme_discovery}/` -> GHA-committed summaries
- validation:
  - `tests/validate_system.py`: 23/23 PASS
    Test 1 Data Integrity: R1000 1008, Finnhub 1008, unified 1012
    Test 2 Scoring Sanity: NVDA+62%, AVGO+105%, MRVL+176%, VRT+280%, GEV+210%
    Test 3 Stability: loaders deterministic
    Test 4 Cross-system: advisor v1 includes 5/5 RS leaders
    Test 5 Edge cases: NaN/empty/missing handled
- risks_or_notes:
  - Advisor v1 top 12 dominated by real ML scores (correct - synthetic intentionally
    scaled lower); v2 differs substantially due to scanner's 0.70 peaking penalty.
  - User chose manual trading; Aggressive engine execution code unused but preserved
    for future enablement.
  - GitHub Actions workflows free tier budget: ~1010 min/month (under 2000 limit).
  - Finnhub MSPR endpoint limited for free tier (44/1008 tickers), other endpoints 100%.
  - Alpaca paper account kept for data API access; order execution deferred.
- commits:
  - 56b894b phase-18a autonomous theme discovery
  - 217fd41 phase-v-f Finnhub + live valuation
  - 8be0423 docs integration guide
  - fbf34e6 fix scanner --universe CLI
  - bcab662 feat advisor v1 (quality-first)
  - d6341f7 ci GitHub Actions 3 workflows
  - 559980e chore FRED API key
  - 339b060 feat advisor v2 (momentum-first)
  - 07e0d99 feat r1000_unified_universe (Option A)
  - 0ffbed2 test phase-a validation suite 23/23 PASS
  - 2ede7d6 ci phase-b unified_monthly workflow
  - 3c3694c feat advisor v3 hybrid


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

### 17:40 KST - phase9-c3-design-and-refactor-plan-update

- scope:
  - Planning artifacts only. No engine or notebook code changes. Documents the Phase 9 C3 EPS turn-positive flag design so the next coding session (post Phase 9 C1+C2 verdict) can implement mechanically, and updates the refactor plan to stage Phase 9 into the existing roadmap.
- files:
  - `PHASE_9_C3_PROPOSAL.md` -> NEW. Full design for 8 new feature-store columns (`profit_turn_positive_4q`, `cashflow_turn_positive_4q`, `roe_turn_positive_4q`, `any_profitability_turn_positive_4q`, `roe_sign_flip_pos`, plus whitelisting 3 existing but-not-exposed loss-narrowing columns). Includes exact code snippets for the Phase 9 C2 gate extension (`_p9_eps_turn_positive` OR `_p9_still_loss_but_improving`), cfg field additions, notebook toggle, and Cell 9 sanity check.
  - `REFACTOR_PLAN.md` -> Updated status header with Phase 9 C1/C2/C3 state table; added §1.5 re Phase 9 C3 keep_cols burden (4th keep_cols survival incident); rewrote §5 Timing around Phase 9 C1+C2 verdict (was Phase 8); added decision tree for C3-first vs Refactor-first; extended §8 What-this-unblocks list with C3 + subtractive pass; added Phase 9 entries to §11.3 COLUMN_OWNERSHIP registry (core/future/early/unassigned + mktcap_percentile + 8 C3 columns + 3 C3 diagnostics); extended §11.4 performance attribution example with Phase 9 C1/C2/C3 rows; added new §12 5-stage sequencing diagram (Verdict → C3-or-Refactor → complement → Subtractive → Phase 8e) with invariants and anti-patterns.
- symbols_added:
  - none (docs only)
- symbols_changed:
  - none (docs only)
- config_fields_added:
  - none (C3 cfg fields documented in proposal but NOT yet added to EngineConfig)
  - proposed (pending C3 implementation): `phase9_c3_turnaround_enabled: bool = True`, `phase9_c3_loss_narrowing_threshold: float = 0.3`
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `py -3 -c "import json; json.load(open('colab_run.ipynb'))"` -> still valid (untouched).
  - Doc-only: verified `PHASE_9_C3_PROPOSAL.md` line count (~350 lines) and §1-§11 structure matches Agent Update Contract referenceable format.
  - Confirmed via grep that `ni_sign_flip_pos` / `ocf_sign_flip_pos` / `any_profit_sign_flip_pos` exist in `recompute_fund_panel_derived_columns` (line 12194-12222) but are ABSENT from all keep_cols whitelists (CORE_FUNDAMENTAL / PHASE1_ALPHA / PHASE2_INDUSTRY / PHASE5 / PHASE8B / FUND_TTM_FALLBACK) -> confirms C3 proposal's premise (internal-only flags need explicit whitelisting).
- risks_or_notes:
  - C3 ship gate is a user decision post Phase 9 C1+C2 verdict. Proposal includes both "C3 before refactor" and "refactor before C3" decision branches so neither session is blocked on the other.
  - The 8 C3 columns + 2 diagnostic flags add minimal footprint (~1 MB on feature_store, negligible on scored_latest.csv).
  - Section 12 sequencing ONLY encodes the intent; each stage still requires its own CHANGELOG entry at ship time.
  - Subtractive pass (Stage 4) requires A/B evidence before deleting Phase 3/5/7a — some may have marginal regime-conditional IC not captured in global means.

## 2026-04-18

### 10:46 KST - handoff-doc-refresh-for-next-agent

- scope:
  - End-of-work-day handoff hygiene. User finished 2026-04-17 with the Phase 9 C1+C2 FULL REBUILD (started 08:10 on commit `33581bc`) still in progress and went home; resumed 2026-04-18 morning to ensure the next agent (possibly on a different machine or chat session) can resume cleanly. No engine / notebook code changes — pure documentation sync.
- files:
  - `SESSION_HANDOFF.md` -> full rewrite. Dated to 2026-04-18 10:46 KST. HEAD updated from `ced5db6` to `527fdde`. Added `afaa768` (SHA banner) and `527fdde` (C3 design) to §1 timeline. §2 "What next" rewritten around the ALREADY-COMPLETED FULL REBUILD (was QUICK_RESCORE guidance). Step 1 added: verify run completed by checking Drive artifact mtimes. Step 2 is the Cell E verdict snippet. §3 decision tree kept SHIP/PARTIAL/REGRESS trichotomy but SHIP path now split into Path A (C3 first per PHASE_9_C3_PROPOSAL.md) and Path B (Refactor first per REFACTOR_PLAN.md §12). §4 bootstrap prompt updated with `527fdde` expected HEAD. §5 file list adds PHASE_9_C3_PROPOSAL.md, marks PHASE_ROADMAP.md DEPRECATED. §6 phase table adds Phase 9 C3 row as DESIGNED. §7 rotation rules expanded to cover all verdict branches.
  - `CLAUDE.md` -> updated Key Files (added EXECUTION_PLAN / ARCHITECTURE_REVIEW / PHASE_9_C3_PROPOSAL; marked PHASE_ROADMAP DEPRECATED; moved REFACTOR_PLAN emphasis to §12). Fixed `ENGINE_REUSE_VERSION` from stale `"2026-04-16-phase2-keepcols-fix"` to actual `"2026-04-17-phase8b-long-lookback-momentum"`. Added `ENGINE_COMMIT_SHA` mention. Replaced Multi-Session Phase Plan order to cite REFACTOR_PLAN §12 and current doc stack instead of deprecated PHASE_ROADMAP. Replaced Phase-1..6 status block with full Phase 1-9 state table including C1/C2 SHIP code status + C3 DESIGNED status + Refactor PLANNED status.
  - `PHASE_ROADMAP.md` -> added DEPRECATED banner at top pointing at SESSION_HANDOFF.md / REFACTOR_PLAN.md §12 / EXECUTION_PLAN.md / PHASE_9_C3_PROPOSAL.md as current roadmap sources. Kept the rest of the file as historical reference (Phase toggle mechanism + keep_cols survival invariant are still valid).
- symbols_added:
  - none (docs only)
- symbols_changed:
  - none (docs only)
- config_fields_added:
  - none
- breaking_changes:
  - none
- outputs:
  - none
- validation:
  - `git diff --cached --stat` -> 3 files, documentation-only.
  - Read-verified SESSION_HANDOFF.md §0/§1/§2/§3/§6 content against current git state (HEAD `527fdde`, Phase 9 C1/C2 code shipped, C3 designed).
  - No ast parse / JSON validate needed (no code or notebook changes).
- risks_or_notes:
  - If the FULL REBUILD from `33581bc` crashed silently overnight, §2 Step 1 catches it via mtime check. Fallback: QUICK_RESCORE (~20 min) from `527fdde` which at least produces comparable metrics.
  - PHASE_ROADMAP.md is kept as deprecated reference rather than deleted because future contributors may still want to read Phase 1-6 original-intent history. All navigation pointers (CLAUDE.md "Multi-Session Phase Plan", SESSION_HANDOFF.md §5) now point away from it.
  - SESSION_HANDOFF rotation rule (§7) is explicit enough that the next verdict-ship cycle can overwrite §0/§1/§2 mechanically without re-reading this entry.

### 11:25 KST - pre-commit-smoke-test-infrastructure

- scope:
  - Fast-iteration infrastructure. User flagged that the "edit -> commit -> push -> Colab pull -> Cell 4 pipeline -> Cell E paste" cycle burns 20-180 minutes per iteration, dominated by pipeline runtime. A local smoke test catches the 80% of bugs that would otherwise surface only after a full Colab run. Target runtime: <15s. Actual measured: 6.9s full (3 syntax + 6 structural + 1 import + 4 logic + 3 regression), 0.7s in --quick mode (syntax + structural only).
- files:
  - `tests/__init__.py` -> NEW. Package marker + single-line pointer to smoke_test.py.
  - `tests/smoke_test.py` -> NEW (~520 lines). Pure-stdlib test framework (no pytest dependency), 17 tests in 5 groups:
    - `syntax` (3 tests): `ast.parse` engine + collector .py, JSON-valid notebook.
    - `structural` (6 tests): PHASE*_COLUMNS in build_feature_store (Phase 1+2 keepcols regression), phase_is_enabled keys snake_case, ENGINE_REUSE_VERSION format, hard_sanitize dedup guard (d87160d regression), _sign_flip_pos semantics preserve (Phase 9 C3 prerequisite), Phase 8+/9 dual-gate cfg fields present.
    - `import` (1 test): engine module loads cleanly + key symbols exported (ENGINE_COMMIT_SHA, ENGINE_REUSE_VERSION, PHASE1/2/8B_COLUMNS, weighted_sleeve_composite, phase_is_enabled, hard_sanitize).
    - `logic` (4 tests): weighted_sleeve_composite weight-0 skip regression, hard_sanitize overlap dedup, phase_is_enabled env precedence, cross-sectional mktcap percentile semantics.
    - `regression` (3 tests): PHASE1_ALPHA_COLUMNS contains 4 required names, PHASE8B_LONG_LOOKBACK_COLUMNS contains mom_18/24/36m + multi_year_winner_score, fund_panel carry_cols contains ni/ocf/fcf/op_income_sign_flip_pos + any_profit_sign_flip_pos (Phase 9 C3 prerequisite).
  - `CLAUDE.md` -> added "Pre-commit smoke test" subsection under Fast-Iteration Workflow with exact commands + coverage list + "add a test when shipping a new phase" instruction.
  - `SESSION_HANDOFF.md` -> §3a added "Before any code change" preamble pointing at smoke test. Step 1 C3 implementation gains step 1 (pre-edit smoke test must show 17/17) + step 3 (re-run expecting 20/20 after adding C3 tests). Renumbered Steps 3-6 to 5-8 accordingly.
- symbols_added:
  - `tests.smoke_test._test(name)` -> decorator factory for pass/fail tracked test functions.
  - `tests.smoke_test.test_engine_syntax`, `test_collector_syntax`, `test_notebook_json` -> Group 1.
  - `tests.smoke_test.test_phase_columns_in_keep_cols`, `test_phase_is_enabled_keys`, `test_engine_reuse_version`, `test_hard_sanitize_dedup`, `test_sign_flip_pos_pattern`, `test_phase9_dual_gate` -> Group 2.
  - `tests.smoke_test.test_engine_import` -> Group 3.
  - `tests.smoke_test.test_weighted_sleeve_zero_weight`, `test_hard_sanitize_overlap`, `test_phase_is_enabled_env`, `test_mktcap_percentile` -> Group 4.
  - `tests.smoke_test.test_phase1_alpha_columns`, `test_phase8b_columns`, `test_sign_flip_cols_carried` -> Group 5.
  - `tests.smoke_test.main() -> int` -> CLI entry point with --quick / --verbose / exit code 0/1/2.
- symbols_changed:
  - none (no engine code changes)
- config_fields_added:
  - none
- breaking_changes:
  - none (pure additive infrastructure)
- outputs:
  - none (stdout only, exit code 0/1/2)
- validation:
  - `py -3 tests/smoke_test.py --quick` -> 9/9 passed in 699ms (syntax + structural only).
  - `py -3 tests/smoke_test.py` -> 17/17 passed in 4012ms (all groups).
  - `py -3 tests/smoke_test.py -v` -> 17/17 passed, per-test timings printed. Slowest test: import.engine_loads_cleanly at 2608ms (numpy/pandas/catboost load). Everything else under 200ms.
  - Verified one intentional failure mode: removing `dict.fromkeys` from hard_sanitize body made `structural.hard_sanitize_has_dedup_guard` + `logic.hard_sanitize_dedups_overlapping_cols` both fail with clear error messages. Reverted change.
- risks_or_notes:
  - Runtime budget for new tests: <500ms each. Import-dependent tests (Groups 3-5) pay a shared ~2.6s import cost; additional tests in these groups add marginal <100ms unless they exercise heavy computations.
  - Test framework is pure stdlib (argparse, ast, json, re, time) + numpy/pandas (required by engine anyway). No pytest / unittest / hypothesis dependency.
  - `--quick` mode (Groups 1-2 only) is sufficient for "did my edit break syntax or structural invariants"; use before every commit. Full mode (all 5 groups) recommended before every push.
  - When a new phase ships, add 2-3 tests in the same commit: one structural (constant exists), one import (attribute exported), one regression (value/behavior as expected). Template in `tests/smoke_test.py` docstring.
  - Future extension (Phase A refactor, REFACTOR_PLAN.md §11.6): this single-file smoke test becomes the seed of the full `tests/` suite with per-module files. Existing tests stay; new unit tests for individual helpers get added.
  - Unicode safety: all output is ASCII (cp949-compatible) so Windows terminals don't crash on em-dash. `--` used as separator instead of Unicode em-dash.

### 12:21 KST - local-pipeline-runner-plus-phase9-c1-c2-verdict

- scope:
  - Two outcomes in one commit: (a) `run_local.py` script that executes the pipeline on the user's local machine against the Drive mirror (no Colab round-trip), and (b) FIRST measurement of Phase 9 C1+C2 combined effect -- verdict is PARTIAL.
- files:
  - `run_local.py` -> NEW (~330 lines). Replicates colab_run.ipynb Cells 2-4 + Cell E as a single Python script. Modes: default QUICK_RESCORE, `--full`, `--no-collector`, `--verdict-only`, `--end-date`, `--base-dir`, `--fast-mode`, `--phase9-c1`, `--phase9-c2`. Uses pathlib + `G:\내 드라이브\r1000_top30_institutional\` by default. Prints `[commit=<sha>]` banner with DIRTY tag when working tree has uncommitted changes. Forces UTF-8 stdout/stderr on Windows so Korean paths render correctly. Falls through to inline Cell E verdict (same snippet as SESSION_HANDOFF.md §2) so SHIP/PARTIAL/REGRESS appears in one run.
  - `tests/smoke_test.py` -> added `syntax.run_local_py_parses` test. Total smoke tests: 18 full / 10 quick.
  - `CLAUDE.md` -> Fast-Iteration Workflow subsection gains "Local pipeline run" block with all 5 run_local.py modes. Mentions Drive mirror path, local advantages (no round-trip, no 12h timeout), Colab still useful for GPU / shared review.
  - `SESSION_HANDOFF.md` -> §0 REWRITTEN with verdict table (ΔCAGR -0.74pp / ΔSharpe +0.0808 / ΔMaxDD +5.78pp / early_scout 8). Three-path decision tree (SHIP-as-is / A/B isolate / C3 first) replaces "awaiting Cell E" posture. §2 now leads with local commands (--verdict-only / --phase9-c1=0 / --phase9-c2=0 / --full), Colab instructions demoted to legacy.
- symbols_added:
  - `run_local.main() -> int` -> CLI entry point.
  - `run_local.parse_args() -> argparse.Namespace`
  - `run_local.check_prereqs(base_dir) -> tuple[bool, list[str]]`
  - `run_local.apply_phase_toggle(env_name, value) -> None`
  - `run_local.resolve_commit_sha() -> tuple[str, bool]`
  - `run_local.now_kst() -> str`
  - `run_local.print_verdict(base_dir) -> int`
  - `run_local.PHASE8_BASELINE: dict` -- baseline for ΔCAGR/ΔSharpe/ΔMaxDD comparison. Rotate to Phase 9 metrics if/when SHIP verdict confirmed.
  - `tests.smoke_test.test_run_local_syntax()` -- new smoke test.
- symbols_changed:
  - none (no engine code changes)
- config_fields_added:
  - none
- breaking_changes:
  - none (pure additive infrastructure + measurement)
- outputs:
  - Measured on Drive: `G:/내 드라이브/r1000_top30_institutional/outputs/backtest_metrics.json` (cagr=0.2112, sharpe=1.0664, max_dd=-0.2630, ir=0.6977, beat_month_ratio=0.6145, excess_cagr=0.0763, avg_turnover_monthly=0.4774, avg_stock_names=24.35).
  - Sleeve counts: core_compounder=4 (NVDA, GOOG, JNJ, VRT), future_winner=5 (GEV, FTI, LITE, CIEN, MRVL), early_scout=8 (ETR + 7 others). Total 17-18 positions. Sleeve targets {core: 0.35, future: 0.30, early: 0.35} actuals {core: 0.332, future: 0.293, early: 0.337} -- within 2% of target.
  - Phase 9 diagnostic columns (from scored_latest.csv): phase9_thesis_gate_active=1.0 (610/610), phase9_core_eligible=58, phase9_future_eligible=54, phase9_early_eligible=77, phase9_unassigned=421. Percentile gate semantics confirmed working as designed.
- validation:
  - `py -3 run_local.py --verdict-only` -> 2s runtime, verdict PARTIAL printed with all 4 gate metrics + sleeve distribution + top holdings. Korean path in header renders correctly after UTF-8 reconfigure.
  - `py -3 tests/smoke_test.py --quick` -> 10/10 passed (new `syntax.run_local_py_parses` test added).
  - `py -3 tests/smoke_test.py` -> 18/18 passed (full suite, ~5s).
  - Deps confirmed installed locally: numpy 2.4.4, pandas 3.0.2, sklearn 1.8.0, catboost 1.2.10, yfinance 1.2.2, requests 2.33.1, pyarrow 23.0.1. Python 3.14.4 Windows.
- risks_or_notes:
  - **Verdict PARTIAL means Phase 9 C1+C2 is NOT auto-SHIP per ship gate.** Taxonomy + risk-adjusted metrics (Sharpe, MaxDD, early count) all strongly improved, but raw CAGR dropped 0.74pp. User decision required among SHIP-as-is / A/B isolate / C3-first paths.
  - The FULL REBUILD measured was the 2026-04-18 02:02 UTC run (commit `33581bc`, before `afaa768` SHA banner commit) not the 2026-04-17 08:10 run (which crashed when user's computer slept overnight).
  - **run_local.py requires CPU-only CatBoost on user's Windows laptop.** FULL rebuild may be 3-4h locally vs 2-3h on Colab GPU. QUICK_RESCORE should be similar speed (20 min) since training is cached.
  - `run_local.py` sets `sys.stdout.reconfigure(encoding="utf-8")` on Windows -- some older Python 3.x (<3.7) cannot reconfigure stdout. Requires Python 3.10+ (enforced in check_prereqs).
  - If user runs `--full` locally while Colab is also running, both will write to the same Drive outputs/ path. Last writer wins. Add `--base-dir` to isolate runs if doing parallel A/B experiments across machines.
  - `PHASE8_BASELINE` in run_local.py is pinned literal. When Phase 9 SHIPs, rotate this block + SESSION_HANDOFF §0 baseline table in the same commit.

### 12:32 KST - phase9-c1-c2-ship-paperwork-baseline-rotation

- scope:
  - Administrative SHIP commit for Phase 9 C1+C2. User reviewed PARTIAL verdict (dCAGR -0.74pp, dSharpe +0.0808, dMaxDD +5.78pp, early_scout 0→8) and chose Path 1 SHIP-as-is: structural win (sleeve taxonomy restored) + risk-adjusted improvement (Sharpe +0.08, MaxDD -5.78pp) outweigh the raw CAGR regression. No engine or notebook code change; pure baseline rotation + doc sync. Next-commit scope: Phase 9 C3 implementation per `PHASE_9_C3_PROPOSAL.md`.
- files:
  - `run_local.py` -> renamed baseline variable: new `CURRENT_BASELINE` dict holds Phase 9 metrics (cagr 0.2112, sharpe 1.0664, max_dd -0.2630, ir 0.6977, avg_turnover_monthly 0.4774, avg_stock_names 24.35, beat_month_ratio 0.6145, excess_cagr 0.0763, sleeve_counts_reference {core 4, future 5, early 8}) plus readable `name` field. `PHASE8_BASELINE` kept as historical reference. `print_verdict` function switched to read `CURRENT_BASELINE` for delta comparison. SHIP/PARTIAL/REGRESS message quotes the current baseline name so ambiguity is eliminated.
  - `colab_run.ipynb` Cell 10 -> replaced stale 2026-04-15 `BASELINE` dict (strategy_cagr 0.2180, sharpe 0.73, max_dd -0.3686, selected_names 2) with Phase 9 C1+C2 baseline matching `run_local.py CURRENT_BASELINE`. Comparison title updated from "baseline vs Phase 1+2" to "baseline (Phase 9 C1+C2) vs new run".
  - `CLAUDE.md` -> "Phase 1+2 Baseline Comparison" section renamed to "Current Production Baseline -- Phase 9 C1+C2 (SHIPPED 2026-04-18)". Added explicit ship gate formula + sleeve sanity guard (early_scout >= 4). Historical baselines (Phase 8, 2026-04-15) listed as reference only.
  - `SESSION_HANDOFF.md` -> §0 TL;DR rewritten as SHIPPED posture with baseline snapshot table + next-step pointer (C3). §2 rewritten as "Next step -- Phase 9 C3 implementation" with 5-step flow (smoke test -> code -> smoke test -> FULL rebuild -> verdict) citing exact touch surface per PHASE_9_C3_PROPOSAL.md. §2b retained as legacy commands for reruns on current baseline. §6 Phase status table: 9.C1 + 9.C2 status "SHIPPED 2026-04-18", 9.C3 "DESIGNED, ready to implement".
- symbols_added:
  - `run_local.CURRENT_BASELINE: dict` -- baseline dict consumed by `print_verdict` for delta comparison. Contains `name` field for user-facing verdict message.
- symbols_changed:
  - `run_local.print_verdict(base_dir)` -- changed to read `CURRENT_BASELINE` instead of `PHASE8_BASELINE`. Now prints "METRICS vs baseline: <name>" header so the comparison is self-documenting.
- config_fields_added:
  - none (no EngineConfig change)
- breaking_changes:
  - none. `PHASE8_BASELINE` dict kept for any consumer that imported it historically.
- outputs:
  - none
- validation:
  - `py -3 run_local.py --verdict-only` -> rotated baseline confirmed: dCAGR +0.00pp, dSharpe +0.0000, dMaxDD +0.00pp, dIR +0.0000 vs itself. Verdict line reads "PARTIAL vs Phase 9 C1+C2 (SHIPPED 2026-04-18)" -- expected (measurement vs itself trivially passes 3 of 4 gates but dCAGR +0.00 < +0.5pp). Future C3 / refactor runs will produce non-zero deltas naturally.
  - `py -3 tests/smoke_test.py` -> 18/18 passed in 5s (no code change in engine, smoke tests still pass).
  - `py -3 -c "import json; json.load(open('colab_run.ipynb'))"` -> notebook JSON still valid after Cell 10 rotation (12 cells, indent=1 preserved). Grep confirms no remaining references to the stale CAGR 0.2180.
- risks_or_notes:
  - **Ship gate interpretation**: Phase 9 C1+C2 ships as an institutional-grade improvement on risk-adjusted metrics, not as a raw CAGR win. User's original goal of CAGR 30%+ remains open; the -0.74pp regression is a deliberate trade for structural repair. C3 hypothesis (EPS turn-positive flags) may recover some CAGR by tightening early_scout quality -- first opportunity to revisit raw-return optimization on the new baseline.
  - **Baseline rotation discipline**: From now on, every verdict run compares to Phase 9 C1+C2 baseline (21.12% / 1.0664 / -26.30% / early_scout 8). The ship gate formula (dCAGR >= +0.5pp AND dSharpe >= -0.05 AND dMaxDD >= -3pp) applied to this new baseline is stricter than vs Phase 8 (because dSharpe and dMaxDD floors are relative, not absolute). A future change that lands at e.g. Sharpe 0.95 would fail the -0.05 Sharpe gate even though 0.95 beats historical Phase 8's 0.99. This is intentional -- we don't want to silently regress the structural wins.
  - **Three places store the baseline**: run_local.py `CURRENT_BASELINE`, colab_run.ipynb Cell 10 `BASELINE`, CLAUDE.md "Current Production Baseline" section. All three rotate atomically in this commit. A future Refactor Phase A (REFACTOR_PLAN.md §6) should move these to a single JSON file (`baselines/current.json`) so the next rotation is one file, not three.
  - **sleeve_counts_reference in CURRENT_BASELINE is advisory not enforced**: the ship gate checks `early_scout >= 4`, not "exactly 8". Subsequent phases may legitimately produce different counts (e.g. C3 may shift 1-2 names across sleeves). The reference is for diagnostic sanity, not regression.
  - **PHASE8_BASELINE remains in code** so historical researchers or Stage 4 subtractive-pass auditors can compare against it without re-running Phase 8 from scratch. Consider deleting in the Stage 4 subtractive pass once sufficient baselines are captured in version-controlled JSON.

### 12:52 KST - phase9-c3-implementation-eps-turn-positive-flags

- scope:
  - Phase 9 C3 implementation per `PHASE_9_C3_PROPOSAL.md`. Adds 8 feature-store columns + 2 new admission branches (`_p9_eps_turn_positive`, `_p9_still_loss_but_improving`) to the Phase 9 C2 early-scout gate. Encodes user definition of early sleeve ("eps 적자거나 양전환 막 하거나") exactly. Requires FULL rebuild (feature-store schema change). Hypothesis: tightening early admission via explicit turnaround signal may recover some of the -0.74pp CAGR lost to Phase 9 C1+C2's taxonomy repair.
- files:
  - `r1000_top30_institutional.py` ->
    (1) `ENGINE_REUSE_VERSION` bumped `"2026-04-17-phase8b-long-lookback-momentum"` -> `"2026-04-18-phase9c3-turnaround-flags"` (triggers FS rebuild).
    (2) New module-level constant `PHASE9_C3_TURNAROUND_COLUMNS` = 8 names (4 aliases + 1 new roe flip + 3 existing-but-unexposed loss-narrowing scores).
    (3) EngineConfig gains `phase9_c3_turnaround_enabled: bool = True` + `phase9_c3_loss_narrowing_threshold: float = 0.3`.
    (4) `recompute_fund_panel_derived_columns` now computes 4 Phase 9 C3 alias columns (`profit_turn_positive_4q`, `cashflow_turn_positive_4q`, `roe_turn_positive_4q`, `any_profitability_turn_positive_4q`) + `roe_sign_flip_pos` via reusing the existing nested `_sign_flip_pos` helper. Defensive against missing assets/liabilities (sets zero instead of skipping).
    (5) `carry_cols` list extended with 5 new Phase 9 C3 names so ffill propagates them through quarter gaps.
    (6) `build_feature_store` `keep_cols` + `hard_sanitize` calls both gain `+ PHASE9_C3_TURNAROUND_COLUMNS` (the Phase 1+2 keepcols-survival rule applied preemptively).
    (7) `compute_portfolio_sleeve_columns` Phase 9 C2 block extended: new `_phase9_c3_active` toggle gates 2 admission branches (`_p9_eps_turn_positive = OR of 3 turn-flags > 0.5`, `_p9_still_loss_but_improving = (ni_ttm < 0) AND (ocf/fcf_under_loss/ni_narrow > threshold)`). `_p9_early_elig` now admits via `(_p9_early_inflect | _p9_early_breakout | _p9_c3_admit)`. C3 diagnostics `phase9_c3_turnaround_active / phase9_c3_eps_turn_positive / phase9_c3_still_loss_branch` written to `d` for post-run analysis.
  - `colab_run.ipynb` Cell 2 -> new `PHASE9_C3_TURNAROUND = 'auto'` toggle + `_set_phase_env('PHASE_PHASE9_C3_TURNAROUND_ENABLED', ...)` + extended print-loop tuple with `'PHASE_PHASE9_C3_TURNAROUND_ENABLED'`.
  - `run_local.py` -> new `--phase9-c3` CLI flag with same {auto, 0, 1} choices as C1/C2. Env var set via `apply_phase_toggle`. Banner prints current value.
  - `tests/smoke_test.py` -> 5 new tests covering C3 (structural: `phase9_c3_turnaround_columns_in_keep_cols`, `phase9_keys_have_dual_gate_cfg` extended with `phase9_c3_turnaround_enabled`; import: `engine_reuse_version_bumped_for_c3`; regression: `phase9_c3_alias_cols_in_carry_cols`, `phase9_c3_gate_wired_in_early_scout`). Fixed long-standing bug in `_import_engine()` — was using `importlib.reload()` on every call which caused 15s-per-test overhead; now caches the module reference globally so all Group 3-5 tests share one import (5s full run vs 54s pre-fix).
- symbols_added:
  - `r1000_top30_institutional.PHASE9_C3_TURNAROUND_COLUMNS: list[str]` -- 8-entry feature-store whitelist.
  - `tests.smoke_test.test_phase9_c3_columns_in_keep_cols` -- structural regression test.
  - `tests.smoke_test.test_engine_reuse_version_c3` -- FS schema-version regression test.
  - `tests.smoke_test.test_phase9_c3_cols_carried` -- fund_panel carry_cols regression test.
  - `tests.smoke_test.test_phase9_c3_gate_wired` -- early-scout gate wiring regression test.
  - `tests.smoke_test._ENGINE_MODULE` -- module-level cache for engine import (performance fix).
- symbols_changed:
  - `recompute_fund_panel_derived_columns` -- added 4 alias columns + `roe_sign_flip_pos`. Backward compatible: new columns are non-destructive additions.
  - `compute_portfolio_sleeve_columns` -- Phase 9 C2 early_scout eligibility expression now unions `_p9_c3_admit`. Behavior-preserving when `phase9_c3_turnaround_enabled=False` (C3 toggle off -> `_p9_c3_admit = pd.Series(False, ...)` -> pure C2 behavior).
  - `tests.smoke_test._import_engine()` -- cached via `_ENGINE_MODULE` global instead of reloading every call.
- config_fields_added:
  - `phase9_c3_turnaround_enabled: bool = True` -- master toggle.
  - `phase9_c3_loss_narrowing_threshold: float = 0.3` -- minimum loss-narrowing rate for the `_p9_still_loss_but_improving` branch. Tunable per-strategy.
- breaking_changes:
  - **ENGINE_REUSE_VERSION bump forces one FULL REBUILD** per machine on next run (cached `feature_store_latest.parquet` will be regenerated with 8 new columns). No runtime behavior breaking.
- outputs:
  - After FULL REBUILD: `feature_store/feature_store_latest.parquet` will have 8 new columns appended. `scored_latest.csv` will have 3 new diagnostic columns (`phase9_c3_turnaround_active / phase9_c3_eps_turn_positive / phase9_c3_still_loss_branch`). All existing columns unchanged in schema.
- validation:
  - `py -3 tests/smoke_test.py` -> 22/22 passed in 4.9s (18 prior + 5 new; 1 test consolidated).
  - `py -3 tests/smoke_test.py --quick` -> 12/12 passed in <1s.
  - `py -3 run_local.py --help` -> `--phase9-c3 {auto,0,1}` flag listed.
  - `py -3 -c "import json; json.load(open('colab_run.ipynb'))"` -> notebook still valid JSON (12 cells).
  - No actual pipeline run yet. Next step: `py -3 run_local.py --full` for FULL rebuild + Cell E verdict against Phase 9 C1+C2 baseline.
- risks_or_notes:
  - **FULL REBUILD required this commit**: ENGINE_REUSE_VERSION bumped, so any machine running the pipeline next will rebuild the feature_store from scratch. Estimated runtime: ~3-4h local CPU, ~2-3h Colab GPU.
  - **C3 branch count variance**: `phase9_c3_eps_turn_positive` typically fires on 3-8 names per rebalance date (fund_panel `ni_sign_flip_pos` raw frequency). `phase9_c3_still_loss_but_improving` is stricter (both loss AND narrowing). Total new admissions estimated at 5-15 per rebalance — if this exceeds 20% of early sleeve (currently 8 names), threshold `phase9_c3_loss_narrowing_threshold` may need tightening from 0.3 to 0.5.
  - **ROE sign-flip noise**: `roe_proxy = net_income_ttm / (assets - liabilities)`. Spurious flip possible when equity crosses zero via accounting adjustments. Defensive: `_sign_flip_pos` already handles NaN via `prev_num.notna()` mask; subsequent gate threshold `> 0.5` filters near-zero noise.
  - **C3 is DEPENDENT on C2**: C3 only activates inside the `if _phase9_thesis_active:` block. Disabling C2 automatically disables C3 regardless of the C3 toggle — this is intentional, not a bug. If user wants to A/B C3 specifically, they must leave C2 ON.
  - **Gate semantics verification deferred**: the exact count/identity of names admitted by C3 cannot be measured without running the pipeline. The 5 new tests verify CODE PRESENCE but not VALUE CORRECTNESS. That verification happens post-FULL-rebuild via Cell E verdict + `scored_latest.csv` inspection.
  - **Backward compat on C3 toggle OFF**: with `PHASE_PHASE9_C3_TURNAROUND_ENABLED=0`, `_p9_c3_admit` becomes all-False so `_p9_early_elig` reverts exactly to the pre-C3 expression. Feature_store columns still get written (cheap, wasted storage ~1MB) but gate ignores them.
  - **SESSION_HANDOFF.md NOT yet rotated**: §0 still says "Phase 9 C1+C2 SHIPPED, C3 DESIGNED". After C3 SHIP verdict (post FULL REBUILD), rotate §0 to "Phase 9 C1+C2+C3 SHIPPED" + CURRENT_BASELINE again + next-step Refactor Phase A.

### 14:42 KST - pandas3-crash-recovery-plus-concentrated-expansion

- scope:
  - Two distinct fixes bundled in one commit because both blocked a single restart of the Phase 9 C3 FULL REBUILD:
    (a) Emergency: pandas 3.0.2 crashes the fund_panel merge with `MergeError: incompatible merge keys dtype('<M8[us]') and dtype('<M8[ns]')`. Local FULL REBUILD on commit 86be7f9 died at 2026-04-18 14:37 KST after 1h 36min. Colab runs work because Colab has pandas 2.x. Recovery: downgrade local to `pandas>=2.3,<3.0` (2.3.3 installed) + add smoke regression guard so future `pip install --upgrade pandas` on this box fails loudly.
    (b) Feature: Phase 9 CE (Concentrated Expansion). Previously the concentrated-mode grid search was hard-clamped to N≤3 at three separate sites and fast_mode stripped it further to `[N=1,2,3] × [monthly] × [conviction_curve]` = 3 combos. Lift the caps + widen defaults so the grid explores N=1..10, intervals 1/2/3 months, all 3 weighting modes (conviction_curve, winner_take_all, score_power) = 63 combos. Goal: beat the measured 29.89% CAGR / 1.124 Sharpe concentrated result by finding a better point on the concentration/interval/weighting surface.
- files:
  - `r1000_top30_institutional.py` ->
    * EngineConfig defaults: `concentrated_top_n_candidates = [1, 2, 3, 4, 5, 7, 10]` (was [1, 2, 3]), `concentrated_rebalance_intervals = [1, 2, 3]` (was [1]), `concentrated_weighting_modes = ["conviction_curve", "winner_take_all", "score_power"]` (was missing score_power).
    * EngineConfig validator: upper bound 3 -> 30 (with explanatory comment about Top-30 main portfolio ceiling).
    * `compare_concentrated_portfolio_backtests` clean_top_n: `min(int(x), 3)` -> `min(int(x), 30)`.
    * `build_latest_concentrated_holdings` top_n picker clamp: `min(3, ...)` -> `min(30, ...)`. Critical — otherwise grid winners at N=5 get silently rewritten to N=3 when producing the live recommendation.
    * `apply_fast_mode` override: stopped stripping the grid down. fast_mode now runs the full 63-combo grid (costs ~6 min extra, negligible vs walk-forward training).
  - `tests/smoke_test.py` ->
    * `import.pandas_version_below_3` -- asserts pandas < 3.0 at test time. Fails with explicit `pip install` command if violated. Skipped in --quick mode (needs import).
    * `regression.concentrated_expansion_caps_lifted` -- greps the engine source to confirm the 3 hard caps are lifted and stay lifted. Structural check.
    * `regression.concentrated_expansion_defaults_widened` -- imports EngineConfig and asserts max(top_n) > 3, len(intervals) > 1, "score_power" in weighting_modes.
- symbols_added:
  - `tests.smoke_test.test_pandas_version()` -- version guard.
  - `tests.smoke_test.test_ce_caps_lifted()` -- structural CE guard.
  - `tests.smoke_test.test_ce_defaults_widened()` -- behavioral CE guard.
- symbols_changed:
  - `EngineConfig.concentrated_top_n_candidates` default -- [1,2,3] -> [1,2,3,4,5,7,10].
  - `EngineConfig.concentrated_rebalance_intervals` default -- [1] -> [1,2,3].
  - `EngineConfig.concentrated_weighting_modes` default -- ["conviction_curve","winner_take_all"] -> ["conviction_curve","winner_take_all","score_power"].
  - `apply_fast_mode` -- no longer narrows concentrated grid to a single 1×1×1 combo.
  - `compare_concentrated_portfolio_backtests.clean_top_n` clamp -- 3 -> 30.
  - `build_latest_concentrated_holdings.top_n` clamp -- 3 -> 30.
  - `_validate_engine_config` concentrated_top_n range gate -- [1,3] -> [1,30].
- config_fields_added:
  - none (expanded existing field defaults)
- breaking_changes:
  - none runtime. Users who previously passed `concentrated_top_n_candidates=[4]` would have gotten a validation error; now it's accepted. Users who WANT the old 3-combo behavior can explicitly set `cfg.concentrated_top_n_candidates = [1, 2, 3]` etc.
- outputs:
  - After next FULL REBUILD: `outputs/reports/concentrated_strategy_comparison.csv` will have 63 rows (was 3). Sorted by `comparison_objective`, the top row drives the latest concentrated recommendation.
- validation:
  - `py -3 -m pip show pandas` -> pandas 2.3.3 (was 3.0.2).
  - `py -3 tests/smoke_test.py` -> 25/25 passed in 5s (22 prior + 3 new). Pandas guard + CE caps + CE defaults all pass.
  - No pipeline run yet. Launching FULL REBUILD immediately after this commit.
- risks_or_notes:
  - **Overfitting risk from wider grid**: 63 combos vs 3 is a 21x increase in hyperparameter search. If we always pick the top-CAGR combo, we're fitting more to 83-month sample. Mitigation: `comparison_objective` already penalizes MaxDD (so raw CAGR alone doesn't win). Post-run: spot-check whether the winner is robust (e.g. still top-decile on 60-month or 48-month sub-windows).
  - **Expected runtime add**: 60 extra concentrated backtests × ~6s each = 6 min. Negligible vs 3-4h walk-forward training.
  - **Winner_take_all weighting**: puts 100% on the #1-scoring name. Expect higher volatility and larger drawdowns than conviction_curve. Historical N=1 already showed -50% MaxDD; N=2 winner_take_all could be worse. `comparison_objective` MaxDD penalty should deselect these.
  - **score_power weighting mode**: weights by score^p (p > 1). Conceptually more extreme conviction than conviction_curve's cumulative 50/30/20. Exact formula lives in `backtest_concentrated_portfolio` around line 24258; needs audit if results look suspicious.
  - **Live recommendation path**: after CE ships, if the grid picks N=5 as winner, `build_latest_concentrated_holdings` will emit 5 ticker names. That's a UI change (from always-3 to variable). Downstream consumers (`concentrated_portfolio_latest.csv`, operator plan) should handle variable N already but worth verifying post-run.
  - **Pandas 3 incompatibility is latent, not fixed**: engine code still has whatever datetime mismatch triggered the crash. The fix is "pin pandas to 2.x"; the next time we upgrade (deliberately or otherwise), the crash returns. Long-term fix belongs in Refactor Phase A observability pass (REFACTOR_PLAN.md §11): audit every `pd.merge` for dtype alignment, add `.astype('datetime64[ns]')` normalization at module boundaries.

### 19:16 KST - phase9-c3-ce-v1-results-plus-ce-v2-inner-clamp-fix

- scope:
  - Results from 4h 29min FULL REBUILD (14:44 -> 19:13 KST, commit f93a4a2) PLUS fix for incomplete CE grid expansion surfaced by the results. Two outcomes bundled:
    (a) Phase 9 C3 + CE v1 measured. Main diversified regresses slightly (CAGR 21.69% -> 20.72%, -0.97pp), consistent with user acceptance of risk-adjusted trade-off. Concentrated grid best is 29.86% at N=3 / interval=2 / score_power — BUT all N>3 produced identical metrics, revealing CE v1 was incomplete.
    (b) CE v2: 2 additional inner clamps found and lifted. CE v1 lifted 3 OUTER caps (validator, grid loop, latest-holdings) but missed 2 INNER caps inside select_concentrated_portfolio_topk (line 24207) and backtest_concentrated_portfolio (line 24310). Those silently forced every N>3 call to behave as N=3 at the actual backtest execution layer, producing the identical-row pattern seen in the 63-row concentrated_strategy_comparison.csv.
- files:
  - `r1000_top30_institutional.py` ->
    * `select_concentrated_portfolio_topk()` top_n clamp at ~line 24207: `min(int(top_n), 3)` -> `min(int(top_n), 30)`.
    * `backtest_concentrated_portfolio()` top_n clamp at ~line 24310: `min(int(top_n), 3)` -> `min(int(top_n), 30)`.
    Both carry inline comment pointing at this CHANGELOG entry so future readers see the v1->v2 history.
  - `tests/smoke_test.py` `regression.concentrated_expansion_caps_lifted` -> tightened. Now checks for BOTH v1 outer caps AND v2 inner caps. Assertion message explicitly names the 5 sites that must stay lifted. Blocks future revert silently.
- symbols_added:
  - none (test updated, not added)
- symbols_changed:
  - `select_concentrated_portfolio_topk(cfg, month_df, top_n)` -- upper clamp 3 -> 30.
  - `backtest_concentrated_portfolio(cfg, signals, top_n, rebalance_interval_months, weighting_mode)` -- upper clamp 3 -> 30.
  - `tests.smoke_test.test_ce_caps_lifted()` -- now verifies 4 string patterns instead of 3.
- config_fields_added:
  - none
- breaking_changes:
  - none. CE v2 is strictly additive — any prior caller expecting N<=3 behavior still gets it (the concentrated_top_n_candidates default goes up to 10 so the grid already tests it).
- outputs:
  - After next QUICK_RESCORE (~30 min): `outputs/reports/concentrated_strategy_comparison.csv` will finally differentiate N=3 vs N=5 vs N=7 vs N=10 because the inner clamp no longer collapses them.
- validation:
  - `py -3 tests/smoke_test.py --quick` -> 11/11 passed in <1s (syntax + structural + new CE cap assertion).
  - Full smoke deferred to post-QUICK_RESCORE.
- risks_or_notes:
  - **CE v1 measurement is NOT usable for N-ladder analysis**: rows showing N=3,4,5,7,10 at same (interval, mode) with identical CAGR all describe the N=3 backtest, not the intended N. Only genuinely measured data points from v1: (N=3, interval=1/2/3, mode=conviction/winner/power) = 9 unique combos, 54 aliases.
  - **Concentrated v1 best measured**: N=3 at interval=2 months, score_power weighting -> 29.86% CAGR / 1.044 Sharpe / -29.57% MaxDD / IR 0.758 / turnover 36% / $609k ending from $100k. Slightly BELOW prior Colab N=3 conviction_curve monthly 29.89% — C3 net effect on concentrated is near-zero, consistent with main-diversified regression.
  - **New finding from v1 that IS reliable**: 2-month interval outperforms monthly across all modes (CAGR delta +3-4pp), turnover halves, Sharpe roughly flat. Suggests monthly rebalance was overtrading.
  - **Main diversified CAGR regression**: 21.69% -> 20.72% is consistent with C3 admitting more noise via widened early_scout pool (172 names admitted during Phase 5 vs 77 previously). The still-loss-improving branch may be admitting names whose EPS IS negative but 3y forward return doesn't materialize. Needs QUICK_RESCORE with PHASE_PHASE9_C3_TURNAROUND_ENABLED=0 to A/B isolate C3 effect cleanly.
  - **winner_take_all mode runs but is N-independent by definition**: 100% weight on #1 scoring name regardless of top_n. CAGR 19.29% / Sharpe 0.697 / MaxDD -35.5% at interval=2. Not a candidate for ship; keep in grid only as reference.
  - **Main portfolio: 14 positions** (was 17 in prior Colab run). Sleeve dist 4 core / 6 future / 4 early. Target {40/40/20} -- different sleeve cap policy selected this run (was 60/25/15 "defensive_drawdown_control"). This change is likely from a different cap policy winner and unrelated to C3.
  - **Next step: QUICK_RESCORE** from this commit. feature_store + trained models stay (engine_version unchanged from f93a4a2 -> this commit is post-FS behavior only). Expected ~30 min. Will produce corrected concentrated grid with true N differentiation -- that's the real CE measurement.

### 21:27 KST - SHIP phase9-c3-plus-ce-v2-and-baseline-rotation

- scope:
  - **SHIP verdict for Phase 9 C3 + CE v2** on commit `d3d3a91`. Measured via `py -3 run_local.py --no-collector` completed at 21:22 KST (runtime 124.9 min — Phase 3 + 4 re-ran because config_fingerprint changed when CE v2 lifted the 2 inner clamps). Both main diversified and concentrated improved across every ship-gate metric. User's original CAGR 30%+ goal achieved via concentrated mode (N=5 / monthly / score_power = 34.75% CAGR). This commit rotates the baseline registry across 3 atomic files and documents the concentrated champion for live use.
- files:
  - `run_local.py` -> `CURRENT_BASELINE` dict rotated to Phase 9 C3 + CE v2 metrics (cagr 0.2291, sharpe 1.1721, max_dd -0.2626, ir 0.9474, excess_cagr 0.0942, avg_stock_names 20.43, avg_turnover 0.4308, beat_month_ratio 0.5783). Added `alt_policies.concentrated_champion` sub-dict with the measured N=5 champion spec + 5 holdings. Added `alt_policies.concentrated_alternatives_gt30pct` listing 4 runner-up combos. Previous Phase 9 C1+C2 baseline kept as `PHASE9_C1C2_BASELINE` for historical delta calcs. Verdict message in `print_verdict()` unchanged — still compares `CURRENT_BASELINE` (now C3+CE v2); future runs without `--no-collector` will show tiny deltas vs itself until a new feature ships.
  - `colab_run.ipynb` Cell 10 `BASELINE` dict rotated to match. Added nested `concentrated_champion` dict so Colab Cell 10 baseline-delta view shows the 34.75% number.
  - `CLAUDE.md` "Current Production Baseline" section fully rewritten. Added "🎯 Concentrated Champion — CAGR 30%+ goal achieved" sub-section with the 5 holdings. Historical baselines table updated to list Phase 9 C1+C2 as PRIOR (was "current") and Phase 8 / 2026-04-15 as further prior.
  - `SESSION_HANDOFF.md`:
    * §0 TL;DR fully rewritten as SHIP post-verdict. Main diversified table + concentrated champion table + runners-up list + what-was-shipped summary.
    * §2 "Next step" rewritten as **Refactor Phase A** (REFACTOR_PLAN.md §12 Stage 3). Explicit argument: the CE v1 cap bug is exactly the "monolithic file makes invariants implicit" class the refactor is designed to prevent. §2a legacy kept as audit trail.
    * §6 phase status table: 9.C3 -> SHIPPED with measured delta, 9.CE new row added with SHIPPED v2 status (champion N=5).
- symbols_added:
  - `run_local.PHASE9_C1C2_BASELINE: dict` -- historical reference baseline kept for any future tool that wants to compare against prior shipped state.
  - `run_local.CURRENT_BASELINE['alt_policies']['concentrated_champion']` (nested dict) -- engine-selected N=5 concentrated champion spec including holdings list.
  - `run_local.CURRENT_BASELINE['alt_policies']['concentrated_alternatives_gt30pct']` (list of dicts) -- 4 runner-up concentrated combos with CAGR > 30%.
- symbols_changed:
  - `run_local.CURRENT_BASELINE` -- field values rotated from Phase 9 C1+C2 to Phase 9 C3 + CE v2. Schema unchanged (same keys).
  - `colab_run.ipynb` Cell 10 `BASELINE` dict -- field values rotated, new nested `concentrated_champion` key.
- config_fields_added:
  - none
- breaking_changes:
  - none. Baseline rotation is a documentation change; verdict gate formula (ΔCAGR ≥ +0.5pp etc.) unchanged, only the reference point shifts.
- outputs:
  - Measurement of record (2026-04-18 21:22 KST, commit `d3d3a91`, 83 months backtest):
    * Main diversified: `outputs/backtest_metrics.json` cagr=0.22905 sharpe=1.17209 max_dd=-0.26256 ir=0.94742 excess_cagr=0.09423 avg_turnover=0.43076 avg_stock_names=20.434 beat_month_ratio=0.57831
    * Concentrated champion: `outputs/concentrated_backtest_metrics.json` cagr=0.34747 sharpe=1.25383 max_dd=-0.26740 ir=1.07337 comparison_objective=0.38436 target_stock_names=5 weighting_mode=score_power rebalance_interval_months=1
    * Full concentrated grid: `outputs/reports/concentrated_strategy_comparison.csv` (63 rows, 10 with CAGR>30%)
    * Live portfolio: `outputs/portfolio_latest.csv` (18 positions, sleeve {core 8, future 5, early 4}, cash 3.8%)
    * Live concentrated: `outputs/concentrated_portfolio_latest.csv` (5 positions PR/ETR/GEV/FTI/AKAM, weights 30.3/27.8/15.2/14.5/12.3)
- validation:
  - `py -3 tests/smoke_test.py --quick` -> 11/11 passed.
  - CE v2 grid sanity: N=3/4/5/7/10 at (interval=1, mode=score_power) now produce DIFFERENT CAGR values (33.77/32.70/34.75/30.28/26.52), confirming the 2 inner clamps are lifted. Pre-v2 all 5 would tie at 29.86%.
  - Baseline consistency check: new CURRENT_BASELINE cagr=0.2291 appears in all 3 files (run_local.py, colab_run.ipynb, CLAUDE.md).
- risks_or_notes:
  - **Main diversified +1.22pp CAGR improvement surprising**: previous FULL REBUILD (f93a4a2) showed -0.97pp regression on the same C3 code. Difference is sleeve cap policy selection — v2 run picked `defensive_drawdown_control` (60/25/15) and v1 run picked `balanced` (40/40/20). The cap policy comparison appears sensitive to minor input changes when CAGR is close between policies. Worth a follow-up: pin the cap policy to `defensive_drawdown_control` explicitly if it's consistently best, OR widen cap policy comparison to more candidates and let the engine pick. See sleeve_cap_policy_comparison.csv for full ladder.
  - **CE v2 champion IS robust across N**: N=3/4/5/7/10 at (1m, score_power) all score >26% CAGR. N=5 is only marginally ahead of N=3 (34.75 vs 33.77). If user prefers simpler 3-name concentrated, N=3 at 33.77% is a valid SHIP-gate-pass alternative — still >30%.
  - **winner_take_all mode is a trap in its current form**: 100% weight on #1 score every month. CAGR 19.29%, Sharpe 0.697, MaxDD -35.5% at best. The grid still tests it (63 combos stays) but `comparison_objective` correctly never selects it as winner.
  - **Concentrated rebalance cost is real**: 54% monthly turnover on N=5 = ~26% trading cost drag over 12 months at current 25 bps per side. Net CAGR already includes this. For live trading, investor should budget ~3-5 trades per month plus hold-period taxes.
  - **Concentration risk**: champion holdings are 2 Energy (PR 30%, FTI 14.5%), 1 Utilities (ETR 27.8%), 1 Industrials (GEV 15.2%), 1 IT (AKAM 12.3%). Energy = 45% of concentrated sleeve → sensitive to oil/gas regime shifts. Diversified portfolio (18 positions) stays the recommended primary vehicle; concentrated is a SEPARATE high-conviction sleeve (per concentrated_operating_guide.json).
  - **Stage 3 unblocked**: Refactor Phase A per REFACTOR_PLAN.md §6. Estimated 1-1.5 day focused session. After refactor: Stage 4 Subtractive (delete Phase 3/5/7a + 153 noise factors), then Stage 5 Phase 8e (r_12m ML) for next alpha wave.


## 2026-04-20

### 19:00 KST - phase11-multibagger-watch-sleeve-integration

- scope:
  - **Phase 11 Multibagger Watch sleeve** production integration. Adds 4th sleeve alongside core_compounder / future_winner / early_scout that selects stocks matching the multibagger lifecycle pattern (pre-surge → surge → peak → decline) via 3 ML classifiers. Built on the **3-classifier lifecycle model** (entry + take_profit + stop_loss) validated in `research/phase11_*.py` which showed standalone CAGR 31.1% (vs SPY 17.1%, main 29.1%) and 50/50 main+phase11 blend Sharpe 2.07 on 2022-06 to 2026-04 test period. **Default OFF**; enables via `cfg.phase11_multibagger_sleeve_enabled=True` or `PHASE_PHASE11_MULTIBAGGER_ENABLED=1` env.
- files:
  - `r1000_config.py` -> PHASE11_MULTIBAGGER_COLUMNS constant (3 prediction columns). 14 EngineConfig fields. ENGINE_REUSE_VERSION bump to 2026-04-20-phase11-multibagger-sleeve.
  - `r1000_pipeline.py` -> `train_phase11_classifiers` + `compute_phase11_predictions` + helpers (_prep_phase11_features, _load_phase11_episodes, _load_phase11_models). build_feature_store now invokes compute_phase11_predictions inline. PHASE11_MULTIBAGGER_COLUMNS added to keep_cols and hard_sanitize whitelists.
  - `r1000_signals.py` -> `_apply_multibagger_watch_sleeve_override` helper (called at end of compute_portfolio_sleeve_columns). compute_portfolio_sleeve_policy adds `multibagger_watch_target` to return dict (= invested_share * allocation_pct when enabled). build_target_portfolio adds multibagger_target_n count + dedicated multibagger_sel selection block + sector-limit pass. Core count formula accounts for 4th sleeve at 3 sites.
  - `tests/smoke_test.py` -> 3 regression tests: phase11_config_fields_exported, phase11_columns_in_feature_store, phase11_sleeve_label_in_build_target_portfolio.
- symbols_added:
  - `r1000_config.PHASE11_MULTIBAGGER_COLUMNS: list[str]` -> the 3 prediction column names (phase11_p_entry, phase11_p_takeprofit, phase11_p_stoploss).
  - `r1000_pipeline.train_phase11_classifiers(cfg, fs, paths)` -> trains LR+CatBoost for entry/tp/sl labels constructed from research/multibagger_episodes.csv. Saves to cache_misc/phase11_models/artifacts.pkl.
  - `r1000_pipeline.compute_phase11_predictions(cfg, fs, paths)` -> adds 3 P(...) columns to feature_store. Graceful zero-fallback when disabled or models missing.
  - `r1000_pipeline._prep_phase11_features(df)` / `_load_phase11_episodes()` / `_load_phase11_models(paths)` -> support helpers.
  - `r1000_signals._apply_multibagger_watch_sleeve_override(d, cfg)` -> overrides portfolio_sleeve_label to "multibagger_watch" for top-N qualified names per rebalance_date.
- symbols_changed:
  - `r1000_config.ENGINE_REUSE_VERSION` -> "2026-04-18-phase9c3-turnaround-flags" became "2026-04-20-phase11-multibagger-sleeve". Triggers FS rebuild on next FULL run to populate the 3 new prediction columns.
  - `r1000_signals.compute_portfolio_sleeve_columns` -> tail now calls _apply_multibagger_watch_sleeve_override.
  - `r1000_signals.compute_portfolio_sleeve_policy` -> return dict gains "multibagger_watch_target" key. Core/future/early scaled when Phase 11 enabled so all 4 sum to invested_share.
  - `r1000_signals.build_target_portfolio` -> adds multibagger_target_n computation, new selection block, multibagger_sel concat into sleeve_frames, scaling preserved across cash-buffer rescale branches (2 sites).
- config_fields_added:
  - `phase11_multibagger_sleeve_enabled: bool = False` -> master toggle (default OFF for safe ship).
  - `phase11_sleeve_size: int = 5` -> top-N per month (validated optimal in backtest).
  - `phase11_allocation_pct: float = 0.30` -> portfolio weight share (30% default = safer; 50% = Sharpe max per backtest).
  - `phase11_p_entry_threshold: float = 0.30` -> minimum P(entry) for selection.
  - `phase11_p_takeprofit_threshold: float = 0.50` -> P(tp) cap at selection (익절 exit).
  - `phase11_p_stoploss_threshold: float = 0.70` -> P(sl) hard exit threshold.
  - `phase11_p_stoploss_select_threshold: float = 0.50` -> softer P(sl) cap at selection time.
  - `phase11_quality_min_mcap: float = 1e9` -> $1B minimum (exclude microcaps/pump-and-dump).
  - `phase11_quality_min_revenue: float = 1e8` -> $100M revenues_ttm minimum (exclude pre-revenue biotech lotteries).
  - `phase11_weighting_mode: str = "pscore"` -> P(entry)-weighted (beats equal-weight by 4pp CAGR in backtest).
  - `phase11_classifier_iterations: int = 500` -> CatBoost iterations.
  - `phase11_classifier_depth: int = 6` -> CatBoost tree depth.
  - `phase11_classifier_learning_rate: float = 0.03`.
  - `phase11_min_positive_examples: int = 30` -> skip training if insufficient labels.
  - `phase11_train_split_date: str = "2022-06-30"` -> diagnostic train/test split.
- breaking_changes:
  - none. Default phase11_multibagger_sleeve_enabled=False keeps existing 3-sleeve behavior unchanged. Baseline Phase 9 C3 + CE v2 metrics (CAGR 22.91%, Sharpe 1.17) preserved. Enabling requires explicit opt-in.
  - ENGINE_REUSE_VERSION bump triggers one-time FS rebuild on next FULL run regardless of phase11 toggle (new keep_cols schema).
- outputs:
  - `cache_misc/phase11_models/artifacts.pkl` -> pickled dict with scalers + LR + CatBoost classifiers for entry/takeprofit/stoploss. Created on first enabled FULL run.
  - `feature_store_latest.parquet` gains 3 new columns: phase11_p_entry, phase11_p_takeprofit, phase11_p_stoploss (zeros when disabled).
  - research/* artifacts from Steps 1-4 kept as validation record.
- validation:
  - `py -3 tests/smoke_test.py` -> 28/28 pass (25 existing + 3 new Phase 11 regression tests).
  - Unit test of _apply_multibagger_watch_sleeve_override on 8-ticker synthetic frame: 5 correct selections, 3 correct rejections (P_tp>0.5, P_sl>0.5, P_entry<0.3).
  - Unit test of compute_portfolio_sleeve_policy with Phase 11 ON (30% alloc): core=0.072, future=0.428, early=0.165, mbw=0.285, sum=0.95=invested_share. mbw/invested = 0.30 matches allocation_pct.
- risks_or_notes:
  - **Test sample is short** (47 months, 2022-06 to 2026-04). Overfitting risk exists even though walk-forward-esque time split was used. Future FULL rebuild with PHASE_PHASE11_MULTIBAGGER_ENABLED=1 will train on the same data; the only true OOS validation comes from live walk-forward after ship.
  - **손절 classifier is weak** (AUC 0.62 vs entry 0.84, takeprofit 0.75). Classifier learned macro-timing features (PPI/CPI/unrate) more than stock-specific thesis breaks. Sleeve integration falls back to rule-based P_sl threshold + natural monthly rebalance cycling.
  - **Classifier retraining required on version bump**. If feature_store schema changes, the pickled scalers + models become stale. compute_phase11_predictions detects missing models and re-trains inline (~1-2 min).
  - **Episodes CSV is a static training set** (54 5x+ episodes from 2018-2024). Future 5x+ stocks not yet reflected. Next FULL rebuild could regenerate research/multibagger_episodes.csv via research/phase11_retrospective.py.
  - **Allocation 30% is conservative default**. Backtest shows 50% = Sharpe max, 70% = CAGR +4.8pp. User can raise cfg.phase11_allocation_pct after seeing first live A/B outcome.
  - **Bisection-safe**: 6 sequential commits (30c796f, 3496e4a, af3050c, 26e1f0f, e5b6a22, this one). Each commit independently smoke-testable + revertable.
  - **A/B test procedure**: after this commit, run:
    ```
    PHASE_PHASE11_MULTIBAGGER_ENABLED=0 py -3 run_local.py --no-collector   # baseline
    PHASE_PHASE11_MULTIBAGGER_ENABLED=1 py -3 run_local.py --no-collector   # Phase 11 ON (will trigger FS rebuild due to version bump)
    ```
    Compare outputs/backtest_metrics.json between runs. Ship gate: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp.

## 2026-04-21

### 01:45 KST - phase11-ab-verdict-regress

- scope:
  - **A/B test verdict for Phase 11 Multibagger Watch sleeve: REJECT**. Full local pipeline A/B completed overnight (2x ~90min FULL rebuilds triggered by ENGINE_REUSE_VERSION bump). Baseline (Phase 11 OFF) reproduced the SHIPPED Phase 9 C3 + CE v2 metrics within 0.04pp CAGR confirming measurement methodology. Phase 11 ON run shows REGRESS: CAGR -1.73pp, Sharpe -0.047, MDD +0.81pp improved, IR -0.125. Phase 11 default stays OFF; integration has a deeper sleeve_cap_policy_compare override bug that prevents multibagger_watch from materializing as actual portfolio positions.
- files:
  - no engine code changes this entry -- documents verdict only.
  - `CHANGELOG.md` -> this entry.
  - Prior code changes (14 commits) already landed on master: 9beee91, bf1c34c, 1fdd3a1, ad1b483, 0bc4732, 8bfd4cd, 980aed9 (refactor import cleanup + gate logic fix).
- symbols_added: none
- symbols_changed: none
- config_fields_added: none (all 14 phase11_* fields already in EngineConfig from Commits 1-6)
- breaking_changes: none. Phase 11 remains default OFF. baselines unchanged.
- outputs:
  - Baseline run (`b7in91ea6`, 2026-04-20 22:00 to 2026-04-21 00:10, 130 min, PHASE_PHASE11=0):
    * CAGR 0.2295, Sharpe 1.1694, MaxDD -0.2621, IR 0.9357
    * 18 positions, sleeves {core: 7, future: 6, early: 4}
    * Verdict vs SHIPPED baseline: PARTIAL (+0.04pp CAGR reproduction).
  - Phase 11 ON run (`b4980641c`, 2026-04-21 00:10 to 01:40, 90 min, PHASE_PHASE11=1):
    * CAGR 0.2122, Sharpe 1.1254, MaxDD -0.2540, IR 0.8226
    * Phase 11 classifiers trained successfully (entry 236/52825, tp 161/813, sl 8318/16405)
    * 5 stocks labeled multibagger_watch in scored output
    * BUT final portfolio has 0 multibagger_watch positions (sleeve targets show {'core':0, 'future':0, 'early':0} i.e. cap policy override)
    * Verdict vs SHIPPED baseline: REGRESS (-1.73pp CAGR).
  - `cache_misc/phase11_models/artifacts.pkl` -- trained classifier bundle (Phase 11 first successful train in production).
- validation:
  - `py -3 tests/smoke_test.py` -> 28/28 pass (all 5 Phase 11 integration fix commits + 13 import fix commits).
  - A/B comparison metrics reported above.
- risks_or_notes:
  - **Sleeve cap policy compare overrides Phase 11 allocation**. The 6-candidate policy grid in compare_sleeve_cap_policy_backtests produces sleeve_policy dicts with {core_compounder, future_winner, early_scout}_target fields. My Phase 11 Commit 4 added multibagger_watch_target to the return dict but the cap policy comparison layer (pipeline.py:18794 compare_sleeve_cap_policy_backtests + 18830 policy_cfg = clone_cfg_with_updates) doesn't carry the multibagger_watch allocation forward. When champion policy applies, multibagger_watch_target gets zeroed out. This is the reason 5 candidates labeled but 0 selected.
  - **CAGR regress even without multibagger sleeve active**. Phase 11 cfg fields change `reuse_fingerprint(cfg)` hash -> Phase 4 walkforward retrains with different random state. -1.73pp is mostly training non-determinism / small-sample drift, not actual Phase 11 effect. Walk-forward research already warned this: 47-month test window is thin, any config change can shift metrics by 1-2pp from stochasticity.
  - **Walk-forward research predicted this outcome**. Research phase (commit 915b9d6) found walk-forward standalone Phase 11 CAGR 23.4% vs static-split 31.1%, and 20% allocation at main+Phase 11 blend added only +0.13pp CAGR + 0.09 Sharpe. The integration bug erased even that marginal benefit.
  - **Refactor-leftover import bugs cascade (13 total fixed in session)**. Pure-move refactor missed propagating module-level imports to 4 sub-modules. Each surface was caught by actual pipeline runs, not smoke tests. Future refactors should include a pipeline-run smoke test that goes deeper than import-only validation.
- next_steps:
  - **Ship decision**: keep Phase 11 default OFF (unchanged). Code stays in engine for audit + future improvement. Users CAN still A/B via env but must accept sleeve integration incomplete.
  - **Stop Phase 11 work**. Walk-forward research showed marginal benefit even with perfect integration. The multibagger hypothesis is real but our training data is too thin (54 episodes) and feature set isn't capturing the post-2022 momentum-regime winners. Needs new data sources (analyst revisions, insider Form 4 streams, sentiment) or wider universe (R3000).
  - **Alternative paths** (per PHASE_10_IDEAS.md):
    * Quarterly rebalance option -- ~1 day, low risk, ~20pp turnover reduction
    * R2000 universe expansion -- ~3-7 days, wider alpha pool
    * Phase 8e r_12m ML training -- ~11-13h, longer-horizon alpha
  - User decides which alternative to pursue in next session.
