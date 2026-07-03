# Main Hedge-OFF Baseline Replay - 2026-07-03

## Context

W0 governance confirmed that Main's official policy is long-only. The previous
Main baseline in run `28436307420` included the SH fast-crash hedge, so Main
could not be quoted as a solved long-only sleeve until a fixed-book hedge-OFF
replay was measured.

This document records that replay.

## Method

- Source target book:
  `artifacts/fullrun_28436307420/official/outputs/alphaops_vnext/official_main_target_book.csv`
- Source official metrics:
  `artifacts/fullrun_28436307420/official/outputs/account_evaluation/official_metrics.json`
- Replay price cache:
  `outputs/phase1_replay_goal_test/cache_prices`
- Replay end date:
  `2026-06-29`
- Fill mode:
  `next_close`
- Cost:
  `25 bps per side`
- Integer shares:
  `true`
- Cash-carry:
  `DGS3MO`, 1 business day lag, ACT/365, 50 bps haircut

The local official artifact cache only carries its manifest, so the replay used
the Phase 1 replay cache built from the official target books. The hedge-on
control replay reproduced official Main almost exactly, so this substrate is
acceptable for the hedge-OFF measurement.

Transformation:

- Removed SH hedge rows.
- Moved removed hedge weight to CASH on the same rebalance dates.
- Preserved all non-SH target weights.
- No fullrun.
- No production mutation.
- No live trading.

Removed hedge rows:

| Rebalance date | Ticker | Weight |
|---|---:|---:|
| 2020-02-28 | SH | 7.50% |
| 2020-10-30 | SH | 7.50% |

## Results

| Arm | CAGR | MaxDD | Sharpe | Ending capital |
|---|---:|---:|---:|---:|
| Official hedge-on zero-yield | 34.2667% | -24.1095% | 1.249 | 803,479.17 |
| Hedge-on zero-yield replay | 34.2670% | -24.1089% | 1.249 | 803,494.63 |
| Hedge-on cash-carry replay | 35.1076% | -23.9929% | 1.273 | 839,748.37 |
| Hedge-OFF zero-yield | 34.1780% | -24.0846% | 1.241 | 799,734.92 |
| Hedge-OFF cash-carry | 34.9962% | -24.0026% | 1.264 | 834,868.09 |

Control reproduction:

- CAGR delta vs official: `+0.000365pp`
- MaxDD delta vs official: `+0.000587pp`
- End date matches official: `true`

## Verdict

Status: `main_long_only_research_fail`

Strict target result:

- Main cash-carry CAGR target: `35.0000%`
- Main hedge-OFF cash-carry CAGR: `34.9962%`
- CAGR shortfall: `0.0038pp`
- MDD target: `>= -25.0000%`
- Main hedge-OFF cash-carry MDD: `-24.0026%`
- MDD margin: `+0.9974pp`

Interpretation:

- Main is now measurable as long-only.
- Removing SH does not break the MDD contract.
- Removing SH costs roughly `0.1113pp` CAGR versus hedge-on cash-carry.
- Under strict comparison, Main is not formally solved because CAGR is
  `0.0038pp` below 35%.
- This is a borderline fail, not a structural MDD failure.

## Next Question For External Review

Ask Claude only after sharing this measured result:

1. Should Main be treated as effectively solved given the strict shortfall is
   only `0.0038pp`, or should the project keep the exact `>= 35%` gate?
2. Does this require governance reopening, or is it enough to continue with S1
   sustainment while leaving Main as `borderline_long_only_fail`?
3. Should the next work remain S1 sustainment and W1 control reproduction rather
   than another Main alpha/MDD lever?

## Non-Negotiables

- No production promotion while `pit_universe_label_clean=false`.
- No live trading.
- No fullrun.
- No SH hedge in official Main path unless governance is explicitly reopened.
