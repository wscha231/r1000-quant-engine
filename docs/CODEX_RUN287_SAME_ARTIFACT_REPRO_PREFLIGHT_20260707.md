# CODEX RUN287 SAME-ARTIFACT REPRO PREFLIGHT 20260707

Status: `research_only_blocked_exact_reproduction`

This document records the Phase 0/R1 same-artifact reproduction preflight after
PR #221. It checks whether the exact runner inputs recorded by run287's
`alphaops_vnext/target_generation_input_manifest.json` are available locally.

No fullrun was dispatched. No market data was downloaded. No target book was
regenerated for scoring. No threshold tuning, alpha hook, production promotion,
or live trading action was performed.

## Artifacts

- `outputs/run287_same_artifact_repro_preflight/summary.json`
- `outputs/run287_same_artifact_repro_preflight/input_availability.csv`
- `outputs/run287_same_artifact_repro_preflight/report.md`

## Verdict

- `exact_reproduction_ready=false`
- `approximate_reproduction_available=true`
- `runner_fidelity_status=same_artifact_repro_blocked`
- `runner_code_commit_available=true`
- `expected_price_file_count=981`
- `official_artifact_price_file_count=0`
- `local_full_candidate_price_file_count=990`

Exact same-artifact reproduction is blocked by missing runner input artifacts:

- `runner_price_file_artifacts_missing`
- `runner_long_crisis_features_missing_or_mismatch`

## What matched

- The runner code commit is available locally:
  `15176b588d5bb0792bce1df6367758d795a8a33a`.
- The SEC-enriched candidate book is available and hash-matches the runner
  manifest:
  `7ffa0b27382d303008ffca55878b259ccf7f11beaee28be6f1e4653c30e97989`.
- The official price-cache manifest is available and hash-matches:
  `fdcf36399cb75225423ce71a92e9cc36e580482015c8bf07718d02376acb4a18`.
- The long-crisis threshold JSON is available and hash-matches:
  `d108c017e301f6929e1441827d5a19c02beb0d89727dbbff40f94f3e504d2da2`.

## What did not match

The official GitHub artifact packages only
`cache_prices/replay_price_cache_manifest.json`; it does not package the 981
runner price files needed for byte-identical target generation. A local
full-candidate cache exists with 990 price files, but its manifest hash is
`1328919074a8ad2ad1916003860ca747183f58f2263bf9af13ebe673810f536a`, not the
runner hash.

The runner manifest records vNext long-crisis features at:

`data_pit/macro/long_crisis_daily_features.parquet`

with sha:

`0059b029d0f304c5030b78c5673cc430d4307904e06e6fb425b7ce6c27fe3ffc`

That file is not present in the downloaded official artifact. The packaged
`outputs/crisis_signals/daily_features.parquet` exists, but its sha is:

`0ef3bdaa313f0956bb74db2d2c85e01d8988c111d9be36f7cc27995e6c4537db`

so it is not the manifest-recorded vNext input.

## Decision

R1 remains not complete. The old 498-cache coverage gap is solved, but exact
runner fidelity is still blocked because the byte-identical runner substrate is
not packaged in the available artifacts.

Approximate reproduction can be attempted with:

1. code pinned to `15176b588d5bb0792bce1df6367758d795a8a33a`;
2. runner `GITHUB_REF` and `GITHUB_SHA` populated;
3. no `--operating-append-end-date` override;
4. the exact SEC-enriched candidate book;
5. the local full-candidate price cache;
6. the packaged post-vNext crisis features.

That attempt must carry `runner_fidelity_status=same_artifact_repro_blocked`
and cannot be used as runner-fidelity acceptance evidence.

## Next Action

Do not dispatch another fullrun. Do not design alpha hooks from regenerated-book
drift while exact runner fidelity is blocked.

The concrete unblock is to make future fullrun artifacts package the exact
target-generation substrate:

- runner price files used by `run_alphaops_vnext_policy_replay.py`;
- `data_pit/macro/long_crisis_daily_features.parquet`;
- target-generation manifest;
- frozen policy env hash;
- code provenance.

After that packaging hardening lands, rerun R1 same-artifact reproduction on
the next eligible official artifact.
