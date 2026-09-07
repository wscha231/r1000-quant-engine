# Research decision V1

Data kind: SYNTHETIC; cutoff: 2026-09-07T12:00:00Z
Mode: NEW_CAPITAL_RESEARCH; orders_allowed=false

Subjective scenarios; OOS and MDD validation incomplete.

| Security | Local total return (currency) | KRW total return | KRW return rank | KRW investment rank |
|---|---:|---:|---:|---:|
| KR:990000 | 85.75% (KRW) | 85.75% | 1 | 6 |
| KR:990001 | 85.75% (KRW) | 85.75% | 2 | 7 |
| US:FIX1 | 85.75% (USD) | 85.75% | 3 | 1 |
| US:FIX2 | 85.75% (USD) | 85.75% | 4 | 2 |
| US:FIX3 | 85.75% (USD) | 85.75% | 5 | 3 |
| US:FIX4 | 85.75% (USD) | 85.75% | 6 | 4 |
| US:FIX5 | 85.75% (USD) | 85.75% | 7 | 5 |

| Security | Action | Weight | Reason |
|---|---|---:|---|
| KR:990000 | ENTER | 1.00% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| KR:990001 | ENTER | 1.00% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX1 | ENTER | 10.01% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX2 | ENTER | 10.01% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX3 | ENTER | 10.01% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX4 | ENTER | 10.01% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX5 | ENTER | 10.01% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |

| Security | Good company? | Good stock? | Buy price now? | Portfolio value? |
|---|---|---|---|---|
| KR:990000 | pass | pass | pass | pass_research_only |
| KR:990001 | pass | pass | pass | pass_research_only |
| US:FIX1 | pass | pass | pass | pass_research_only |
| US:FIX2 | pass | pass | pass | pass_research_only |
| US:FIX3 | pass | pass | pass | pass_research_only |
| US:FIX4 | pass | pass | pass | pass_research_only |
| US:FIX5 | pass | pass | pass | pass_research_only |

Cash / unallocated capital: 47.94%.

| Constraint audit | Observed |
|---|---|
| Gross exposure | 52.06% |
| Scenario stress loss / limit | 23.43% / 25.00% |
| Country exposure | {"KR": 0.02, "US": 0.50058675} |
| Country counts | {"KR": 2, "US": 5} |
| Common risk exposure | {"customer:synthetic-0": 0.04404694000000001, "customer:synthetic-1": 0.04404694000000001, "customer:synthetic-2": 0.04004694, "customer:synthetic-3": 0.04004694, "customer:synthetic-4": 0.04004694, "industry:synthetic-KR-0": 0.01, "industry:synthetic-KR-1": 0.01, "industry:synthetic-US-0": 0.10011735, "industry:synthetic-US-1": 0.10011735, "industry:synthetic-US-2": 0.10011735, "industry:synthetic-US-3": 0.10011735, "industry:synthetic-US-4": 0.10011735, "theme:synthetic-0": 0.11011734999999999, "theme:synthetic-1": 0.11011734999999999, "theme:synthetic-2": 0.10011735, "theme:synthetic-3": 0.10011735, "theme:synthetic-4": 0.10011735} |
| Violations | none |

Readiness: `{"broker_reconciled": false, "data_quality_pass": true, "oos_validated": false, "orders_allowed": false, "portfolio_proposal_ready": true, "production_promoted": false, "research_pipeline_ready": true, "research_ranking_ready": true, "research_universe_fully_covered": true, "return_calibration_validated": false, "target_5_plus_2_complete": true}`
