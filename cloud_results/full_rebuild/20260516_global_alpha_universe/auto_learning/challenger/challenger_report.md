# AutoLearning Policy Challenger Report

This report evaluates the candidate policy gates. It does not apply the policy to production.

- Policy version: `2026-05-alphaops-20260516-v1`
- Status: `blocked`
- Approved for promotion: `False`
- Hard failures: 12

## Gate Matrix

| Gate | Check | Severity | Passed | Observed | Threshold |
| --- | --- | --- | --- | --- | --- |
| broker_accounting | audit_artifact_present | hard | True | `True` | `True` |
| broker_accounting | delisted_cost_basis_fallback_eliminated | hard | True | `True` | `True` |
| broker_accounting | survivorship_coverage_audited | hard | False | `False` | `True` |
| broker_accounting | multi_day_fill_date_stamping_corrected | soft | False | `False` | `True` |
| broker_accounting | sharpe_uses_excess_return | soft | True | `True` | `True` |
| schema | policy_valid | hard | True | `[]` | `valid proposal-only schema` |
| schema | production_activation_disabled | hard | True | `False` | `False` |
| schema | human_approval_required | hard | True | `True` | `True` |
| main | feature_gate_candidate_backtest_executed | hard | False | `candidate_only` | `full candidate rebuild/backtest` |
| main | main_cagr_floor | hard | True | `0.20165834588806963` | `0.19287851054314809` |
| main | main_sharpe_floor | hard | False | `1.0971959712745438` | `1.4048607897809737` |
| main | main_max_dd_floor | hard | False | `-0.27307967491398366` | `-0.16275979516510797` |
| main_v2 | main_v2_historical_backtest_exists | hard | False | `latest_snapshot_only` | `83-month main_v2 backtest` |
| main_v2 | main_v2_cap_audit | soft | True | `{'positions': 11, 'cash': 0.07820306303913749}` | `cap<=15%, positions>0` |
| concentrated | concentrated_cagr_floor | hard | False | `0.28111314811671373` | `0.3` |
| concentrated | concentrated_max_dd_floor | hard | True | `-0.11445174764460198` | `-0.25` |
| concentrated | single_name_and_sector_cap_audit | hard | False | `2` | `0` |
| orchestrator | orchestrator_historical_backtest_exists | hard | False | `snapshot_report_only` | `83-month orchestrator backtest` |
| orchestrator | snapshot_cash_floor | soft | True | `0.19999999999999996` | `0.25` |
| alpha_sprint | alpha_sprint_historical_backtest_exists | hard | False | `{'alpha_sprint_status': 'not_backtested_missing_historical_scored_snapshot', 'weekly_leader_available': False}` | `weekly/historical alpha sprint or weekly leader-entry broker replay` |
| weekly_leader_entry | weekly_leader_broker_replay_available | soft | False | `{'main_status': None, 'main_cagr': None, 'concentrated_status': None, 'concentrated_cagr': None}` | `completed account-like replay` |
| stress | stress_windows_backtested | hard | False | `not_available` | `2020/2022/momentum/rate/vix stress windows` |
| cost | cost_sensitivity_backtested | hard | False | `{'main': {'schema_version': None, 'completed_levels': [], 'breakeven_cost_bps': None}, 'concentrated': {'schema_version': None, 'completed_levels': [], 'breakeven_cost_bps': None}}` | `{'cost_bps_levels_required': [25, 50, 75], 'main_summary_path': 'outputs/cost_sensitivity/main/summary.json', 'concentrated_summary_path': 'outputs/cost_sensitivity/concentrated/summary.json'}` |
| stability | rolling_3y_5y_backtested | hard | False | `not_available` | `rolling 3y and 5y pass` |

## Blockers

- broker_accounting/survivorship_coverage_audited: The price cache must include historical R1000 constituents that have since been delisted or acquired. Without this audit, broker-ledger metrics over 7+ years can only see survivors, inflating CAGR and hiding MaxDD. As of 2026-05-14 the AUDIT TOOL ships (tools/run_survivorship_audit.py + smoke test) but the gate flip awaits a real-data measurement showing coverage_ratio >= 0.85 over a >= 100-ticker delisted set.
- main/feature_gate_candidate_backtest_executed: Feature-gate candidate currently has dry-run/proxy metrics only.
- main/main_sharpe_floor: Candidate main Sharpe must not regress beyond the policy gate.
- main/main_max_dd_floor: Candidate main MaxDD must not worsen beyond the policy gate.
- main_v2/main_v2_historical_backtest_exists: Main v2 currently has latest shadow output, not historical performance.
- concentrated/concentrated_cagr_floor: Standalone concentrated historical CAGR must clear the policy floor.
- concentrated/single_name_and_sector_cap_audit: Latest concentrated policy audit found cap violations that must be resolved before more capital.
- orchestrator/orchestrator_historical_backtest_exists: Orchestrator balanced currently reports latest snapshot only.
- alpha_sprint/alpha_sprint_historical_backtest_exists: Alpha Sprint can remain candidate-only until bull/strong-bull historical tests exist; weekly leader entry broker replay can now serve as the first counterfactual bridge.
- stress/stress_windows_backtested: Policy challenger needs monthly equity and allocation series before stress gates can pass.
- cost/cost_sensitivity_backtested: Cost sensitivity sidecar must run for both main and concentrated target books and emit one completed level per required cost_bps step.
- stability/rolling_3y_5y_backtested: Rolling stability cannot pass until full challenger return series exists.

## Next Required Backtests

- `broker_accounting_audit_flips_hard_gates_to_true`
- `main_v2_83_month_backtest`
- `orchestrator_83_month_backtest`
- `weekly_leader_entry_cost_and_stress_replay`
- `alpha_sprint_weekly_historical_backtest`
- `stress_window_equity_curve_test`
- `cost_sensitivity_25_50_75_bps`
- `rolling_3y_5y_stability`
