# R1000 AlphaOps Implementation Plan

Date: 2026-05-02 KST
Mode: planning only, no production behavior change yet

## Guiding Rules

1. Preserve the shipped Phase 15-D and latest Phase 17-19 baselines as controls.
2. Do not change `DEFAULT_FEATURES`, sector caps, sleeve weights, target N, or
   risk exits without an A/B run and ship gate.
3. Keep auto-learning proposal-only until a challenger run passes.
4. Keep broker execution dry-run or signal-only until live/paper gates pass.
5. Treat concentrated, tactical, and leverage as separate risk budgets, not as
   hidden boosts to the main portfolio.
6. Every behavior change must be reversible by config or branch rollback.

## Stage 0 - Baseline Registry

Goal: make future experiments comparable.

Deliverables:

- `outputs/reports/baseline_registry.json`
- `outputs/reports/baseline_registry.md`
- record Phase 15-D baseline and latest `242f02f` run
- record exact run id, branch, commit, universe mode, window, fast/full mode,
  cost, backtest months, selected names, and artifact path

Files likely touched:

- new helper under `tools/`
- optional call from `full_rebuild_manual.yml`

Validation:

- registry file exists after workflow
- no changes to portfolio results

Rollback:

- remove helper/workflow call

## Stage 1 - Config And Default Audit

Goal: expose config drift before it changes results.

Deliverables:

- `outputs/reports/config_audit.json`
- `outputs/reports/config_audit.md`
- flags for differences among `r1000_config.py`, `run_local.py`,
  `colab_run.ipynb`, and GitHub workflow inputs

Must check:

- backtest years
- fast mode
- cost assumptions
- sleeve weights
- target N
- rebalance intervals
- mandate capacities
- active auto gates
- leverage settings
- GDrive sync expectations

Validation:

- `py -3 tests\smoke_test.py`
- `py -3 tests\audit_features.py --no-runtime`
- config audit produces deterministic output

Rollback:

- report-only tool can be removed without changing engine behavior

## Stage 2 - Orchestrator Shadow Output

Goal: create the future unified target file without using it for backtest yet.

Current state:

- `r1000_orchestrator.py` is inspection-only.
- It can scale main/concentrated/tactical weights by regime capacity and merge
  ticker conflicts by max weight.
- It writes JSON but is not the production target.

Deliverables:

- `outputs/orchestrator/unified_target_latest.csv`
- `outputs/orchestrator/unified_target_latest.json`
- `outputs/orchestrator/audit_latest.json`
- test that, with concentrated/tactical disabled, shadow output matches legacy
  latest portfolio within tolerance

Files likely touched:

- `r1000_orchestrator.py`
- `r1000_pipeline.py` export section only
- tests under `tests/`

Validation:

- no change to `outputs/portfolio_latest.csv`
- no change to backtest metrics
- orchestrator audit shows cash, gross exposure, caps, conflicts

Rollback:

- disable export flag

## Stage 3 - Risk Sensing To Operator Recommendations

Goal: turn risk sensing into a human-readable plan, not automatic trading.

Current state:

- `r1000_risk_sensing.py` has individual, portfolio, regime, and swap actions.
- CLI is still a stub for live integration.
- `r1000_operator.py` creates plan outputs but does not consume risk actions.

Deliverables:

- `outputs/risk/risk_actions_latest.csv`
- `outputs/risk/risk_actions_latest.json`
- `outputs/ops/live_operator_plan_latest.csv` includes risk reason columns
- urgent exit / no-buy flags as explicit report-only fields

Rules:

- risk actions may recommend sells, cash raises, no-buy, or review
- no broker execution
- no forced production backtest change in this stage

Validation:

- smoke tests
- synthetic risk action test
- latest operator plan remains generated if risk file missing

Rollback:

- ignore risk action input in operator

## Stage 4 - Execution Realism And Order Tickets

Goal: make the engine produce realistic order tickets before connecting brokers.

Deliverables:

- `execution/cost_model.py`
- `execution/order_ticket.py`
- `outputs/orders/orders_preview_latest.csv`
- assumptions for market, limit, and TWAP

Required fields:

- ticker
- side
- current_weight
- target_weight
- trade_value_usd
- estimated_cost_usd
- expected_slippage_bps
- order_type
- limit_price_hint
- reason
- risk_flag

Validation:

- ticket weights reconcile to target
- estimated costs use 25 bps per side by default
- no live API call

Rollback:

- order ticket layer is additive

## Stage 5 - Trade Journal Postmortem Loop

