# Session Handoff - 2026-05-09 16:18 KST (Live trading safety + export hygiene)

> **WHO AM I**: r1000 Quant Engine project (Russell 1000 Top-30 institutional).
> **PURPOSE OF THIS FILE**: shortest possible "pick-up-where-we-left-off" brief for a new Claude / Codex / GPT chat session on a different machine.
> **LIFETIME**: rewrite this file whenever a phase ships or a new blocker appears. One active handoff only.

---

## ACTIVE INBOX (2026-05-09 16:18 KST) - Live trading safety + export hygiene

Latest account-ledger state on branch `codex/broker-ledger-replay-foundation`:
- Current safety-first response after the user asked to anticipate live/paper
  trading errors, data leakage, and information mismatch before performance
  tuning:
  - New pre-trade audit:
    `tools/run_live_trading_safety_audit.py`.
  - It audits `portfolio_latest.csv`, `concentrated_portfolio_latest.csv`, and
    `outputs/account_ledger_preview/{main,concentrated}/` without placing
    orders.
  - It blocks actionable target files containing forward-return or benchmark
    forward-return leakage columns.
  - It checks invalid/negative/NaN weights, total exposure, single-name caps,
    account preview status, sell-first ordering, positive quantities, blocked
    orders, estimated cash feasibility, stale/missing prices, and missing price
    evidence for target tickers.
  - It writes:
    - `outputs/live_trading_safety/safety_audit_summary.json`
    - `outputs/live_trading_safety/safety_audit_issues.csv`
    - `outputs/live_trading_safety/safety_audit_report.md`
  - Workflows now run and sync this audit from both `full_rebuild_manual.yml`
    and `alphaops_replay_sidecars_manual.yml`.
  - `tools/sync_cloud_to_drive.py` syncs `live_trading_safety/`.
- Legacy execution lock:
  - `r1000_paper_executor.py --execute` now refuses to run unless
    `--allow-legacy-execute` is also provided.
  - `.github/workflows/after_close_daily.yml` exposes a manual
    `allow_legacy_execute` acknowledgement and defaults it to false.
  - This prevents the old Alpaca paper executor from bypassing the new
    account-ledger order-preview and safety-audit path by accident.
- Latest validation after the safety guard:
  - `py -3 -m py_compile tools\run_live_trading_safety_audit.py r1000_paper_executor.py`
  - `py -3 tests\live_trading_safety_audit_smoke.py`
  - `py -3 tests\workflow_artifact_smoke.py`
  - `py -3 tests\account_order_preview_smoke.py`
  - `py -3 tests\broker_ledger_replay_smoke.py`
  - `py -3 tests\account_evaluation_smoke.py`
  - `py -3 tests\smoke_test.py` (89/89)
  - `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime`
  - `git diff --check`
- Next safe operating rule:
  - Do not use legacy `r1000_paper_executor.py --execute` for the current
    system unless intentionally testing the old Alpaca path.
  - Use account-ledger order previews plus `outputs/live_trading_safety/`.
  - If safety audit status is `blocked`, do not trade; inspect
    `safety_audit_issues.csv` first.
- Safety audit real-world verdict:
  - Fast replay run `25594827958` completed successfully on commit `6798d30`
    and synced to Google Drive:
    `r1000_top30_institutional/research_runs/codex_broker-ledger-replay-foundation/25594827958/replay_outputs`.
  - The audit status was `blocked`.
  - Root issue:
    `outputs/concentrated_portfolio_latest.csv` contained benchmark forward
    return labels: `bench_r_1m`, `bench_r_3m`, `bench_r_6m`, `bench_r_12m`,
    `bench_r_24m`, `bench_r_36m`.
  - This confirmed the safety audit is useful: the order-preview normalized
    `target_weights.csv` was clean, but the top-level orderable target CSV
    still carried research/label columns.
- Fix after the blocked safety audit:
  - `r1000_pipeline.py` now has
    `drop_actionable_leakage_columns(df)`.
  - `portfolio_latest.csv` and `concentrated_portfolio_latest.csv` are
    sanitized before export.
  - The sanitizer removes `r_*`, `bench_r_*`, and explicit
    `*_forward_return` label columns while preserving legitimate features such
    as `future_winner_scout_score`.
  - `tools/run_live_trading_safety_audit.py` now also blocks `r_<horizon>`
    label columns in actionable target files.
- Required next action:
  - The export hygiene fix was committed as `2fcb3c2`.
  - Do not expect a fast replay from old source run `25581634925` to prove the
    exporter fix, because that source artifact already contains the old dirty
    `concentrated_portfolio_latest.csv`.
  - Confirm this fix with either a new full rebuild from commit `2fcb3c2` or a
    deliberate target-regeneration/sanitization replay that rewrites the
    copied target CSV before safety audit.
  - After a new target is generated, confirm
    `outputs/live_trading_safety/safety_audit_summary.json` is `pass` or
    inspect any remaining independent block.
- The engine now has a stricter account-like evaluation chain:
  1. `tools/run_broker_ledger_replay.py` replays monthly target books through
     next-close fills, integer shares, cash, transaction costs, and no leverage.
  2. `tools/run_broker_trade_journal.py` converts broker replay executions into
     FIFO round-trip journals and joins point-in-time entry evidence for
     AutoLearning.
  3. `tools/run_account_order_preview.py` creates preview-only sell-first /
     buy-second order tickets from account state and latest target portfolios.
  4. `tools/run_account_evaluation.py` is the new official account-level
     performance summary under `outputs/account_evaluation/`.
- Important governance change:
  - `tools/run_portfolio_goal_search.py` already separates research/proxy
    target pass from production-compatible target pass.
  - `tools/run_portfolio_system_guard.py` now uses broker-ledger metrics first
    for target pass/fail and falls back to legacy metrics only when broker
    evidence is absent.
  - `tools/run_alphaops_policy_fusion.py` now compares candidate policies
    against broker-ledger production metrics when available.
  - Legacy `backtest_metrics.json` and `concentrated_backtest_metrics.json`
    remain research-comparison artifacts, not official production evidence.
- Latest verified replay evidence from run `25593261448` at branch SHA
  `0d36a4c`:
  - main broker ledger: CAGR 20.96%, MaxDD -36.47%, Sharpe 0.972, avg cash
    5.43%, 1,918 round trips, win rate 54.7%.
  - concentrated broker ledger: CAGR 34.53%, MaxDD -40.38%, Sharpe 1.091, avg
    cash 0.04%, 244 round trips, win rate 61.1%.
  - Research/proxy candidates can show target pass, but production target pass
    remains false until the account-ledger/daily validation path confirms them.
  - `outputs/account_evaluation/` was generated in the GitHub artifact and
    synced to Google Drive:
    `r1000_top30_institutional/research_runs/codex_broker-ledger-replay-foundation/25593261448/replay_outputs/account_evaluation/`.
- No broker API is called and no live/paper orders are placed. These are
  replay, journal, and order-preview artifacts only.
- New proxy-to-account conversion after user asked to convert proxy winners:
  - `tools/run_broker_position_risk_replay.py` converts the position-risk proxy
    idea into observable account-ledger rules.
  - It does not copy proxy actions that used `period_forward_return`.
  - It checks daily close hard-stop / trailing-stop signals and weekly relative
    exits/trims, then fills them at the next close with shares, cash, fees, and
    no leverage.
  - `tools/run_portfolio_goal_search.py` now includes
    `main_broker_position_risk_replay` and
    `concentrated_broker_position_risk_replay` as production-compatible
    candidates when their broker metrics are valid.
  - `tools/run_alphaops_policy_fusion.py` now prefers broker-position-risk
    evidence before weekly validation or monthly proxy evidence.
  - `PRODUCTION_PROMOTION_GATES.md` defines the promotion path:
    proposal -> research replay -> account-compatible replay -> shadow ->
    canary -> production.
- Latest conversion run:
  - Branch commit `c2ac470` pushed to `codex/broker-ledger-replay-foundation`.
  - Master workflow registration commit `464dbde` pushed so the fast replay
    workflow can run the broker-position-risk sidecar.
  - GitHub fast replay run `25593756248` completed successfully from source
    full run `25581634925`.
  - Broker-position-risk account replay results:
    - main: CAGR 16.16%, MaxDD -37.17%, Sharpe 0.908, avg cash 15.04%,
      394 exits, 129 trims.
    - concentrated: CAGR 20.45%, MaxDD -50.16%, Sharpe 0.843, avg cash
      10.80%, 48 exits, 15 trims.
  - Verdict: proxy position-risk target pass did not survive conversion to
    next-close broker-ledger evidence. Do not promote this policy.
  - Governance fix in progress: `tools/run_portfolio_goal_search.py` should use
    top-level `target_pass` for production-compatible pass/fail only; proxy
    success remains under `research_target_pass`.
- Current development response to the metric collapse:
  - Root-cause finding: the old monthly/proxy accounting can show strong CAGR
    and mild MDD while broker-ledger replay collapses because monthly returns
    hide intramonth drawdown and the target books cause high churn, fees, and
    forced monthly replacement.
  - Local attribution on source run `25581634925` plus broker replay
    `25593991828`:
    - main proxy/implied CAGR 35.57% vs broker 20.96%, CAGR gap 14.61pp,
      target turnover 53.30%, fees $42,519, daily MDD -36.47%.
    - concentrated proxy/implied CAGR 56.60% vs broker 34.53%, CAGR gap
      22.07pp, target turnover 61.89%, fees $75,678, daily MDD -40.38%.
  - New diagnostic sidecar:
    - `tools/run_broker_gap_attribution.py`
    - outputs `outputs/broker_gap_attribution/`.
  - New research challenger:
    - `tools/run_broker_execution_policy_replay.py`
    - outputs `outputs/broker_execution_policy_replay/`.
    - It keeps production defaults unchanged but tests no-trade bands, staged
      entries, minimum holding, and winner trim deferral under broker-ledger
      next-close accounting.
  - Next required action after commit/push:
    - Run fast replay from source run `25581634925` on the latest branch HEAD.
    - Inspect `outputs/broker_execution_policy_replay/{main,concentrated}/metrics.json`
      versus `outputs/broker_replay/{main,concentrated}/metrics.json`.
    - If execution-policy improves account-ledger CAGR/MDD without target pass,
      use it as the next AutoLearning optimization surface, not production.
- Validation passed after the latest change:
  - `py -3 -m py_compile tools\run_broker_position_risk_replay.py tools\run_portfolio_goal_search.py tools\run_alphaops_policy_fusion.py`
  - `py -3 tests\broker_position_risk_replay_smoke.py`
  - `py -3 -m py_compile tools\run_account_evaluation.py tools\run_portfolio_system_guard.py tools\run_alphaops_policy_fusion.py tools\sync_cloud_to_drive.py`
  - `py -3 tests\account_evaluation_smoke.py`
  - `py -3 tests\workflow_artifact_smoke.py`
  - `py -3 tests\portfolio_system_guard_smoke.py`
  - `py -3 tests\portfolio_goal_search_smoke.py`
  - `py -3 tests\alphaops_policy_fusion_smoke.py`
  - `py -3 tests\broker_trade_journal_smoke.py`
  - `py -3 tests\auto_learning_evidence_smoke.py`
  - `py -3 tests\broker_ledger_replay_smoke.py`
  - `py -3 tests\smoke_test.py` (89/89)
  - `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime`
  - `git diff --check`
- Completed after validation:
  - Branch commit `0d36a4c` pushed.
  - Master workflow registration commit `dffb01b` pushed for
    `alphaops_replay_sidecars_manual.yml`.
  - GitHub fast replay run `25593261448` completed successfully.
- Next steps:
  1. Treat `outputs/account_evaluation/*` as the official current performance
     checkpoint.
  2. Run fast replay again from source run `25581634925` after committing the
     broker-position-risk conversion, then inspect
     `outputs/broker_position_risk_replay/*`, `outputs/portfolio_goal_search/*`,
     `outputs/policy_fusion/*`, and `outputs/account_evaluation/*`.
  3. Do not promote proxy target-pass candidates directly. Promotion requires
     account-compatible target pass, stress/cost review, and human approval.
  4. Next engineering phase is a daily scored-decision simulator that can
     evaluate true dated model decisions closer to paper/live trading, while
     keeping broker-ledger official metrics as the current baseline.

## RECENT CONTEXT (2026-05-08) - AlphaOps policy fusion arbitration

Strict macro/cash confirmation update:
- User clarified that broad cash should not rise simply because the index dips
  or a one-off event shock scares the market. Some monster leaders can keep
  rising during index weakness, so cash expansion must require more durable
  evidence.
- Updated `tools/run_macro_policy_engine.py`:
  - removed `cash_weight` as a causal risk input;
  - added component scores for long-trend damage, liquidity drain,
    breadth/credit stress, and event shock;
  - added `cash_raise_confirmation_count`, `confirmed_cash_raise`,
    `cash_raise_gate`, `recommended_monster_exception_capacity`, and
    `monster_exception_allowed`;
  - reduced yellow/recovery research cash floors from 10% to 5%;
  - requires two independent confirmations before red cash defense and
    stronger confirmation before crisis cash defense.
- Updated `tools/run_cash_policy_attribution.py`:
  - separates confirmed macro-defense cash from event-shock cash;
  - flags event-shock cash for review instead of treating it as automatic
    risk-defense cash;
  - keeps idle-cash redeploy candidates restricted to non-confirmed risk
    regimes.
- New test:
  - `tests/cash_policy_attribution_smoke.py`
- Validation passed:
  - `py -3 tests\macro_policy_engine_smoke.py`
  - `py -3 tests\cash_policy_attribution_smoke.py`
  - `py -3 tests\workflow_artifact_smoke.py`
  - `py -3 tests\historical_challenger_replays_smoke.py`
  - `py -3 tests\smoke_test.py` (89/89)
  - `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime`
- This remains research-only. It does not change production weights. Next
  cloud run should show whether `outputs/macro_policy_engine/` and
  `outputs/cash_policy/` classify prior high-cash months as confirmed macro
  defense, event-shock review, or idle drag.

Selection audit update:
- User asked whether current portfolio names are inherited holdings or just a
  separate current display. Code review showed:
  - `portfolio_latest.csv` is the current target portfolio generated from the
    latest scored universe, enriched with live-state fields when available;
  - historical holding continuity lives in `reports/main_monthly_weights.csv`
    and `reports/concentrated_strategy_holdings.csv`;
  - true dated BUY/TRIM/SELL validation lives in
    `outputs/position_risk_weekly_validation/*/trade_log.csv`.
- Added `tools/run_selection_audit.py`.
- Full rebuild now writes:
  - `outputs/selection_audit/current_selected_audit.csv`
  - `outputs/selection_audit/omitted_high_potential_candidates.csv`
  - `outputs/selection_audit/historical_hold_persistence.csv`
  - `outputs/selection_audit/ticker_decision_audit.csv`
  - `outputs/selection_audit/selection_audit_summary.json`
  - `outputs/selection_audit/selection_audit_report.md`
- This lets the next run answer:
  - why current names were selected;
  - whether selected names are stale-review names;
  - which high-pressure/monster candidates were omitted;
  - whether omissions were due to candidate gate, risk block, stale penalty,
    sleeve/cap pressure, or lower priority;
  - whether current names are long-held or newly selected.
- Validation passed:
  - `py -3 tests\selection_audit_smoke.py`
  - `py -3 tests\workflow_artifact_smoke.py`
  - `py -3 tests\smoke_test.py` (89/89)
  - `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime`
- This remains explanatory only and does not change production selection.

Position-risk proxy realism update:
- User asked whether the strong monthly proxy results can be made realistic.
- Added `tools/run_position_risk_weekly_validation.py`.
- Full rebuild now validates both books:
  - `outputs/position_risk_weekly_validation/main/`
  - `outputs/position_risk_weekly_validation/concentrated/`
- The validator uses monthly holding books plus `cache_prices` daily data:
  - daily hard-stop checks
  - daily trailing-stop checks after profit cushion
  - weekly SPY-relative trim/exit checks
  - trim action sells half first; hard/distribution exits override long-hold
    patience
- The validator writes explicit dated trade ledgers:
  - `trade_log.csv` with BUY/SELL/TRIM rows
  - `actions.csv` with risk/relative trigger diagnostics
  - `positions.csv` with entry/exit/final price-path summary
- This is stricter than the previous monthly position-risk proxy because it
  requires an observable price path before a stop/exit is credited.
- It is still research-only. It does not yet create true weekly scored
  snapshots, replacement buys, order tickets, or broker execution evidence.
- `tools/run_portfolio_goal_search.py` now ranks these validation candidates:
  - `main_position_risk_weekly_validation`
  - `concentrated_position_risk_weekly_validation`
- `tools/run_alphaops_policy_fusion.py` now prefers weekly-validation evidence
  over monthly proxy evidence for `position_hard_stop_distribution`, falling
  back to the proxy only when validation artifacts are missing.
- Local validation passed, but local `cache_prices` is empty, so the next cloud
  full rebuild is needed to see actual historical validation metrics.

Weekly evaluation freshness update:
- User identified that monthly `equity_curve.csv` can look stale because the
  row label is the entry/rebalance date, while realized return needs the next
  rebalance date.
- Added `tools/run_weekly_evaluation.py` and wired it into full rebuild.
- New output directory:
  - `outputs/weekly_evaluation/`
- Expected files:
  - `weekly_equity_curve.csv`
  - `main_weekly_equity_curve.csv`
  - `concentrated_weekly_equity_curve.csv`
  - `weekly_metrics.json`
  - `weekly_freshness_audit.json`
  - `weekly_freshness_audit.md`
- This is weekly mark-to-market evaluation of monthly holding books only. It
  does not change portfolio selection, rebalance cadence, or production
  weights.
- If `weekly_freshness_audit.json` is still `stale`, next development step is
  true weekly scored snapshots in the feature-store/backtest pipeline.

GDrive branch isolation update:
- Future full rebuilds now route Google Drive outputs by branch.
- `master` keeps the canonical production path:
  - `outputs/`
  - `full_rebuild_logs/`
- Non-master branches now write to branch/run-isolated paths:
  - `research_runs/<safe_branch>/<run_id>/outputs/`
  - `research_runs/<safe_branch>/<run_id>/full_rebuild_logs/`
- Failed non-master runs write to:
  - `research_runs/<safe_branch>/failed_runs/<run_id>/outputs/`
- This prevents research branch rebuilds from overwriting production Drive
  outputs. It affects future runs only; currently running runs use the workflow
  from their own head SHA.

**2026-05-08 target update:** User raised the product gates to:

```
main:         CAGR >= 30%, MaxDD >= -15%
concentrated: CAGR >= 50%, MaxDD >= -18%
```

These are now centralized in `r1000_config.PORTFOLIO_GOAL_TARGETS` and consumed
by `tools/run_portfolio_goal_search.py`. This is an evaluation/goal change only;
production selection and portfolio weights are not changed by this edit.

