# Run287 Concentrated Next Alpha Search - 2026-07-08

## Verdict

`concentrated_next_alpha_search_rejected_current_data`

No Concentrated candidate was found from the remaining current-data sources. This is research-only evidence: no fullrun was dispatched, no alpha hook was added, no threshold/grid tuning was performed, and production promotion remains blocked while `pit_universe_label_clean=false`.

## Measurement Contract

- Source run: `28725350727`
- Target book: run287 official fixed Concentrated book
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-02`
- Cash rate: `DGS3MO`, 1-day lag, ACT/365, 50 bps haircut
- Runner parity status: `parity_documented_gap`
- Measurement acceptance allowed: `false`

Baseline: `48.41% CAGR / -22.96% MDD / Sharpe 1.49`.

## New Tests

| Source | Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | OOS dCAGR pp | OOS2 dCAGR pp |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `w4_consensus_score` | `w4_consensus_top_quintile_tilt05` | `blocked_no_signal` | 48.41% | -22.96% | +0.00 | +0.00 | +0.00 | +0.00 |
| `w4_consensus_score` | `w4_consensus_top_quintile_tilt10` | `blocked_no_signal` | 48.41% | -22.96% | +0.00 | +0.00 | +0.00 | +0.00 |
| `evidence_fusion_score` | `evidence_fusion_top_quintile_tilt05` | `reject_oos_cagr_worse` | 48.79% | -22.27% | +0.38 | +0.69 | -2.94 | -1.60 |
| `evidence_support_score` | `evidence_support_top_quintile_tilt05` | `reject_oos_cagr_worse` | 47.93% | -22.31% | -0.47 | +0.65 | -4.47 | -2.49 |
| `institutional_evidence_score` | `institutional_evidence_top_quintile_tilt05` | `reject_oos_cagr_worse` | 47.13% | -22.44% | -1.27 | +0.52 | -3.84 | -2.29 |
| `sec_combined_evidence_score` | `sec_combined_evidence_top_quintile_tilt05` | `reject_oos_cagr_worse` | 48.71% | -22.82% | +0.31 | +0.13 | -0.42 | -0.63 |
| `smart_money_confirmation_score` | `smart_money_confirmation_top_quintile_tilt05` | `reject_oos_cagr_worse` | 46.88% | -22.44% | -1.53 | +0.52 | -5.40 | -3.14 |
| `smart_money_shadow_score` | `smart_money_shadow_top_quintile_tilt05` | `reject_oos_cagr_worse` | 48.61% | -22.58% | +0.20 | +0.38 | -2.07 | -1.22 |

The best full-window non-candidate was `evidence_fusion_score` at `48.79% CAGR / -22.27% MDD`, still below the 50% target and rejected because OOS/OOS2 CAGR deteriorated. W4 consensus produced no weight change because `w4_consensus_score` is zero on the official Concentrated book.

## Signal Availability On Official Book

| Column | Nonzero rows / non-cash rows | P80 | Max |
| --- | ---: | ---: | ---: |
| `w4_form4_score` | 46 / 463 | 0.0000 | 0.0000 |
| `w4_13f_score` | 394 / 463 | 1.0000 | 1.0000 |
| `w4_combined_score` | 394 / 463 | 0.4000 | 0.4000 |
| `w4_consensus_score` | 0 / 463 | 0.0000 | 0.0000 |
| `w4_sec_score` | 394 / 463 | 0.4000 | 0.4000 |
| `evidence_fusion_score` | 463 / 463 | 0.3114 | 0.4080 |
| `smart_money_shadow_score` | 392 / 463 | 0.1253 | 0.3276 |
| `smart_money_confirmation_score` | 405 / 463 | 0.1273 | 0.2873 |
| `sec_combined_evidence_score` | 409 / 463 | 0.2838 | 0.4325 |
| `institutional_evidence_score` | 405 / 463 | 0.5074 | 0.8697 |
| `evidence_support_score` | 462 / 463 | 2.4466 | 3.0000 |
| `etf_holdings_score` | 0 / 463 | 0.0000 | 0.0000 |
| `etf_theme_leadership_score` | 0 / 463 | 0.0000 | 0.0000 |

## Already Closed Current-Data Routes

- Pure 13F: PIT-clean and source-positive, but fixed-book A/B rejected on OOS2 and full-window CAGR (`docs/CODEX_13F_FIXEDBOOK_AB_RESULT_20260708.md`).
- Financial actual/proxy scores: rejected by fixed-book broker A/B; actual/proxy fields are not true revision/guidance data (`docs/CODEX_RUN287_CONCENTRATED_FINANCIAL_PROXY_AB_RESULT_20260708.md`).
- Form4 + 13F + financial + technical + macro fusion: rejected for Concentrated because OOS CAGR deteriorated (`docs/CODEX_RUN287_MULTISOURCE_FUSION_BROKER_AB_20260708.md`).

## Data Availability

- True PIT analyst estimate revision feed: blocked, local row count `0`.
- True PIT company guidance direction feed: blocked, local row count `0`.
- Earnings-call keyword feed: code/tests exist, but no usable PIT source feed was found locally.
- Current available sources are SEC Form4, SEC 13F, SEC actual/proxy financial columns, and target-book evidence columns; these have now failed the run287 fixed-book Concentrated broker gate.

## Next Action

Do not dispatch a fullrun from these results. Do not tune percentiles or tilt strengths against this result set. The next defensible Concentrated path is to ingest a true PIT earnings/guidance/revision or earnings-call keyword feed with `available_from <= rebalance_date`, then run a fresh source screen before any fixed-book A/B or hook design.
