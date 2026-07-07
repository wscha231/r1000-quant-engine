# CODEX_RUN287_MULTISOURCE_FUSION_BROKER_AB_20260708

## Verdict

`growth_confirmation_score` is rejected as a run287 fixed-book broker A/B candidate.

This is research-only evidence. It did not dispatch a fullrun, did not add a policy hook, did not tune thresholds, did not mutate production state, and did not enable live trading.

## Measurement Contract

- Source run: `28725350727`
- Target books: official run287 fixed books
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-02`
- Price cache: `H:/codex/tmp_r1000_grossfloor_20260625/outputs/run287_price_cache_full_candidate/cache_prices`
- Cash rate: `DGS3MO`, 1 trading-day lag, ACT/365, 50 bps haircut
- Runner parity status: `parity_documented_gap`
- PIT universe label clean: `false`
- Production promotion allowed: `false`
- Measurement acceptance allowed: `false`

The requested latest replay date was aligned to the latest observed date in the available price cache, `2026-07-02`. A later date is not valid for this artifact because the broker replay engine blocks unobserved replay end dates.

## Score Join Coverage

The source-screen candidate book did not contain same-day score rows for the final `2026-07-02` target rows. The broker A/B tool therefore used the latest ticker score available on or before the target rebalance date and stamped the join mode in the enriched target books. This is decision-time safe and avoids neutral-fill rows becoming artificial donors or winners.

| Portfolio | Non-cash rows | Exact rows | As-of prior rows | Missing rows |
| --- | ---: | ---: | ---: | ---: |
| Main | 1121 | 1107 | 14 | 0 |
| Concentrated | 463 | 458 | 5 | 0 |

## Broker A/B Result

| Portfolio | Arm | Verdict | CAGR | MaxDD | Delta CAGR pp | Delta MDD pp | Contract pass |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Main | baseline | `baseline` | 33.81% | -25.36% | +0.00 | +0.00 | false |
| Main | growth confirmation tilt 5% | `reject_mdd_worse` | 34.87% | -25.62% | +1.06 | -0.26 | false |
| Main | growth confirmation tilt 10% | `reject_mdd_worse` | 35.79% | -25.93% | +1.98 | -0.56 | false |
| Concentrated | baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | false |
| Concentrated | growth confirmation tilt 5% | `reject_oos_cagr_worse` | 47.52% | -22.88% | -0.89 | +0.07 | false |
| Concentrated | growth confirmation tilt 10% | `reject_oos_cagr_worse` | 46.53% | -22.55% | -1.87 | +0.41 | false |

## Interpretation

Main: the fusion tilt has a real CAGR effect, but it buys that effect by worsening the already-failed 2022 drawdown. The 10% tilt clears 35% CAGR but fails the -25% MDD side of the contract by a wider margin than baseline.

Concentrated: the same tilt does not transfer. It improves drawdown slightly but destroys OOS CAGR and moves the sleeve farther from the 50% CAGR target.

This closes the Form4 + 13F + financial + technical + macro fusion path as a direct fixed-book tilt candidate for run287. It remains useful as diagnostic source-screen evidence, but it should not be converted into a default-off hook without a new ex-ante design and a new cheap evidence package.

## Next Action

Do not dispatch a fullrun from this result. Do not tune the 5%/10% tilt or choose a different percentile post hoc.

The next defensible path is a narrow loss-attribution audit on the Main 2022 drawdown for the names overweighted by the growth-confirmation tilt, plus a separate search for Concentrated improvement that does not reuse this failed direct tilt.

Production remains blocked while `pit_universe_label_clean=false` and runner parity is not exact.