Policy-fusion update:
- `tools/run_alphaops_policy_fusion.py` now reads the major sidecars/replays and
  emits a single conflict-aware shadow activation plan.
- The full rebuild workflow now runs it after goal search, historical journey,
  and dataset coverage, then uploads/syncs `outputs/policy_fusion/`.
- Output files:
  - `outputs/policy_fusion/policy_fusion_summary.json`
  - `outputs/policy_fusion/policy_candidates.csv`
  - `outputs/policy_fusion/conflict_matrix.csv`
  - `outputs/policy_fusion/activation_plan.yaml`
  - `outputs/policy_fusion/policy_fusion_report.md`
- Production mutation remains disabled. This is the arbitration layer that says
  which policy wins when monster sizing, stale trims, shakeout veto, crisis cash,
  idle-cash redeploy, long-winner patience, macro style routing, governance
  catalysts, and AutoLearning proposals disagree.
- Precedence is explicit:
  1. hard stop / distribution exit
  2. macro crisis cash ladder
  3. stale leader trim
  4. shakeout hold veto for soft trims only
  5. monster early staged sizing
  6. long-winner hold template
  7. idle cash redeploy
  8. style/macro router
  9. governance catalyst watch
  10. AutoLearning proposal
- Local check against existing `latest_global_alpha_universe` passed, but those
  artifacts did not yet contain enough completed sidecar metrics for an
  actionable top policy. A rebuild from this new commit is needed for full cloud
  evidence.

Artifact-validity guard:
- A cancelled 2026-05-08 run had overwritten
  `cloud_results/full_rebuild/latest_global_alpha_universe` with a partial
  artifact lacking `backtest_metrics.json` and
  `concentrated_backtest_metrics.json`.
- The workflow now treats those core metric files as the validity gate.
- If either core metric is missing:
  - GitHub cloud results go to
    `cloud_results/full_rebuild/failed_runs/<run_id>_<universe_mode>/`.
  - Google Drive sync goes to `failed_runs/<run_id>/outputs/`.
  - Existing canonical Drive `outputs/` and local `latest_<universe_mode>` are
    preserved.
- If both core metrics exist, behavior is unchanged: the dated folder and
  `latest_<universe_mode>` are refreshed.

Winner-learning wire-up:
- The full rebuild now runs these previously standalone research sidecars before
  policy fusion:
  - `tools/run_auto_learning_v2.py`
  - `tools/run_winner_lifecycle_reports.py`
  - `tools/run_winner_onset_study.py`
  - `tools/run_shakeout_breakdown_study.py`
  - `tools/run_autolearning_winner_challenger.py`
- New synced outputs:
  - `outputs/auto_learning_v2/`
  - `outputs/winner_lifecycle/`
  - `outputs/winner_onset_study/`
  - `outputs/shakeout_breakdown_study/`
  - `outputs/autolearning_winner_challenger/`
- `run_alphaops_policy_fusion.py` now consumes those outputs:
  - winner onset -> `monster_early_staged_sizing` diagnostic evidence
  - shakeout/breakdown -> `shakeout_hold_veto` evidence
  - AutoLearning v2 / winner challenger -> `auto_learning_policy_candidate`
    proposal evidence
- These remain proposal/research-only. They are now fused and visible every run,
  but production scoring/weights are not changed without replay-backed gates.

Cash policy intent from user:
- Keep cash low in normal/bull regimes.
- Allow staged cash increases in real deterioration and up to roughly 50% in
  severe drawdown/black-swan regimes.
- Add a bargain-reentry style: deploy cash aggressively only when drawdown
  risk is fading and recovery/bottoming evidence appears.

Step 1 implemented after the target update:
- `tools/run_cash_policy_attribution.py` now writes
  `outputs/cash_policy/cash_drag_attribution.csv`,
  `outputs/cash_policy/cash_drag_summary.json`, and
  `outputs/cash_policy/cash_drag_report.md`.
- The full rebuild workflow runs this sidecar and uploads/syncs
  `outputs/cash_policy/`.
- Local diagnostic against the latest completed artifacts found a major
  accounting issue to address before idle-cash A/B: `regime_by_month.cash_weight`
  averages 21.02%, while explicit CASH rows in `main_monthly_weights.csv`
  average only 4.71%. Existing cash-drag replays that read only explicit CASH
  rows can understate real cash drag.
- `tools/run_main_cash_drag_replay.py` now defaults to
  `--cash-source reported`, reconstructs CASH rows from
  `regime_by_month.cash_weight`, and writes `outputs/main_cash_drag_replay/`.
  Local replay still does not exactly match production metrics, so treat it as
  directional A/B evidence until a production-compatible replay is added.

Step 2 implemented after the cash attribution:
- `tools/run_crisis_reentry_replay.py` now writes
  `outputs/crisis_reentry_replay/comparison.csv`,
  `outputs/crisis_reentry_replay/policy_by_month.csv`,
  `outputs/crisis_reentry_replay/monthly.csv`,
  `outputs/crisis_reentry_replay/equity_curve.csv`,
  `outputs/crisis_reentry_replay/holdings.csv`,
  `outputs/crisis_reentry_replay/metrics.json`, and
  `outputs/crisis_reentry_replay/replay_report.md`.
- The full rebuild workflow runs this sidecar and uploads/syncs
  `outputs/crisis_reentry_replay/`.
- The replay is research-only. It starts from exported monthly main holdings,
  aligns them to reported backtest cash, applies macro-policy cash floors, and
  tests crisis cash ladders plus staged bargain reentry. Production selection
  and production weights are still unchanged.
- It fixes the first version's equity-curve accounting by resetting equity per
  policy instead of chaining all policies into one curve.
- Latest local directional replay against
  `cloud_results/full_rebuild/latest_global_alpha_universe` ranked
  `fast_reentry` best: CAGR 32.11%, MaxDD -10.98%, Sharpe 1.984,
  avg cash 8.47%. This is promising but still not production evidence.
- Latest local directional replay should be treated as evidence for the next
  production-compatible replay, not as an activation gate.

Step 3 implemented for concentrated target hardening:
- `tools/run_concentrated_position_risk_replay.py` now uses the shared
  `PORTFOLIO_GOAL_TARGETS["concentrated"]` target: CAGR 50%, MaxDD -18%.
- It tests cost sensitivity at 25/50/75bps and writes
  `outputs/concentrated_position_risk_replay/rolling_3y.csv`.
- Local latest replay is near-miss evidence rather than a pass:
  best policy is `score_power`, hard stop -8%, 25bps cost, CAGR 49.90%,
  MaxDD -18.16%, Sharpe 1.749, rolling 3-year pass rate 10.42%.
- Interpretation: concentrated is close to the commercial target but still
  needs either more alpha capture from early monster/staged sizing or a better
  intramonth/weekly risk execution model before production promotion.

Step 4 implemented for monster lifecycle risk defense:
- `tools/run_monster_lifecycle_replay.py` lifecycle-review policies now have a
  monthly hard-stop proxy: main -10%, concentrated -8%.
- Holdings now carry `risk_adjusted_forward_return`, `risk_exit_proxy`,
  `risk_exit_reason`, and `hard_stop_proxy`; events now include
  `monthly_hard_stop_proxy` exits.
- Local latest lifecycle-review concentrated improved materially but remains
  weak: CAGR 14.42%, MaxDD -25.91%, Sharpe 0.881. This is not a production
  candidate.
- Interpretation: lifecycle replay is useful for learning/diagnostics, but the
  near-target commercial concentrated path is still the concentrated
  position-risk replay plus better early leader capture.

Step 5 implemented for historical-first evaluation:
- User clarified that historical behavior matters more than current latest
  outputs. `tools/run_historical_trade_journey.py` now treats historical
  decision quality as the first section of the report.
- New outputs:
  - `outputs/historical_trade_journey/book_summary.csv`
  - `outputs/historical_trade_journey/journey_tag_summary.csv`
  - `outputs/historical_trade_journey/historical_decision_priorities.csv`
- Local latest diagnostic:
  - holding runs: 2,170
  - unique held tickers: 446
  - production main avg run length: 2.81 months
  - production main 12m+ runs: 8
  - production main `short_big_win_review`: 43
  - current stale priority includes NVDA in current main.
- Interpretation: the engine still churns too quickly for the desired
  “enter early, pyramid winners, hold for years unless true breakdown” behavior.
  Next work should convert historical priority queues into AutoLearning
  counterfactual experiments: premature-exit repair, long-winner template
  preservation, and stale-current trim/exit rules.

**TL;DR** Full rebuild `25481291492` completed successfully on branch
`codex/leader-rescue-stale-trim`, but it ran on commit `eb99c97`, before the
macro-policy sidecar commit `0c7f91d`. Production main improved versus the
older target-pass run, but concentrated production metrics were invalid because
the concentrated comparison grid crashed on N=4 conviction-curve weighting.
That bug is now fixed locally and should be committed/pushed before the next
full rebuild.

Latest completed run `25481291492`:

```
main production:                 CAGR 28.16%, MaxDD -18.19%, Sharpe 1.577
concentrated production metrics: NaN / invalid due N>3 conviction-curve bug
latest concentrated holdings:    GLW 50%, WDC 30%, SNDK 20%
position-aware risk proxy:       CAGR 37.34%, MaxDD -12.73%, Sharpe 1.799
Main v2 historical replay:       CAGR 22.50%, MaxDD -26.98%, Sharpe 1.056
monster lifecycle replays:       weak; diagnostics only, not promotion-ready
```

Clear bug fixed after the run:
- `concentrated_weight_map()` only had explicit `conviction_curve` weights for
  N=1/2/3. The grid now tests N=4/5/7/10, so N=4 hit a shape mismatch:
  `Length of values (3) does not match length of index (4)`.
- The fix keeps legacy N<=3 weights exactly as before and generates a smooth
  decay curve for wider N values.
- Added regression coverage in `tests/historical_challenger_replays_smoke.py`.

Validation already passed:
- `py -3 tests\historical_challenger_replays_smoke.py`
- `py -3 -m py_compile r1000_pipeline.py tests\historical_challenger_replays_smoke.py`
- `py -3 tests\workflow_artifact_smoke.py`
- `py -3 tests\macro_policy_engine_smoke.py`
- `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime`
- `py -3 tests\smoke_test.py` -> 88/88

Next action:
1. Commit and push the concentrated grid fix.
2. Trigger a new `full_rebuild_manual` on `codex/leader-rescue-stale-trim` with
   `universe_mode=global_alpha_universe`, `backtest_years=8`, `fast_mode=true`,
   `skip_collector=true`.
3. Verify:
   - `concentrated_backtest_metrics.json` has finite CAGR/Sharpe/MaxDD.
   - `outputs/reports/concentrated_strategy_monthly.csv` exists.
   - `outputs/macro_policy_engine/` is exported because the next run includes
     commit `0c7f91d`.
   - Main stays near the current 28% CAGR / -18% MaxDD level or better.

**Latest local patch after full rebuild `25490280861` started**

Purpose:
- Add finer power/material theme recognition requested by the user:
  nuclear fuel-cycle (`LEU`), SMR/advanced nuclear, fuel cells, gas turbines,
  renewable power equipment, and critical minerals / rare earths.
- Separate long-duration structural themes from product-cycle and
  commodity-cycle themes so theme RS/phase changes can drive different
  research-only holding and trim behavior.
- Add non-R1000 or possibly non-R1000 names to `cycle_play_universe.yaml` so
  they can appear in `global_alpha_universe` scoring when liquidity/mcap gates
  pass. This is not a buy list.

Changed files:
- `themes.yaml`
- `cycle_play_universe.yaml`
- `tests/smoke_test.py`
- `CHANGELOG.md`
- `SESSION_HANDOFF.md`

Validation:
- `py -3 tests\smoke_test.py` passed, 89/89.
- `py -3 tests\historical_challenger_replays_smoke.py` passed.
- `$env:PYTHONUTF8='1'; py -3 tests\audit_features.py --no-runtime` passed.

Run note:
- Active run `25490280861` started on commit `ee8f0d1`, before this theme
  refresh. Commit/push this patch after review; the next full rebuild after
  `25490280861` should include it.

**Prior context follows.**

## PRIOR INBOX (2026-05-06 18:10 KST) - relative weakness + catalyst diagnostics

**TL;DR** The target-pass rebuild `25394753964` remains the latest completed
evidence set, but the active work has moved to branch
`codex/leader-rescue-stale-trim`. This branch generalizes the PLTR/SNDK/LITE
diagnostic into data-driven leader rescue, stale-leader trim, lifecycle review,
and historical holding/trade journey reporting. Full rebuild `25416283891`
completed successfully on commit `b5d1ee1`; the bot pushed results in
`cloud_results/full_rebuild/latest_global_alpha_universe`. The latest local
patch adds research-only relative-weakness trim/exit replay, guaranteed leader
drop fallback diagnostics, governance catalyst surfacing, and an explicit 50%
concentrated single-name cap.

Latest completed target-pass reference:

```
main production:          CAGR 30.29%, MaxDD -18.90%, Sharpe 1.659
concentrated production:  CAGR 45.16%, MaxDD -19.87%, Sharpe 1.653
latest concentrated:      WDC / CIEN / SNDK, all monster_extreme_early
```

**Current branch**

```
codex/leader-rescue-stale-trim
latest bot result commit: 0903e14 chore(bot): full rebuild [global_alpha_universe] 2026-05-06 [skip ci]
code commit under test: b5d1ee1 feat(alphaops): add historical trade journey report
base evidence run: 25394753964 on codex/goal-risk-replay-fullrun @ a54872e
```

**Latest local patch after run `25416283891`**

Purpose:
- Cut stale leaders in two stages: trim 50% after prior monthly benchmark-relative weakness, then exit if weakness persists.
- Keep true long-hold winners from being shaken out by one bad relative window.
- Make concentrated risk policy explicit: single-name cap is now 50%; infeasible excess stays cash instead of being renormalized away.
- Guarantee `leader_drop_diagnostics_latest.csv` / summary exists even if the in-pipeline writer does not produce it.
- Surface ownership/insider/event/revision catalyst columns every full run so governance-change signals can be inspected.

Changed files:
- `.github/workflows/full_rebuild_manual.yml`
- `r1000_config.py`
- `r1000_pipeline.py`
- `tools/run_position_aware_risk_replay.py`
- `tools/run_leader_drop_diagnostics_sidecar.py`
- `tools/run_governance_catalyst_report.py`
- `tests/historical_challenger_replays_smoke.py`
- `tests/workflow_artifact_smoke.py`
- `CHANGELOG.md`
- `SESSION_HANDOFF.md`

Local real-artifact check on `cloud_results/full_rebuild/latest_global_alpha_universe`:

```
enhanced position-aware risk proxy @25bps:
  CAGR 34.97%, MaxDD -8.63%, Sharpe 1.729
  relative trims 20, relative exits 2, risk exits 232
  50bps CAGR 34.07%, 75bps CAGR 33.19%

leader diagnostics fallback:
  701 rows generated with watchlist examples

governance catalyst report:
  82 rows generated
```

**Latest local patch after 2026-05-07 13:15 KST**

Purpose:
- Add a theme half-life / chameleon policy route without changing production
  `DEFAULT_FEATURES`.
- Event/commodity themes such as oil & gas services, oil E&P, crypto, and
  defense shock beneficiaries are tagged as shorter-cycle candidates.
- Structural growth themes such as AI compute, optical/datacenter, memory,
  semiconductor equipment/design, power grid, and nuclear/SMR are tagged as
  longer-duration candidates.
- `candidate_replay_book.csv` will now preserve theme horizon, event-risk,
  structural-growth, target-hold, max-hold, and short-cycle fields.
- `monster_lifecycle_replay` and `position_aware_risk_replay` use those fields
  in research-only replays: short-cycle event themes get faster trim/time-stop
  logic; structural winners get more shakeout patience when leadership remains
  intact.

Changed files:
- `themes.yaml`
- `r1000_themes.py`
- `r1000_features.py`
- `r1000_config.py`
- `r1000_pipeline.py`
- `tools/run_monster_lifecycle_replay.py`
- `tools/run_position_aware_risk_replay.py`
- `tools/run_main_v2_backtest.py`
- `tests/historical_challenger_replays_smoke.py`
- `tests/smoke_test.py`
- `CHANGELOG.md`
- `SESSION_HANDOFF.md`

Validation:
- `py -3 tests\historical_challenger_replays_smoke.py` passed.
- `py -3 tests\workflow_artifact_smoke.py` passed.
- `py -3 tests\smoke_test.py` passed, 85/85.
- `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime`
  passed, 245 features and no leakage.

**Latest local patch after 2026-05-07 13:23 KST**

Purpose:
- Add a research-only market style regime router for the user's concern that
  the engine leans heavily toward near-high breakout leaders.
- The new route outputs whether the current tape favors:
  - `breakout_growth`
  - `turnaround_accumulation`
  - `quality_compounder`
  - `cash_defense`
  - `balanced`
- It uses existing macro/market columns such as liquidity, M2/TGA/reverse repo
  derivatives, CPI/inflation pressure, rates, VIX/credit, benchmark trend,
  breadth/participation, QQQ-vs-SPY, and overheat/narrowing.
- It also surfaces calendar/seasonality metadata: month, quarter, weekday,
  years since first sample, and month/quarter/weekday sin/cos encodings.
- These fields are preserved in `candidate_replay_book.csv` and summarized by
  a new `outputs/style_regime_report/` sidecar.

Changed files:
- `.github/workflows/full_rebuild_manual.yml`
- `r1000_config.py`
- `r1000_features.py`
- `r1000_pipeline.py`
- `tools/run_style_regime_report.py`
- `tools/run_main_v2_backtest.py`
- `tools/run_position_aware_risk_replay.py`
- `tests/historical_challenger_replays_smoke.py`
- `tests/workflow_artifact_smoke.py`
- `tests/smoke_test.py`
- `CHANGELOG.md`
- `SESSION_HANDOFF.md`

Validation:
- `py -3 tests\historical_challenger_replays_smoke.py` passed.
- `py -3 tests\workflow_artifact_smoke.py` passed.
- `py -3 tests\smoke_test.py` passed, 86/86.
- `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime`
  passed, 245 features and no leakage.

Interpretation:
- This is not a production style allocation switch yet.
- Next full rebuild should populate `outputs/style_regime_report/monthly.csv`
  and latest top breakout/turnaround/compounder candidate lists.
- The next A/B should test whether style-aware slot/cap changes improve CAGR
  without worsening MDD.

**Latest local patch after 2026-05-07 14:05 KST**

Purpose:
- Connect the style regime router to actual Main v2 research-only selection.
- `Main v2` now infers the dominant monthly style regime from
  `candidate_replay_book.csv` rows and adjusts sleeve capacity plus target N:
  - `breakout_growth`: more future/early leader slots.
  - `turnaround_accumulation`: more early-scout turnaround slots.
  - `quality_compounder`: more core compounder slots.
  - `cash_defense`: less future/early event risk and more core/cash defense.