Goal: identify why trades won or failed before changing rules.

Current state:

- holdings/trades/grades are produced.
- `tools/trade_insights.py` can generate IC and cluster reports.
- feature-gate proposal exists but is proposal-only.

Deliverables:

- `trap_pattern_report.md`
- `missed_winner_report.md`
- `premature_exit_report.md`
- `good_exit_report.md`
- `regime_trade_matrix.csv`
- `theme_trade_matrix.csv`
- `signal_decay_report.csv`
- `rule_proposal.md`

Validation:

- reports are generated from existing trade journal artifacts
- no active gate file is created by default
- no production selection change

Rollback:

- report-only

## Stage 6 - Auto-Gate Challenger A/B

Goal: test learning proposals without silent production mutation.

Current state:

- latest proposal suggested disabling weak theme features in bear/neutral and
  amplifying `rs_acceleration_score` in bull.
- promotion was blocked because main CAGR floor failed.

Deliverables:

- candidate YAML stored under `research/auto_learning/candidates/`
- experiment run with candidate active
- promotion report compares baseline vs candidate

Rules:

- do not create `research/auto_feature_gates.yaml` directly
- do not auto-merge to active
- require full metrics, cost, drawdown, and window checks

Validation:

- candidate must improve or preserve main CAGR floor
- concentrated must not regress materially
- no leakage audit failures

Rollback:

- delete candidate file

## Stage 7 - Tactical Sleeve Ship-Gated Integration

Goal: make tactical a real but capped sleeve only if it earns its risk budget.

Current state:

- tactical research backtester exists.
- tactical capacity is 0 in deep_bear/bear/neutral, 5% in bull, 10% in
  strong_bull.
- explosion model fallback is currently zero.

Deliverables:

- standalone tactical backtest report
- tactical sleeve candidate weights
- orchestrator shadow composition with tactical enabled
- no production activation until tactical gate passes

Validation:

- positive standalone excess return after cost
- no allocation outside bull/strong_bull
- drawdown contribution within gate
- turnover cost measured

Rollback:

- tactical capacity stays zero in production

## Stage 8 - Target N And Regime Capacity A/B

Goal: improve CAGR without losing drawdown control.

Hypothesis:

- main CAGR is diluted by too many names.

Experiments:

- main target N: 8, 10, 12, 17, 20, 30
- concentrated target N: 3, 4, 5, 7, 10
- regime capacity maps: current, conservative, aggressive

Validation:

- main production gate
- concentrated gate
- stress windows 2020 and 2022
- cost sensitivity
- turnover cap

Rollback:

- revert to current `MANDATE_REGISTRY` and legacy portfolio path

## Stage 9 - Dynamic Theme Engine

Goal: find emerging themes earlier without hard-coding only static YAML.

Inputs:

- ETF holdings overlap
- industry/sub-industry relative strength
- SEC filing keywords
- earnings call or event keywords when available
- price co-movement clusters
- analyst revision clusters when available

Deliverables:

- `dynamic_theme_memberships.parquet`
- `theme_birth_report.md`
- `theme_fatigue_report.md`
- sidecar theme scores

Rules:

- sidecar first
- no hard filter until A/B
- do not replace curated themes immediately

Validation:

- explainable membership
- stable across refreshes
- improves early-winner recall in retrospective tests

## Stage 10 - Conditional Leverage

Goal: amplify proven edge only after unlevered gates pass.

Rules:

- not part of first implementation batch
- no leverage in bear/neutral
- first test only 1.15x in strong_bull
- require explicit leverage gate

Validation:

- unlevered Sharpe and MaxDD gates pass first
- stress windows pass
- no margin behavior hidden in main metrics

## Recommended Weekend Batch

Implement only the low-risk foundation first:

1. Stage 0 baseline registry.
2. Stage 1 config/default audit.
3. Stage 2 orchestrator shadow output.
4. Stage 3 risk sensing to operator recommendations, report-only.
5. Stage 5 trade journal postmortem reports.

Do not activate Stage 6-10 behavior until the foundation is in place and the
first shadow outputs are reviewed.

## Standard Validation Commands

```powershell
py -3 tests\smoke_test.py
py -3 tests\audit_features.py --no-runtime
git diff --check
```

Run full cloud rebuild only after a behavior-changing stage:

```text
workflow: Full Rebuild (Manual / Long-Run)
branch: codex/integrate-phase17-19
universe: global_alpha_universe
backtest_years: 8
fast_mode: true for first pass
skip_collector: false if cache health is uncertain
```

