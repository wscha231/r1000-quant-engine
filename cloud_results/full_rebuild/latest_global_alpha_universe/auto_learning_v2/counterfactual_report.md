# AutoLearning v2 Counterfactual Report

This report states whether each creative hypothesis has enough historical evidence to be trusted.

| Hypothesis | Experiment | Status | Discovery | CAGR delta pp | MaxDD delta pp | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- |
| main_future_alpha_concentration_v1 | E2_main_v2_balanced | `needs_full_challenger_backtest` | false | 0.00 | 0.00 | Only snapshot_report_only evidence exists; run full historical replay before promotion. |
| concentrated_neutral_25_v1 | E4_concentrated_balanced | `needs_full_challenger_backtest` | true | 13.45 | 4.33 | Only standalone_sleeve_policy_audit evidence exists; run full historical replay before promotion. |
| risk_governor_layered_exit_v1 | E6_risk_sensing_on | `counterfactual_available` | true | -2.94 | 5.65 | Historical replay exists; review discovery/production gates. |
| cluster_conviction_router_v1 |  | `infrastructure_or_guardrail` | false |  |  | Governance/infrastructure hypothesis; blocks promotion until replay coverage improves. |
| alpha_sprint_breakout_fallback_v1 | weekly_leader_entry_broker_replay | `counterfactual_available` | false | -16.22 | -1.02 | Weekly leader-entry broker replay is available as account-like counterfactual evidence; keep proposal-only until stress/cost gates pass. |
| counterfactual_replay_priority_v1 |  | `infrastructure_or_guardrail` | false |  |  | Governance/infrastructure hypothesis; blocks promotion until replay coverage improves. |
