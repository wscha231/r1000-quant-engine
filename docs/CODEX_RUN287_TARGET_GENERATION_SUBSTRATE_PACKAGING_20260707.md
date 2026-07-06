# CODEX RUN287 TARGET GENERATION SUBSTRATE PACKAGING 20260707

Status: `research_only_artifact_hardening`

This follow-up implements the unblock identified by the run287 same-artifact
preflight: future official artifacts must package the byte-level target
generation substrate, not only the target books and manifest.

No fullrun was dispatched. No market data was downloaded. No target book was
regenerated for scoring. No alpha hook, threshold tuning, production promotion,
or live trading action was performed.

## Change

Added `tools/archive_target_generation_substrate.py` and wired it into
`full_rebuild_manual.yml` before artifact upload.

The tool copies already-materialized files into:

`outputs/target_generation_substrate/`

The bundle includes:

- `alphaops_vnext/target_generation_input_manifest.json`
- SEC-enriched candidate replay book
- `cache_prices/replay_price_cache_manifest.json`
- price cache files (`.parquet` / `.csv`)
- `data_pit/macro/long_crisis_daily_features.parquet`
- `outputs/long_crisis_learning/best_thresholds.json`
- `summary.json`
- `report.md`

## Artifact Policy

The full substrate bundle is uploaded in:

- `official-broker-ledger-${{ inputs.universe_mode }}-${{ github.run_id }}`
- `research-full-${{ inputs.universe_mode }}-${{ github.run_id }}`

The user operating minimal artifact receives only:

- `outputs/target_generation_substrate/summary.json`
- `outputs/target_generation_substrate/report.md`

This keeps the UI-facing artifact smaller while preserving exact reproduction
substrate in the official evidence artifact.

## Git Policy

Do not copy the full price cache substrate into committed `cloud_results`.
Those files are reproduction substrate for expiring GitHub Actions artifacts,
not a suitable permanent git history payload.

## Validation

- `python -m py_compile tools/archive_target_generation_substrate.py tests/target_generation_substrate_archive_smoke.py`
- `python tests/target_generation_substrate_archive_smoke.py`
- `python tests/workflow_artifact_smoke.py`
- `python tools/run_pr_validation.py --only target_generation_substrate_archive_smoke --only workflow_artifact_smoke --quiet`

## Decision

Future R1 exact runner-fidelity attempts should use
`outputs/target_generation_substrate/` from the official broker-ledger artifact.
If that bundle reports missing or mismatched inputs, regenerated-book
attribution remains blocked and must carry a runner-fidelity caveat.
