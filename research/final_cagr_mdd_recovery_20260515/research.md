# Final CAGR / MDD Recovery Research - 2026-05-15

## Scope

This document consolidates the latest full-run evidence and the user discussion
around CAGR improvement, MaxDD reduction, early leader discovery, broker-ledger
realism, cash policy, and operational reports.

Implementation is intentionally deferred. This file is the research step only.

## Source Of Truth

Repository:

- Remote: `https://github.com/wscha231/r1000-quant-engine.git`
- Branch: `claude/short-rs-intc-etf-overlay`
- Current local HEAD at review time: `19e1a59`
- Important latest measurement run: `25873418413`
- Iter 6 measured code: `60fe558`
- Local artifact root:
  `_run_25873418413_artifacts/full-rebuild-global_alpha_universe-25873418413/`

Important correction:

- Some draft notes referenced run `25860138864` / head `d95933e` as the latest
  baseline. That is Iter 5, not the final latest measurement.
- The latest official full-run evidence is Iter 6, run `25873418413`, measured
  at head `60fe558`.
- The GitHub Actions conclusion is `failure`, but the failed step is Google
  Drive sync. Core rebuild, verdict, sidecars, artifact upload, Telegram, and
  bot commit completed.

Official metric mode:

- `broker_ledger_next_close`
- adjusted close price mode
- integer shares
- no leverage
- 25 bps cost per side
- 100,000 USD starting capital

Legacy monthly-weight and proxy results are research context only.

## Latest Official Baseline

Artifacts:

- `broker_replay/main/metrics.json`
- `broker_replay/concentrated/metrics.json`

| Portfolio | CAGR | MaxDD | Sharpe | Avg Cash | Trades | End Date | Verdict |
|---|---:|---:|---:|---:|---:|---|---|
| Main | 18.44% | -31.93% | 0.848 | 14.70% | 2873 | 2026-05-14 | fail |
| Concentrated | 35.10% | -22.68% | 1.300 | 17.90% | 649 | 2026-05-14 | fail |

User targets:

| Portfolio | CAGR Target | MaxDD Target | Current Gap |
|---|---:|---:|---|
| Main | 30%+ | -15% or better | far below both |
| Concentrated | 50%+ | -18% or better | CAGR short; MaxDD close but not there |

Interpretation:

- Concentrated made real progress versus prior broker-ledger results, mainly on
  MaxDD.
- Main deteriorated into a low-CAGR / still-high-drawdown profile.
- Concentrated is the nearer candidate for an investable high-performance
  product; Main needs a larger redesign.

## Proxy / Research Versus Broker-Ledger Gap

Artifacts:

- `portfolio_goal_search/goal_search_summary.json`
- `broker_gap_attribution/gap_attribution_summary.json`

Best research/proxy candidates:

| Portfolio | Candidate | CAGR | MaxDD | Sharpe | Production Valid |
|---|---|---:|---:|---:|---|
| Main | `main_v2_position_aware_risk_proxy` | 37.23% | -12.70% | 1.783 | false |
| Concentrated | `concentrated_position_risk_proxy` | 59.11% | -13.70% | 1.955 | false |

Best production-compatible candidates:

| Portfolio | Candidate | CAGR | MaxDD | Sharpe | Production Valid |
|---|---|---:|---:|---:|---|
| Main | `main_broker_crisis_reentry_fast_reentry` | 19.68% | -31.91% | 0.851 | true |
| Concentrated | `concentrated_broker_ledger_replay` | 35.10% | -22.68% | 1.300 | true |

Gap attribution:

| Portfolio | Monthly Diagnostic CAGR | Broker CAGR | Monthly Diagnostic MaxDD | Broker Daily MaxDD |
|---|---:|---:|---:|---:|
| Main | 35.52% | 18.44% | -14.62% | -31.93% |
| Concentrated | 57.30% | 35.10% | -13.66% | -22.68% |

Main broker gap drivers:

- average names: 26.43
- average target turnover: 55.14%
- gross traded on starting capital: 138x
- fees: about 34,566 USD
- average cash: 14.70%
- monthly/proxy drawdown materially understates intramonth account drawdown

Concentrated broker gap drivers:

- average names: 3.00
- average target turnover: 61.19%
- gross traded on starting capital: 276x
- fees: about 69,041 USD
- average cash: 17.90%
- monthly/proxy accounting still overstates executable performance

Research conclusion:

The selection layer may contain useful alpha, but a large portion is lost when
translated into an account-like trading path. The next work should focus on
the conversion layer: lower churn, better replacement logic, cash discipline,
and broker-compatible execution timing.

## Latest Portfolio Freshness And User Outputs

Artifacts:

- `user_portfolio_reports/summary.json`
- `user_portfolio_reports/main_current_operating_holdings_latest.csv`
- `user_portfolio_reports/main_recommendation_latest.csv`
- `user_portfolio_reports/concentrated_current_operating_holdings_latest.csv`
- `user_portfolio_reports/concentrated_recommendation_latest.csv`

Positive result:

- As-of date is `2026-05-14`.
- Main current operating account last replay trade date is `2026-05-14`.
- Concentrated current operating account last replay trade date is
  `2026-05-14`.
- Stale days are `0` for both portfolios.

This means the previous "stuck at 2026-03-02" operating portfolio problem is
structurally closed in Iter 6.

Remaining user-output bug:

- `user_portfolio_reports/*current_operating_holdings_latest.csv` computes the
  CASH row's `recommended_target_weight` incorrectly.
- Example from Iter 6:
  - Main preview metrics `target_cash_weight` is `0.0`, but the current report
    CASH row shows `recommended_target_weight = 0.9342`.
  - Concentrated preview metrics `target_cash_weight` is `0.0`, but the current
    report CASH row shows `recommended_target_weight = 0.5`.
- Root cause: the report estimates target cash from `orders_preview` target
  weights. `orders_preview` contains only deltas/action rows, not the full
  target book. The report should read target cash from `preview_metrics` or
  `account_ledger_preview/*/target_weights.csv`.

This is a reporting bug, not proof that broker-ledger performance metrics are
wrong. It must be fixed before user-facing files are trusted.

## Safety Audit Status

Artifact:

- `live_trading_safety/safety_audit_summary.json`

Status:

- `blocked`
- `error_count = 2`

Errors:

- `concentrated_orders_nonpositive_qty`
- `concentrated_orders_blocked`

Cause:

- `account_ledger_preview/concentrated/orders_preview.csv` includes a blocked
  FIX buy order with `quantity = 0.0`.
- The preview metrics show `blocked_order_count = 1`, `ready_order_count = 0`.

Research conclusion:

The system needs to separate actionable orders from informational deltas:

- actionable order file: ready orders only, positive quantity only
- blocked/review deltas: allowed in a separate report
- safety audit should hard-check actionable orders, not informational rows

This is P0 because it affects operational trust.

## Cash Policy Contradiction

Relevant evidence from latest run:

- macro policy state: green / breakout-growth style
- recommended cash floor: about 3%
- cash raise gate: none
- cash raise confirmations: 0
- Main broker average cash: 14.70%
- Concentrated broker average cash: 17.90%

The draft also notes an orchestrator target cash around 30% in recent output.
The key structural issue is still valid:

Macro policy can recommend low cash while portfolio construction and mandate
capacity leave a large residual cash target or average cash drag.

This is a CAGR problem:

- Cash can protect drawdowns in confirmed bear/crisis regimes.
- But in green or breakout-growth regimes, unexplained residual cash directly
  reduces CAGR and may prevent participation in leader bubbles.

Needed diagnosis:

- macro cash floor
- orchestrator residual cash
- capacity-based unallocated cash
- merge-conflict cash
- broker rounding cash
- unfilled-order cash
- defensive-rule cash
- historical average cash by regime

## Early Leader Discovery Failure

The recent branch work found multiple admission-layer problems:

- INTC-class strategic hardware candidates were cut before scoring by universe
  or drawdown filters.
- ETF thematic overlay candidates such as quantum, eVTOL, space, AI speculative,
  and genomics names could be filtered before scoring.
- Commit `d95933e` added an ETF thematic overlay `dd_1y` bypass for mktcap
  above 1B.

Research conclusion:

Missing leaders is not only a model-scoring problem. It is often an admission
and data-coverage problem:

1. Candidate never enters the universe.
2. Candidate has no price cache or stale cache.
3. Candidate fails market-cap/liquidity gates.
4. Candidate fails `dd_1y` because early winners often emerge from deep
   drawdowns.