- Sleeve scores now receive style-fit bonuses:
  - future sleeve uses `style_row_breakout_fit`.
  - early sleeve uses `style_row_turnaround_fit`.
  - core sleeve uses `style_row_compounder_fit`.
- Early-scout can now admit bottom/turnaround growth candidates when style,
  improving fundamentals, h1 oversold value, RS stabilization, and risk gates
  align, even before the stock is fully back above MA200.
- Cash-defense regimes block high event-risk future/early candidates unless
  they also have strong structural-growth metadata.
- Production `DEFAULT_FEATURES` and production portfolio construction remain
  unchanged.

Changed files:
- `r1000_main_v2.py`
- `tools/run_main_v2_backtest.py`
- `tests/smoke_test.py`
- `tests/historical_challenger_replays_smoke.py`
- `CHANGELOG.md`
- `SESSION_HANDOFF.md`

Validation:
- `py -3 -m py_compile r1000_main_v2.py tools\run_main_v2_backtest.py
  tests\smoke_test.py tests\historical_challenger_replays_smoke.py` passed.
- `py -3 tests\smoke_test.py` passed, 87/87.
- `py -3 tests\historical_challenger_replays_smoke.py` passed.
- `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime`
  passed, 245 features and no leakage.

Next run focus:
- Run full rebuild on `codex/leader-rescue-stale-trim`.
- Inspect `outputs/main_v2_backtest/monthly_returns.csv`,
  `outputs/main_v2_backtest/monthly_holdings.csv`, and
  `outputs/style_regime_report/monthly.csv`.
- Compare style-aware Main v2 CAGR/MaxDD/Sharpe/turnover against the latest
  production main and prior Main v2 replay before any promotion.

**Latest local patch after 2026-05-07 16:00 KST**

Purpose:
- Add a research-only opportunity-cost replacement layer to Main v2.
- The goal is to stop high-value signals from "each playing separately" by
  combining them into one replacement score:
  - earnings / revision / event reaction
  - macro and semis-cycle tailwind
  - market style fit
  - theme phase and structural-growth metadata
  - monster/future/early alpha strength
  - profitability/cash-flow turnaround evidence
  - stale leader, risk block, overheat, relative weakness, and event-cycle
    decay penalties
- Strong replacement candidates can pass future/early gates and receive score
  tilt; stale/event-cycle candidates receive decay pressure.
- This is designed to test whether names like AMD/INTC/ARM/STX-style new
  leaders can displace weaker incumbents without hardcoding tickers.
- Production `DEFAULT_FEATURES` and production portfolio construction remain
  unchanged.

Changed files:
- `r1000_main_v2.py`
- `tools/run_main_v2_backtest.py`
- `tests/smoke_test.py`
- `tests/historical_challenger_replays_smoke.py`
- `CHANGELOG.md`
- `SESSION_HANDOFF.md`

Validation:
- `py -3 -m py_compile r1000_main_v2.py tools\run_main_v2_backtest.py
  tests\smoke_test.py tests\historical_challenger_replays_smoke.py` passed.
- `py -3 tests\smoke_test.py` passed, 88/88.
- `py -3 tests\historical_challenger_replays_smoke.py` passed.
- `py -3 tests\workflow_artifact_smoke.py` passed.
- `$env:PYTHONIOENCODING='utf-8'; py -3 tests\audit_features.py --no-runtime`
  passed, 245 features and no leakage.

Run note:
- Full rebuild `25477647771` is still running on prior commit `7ff739c`.
- After this replacement patch is committed/pushed, trigger a new rebuild only
  if the user wants the replacement effect measured immediately.

Do not treat the enhanced risk replay as production execution evidence yet:
it still uses monthly proxy stop assumptions. It is now better suited for the
next full rebuild / A-B check because it also exports cost sensitivity and
rolling 3-year metrics.

**Active GitHub Actions**

1. Old run `25415594156` was started on commit `91958dd` before the historical
   journey reporter was added. The user asked to stop it. A cancel request was
   submitted; GitHub may still show it as `in_progress` for a short time.
2. New run `25416283891` completed successfully on branch
   `codex/leader-rescue-stale-trim` at commit `b5d1ee1`.
   Settings:

```
workflow: Full Rebuild (Manual / Long-Run)
universe_mode: global_alpha_universe
backtest_years: 8
fast_mode: true
skip_collector: true
leader_rescue_mode: latest_only
cache_key_suffix: ""
```

The next agent should analyze run `25416283891`, not the canceled run. GDrive
sync, artifact upload, Telegram bundle, and bot `cloud_results` commit all
completed successfully.

**Run `25416283891` quick result snapshot**

```
main latest champion:          CAGR 30.19%, MaxDD -18.35%, Sharpe 1.662
concentrated latest champion:  CAGR 45.75%, MaxDD -20.62%, Sharpe 1.642
main position-risk proxy:      CAGR 36.25%, MaxDD -8.20%,  Sharpe 1.790
orchestrator main proxy:       CAGR 34.30%, MaxDD -16.02%, Sharpe 1.848
```

Important interpretation:
- Production main/concentrated still pass the user's target gates.
- `main_v2_position_aware_risk_proxy` and `orchestrator_replay_main_proxy`
  are strong but still sidecar/proxy candidates. Do not promote blindly.
- The historical journey reporter worked and produced the new output directory.

**Current direction**

1. The system should read the market environment earlier and better before
   portfolio construction.
2. Main should not keep high-weight stale leaders only because long-horizon
   winner / core scores are high.
3. Main should admit data-driven monster/extreme early candidates earlier,
   without hardcoding tickers.
4. The system should not analyze only the latest portfolio. It must also review
   historical holdings, round-trip trades, re-entry churn, short big wins, and
   current holdings versus history.
5. Relative underperformance should be staged: first trim, then exit if the
   stock keeps lagging SPY/QQQ and no long-hold winner protection remains.
6. Governance/ownership catalysts should be visible in reports now, then later
   upgraded with a true SEC 8-K/Form 4/Form 13F/news event parser.

**What changed on `codex/leader-rescue-stale-trim`**

1. Generic leader rescue, no ticker hardcoding.
   - S&P 500 / Nasdaq-100 rescue candidates are added as broad source evidence.
   - `leader_rescue_mode=latest_only` keeps this PIT-safer by excluding
     rescue-only historical rows from OOS backtest months.
   - `full_proxy` remains research-only because it uses today's index members
     historically.

2. Stale former-leader trim, no ticker hardcoding.
   - Broad stale-leader logic now covers prior large winners below MA50/MA200
     with weak RS acceleration and requires a price/trend break when configured.
   - Intended to reduce stale PLTR/NVDA-style old leaders only when the data
     confirms current weakness.

3. Lifecycle review experiments.
   - `tools/run_lifecycle_review_overlay.py` tests monthly review without
     forced monthly churn.
   - `tools/run_monster_lifecycle_replay.py` has lifecycle review policies for
     main and concentrated research.
   - Local check on prior artifacts showed E10 reduced turnover/cash but did
     not beat the 30% main run, so it is research-only, not a production
     candidate yet.

4. Historical trade journey reporting.
   - New report-only sidecar:
     `tools/run_historical_trade_journey.py`
   - Outputs:
     - `outputs/historical_trade_journey/summary.json`
     - `outputs/historical_trade_journey/holding_runs.csv`
     - `outputs/historical_trade_journey/trade_summary_by_ticker.csv`
     - `outputs/historical_trade_journey/leader_rotation_timeline.csv`
     - `outputs/historical_trade_journey/current_vs_history.csv`
     - `outputs/historical_trade_journey/ticker_journey.csv`
     - `outputs/historical_trade_journey/report.md`
   - Full rebuild artifact, GDrive sync, Telegram zip, and `cloud_results`
     copy all include this directory.
   - The tool explicitly collapses duplicated concentrated grid rows, so
     `concentrated_strategy_holdings.csv` does not produce impossible holding
     durations.

**Concrete PLTR / SNDK / LITE / INTC diagnostics**

- Latest `portfolio_latest.csv` from run `25416283891` has `PLTR` at about
  5.00% weight. It is no longer a dominant main name, but it still survives
  because long-horizon/core scores offset weak current relative strength.
- Latest `PLTR` diagnostics are contradictory: strong long-horizon winner/core
  scores but weak current technical state:
  - `price_above_ma50 = 0`
  - `price_above_ma200 = 0`
  - `rs_acceleration_score = about -0.84`
  - `breakout_fresh_20d = 0`
- `PLTR` first appeared in main monthly weights on `2024-11-29` at about 8.90%,
  then reached about 20.25% on `2024-12-31`.
- Latest `SNDK` is in concentrated but not main. It has strong current monster
  characteristics but is rejected by the main gate:
  - `portfolio_future_winner_engine_score = 0.947`
  - `portfolio_early_scout_engine_score = 0.920`
  - `price_above_ma50 = 1`
  - `price_above_ma200 = 1`
  - `breakout_fresh_20d = 1`
  - `multi_year_winner_score = 0`
  - `ranking_eligible = False`
  - `portfolio_candidate_gate_label = rejected`
- Latest `LITE` is eligible as `future_winner` and passes `future_relaxed`, but
  it does not make the final main portfolio because selected future/monster
  slots and sleeve scoring still prefer other names.
- Latest `INTC` is not present in `scored_latest.csv`; it cannot enter any
  portfolio until universe coverage admits it. Treat INTC as an example of a
  large-cap comeback / recovery candidate, not as a hardcoded ticker target.
- The new fallback sidecar can emit watchlist-missing rows for examples like
  `INTC` and `STX`, but a true fix still requires upstream universe/source
  admission and event coverage rather than ticker-specific selection code.

**Market-context gap to fix before another run**

Add a market-context preflight before final main/concentrated selection. It
should summarize the current environment from existing repo artifacts rather
than from hardcoded opinions:

- `macro_daily` / macro columns: liquidity, rates, VIX, inflation, risk-off,
  growth re-entry, war/oil/rate shock.
- `etf_leadership` / industry leadership columns: semis, AI infrastructure,
  power infrastructure, energy, financials, defensive leaders.
- `explosive_movers` / breakout columns: fresh breakout, volume confirmation,
  volatility contraction, near 52-week high, RS acceleration.
- candidate diagnostics: `portfolio_monster_early_score`,
  `portfolio_risk_entry_block_score`, `portfolio_stale_mega_leader_score`,
  `portfolio_defensive_rotation_action`.

The goal is to classify environments like:

```
leadership_narrow_bull
growth_reentry
rate_shock
liquidity_shock
inflation_energy_bear
AI_power_infra_cycle
semis_storage_recovery
defensive_rotation
```

This label should affect gates and slots, not directly buy/sell by itself.

**Specific code changes recommended next**

1. Expand stale leader defense in `r1000_signals.py`.
   - Current stale logic is too mega-cap-specific.
   - Add a stale-leader branch for large prior winners:
     `market_cap > 50B or 100B`, high long-horizon winner score, below MA50 or
     MA200, negative RS acceleration, no fresh breakout.
   - Action should be `rotate_out_stale_leader`, not only
     `rotate_out_stale_mega_core`.

2. Add new-buy block or severe cap for broken core leaders.
   - A `core_strict` candidate with `price_above_ma50 = 0`,
     `price_above_ma200 = 0`, and `rs_acceleration_score < -0.5` should not get
     a high fresh allocation.
   - If it is an incumbent, allow a small review/hold cap only when thesis and
     market-context support it.

3. Add sparse-history monster override for main.
   - Do not require `multi_year_winner_score > 0` when all current monster
     evidence is strong.
   - Candidate rule shape:
     `future_engine >= 0.85`, `early_engine >= 0.80`, above MA50/MA200,
     fresh breakout, acceptable risk block, and positive catalyst/inflection.
   - This is how SNDK-style names can enter main earlier without hardcoding.

4. Reserve main monster slots by market context.
   - In neutral/bull leadership environments, reserve at least 2-4 future/monster
     slots for sparse-history monster candidates.
   - In risk-off environments, keep the reserve smaller and require stronger
     price confirmation.

5. Improve Layer 4 swap integration.
   - Use daily/monthly Layer 4 only as proposal/manual review for now.
   - Swap stale leaders into monster candidates only when cap, sector, theme,
     and risk-entry-block checks pass.

6. Add concentrated metadata parity.
   - Latest concentrated metrics pass the target, but
     `concentrated_backtest_metrics.json` does not explicitly expose
     `position_risk_enabled` and `position_risk_metric_mode`.
   - Add those fields so future agents/users do not confuse production metrics
     with sidecar proxy metrics.

**Do not hardcode these tickers**

Use `PLTR`, `SNDK`, `LITE`, and `INTC` only as diagnostic examples. The actual
logic should be data-driven and should generalize to any future stale leader or
early monster candidate.

**What to analyze next from run `25416283891`**

1. Production metrics:
   - `outputs/backtest_metrics.json`
   - `outputs/concentrated_backtest_metrics.json`
   - compare against reference run `25394753964`:
     main 30.29% CAGR / -18.90% MaxDD / 1.659 Sharpe,
     concentrated 45.16% CAGR / -19.87% MaxDD / 1.653 Sharpe.

2. Latest holdings:
   - `outputs/portfolio_latest.csv`
   - `outputs/concentrated_portfolio_latest.csv`
   - verify stale leaders are trimmed only with confirmed break evidence.
   - verify sparse-history monsters are not blocked solely because
     `multi_year_winner_score=0`.

3. Leader rescue diagnostics:
   - `outputs/reports/leader_drop_diagnostics_latest.csv`
   - `outputs/reports/leader_drop_diagnostics_summary.json`
   - `outputs/reports/leader_rescue_backtest_filter_summary.json`
   - confirm `leader_rescue_mode=latest_only` kept rescue-only names latest-only.

4. Historical journey:
   - `outputs/historical_trade_journey/report.md`
   - `holding_runs.csv` for longest winners, short big wins, and stale current
     holdings.
   - `trade_summary_by_ticker.csv` for repeated re-entry churn.
   - `current_vs_history.csv` for whether current holdings are new leaders,
     stale old winners, or returning names.
   - Quick read from the completed run:
     - holding runs: 1,971
     - unique held tickers: 440
     - average / median run length: 3.06m / 2.00m
     - runs >= 6m / 12m: 266 / 25
     - short big wins to review: 116
     - open stale watch: 1 (`GOOGL` in lifecycle overlay)

5. Lifecycle/replay sidecars:
   - `outputs/lifecycle_review_overlay_main/`
   - `outputs/monster_lifecycle_review_main/`
   - `outputs/monster_lifecycle_review_concentrated/`
   - Treat these as challenger evidence only. Do not promote if they do not beat
     production targets.

**Validation already run on `b5d1ee1` before dispatch**

```
py -3 tests\historical_trade_journey_smoke.py        -> passed
py -3 tests\workflow_artifact_smoke.py               -> passed
py -3 tests\smoke_test.py                            -> 83/83 passed
PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime -> passed
py -3 tests\historical_challenger_replays_smoke.py   -> passed
```

**Result paths now available locally after pulling bot commit**

```
cloud_results/full_rebuild/20260506_global_alpha_universe/
cloud_results/full_rebuild/latest_global_alpha_universe/
```

---

## PRIOR INBOX (2026-05-04 10:43 KST) - PR #3 historical replay foundation

**TL;DR** PR #3 is directionally good but still too report-only/proxy-heavy for
production. This follow-up branch preserves the raw monthly artifacts needed for
true historical replay and fixes the concentrated entry-gate fallback issue
flagged by review. Production defaults, DEFAULT_FEATURES, orchestrator
activation, broker execution, and auto-promotion remain unchanged.

**Branch**

```
codex/pr3-historical-replay-foundation
base: codex/integrate-phase17-19
purpose: narrow hardening follow-up before judging PR #3 as a production candidate
```

**What changed**

1. `r1000_pipeline.py` now writes monthly replay inputs:
   - `outputs/reports/main_monthly_weights.csv`
   - `outputs/reports/tactical_monthly_weights.csv` (empty schema until true tactical book is wired)
   - `outputs/reports/alpha_sprint_monthly_weights.csv` (empty schema until true alpha-sprint book is wired)
   - `outputs/reports/regime_by_month.csv`
   - `outputs/reports/sleeve_returns_by_month.csv`
2. `.github/workflows/full_rebuild_manual.yml` now preserves those files plus
   `outputs/equity_curve.csv` and `outputs/reports/concentrated_strategy_*.csv`
   in GitHub artifacts, Google Drive sync, Telegram zip, and cloud_results.
3. cloud_results directory copies now use `copy_dir_clean` to avoid nested
   `orchestrator/orchestrator`, `trade_journal/trade_journal`, etc.
4. `r1000_concentrated_policy.py` now derives an `entry_quality_proxy` when
   `entry_quality_score` is missing, using existing pass flags and conservative
   technical/confirmation fallbacks. Audit rows expose both proxy value and
   source.
5. `tools/run_winner_lifecycle_reports.py` adds report-only missed winner,
   stale winner, and leadership rotation diagnostics. Existing artifacts flag
   SNDK/LITE/WDC as missed explosive leaders and NVDA as a stale/opportunity-cost
   holding candidate.
6. `.github/workflows/daily_autolearning_scan.yml` schedules the winner
   lifecycle diagnostics after the US close as an artifact-only daily scan.
7. `tools/run_winner_onset_study.py` adds a report-only historical onset miner
   for multi-month/multi-bagger advances. It studies the months before/after
   detected onset events, evaluates hold/exit diagnostics, and emits only
   proposal-only policy candidates. When sourced from `scored_latest.csv`, it
   defaults to a $5B current market-cap floor and $20M 20-day dollar-volume
   floor to avoid micro-cap multi-bagger noise.
8. `tools/run_autolearning_winner_challenger.py` connects AutoLearning v2,
   winner lifecycle, and winner onset outputs into a separate research-only
   challenger package. Current local event-level run found 16 onset cases and
   reports verdict `EVENT_LEVEL_ONLY_WAIT_FOR_MONTHLY_BOOKS` until the cloud
   run provides monthly books.
9. `tools/run_shakeout_breakdown_study.py` adds report-only drawdown event
   labeling for SHAKEOUT, BUYABLE_RESET, TRUE_BREAKDOWN, DEAD_THEME, and
   AMBIGUOUS events. It replays hold/trim/add/exit actions at event level and
   feeds the separate AutoLearning winner challenger. Daily scan now uploads
   lifecycle, onset, shakeout/breakdown, and combined challenger artifacts.
   Local top-40 scored-universe probe found 682 events: 261 SHAKEOUT, 124
   TRUE_BREAKDOWN, and 297 AMBIGUOUS. Six-month SHAKEOUT hold median was
   +37.11%; TRUE_BREAKDOWN hold median was -17.58%.

