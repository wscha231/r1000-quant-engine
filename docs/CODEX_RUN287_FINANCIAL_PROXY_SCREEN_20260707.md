# Run287 Financial Proxy Screen - 2026-07-07

## Verdict

The measurement/provenance phase is closed for run287. This document starts the
next CAGR/MDD workstream with a cheap, research-only financial proxy screen.

No fullrun was dispatched. No broker target book was mutated. No alpha hook,
threshold tuning, production promotion, or live trading action was performed.
Forward returns are audit labels only.

## Input

- Candidate book:
  `cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/reports/candidate_replay_book.csv`
- Rows evaluated: 47,435
- Tickers: 981
- OOS split: 2024-07-01
- True PIT revision/guidance feed: not available in this worktree

## Result

Two financial actual/proxy signals passed the cheap diagnostic screen:

| Signal | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| `actual_results_score` | +0.34% | +0.36% | +0.24% | 2,889 | 53.69% |
| `profitability_inflection_score` | +1.04% | +0.57% | +2.03% | 2,889 | 56.70% |

The stronger candidate is `profitability_inflection_score`. The
`actual_results_score` edge is positive but small.

Several growth columns showed OOS-only strength but failed the joint IS/OOS
gate, so they should not be used for hook design from this run287 evidence:

- `eps_growth_yoy`
- `ocf_growth_yoy`
- `rev_growth_accel_4q`

## Decision

- `candidate_allowed=false`
- `decision_label=diagnostic_positive_requires_broker_ab_review`
- `next_action_allowed=broker_ab_design_review_only`

This screen can justify a default-off broker A/B design review for a narrow
financial-quality proxy, especially `profitability_inflection_score`. It cannot
justify a fullrun or production claim.

## Anti-Leakage Boundary

- Do not use `period_forward_return` for ranking or selection.
- Do not backfill current financial statements into historical decisions.
- Do not treat `actual_results_score` as true analyst revision or guidance.
- Do not design a hook until the broker A/B definition is frozen before replay.
- True PIT revision/guidance remains a separate W4 data feed requirement.

## Artifacts

- `outputs/run287_financial_proxy_screen/summary.json`
- `outputs/run287_financial_proxy_screen/signal_stats.csv`
- `outputs/run287_financial_proxy_screen/report.md`
