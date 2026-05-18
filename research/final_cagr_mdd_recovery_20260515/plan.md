# Final CAGR / MDD Recovery Implementation Plan - 2026-05-15

## Objective

Improve official broker-ledger CAGR and MaxDD without relying on legacy monthly
or proxy metrics.

Official metric source:

- `outputs/broker_replay/main/metrics.json`
- `outputs/broker_replay/concentrated/metrics.json`
- metric mode: `broker_ledger_next_close`
- integer shares, no leverage, adjusted close, 25 bps per side

Current Iter 6 baseline:

| Portfolio | CAGR | MaxDD | Sharpe | Status |
|---|---:|---:|---:|---|
| Main | 18.44% | -31.93% | 0.848 | fail |
| Concentrated | 35.10% | -22.68% | 1.300 | fail but closest |

Targets:

- Main: CAGR >= 30%, MaxDD >= -15%
- Concentrated: CAGR >= 50%, MaxDD >= -18%

## Rules

- Do not optimize or promote monthly-weight or research-proxy metrics.
- Treat proxy target-pass results as idea sources only.
- Do not change production defaults blindly.
- Every strategy change must produce broker-ledger evidence.
- Fix operational/reporting correctness before CAGR tuning.
- Keep generated bulky outputs out of source commits where possible.
- Update `CHANGELOG.md` with every material code/config/workflow change.

## Phase P0 - Operational Trust Fixes

Goal: make the latest user-facing and live-safety outputs reliable before
strategy tuning.

### P0.1 Fix Current CASH Target Reporting

Problem:

- `user_portfolio_reports/*current_operating_holdings_latest.csv` computes
  CASH `recommended_target_weight` from `orders_preview` rows.
- `orders_preview` contains only deltas/action rows, not the full target book.
- Iter 6 shows false values such as Main CASH target `93.4%` and Concentrated
  CASH target `50%` while preview metrics say `target_cash_weight = 0.0`.

Implementation:

- Update `tools/run_user_portfolio_reports.py`.
- For current CASH row, use:
  - first: `preview_metrics["target_cash_weight"]`
  - fallback: `1 - sum(account_ledger_preview/<portfolio>/target_weights.csv.target_weight)`
  - never infer full target cash from `orders_preview.csv`.

Validation:

- Add smoke test using a partial `orders_preview.csv` and full
  `target_weights.csv`.
- Verify CASH target equals preview target cash.

Expected outputs:

- corrected `user_portfolio_reports/main_current_operating_holdings_latest.csv`
- corrected `user_portfolio_reports/concentrated_current_operating_holdings_latest.csv`

### P0.2 Split Actionable Orders From Blocked Deltas

Problem:

- Iter 6 live-safety is blocked because
  `account_ledger_preview/concentrated/orders_preview.csv` contains a blocked
  zero-quantity row.
- Blocked deltas are useful diagnostics but should not be mixed with
  actionable orders.

Implementation:

- Find the tool that writes `account_ledger_preview/*/orders_preview.csv`.
- Emit two files:
  - `orders_preview.csv`: actionable rows only, `quantity > 0`, ready status.
  - `order_deltas_review.csv`: blocked / zero-quantity / informational rows.
- Update `live_trading_safety` to hard-check only actionable orders while still
  warning if blocked review rows exist.

Validation:

- Add smoke test for zero-quantity blocked row.
- Safety should return:
  - no actionable-order error
  - warning/review status for blocked delta file

Expected outputs:

- `account_ledger_preview/{main,concentrated}/orders_preview.csv`
- `account_ledger_preview/{main,concentrated}/order_deltas_review.csv`
- `live_trading_safety/safety_audit_summary.json` no longer blocked for
  non-actionable rows.

### P0.3 Keep Broker-Ledger Current Account Freshness Guard

Problem:

- The stale 2026-03-02 account bug is fixed in Iter 6, but it should not
  regress.

Implementation:

- Add/verify guard that `current_account_last_trade_date` is close to the
  latest recommendation date when tail-row fallback is enabled.
- If a latest target is appended but broker replay cannot fill it, surface a
  hard warning with exact reason.

Validation:

- Smoke test: latest target row at latest cache close fills via same-close tail
  fallback.
- Smoke test: no fallback for historical rows.

## Phase P1 - Honesty And Data Gates

Goal: remove remaining reasons official metrics are still research-grade.

### P1.1 Survivorship Coverage Audit

Problem:

- Iter 6 `audit/survivorship_coverage.json` is blocked because
  `data_raw/historical_universe_membership.csv` is missing or unparseable.

Implementation:

- Locate or generate a historical membership file.
- If true Russell 1000 history is unavailable, label the result clearly as
  proxy and do not flip the hard gate.
- Wire the correct path into the workflow and audit tool.

Validation:

