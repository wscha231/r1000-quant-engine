# Run287 Concentrated Alpha Source Packet

This is a Claude/GitHub-visible review packet. It is source-screen evidence only.

## Verdict

- status: `completed`
- source_screen_decision_label: `w4_combined_positive_requires_broker_ab_review`
- positive_signals: `w4_13f_score, w4_combined_score, w4_consensus_score`
- miss_set_rows: `51`
- miss_set_mean_forward_return_audit_only: `2.90%`
- W4 broker A/B decision: `no_positive_broker_ab_candidate`

## Non-Negotiables

- No fullrun was dispatched.
- No hook was added.
- No threshold tuning was performed.
- Forward returns are audit labels only and are not used for ranking.
- Production promotion remains blocked.

## Source Screen Summary

| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| w4_form4_score | false | -0.34% | 0.62% | -1.12% | 490 | 53.27% |
| w4_13f_score | true | 0.57% | 0.14% | 1.69% | 2087 | 53.67% |
| w4_combined_score | true | 0.39% | 0.27% | 0.72% | 2205 | 54.15% |
| w4_consensus_score | true | 1.52% | 1.33% | 1.20% | 58 | 50.00% |

## Broker A/B Context

| Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | OOS dCAGR pp |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | `baseline` | 48.41% | -22.96% | +0.00 | +0.00 | +0.00 |
| w4_sec_top_quintile_tilt05 | `reject_oos_cagr_worse` | 49.37% | -22.60% | +0.97 | +0.35 | -1.21 |
| w4_sec_top_quintile_tilt10 | `reject_oos_cagr_worse` | 49.56% | -22.26% | +1.16 | +0.70 | -3.06 |

## Claude Review Ask

1. Red-team whether the positive `w4_13f_score`, `w4_combined_score`, or sparse `w4_consensus_score` is clean enough to justify a default-off fixed-book broker A/B.
2. Focus the next design on the 51-row `cap_or_replacement` miss-set, not the full universe.
3. Reject Form4-only as a candidate unless Claude finds a data-contract issue in the current screen; OOS high-low is negative.
4. Treat the existing W4 SEC broker A/B as near-miss/negative evidence because OOS CAGR worsened despite full-window CAGR improvement.
5. Do not recommend a hook or fullrun before a new fixed-book broker A/B passes absolute CAGR/MDD and SPY-relative diagnostics.

## Files

- `outputs/run287_conc_alpha_source_packet/summary.json`
- `outputs/run287_conc_alpha_source_packet/miss_set_candidates.csv`
- `outputs/run287_conc_alpha_source_packet/source_inventory.csv`
- `outputs/run287_conc_alpha_source_packet/source_screen_signal_stats.csv`
- `outputs/run287_w4_form4_13f_source_screen/report.md`
- `outputs/run287_best_path_source_broker_ab/signal_replays/w4_sec_score/concentrated/report.md`
