# CODEX_DIRECTIVE_CONC_ALPHA_SOURCE_SCREEN_20260708

## Objective

Make Concentrated alpha-source evidence visible for Claude/GitHub review before
any hook, threshold change, fullrun, or production action.

The current Concentrated generated-book cash-carry baseline is:

- CAGR: `48.41%`
- MaxDD: `-22.96%`
- Absolute mission gap: CAGR is below the `50%` target; MaxDD is inside the `-25%` floor.

## Current Evidence Packet

Primary packet:

- `outputs/run287_conc_alpha_source_packet/report.md`
- `outputs/run287_conc_alpha_source_packet/summary.json`
- `outputs/run287_conc_alpha_source_packet/miss_set_candidates.csv`
- `outputs/run287_conc_alpha_source_packet/source_inventory.csv`
- `outputs/run287_conc_alpha_source_packet/source_screen_signal_stats.csv`

Supporting source-screen artifacts:

- `outputs/run287_w4_form4_13f_source_screen/report.md`
- `outputs/run287_w4_form4_13f_source_screen/summary.json`
- `outputs/run287_w4_form4_13f_source_screen/signal_stats.csv`

Supporting broker A/B evidence:

- `outputs/run287_best_path_source_broker_ab/signal_replays/w4_sec_score/concentrated/report.md`
- `outputs/run287_best_path_source_broker_ab/signal_replays/w4_sec_score/concentrated/summary.json`

## Screen Result

The W4 Form4 + 13F source screen is positive enough for review, not for a hook:

| Signal | Full high-low | IS high-low | OOS high-low | Verdict |
| --- | ---: | ---: | ---: | --- |
| `w4_form4_score` | `-0.34%` | `+0.62%` | `-1.12%` | reject standalone |
| `w4_13f_score` | `+0.57%` | `+0.14%` | `+1.69%` | review candidate |
| `w4_combined_score` | `+0.39%` | `+0.27%` | `+0.72%` | review candidate |
| `w4_consensus_score` | `+1.52%` | `+1.33%` | `+1.20%` | sparse review candidate |

Existing W4 SEC broker A/B remains a near-miss/negative result:

- baseline: `48.41% CAGR / -22.96% MaxDD`
- 5% tilt: `49.37% CAGR / -22.60% MaxDD`, but OOS CAGR worsened
- 10% tilt: `49.56% CAGR / -22.26% MaxDD`, but OOS CAGR worsened
- verdict: `no_positive_broker_ab_candidate`

## Claude Review Ask

Red-team the packet as measurement/governance, not as a hook proposal.

Questions:

1. Is `w4_13f_score`, `w4_combined_score`, or sparse `w4_consensus_score`
   clean enough to justify a default-off fixed-book broker A/B?
2. Should the next design focus only on the 51-row `cap_or_replacement`
   miss-set in `miss_set_candidates.csv`?
3. Does the 13F signal pass decision-time availability and leakage scrutiny
   given accepted/available filing lag?
4. Is Form4 standalone correctly rejected by OOS high-low, or is there a
   data-contract issue that invalidates the screen?
5. Does the existing W4 SEC broker A/B already exhaust this source family, or
   is a miss-set-specific fixed-book A/B still justified?

## Non-Negotiables

- No fullrun.
- No new policy hook.
- No threshold tuning.
- No endpoint/window cherry-picking.
- No benchmark cherry-picking.
- No production promotion.
- No live trading.
- No public return or S&P 500 outperformance claim.
- Do not use `period_forward_return` for ranking; it is audit-only.
- Do not repair specific losing months or tickers.

## Next Action Policy

If Claude accepts the evidence as clean:

1. Design exactly one default-off fixed-book broker A/B focused on
   `cap_or_replacement` miss-set rows.
2. Evaluate against:
   - absolute CAGR/MDD,
   - SPY-relative excess CAGR,
   - relative MaxDD,
   - down capture,
   - beta-adjusted alpha,
   - OOS/OOS2.
3. Reject if OOS worsens or absolute mission remains below threshold.

If Claude rejects the evidence:

1. Record negative evidence.
2. Do not design a hook from Form4/13F.
3. Re-open only if true PIT earnings/guidance revision feed becomes available.
