# AutoLearning v2 Design

Date: 2026-05-03 KST
Branch: `codex/integrate-phase17-19`
Mode: design only

## Current State

Auto-learning today is a guarded feature-gate proposal flow:

```text
trade journal artifacts
  -> tools/trade_insights.py
  -> tools/feature_gate_proposal.py
  -> candidate gate YAML
  -> tools/auto_learning_promote.py
  -> blocked or promoted after hard checks
```

Latest candidate gates:

- Bear `rs_acceleration_score` amplify 1.3.
- Bear `h1_oversold_value_score` amplify 1.3.
- Bear `theme_phase_multiplier_primary` disable.
- Bear `theme_phase_multiplier_max` disable.

Latest promotion decision:

- Approved: false.
- Promoted: false.
- Main CAGR floor failed.
- Main Sharpe floor failed.
- Main MaxDD floor failed.
- Concentrated CAGR floor passed.
- Trade count floor passed.

This is a good safety model, but it is only AutoLearning v1. It learns feature
gates, not portfolio policy.

## Design Goal

AutoLearning v2 should become a policy learner that proposes challenger
policies across features, sleeves, target N, allocation, entry, exit, cash, and
execution. It must never mutate production behavior directly.

Required lifecycle:

```text
evidence
  -> hypothesis
  -> candidate policy
  -> counterfactual test
  -> isolated challenger backtest
  -> discovery gate
  -> production gate
  -> human approval
  -> explicit activation
```

## Non-Goals

Do not implement these in the first pass:

- Direct production auto-policy activation.
- Broker execution.
- Leverage.
- Automatic baseline rotation.
- Silent updates to `DEFAULT_FEATURES`.
- Silent updates to `research/auto_feature_gates.yaml`.
- Any rule that bypasses human approval.

## Policy Learners

### 1. Feature Gate Learner

Learns:

- signal disable by regime
- signal amplify by regime
- pattern block
- signal decay
- minimum confirmation requirements

Evidence:

- signal IC by regime
- cluster win rates
- SHAP or model importance when available
- trade-level return distribution

Output:

```yaml
policy_type: feature_gate
scope: challenger
gates:
  - kind: signal_regime_amplify
    signal: rs_acceleration_score
    regime: bear
    factor: 1.3
```

### 2. Sleeve Allocation Learner

Learns:

- main, concentrated, tactical, Alpha Sprint, and cash capacities by regime
- sleeve-level drawdown responses
- sleeve risk budget limits

Evidence:

- sleeve returns
- sleeve drawdowns
- sleeve turnover
- mandate overlap
- stress windows

Output:

```yaml
policy_type: sleeve_allocation
scope: challenger
capacity_by_regime:
  neutral:
    main: 0.55
    concentrated: 0.25
    alpha_sprint: 0.00
    cash: 0.20
```

### 3. Target N Learner

Learns:

- main target N by regime
- concentrated target N by regime
- target N by breadth and score dispersion
- incumbent buffer by sleeve

Evidence:

- rank bucket return contribution
- realized name count
- turnover
- drawdown by concentration level

Output:

```yaml
policy_type: target_n
scope: challenger
main_target_n:
  neutral: 15
  bull: 12
concentrated_target_n:
  neutral: 5
  strong_bull: 3
```

### 4. Orchestrator Allocation Learner

Learns:

- merge mode
- unified single-name cap
- duplicate ticker conflict policy
- sleeve priority during risk-on and risk-off periods

Evidence:

- orchestrator backtest
- conflict logs
- cap violations
- cash drag
- stress window outcomes

Output:

```yaml
policy_type: orchestrator
scope: challenger
merge_mode: sum_then_cap
unified_single_name_cap: 0.20
```

### 5. Entry Timing Learner

Learns:

- staged entry rules
- entry quality threshold
- overextension block
- breakout freshness
- earnings blackout or confirmation

Evidence:

- trade entry drawdown
- post-entry return distribution
- failed breakout rate
- cluster signatures

Output:

```yaml
policy_type: entry_timing
scope: challenger
staged_entry: true
initial_entry_pct: 0.60
add_on_confirmations:
  - follow_through_5pct
  - plus_1_atr
```

### 6. Exit Timing Learner

Learns:

- hard stop
- trailing stop
- RS break
- theme decay exit
- better replacement swap
- time stop for Alpha Sprint

Evidence:

- premature exits
- good exits
- missed exits
- drawdown from peak
- replacement opportunity cost

Output:

