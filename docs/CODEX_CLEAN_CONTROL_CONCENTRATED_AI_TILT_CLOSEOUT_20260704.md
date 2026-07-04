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

This still misses:

- CAGR target by about `1.25pp`
- MaxDD target by about `0.08pp`

The remaining Concentrated task is not "more AI tilt"; it is either:

1. improve replacement timing/quality without increasing concentration or cash usage,
2. find a tiny MDD-neutral CAGR source orthogonal to replacement-quality, or
3. run a narrow MDD repair that does not erase the replacement-quality CAGR gain.
4. revalidate cash-funded early-entry only if it can be measured on clean-control inputs or isolated from dirty target-book generation.

## Current Verdict

`concentrated_ai_capex_and_sizing_rejected`

Do not retry this exact AI Capex tilt or generic fixed-book sizing on Concentrated unless there is a new PIT evidence feed or a materially different hypothesis. The next viable path is still event-matched replacement-quality, plus a separate, narrowly measured source for the remaining CAGR/MDD gap.
