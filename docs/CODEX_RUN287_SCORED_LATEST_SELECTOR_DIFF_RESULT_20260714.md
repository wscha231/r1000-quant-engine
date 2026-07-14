# Run287 scored-latest selector-diff result — 2026-07-14

## Decision

The 2026-07-13 exact-close `scored_latest` snapshot is suitable for a bounded
holding-versus-research-rank review, but it is not suitable for a registered
selector rerun or a portfolio action.

- score rows: `989`;
- finite, contiguous research ranks: `347` (`1..347`);
- decision-feature-complete rows: `0/989`;
- decision-ranking-allowed rows: `0/989`;
- registered selector runs: `0`;
- target-book changes, orders, fullrun, production, or live trading: `0`.

The score was generated after the 2026-07-13 close. The same close cannot be
used for execution. Any later action remains next-close only and first requires
a decision-complete feature frame, the pinned registered selector, transition
controls, cost checks, and a separate review.

## Marked current portfolios

The paper accounts remain the frozen 2026-07-10 ledgers. Existing share counts
were marked diagnostically to the exact 2026-07-13 close; no trade was assumed.

| Portfolio | Stocks | Marked stock | Marked cash | Ranked holdings | Inside current-position-count top-N | Ineligible holdings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Main | 14 | 88.7467% | 11.2533% | 8 | 4 | 6 |
| Concentrated | 5 | 82.5314% | 17.4686% | 5 | 1 | 0 |

The latest broker-ledger metrics still end on 2026-07-10, not 2026-07-13:

| Portfolio | CAGR | MDD | Metric mode |
| --- | ---: | ---: | --- |
| Main | 34.4032% | -25.3619% | broker-ledger next-close, 25 bps, cash carry |
| Concentrated | 49.0971% | -22.9552% | broker-ledger next-close, 25 bps, cash carry |

Marking one later session does not create a new seven-year CAGR/MDD result.

## Held-name review

Main has six held names that are no longer research eligible in the partial
current frame: `ALAB`, `ON`, `CIEN`, `QCOM`, `HPE`, and `RVMD`. This does not
authorize an exit; the prior-hold transition bridge and a fresh registered
selector were not run. Main also has exact-close alerts in `SNDK`, `NXT`,
`ALAB`, and `MRVL`.

Concentrated has all five names research eligible, but only `MU` is inside the
top five. `SNDK` remains an exact-close alert and `MU` a watch. The marked cash
weight of 17.47% is the residual after the 2026-07-13 decline, not a newly
chosen cash target.

## Rank-gap review pairs

The packet pairs top-ranked unheld names with held names outside the simple
top-N or ineligible set solely to expose where a later registered selector must
spend review effort. It creates 10 Main pairs and four Concentrated pairs.

Examples include:

- Main: `LRCX` versus `CIEN`, `PANW` versus `ALAB`, `GOOGL` versus `NXT`, and
  `VRT` versus `SNDK`;
- Concentrated: `LRCX` versus `TXN`, `WDC` versus `UMC`, `AMAT` versus `SNDK`,
  and `CSCO` versus `AMD`.

These are not replacement recommendations. They omit registered sleeve logic,
prior-hold rules, issuer duplication controls, cash sizing, turnover, tax,
cost, and execution constraints. Every row is stamped `NONE_REVIEW_ONLY` and
`execution_allowed=false`.

## Next gate

Build a bounded, decision-complete exact-close feature frame without fullrun.
Only if its PIT, exact-session, identity, missing-neutral, and hash gates pass
should the previously pinned selector be restored and rerun in advisory mode.
The next output must compare strict versus prior-hold transition scenarios,
include 25/50/100 bps transition cost estimates, and still write no target book
or order.

## Evidence

- `tools/audit_run287_scored_latest_selector_diff.py`
- `tests/run287_scored_latest_selector_diff_smoke.py`
- `outputs/run287_scored_latest_selector_diff_20260714_close_20260713/`
- `outputs/run287_holding_risk_watch_20260714_close_20260713/`
- `cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv`
