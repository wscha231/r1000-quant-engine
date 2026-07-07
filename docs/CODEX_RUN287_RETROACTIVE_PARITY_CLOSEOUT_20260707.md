# Run287 Retroactive Parity Closeout - 2026-07-07

## Verdict

Run287 retroactive exact target-book parity is formally blocked by missing
artifact payload. This is a substrate/provenance blocker, not an alpha result.

No fullrun was dispatched. No market data was downloaded. No target book was
regenerated for scoring. No alpha hook, threshold tuning, production promotion,
or live trading action was performed.

## Closeout State

- `exact_reproduction_ready=false`
- `approximate_reproduction_available=true`
- `runner_fidelity_status=same_artifact_repro_blocked`
- `runner_code_commit_available=true`
- `expected_price_file_count=981`
- `official_artifact_price_file_count=0`
- `local_full_candidate_price_file_count=990`

The available official artifact includes the target-generation manifest and
the price-cache manifest, but not the byte-identical runner price parquet files.
It also does not include the manifest-recorded vNext long-crisis feature file at
`data_pit/macro/long_crisis_daily_features.parquet`.

## Blocking Inputs

The preflight confirms two hard blockers:

- `runner_price_file_artifacts_missing`
- `runner_long_crisis_features_missing_or_mismatch`

The SEC-enriched candidate replay book and long-crisis threshold JSON match the
runner manifest. The local full-candidate cache is usable only for approximate
reproduction because its manifest hash differs from the runner manifest.

## Decision

Run287 cannot be retroactively promoted to exact runner-fidelity evidence.
Regenerated-book attribution remains diagnostic-only and must carry
`runner_fidelity_status=same_artifact_repro_blocked`.

Any future exact reproduction attempt must use a future official artifact that
contains `outputs/target_generation_substrate/` from the patched workflow
packaging path.

## Artifacts

- `outputs/run287_same_artifact_repro_preflight/summary.json`
- `outputs/run287_same_artifact_repro_preflight/input_availability.csv`
- `outputs/run287_same_artifact_repro_preflight/report.md`
- `outputs/run287_retroactive_parity_closeout/summary.json`

## Next Action

Do not dispatch another fullrun for run287 parity. The next valid R1 action is
to wait for a future user-approved official run that includes target-generation
substrate packaging, then rerun same-artifact reproduction against that artifact.