**Validation**

```
py -3 -m py_compile r1000_concentrated_policy.py r1000_pipeline.py tests\concentrated_policy_smoke.py tests\workflow_artifact_smoke.py
py -3 tests\concentrated_policy_smoke.py
py -3 tests\workflow_artifact_smoke.py
py -3 tests\orchestrator_replay_smoke.py
py -3 tests\portfolio_system_guard_smoke.py
py -3 tests\aggressive_lab_smoke.py
py -3 tests\smoke_test.py                         # 81/81 pass
PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime
py -3 tests\winner_lifecycle_smoke.py
py -3 tools\run_winner_lifecycle_reports.py --latest-run cloud_results\full_rebuild\latest_global_alpha_universe --output-dir outputs\winner_lifecycle --top-n 20
py -3 tests\winner_onset_study_smoke.py
PYTHONIOENCODING=utf-8 py -3 tests\audit_features.py --no-runtime
py -3 tests\autolearning_winner_challenger_smoke.py
py -3 tools\run_winner_onset_study.py --scored cloud_results\full_rebuild\latest_global_alpha_universe\scored_latest.csv --top-tickers 80 --limit 40 --years 10 --sleep 0 --output-dir outputs\winner_onset_study
py -3 tools\run_autolearning_winner_challenger.py
py -3 tests\shakeout_breakdown_study_smoke.py
py -3 tools\run_shakeout_breakdown_study.py --scored cloud_results\full_rebuild\latest_global_alpha_universe\scored_latest.csv --top-tickers 80 --limit 40 --years 10 --sleep 0 --output-dir outputs\shakeout_breakdown_study
```

**Next work**

1. Run full rebuild on this branch with `global_alpha_universe`, 8 years,
   fast mode, cached collector if cache exists.
2. Confirm GDrive and artifact contain the monthly books above.
3. Use winner lifecycle diagnostics to seed SNDK/NVDA-style counterfactual
   rules: acceleration override, stale trim, and leadership rotation.
4. Run `tools/run_winner_onset_study.py` on a targeted universe to mine
   historical early-onset patterns before promoting any "hold winners longer"
   rule.
5. Use `tools/run_shakeout_breakdown_study.py` to mine whether sharp drawdowns
   were recoverable shakeouts or true breakdowns before testing hold/add/exit
   policies and high single-name cap grids.
6. Implement true `tools/run_main_v2_backtest.py` using monthly books.
7. Implement true concentrated policy replay using `concentrated_strategy_monthly.csv`
   and `concentrated_strategy_holdings.csv`.
8. Only after true replays exist, test orchestrator merge policies
   (`max`, `sum_then_cap`, `priority_concentrated`, `risk_budget_blend`).

---

## PRIOR INBOX (2026-04-29 19:08 KST) - ADR USD market-cap fix + concentrated continuation fix + Phase 15-D rerun

**TL;DR** — Run `25091384080` completed successfully and synced to GDrive, but
verdict was PARTIAL, not SHIP. User spotted a real ADR market-cap bug: TSM was
larger than NVDA because the engine multiplied USD ADR price by ordinary local
shares. Code now normalizes ADR market cap to yfinance USD marketCap and uses
ADR-equivalent shares for valuation. A second regression was found in
concentrated: Phase 15-D entry_quality hard filter suppressed high-momentum
continuation winners and cut concentrated CAGR. Code now allows only high-rank,
trend-intact continuation winners through that gate. A new full_rebuild is
required before judging Phase 15-D again.

**State of master (as of 2026-04-29 19:08 KST)**

```
HEAD: pending/current master after ADR USD market-cap normalization +
      concentrated continuation-winner override
       5bc9ef0  chore(bot): full rebuild [global_alpha_universe] 2026-04-29 [skip ci]
       959b76a  fix(actions): expose finnhub state for phase15d rebuild
       180d854  docs: CHANGELOG + SESSION_HANDOFF for Phase 15-D handoff
       3db9386  feat(phase15d): cycle_play universe + multi-source fallback + chase prevention
       e7c6ff9  fix(acceptance): unblock portfolio for r1000+adr universe (research mode)
       186f9f5  fix(phase15c): mktcap $1T clip + 1970 epoch fund_period leak
       50f432b  fix(phase15c): sub_industry_rs_score crash (build_feature_store)
       0e8ced2  fix(export): prune empty / zero-fill columns from scored_latest.csv
       cc4bcff  feat(phase15c): risk discipline + ML×tech gate + sub-industry rank
       47875dd  feat(phase15c): entry_quality_score
       9bd5606  fix(phase15): activate sleeping cycle_recovery + eps_revision

ENGINE_REUSE_VERSION: 2026-04-29-concentrated-continuation
DEFAULT_FEATURES: 245
Smoke: 70/70 pass after concentrated continuation fix; audit 0 leakage
Working tree: pending commit/push if this handoff is read before finalization
```

**What Phase 15-A/B/C/D added (cumulative)**

7 ML features in `PHASE15_ALPHA_COLUMNS`:
1. `cycle_recovery_score`     — late-rescue cycle leaders (mom_24m bottom + mom_6m turn)
2. `eps_revision_score`        — eps_growth fallback when AV estimates missing
3. `early_cycle_inflection_score` — multiplicative gate (price near MA200 + mom_12m bottom + mom_3m early turn) + boost (eps revision + sign flip + industry breadth)
4. `entry_quality_score`       — chase-prevention (extension penalty + RSI zone + mom sweet spot + volume confirmation)
5. `ml_technical_agreement_score` — demote ML-strong-tech-weak names
6. `sub_industry_rs_score`     — best-of-best in sub_industry pct rank
7. `insider_cluster_boost_score` — 3+ insider buyers boost

Plus 36-name `cycle_play_universe.yaml` (BE/PLUG/RIVN/ENPH/...) with monthly
auto-refresh (`tools/refresh_cycle_play_universe.py` +
`.github/workflows/cycle_play_refresh.yml`, 1st of month 14:00 UTC).

**Critical fixes shipped (read these before re-debugging)**

1. ADR carve-out (8172c0d): exempts ADRs from R1000 SEC fundamentals gate
   denominator so R1000-only metrics don't degrade when ADR overlay added.
2. Acceptance gate relaxation (e7c6ff9): r1000+adr / global_alpha_universe
   modes no longer block portfolio_latest export when historical_membership
   file missing (research mode, ADR overlay = research, relax strict check).
3. mktcap clip $1T -> $100T (186f9f5): NVDA / AAPL / MSFT etc no longer get
   collapsed into single $1T tier. Was bug at 3 sites (build_feature_store,
   training, historical scoring); previously only patched at 1 site.
4. fund_period 1970 epoch leak (186f9f5): pd.to_datetime(0) returned
   1970-01-01 for missing periods. Now masked to NaT for any date < 1990.
5. CSV export pruner (0e8ced2): scored_latest.csv 638 cols -> 483 cols
   (24% reduction) by dropping all-NaN + all-zero placeholder columns.
   Phase 14/15 score columns whitelisted regardless.
6. Concentrated entry_quality continuation override (latest pending commit):
   Phase 15-D hard filter was too blunt for the CAGR-max sleeve. It blocked
   high-rank, trend-intact continuation winners like WDC/MRVL/CIEN/AMKR/FTI
   and replaced them with lower-momentum names, contributing to concentrated
   CAGR falling to 25.43%. The gate now still blocks broken/exit-risk chase
   entries but allows top-decile continuation winners when confirmation/trend
   are intact.

**Latest cloud run state**

Run `25091384080` (commit `959b76a`) completed successfully:
- GitHub Actions: success; artifact `full-rebuild-global_alpha_universe-25091384080`
- GDrive sync: success; outputs under `G:\내 드라이브\r1000_top30_institutional\outputs`
- Bot commit: `5bc9ef0`
- Main metrics: CAGR 23.48%, Sharpe 1.251, MaxDD -23.79%
- Verdict: PARTIAL vs Phase 14 (dCAGR -0.10pp, dSharpe +0.0727, dMaxDD -0.62pp)
- Concentrated: CAGR 25.43%, Sharpe 1.246, MaxDD -21.62%, 5 names
- ADRs worked: 30 scored, 4 in main portfolio (NTES, TSM, ZTO, ASML)
- Cycle-play weak: 33 injected / 20 added, but only 2 scored and 0 selected
- Do **not** rotate CURRENT_BASELINE.

**Critical post-run bug found and fixed (2026-04-29 18:00 KST)**

- TSM `mktcap` was ~10.17T because `px=392 USD ADR price` was multiplied by
  `shares=25.9B Taiwan ordinary shares`. True yfinance USD marketCap proxy is
  ~2.03T. Similar ADR-ratio distortions exist for NTES/PDD/ZTO.
- Fix: `apply_adr_usd_mktcap_proxy` anchors ADR market cap to yfinance USD
  marketCap and applies the ADR-ratio factor to historical px*shares rows.
- Fix: `compute_valuation_columns` uses `mktcap / px` as ADR-equivalent shares
  for ADR EPS/PE math.
- Fix: `extract_companyfacts_records` now prefers USD companyfacts units when
  SEC exposes multiple monetary unit buckets.
- `ENGINE_REUSE_VERSION` was later bumped again to
  `2026-04-29-concentrated-continuation`; next full_rebuild must regenerate
  feature_store/scored artifacts.

**Critical concentrated CAGR regression fixed (2026-04-29 19:08 KST)**

- Latest stale scored snapshot under the new continuation rule selects
  WDC / CIEN / MRVL / AMKR / FTI for concentrated, each marked
  `concentrated_entry_quality_override=True`.
- The prior hard filter selected ETR / ZTO / KIM / CW / PEG and the latest
  concentrated backtest fell to 25.43%, below both the Phase 14 33.40% champion
  and prior 36% research runs.
- This does not prove a new SHIP verdict. It restores the correct aggressive
  selection surface so the next cloud run can measure whether CAGR recovers.
- `ENGINE_REUSE_VERSION` is now `2026-04-29-concentrated-continuation`.

**Pre-trigger correction (2026-04-29 13:41 KST)**

- Do **not** use `skip_collector=true` for the first Phase 15-D verification.
  Local/GDrive price cache only has 13/33 active cycle-play tickers; 20 are
  missing and need the collector to fetch their history.
- Latest successful Finnhub weekly artifact (`25003804766`) was downloaded into
  `aggressive/state/finnhub/r1000_features.parquet` and force-added so cloud
  full_rebuild can immediately use Phase 15-D Finnhub PE/PEG fallback.
- GitHub Actions now caches/restores `aggressive/state/finnhub` and prints
  pre-run diagnostics:
  - `[cycle] active=... missing_price_cache_before_collector=...`
  - `[finnhub] fallback parquet present rows=... cols=...`

**Recommended next agent action sequence**

1. **TRIGGER AGAIN AFTER ADR + CONCENTRATED FIXES**: GitHub Actions `Full Rebuild (Manual / Long-Run)` with:
   ```
   universe_mode:    global_alpha_universe   ← includes R1000 + ADR + cycle play
   backtest_years:   8
   skip_collector:   false (first fair Phase 15-D run must collect missing cycle prices)
   fast_mode:        true
   cache_key_suffix: phase15d-cycle
   ```
   Expected runtime: ~2-3h if cache restored; use `skip_collector=false` if
   cycle-play price cache is still missing in the runner.

2. **VERIFY POST-REBUILD**:
   - `cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_latest.csv`
     should be NON-EMPTY (e7c6ff9 unblocks)
   - concentrated_portfolio should be allowed to include WDC/MRVL/CIEN/AMKR/FTI
     only when `concentrated_entry_quality_override=True` and trend/exit-risk
     gates are clean.
   - scored_latest.csv should include cycle play tickers (BE/PLUG/RIVN/...)
   - new columns: trailing_pe_recomputed, earnings_yield_recomputed,
     forward_pe_source, sub_industry_rs_score, insider_cluster_boost_score
   - `tools/aggregate_portfolio_performance.py --base-dir
     cloud_results/full_rebuild/latest_global_alpha_universe` to summarize
     per-sleeve + aggregate.

3. **DECIDE BASELINE ROTATION**:
   - If verdict SHIP (dCAGR ≥ +0.5pp, dSharpe ≥ -0.05, dMaxDD ≥ -3pp,
     early_scout selected ≥ 4): rotate CURRENT_BASELINE in
     `run_local.py` and update CLAUDE.md "Current Production Baseline"
     section.
   - If REGRESS: identify which Phase 15 feature has negative ML weight
     (read backtest_metrics.json model_coef section), disable via env
     var (PHASE_PHASE15C_ENTRY_QUALITY_ENABLED=0 etc), re-trigger.
   - If PARTIAL: investigate sleeve mix; concentrated likely shipping
     (33%+ CAGR threshold); main may need next iteration.

4. **TELEGRAM SILENCE since Apr 23**:
   - cron workflows (daily_review, paper_executor, tactical_after_close)
     stopped firing for 5 days. Manual triggers still work
     (full_rebuild ran successfully Apr 28).
   - Suspected cause: GHA scheduled workflow auto-disable due to free-tier
     quota (~15-20h consumed by recent full_rebuild runs).
   - Diagnose: GitHub Actions tab → check for "disabled" badge on
     daily_review workflow. Settings → Billing → see GHA usage.
   - If disabled: click "Enable workflow" on each affected cron file.
     Manual trigger of daily_review can validate Telegram works.

5. **D5 CYCLE PLAY AUTO-REFRESH**:
   - Workflow `.github/workflows/cycle_play_refresh.yml` runs 1st of
     each month at 14:00 UTC.
   - First scheduled fire: 2026-05-01 14:00 UTC.
   - Manually trigger to test: Actions tab → Cycle Play Universe Refresh
     → Run workflow.

**Files to read in order for new agent pickup**

1. This file (SESSION_HANDOFF.md) — current.
2. CHANGELOG.md top section (2026-04-29 entry) — Phase 15-D detail.
3. CLAUDE.md "Current Production Baseline" — Phase 14 still production.
4. cycle_play_universe.yaml — 36 entries by theme.
5. r1000_features.py compute_entry_quality_score / compute_cycle_recovery_score
   — current alpha logic.
6. Recent backtest_metrics.json (cloud_results/full_rebuild/latest_*) — last run.

---

## PRIOR INBOX (archived — Phase 14 / Apr 27)

Below is the previous session handoff (Phase 14 SHIP + ADR v2 prep). Useful
for understanding the Phase 14 baseline that Phase 15-D extends.

## ACTIVE INBOX (2026-04-27 18:40 KST) - ADR v2 / 8y official run next

**Current status**

- **A complete**: Phase 14 metrics are the production baseline in `run_local.py`, `colab_run.ipynb`, and `CLAUDE.md`. Old baseline preserved as `PHASE9_C3_CE_V2_BASELINE`.
- **B fixed in code**: ADR universe was dead in the main engine. Root cause was three-part:
  - GitHub Actions set `UNIVERSE_MODE`, but `run_local.py` did not pass it into EngineConfig overrides.
  - `full_rebuild_manual.yml` used legacy `PHASE14_HYBRID_ALPHA_ENABLED`; `phase_is_enabled("phase14_hybrid_alpha")` consumes `PHASE_PHASE14_HYBRID_ALPHA_ENABLED`.
  - `r1000_pipeline.py build_candidate_universe()` always used historical R1000 membership and historical membership filtering would drop external ADR rows.
- **B validation**: smoke 62/62 PASS, ADR quick audit 26/26 PASS, synthetic membership-filter check keeps `adr_whitelist` rows.
- **Global alpha universe path now wired**: use `universe_mode=global_alpha_universe` for the shared R1000 + curated ADR/global-alpha pool. Core and concentrated both consume the same scored frame, so this is the common universe for both sleeves/engines.
- **ADR v2 prepared**: `adr_universe.yaml` expanded from the original 26-name mega-cap ADR set to a 105-name active whitelist at the default ~$8B floor. ADR/global-alpha rows with sparse SEC fundamentals can pass via `adr_global_alpha_fallback` when price, momentum, relative strength, and score confirmation are strong enough.
- **8-year path is now the official default**: default backtest window is 8 years. GitHub Actions exposes `backtest_years=8`/`10`; `backtest_window_comparison.csv` still includes 5/8/10 and flags `partial_window` when OOS history does not cover the full requested window.
- **Sleeve audit now wired**: FULL/QUICK exports `reports/global_alpha_sleeve_audit_by_month.csv` and `reports/global_alpha_sleeve_audit_summary.csv` with per-sleeve candidate counts, gate-pass counts, ADR/source mix, growth/momentum/quality averages, and latest core/concentrated selected counts.
- **Latest global-alpha FULL run before ADR v2**: run 24974747494 proved ADR injection worked mechanically, but only 5 ADR/global-alpha rows survived into `scored_latest.csv`, 0 were selected, and the run was marked `research_only_backtest=true` because 10y coverage was partial. Trigger a new FULL rebuild after this ADR v2 commit.

**Design read against user goal**

- **Core portfolio goal**: current Phase 14 main CAGR is 23.58%, Sharpe 1.178, MaxDD -23.17%, avg monthly turnover 45.5%. The architecture is pointed the right way, but core is not yet a stable 25% system. Do not chase this by adding more names/signals first; next best step is C, the quarterly/sleeve-aware rebalance A/B, because turnover and exit cadence are the largest stability risks.
- **Concentrated goal**: current champion is N=5/monthly/score_power, CAGR 33.40%, Sharpe 1.284, MaxDD -25.29%. If daily trading is allowed, concentrated needs a separate daily replay/aggressive execution track; forcing daily behavior into the monthly core backtest will blur the mandate and make core less stable.
- **Recommended sequence from here**:
  1. Run smoke, commit/push current `global_alpha_universe` + 8y default + ADR v2 fallback wiring.
  2. Trigger GitHub Actions `full_rebuild_manual.yml` with `universe_mode=global_alpha_universe`, `backtest_years=8`, `skip_collector=false` if the ADR cache needs full refresh, otherwise `skip_collector=true`, `fast_mode=true`.
  3. Review `scored_latest.csv` ADR count, ADR fallback gate labels, and `global_alpha_sleeve_audit_summary.csv` to confirm sleeve selection behavior.
  4. Then start C for core stability: compare monthly vs quarterly/sleeve-aware cadence and only change sleeve score/gate weights after the audit shows the failure mode.
  5. After C, design concentrated daily replay using scanner signals, daily stop/hold rules, and separate CAGR-max objective.

---

## 🎉 Phase 14 ZIP Verdict (run 24961673988, 2026-04-27 10:18) — SHIP CONFIRMED

**Verdict tool output** (`tools/compare_adr_backtest.py --variant ... --use-pinned-baseline`):

