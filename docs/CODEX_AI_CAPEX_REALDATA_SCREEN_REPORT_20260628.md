# AI Capex Real-Data Screen Report — 2026-06-28

## Scope

This report applies the research-only AI Capex late-cycle layer to the clean 7Y artifact:

- `artifacts/28074476465/outputs/alphaops_vnext/official_concentrated_target_book.csv`
- `artifacts/28074476465/outputs/alphaops_vnext/official_main_target_book.csv`

No production target, score, weight, workflow, fullrun, or live-trading path was changed.

## Summary Verdict

The AI Capex bottleneck layer produces a real cheap-screen signal on the existing clean 7Y target books.

However, this is not yet broker-ledger evidence:

- The screen uses `period_forward_return` as an audit label only.
- The current artifact lacks true vendor EPS revision / guidance data.
- Existing `actual_results_score > 0` can serve as a PIT earnings-confirmation fallback, but it should not replace a proper FactSet-style revision feed.

Next step is not fullrun. Next step is a default-off hook design plus cheap broker A/B, or first ingest real EPS/guidance data and rerun the screen.

## Concentrated Results

Enrichment:

- Rows: 497
- Classified AI Capex rows: 142
- Classified coverage: 28.57%
- High bottleneck rows: 142
- Source confidence:
  - `text_or_industry_match`: 113
  - `seed_example_only`: 29
  - `unclassified`: 355

Target group:

`ai|bottleneck_high|revision_pos|momentum_high`

Here `revision_pos` means earnings confirmation is positive. In this run, the confirmation source is existing `actual_results_score`, not vendor EPS revision.

| Split | Count | Positive Rate | Mean 126d Excess | Median 126d Excess | Unique Tickers | Unique Buckets |
|---|---:|---:|---:|---:|---:|---:|
| Full | 86 | 61.63% | +7.85% | +4.76% | 29 | 5 |
| OOS | 33 | 75.76% | +14.58% | +10.38% | 9 | 4 |

This passes the cheap screen.

Important caveat:

The stronger full/OOS group in this artifact is often `ai|bottleneck_high|revision_nonpos|momentum_high`, with:

- Full: +10.61% mean 126d excess
- OOS: +17.10% mean 126d excess

This means the current `actual_results_score` fallback does not cleanly improve the AI Capex momentum signal. It may be noisy or lagged. Do not make `actual_results_score` a mandatory policy condition without broker A/B.

## Main Results

Enrichment:

- Rows: 1,282
- Classified AI Capex rows: 368
- Classified coverage: 28.71%
- High bottleneck rows: 368
- Source confidence:
  - `text_or_industry_match`: 316
  - `seed_example_only`: 52
  - `unclassified`: 914

Target group:

`ai|bottleneck_high|revision_pos|momentum_high`

| Split | Count | Positive Rate | Mean 126d Excess | Median 126d Excess | Unique Tickers | Unique Buckets |
|---|---:|---:|---:|---:|---:|---:|
| Full | 233 | 59.23% | +4.59% | +2.70% | 54 | 5 |
| OOS | 91 | 65.93% | +9.25% | +4.90% | 26 | 5 |

This also passes the cheap screen, but the effect is smaller than Concentrated.

## Late-Cycle Regime Audit

Running `run_late_cycle_ai_regime_audit.py` on the enriched Main candidates without a revision/guidance feed produced:

- `late_cycle_ai_capex_regime=false`
- `momentum_dominance_score=0.895`
- `ai_bottleneck_positive_ratio=0.287`
- `eps_revision_positive_ratio=0.0`
- `guidance_positive_ratio=0.0`

Interpretation:

The current artifact confirms strong momentum and AI Capex classification coverage, but it does not yet contain enough FactSet-style EPS revision/guidance data to validate the full late-cycle regime thesis.

## What Improved In This PR

The first implementation was too strict for existing artifacts:

- AI rows classified, but `high_bottleneck_count=0`.
- The screen could not run meaningfully because vendor EPS revision columns were absent.

The follow-up changes fixed this without using forward returns:

- `industry_group` is now included in taxonomy matching.
- AI bucket seed/industry evidence now gets a structural bottleneck test score.
- `actual_results_score > 0` is allowed as a PIT earnings-confirmation fallback.
- Screen summaries now emit `best_full_group` and `best_oos_group` so we can see whether the intended target group is actually the best group.

## 2026-06-28 Follow-Up: True EPS/Guidance Feed Join

`run_ai_capex_bottleneck_screen.py` now attempts a PIT as-of join against:

`data_pit/events/earnings_revision_signals.parquet`

Join rule:

- match by ticker
- use only rows with `available_from <= screen_date`
- ignore future `available_from`
- write joined values to `vendor_*` columns
- prefer true vendor EPS/revenue revision or positive guidance over `actual_results_score`

This means a real EPS/guidance feed can be added later without rewriting the screen. The fallback remains explicit and auditable.

Current clean 7Y artifact state:

| Sleeve | earnings signal status | joined rows | confirmation source counts |
|---|---|---:|---|
| Concentrated | `missing_or_empty` | 0 | `actual_results_score_fallback`: 254, `neutral`: 243 |
| Main | `missing_or_empty` | 0 | `actual_results_score_fallback`: 789, `neutral`: 493 |

Therefore the real-data screen pass is still a fallback-based research signal, not a true FactSet-style EPS/guidance-confirmed signal.

Updated screen results remain unchanged in direction:

| Sleeve | Target group full mean 126d excess | OOS mean 126d excess | Best group |
|---|---:|---:|---|
| Concentrated | +7.85% | +14.58% | `ai|bottleneck_high|revision_nonpos|momentum_high` |
| Main | +4.59% | +9.25% | `ai|bottleneck_high|revision_nonpos|momentum_high` |

Important interpretation:

- The intended group still passes: `ai|bottleneck_high|revision_pos|momentum_high`.
- But the stronger group in both sleeves remains `ai|bottleneck_high|revision_nonpos|momentum_high`.
- Since `revision_pos` is currently driven by `actual_results_score_fallback`, do not require earnings confirmation in a policy hook yet.
- The next policy candidate must compare:
  - AI bottleneck + momentum
  - AI bottleneck + momentum + actual-results fallback
  - AI bottleneck + momentum + true vendor EPS/guidance confirmation when the feed exists

## No-Lookahead Check

The cheap screen still reports:

- `used_forward_return_in_ranking=false`
- `forward_returns_audit_only=true`
- `production_activation_allowed=false`

Forward 63d/126d excess is used only to judge whether the pre-specified PIT group had favorable outcomes.

## Recommended Next Step

Do not fullrun.

Run one of these two next:

1. **Data-first**: ingest true EPS revision / guidance data into `build_earnings_revision_signals.py`, join it to candidates, then rerun the screen. This is the cleaner path.
2. **Cheap hook screen**: design a default-off candidate hook that compares:
   - AI bottleneck + momentum
   - AI bottleneck + momentum + `actual_results_score > 0`
   - AI bottleneck + momentum + true EPS revision positive when available

The hook must pass broker-ledger A/B before any fullrun.

Production remains blocked while `pit_universe_label_clean=false`.