- `coverage_ratio >= 0.85`
- `delisted_count >= 100`
- `hard_gate_flip_eligible = true`

Expected outputs:

- `audit/survivorship_coverage.json`
- `audit/survivorship_coverage_report.md`

### P1.2 Multi-Day Fill Date Stamping

Problem:

- Multi-day fill date stamping remains a known soft accounting issue.

Implementation:

- In broker-ledger replay, stamp each trade with its actual fill date, not the
  minimum fill date across the rebalance batch.

Validation:

- Synthetic price cache with one ticker filling later than another.
- Trade rows must carry individual fill dates.

## Phase P2 - Cash Policy Reconciliation

Goal: stop unexplained cash drag from reducing CAGR in green / breakout regimes.

### P2.1 Add Cash Policy Reconciliation Tool

New tool:

- `tools/run_cash_policy_reconciliation.py`

Inputs:

- `macro_policy_engine/summary.json`
- `orchestrator/unified_target_latest.json`
- `broker_replay/*/metrics.json`
- `broker_replay/*/cash_ledger.csv`
- `account_ledger_preview/*/preview_metrics.json`

Outputs:

- `outputs/cash_policy_reconciliation/cash_policy_reconciliation_summary.json`
- `outputs/cash_policy_reconciliation/cash_target_by_source.csv`
- `outputs/cash_policy_reconciliation/cash_policy_reconciliation_report.md`

Required decomposition:

- macro floor
- macro cash raise gate
- macro confirmation count
- orchestrator residual cash
- mandate capacity cash
- conflict/merge cash
- broker actual cash
- rounding cash
- unfilled-order cash
- average cash by regime
- estimated CAGR drag

Validation:

- Smoke test with macro floor 3% and orchestrator target 30%.
- Tool must flag `target_cash_above_macro_floor_without_confirmation`.

### P2.2 Cash Policy Repair A/B

Do not turn on blindly.

Research-only challenger:

```text
if macro_risk_state in {green, recovery, breakout_growth}
and cash_raise_confirmation_count == 0:
    target_cash = min(current_target_cash, macro_floor + buffer)
    redeploy residual into best eligible leaders
```

Test variants:

- buffer 2%, 4%, 7%
- Main only
- Concentrated only
- Both

Promotion gate:

- broker-ledger CAGR improves
- MaxDD does not worsen by more than 2pp
- turnover does not explode

## Phase P3 - Leader Drop Diagnostics

Goal: make missed leaders visible before adding more factors.

### P3.1 Add Gate-Level Diagnostics

New tool:

- `tools/run_leader_drop_diagnostics.py`

Candidate sources:

- ETF thematic overlay names
- strategic hardware names
- ADR/global names
- recent 1M/3M/6M relative strength leaders
- theme leadership tape names
- missed winners from forward diagnostics
- current replacement challengers

Gate trace:

- universe source
- price cache
- market cap
- liquidity
- `dd_1y`
- fundamental minimum
- ADR/global reliability
- ETF thematic source
- sleeve eligibility
- score rank
- target selection
- broker order feasibility

Outputs:

- `outputs/leader_drop_diagnostics/leader_drop_summary.json`
- `outputs/leader_drop_diagnostics/leader_drop_by_gate.csv`
- `outputs/leader_drop_diagnostics/missed_leader_candidates.csv`
- `outputs/leader_drop_diagnostics/report.md`

Validation:

- Synthetic candidates for:
  - admitted and selected
  - rejected by dd_1y
  - rejected by missing price
  - rejected by fundamental minimum
  - selected but unfilled by broker

### P3.2 Use Diagnostics To Propose Gate Fixes

Rules:

- Gate fixes should first be whitelist-scoped by source and market cap.
- No broad penny-stock or illiquid expansion.
- If a gate is bypassed, a downstream evidence or liquidity requirement must
  remain.

## Phase P4 - Selection Quality Report

Goal: prove whether scores select future winners.

New tool:

- `tools/run_selection_quality_report.py`

Outputs:

- `outputs/selection_quality/factor_ic_by_horizon.csv`
- `outputs/selection_quality/topk_forward_hit_rate.csv`
- `outputs/selection_quality/score_decile_spread.csv`
- `outputs/selection_quality/sleeve_alpha_attribution.csv`
- `outputs/selection_quality/regime_conditioned_ic.csv`
- `outputs/selection_quality/current_hold_vs_replace.csv`
- `outputs/selection_quality/missed_winner_onset.csv`
- `outputs/selection_quality/report.md`

Required horizons:

- 1M
- 3M
- 6M
- 12M

Required dimensions:

- score decile
- sleeve label
- regime
- theme horizon
- market cap bucket
- selected versus not selected
- held versus challenger

Validation:

- Synthetic frame with known forward returns.
- No lookahead: features at date T must only compare to future returns after T.