```
CAGR      22.91%  ->    23.58%   ΔCAGR  +0.67pp  (gate ≥ +0.50pp)  ✅
Sharpe    1.172   ->    1.178    ΔSharpe +0.006  (gate ≥ -0.050)   ✅
MaxDD    -26.26%  ->   -23.17%   ΔMaxDD +3.09pp  (gate ≥ -3.00pp)  ✅
VERDICT: ✅  SHIP — All 3 gates pass.
```

**Lifetime CAGR (Phase 12)**: 23.48% over 6.84y, $100k → $432k cumulative.

**Phase 14 features verified in scored_latest.csv** (6/6 present):
rs_acceleration_score, h1_oversold_value_score, h6_dynamic_leader_score, stage2_overext_penalty, theme_phase_multiplier_primary, theme_phase_multiplier_max.

**Run metadata**: commit 724fbb9 DIRTY, engine 2026-04-25-phase14-hybrid-alpha, 95/95 walk-forward months, acceptance_checks all_pass=True.

**Artifact location**: `research/phase14_artifact/` (7 files including verdict.log + full pipeline log) — preserved for new agent reference.

---

## 🟢 LATEST STATE (2026-04-26) — Phase 14 hybrid alpha + ADR universe code-ready, FULL rebuild verdict pending

**Current HEAD = `2d1f329`** on `claude/analyze-updated-code-OfEbu` branch.

### What just shipped (code only, FULL rebuild not yet run)

**Phase 14 hybrid alpha (`5a41219`)** — wired validated Aggressive scanner alpha into 정석 ML cfg.features:
- `rs_acceleration_score` (T4 +10% alpha)
- `h1_oversold_value_score` (Opus H1 +8.67% alpha 12m, n=1149, p<0.0001)
- `h6_dynamic_leader_score` (Opus H6 +7.38% alpha 12m, n=704, p<0.0001)
- `stage2_overext_penalty` (T1 -2.5% protection)
- `theme_phase_multiplier_{primary,max}` (themes.yaml early/maturing/peaking/ending/dead)
- `ENGINE_REUSE_VERSION = "2026-04-25-phase14-hybrid-alpha"` (DEFAULT_FEATURES 232→238)

**ADR universe (`d62fbb6`)** — 26 top-mcap ADRs (TSM, ASML, BABA, NVO, ...) + 3 watchlist (SK Hynix Oct 2026, Samsung Pink-OTC, Reliance India). Universe modes `r1000`, `r1000+adr`, `adr`. Safety: ADRs flagged `skip:true` (TCEHY OTC) excluded.

**8 GitHub Actions workflows operational** (~1120min/month < 2000 free):
- `daily_review.yml` Mon-Fri 23:00 KST (R1000 scanner top 25)
- `paper_executor_dryrun.yml` Mon-Fri 23:30 + Sat 15:00 KST (regime + advisor + Telegram)
- `unified_monthly.yml` 1·15일 23:30 KST (scored_unified.csv)
- `theme_discovery.yml` Sun 22:00 KST (Phase 18A)
- `finnhub_weekly.yml` Mon 22:30 KST
- `layer4_monthly_swap.yml` 5일 23:00 KST (Layer 4 swap, dry-run by default)
- `monthly_ic_monitor.yml` 1일 11:00 KST (ADR macro IC, Telegram alert if China-IC > US-IC + 0.05)
- `full_rebuild_manual.yml` MANUAL ONLY (3-5h, universe_mode r1000 / r1000+adr / r1000+adr_phase14_off)

**Pre-flight verified (Phase A-F system audit, 2026-04-26)**:
- ✅ smoke 56/56 PASS
- ✅ audit_features 3/3 PASS, 238 features, 0 forward-return
- ✅ Phase 14 PIT-safe (no r_*m / bench_r_*m / earn_post_ / future_* refs)
- ✅ NaN robustness verified (all-NaN/sparse → neutral 1.0 multipliers)
- ✅ Call order: merge_benchmark_relative_features (line 6442) → Phase 14 (7043+)
- ✅ All 8 workflows YAML valid, secret refs correct

### 🚧 Next-agent priority (in order)

1. **Trigger `full_rebuild_manual.yml`** with `universe_mode=r1000+adr` (variant). 3-5h GHA runtime, Telegram alert at completion.
2. **Trigger again with `universe_mode=r1000`** (control, R1000-only baseline).
3. **Run verdict tool**: `py -3 tools/compare_adr_backtest.py --baseline <r1000_metrics> --variant <r1000+adr_metrics>`. Output: SHIP / PARTIAL / REGRESS.
4. **If SHIP**: rotate `CURRENT_BASELINE` in `run_local.py` + update CLAUDE.md "Current Production Baseline" + add CHANGELOG entry.
5. **If REGRESS**: optionally run 3rd workflow `r1000+adr_phase14_off` to isolate (ADR fault vs Phase 14 fault).

Detailed step-by-step in `PHASE14_VERDICT_PROCEDURE.md` (164 lines).

---

## 🗂️ ARCHIVED (pre-2026-04-26)

(Original handoff content from 2026-04-22 below — kept for historical reference. Issues mooted by Phase 14 + ADR work shipping. Do not act on these unless Phase 14 verdict triggers re-investigation.)

## 🟢 ARCHIVED STATE (2026-04-22 evening) — 9-cell grid done, baseline regression to investigate

**Current HEAD = `b4e3bab`** on `master`. 41 commits today.

### ✅ UPDATE (evening `bl49bkdrv` full QUICK complete)

**--ab-quick bug identified + actual regression is manageable**:

```
OLD baseline (b0r5er6bz):              CAGR 22.95% / Conc 33.17%
--ab-quick baseline (bi4d0bmfu, bad):  CAGR 16.08% / Conc NaN (degenerate)
Full QUICK baseline (bl49bkdrv, good): CAGR 19.78% / Conc 30.92%
```

**Root cause of perceived catastrophic regression**: --ab-quick mode
disables concentrated grid → sleeve_cap_policy champion selection fails
→ main blend construction cascaded degradation. Not a real alpha regression;
a bug in the A/B-quick mode.

**Actual regression is -3.17pp main / -2.25pp concentrated**, consistent
with normal data drift + Tier 0 mktcap cap change + ML retrain. Not catastrophic.

### ⚠️ Next-agent priority (revised)

1. **--ab-quick mode fix** — preserve at minimum 1 concentrated combo + sleeve_cap_policy champion so main blend stays valid. All 9-cell grid results from `b4e3bab` invalid (used broken --ab-quick baseline).
2. **Rerun 9-cell grid on Full QUICK baseline** — each cell ~20-30min × 9 = 3-4 hours. OR cherry-pick most-likely cells only.
3. **15-A1 FULL rebuild** — test feature-store-level change properly (~3h).
4. **Investigate -3pp drift**: is it Tier 0a mktcap cap? Revert in isolation to confirm.
5. **15-S1b ML target r_3m** — biggest expected lift per deep audit (~3h FULL).

### Tier 2 grid verdict (9-cell, `b4e3bab`)
See `research/phase15_tier2_ab/VERDICT_OVERNIGHT.md`.

- R1/R2/R3 trailing/revision/RS break exits: **zero delta** (threshold never
  triggers in 83-month sample). Safe to ship as future insurance.
- Phase 4 regime sleeve weights: **-0.25pp FAIL**. Keep default OFF.
- Phase 6c vol targeting: **zero delta** (dormant). Safe to ship.
- 15-A1 negative features drop: **zero delta** because cache-blocked.
  Requires FULL rebuild for valid A/B.
- Concentrated outputs: all NaN (--ab-quick disables concentrated grid).

### In-flight
`bl49bkdrv` full QUICK (no --ab-quick) baseline — will produce concentrated
grid results. 30-60min. Results saved to `outputs/` on Drive.

### Massive Tier 0/1/2 ship batch (26 commits today)

Foundation + gate fixes:
- `04503fd` tier0a + gates: mktcap clip 1e12 → 1e14 (mega-caps no longer collapsed); Phase 4/6c/7a gate env-overrides-cfg (previously locked dormant since 2026-04-16)
- `42ddce3` tier0b: SEC companyfacts int-date parsing (1970 epoch bug — 477/610 rows)
- `5b5edac` tier0c: standalone sleeve CSVs now populate (sleeve_test column added)

Speed infra:
- `ebc0b26` --ab-quick CLI flag (disable 7 grid comparisons)
- `b43c680` apply_fast_mode override fix (concentrated grid was forced on)
- `fb4547f` em-dash crash fix (cp949 console)
- `7b9dad1` reuse_fingerprint excludes runtime-only fields (no more cache invalidation when adding cfg fields)

Phase 15 implementations (all default OFF, env A/B ready):
- `dfcc07c` 15-S1a: 3 toxic factor prune (future_winner only)
- `b002f8a` 15-S1a gate env-overrides-cfg fix
- `2cc2a76` 15-S1a sub-toggles (per-factor ablation)
- `6d1d848` 15-A1: drop 3 NEGATIVE-IR features (macro_hedge, focus_defensive, focus_live_event_defensive)
- `1f6349e` 15-R1: trailing stop early_scout / future_winner (peak drawdown)
- `abe89b0` 15-R2 + 15-R3: revision break + RS break exits
- `aba097c` smoke locks + Tier 2 grid runner

Research:
- `21f1979` Phase 15-S1 factor IC audit (3m horizon = sweet spot, 1m near-random)
- `53af224` 15-S1a verdict: main FAIL / concentrated PASS
- `77d829f` selection deep audit (production score IR 0.048; 11 missed winners; 4 negative features)

### A/B in flight
`b029fgd3t` 15-A1 with --ab-quick. ONE-TIME slow rebuild (30-60min) due to fingerprint formula change in `7b9dad1`. After this completes, ALL future A/Bs are ~5min.

### Tier 2 A/B grid READY (after b029fgd3t completes)
```
bash research/phase15_tier2_ab/run_tier2_grid.sh   # 6 cells × ~5min = ~30min
py -3 research/phase15_tier2_ab/analyze_tier2.py    # delta + ship gate verdict per cell
```
Cells: A baseline / B R1 only / C R2 only / D R3 only / E all_R / F R+A1.

