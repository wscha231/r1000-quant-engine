# Agent Location Discipline

This document is the shared operating contract for Claude Code, Codex, and
ChatGPT Pro when working on this repository. Its purpose is to prevent agents
from mixing local clone state, GitHub remote state, and Drive mirror artifacts.

## Location Tags

Every command, status claim, and handoff note must identify exactly one
location:

| Tag | Meaning | Source of truth for |
| --- | --- | --- |
| `[LOCAL]` | The active local git working tree. Files may be stale until `git fetch origin` or `git pull`. | edits, local tests, local commits before push |
| `[GITHUB]` | `github.com/wscha231/r1000-quant-engine`, including `origin/*`, PRs, CI, and workflow runs. | branch SHAs, PR status, CI status, remote artifacts committed to git |
| `[DRIVE]` | Drive mirror or `H:/codex/...` artifact storage. Treat as read-only input unless copied into `[LOCAL]`. | long-term run artifacts that are not committed to GitHub |

Google Drive is a mirror, not the primary source of truth. Official promotion
evidence must trace back to a GitHub workflow `run_id`, commit SHA, and artifact
or a committed `cloud_results` tree. A Drive-only file may guide review, but it
does not prove production readiness by itself.

## Required Preamble

Before any multi-step work, the agent must report:

- `[LOCAL]` clone path.
- `[LOCAL]` time of the last `git fetch origin`.
- `[GITHUB]` branch SHAs for every branch being used.
- `[GITHUB]` PR numbers and base/head branches when relevant.
- Whether `[DRIVE]` artifacts are being read, and why they are not the git
  source of truth.

## Hard Rules

- Do not assume local state equals remote state. Run `[LOCAL] git fetch origin`
  before branch/SHA decisions.
- Do not merge or push directly to `master`. Only the user merges PRs.
- Do not whole-merge `origin/claude/analyze-updated-code-OfEbu`; it is a
  research/docs source only.
- Do not commit directly from `[DRIVE]`. Copy reviewed content into `[LOCAL]`
  and push through `[GITHUB]`.
- If `[LOCAL]` and `[GITHUB]` disagree, stop and explicitly choose the source of
  truth before editing.
- If a command switches location, write a transition note, for example:
  `# transition: [LOCAL] -> [GITHUB] because PR metadata is remote state`.

## Current Branch Roles

As of 2026-06-15 after fetch:

| Branch | Role |
| --- | --- |
| `origin/master` | default branch and final merge target |
| `origin/codex/self-sustaining-loop-20260615` | PR64 implementation base for control-loop and 8-year evidence work |
| `origin/codex/goals-2026-06-15` | PR65 review-only goals proposal, stacked on PR64 |
| `origin/codex/pr64-coordination-ledger-router-20260615` | PR66 coordination, ledger preservation, target-contract metadata, and self-correction queue closure stacked on PR64 |
| `origin/codex/goals-update-bull-floor-contract-20260615` | PR67 review-only goals update stacked on PR65 |
| `origin/claude/analyze-updated-code-OfEbu` | Claude research/docs source; never whole-merge |

## Active PR Stack

| PR | Base | Head | Merge order |
| --- | --- | --- | --- |
| #64 | `master` | `codex/self-sustaining-loop-20260615` | 1 |
| #66 | `codex/self-sustaining-loop-20260615` | `codex/pr64-coordination-ledger-router-20260615` | 2 |
| #65 | `codex/self-sustaining-loop-20260615` | `codex/goals-2026-06-15` | 3 |
| #67 | `codex/goals-2026-06-15` | `codex/goals-update-bull-floor-contract-20260615` | 4 |

Do not retarget PR65/PR67 onto `master` until the implementation stack has
landed. If a base branch is merged and deleted, rebase or retarget the next PR
only after confirming the merged commit is present on `origin/master`.

## Review Boundaries

Codex and Claude Code may create branches, commits, and PRs. They must not:

- merge their own PRs,
- mutate live trading settings,
- mark 7-year evidence as official 8-year evidence,
- rewrite ledger history without preserving run IDs and provenance,
- change canonical mission targets without explicit user approval.
