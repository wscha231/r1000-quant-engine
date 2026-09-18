# Run287 review-complete gate v3 — 2026-09-16

Status: governance/safety change. This change is `R3` and itself requires exact-head Codex review under the existing v2 gate.

## Cost and safety policy

- `R0`: documentation/general tests only. Codex optional after canonical checks + exact-head maintainer attestation.
- `R1`: non-executing data/PIT/research assets plus isolated `research_only/` code. Codex optional after canonical checks + exact-head maintainer attestation.
- `R2`: every GitHub workflow by default, every `tools/`/`scripts/`/`bin/` executable, unknown executable code, and portfolio/target/risk/execution-policy changes. Codex required.
- `R3`: governance/safety gates, any scoped `AGENTS.md`, broker/live/order/ledger/accepted state, secrets, scheduler/automatic trigger, write permission, or mutation-authority control changes. Codex required; operational activation remains separately user-approved.

## Fail-closed hardening

Classification uses GitHub's complete changed-file inventory and verifies the count equals PR `changed_files`. Renames classify both `filename` and `previous_filename`. Both added and removed patch lines are inspected, so deleting a safety guard cannot lower risk. Missing executable patches fail to R3. Common executable suffixes, extensionless `tools/`/`scripts/`/`bin/` paths, Dockerfile/Makefile and custom GitHub actions are at least R2.

All workflow edits are at least R2. Changes involving schedule/cron, secret syntax, repository dispatch, pull_request_target/workflow_run triggers or write permissions are R3.

`validate` and `portfolio_guard` are verified from exact-head Actions runs whose workflow paths are exactly `.github/workflows/pr_validation.yml` and `.github/workflows/portfolio_system_guard.yml`; a same-name job in another workflow cannot spoof the gate.

## Invariants

- trusted exact-head observation;
- exact-head write/maintain/admin attestation;
- canonical `validate` and `portfolio_guard` green;
- zero unresolved review threads;
- current-head trusted CHANGES_REQUESTED blocks;
- no auto-merge authority;
- no production/live/fullrun authority.
