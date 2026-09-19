# Control Plane Contracts — I0 to I3

This package is intentionally isolated from selector, target, workflow, broker, paper-ledger and production code.

## Purpose

- I0: machine-readable system state registry.
- I1: common artifact contracts and `ResearchCandidatePacket`.
- I2: PR dependency / merge matrix.
- I3: synthetic cross-module integration fixture.
- Forward contracts included now: candidate data queue, experiment registry, global book contract.

## Safety

- `RESEARCH_ONLY`.
- No BUY/SELL/order authority.
- No target-book write authority.
- No paper/actual ledger mutation.
- No scheduler/workflow changes.
- No production/champion promotion.
- Missing/stale inputs are explicit and never converted to favorable values.

## Current repository state

The snapshot distinguishes:
- repository head (which may include automated after-close commits), and
- reviewed feature baseline.

Do not substitute one for the other.

## Application

Apply only in an approved local worktree:

```bash
git switch -c control-plane/i0-i3-20260917
git apply /path/to/control_plane_i0_i3_20260917.patch
python tests/control_plane_contract_smoke.py
git diff --check
```

Do not edit `tools/run_pr_validation.py` in this low-risk slice. Registration into protected CI can be a separate reviewed change.

## Codex quota boundary

Current master review-complete v2 still requires current-head Codex evidence. Therefore this slice may be implemented and locally validated now, but merge must remain blocked until the repository review contract is satisfied.
