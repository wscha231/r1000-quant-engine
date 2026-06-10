# Implementation Plan

Date: 2026-05-03 KST
Branch: `codex/integrate-phase17-19`
Mode: approval-gated

## Prime Directive

Do not change production behavior before approval.

Specifically:

- Do not edit `DEFAULT_FEATURES`.
- Do not activate auto feature gates.
- Do not change production sleeve weights.
- Do not change production target N.
- Do not change sector caps or risk exits.
- Do not add leverage.
- Do not connect broker execution.
- Do not replace production portfolio construction with orchestrator output.

All aggressive work must be isolated under experiment flags and
`outputs/experiments/{experiment_id}`.

## Stage 0 - Research And Lab Scaffold

Status: current batch.

Deliverables:

- `research/7h_synthesis/current_system_map.md`
- `research/7h_synthesis/dormant_feature_inventory.md`
- `research/7h_synthesis/regression_attribution_plan.md`
- `research/7h_synthesis/auto_learning_v2_design.md`
- `research/7h_synthesis/aggressive_lab_plan.md`
- `research/7h_synthesis/implementation_plan.md`
- `research/aggressive_lab_202605/experiment_matrix.yaml`
- `research/aggressive_lab_202605/discovery_gates.yaml`
- `research/aggressive_lab_202605/production_gates.yaml`

Validation:

- `git diff --check`
- inspect `git diff --stat`

Exit condition:

- Human reviews and approves whether to implement Stage 1 and Stage 2.

## Stage 1 - Regression Attribution Report

Goal:

Explain latest regression versus 2026-04-30 and Phase 15-D.

Deliverables:

- `reports/regression_attribution_20260430_vs_latest.md`
- optional `reports/regression_attribution_20260430_vs_latest.json`

Suggested implementation:

- Add `tools/regression_attribution.py`.
- Read existing JSON and CSV artifacts.
- Compare metrics, holdings, sleeve returns, score distributions, regimes,
  explosion activity, trade journal evidence, and run identity.

Validation:

- Report generates from existing artifacts.
- Missing optional artifacts degrade gracefully.
- No portfolio output changes.

Approval required before starting.

## Stage 2 - Aggressive Lab Runner Skeleton

Goal:

Create an isolated experiment runner without implementing new strategy behavior
yet.

Deliverables:

- `tools/run_aggressive_lab.py`
- output contract writer
- gate evaluator
- failure report writer

Initial runner may support only:

- `E0_baseline_latest` artifact copy and report.
- config parsing.
- gate evaluation against provided metrics.

Validation:

- `E0` writes complete output structure.
- No production files are overwritten.
- `git diff --check`.

Approval required before starting.

## Stage 3 - Main v2 Shadow

Goal:

Test whether a 12-15 name high-conviction main book improves CAGR and drawdown.

Deliverables:

- Main v2 selector or adapter behind experiment-only flag.
- Balanced and aggressive experiment outputs.
- Rank bucket attribution.

Candidate tests:

- `E2_main_v2_balanced`
- `E3_main_v2_aggressive`

Risk controls:

- Single-name cap.
- Incumbent buffer.
- Sleeve rebalance cadence.
- Bear feature gates only in challenger mode.

Approval required before starting.

## Stage 4 - Concentrated Balanced Shadow

Goal:

Test concentrated as a larger alpha sleeve while controlling single-name,
theme, sector, timing, and exit risk.

Deliverables:

- Experiment-only concentrated capacity map.
- Caps report.
- Weekly timing/staged entry report if data allows.

Candidate test:

- `E4_concentrated_balanced`

Approval required before starting.

## Stage 5 - Orchestrator Backtest

Goal:

Move orchestrator from latest shadow output to historical challenger backtest.

Deliverables:

- 83-month orchestrator backtest.
- Merge mode A/B.
- Unified cap checks.
- Monthly allocation output.

Candidate test:

- `E5_orchestrator_balanced`

Merge modes:

- `max`
- `sum_then_cap`
- `priority_concentrated`
- `risk_budget_blend`

First challenger:

- `sum_then_cap + unified cap`

Approval required before starting.

## Stage 6 - Risk Sensing Historical Integration

Goal:

Test whether risk sensing lowers drawdown without destroying winner capture.

Deliverables:

- Risk action historical output.
- Stress window comparison.
- Position-level action summary if data allows.

Candidate test:

- `E6_risk_sensing_on`

Constraints:

- Report-only recommendations.
- No broker calls.
- No forced production sell logic.

Approval required before starting.

## Stage 7 - Tactical And Alpha Sprint Sidecars

Goal:

Test short-horizon alpha only as capped bull/strong-bull sidecars.

Candidate tests:

- `E7_tactical_bull_only`
- `E8_alpha_sprint_sidecar`

Deliverables:

- Standalone after-cost metrics.
- Time stop and hard stop reports.
- Allocation impact if combined through orchestrator.

Approval required before starting.

## Stage 8 - AutoLearning v2 Report-Only Implementation

Goal:

Expand from feature-gate proposals into policy proposals while keeping
production immutable.

Deliverables:

- policy schema
- candidate writer
- validator
- promotion governor report
- failure registry

Constraints:

- No active policy file is changed.
- No production config is changed.
- Human approval remains mandatory.

Approval required before starting.

## Stage 9 - Order Ticket Preview

Goal:

Produce realistic order previews with costs and reasons, without broker
execution.

Deliverables:

- `execution/cost_model.py`
- `execution/order_ticket.py`
- `outputs/orders/orders_preview_latest.csv`

Required fields:

- ticker
- side
- current_weight
- target_weight
- trade_value_usd
- estimated_fee_usd
- estimated_slippage_usd
- order_type
- limit_price_hint
- reason
- risk_flag
- requires_human_approval

Approval required before starting.

## Recommended Next Approval

Approve only these two implementation steps first:

1. Stage 1 regression attribution report.
2. Stage 2 aggressive lab runner skeleton with `E0` only.

Reason:

- They increase observability and repeatability.
- They do not alter production behavior.
- They create the foundation for later challenger tests.

After those are reviewed, approve Main v2, concentrated balanced, orchestrator,
risk sensing, and Alpha Sprint in separate batches.
