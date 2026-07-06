# Run287 Same-Artifact Reproduction Preflight

Status: `blocked_exact_reproduction`

This is a research-only preflight. It did not dispatch a fullrun, download market data, regenerate target books, tune thresholds, or promote production.

## Verdict

- exact_reproduction_ready: `false`
- approximate_reproduction_available: `true`
- runner_fidelity_status: `same_artifact_repro_blocked`
- blocker_count: `2`

## Blockers

- `runner_price_file_artifacts_missing`
- `runner_long_crisis_features_missing_or_mismatch`

## Input Availability

| Artifact | Status | SHA match | Path |
| --- | --- | --- | --- |
| `runner_manifest` | `available_match` | `` | `cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/alphaops_vnext/target_generation_input_manifest.json` |
| `candidate_book` | `available_match` | `True` | `H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\outputs\sec_enriched_candidate_replay\candidate_replay_book_sec_enriched.csv` |
| `official_price_cache_manifest` | `available_match` | `True` | `H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\cache_prices\replay_price_cache_manifest.json` |
| `local_full_candidate_price_manifest` | `available_mismatch` | `False` | `H:\codex\tmp_r1000_grossfloor_20260625\outputs\run287_price_cache_full_candidate\cache_prices\replay_price_cache_manifest.json` |
| `runner_long_crisis_features_expected_path` | `missing_required` | `False` | `H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\data_pit\macro\long_crisis_daily_features.parquet` |
| `packaged_post_vnext_crisis_features` | `available_mismatch` | `False` | `H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\outputs\crisis_signals\daily_features.parquet` |
| `long_crisis_thresholds` | `available_match` | `True` | `H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\outputs\long_crisis_learning\best_thresholds.json` |

## Interpretation

The frozen policy env and candidate book can be checked separately, but exact runner reproduction requires the byte-identical runner price files and long-crisis feature file recorded in the target-generation manifest. If either is absent, regenerated target-book attribution remains blocked or must carry `runner_fidelity_status=same_artifact_repro_blocked`.
