# AutoLearning Policy Challenger Report

This report evaluates the candidate policy gates. It does not apply the policy to production.

- Policy version: `2026-05-alphaops-20260510-v1`
- Status: `blocked`
- Approved for promotion: `False`
- Hard failures: 11

## Gate Matrix

| Gate | Check | Severity | Passed | Observed | Threshold |
| --- | --- | --- | --- | --- | --- |
| schema | policy_valid | hard | True | `[]` | `valid proposal-only schema` |
| schema | production_activation_disabled | hard | True | `False` | `False` |
| schema | human_approval_required | hard | True | `True` | `True` |
| main | feature_gate_candidate_backtest_executed | hard | False | `candidate_only` | `full candidate rebuild/backtest` |
| main | main_cagr_floor | hard | False | `0.20165834588806963` | `0.2747134251245684` |
| main | main_sharpe_floor | hard | False | `1.0971959712745438` | `1.570588082520192` |
| main | main_max_dd_floor | hard | False | `-0.27307967491398366` | `-0.1642379649695953` |
| main_v2 | main_v2_historical_backtest_exists | hard | False | `latest_snapshot_only` | `83-month main_v2 backtest` |
| main_v2 | main_v2_cap_audit | soft | True | `{'positions': 11, 'cash': 0.07820306303913749}` | `cap<=15%, positions>0` |
| concentrated | concentrated_cagr_floor | hard | True | `0.43243153809103063` | `0.3` |
| concentrated | concentrated_max_dd_floor | hard | True | `-0.1259120118944551` | `-0.25` |
| concentrated | single_name_and_sector_cap_audit | hard | False | `2` | `0` |
| orchestrator | orchestrator_historical_backtest_exists | hard | False | `snapshot_report_only` | `83-month orchestrator backtest` |
| orchestrator | snapshot_cash_floor | soft | True | `0.19999999999999996` | `0.25` |
| alpha_sprint | alpha_sprint_historical_backtest_exists | hard | False | `not_backtested_missing_historical_scored_snapshot` | `weekly/historical alpha sprint backtest` |
| stress | stress_windows_backtested | hard | False | `not_available` | `2020/2022/momentum/rate/vix stress windows` |
| cost | cost_sensitivity_backtested | hard | False | `not_available` | `[25, 50, 75]` |
| stability | rolling_3y_5y_backtested | hard | False | `not_available` | `rolling 3y and 5y pass` |

## Blockers

- main/feature_gate_candidate_backtest_executed: Feature-gate candidate currently has dry-run/proxy metrics only.
- main/main_cagr_floor: Candidate main CAGR must not regress beyond the policy gate.
- main/main_sharpe_floor: Candidate main Sharpe must not regress beyond the policy gate.
- main/main_max_dd_floor: Candidate main MaxDD must not worsen beyond the policy gate.
- main_v2/main_v2_historical_backtest_exists: Main v2 currently has latest shadow output, not historical performance.
- concentrated/single_name_and_sector_cap_audit: Latest concentrated policy audit found cap violations that must be resolved before more capital.
- orchestrator/orchestrator_historical_backtest_exists: Orchestrator balanced currently reports latest snapshot only.
- alpha_sprint/alpha_sprint_historical_backtest_exists: Alpha Sprint can remain candidate-only until bull/strong-bull historical tests exist.
- stress/stress_windows_backtested: Policy challenger needs monthly equity and allocation series before stress gates can pass.
- cost/cost_sensitivity_backtested: Cost sensitivity has not been run for the full candidate policy.
- stability/rolling_3y_5y_backtested: Rolling stability cannot pass until full challenger return series exists.

## Next Required Backtests

- `main_v2_83_month_backtest`
- `orchestrator_83_month_backtest`
- `alpha_sprint_weekly_historical_backtest`
- `stress_window_equity_curve_test`
- `cost_sensitivity_25_50_75_bps`
- `rolling_3y_5y_stability`