```yaml
policy_type: exit_timing
scope: challenger
hard_stop_pct: -0.08
trailing_stop_pct: -0.15
time_stop_days: 30
```

### 7. Cash Policy Learner

Learns:

- cash by regime
- drawdown circuit breaker
- no-buy conditions
- risk-off scale-down

Evidence:

- benchmark trend
- VIX
- breadth
- credit stress
- portfolio drawdown
- opportunity cost of cash

Output:

```yaml
policy_type: cash_policy
scope: challenger
portfolio_dd_breaker: true
neutral_cash_cap: 0.20
```

### 8. Execution Policy Learner

Learns report-only execution guidance:

- order type
- limit hint
- trade slicing
- max trade value
- liquidity caution

Evidence:

- turnover
- slippage assumption
- position size
- liquidity proxies

Output:

```yaml
policy_type: execution
scope: preview_only
order_type_default: limit
requires_human_approval: true
```

### 9. Hypothesis Generator

Turns anomalies into testable policy ideas.

Example hypotheses:

- Main rank 16-30 is diluting CAGR without reducing MaxDD.
- Neutral cash above 25% is too defensive for CAGR goals.
- Bear `h6_dynamic_leader_score` needs RS acceleration confirmation.
- Concentrated should not be fully off in bear if one or two leaders remain
  intact, but capacity should be capped.

### 10. Counterfactual Tester

Runs cheap offline checks before expensive backtests:

- What if this gate was active for past trades?
- What if target N was 15 instead of 25?
- What if concentrated capacity was 20% in neutral?
- What if max-merge was replaced by sum-then-cap?

Counterfactuals are not production evidence. They only decide which challengers
are worth full backtesting.

## Data Inputs

Primary inputs:

- `backtest_metrics.json`
- `concentrated_backtest_metrics.json`
- `reports/baseline_registry.json`
- `reports/config_audit.json`
- `portfolio_latest.csv`
- `concentrated_portfolio_latest.csv`
- `scored_latest.csv`
- `trade_journal/trades.csv`
- `trade_journal/grades.csv`
- `trade_journal/holdings_history.csv`
- `trade_journal/insights/ic_matrix.csv`
- `trade_journal/insights/cluster_winrate.csv`
- orchestrator shadow JSON and CSV
- risk sensing compare outputs

## Candidate Policy Schema

Recommended root:

```text
research/auto_learning_v2/candidates/
```

Candidate file pattern:

```text
candidate_policy_YYYYMMDD_HHMMSS.yaml
```

Minimum schema:

```yaml
schema_version: auto_learning_v2_policy_v1
generated_at_utc: "2026-05-03T00:00:00Z"
scope: challenger_only
source_artifacts:
  baseline_registry: cloud_results/full_rebuild/latest_global_alpha_universe/reports/baseline_registry.json
  trade_insights: cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md
hypothesis:
  id: H_main_dilution_001
  statement: Main rank 16-30 dilutes CAGR without improving drawdown.
policies:
  feature_gates: []
  sleeve_allocation: {}
  target_n: {}
  orchestrator: {}
  entry_timing: {}
  exit_timing: {}
  cash_policy: {}
  execution: {}
required_outputs:
  - metrics.json
  - experiment_report.md
approval:
  human_approval_required: true
  production_activation_allowed: false
```

## Promotion Governor

AutoLearning v2 needs a governor that is stricter than discovery.

Discovery gate:

- Lets a candidate continue research.
- Does not allow production activation.

Production gate:

- Requires improvement versus the correct baseline.
- Requires stress window checks.
- Requires cap compliance.
- Requires turnover and cost checks.
- Requires human approval.

Promotion states:

```text
draft
counterfactual_passed
challenger_running
discovery_passed
production_gate_failed
production_gate_passed
approved_for_manual_activation
activated
rejected
expired
```

## Failure Logging

Failed experiments must be first-class artifacts.

Required failure fields:

- candidate id
- hypothesis
- baseline id
- failure gate
- metric deltas
- suspected reason
- whether to retry
- next modification

Failure output:

```text
outputs/experiments/{experiment_id}/experiment_report.md
```

## First Implementation Batch After Approval

1. Define `research/auto_learning_v2/policy_schema.yaml`.
2. Add a report-only candidate policy writer.
3. Add a validator that rejects production activation fields.
4. Add a promotion governor report that reads existing experiment outputs.
5. Do not connect to production config.

## Approval Boundary

This file is design only. It authorizes no code behavior changes. The next
approval should choose whether to implement the report-only AutoLearning v2
schema and candidate writer.
