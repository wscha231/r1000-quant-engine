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
`docs/run287_p0_3_authority_census/source_u0_github_census.json.gz`
(deterministic gzip, SHA-256
`43037952f1464bd41cdb0d2eaba78503da60f17d66c410dea186b34e0b62ef2c`).
The collector accepts this `.gz` file directly; its decompressed SHA-256 is
`5c9741b84fe9cfff74619322bc99402d92f25979974d42a405e30091ff461216`.
Frozen normalized PR check/review metadata is tracked separately as
`docs/run287_p0_3_authority_census/source_pr_supplement.json.gz` (SHA-256
`9afb5257b6ae73f96b668a54fd3cfda8e538ee386e4ba461222fc00d5e4903d3`).
Frozen branch ancestry/path evidence is tracked as
`docs/run287_p0_3_authority_census/source_branch_supplement.parquet` (SHA-256
`12ea17046e062707437b995b95cc610ccf2ef0398dbdf9ff05c0011ff810f530`).
By default regeneration uses these three frozen sources;
`--verify-live-namespace` is reserved for the original generation-time
equality guard.

## Evidence limitations

Changed-path collection is incomplete for PRs
`[5,6,11,16,49,62,147,212]`. Their rows remain useful for identity and
disposition evidence, but they are not complete recovery-path inventories and
grant no merge or promotion authority.

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
