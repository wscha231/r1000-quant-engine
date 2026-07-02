# Phase 2 Concentrated Gap Report - 2026-07-02

## Context

Phase 1 established a new research accounting baseline:

```text
Concentrated + cash-carry: 48.83% CAGR / -23.79% MaxDD
Remaining target gap: +1.17pp CAGR
```

Production remains blocked by `pit_universe_label_clean=false`. Cash-carry is
still a research/accounting mode until an explicit accounting contract is
accepted.

This report covers fixed official-book Phase 2 replay tests. These tests do not
regenerate AlphaOps vNext target books and do not dispatch a fullrun.

## Replay-End Guard

`tools/run_broker_ledger_replay.py` now exposes the skipped signal dates when
next-close fills would occur after `replay_end_date`.

Required behavior is covered by `tests/broker_cash_carry_smoke.py`:

```text
signal date: 2026-01-06
next close fill: 2026-01-07
replay_end_date: 2026-01-06
expected: skip 2026-01-07 trade and record replay_end_skipped_signal_dates
```

The official-book replays below recorded:

```text
actual_equity_curve_end_date = 2026-06-29
end_date_matches_official = true
replay_end_skipped_rebalance_count = 1
```

## Fixed Official Book Hold / Exit Timing A/B

Output:

```text
outputs/phase2_concentrated_gap/fixed_book_hold_exit_timing_ab_v2_20260702
```

| Arm | Applied | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline_cash_carry | 0 | 48.83% | -23.79% | 1.445 | 0.00pp | 0.00pp | control |
| delay_target_exit_one_cycle | 223 | 43.16% | -31.59% | 1.287 | -5.67pp | -7.79pp | reject |
| delay_target_exit_only_if_leader | 216 | 43.05% | -31.60% | 1.285 | -5.78pp | -7.81pp | reject |
| partial_replace_50 | 223 | 46.97% | -27.40% | 1.388 | -1.87pp | -3.61pp | reject |
| accelerate_exit_if_deteriorating | 0 | 48.83% | -23.79% | 1.445 | 0.00pp | 0.00pp | no-op |
| keep_winner_if_rs_positive | 216 | 43.05% | -31.60% | 1.285 | -5.78pp | -7.81pp | reject |

Implementation note: the one-cycle hold overlay was corrected so research
extension rows do not become the next month's official prior state. This
prevents accidental indefinite carry.

Interpretation:

- Broadly delaying exits is not the missing +1.17pp.
- It reduces cash and keeps stale names too long, damaging both CAGR and MDD.
- The only no-op arm (`accelerate_exit_if_deteriorating`) did not find eligible rows under the fixed official-book fields.

## Fixed Official Book Cap-Safe Sizing A/B

Output:

```text
outputs/phase2_concentrated_gap/fixed_book_concentrated_sizing_ab_v2_20260702
```

| Arm | Applied | Cap breaches | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline_cash_carry | 0 | 0 | 48.83% | -23.79% | 1.445 | 0.00pp | 0.00pp | control |
| vol_adjusted_weight | 453 | 0 | 38.00% | -20.21% | 1.352 | -10.83pp | +3.58pp | reject |
| max_drawdown_contribution_capped | 453 | 0 | 40.55% | -21.26% | 1.371 | -8.28pp | +2.53pp | reject |
| rs_plus_low_vol_blend | 453 | 0 | 41.38% | -24.13% | 1.295 | -7.46pp | -0.33pp | reject |
| winner_pyramiding_only_if_positive_rs | 453 | 0 | 41.75% | -24.40% | 1.293 | -7.08pp | -0.61pp | reject |
| equal_weight_with_cash_preserved | 453 | 0 | 40.66% | -21.31% | 1.371 | -8.18pp | +2.48pp | reject |

Implementation note: the sizing harness now enforces cap reduction as well as
cap-limited filling. If cap capacity is infeasible, residual stock gross is
left in cash instead of allowing a cap breach.

Interpretation:

- Cap-safe risk-adjusted sizing improves MaxDD in defensive variants but gives up too much CAGR.
- RS/pyramiding variants also fail because they lose CAGR and do not improve MaxDD.
- The current Concentrated sizing appears to be intentionally winner-concentrated; flattening or volatility de-risking removes too much right-tail return.

## Phase 2 Verdict

No replay-stage candidate currently justifies a fullrun.

Rejected:

- broad bull-floor / gross-floor
- broad hold-extension / exit-delay
- cap-safe risk-adjusted sizing

## AI Capex / EPS Replacement-Quality Diagnostic

Output:

```text
outputs/phase2_concentrated_gap/ai_capex_bottleneck_screen_20260702
```

This is a cheap screen, not broker evidence. It uses 63d/126d forward excess only
as an audit label and does not rank live candidates with forward returns.

| Group | Split | Count | Mean 126d excess | Positive rate | Buckets | Tickers |
|---|---|---:|---:|---:|---:|---:|
| target: AI bottleneck + revision positive + momentum | full | 98 | +9.10% | 63.27% | 5 | 31 |
| target: AI bottleneck + revision positive + momentum | OOS | 37 | +14.23% | 72.97% | 4 | 10 |
| best: AI bottleneck + revision nonpositive + momentum | full | 56 | +10.61% | 62.50% | 4 | 20 |
| best: AI bottleneck + revision nonpositive + momentum | OOS | 34 | +17.10% | 73.53% | 4 | 12 |

Interpretation:

- The missing Concentrated CAGR is more likely a replacement-quality / candidate-quality problem than a gross, broad hold, or cap-safe sizing problem.
- True vendor EPS/guidance feed is still missing; the screen uses `actual_results_score` fallback for some rows and therefore remains diagnostic.
- A future hook must compare AI bottleneck + momentum against AI bottleneck + momentum + true EPS/guidance confirmation once the feed exists.

Surviving direction:

- selection-side quality, but only after target-generation control reproduction is fixed
- AI-capex bucket / earnings-revision confirmation as a diagnostic
- narrow replacement-quality logic, not broad cash redeploy or broad hold

## Next Engineering Steps

1. Keep cash-carry as the research baseline pending governance approval.
2. Do not run a fullrun until a replay-stage candidate reaches Concentrated CAGR >= 50% with MaxDD >= -25%.
3. Complete target-generation input snapshot and control-reproduction work before trusting regenerated selection-side A/B.
4. Run AI-capex bucket / EPS revision diagnostics to identify whether the missing +1.17pp is a replacement-quality problem rather than a sizing or cash problem.
