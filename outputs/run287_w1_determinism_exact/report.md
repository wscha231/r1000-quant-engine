# Run287 W1 Determinism Audit

Status: `completed`

This audit reran current-code target generation twice from the same run287
inputs.

Inputs:

- frozen policy payload env
- `R1000_CATBOOST_TASK_TYPE=CPU`
- candidate book:
  `outputs/run_28725350727_official_broker_artifact/outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv`
- price cache: `outputs/run287_price_cache_latest/cache_prices`
- crisis features:
  `outputs/run_28725350727_official_broker_artifact/outputs/crisis_signals/daily_features.parquet`
- crisis thresholds:
  `outputs/run_28725350727_official_broker_artifact/outputs/long_crisis_learning/best_thresholds.json`
- output mode: `shadow_only`
- broker replay: skipped
- fullrun dispatched: false
- production mutation: false

## Result

| Portfolio | official_only_date_count | generated_only_date_count | ticker_mismatch_date_count | max_weight_delta_abs | exact |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 0 | 0 | 0 | 0.0 | true |
| Concentrated | 0 | 0 | 0 | 0.0 | true |

Local W1 double-run gate passes.

## Boundary

This proves same-input local determinism on the restored run287 substrate. It
does not prove official artifact parity because the local candidate-generation
price cache is smaller than the original run287 runner cache.

Use this result to unblock local deterministic attribution, but keep official
runner parity as a separate cache/provenance issue.
