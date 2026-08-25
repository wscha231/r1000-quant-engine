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
