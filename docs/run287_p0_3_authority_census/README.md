# Run287 P0-3 authority census

This directory is the read-only census required by Issue #371.  The snapshot is
bound to `master` `916a02ac0612d64d41f71690cf667a90dfd0531a` and was observed at
`2026-08-25T05:19:23.469377+00:00`.

## Coverage

- Remote branches: `297`
- Pull requests: `372`
- Workflow YAML files: `40`
- Branch classifications: `{"A":67,"B":24,"C":74,"D":27,"E":4,"F":101}`
- Workflow decisions: `{"CONSOLIDATE":6,"KEEP":32,"UNKNOWN":2}`

## Reproducible source

The exact U0 GitHub input is tracked as
`docs/run287_p0_3_authority_census/source_u0_github_census.json.gz` (deterministic gzip, SHA-256
`43037952f1464bd41cdb0d2eaba78503da60f17d66c410dea186b34e0b62ef2c`). The collector accepts this `.gz`
file directly; its decompressed SHA-256 is
`5c9741b84fe9cfff74619322bc99402d92f25979974d42a405e30091ff461216`.
Frozen normalized PR check/review metadata is tracked separately as
`docs/run287_p0_3_authority_census/source_pr_supplement.json.gz` (SHA-256
`c61d10cd3408b1a9910e6a40fba317894ba82b1c8506abcc704de7df3ea89516`).
Frozen branch ancestry/path evidence is tracked as
`docs/run287_p0_3_authority_census/source_branch_supplement.parquet` (SHA-256
`12ea17046e062707437b995b95cc610ccf2ef0398dbdf9ff05c0011ff810f530`).
The frozen workflow authority policy is tracked as
`docs/run287_p0_3_authority_census/source_workflow_authority_policy.json` (SHA-256 `01977fda9c76c2513244b07d118cbb8bae620e6db03c0d6c3060763e36b9d3f7`).
The normalized full branch-protection and ruleset policy is tracked as
`data_static/run287_review_complete_gate_contract.json` (SHA-256
`5c278cbf8854f747d9ca6cf854661e47288bb52528b91ab83e4367cc59d1fe74`). By default regeneration uses these frozen
sources;
`--verify-live-namespace` is reserved for the original generation-time
equality guard.

The byte-stable generator runtime is pinned in
`docs/run287_p0_3_authority_census/requirements.txt` (SHA-256
`8c74d7c2c73e36c06bee51001a8ffc2579ea71555bb392cfb89a6ce0e05047ca`):
`{"PyYAML":"6.0.3","pandas":"2.3.3","pyarrow":"23.0.1"}`.

## Evidence limitations

Changed-path collection is incomplete for PRs
`[5,6,11,16,49,62,147,212]`. Their rows remain useful for
identity and disposition evidence, but they are not complete recovery-path
inventories and grant no merge or promotion authority.

The frozen U0 source reports historical experiment census completeness as
`false` and
declares these promotion blockers:
`["branch_only_experiment_candidates_require_recovery","duplicate_code_head_sha_groups_require_canonical_deduplication","experiment_candidates_require_canonical_mapping","historical_return_series_and_trial_deduplication_not_recovered","one_or_more_git_ancestry_results_are_unverified","one_or_more_pr_changed_path_lists_are_truncated","one_or_more_pr_check_metadata_sets_are_unresolved","one_or_more_pr_review_metadata_sets_are_unresolved","parameter_and_data_hash_duplicate_groups_not_yet_recovered"]`. This authority census preserves those
blockers and does not replace experiment recovery, ancestry verification,
trial deduplication, or historical return evidence.

The publication branch and its PR did not exist in the captured namespace.  Their
creation is the expected publication-only delta and does not authorize cleanup,
workflow dispatch, a target/ledger mutation, fullrun, promotion, production, or
live trading.

## Authority result

- Official current US target writer: `daily_operating_selection_refresh.yml`
- Official simulated-fill paper-ledger consumer/writer: `daily_operating_selection_refresh.yml`
- Live broker writer: `NONE`
- Automatic model promotion authority: `NONE`

Every other target-, broker-, ledger-, or promotion-related workflow is recorded
as research-only, noncanonical, or blocked in `workflow_registry.yaml`.

## Fail-closed limits

- Branch classifications C/D/E are recovery or research dispositions, never merge authority.
- Class F remains quarantined and must never be auto-merged.
- PR review-thread resolution was not bulk-collected; open PRs remain review-required.
- No branch deletion, merge, workflow execution, fullrun, target/order/ledger write,
  champion change, production enablement, or live trading occurred.