5. Candidate fails fundamental minimum because the thesis is still early.
6. Candidate gets scored but not selected.
7. Candidate is selected but not bought in broker replay.

Needed artifact:

- `outputs/leader_drop_diagnostics/leader_drop_by_gate.csv`
- `outputs/leader_drop_diagnostics/missed_leader_candidates.csv`
- `outputs/leader_drop_diagnostics/report.md`

## Selection Quality Needs Direct Measurement

The system should answer whether its scores predict forward returns before
debating portfolio construction.

Needed questions:

- Do top score deciles outperform lower deciles over 1M, 3M, 6M, and 12M?
- Does `future_winner` have positive forward alpha after costs?
- Does `early_scout` enter early enough, or only after the move?
- Do stale leader penalties correctly remove lagging former winners?
- Does replacing a current holding with a challenger improve forward returns?
- Which features have stable information coefficient by regime?

Needed artifact:

- `outputs/selection_quality/factor_ic_by_horizon.csv`
- `outputs/selection_quality/topk_forward_hit_rate.csv`
- `outputs/selection_quality/score_decile_spread.csv`
- `outputs/selection_quality/sleeve_alpha_attribution.csv`
- `outputs/selection_quality/regime_conditioned_ic.csv`
- `outputs/selection_quality/current_hold_vs_replace.csv`
- `outputs/selection_quality/missed_winner_onset.csv`
- `outputs/selection_quality/report.md`

## Rotation Review Is Not Enough

The user wants weak holdings to be replaced by stronger leaders when the regime
is favorable. Current outputs can label `ROTATION_REVIEW`, but a review label is
not a broker-compatible swap.

Needed broker-compatible rule:

```text
if holding is broken:
    if replacement candidate passes leader / liquidity / entry / risk gates:
        sell holding at next close
        buy replacement at next close
    elif monster thesis intact:
        hold or trim
    elif macro risk confirmed:
        cash
    else:
        hold
```

Cash should not be the default answer in green / breakout-growth regimes.
Replacement should be preferred when a better leader is available.

Needed tool:

- `tools/run_broker_replacement_swap_replay.py`

Needed outputs:

- `outputs/broker_replacement_swap_replay/main/metrics.json`
- `outputs/broker_replacement_swap_replay/concentrated/metrics.json`
- trade-level evidence, replacement reasons, and rejected-swap reasons

## Main Recovery Direction

Current Main:

- CAGR: 18.44%
- MaxDD: -31.93%
- Sharpe: 0.848
- average names in target-forward diagnostic: 26.43

Problems:

- too much diversification for the user's high-CAGR objective
- high turnover
- poor conversion from monthly diagnostic alpha to broker-ledger alpha
- Mode Y and defensive filters reduce CAGR without solving MDD enough
- current construction may be too broad and too cash-heavy

Research direction:

- Main v3 alpha concentration
- target N around 12 to 18 rather than 26+
- macro cash floor near 3-7% in green/recovery unless confirmed risk
- no-trade band to reduce churn
- replacement swap before cash in green regimes
- monster-hold exception so winners are not sold too early
- stale-leader exits only when price, relative strength, and thesis decay align

Near-term milestone:

- first improve from 18.44% / -31.93% toward 24-26% / -25%
- then push toward 28-30% / -20%
- only then revisit the 30% / -15% stretch target

## Concentrated Recovery Direction

Current Concentrated:

- CAGR: 35.10%
- MaxDD: -22.68%
- Sharpe: 1.300

Progress:

- Concentrated MaxDD improved materially versus prior broker-ledger runs.
- It is now the closest portfolio to target.

Problems:

- CAGR still far from 50%.
- Safety audit is blocked by non-actionable zero-quantity order preview.
- Average cash 17.90% is high for a 50% CAGR target.
- Trade count jumped from earlier runs; this needs attribution so F13 did not
  accidentally activate too many historical rebalance rows.

Research direction:

- keep 3-5 names
- allow high single-name cap only for confirmed leaders
- staged entry: 50/80/100 exposure
- same-theme cap can be high in confirmed theme leadership regimes
- replacement before cash when macro is green
- weekly risk review may help, but daily stops are too costly
- monster hold exception should prevent premature exits

