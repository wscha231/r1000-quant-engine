# Clean-Control Concentrated AI Capex Tilt Closeout - 2026-07-04

## Status

Research-only fixed-book broker replay. No fullrun, production activation, live trading, or target-book mutation.

The AI Capex momentum tilt was useful for the Main top14 MDD-repair boundary, but it does not solve the Concentrated gap.

## Shared Contract

- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end: `2026-06-29`
- Fill mode: `next_close`
- Cost: `25 bps`
- Price cache: `outputs/phase1_replay_goal_test/cache_prices`
- Cash rate path: `cache_macro/fred_dgs3mo_DGS3MO.parquet`
- Cash carry: `DGS3MO`, 1 business-day lag, 50 bps haircut, ACT/365
- PIT universe production blocker remains active.

## Test 1 - Official Concentrated Clean-Control Book

- Target book: `outputs/target_book_control_repro_root_cause/repro_a/official_concentrated_target_book.csv`
- Output: `outputs/clean_control_concentrated_ai_capex_tilt/concentrated/`

| arm | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | 47.30% | -25.06% | 1.422 | +0.00 | +0.00 | `baseline` |
| AI bottleneck + momentum tilt15 | 46.98% | -25.08% | 1.415 | -0.32 | -0.02 | `reject_oos_cagr_worse` |
| AI bottleneck + momentum + earnings tilt15 | 46.27% | -25.03% | 1.404 | -1.03 | +0.02 | `reject_oos_cagr_worse` |

## Test 2 - Replacement-Quality Book

- Target book: `outputs/clean_control_replacement_counterfactual/concentrated_cash_carry_full_missed/rank_top15_and_revenue_ge10/target_book.csv`
- Output: `outputs/clean_control_concentrated_replacement_plus_ai_capex_tilt/concentrated/`

| arm | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| replacement-quality baseline | 48.75% | -25.08% | 1.467 | +0.00 | +0.00 | `baseline` |
| AI bottleneck + momentum tilt15 | 48.48% | -25.16% | 1.459 | -0.27 | -0.08 | `reject_oos_cagr_worse` |
| AI bottleneck + momentum + earnings tilt15 | 47.67% | -25.09% | 1.447 | -1.08 | -0.02 | `reject_oos_cagr_worse` |

## Interpretation

Concentrated does not need a broad AI Capex tilt inside the already-selected names. The tilt reduces CAGR and does not repair the small MaxDD miss.

The useful Concentrated signal remains the event-matched replacement-quality path:

- Official clean-control baseline: `47.30% / -25.06%`
- Replacement-quality baseline: `48.75% / -25.08%`

## Test 3 - Replacement-Quality + Fixed-Book Sizing

- Tool: `tools/run_fixed_book_concentrated_sizing_ab.py`
- Target book: `outputs/clean_control_replacement_counterfactual/concentrated_cash_carry_full_missed/rank_top15_and_revenue_ge10/target_book.csv`
- Output: `outputs/clean_control_concentrated_replacement_fixed_sizing_ab/`

| arm | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| replacement-quality baseline | 48.75% | -25.08% | 1.467 | +0.00 | +0.00 | `baseline` |
| vol_adjusted_weight | 42.96% | -21.63% | 1.490 | -5.79 | +3.44 | `reject_cagr_damage` |
| max_drawdown_contribution_capped | 43.86% | -24.18% | 1.473 | -4.88 | +0.90 | `reject_cagr_damage` |
| rs_plus_low_vol_blend | 44.07% | -26.19% | 1.386 | -4.68 | -1.11 | `reject` |
| winner_pyramiding_only_if_positive_rs | 44.31% | -26.42% | 1.382 | -4.44 | -1.34 | `reject` |
| equal_weight_with_cash_preserved | 43.86% | -24.37% | 1.470 | -4.89 | +0.71 | `reject_cagr_damage` |

Sizing conclusion: cap-safe fixed-book sizing does not solve the Concentrated gap. Risk-aware arms can repair MaxDD but destroy too much CAGR; RS/pyramiding arms worsen both CAGR and MaxDD. This confirms the useful mechanism is not generic selected-name resizing.

