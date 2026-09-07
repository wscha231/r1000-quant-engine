# Research decision V1

Data kind: SYNTHETIC; cutoff: 2026-09-07T12:00:00Z
Mode: NEW_CAPITAL_RESEARCH; orders_allowed=false

Subjective scenarios; OOS and MDD validation incomplete.

| Security | Local total return (currency) | KRW total return | KRW return rank | KRW investment rank |
|---|---:|---:|---:|---:|
| KR:990000 | 85.75% (KRW) | 85.75% | 1 | 3 |
| US:FIX1 | 85.75% (USD) | 85.75% | 2 | 1 |
| US:FIX2 | 85.75% (USD) | 85.75% | 3 | 2 |

| Security | Action | Weight | Reason |
|---|---|---:|---|
| KR:990000 | ENTER | 1.00% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX1 | ENTER | 20.00% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |
| US:FIX2 | ENTER | 20.00% | positive_scenario_utility_subject_to_risk_liquidity_cost_caps |

| Security | Good company? | Good stock? | Buy price now? | Portfolio value? |
|---|---|---|---|---|
| KR:990000 | pass | pass | pass | pass_research_only |
| US:FIX1 | pass | pass | pass | pass_research_only |
| US:FIX2 | pass | pass | pass | pass_research_only |

Cash / unallocated capital: 59.00%.

Readiness: `{"broker_reconciled": false, "data_quality_pass": true, "oos_validated": false, "orders_allowed": false, "portfolio_proposal_ready": true, "production_promoted": false, "research_pipeline_ready": true, "research_ranking_ready": true, "research_universe_fully_covered": true, "return_calibration_validated": false, "target_5_plus_2_complete": false}`