Near-term milestone:

- preserve the new -22% MaxDD region while recovering CAGR toward 38-42%
- then test whether more aggressive leader concentration can move toward 45-50%

## Early Thesis / Non-Financial Data Strategy

The user wants the engine to detect names like SNDK, GEV, PLTR, LITE, INTC,
AMD, RKLB, and future sector leaders before they are obvious in mature
financial statements.

This requires evidence beyond conventional financials:

- ETF look-through / holdings attention
- sector/theme leadership
- governance/catalyst change
- customer/adoption/capex signals
- earnings acceleration and revisions
- price-volume confirmation
- relative strength and dollar-volume surge

But non-financial data is sparse and biased. It should begin as shadow evidence:

- universal shallow scan for all candidates
- deeper evidence scan for current holdings, top candidates, challengers,
  high-evidence themes, and random controls
- missing data should reduce confidence, not automatically reduce quality

Needed outputs:

- `data_pit/evidence/universal_company_evidence.parquet`
- `data_pit/evidence/deep_company_evidence.parquet`
- `outputs/evidence_coverage/coverage_audit.csv`
- `outputs/early_thesis_shadow/report.md`

## Survivorship And Data Honesty

Artifact:

- `audit/survivorship_coverage.json`

Current Iter 6 status:

- `status = blocked`
- reason: missing / unparseable
  `data_raw/historical_universe_membership.csv`
- `hard_gate_flip_eligible = false`

This means the handoff claim that survivorship audit can be flipped in 5
minutes is too optimistic unless the membership file exists elsewhere and only
needs to be restored.

Research conclusion:

Before promoting broker-ledger results to production-grade, solve:

- historical universe membership source
- delisted coverage count
- coverage ratio
- audit path in workflow

Until then, results are materially better than old proxy metrics but still not
fully production-grade.

## Workflow Bottleneck

Full rebuild remains too expensive for iterative strategy development.

Current issue:

- full run can take 4-8 hours
- GitHub Actions failure can be caused by GDrive sync after core success
- large artifacts and cache suffix changes cause slow reruns

Needed workflow tiers:

1. PR validation: seconds to minutes
2. sidecar-only replay on existing artifacts: minutes
3. broker-ledger challenger replay on existing target books: minutes to tens of
   minutes
4. full rebuild: final validation only

Development should not wait for a full run for every small policy change.

## Required New Tools / Artifacts

Recommended tools:

- `tools/run_cash_policy_reconciliation.py`
- `tools/run_leader_drop_diagnostics.py`
- `tools/run_selection_quality_report.py`
- `tools/run_broker_replacement_swap_replay.py`

Recommended outputs:

- `outputs/cash_policy_reconciliation/*`
- `outputs/leader_drop_diagnostics/*`
- `outputs/selection_quality/*`
- `outputs/broker_replacement_swap_replay/{main,concentrated}/*`

## Immediate Priority

P0: Fix operational/report trust issues.

1. Split actionable orders from blocked/informational deltas.
2. Fix user portfolio current CASH `recommended_target_weight` calculation.
3. Keep blocked orders in reports, but do not include them in actionable order
   files that safety audit treats as tradeable.

P1: Diagnose why alpha disappears in broker-ledger conversion.

1. Cash policy reconciliation.
2. Leader drop diagnostics.
3. Selection quality report.

P2: Improve actual strategy.

1. Broker-compatible replacement swap replay.
2. Main v3 alpha concentration.
3. Concentrated v2 staged sizing and replacement before cash.

## Final Research Judgment

The branch made meaningful progress:

- Official account-like evaluation now reaches 2026-05-14.
- Current operating holdings are no longer stuck at 2026-03-02.
- Concentrated MaxDD improved materially.
- The system found and partially fixed an important leader-admission problem.

But the target is not yet reached:

- Main is weak.
- Concentrated is closer but still below the 50% / -18% target.
- Research/proxy alpha still fails to convert cleanly into broker-ledger
  performance.
- User-facing current CASH target reporting has a bug.
- Live trading safety is blocked.
- Survivorship hard gate remains blocked.

The next phase should not add more standalone factors blindly. It should make
leader admission, selection quality, cash policy, and replacement swaps
measurable under the broker-ledger next-close framework.