## Remaining Gap

At this point replacement-quality alone still misses:

- CAGR target by about `1.25pp`
- MaxDD target by about `0.08pp`

The remaining Concentrated task is not "more AI tilt" or generic selected-name sizing. It is a narrow, cash-funded early-entry source measured on fixed books.

## Test 4 - Fixed-Book Cash-Funded Early Entry

- Tool: `tools/run_fixed_book_cashfunded_early_entry_ab.py`
- Candidate source: `outputs/target_book_control_repro_root_cause/repro_a/lane_scores_history.csv`
- Candidate variant: `concentrated_N5`
- Signal: `future_winner_scout_score`
- Selection uses PIT columns only; forward labels remain audit-only.
- Entry is non-sticky and funded only from existing cash.
- No target regeneration, no fullrun, no production mutation.

### Official Book Ablation

- Target book: `outputs/phase1_replay_goal_test/official_book_bull_floor_broker_ab/floor_0p0/target_book.csv`
- Output: `outputs/clean_control_concentrated_official_cashfunded_early_entry_ab_v2/`

| arm | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | applied | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| official baseline | 48.83% | -23.79% | 1.445 | +0.00 | +0.00 | 0 | `baseline` |
| entry_w3p0 | 49.62% | -24.66% | 1.455 | +0.79 | -0.87 | 43 | `partial` |
| entry_w5p8 | 50.15% | -25.48% | 1.461 | +1.32 | -1.69 | 43 | `reject_mdd_still_below_target` |
| entry_w3p0_breakout70 | 48.80% | -23.79% | 1.442 | -0.04 | +0.01 | 9 | `reject_no_cagr_edge` |
| entry_w5p8_breakout70 | 48.75% | -23.80% | 1.440 | -0.09 | -0.00 | 9 | `reject_no_cagr_edge` |

Early entry alone is not a policy candidate. It can push official-book CAGR above 50, but it breaks the MaxDD gate.

### Replacement-Quality Book Combination

- Target book: `outputs/clean_control_replacement_counterfactual/concentrated_cash_carry_full_missed/rank_top15_and_revenue_ge10/target_book.csv`
- Output: `outputs/clean_control_concentrated_replacement_cashfunded_early_entry_ab/`

| arm | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | applied | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| replacement-quality baseline | 48.75% | -25.08% | 1.467 | +0.00 | +0.00 | 0 | `baseline` |
| entry_w3p0 | 49.98% | -23.53% | 1.484 | +1.23 | +1.55 | 43 | `partial` |
| entry_w5p8 | 51.04% | -23.93% | 1.498 | +2.29 | +1.15 | 43 | `research_pass_policy_candidate` |
| entry_w3p0_breakout70 | 49.18% | -24.80% | 1.474 | +0.43 | +0.28 | 9 | `partial` |
| entry_w5p8_breakout70 | 49.60% | -24.53% | 1.481 | +0.86 | +0.55 | 9 | `partial` |

The surviving combination is:

1. event-matched replacement-quality,
2. cash-carry research accounting,
3. non-sticky cash-funded early entry at `5.8%`,
4. clean replay-end clamp at `2026-06-29`.

This is the first fixed-book Concentrated combination in this track to exceed both targets:

- Concentrated CAGR target: `51.04% >= 50%`
- Concentrated MaxDD target: `-23.93% >= -25%`

Distribution sanity:

- Applied dates: `43`
- Top ticker by count: `NVDA`, `3` applied dates
- Applied-year distribution: `2019:5`, `2020:7`, `2021:11`, `2023:5`, `2024:9`, `2025:5`, `2026:1`
- Not a one-ticker or one-era result by simple count concentration.

## Current Verdict

`concentrated_combination_replay_pass_candidate`

Do not retry this exact AI Capex tilt or generic fixed-book sizing on Concentrated unless there is a new PIT evidence feed or a materially different hypothesis. The viable Concentrated path is now the narrow combination of event-matched replacement-quality plus cash-funded early entry. This still remains research-only until the policy-path hooks reproduce the fixed-book transformation and the normal fullrun gates are satisfied.