## Phase P5 - Broker-Compatible Replacement Swap Replay

Goal: turn `ROTATION_REVIEW` into executable, tested swap logic.

New tool:

- `tools/run_broker_replacement_swap_replay.py`

Policy:

```text
if holding is broken:
    if replacement candidate passes gates:
        sell weak holding next close
        buy replacement next close
    elif monster thesis intact:
        hold or trim
    elif macro risk confirmed:
        cash
    else:
        hold
```

Candidate gates:

- score advantage over holding
- short/medium relative strength advantage
- liquidity
- price cache
- theme leadership
- not overextended unless structural-growth exception
- broker order feasibility

Outputs:

- `outputs/broker_replacement_swap_replay/main/metrics.json`
- `outputs/broker_replacement_swap_replay/concentrated/metrics.json`
- `replacement_actions.csv`
- `rejected_replacements.csv`
- `replacement_attribution.csv`

Validation:

- Replacement is never same-ticker.
- Replacement does not create negative cash.
- Replacement obeys target caps.
- Replay uses next-close fills.

Promotion gate:

- Main: improves CAGR by at least 2pp or improves MaxDD by at least 3pp with
  no CAGR loss over 1pp.
- Concentrated: improves CAGR by at least 3pp or MaxDD by at least 3pp with no
  CAGR loss over 2pp.

## Phase P6 - Main V3 Alpha Concentration

Goal: make Main less diluted and more aligned with high-CAGR objective.

Research-only variants:

- target N: 12, 15, 18, dynamic 12-20
- cash in green/recovery: macro floor + 2/4/7%
- no-trade band: score gap threshold
- replacement swap on
- monster hold exception on
- stale leader exit requires price + RS + thesis decay

First milestone:

- Main: 24-26% CAGR and MaxDD around -25%

Second milestone:

- Main: 28-30% CAGR and MaxDD around -20%

Stretch:

- Main: 30% CAGR and MaxDD -15%

## Phase P7 - Concentrated V2

Goal: preserve Iter 6 MaxDD improvement while lifting CAGR.

Research-only variants:

- target N: 3, 4, 5
- single-name cap: 40%, 45%, 50%
- staged entry: 50%, 80%, 100%
- same-theme cap: 70-80% during confirmed theme leadership
- replacement before cash in green regimes
- weekly risk review only; avoid daily whipsaw stops
- monster hold exception

First milestone:

- keep MaxDD near -22% while recovering CAGR to 38-42%

Second milestone:

- push CAGR to 45% with MaxDD no worse than -23%

Stretch:

- 50% CAGR and -18% MaxDD

## Phase P8 - Early Thesis Shadow Engine

Goal: capture SNDK/GEV/PLTR/LITE/INTC/AMD/RKLB-like early moves without
turning sparse non-financial data into biased production signals too early.

Approach:

- universal shallow scan
- deep dive only for:
  - current holdings
  - top candidates
  - replacement candidates
  - high-evidence themes
  - random controls

Scores:

- evidence score
- coverage score
- confidence score

Outputs:

- `data_pit/evidence/universal_company_evidence.parquet`
- `data_pit/evidence/deep_company_evidence.parquet`
- `outputs/evidence_coverage/coverage_audit.csv`
- `outputs/early_thesis_shadow/report.md`

Rule:

- Missing evidence is not zero quality. It lowers confidence.

## Phase P9 - Workflow Split

Goal: stop using 4-8 hour full rebuilds for every idea.

Tiers:

1. local PR validation: seconds
2. sidecar replay against existing artifacts: minutes
3. broker-ledger challenger replay against existing target books: minutes to
   tens of minutes
4. full rebuild: final validation only

Required workflow changes:

- Add manual sidecar-only workflow for:
  - cash policy reconciliation
  - leader drop diagnostics
  - selection quality
  - replacement swap replay
- Full rebuild should remain final evidence, not development loop.

## Recommended Execution Order

1. P0.1 current CASH target reporting fix.
2. P0.2 actionable order split and safety audit unblock.
3. P1.1 survivorship audit path restoration or explicit blocked status.
4. P2.1 cash policy reconciliation tool.
5. P3.1 leader drop diagnostics.
6. P4 selection quality report.
7. P5 replacement swap replay.
8. P6/P7 strategy challengers based on evidence from P2-P5.
9. P8 early thesis shadow engine.
10. P9 workflow split as soon as P2-P5 tools exist.

## First Implementation Batch

The first code batch should be narrow and operational:

- Fix `tools/run_user_portfolio_reports.py` CASH target calculation.
- Split actionable versus blocked order preview rows.
- Add smoke coverage.
- Run:
  - `py -3 tools/run_pr_validation.py`
  - targeted smoke tests for the changed files

Do not start strategy tuning until P0 is clean.

