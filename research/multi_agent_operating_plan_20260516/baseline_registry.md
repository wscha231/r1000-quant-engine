# Baseline Registry 20260516

## Official Metric Contract

Only the following is accepted as production-grade evidence:

```text
official_metric_mode = broker_ledger_next_close
valid_for_production = true
official_source = broker_replay/.../metrics.json or account_evaluation/official_metrics.json
```

Excluded from promotion evidence:

```text
legacy weight-level metrics
monthly forward diagnostics
position-risk proxy
research-only target pass
plain backtest_metrics.json
```

## Registered Baselines

| Portfolio | Baseline | Official CAGR | Official MaxDD | Status | Use |
| --- | --- | ---: | ---: | --- | --- |
| Main | `codex/broker-ledger-replay-foundation` | 21.84% | -28.62% | active champion | Main recovery baseline |
| Main control | `20260511_global_alpha_universe` | 21.09% | -31.69% | active control | Current-branch reproducibility check |
| Concentrated | `20260514_global_alpha_universe` | 35.10% | -22.68% | active champion | Concentrated recovery baseline |
| Concentrated aggressive reference | `20260509_global_alpha_universe` | 36.42% | -37.38% | reference only | High-CAGR / high-risk comparator |
| Latest regression | `latest 20260516` | 12.86% main / 16.89% concentrated | -27.07% main / -33.80% concentrated | not promotable | Regression case, not a tuning baseline |

## Baseline Rules

- Main challengers compare against the Main champion and the Main control.
- Concentrated challengers compare against the Concentrated champion.
- A bundle cannot be promoted if either portfolio regresses materially against its own official baseline.
- Baseline replacement requires A0 registry update, A8 QA pass, A6 broker/risk validation, and human approval.
- `latest 20260516` must not be used as a promotion baseline.
