# Integrated AlphaOps Preflight - 2026-05-07

Status: pre-result analysis for run `25481291492` on branch
`codex/leader-rescue-stale-trim`, commit `eb99c97`.

This note exists so the next step after the full rebuild is mechanical:
inspect the exact artifacts below, classify the result as bug/strategy/gate
decision, and only then decide whether Main v2 / monster lifecycle /
opportunity swap can be promoted beyond research.

## Current Backup Anchor

- branch backup: `codex/backup-leader-rescue-stale-trim-20260507-eb99c97`
- tag backup: `backup/leader-rescue-stale-trim-20260507-eb99c97`
- protected commit: `eb99c97`

## Current Run To Evaluate

- GitHub Actions run: `25481291492`
- branch: `codex/leader-rescue-stale-trim`
- commit: `eb99c97`
- important input: `leader_rescue_mode=latest_only`
- purpose: evaluate style-aware Main v2 plus opportunity replacement scoring.

## Production vs Research Boundary

Production path:

- `run_local.py`
- `r1000_pipeline.py`
- `r1000_config.DEFAULT_FEATURES`
- `outputs/backtest_metrics.json`
- `outputs/portfolio_latest.csv`
- `outputs/concentrated_backtest_metrics.json`
- `outputs/concentrated_portfolio_latest.csv`

Research/challenger path:

- `r1000_main_v2.py`
- `tools/run_main_v2_backtest.py`
- `tools/run_monster_lifecycle_replay.py`
- `tools/run_concentrated_policy_replay.py`
- `tools/run_position_aware_risk_replay.py`
- `tools/run_alpha_sprint_backtest.py`
- `tools/run_historical_trade_journey.py`
- `tools/run_winner_lifecycle_reports.py`
- `tools/run_leader_drop_diagnostics_sidecar.py`
- `tools/run_macro_policy_engine.py`
- `tools/auto_policy_challenger.py`
- `tools/auto_policy_proposal.py`
- `tools/auto_policy_promote.py`

Research artifacts must not be used as production proof unless they are backed
by historical replay, same-run baseline comparison, cost sensitivity, and
stress-window checks.

## Result Artifacts To Inspect First

Core production:

- `outputs/backtest_metrics.json`
- `outputs/concentrated_backtest_metrics.json`
- `outputs/scored_latest.csv`
- `outputs/portfolio_latest.csv`
- `outputs/concentrated_portfolio_latest.csv`
- `outputs/reports/candidate_replay_book.csv`

Research/challenger:

- `outputs/main_v2_backtest/metrics.json`
- `outputs/main_v2_backtest/monthly_holdings.csv`
- `outputs/main_v2_backtest/monthly_returns.csv`
- `outputs/monster_lifecycle_replay/metrics.json`
- `outputs/monster_lifecycle_replay/monthly_holdings.csv`
- `outputs/concentrated_policy_replay/metrics.json`
- `outputs/position_aware_risk_replay/metrics.json`
- `outputs/alpha_sprint_backtest/metrics.json`
- `outputs/historical_trade_journey/*`
- `outputs/leader_drop_diagnostics/*`
- `outputs/macro_policy_engine/*`
- `outputs/portfolio_goal_search/*`
- `outputs/auto_learning_v2/*`

## Questions The Result Must Answer

1. Did production main remain strong?
   - CAGR should stay near or above the previous high-quality run.
   - MaxDD should not materially degrade.
   - Cash drag should be explained, not accidental.

2. Did Main v2 actually improve the decision problem?
   - Compare Main v2 historical CAGR/Sharpe/MaxDD/turnover vs same-run legacy main.
   - Confirm it uses historical candidate replay, not latest snapshot only.
   - Inspect monthly holdings for real early entries into new leaders.

3. Did opportunity replacement reduce stale-leader drag?
   - Check PLTR/NVDA-style stale leaders for trim/exit evidence.
   - Check AMD/INTC/STX/SNDK-like candidates for inclusion or explicit exclusion reasons.
   - If excluded, classify why: sector cap, score gap, liquidity, stale gate, risk block, missing data.

4. Did monster lifecycle catch early leaders without overfitting?
   - Confirm no hardcoded ticker path.
   - Confirm minimum market-cap/liquidity filters are active.
   - Confirm scout -> confirm -> winner -> monster weights are staged, not one-shot.
   - Confirm shake-out protection does not hold true distribution too long.

5. Did concentrated recover valid metrics?
   - `concentrated_backtest_metrics.json` must not contain NaN for CAGR/Sharpe/MaxDD.
   - Latest concentrated portfolio should not collapse to one accidental holding unless policy says so.
   - Single-name cap and normal/max mode must be visible in reports.

6. Did auto-learning produce executable challenger evidence?
   - It may propose rules.
   - It must not silently promote production defaults.
   - It should reference replay evidence and blocked reasons.

7. Did the macro policy layer identify regime-speed problems?
   - Inspect `outputs/macro_policy_engine/regime_speed_audit.csv`.
   - Look for late risk alerts, balanced-under-drawdown months, premature growth re-entry, and possible cash drag.
   - A good candidate should have fast defense, slow re-entry, and lower cash drag after confirmation.

## Promotion Gates

Main v2 can be promoted only if all are true:

- CAGR >= legacy main + 2 percentage points, or same CAGR with materially lower MaxDD.
- MaxDD no worse than legacy by more than 1 percentage point.
- Sharpe no worse than legacy.
- Average monthly turnover not materially excessive after 50 bps cost.
- Stress windows do not hide a large crash.
- Missed leader count decreases.
- Stale leader overweight count decreases.

Monster lifecycle can be promoted only if:

- It improves CAGR without worsening MaxDD beyond the gate.
- It shows staged entries into real historical winners.
- It exits true distribution earlier than legacy.
- It does not rely on tiny market-cap lottery names.

Auto-learning can be promoted only as proposal/challenger generation unless:

- A generated policy has historical replay results.
- A human-reviewed promotion file is produced.
- Tests and audit pass.

## If Result Is Good

1. Save the result as a baseline artifact.
2. Add a changelog/session note with exact run id and metrics.
3. Keep production defaults unchanged unless gates pass.
4. If gates pass, open a separate promotion branch from the backed-up commit.
5. Promote only the smallest path: likely Main v2 challenger first, not all sidecars.

## If Result Regresses

Classify before editing:

- Code/config bug: NaN metrics, missing candidate book, wrong output path, cache/stale data issue.
- Strategy regression: CAGR drops but artifacts are valid.
- Data coverage problem: missing tickers, market-cap/currency issue, stale fundamental/event data.

Only bug/config/data problems should be patched immediately. Strategy regressions
should produce the next A/B hypothesis, not blind weight tuning.

## Likely Next Code Work After Result

- Add leader-miss attribution summary if missing from artifacts.
- Make Main v2 monthly holdings explain each inclusion/exclusion reason.
- Add sector-cap pressure and replacement-candidate pressure to holdings output.
- Add stale-leader half-trim then full-exit A/B as research-only policy.
- Add production-compatible concentrated metrics guard if NaN recurs.
- Feed winner/loss/stale diagnostics into auto-policy challenger evidence.
- Use `macro_policy_engine/macro_policy_by_month.csv` as the research-only control table for the next Main v2 macro-policy challenger.
