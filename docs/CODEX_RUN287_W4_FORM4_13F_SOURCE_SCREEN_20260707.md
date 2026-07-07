# Run287 W4 Form4 + 13F Source Screen

Date: 2026-07-07

Status: research-only source evidence.

No fullrun was dispatched. No hook was added. No threshold tuning was performed. Production promotion, live trading, and public return claims remain blocked.

## Objective

Evaluate whether locally available SEC W4 sources have enough decision-time signal to justify a default-off broker A/B design review:

- Form4: timely insider transaction evidence.
- 13F: slower but broader institutional position-change evidence.
- Combined: fixed blend of the two source advantages, without fitting thresholds to realized winners.

Forward returns are used only as audit labels. Events are included only when available before the rebalance date; same-day disclosures are excluded because this repo does not have an intraday rebalance-time contract.

## Inputs

- Candidate book: `cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/reports/candidate_replay_book.csv`
- Form4 feed: `H:/codex/alphaops_deep_research_context/artifacts/form4_26425151497/sec-form4-daily-26425151497/data_pit/sec/form4_transactions.parquet`
- 13F feed: `H:/codex/alphaops_deep_research_context/artifacts/sec_13f_26387370997/sec-13f-quarterly-26387370997/data_pit/sec/institutional_13f_holdings.parquet`
- OOS start: `2024-07-01`

## Results

| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `w4_form4_score` | false | -0.34% | 0.62% | -1.12% | 490 | 53.27% |
| `w4_13f_score` | true | 0.57% | 0.14% | 1.69% | 2,087 | 53.67% |
| `w4_combined_score` | true | 0.39% | 0.27% | 0.72% | 2,205 | 54.15% |
| `w4_consensus_score` | true | 1.52% | 1.33% | 1.20% | 58 | 50.00% |

Coverage:

- Candidate rows: 47,435
- Candidate tickers: 981
- Form4 signal rows: 4,566 / 212 tickers
- 13F signal rows: 33,643 / 689 tickers
- Combined signal rows: 34,835 / 744 tickers

## Interpretation

Form4 alone is not robust. It is positive in-sample but negative OOS, so it cannot be used as a standalone W4 hook source.

13F is the strongest available W4 source in this screen. It has broad coverage and remains positive OOS.

The combined Form4+13F score is positive across full, IS, and OOS windows. The edge is modest, but it is broad enough to justify a default-off broker A/B design review. It does not justify a fullrun or direct policy hook.

The consensus score has the best high-low spread, but only 58 OOS high-quantile rows. Treat it as a precision overlay candidate, not as a standalone portfolio rule.

## Caveats

- This is source-screen evidence, not broker-ledger evidence.
- The 13F manager-universe file is absent locally, so manager-rank metadata is not applied.
- The cheap 13F screen uses observed add/trim position deltas. Full absent-position exit events require the heavier 13F event builder and are not included here.
- Current results remain survivorship-proxy-labeled and cannot support production promotion.
- A positive source screen only permits a default-off broker A/B design review with the same PIT availability rules.

## Decision

Decision label: `w4_combined_positive_requires_broker_ab_review`

Next allowed action:

- Design a cheap default-off broker A/B review for `w4_combined_score`.
- Keep Form4-only rejected as standalone source.
- Keep 13F-only and Form4+13F combined as candidate source families for review.

Forbidden actions:

- Do not dispatch a fullrun.
- Do not add a live hook.
- Do not tune thresholds against winning dates.
- Do not promote to production while `pit_universe_label_clean=false`.