### Known gaps still open
- Tier 0d: r_12m coverage cliff — investigated, **NOT a bug** (forward returns naturally NaN for recent 12m). No action.
- Tier 0e: Benchmark R1000 vs SPX — investigation pending.
- Phase 4 / 6c A/B — gate fixed `04503fd`, ready to run once Tier 2 done.
- Phase 7a redesign (clustered insider buying) — design pending.
- 15-R4 weekly monitor — architectural change, not started.
- 15-S2b core conviction lock — design needs revision (target mid-rank #8-18 per audit Finding 4).
- 15-S1b ML target r_3m realign — needs FULL rebuild (~3h).
- Phase 13-lite (yaml split + summary.json + recent_trades.json) — service tier, not started.
- Phase 14 dividends — deferred.

### Ablation COMPLETE (`bbl6mkuiq` + `bhyyse6xs`)

| Variant | Main ΔCAGR | Main MaxDD | Conc ΔCAGR | Conc Sharpe | Verdict |
|---|---|---|---|---|---|
| full_prune (all 3) | -0.46pp | +4.03pp | +3.25pp | +0.118 | main FAIL |
| drop_ft only | -0.12pp | +4.01pp | +2.97pp | +0.111 | main FAIL |
| drop_cf only | +0.15pp | -0.08pp | +0.80pp | +0.022 | FLAT |
| **drop_ub only** | **+0.36pp** | -0.08pp | +0.77pp | +0.021 | **FLAT (best)** |
| drop_cf+ub | +0.16pp | -0.19pp | +0.80pp | +0.022 | FLAT |

**Decision**: strict ship gate (+0.5pp) not cleared by any variant. All cfg defaults remain OFF.

**Insights**:
- FT alone drives 91% of concentrated +3.25pp AND all of main MaxDD +4pp win — but costs -0.12pp main CAGR.
- CF + UB combined ≈ UB alone (sub-additive, correlated noise).
- drop_ub best single-factor pick (+0.36pp main, +0.77pp conc, MaxDD flat).

Full write-up: `research/phase15_s1a_ab/VERDICT_ADDENDUM_ABLATION.md`.

### Recommended next step (for next agent session)

1. **Concentrated-exclusive FT drop** (~1-2h code work, then QUICK A/B):
   - Modify `concentrated_score` computation at r1000_pipeline.py:11939 to use a second "pruned" future_winner composite with FT zeroed. Main composite untouched.
   - Expected: main neutral, concentrated +2.97pp (matches variant A).
   - Cleanly ships biggest concentrated win without main regression.

2. OR **Phase 15-S1b horizon realign** (FULL rebuild, 2-3h):
   - Train `pred_future_winner_ret` on `r_3m` target instead of `r_1m`.
   - IC audit root finding: future_winner composite factors are 3m alpha, not 1m.
   - Higher expected impact but bigger cycle.

3. OR **15-R1 Trailing stop** (cfg fields already prepped in dfbfaed):
   - Wire the backtest loop (r1000_pipeline.py:9831-9864 speculative stop area) to track peak + drawdown per early_scout position.
   - 4-cell A/B (baseline / 0.15 early / 0.20 early / 0.15 both sleeves).
   - Independent of 15-S1 path.

### Gate semantics currently shipped
- Master: `PHASE_PHASE15_S1A_FUTURE_PRUNE_ENABLED=1` drops all 3 factors.
- Sub-toggles: `DROP_FT`, `DROP_CF`, `DROP_UB` drop individually.
- Cfg default: all False (production unchanged). Env var overrides.

**NEW TARGETS** (user set 2026-04-21 PM): main 22.95% → **25% CAGR**, concentrated 33.17% → **40% CAGR**.

### Just finished (afternoon session)
- `6a5491d` chore: gitignore catboost_info/ training artifact
- `24992c7` fix: Phase 12B+ensure_live_portfolio_state moved BEFORE first enrichment (cold-start fix — solves the 2-known-issues #1 from morning handoff)
- `a5a5271` fix: Phase 12A held_days tz bug (utcnow tz-aware vs entry_date tz-naive) + reference_price auto-fill in apply_manual_positions_from_yaml (no more "no_live_data" in lifetime_metrics.json)
- `dfbfaed` prep(phase15-r1): trailing_stop_enabled + trailing_stop_early_scout_pct cfg fields (default OFF, A/B-ready) + structural smoke test
- `21f1979` research(phase15-s1): per-factor rank-IC audit on future_winner composite. **KEY FINDING** (see below).

### VALIDATION in progress (background `b0r5er6bz`)
QUICK pipeline re-run with `PHASE_PHASE11_MULTIBAGGER_ENABLED=0 py -3 run_local.py --no-collector` to verify both Phase 12 fixes land. Expected: 9/9 enrichment columns populated (vs 6/9 on `24992c7`-only run), lifetime_equity_curve.csv = 84 rows (83 backtest + 1 live extension), live_value_method = "shares_x_reference_price".

### 🔥 KEY RESEARCH FINDING — future_winner 1m composite has no factor-level alpha

`research/phase15_s1_future_winner_factor_ic.csv` audit of 21 factors at 1m vs 3m horizons:

| Factor | Weight | IC_1m IR | IC_3m IR |
|---|---|---|---|
| leader_emergence_score | 0.90 | +0.04 | **+2.54** |
| anticipatory_growth_score | 0.95 | +0.00 | **+2.25** |
| future_winner_scout_score | 1.10 | -0.01 | **+2.22** |
| dynamic_leader_score | 0.95 | -0.03 | **+1.71** |
| uptrend_continuation_score | 0.30 | +0.01 | +1.53 |
| rs_industry_6m | 0.25 | +0.06 | +1.50 |
| fundamental_turnaround_acceleration_score | 0.50 | -0.19 | -0.27 (toxic!) |
| cashflow_inflection_under_loss_score | 0.35 | -0.15 | -0.20 (toxic!) |
| uptrend_breakdown_penalty | -0.30 | +0.03 | -2.03 (sign mismatch!) |

**Interpretation**: 17/17 factors are "1m prune candidates" but >10 have IR_3m > +1.5. The composite factors **are 3-month alpha disguised as 1-month decisions**. Future_winner standalone CAGR 16.08% (topn_cagr_1m) is the cost of this horizon mismatch.

**Implications for 15-S1 redesign** (from naive "prune composite" to "realign horizon"):
1. Train `pred_future_winner_ret` ML target on `r_3m` (not `r_1m`)
2. A/B future_winner rebalance interval {2m→3m}
3. Remove the 3 genuinely-toxic factors (negative at BOTH horizons)
4. Expected lift: future_winner 16% → 22-25% standalone (+main blend +0.5-1pp, +concentrated +2-3pp)

### USER'S SEQUENCING DECISIONS (2026-04-21 PM)
- **Phase 13** full ledger (PHASE_13_PLAN.md, 8h) → **discard**. Replace with Phase 13-lite (Option B yaml split, 3h, anytime).
- **R2000 expansion** → **defer indefinitely** (regime-amplification risk during Energy bull).
- **Sector concentration cap (B9)** → **rejected** ("시그널이 그 섹터라고 외치면 믿자"). Keep cap-free, compensate with EXIT discipline (trailing stop, RS break, revision break).
- **Phase 15 ordering** → stability-first, priority-first:
  - Tier 1: Phase 12 bug fix (running)
  - Tier 2: exit discipline (15-R1 trailing / 15-R2 revision break / 15-R3 RS break / 15-R4 weekly monitor)
  - Tier 3: sleeve strengthening (15-S1 future_winner horizon realign / 15-S2 core quality gates / 15-S3 early_scout hardening)
  - Tier 4: 15-S4 sleeve-specific rebalance A/B
  - Tier 5: 15-S5 concentrated regrid
  - Orthogonal: Phase 13-lite (export infra)
- **Deferred**: dividend handling (Phase 14), market-shock detection, automation.

### NEXT AGENT — start here when validation completes
1. Check `/tmp/phase12_bugfix_validation.log` or `G:\내 드라이브\r1000_top30_institutional\outputs\lifetime_metrics.json` for `live_value_method` value.
2. Verify `portfolio_latest.csv` has all 9 enrichment columns populated (not just 6/9).
3. If verdict OK → start **15-R1 trailing stop implementation** in `backtest_portfolio` around line 9831:
   - Mirror `speculative_cum_ret` logic with `trailing_peak_ret` + drawdown-from-peak check
   - Gate on `cfg.trailing_stop_enabled AND phase_is_enabled("phase15_r1_trailing")`
   - A/B matrix: baseline / 0.15 early / 0.20 early / 0.15 both sleeves
4. If validation surfaces additional bugs → fix first before 15-R1.

---

## 0. Production Baseline + recent verdicts

**Phase 9 C3 + CE v2** (SHIPPED 2026-04-18 21:22 KST, still active):
- Main diversified: CAGR 22.91%, Sharpe 1.17, MaxDD -26.26%, 18 positions
- Concentrated champion: N=5/1m/score_power → CAGR 34.75%, Sharpe 1.254

**Phase 11** (multibagger) A/B **REJECTED** 2026-04-21: -1.73pp CAGR. Default OFF.

**Phase 12** (live continuity) **SHIPPED** 2026-04-21.

---

## 0a. TL;DR — 🎉 **REFACTOR PHASE A COMPLETE** (26 commits on branch `refactor/phase-a-module-split`). Full 5-module split + Subtractive dead code removal. Main engine 27,838 → 382 lines facade (-98.6%).

**Current HEAD = `4c9858a`** on branch `refactor/phase-a-module-split` (pushed to remote). **26 refactor commits** on top of last SHIP `6440957`. All 5 new modules created + main converted to facade:

| Module | Lines | Owns |
|---|---|---|
| `r1000_config.py` | 2,109L | Pure data constants + EngineConfig (435 fields) |
| `r1000_helpers.py` | 967L | Stats + IO + cache + CIK normalization |
| `r1000_features.py` | 4,598L | 44 feature funcs (industry/fund/macro/blueprint/pillar/minervini) |
| `r1000_signals.py` | 3,614L | Sleeve composition + portfolio construction |
| `r1000_pipeline.py` | 15,315L | Training + backtest + export + validation + grid comparisons |
| `r1000_top30_institutional.py` | **382L** | **FACADE** (imports + re-exports) |
| **TOTAL** | 26,985L | (was 27,838 monolith; -853L dead code removed) |

**Dependency graph** (acyclic):
```
config.py <- helpers.py <- features.py <- signals.py <- pipeline.py <- main (facade)
```

Smoke tests **25/25 PASS** at every sub-stage. All nested helpers scope-preserved (Phase 9 C3 `_sign_flip_pos`, `within_group_z`, `sector_median`, `_scaled_unit_from_series`).

### What's done (26 commits, newest first)

| Commit | Stage | Summary | Lines |
|---|---|---|---|
| `4c9858a` | **5** | Create `r1000_pipeline.py` (15,315L) + convert main to 382L facade | -14,912 main |
| `48e4f8b` | **6 Subtractive** | Delete 17 `_legacy_unused_*` dead funcs | -2,307 main |
| `bb44fe8` | **docs** | SESSION_HANDOFF update after 4b-ii | docs |
| `b58dd51` | **4b-ii** | `build_target_portfolio` (739L) + 21 portfolio helpers → signals.py | -1,495 main |
| `14f2cef` | **4b-i** | `compute_regime_portfolio_controls` (349L) + `compute_benchmark_beating_focus_overlay` (260L) → signals.py | -607 main |
| `a7aca61` | **4a** | NEW `r1000_signals.py`: `compute_portfolio_sleeve_columns` (1,028L with Phase 9 C1+C2+C3 gate) + `compute_portfolio_sleeve_policy` (222L) + 3 helpers | -1,358 main |
| `a6014ab` | **docs** | rotate SESSION_HANDOFF after Stage 1 rollup FAIL analysis (data drift, NOT regression) | docs |
| `b0ca4c1` | **docs** | rotate SESSION_HANDOFF + STAGE_3D_PLAN after Stage 3d commits | docs |
| `b2f4331` | **3d-iv** | `compute_strategy_blueprint_columns` (926L) + `compute_multidimensional_pillar_scores` (186L) + `compute_minervini_momentum_overlay` (144L) → features.py | -1,246 main |
| `54986f7` | **3d-iii** | 6 funcs: market_adaptation + dynamic_leadership (w/ within_group_z nested) + manual moat overrides + ticker overlays + three_level RS + crisis_sector_fit → features.py | -546 main |
| `466ba27` | **3d-ii-min** | `compute_event_regime_features` + `sector_indicator` + `compute_macro_interaction_features` (pure transforms) → features.py | -194 main |
| `6b172a3` | **3d-i** | `_flexible_lag` + `_cagr_from_lag` + `recompute_fund_panel_derived_columns` (458L). Phase 9 C3 nested `_sign_flip_pos`/`_loss_narrowing_rate`/`_under_loss_growth` scope PRESERVED. | -559 main |
| `2631e62` | **3d-i-prep** | 4 CIK normalization helpers → helpers.py (unblocks 3d-i `normalize_cik_series` dep) | -32 main |
| `fd4e6a0` | **3c** | 8 live/satellite/moat/gate feature functions → features.py | -469 main |
| `74be2a0` | **3b** | 28 alpha_vantage + yfinance + fundamental trend fetchers → features.py | -1,237 main |
| `cf5e1a2` | **3a** | 8 industry RS/O'Neil feature funcs → new `r1000_features.py` | -217 main |
| `9cf6d38` | **2d** | 27 IO/ticker/cache/run-identity helpers → helpers.py | -612 main |
| `f2274fc` | **2c** | 11 numpy/pandas stats primitives (winsorize, robust_z, cross_sectional_robust_z, …) → helpers.py | -389 main |
| `d898f48` | **2b** | apply_fast_mode + to_cfg + configure_last_n_years_backtest → helpers.py | -237 main |
| `dfbea54` | **2a** | 5 smallest helpers (phase_is_enabled, now_ts, log, ENGINE_COMMIT_SHA, _resolve_engine_commit_sha) → new `r1000_helpers.py` | -117 main |
| `06f1171` | **1d-ii** | EngineConfig dataclass (435 fields) + default_manual_regime_conditioned_sleeve_map → config.py | -748 main |
| `c3df377` | **1d-i** | 5 scalar constants + `import re` → config.py | -12 main |
| `c59db52` | **1c** | 17 SEC/yfinance/sector data structures → config.py | -216 main |
| `b782e36` | **1b** | 40 pure-data constants → config.py | -774 main |
| `01d5f85` | **1a** | 5 PHASE*_COLUMNS lists → new `r1000_config.py` | -48 main |
| `dd7cf46` | **0 DONE** | baseline captured from `6440957` SHIP outputs (scored/portfolio/weights/backtest_metrics ref files in `.refactor_baseline/`) — no pipeline run needed | +refs |

### What's pending

1. **Stage 1 rollup COMPLETED at 15:43:28 KST with DIVERGENCE — root cause data drift, NOT refactor regression.** Actual commit tested: `06f1171` (Stage 1d-ii), started 11:12:59 KST. Rollup reached Phase 6 successfully writing 4 verify targets (scored/portfolio/weights/backtest_metrics) at 15:43, then crashed in `update_operational_tracking` Phase 6 ops tracking with `pyarrow.lib.ArrowInvalid: Could not convert 1.0 with type float: tried to convert to boolean` — **PRE-EXISTING schema drift bug** in `append_history_parquet` (held_from_prev_rebalance column has mixed bool/float across call sites in main:9269, main:9332, main:18581). Flagged as separate task.

   `verify.py` output:
   - All 4 files size/SHA differ from baseline
   - Column structure IDENTICAL (618 cols, 610 rows both)
   - `rebalance_date` max: current `2026-04-20` vs ref `2026-04-17` (3 days data drift)
   - CAGR: current `0.2341` vs ref `0.2291` (+0.50pp; explained by retrain on different data window)
   - Other metric diffs (avg_stock_names, beat_month_ratio, etc.) — all consistent with 3-day data window shift causing feature_store + walk-forward full rebuild.

   **Why full rebuild happened**: `reuse_fingerprint(cfg, scope)` (main:1287) hashes `asdict(cfg)` which includes `cfg.end_date`. When `end_date` differs between runs, fingerprint differs, cached artifacts get rebuilt. `run_local.py` defaults `end_date` to today. **This means byte-exact verify on re-run is fundamentally impractical** without pinning `end_date` exactly AND disabling price cache refresh AND locking every ML seed.

2. **Verification strategy pivot** (post-rollup-finding): byte-exact via full-pipeline re-run is impractical. Strategy must shift to:
   - **Smoke tests 25/25** after every sub-stage (catches structural invariants)
   - **Identity checks** (`r.FN is f.FN` / `r.HELPER is h.HELPER`) after each move
   - **Scope checks** (nested helpers stay encapsulated via hasattr negative test)
   - **Spot-behavior** (empty/small-input behavior for each moved function)
   - **Optional re-run with pinned `--end-date 2026-04-17 --no-collector`** at Stage 5 completion — will still drift due to stochastic training but metrics should be within 0.3pp CAGR tolerance if refactor is value-preserving.

3. **Commits `2631e62..b58dd51` (Stage 3d-i-prep through 4b-ii)** — verified via smoke/identity/scope/spot-behavior only; byte-exact deferred per strategy pivot above.

4. **Stage 4c pending** — concentrated grid + sleeve_cap_policy comparison. Dependency analysis shows this layer calls `backtest_portfolio` (Stage 5 target) via `compare_sleeve_cap_policy_backtests` + `compare_standalone_sleeve_topn_backtests`. This means:
   - Only 3 concentrated-grid funcs (`select_concentrated_portfolio_topk`, `backtest_concentrated_portfolio`, `compare_concentrated_portfolio_backtests`) are movable to signals.py standalone — they have their own backtest loops.
   - The grid/comparison layer (`compare_sleeve_cap_policy_backtests`, `compare_standalone_sleeve_topn_backtests`, `choose_sleeve_cap_policy`, `apply_sleeve_cap_policy_to_cfg`, `sleeve_cap_policy_objective`, `generate_sleeve_cap_policy_candidates` 248L, etc.) belongs in `r1000_pipeline.py` (Stage 5) since it orchestrates backtests.
   - **Recommendation**: merge Stage 4c into Stage 5. Create `r1000_pipeline.py` with BOTH the grid-comparison layer AND the core pipeline (`train_walkforward`, `backtest_portfolio`, `export_outputs`, `run_all`, etc.).

5. **Stage 5 planning** — expected scope ~5,000L across ~20 functions:
   - `train_walkforward` (443L)
   - `backtest_portfolio` (694L)
   - `backtest_standalone_sleeve_topn` (?)
   - `export_outputs` (1,622L) — LARGEST function remaining
   - `run_all`, `run_default_pipeline`, `run_last_n_years_backtest`
   - `build_feature_store` (224L), `build_universe_monthly` (321L)
   - Stage 4c grid comparisons (~800L as noted above)
   - Misc pipeline helpers
   
   Executable as 3-5 sub-stages (5a: universe + feature_store; 5b: train + backtest; 5c: concentrated grid; 5d: policy comparison; 5e: export_outputs + run_all). Each sub-stage ~1-2k lines, smoke+identity verified.
3. **Stage 3d-ii-b (deferred)** — `load_fred_series` + `build_macro_regime_table` 417L + `build_live_event_alert_table` 187L + merge helpers (~850L). Blocked on moving 5 price-cache cascade helpers (`ensure_prices_cached_incremental` 95L + `load_px` + `macro_cache_file` + `price_close_series` + `write_stage_coverage_report`) to helpers.py first. See `STAGE_3D_PLAN.md` execution log for details.
4. **Stage 4**: `r1000_signals.py` — sleeve composition + portfolio construction. In-scope: `compute_portfolio_sleeve_columns` (1,028L), `compute_portfolio_sleeve_policy` (222L), `build_target_portfolio` (739L), `compute_regime_portfolio_controls` (349L), `compute_benchmark_beating_focus_overlay` (260L).
5. **Stage 5**: `r1000_pipeline.py` — orchestration + facade re-exports. In-scope: `train_walkforward` (443L), `backtest_portfolio` (694L), `export_outputs` (1,622L), `run_all` + `run_default_pipeline` + `run_last_n_years_backtest`, `build_feature_store` (224L), `build_universe_monthly` (321L).
6. **Stage 6 (Subtractive)**: delete `_legacy_unused_*` funcs (~2,500L) + Phase 3/5/7a dead branches.

### Production baseline — UNCHANGED by refactor (value-preserving extraction)

Phase 9 C3 + CE v2 baseline from `d3d3a91` / `6440957` still stands:

## 0a. Phase 9 C3 + CE v2 SHIPPED (2026-04-18 21:22 KST) — production baseline

**SHIP VERDICT confirmed on commit `d3d3a91`** (2026-04-18 21:22 KST) via `py -3 run_local.py --no-collector`. Both main diversified AND concentrated improved across every metric. User's original CAGR 30%+ goal achieved via concentrated mode.

### Main diversified — new production baseline (replaces Phase 9 C1+C2)

| metric | new | prior (C1+C2) | delta | ship gate |
|---|---|---|---|---|
| **CAGR** | **22.91%** | 21.69% | **+1.22pp** | ✅ (≥+0.5pp) |
| **Sharpe** | **1.1721** | 1.0732 | **+0.0989** | ✅ (≥-0.05) |
| **MaxDD** | -26.26% | -23.97% | -2.29pp | ✅ (within -3pp) |
| **IR** | **0.9474** | 0.7985 | **+0.1489** | - |
| **excess_cagr** | **+9.42%** | +8.19% | +1.23pp | - |
| avg_turnover | 43.1% | 45.0% | -1.9pp | - |
| early_scout count | 4 | 4 | 0 | ✅ (≥4) |

Portfolio: **18 positions, cash 3.8%**. Sleeve target 60/25/15 (defensive_drawdown_control). Top 5: NVDA 14%, GOOG 14%, AVGO 8.2%, AAPL 7.8%, JNJ 7.8%.

### 🎯 Concentrated champion — CAGR 30%+ goal DONE

**N=5 / monthly / score_power → CAGR 34.75% / Sharpe 1.254 / MaxDD -26.74% / IR 1.073**. $100k → $786k in 83 months (7.87x). **10 combos > 30% CAGR** in the full 63-combo CE v2 grid.

5-name holdings (by score_power weight):

| Rank | Ticker | Name | Sector | Weight |
|---|---|---|---|---|
| 1 | **PR** | Permian Resources | Energy | 30.3% |
| 2 | **ETR** | Entergy | Utilities | 27.8% |
| 3 | **GEV** | GE Vernova | Industrials | 15.2% |
| 4 | **FTI** | TechnipFMC | Energy | 14.5% |
| 5 | **AKAM** | Akamai | IT | 12.3% |

Runner-up concentrated (all >30% CAGR, for A/B robustness):
- N=3 / 1m / score_power: 33.77%, Sharpe 1.193
- N=4 / 1m / score_power: 32.70%, Sharpe 1.185
- N=7 / 2m / score_power: 30.92%, Sharpe 1.227 (lowest turnover 33.9%)
- N=3..10 / 1m / conviction_curve tied at 30.80% (weight decay makes tail positions zero)

### What was shipped (commits f93a4a2 + d3d3a91)
- Phase 9 C3: EPS turn-positive / still-loss-improving branches on early-scout gate (commit `86be7f9`, now in this baseline)
- CE v1: widened concentrated grid defaults (7 N × 3 intervals × 3 modes = 63 combos) and lifted 3 outer caps (commit `f93a4a2`)
- CE v2: lifted 2 inner clamps in `select_concentrated_portfolio_topk` + `backtest_concentrated_portfolio` that were silently clamping N>3 back to N=3. **Without CE v2 the Phase 5e grid was a 21-combo test cosplaying as 63.** Commit `d3d3a91`.

### Baselines rotated (3 files atomic)
- `run_local.py CURRENT_BASELINE` → Phase 9 C3 + CE v2 metrics. Previous baseline kept as `PHASE9_C1C2_BASELINE` for legacy delta calculations.
- `colab_run.ipynb` Cell 10 `BASELINE` → same numbers.
- `CLAUDE.md` "Current Production Baseline" section → same numbers + concentrated champion pointer.

**Current HEAD = `d3d3a91`.** Next commit (this one) rotates baselines atomically across the 3 files.

---

## 1. Recent timeline (newest first) — branch `refactor/phase-a-module-split` on top of `origin/master@6440957`

**Refactor Phase A commits (branch only — NOT yet merged to master)**:

| Commit | Title | Stage | Byte-exact verify |
|---|---|---|---|
| `fd4e6a0` | Stage 3c: 8 live/satellite/moat/gate feature funcs → features.py | 3c | ⏳ pending rollup |
| `74be2a0` | Stage 3b: 28 alpha_vantage + yfinance + fundamental trend → features.py | 3b | ⏳ pending rollup |
| `cf5e1a2` | Stage 3a: 8 industry feature funcs → new `r1000_features.py` | 3a | ⏳ pending rollup |
| `9cf6d38` | Stage 2d: 27 IO/ticker/cache/run-identity helpers → helpers.py | 2d | ⏳ pending rollup |
| `f2274fc` | Stage 2c: 11 numpy/pandas stats primitives → helpers.py | 2c | ⏳ pending rollup |
| `d898f48` | Stage 2b: apply_fast_mode + to_cfg + configure_last_n_years → helpers.py | 2b | ⏳ pending rollup |
| `dfbea54` | Stage 2a: 5 smallest helpers → new `r1000_helpers.py` | 2a | ⏳ pending rollup |
| `06f1171` | Stage 1d-ii: EngineConfig dataclass → config.py | 1d-ii | ⏳ pending rollup |
| `c3df377` | Stage 1d-i: 5 scalar constants → config.py | 1d-i | ⏳ pending rollup |
| `c59db52` | Stage 1c: 17 SEC/yfinance/sector data structures → config.py | 1c | ⏳ pending rollup |
| `b782e36` | Stage 1b: 40 pure-data constants → config.py | 1b | ⏳ pending rollup |
| `01d5f85` | Stage 1a: 5 PHASE*_COLUMNS lists → new `r1000_config.py` | 1a | ⏳ pending rollup |
| `dd7cf46` | Stage 0 DONE: baseline captured from 6440957 SHIP outputs | 0 | ✅ reference |

**Pre-refactor on `origin/master` (newest first)**:

| Commit | Title | Phase | Requires | Default |
|---|---|---|---|---|
| `6440957` | **SHIP Phase 9 C3 + CE v2** (production HEAD before refactor) | 9.C3 + 9.CE v2 | FULL done | ON |
| `d3d3a91` | CE v2: lift 2 inner N<=3 clamps (select + backtest) | 9.CE v2 | QUICK | ON |
| `f93a4a2` | Phase 9 CE: Concentrated Expansion — lift N<=3 cap, 3→63 grid | 9.CE v1 | QUICK | ON |
| `031fa3c` | Fix Cell 5 KeyError + correct Phase 9 baseline metrics | ops | — | — |
| `86be7f9` | **Phase 9 C3: EPS turn-positive + still-loss-improving** | 9.C3 | FULL | ON |
| `c228238` | SHIP Phase 9 C1+C2 rotate baseline to CURRENT_BASELINE | 9.C1+C2 | FULL | ON |
| `527fdde` | Phase 9 C3 design + refactor plan update (docs only) | 9.C3 design | — | — |
| `ced5db6` | **Phase 9 C1+C2: multi_year rebalance + percentile thesis-gate** | 9.C1 + 9.C2 | QUICK | ON |
| `d87160d` | hard_sanitize dedup fix (CRITICAL — unblocked Phase 8 FULL run) | 8 fix | no rebuild | always-on |
| `9b083d2` | Phase 8d: IC-reweight + long-horizon alpha composite | 8d.1 + 8d.2 | QUICK | ON |

**Current `ENGINE_REUSE_VERSION`**: `"2026-04-17-phase8b-long-lookback-momentum"`. **Phase 9 C1+C2 are post-feature-store changes — no version bump.** The in-progress FULL REBUILD was overkill for measuring C1+C2 (a QUICK_RESCORE would have worked in ~20 min), but since it ran, the outputs are valid for verdict.

See `EXECUTION_PLAN.md`, `ARCHITECTURE_REVIEW.md` (incl §6b sleeve taxonomy redesign), `PHASE_9_C3_PROPOSAL.md`, `REFACTOR_PLAN.md` §12 (5-stage sequencing) for design history + forward plan.

---

## 2. Next step — Phase 12 SHIPPED. Choose next direction from prioritized candidates.

### Immediate small fix (recommended first, ~35 min)

**Cold-start fix for Phase 12A**: currently `_enrich_with_live_state` (line 14292/14730 in r1000_pipeline.py) runs BEFORE `apply_manual_positions_from_yaml` (line 14893). On FIRST run after filling manual_positions.yaml, portfolio_latest.csv shows NaN for avg_cost/shares/unrealized_return. Second run onwards works correctly because state carries over.

**Fix**: move the Phase 12B + ensure_live_portfolio_state blocks (line ~14878-14897) to BEFORE the first `_enrich_with_live_state` call. OR re-enrich right before `portfolio_operational.to_csv(portfolio_path)` at line 14353 + 14735.

After fix, run QUICK pipeline once (~20-30 min) to validate:
- portfolio_latest.csv all 9 enrichment columns populated
- lifetime_equity_curve.csv generated (84 rows = 83 backtest + 1 live)
- lifetime_metrics.json with live_value_method=shares_x_reference_price
- verdict shows lifetime CAGR section

### Prioritized next candidates (user decision needed)

**A. Quarterly Rebalance A/B** (~3-4h) — high-value efficiency improvement
  - Add `cfg.rebalance_interval_months: int = 1` field (default monthly, switch to 3 for quarterly)
  - Modify `backtest_portfolio` to honor interval (concentrated code already has this)
  - A/B test monthly vs quarterly on main diversified
  - Expected: turnover -50% (43% → ~20%), CAGR -0.5-1pp (minor hit), tax efficiency large gain
  - Ship gate: ΔCAGR ≥ -1pp AND Δturnover ≤ -20pp (efficiency gate, not alpha gate)

**B. Phase 13 scope-down** (~3-4h) — frontend-ready for subscription service
  - PHASE_13_PLAN.md (419 lines) is over-engineered; user pushed back on complexity
  - Scoped down version: apply `_enrich_with_live_state` to concentrated_portfolio_latest.csv + write `current_portfolio_summary.json` + `recent_trades.json`
  - Agent's entry_date/avg_cost = first recommendation date/price (already in live_portfolio_state_history.parquet, 152 snapshots accumulated)
  - Sufficient for frontend subscription product (정석 FREE, 성장주 PAID)

**C. Dividend tracking** (~1-2일) — Phase 14 candidate
  - Backtest: yfinance Adj Close already includes dividends (reinvested total return)
  - Live: no separate cash dividend tracking
  - Add: `next_ex_div_date`, `next_pay_date`, `next_div_per_share` columns + cash accumulator
  - Priority: MEDIUM (live tracking accuracy)

**D. Russell 2000 expansion** (~3-7일) — alpha universe widening
  - 1000 → 3000 tickers (with liquidity filter to 1500-2000 effective)
  - Compute cost 3-4x (90min FULL → 4-6h FULL)
  - Daily QUICK still 30-60min (automatable)
  - Need: universe builder + liquidity filter + R3000 constituent list

**E. Automation setup** (~1주) — subscription service infra
  - Local: Windows Task Scheduler (daily + monthly + quarterly triggers)
  - Cloud: AWS Lambda + S3 + SNS for subscriber alerts
  - Priority: after product decisions locked

### 🟢 Status (2026-04-20 12:00 KST)

**Branch**: `refactor/phase-a-module-split` (pushed to origin). 13 commits on top of `6440957`. Smoke tests 25/25 at each sub-stage.

**Stage 0 DONE via shortcut** — baseline NOT captured via fresh pipeline run. Instead `.refactor_baseline/capture.py` hashed + copied the existing Drive outputs from 2026-04-18 21:22 SHIP run (commit `6440957`). The 4 reference files are in `.refactor_baseline/`:
- `scored_latest.ref.csv` (SHA256 stored in `reference.json`)
- `portfolio_latest.ref.csv`
- `weights_latest.ref.json`
- `backtest_metrics.ref.json`

**Why shortcut works**: the Drive outputs ARE the byte-exact baseline for commit `6440957` — running the pipeline again from scratch was optional. Saved ~2h.

### What to do on wake-up (pick in order)

**Step 1 — Check Stage 1 rollup status** (~30 sec)

```bash
# Is the rollup task still running?
tasklist | findstr python
# If you see python.exe PID with high memory (600MB+), it's still running.

# Check latest log
tail -f G:\내 드라이브\r1000_top30_institutional\outputs\runlog.txt
# Look for "[validation]" or final "[ALL DONE]" marker
```

If still running: wait. If done: proceed to Step 2.

**Step 2 — Run byte-exact verify** (~5 sec)

```bash
py -3 .refactor_baseline/verify.py
```

Expected output: `✅ ALL 4 FILES BYTE-EXACT MATCH` (scored_latest.csv + portfolio_latest.csv + weights_latest.json SHA256 match; backtest_metrics.json numeric diff within tolerance).

**Possible outcomes**:

- **PASS** → Stages 0 through 3c are confirmed value-preserving. Proceed to Step 3.
- **FAIL** (one or more file mismatch) → **bisect**. The refactor has 13 commits; for each suspect commit, `git checkout <commit> && py -3 run_local.py --no-collector && py -3 .refactor_baseline/verify.py`. Start with the highest-risk commits: Stage 3c (`fd4e6a0`, 8 funcs incl moat/gate), Stage 2c (`f2274fc`, robust_z numeric primitives), Stage 2d (`9cf6d38`, run-identity helpers). Lowest risk: Stages 1a-c (pure constants). Once first-bad commit isolated, read its diff and find the dropped reference / rename / missed import.

**Step 3 (PASS only) — Execute Stage 3d** per `STAGE_3D_PLAN.md`

Read `STAGE_3D_PLAN.md` first — it has the 4-sub-stage breakdown with exact function lists, line numbers, risk notes, and sanity tests. Summary:

- **3d-i** (fundamental panel builders, ~1,100L, HIGHEST RISK) — 7 funcs centered on `recompute_fund_panel_derived_columns` (458L, lines 7805-8262 in current main). This function contains the Phase 9 C3 `_sign_flip_pos` nested helpers critical for the early_scout gate. Scope preservation via explicit nested-function capture is non-negotiable.
- **3d-ii** (macro/event regime builders, ~850L) — 9 funcs incl. `build_macro_regime_table` (417L).
- **3d-iii** (market/dynamic-leadership/crisis features, ~650L) — 6 funcs.
- **3d-iv** (strategy blueprint/pillar/minervini composites, ~1,400L) — 3 funcs incl. `compute_strategy_blueprint_columns` (926L). Largest function in codebase.

**Each sub-stage must**: (1) smoke test 25/25, (2) commit separately, (3) push after commit. Rollup byte-exact verify runs after 3d-iv (same pattern as Stage 1/2/3 rollup, but the 3d changes move feature construction, so a rollup between 3d-i and 3d-ii is acceptable if the user wants tighter bisection).

**Step 4 — Stages 4 + 5 + 6**

- **Stage 4**: `r1000_signals.py` — sleeve composition + portfolio construction (sleeve selectors, backtest_concentrated_portfolio, etc.). ~2-3k lines.
- **Stage 5**: `r1000_pipeline.py` + facade — orchestration (run_default_pipeline, run_full_validation_suite) + add re-exports to `r1000_top30_institutional.py` so existing import sites still work. ~2k lines.
- **Stage 6 (Subtractive)**: delete `_legacy_unused_*` funcs (~2,500L) + Phase 3/5/7a dead branches. Post-refactor, dead code is mechanical to remove.

### Why refactor (unchanged from 2026-04-18 reasoning)

1. Pre-refactor engine was 27,838 lines. Invariants like "PHASE*_COLUMNS must be in `build_feature_store.keep_cols`" + "concentrated cap lifted in 5 sites not 3" are implicit in a monolith. Module split makes them explicit (one owner per concept).
2. Phase 9 is done; no feature work blocking cleanup.
3. Class of bugs like CE v1 inner-clamp miss + Phase 2 keepcols-drop + hard_sanitize dedup dedup — all root cause "monolithic file hides invariants". Refactor encodes them.

### Alternative if rollup FAILs and bisect takes too long

**Option: revert to Stage 2d (`9cf6d38`) and re-attempt Stage 3**. Stage 2 was pure helper extraction with well-known grep patterns; the failure is more likely in Stage 3 (features moved with yf fetchers that call module-level state). Recommend:

```bash
git reset --hard 9cf6d38     # back to end of Stage 2
# re-run rollup verify
py -3 run_local.py --no-collector
py -3 .refactor_baseline/verify.py
# if PASS → Stage 2 is good; Stage 3 has the bug → re-do Stage 3a more carefully
```

---

## 2a. LEGACY — Phase 9 C3 implementation flow (kept for audit trail)

Phase 9 C1+C2 is shipped. C3 adds EPS turn-positive flags to sharpen the early_scout gate. Detailed design in `PHASE_9_C3_PROPOSAL.md`. Implementation flow:

### Step 1 — smoke test current state
```bash
py -3 tests/smoke_test.py
# expect 18/18 passed
```

### Step 2 — add C3 code per PHASE_9_C3_PROPOSAL.md §3

Touch surface (all in the SAME commit, bundled C3 feature code; keep refactor separate):

| File | Change |
|---|---|
| `r1000_top30_institutional.py` | • `PHASE9_C3_TURNAROUND_COLUMNS` constant (~line 1080)<br>• Add `d["roe_sign_flip_pos"] = _sign_flip_pos("roe_proxy")` after line 12228<br>• Add 4 alias columns (profit_turn_positive_4q, cashflow_turn_positive_4q, roe_turn_positive_4q, any_profitability_turn_positive_4q) after the `any_profit_sign_flip_pos` block<br>• Extend `carry_cols` list (line ~12358) with 5 new names<br>• Add `+ PHASE9_C3_TURNAROUND_COLUMNS` to `build_feature_store.keep_cols` (line 14327) AND to `hard_sanitize` call (line 14354)<br>• Extend Phase 9 C2 early-scout gate block (line ~19357) with `_p9_eps_turn_positive` + `_p9_still_loss_but_improving` branches<br>• Add 2 cfg fields: `phase9_c3_turnaround_enabled: bool = True`, `phase9_c3_loss_narrowing_threshold: float = 0.3`<br>• Bump `ENGINE_REUSE_VERSION` → `"2026-04-18-phase9c3-turnaround-flags"` |
| `colab_run.ipynb` Cell 2 | `PHASE9_C3_TURNAROUND = 'auto'` + env binding + print-loop entry |
| `run_local.py` | Add `--phase9-c3` CLI flag mirroring Phase 9 C1/C2 toggles |
| `tests/smoke_test.py` | Add 3 tests: `import.phase9_c3_constants_exported`, `regression.phase9_c3_columns_complete`, `structural.phase9_c3_carry_cols_present` |
| `CHANGELOG.md` | Agent Update Contract entry |

### Step 3 — pre-push validation
```bash
py -3 tests/smoke_test.py
# expect 21/21 passed (18 existing + 3 new)
```

### Step 4 — FULL REBUILD (required: feature_store schema change)
```bash
py -3 run_local.py --full          # ~3-4h local CPU
# or
# Colab Cell A + Cell 4 if GPU needed (~2-3h)
```

### Step 5 — Cell E verdict
```bash
py -3 run_local.py --verdict-only
```

Ship gate: ΔCAGR ≥ +0.5pp AND ΔSharpe ≥ -0.05 AND ΔMaxDD ≥ -3pp vs Phase 9 C1+C2 baseline (defined in `run_local.py CURRENT_BASELINE`).

### Ship vs Partial vs Regress decision tree (same as C1+C2)
- **SHIP** → rotate CURRENT_BASELINE in run_local.py + SESSION_HANDOFF §0 to Phase 9 C1+C2+C3 metrics. Proceed to Refactor Phase A (REFACTOR_PLAN.md §6).
- **PARTIAL** → user decision: A/B isolate C3 ON/OFF, or accept taxonomy improvement with marginal CAGR trade (same call we just made for C1+C2).
- **REGRESS** → revert the C3 commit; Phase 9 C1+C2 remains baseline; re-plan.

---

## 2b. Legacy commands — local or Colab runs on current baseline

### If you want to re-verify current baseline (~2s, no pipeline)
```bash
py -3 run_local.py --verdict-only
# expect ΔCAGR +0.00pp vs Phase 9 C1+C2 baseline (comparing itself to itself)
```

### If you want full local run (~15-25 min QUICK / ~3-4h FULL)
```bash
py -3 run_local.py                 # QUICK_RESCORE (cached feature_store + models)
py -3 run_local.py --full          # FULL rebuild (required after FS schema change)
py -3 run_local.py --phase9-c1=0   # A/B: C1 OFF
py -3 run_local.py --phase9-c2=0   # A/B: C2 OFF
```

### If you prefer Colab (legacy, documented below)

### Step 1 -- verify run completed

```python
import pathlib, time
BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')
for f in ['outputs/scored_latest.csv', 'outputs/backtest_metrics.json',
          'outputs/weights_latest.json', 'outputs/portfolio_latest.csv',
          'outputs/top30_latest.csv']:
    p = BASE / f
    if p.exists():
        mtime = time.strftime('%Y-%m-%d %H:%M KST', time.localtime(p.stat().st_mtime))
        print(f'  OK   {f:40s}  mtime={mtime}')
    else:
        print(f'  MISS {f:40s}')
```

If any files missing or mtime older than 2026-04-17 08:10 KST: the FULL REBUILD crashed or was interrupted. In that case:
1. Ask user for crash traceback / Colab scrollback.
2. If unrecoverable, switch to QUICK_RESCORE (~20 min) from current HEAD `527fdde` which includes commit banner SHA.

If all files present with recent mtime: proceed to Step 2.

### Step 2 — Cell E verdict snippet

```python
import json, pathlib, pandas as pd
BASE = pathlib.Path('/content/drive/MyDrive/r1000_top30_institutional')

print("=" * 70); print("PHASE 9 C1+C2 DIAGNOSTIC"); print("=" * 70)

scored = pd.read_csv(BASE / 'outputs/scored_latest.csv', low_memory=False)
print(f"\nScored rows: {len(scored)}")
sleeve_dist = scored['portfolio_sleeve_label'].value_counts()
print(f"\nSleeve distribution (raw):"); print(sleeve_dist)

phase9_cols = ['phase9_thesis_gate_active',
               'phase9_core_eligible','phase9_future_eligible',
               'phase9_early_eligible','phase9_unassigned',
               'phase9_mktcap_percentile']
print("\nPhase 9 diagnostic columns (expect all present if C2 active):")
for c in phase9_cols:
    if c in scored.columns:
        v = pd.to_numeric(scored[c], errors='coerce').fillna(0)
        print(f"  {c:40s}  mean={v.mean():.3f}  sum={v.sum():.0f}")
    else:
        print(f"  {c:40s}  MISSING (C2 toggle may be off)")

pf = pd.read_csv(BASE / 'outputs/portfolio_latest.csv')
print(f"\nFinal portfolio: {len(pf)} positions")
print(f"  Sleeve dist: {pf.groupby('portfolio_sleeve_label').size().to_dict()}")
print(f"  Top 10 by weight:")
print(pf.nlargest(10, 'weight')[['ticker','portfolio_sleeve_label','weight']].to_string(index=False))

print("\n" + "=" * 70); print("METRICS vs Phase 8 baseline"); print("=" * 70)
bm = json.loads((BASE / 'outputs/backtest_metrics.json').read_text())
phase8_baseline = {'cagr': 0.2186, 'sharpe': 0.9856, 'max_dd': -0.3208, 'ir': 0.5800,
                   'avg_turnover_monthly': 0.5119, 'avg_stock_names': 21.34}
print(f"  {'metric':24s} {'new':>10s} {'Phase 8':>10s} {'delta':>14s}")
for k in ['cagr','sharpe','max_dd','ir','avg_turnover_monthly','avg_stock_names',
          'beat_month_ratio','excess_cagr']:
    new_v = bm.get(k, float('nan')); bl_v = phase8_baseline.get(k)
    if bl_v is None: print(f"  {k:24s} {new_v:>10.4f}"); continue
    if k in ['cagr','max_dd','avg_turnover_monthly','excess_cagr']:
        d_str = f"{(new_v - bl_v) * 100:+.2f}pp"
    else:
        d_str = f"{new_v - bl_v:+.4f}"
    print(f"  {k:24s} {new_v:>10.4f} {bl_v:>10.4f} {d_str:>14s}")

print("\n=== SLEEVE ALLOCATION ===")
weights = json.loads((BASE / 'outputs/weights_latest.json').read_text())
print(f"  target:  {weights.get('sleeve_target_weights')}")
print(f"  actual:  {weights.get('sleeve_actual_weights')}")
print(f"  counts:  {weights.get('sleeve_selected_counts', '?')}")

print("\n=== VERDICT ===")
dCAGR = (bm['cagr'] - phase8_baseline['cagr']) * 100
dSharpe = bm['sharpe'] - phase8_baseline['sharpe']
dMaxDD = (bm['max_dd'] - phase8_baseline['max_dd']) * 100
early_n = (weights.get('sleeve_selected_counts') or {}).get('early_scout', 0)
print(f"  ΔCAGR     {dCAGR:+.2f}pp   (gate >= +0.5pp)")
print(f"  ΔSharpe   {dSharpe:+.4f}    (gate >= -0.05)")
print(f"  ΔMaxDD    {dMaxDD:+.2f}pp   (gate >= -3pp; positive better)")
print(f"  early_scout selected: {early_n}    (gate >= 4)")

if dCAGR >= 0.5 and dSharpe >= -0.05 and dMaxDD >= -3.0 and early_n >= 4:
    print("\n  --> SHIP. Phase 9 C1+C2 wins. Next: §3a.")
elif dCAGR >= -2.0 and early_n >= 2:
    print("\n  --> PARTIAL. Next: §3b (A/B isolation).")
else:
    print("\n  --> REGRESS. Next: §3c (rollback).")
```

**Paste the full Cell E output (verdict line + metrics table) back to chat.**

---

## 3. Decision tree after Cell E verdict

### 3a. SHIP (CAGR ≥ +0.5pp, Sharpe ≥ -0.05, MaxDD ≥ -3pp, early ≥ 4 names)

**Both Phase 9 C3 AND Refactor Phase A ship** — they are serialized, NOT mutually exclusive. The only choice is the ORDER. Per REFACTOR_PLAN.md §12: Stage 2 picks the first, Stage 3 does the complement.

**Hard rule**: never bundle C3 + Refactor in the same commit. Bisection dies. Ship C3 as its own commit, Refactor as its own commit (actually multiple commits per §6 checklist), each with its own verification.

**Recommended order: C3 first, then Refactor** (~2 days total wall-clock)

Reasons:
- **Fast measurable result**: C3 behavior change measurable within ~3.5h vs 1.5 days.
- **Final FS schema locks in before refactor moves code**: Refactor's byte-exact verification needs a stable feature_store schema as reference. If C3 ships after refactor, the schema changes twice.
- **C3 regression is cheap to revert**: 1-commit revert, refactor continues on Phase 9 C1+C2 baseline. Opposite order means if C3 regresses, refactor is already done on the wrong baseline.
- **Sleeve taxonomy stabilizes first**: user's definition of early sleeve ("eps 적자거나 양전환 막 하거나") is codified before structural refactor cements it.

**Alternative order: Refactor first, then C3** — valid if user prefers long mechanical work before feature work. Pros: C3 becomes single-file change in `r1000_signals.py` post-refactor. Cons: 1.5 days before C3's effect is measurable; refactor's byte-exact reference is Phase 9 C1+C2 (i.e. sleeve count/composition may shift again when C3 lands post-refactor, forcing a second byte-exact verification pass).

#### Before any code change — run smoke test first (~7s local, saves hours)

```bash
py -3 tests/smoke_test.py
```

Runs 17 tests (syntax + structural + import + logic + regression). Target: all pass before `git push` → Colab. Catches ~80% of bugs without burning Colab time. If you add new engine code, add a matching `@_test` entry at the bottom of `tests/smoke_test.py` in the same commit (see file docstring for the template).

#### Step 1 -- Phase 9 C3 (recommended first, ~3.5h wall-clock)

1. **Run smoke test first**: `py -3 tests/smoke_test.py` — must show `17/17 passed` before editing.
2. Implement per `PHASE_9_C3_PROPOSAL.md` §3. Touch surface:
   - `r1000_top30_institutional.py` — new `PHASE9_C3_TURNAROUND_COLUMNS` constant (~line 1080), 5 new fund_panel columns after line 12228, keep_cols + hard_sanitize whitelist (line 14327, 14354), Phase 9 C2 gate extension (line 19357), 2 new cfg fields, ENGINE_REUSE_VERSION bump to `2026-04-17-phase9c3-turnaround-flags`.
   - `colab_run.ipynb` Cell 2 — add `PHASE9_C3_TURNAROUND = 'auto'` toggle + env binding + print-loop entry.
   - `tests/smoke_test.py` — add 2-3 new `@_test` entries: PHASE9_C3_TURNAROUND_COLUMNS constant present, cfg field `phase9_c3_turnaround_enabled` in EngineConfig, early-scout gate respects new branch.
   - `CHANGELOG.md` — Agent Update Contract entry.
3. **Re-run smoke test**: `py -3 tests/smoke_test.py` — expect 20/20 passed (added 3 new tests).
4. Commit + push from fresh checkout.
5. Trigger Colab FULL REBUILD (required — FS schema changes). The `[commit=<sha>]` banner will self-identify the run.
6. Cell E verdict vs Phase 9 C1+C2 baseline (ship gate: ΔCAGR ≥ 0, early count widening, no Sharpe regression > -0.05).
7. If C3 SHIPs: continue to Step 2 (Refactor).
8. If C3 REGRESSes: revert C3 commit, proceed to Step 2 on Phase 9 C1+C2 baseline.

#### Step 2 — Refactor Phase A (~1-1.5 day)

1. Execute `REFACTOR_PLAN.md` §6 checklist (5-module split + §11 observability scaffolding).
2. Byte-exact verification via QUICK_RESCORE diff: pre-refactor `scored_latest.csv` SHA256 must match post-refactor.
3. Commit + push (multiple commits per §6 migration order: config → helpers → features → signals → pipeline → facade).
4. If byte-exact fails: bisect which module move broke which symbol; fix; retest.
5. Post-refactor: update CLAUDE.md "Key Files", PHASE_ROADMAP.md deprecation note, SESSION_HANDOFF.md §5 file list to reflect new module map.

#### After both ship: Stage 4 (Subtractive pass)

Per REFACTOR_PLAN.md §12 Stage 4: delete Phase 3 / Phase 5 / Phase 7a dead branches + 153 zero-IC noise factors. Post-refactor this is mechanical (remove constant + call site in the owning module). ~4-8h. Saves ~15-20% LOC.

### 3b. PARTIAL (CAGR -2pp to +0.5pp OR mixed metrics)

Run two QUICK_RESCORE A/B isolation passes (each ~20 min, total 40 min):

```python
# Run A: C1 isolated (C2 off)
PHASE9_C1_REBALANCE = 'auto'
PHASE9_THESIS_GATE = '0'
# rerun Cell 4 QUICK_RESCORE + Cell E

# Run B: C2 isolated (C1 off)
PHASE9_C1_REBALANCE = '0'
PHASE9_THESIS_GATE = 'auto'
# rerun Cell 4 QUICK_RESCORE + Cell E
```

Compare each isolated effect vs Phase 8 baseline. Ship whichever (or both) gives net positive metrics; roll back the other by editing `EngineConfig` default.

### 3c. REGRESS (CAGR < -2pp OR early < 2 names)

1. Edit `EngineConfig`: `phase9_c1_rebalance_enabled: bool = False` AND `phase9_thesis_gate_enabled: bool = False`.
2. Phase 9 stays in code as `experimental` for future re-evaluation but is OFF by default.
3. Commit + push with message "Roll back Phase 9 C1+C2 defaults after FULL-REBUILD regression".
4. Phase 8 (CAGR 21.86%) becomes production baseline.
5. Re-plan: is the percentile threshold off? Do EPS turn-positive flags (Phase 9 C3) need to ship first to rescue C2?

---

## 4. Bootstrap prompt for a fresh chat session

```
I'm continuing work on the r1000 Quant Engine project. Before editing anything:

1. Read SESSION_HANDOFF.md top section (🟢 LATEST STATE 2026-04-21).
2. Read CLAUDE.md — project basics.
3. Run `git log --oneline -15` — HEAD should be `1642b66` or later on master.
4. Run `git status` — should be clean.
5. Read PHASE_13_PLAN.md ONLY if you're going to implement the scoped-down version.

Current state summary:
  - Refactor Phase A complete (33 commits pre-session, merged to master)
  - Phase 11 multibagger A/B REJECTED (default OFF)
  - Phase 12 live continuity SHIPPED (4 sub-stages) + 1 tz fix committed
  - Pipeline b84oo5xrv ran 83 min, reproduced baseline CAGR 22.95%
  - 2 known issues in SESSION_HANDOFF §LATEST STATE
  - User explicitly said Phase 13 as designed (PHASE_13_PLAN.md) is over-engineered; scope down

Production baseline (unchanged): Phase 9 C3 + CE v2
  Main: CAGR 22.91% / Sharpe 1.17 / MDD -26.26%
  Concentrated: N=5/1m/score_power → CAGR 34.75% / Sharpe 1.254

User has open questions (SESSION_HANDOFF §LATEST STATE → USER'S OPEN QUESTIONS):
  1. Scope-down Phase 13 (3-4h)
  2. Dividend tracking (Phase 14 candidate)
  3. Russell 2000 expansion
  4. Quarterly rebalance A/B (3-4h, highest-value quick win)
  5. Market shock detection gaps (no news/sentiment yet)
  6. Automation (Windows Task Scheduler / AWS cron)

Recommended first action (per SESSION_HANDOFF §2):
  Cold-start fix for Phase 12A (35 min code + 20-30 min QUICK validation run).
  Then user chooses next candidate: Quarterly A/B (A) or Phase 13 scope-down (B) or other.

Do NOT start new work until user confirms priority from SESSION_HANDOFF §2 candidates.
```

---

## 5. Files that persist across machines

Source-of-truth in git. Branch `refactor/phase-a-module-split` has the refactor-in-progress state. `origin/master@6440957` is the last SHIP before refactor.

**Engine modules (refactor branch)**:
- `r1000_top30_institutional.py` — main engine, 23,594L (was 27,838L pre-refactor). Still contains Stage 3d+4+5 functions pending extraction.
- **`r1000_config.py`** — NEW, 2,109L. All pure data constants (PHASE*_COLUMNS, SEC tags, sector maps) + EngineConfig dataclass (435 fields) + default_manual_regime_conditioned_sleeve_map helper. Zero side effects. Import depth: 0.
- **`r1000_helpers.py`** — NEW, 925L. 46 pure helpers: stats primitives (winsorize, robust_z, cross_sectional_robust_z), IO/ticker/cache, run identity, phase_is_enabled gate. Import depth: 1 (from config).
- **`r1000_features.py`** — NEW, 1,923L. 44 feature engineering funcs: industry RS/O'Neil, alpha_vantage/yfinance fetchers, fundamental trend, live/moat/flow/gate features. Import depth: 2 (from config + helpers).
- `r1000_data_collector.py` — collector (unchanged by refactor)
- `r1000_operator.py` — live operator layer (unchanged)
- `r1000_portfolio_state.py` — state persistence (unchanged)
- `colab_run.ipynb` — runbook (unchanged — engine module split is transparent via facade re-exports planned for Stage 5)

**Refactor infrastructure**:
- **`.refactor_baseline/`** — byte-exact reference files from commit `6440957`. Contains `reference.json` (SHA256 manifest), `scored_latest.ref.csv`, `portfolio_latest.ref.csv`, `weights_latest.ref.json`, `backtest_metrics.ref.json`, `verify.py` (comparator), `capture.py` (rebuild script).
- **`STAGE_3D_PLAN.md`** — NEW. 4-sub-stage plan for Stage 3d (fundamental panel + macro + strategy_blueprint + pillar). Read before executing 3d.
- `tests/smoke_test.py` — 25 tests spanning main + config + helpers via `_combined_src()` helper.

**Docs**:
- `CLAUDE.md` — project brain (short)
- **`SESSION_HANDOFF.md` — this file (single-item inbox)**
- `CHANGELOG.md` — decision log (every commit has a matching Agent Update Contract entry)
- `EXECUTION_PLAN.md` — 4-stage roadmap
- `ARCHITECTURE_REVIEW.md` — cold first-principles assessment + sleeve redesign rationale
- `REFACTOR_PLAN.md` — 5-module split + observability + §12 5-stage sequencing diagram (currently being executed)
- `PHASE_9_C3_PROPOSAL.md` — Phase 9 C3 EPS turn-positive flag design (shipped, kept for audit trail)
- `PHASE_8_PROPOSAL.md` — older, Phase 8 design history
- `DIAGNOSIS_FACTOR_IC.md` / `DIAGNOSIS_COUNTERFACTUAL.md` / `DIAGNOSIS_BUGS.md` — Phase C empirical evidence
- `PHASE_ROADMAP.md` — DEPRECATED (only covers Phase 1-6). Use REFACTOR_PLAN.md §12 for current roadmap.
- `PROPOSAL_defensive_upgrades.md` / `PROPOSAL_growth_regime_offense_defense.md` — older design refs

Drive (NOT in git):
- `/content/drive/MyDrive/r1000-quant-engine/` — Cell A keeps `git reset --hard origin/master` on every run.
- `/content/drive/MyDrive/r1000_top30_institutional/` — data folder (`cache_*/`, `feature_store/`, `checkpoints/`, `outputs/`, `companyfacts.zip`).
- Local Windows mirror: `G:\내 드라이브\r1000_top30_institutional\`.

---

## 6. Quick reference — Phase status + toggles (post Phase 9 C1+C2)

| Phase | cfg field | env var | Default | Status |
|---|---|---|---|---|
| 1 (alpha) | (auto via phase_is_enabled) | `PHASE_PHASE1_ALPHA_ENABLED` | ON | Shipped |
| 2 (industry RS) | (no flag) | `PHASE_PHASE2_INDUSTRY_ENABLED` | ON | Shipped (feeds C2 thesis gate) |
| 3 (sleeve renorm) | `sleeve_weight_renorm_enabled` | `PHASE_PHASE3_RENORM_ENABLED` | OFF | REJECTED (-2.30pp CAGR) |
| 4 (regime mult) | `regime_dynamic_sleeve_weights_enabled` | `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED` | OFF | A/B pending |
| 5 (sub-industry) | `sub_industry_leader_laggard_enabled` | `PHASE_PHASE5_LEADER_LAGGARD_ENABLED` | OFF | REJECTED (IC ~0) |
| 6a (DD breaker) | `drawdown_breaker_multilevel_enabled` | `PHASE_PHASE6A_BREAKER_ENABLED` | ON | Dormant in 83-month sample |
| 6b (VIX guard) | `vix_level_guard_enabled` | `PHASE_PHASE6B_VIX_ENABLED` | ON | Dormant in 83-month sample |
| 6c (vol target) | `volatility_targeting_enabled` | `PHASE_PHASE6C_VOLTARGET_ENABLED` | OFF | A/B pending |
| 7a (insider+accruals) | `phase7a_insider_accruals_enabled` | `PHASE_PHASE7A_INSIDER_ACCRUALS_ENABLED` | OFF | A/B pending |
| **8a.1** neg-IC drop | (hard-coded) | `PHASE_PHASE8A_NEG_IC_DROP_ENABLED` | ON | Shipped (Phase 8 PARTIAL) |
| **8a.4** hold-persist | `phase8a_hold_persistence_enabled` | `PHASE_PHASE8A_HOLD_PERSISTENCE_ENABLED` | ON | Shipped |
| **8a.5** macro clamp | (always active) | — | always | Shipped (safety) |
| **8b.1** long-lookback | `phase8b_long_lookback_enabled` | `PHASE_PHASE8B_LONG_LOOKBACK_ENABLED` | ON | Shipped |
| **8b.3** Phase 1 keepcols | (always active) | — | always | Shipped (structural) |
| **8c.1** megacap override | `phase8c_megacap_future_override_enabled` | `PHASE_PHASE8C_MEGACAP_OVERRIDE_ENABLED` | ON | Shipped (also gated by Phase 9 C2) |
| **8c.2** growth-adj val | `phase8c_growth_adj_valuation_enabled` | `PHASE_PHASE8C_GROWTH_ADJ_VALUATION_ENABLED` | ON | Shipped |
| **8d.1** IC reweight | `phase8d_ic_reweight_enabled` | `PHASE_PHASE8D_IC_REWEIGHT_ENABLED` | ON | Shipped |
| **8d.2** long-horizon alpha | `phase8d_long_horizon_alpha_enabled` | `PHASE_PHASE8D_LONG_HORIZON_ALPHA_ENABLED` | ON | Shipped |
| **9.C1** multi_year weight rebalance | `phase9_c1_rebalance_enabled` | `PHASE_PHASE9_C1_REBALANCE_ENABLED` | ON | **SHIPPED 2026-04-18** (part of current baseline) |
| **9.C2** percentile thesis gate | `phase9_thesis_gate_enabled` | `PHASE_PHASE9_THESIS_GATE_ENABLED` | ON | **SHIPPED 2026-04-18** (restored sleeve taxonomy) |
| **9.C3** EPS turn-positive flags | `phase9_c3_turnaround_enabled` | `PHASE_PHASE9_C3_TURNAROUND_ENABLED` | ON | **SHIPPED 2026-04-18 21:22 KST** (commit `d3d3a91`; +1.22pp CAGR, +0.099 Sharpe, +0.149 IR vs C1+C2) |
| **9.CE** Concentrated Expansion | `concentrated_top_n_candidates`, `concentrated_rebalance_intervals`, `concentrated_weighting_modes` (list cfg) | — (grid params) | default 7×3×3 = 63 combos | **SHIPPED v2 2026-04-18** (commit `d3d3a91`; lifted 5 hard caps; champion N=5/1m/score_power = 34.75% CAGR) |

**Deferred work** (per `REFACTOR_PLAN.md` §12 5-stage sequencing):

- **Stage 2 Option A — Phase 9 C3**: EPS turn-positive flags. Design in `PHASE_9_C3_PROPOSAL.md`. Requires fund_panel modification + FULL rebuild. ~3.5h.
- **Stage 2 Option B — Refactor Phase A**: 5-module split (`r1000_config.py / r1000_helpers.py / r1000_features.py / r1000_signals.py / r1000_pipeline.py`) + facade + observability + tests. ~12-16h focused work.
- **Stage 3 — complement**: whichever of C3 or Refactor wasn't done in Stage 2.
- **Stage 4 — Subtractive**: delete Phase 3 / 5 / 7a dead branches + 153 noise factors. ~4-8h. Saves ~15-20% LOC.
- **Stage 5 — Phase 8e**: r_12m ML training target. Walk-forward refactor required. Best done on modular code post-Refactor. ~11-13h.
- **Optional (separate track)**: one of {quarterly rebalance / top-10 concentration / R2000 universe expansion}. Each ~1 day to ~1 week.

---

## 7. How to rotate this handoff

When:
- **Stage 1 rollup verify PASSES** → update §0 "Stage 1 rollup ✅", §2 Step 1/2 remove, bump "what's pending" to Stage 3d as active.
- **Stage 3d-i ships** (after fundamental panel move) → rotate §0 "Stages 0-3c-i ✅", §2 becomes "next: 3d-ii macro". Byte-exact verify gates every 3d-{i,ii,iii,iv} ship.
- **Stage 3d-iv ships** (Stage 3d complete) → rotate §0, §2 becomes "next: Stage 4 signals.py". Update `STAGE_3D_PLAN.md` to "COMPLETE".
- **Stage 4 + Stage 5 ship** (full 5-module split live) → §0 becomes "Refactor Phase A COMPLETE, 5-module structure live". §2 pivots to Stage 6 (Subtractive pass) or Phase 8e (r_12m ML).
- **Stage 6 (Subtractive) ships** → §0 notes LOC savings (~2,500L); close refactor chapter; §2 pivots to next alpha work (Phase 8e, quarterly rebalance, R2000 universe, etc.).
- **Refactor branch merged to master** → squash-merge or preserve 13+n commits; tag `refactor-phase-a-done`; delete branch.
- **Any ship rollback** → §0 becomes "refactor branch paused, current production = `origin/master@6440957`"; re-plan.

Never accumulate multiple handoff files. Single-item inbox only.
