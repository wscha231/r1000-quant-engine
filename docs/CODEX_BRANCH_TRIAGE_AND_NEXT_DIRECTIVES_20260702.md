# Branch Triage And Next Directives - 2026-07-02

## Purpose

This is the next execution packet after the July 2 implementation round. It
separates instructions by audience:

- Codex: implement and verify.
- Claude: red-team code paths, no-op risks, measurement validity, and branch
  hygiene.
- ChatGPT Pro: governance, service/public-display contract, and policy
  decisions.

Do not send the same prompt to all engines. Each engine should receive only the
section intended for its role.

## Current Implemented State

### Merged / Implemented Facts

- Clean 7Y window/account evaluation is now structurally valid via the #213
  window-gate hardening.
- Research-only cash-carry accounting exists via #214.
- Required experiment price tickers are now surfaced through readiness and
  collection/audit plumbing via #215/#216.
- Phase 1 replay established:
  - cash-carry is a research-accounting win;
  - broad bull-floor is rejected;
  - cash in Concentrated is load-bearing MDD defense, not idle drag.
- Phase 2 fixed-official-book replays established:
  - hold/exit timing variants rejected;
  - cap-safe sizing variants rejected;
  - no fullrun is justified from timing/sizing/bull-floor.
- AI Capex diagnostics exist, but are diagnostic-only:
  - true PIT EPS/guidance feed is still missing;
  - AI bucket membership alone must not become a policy hook.
- W7 forward-service seed now exists:
  - `tools/run_forward_service_snapshot.py`;
  - `docs/CODEX_FORWARD_SERVICE_READINESS_20260702.md`;
  - `tests/forward_service_snapshot_smoke.py`.

### Latest Real Snapshot

Generated from run `28436307420`:

```text
freeze_date = 2026-06-29
public_snapshot_hash = 5927b865bbc3ac70e134dc09b0bccb3cab72fe756f8a7e1b8cafc3d7b1bd0ae8
broker_state_hash = 9372228d276622d1f8c5f83e40bc3a779d78c8addad58015f3b040f06587c822
target_snapshot_hash = eec82fa9f221bf52637a172a29ed5b41a381c7c2d62d4df6ca3e2ccf67648d79
public_display_allowed = false
production_activation_allowed = false
pit_universe_label_clean = false
holding_row_count = 20
```

This snapshot can seed a forward paper ledger. It must not be used as public
marketing or trade instruction.

## Repository / Branch Situation

Current remote branch count:

```text
total_heads = 166
codex_heads = 154
claude_heads = 10
```

This is now an engineering risk. The next stage must include branch and PR
triage before additional feature branches are created.

Recent important PR state from GitHub:

- #213 merged: account/window gate hardening.
- #214 merged: research-only cash-carry accounting.
- #215 merged: require hedge/benchmark price freshness.
- #216 merged: collect required price tickers upstream.
- #217 open draft: Claude consolidated directive. Treat as a merge candidate
  for planning history, not as superseded code. If merged, mark the newer W1/W7
  directives as the active execution layer.
- #212 open draft: integration target hooks. Keep as research reference only;
  do not merge as production.
- #211 open draft: Main fast-crash hedge hook. This creates a governance
  contradiction: the latest official run used fast-crash hedge behavior, while
  the user has also expressed long-only/no-hedge preference. Resolve before
  quoting Main MDD as a long-only baseline.
- #209/#208 open drafts: Concentrated cash-funded early-entry hook/harness.
  Relabel as `unproven_adjacent_to_falsified_cash_deployment`, not as a
  surviving path. Bull-floor proved cash is load-bearing defense; #208/#209
  consume cash and need isolated fixed-book/broker proof after W1.
- #206 open draft: hedge overlay harness. Keep as opt-in backlog only.
- #201 open draft: Main MDD negative-evidence ledger. Mergeable as a research
  closeout if body is updated to mention the hedge-on vs long-only governance
  conflict.
- #199 open draft: AI Capex research screens. Useful as data/diagnostic
  infrastructure, not a policy hook.
- #166 and #170 are open, non-draft, and not mergeable. They predate the
  current fixed-book/OOS-IS/control-repro discipline. Classify as
  `blocked_needs_rebase_or_review`.
- #197 is docs-only but touches target contracts. Keep blocked until W0
  governance decides cash-carry and MDD contract language.
- #194/#195/#196 open drafts: whipsaw audit / reject reports. Useful evidence;
  do not let them restart broad hold-duration variants.
- #106-#118 and similar June 17 stacked evidence PRs are likely superseded or
  stale. They should be reviewed in a close/archive sweep, not used as current
  next-step inputs.

## Non-Negotiables

- No production promotion while `pit_universe_label_clean=false`.
- No live trading.
- No fullrun until a new candidate passes cheap replay gates and the user
  explicitly approves.
- No 8Y/10Y proxy work.
- No broad bull-floor/gross-floor revival.
- No regenerated selection-side A/B acceptance until target-book control
  reproduction is understood.
- Current holdings are process outputs, not a future CAGR promise.

---

# CODEX_IMPLEMENTATION_DIRECTIVE

## Goal

Prepare the repository for the next reliable alpha/service step by reducing
branch ambiguity and fixing the measurement substrate before creating new
policy hooks.

## P0 - Branch / PR Hygiene Index

Create a machine-readable triage report:

```text
outputs/branch_triage_20260702/open_pr_triage.csv
outputs/branch_triage_20260702/report.md
```

For every open PR, classify:

- `pr_number`
- `title`
- `branch`
- `state`
- `draft`
- `mergeability`
- `ci_status`
- `changed_files`
- `merge_candidate_now`
- `keep_draft_research_reference`
- `close_superseded`
- `close_rejected_negative_evidence_captured`
- `blocked_needs_rebase_or_review`
- `blocked_needs_governance_decision`
- `superseded_by_pr`
- `related_evidence_doc`
- `last_measured_artifact`
- `decision_reason`
- `required_action_owner`
- `safe_to_close_after_user_approval`

Minimum classification rules:

- Keep #212 as a research integration reference, not a production path.
- Keep #209/#208 only as `unproven_adjacent_to_falsified_cash_deployment`
  references until W1 and isolated proof resolve them.
- Keep #206 as hedge opt-in backlog, not active work.
- Prefer merging #201 only as negative evidence if still clean, non-conflicting,
  and updated for the hedge-vs-long-only governance issue.
- Treat #217 as a docs merge candidate for historical W0-W7 context.
- Classify #166/#170 as `blocked_needs_rebase_or_review`.
- Classify #197 as `blocked_needs_governance_decision`.
- Mark old June 17 stacked PRs for close/review unless their changes are absent
  from master and still needed.

Do not delete branches automatically. Produce the report first.

## P1 - W1 Target-Book Control Reproduction Root Cause

Do not frame this as a seed-only patch. The current code already has
`cfg.random_seed = 42` wired through major ML paths.

First bisection:

1. Record environment parity:
   - CatBoost task type CPU/GPU;
   - library versions;
   - thread counts;
   - relevant env flags.
2. Force reproduction mode to CPU and single-thread where feasible.
3. Hash all target-generation inputs:
   - candidate book;
   - SEC-enriched candidate book if used;
   - price cache manifest;
   - macro/crisis inputs;
   - append/latest-close date;
   - env flags.
4. Run same-machine double reproduction.
5. Compare against official target book:
   - official-only dates;
   - generated-only dates;
   - ticker mismatch dates;
   - max weight delta;
   - per-date top mismatch.

Output:

```text
outputs/target_book_control_repro_root_cause/summary.json
outputs/target_book_control_repro_root_cause/report.md
```

Acceptance before regenerated selection-side A/B:

```text
official_only_date_count = 0
generated_only_date_count = 0
ticker_mismatch_date_count = 0
max_weight_delta_abs <= 1e-9 for deterministic/hash-equal reproduction
or max_weight_delta_abs <= 0.001 only with an explicit floating-path exception
documented in the report
```

Do not write `near zero` in machine-readable acceptance. It invites drift.

## P2 - W2 PIT Membership Track

Keep this parallel and data-focused:

- Find or build real historical PIT membership source.
- Use existing PIT membership producer/audit tools.
- Do not flip `pit_universe_label_clean` manually.
- `current_constituents` backfill remains a production blocker.

## P3 - W7 Forward Paper Ledger

Use the new forward-service snapshot as the freeze point.

Next tools to add after W1 starts:

```text
tools/update_forward_service_ledger.py
tools/run_forward_expectation_band.py
tests/forward_service_ledger_smoke.py
tests/forward_expectation_band_smoke.py
```

Requirements:

- append-only ledger;
- no retroactive edits without new correction record;
- snapshot hash carried into every row;
- display only percentile bands, not point CAGR promises;
- public display remains blocked until license/regulatory/readiness gates clear.

## P4 - W3 Rotation / Replacement Audit

Start only after P1 has a first root-cause report.

Goal:

- quantify rotation latency;
- determine whether the early-entry/replacement path from #208/#209 survives
  after control reproduction;
- use PIT evidence only;
- no new hook before applied-count and broker replay evidence.

---

# CLAUDE_REVIEW_PACKET

## Ask

Please review the repository state as a red-team reviewer, not as a planner.

Focus on:

1. Is the branch/PR triage classification technically sound?
2. Are there PRs that look safe but are actually stale or contradictory?
3. Is W1 correctly framed as target-book control reproduction rather than a
   seed-only patch?
4. Is GPU/CPU CatBoost task-type parity the right first suspect?
5. Does W7 forward-service snapshot avoid misleading users about future CAGR?
6. Are any old rejected ideas being accidentally revived by #212/#209/#208?
7. Is the hedge-ON latest baseline inconsistent with the user's long-only/no
   hedge preference, and what exact artifact is needed to resolve it?

Do not propose new alpha levers unless they directly follow from a measured
artifact. Prefer finding no-op, leakage, stale-branch, or measurement-contract
errors.

## Evidence To Use

- #213/#214/#215/#216 are merged and load-bearing.
- Phase 1: cash-carry pass, bull-floor reject.
- Phase 2: fixed-book timing/sizing reject.
- AI Capex: diagnostic only until true PIT EPS/guidance feed.
- W7 snapshot:
  - public snapshot hash `5927b865bbc3ac70e134dc09b0bccb3cab72fe756f8a7e1b8cafc3d7b1bd0ae8`;
  - broker state hash `9372228d276622d1f8c5f83e40bc3a779d78c8addad58015f3b040f06587c822`;
  - target snapshot hash `eec82fa9f221bf52637a172a29ed5b41a381c7c2d62d4df6ca3e2ccf67648d79`;
  - `public_display_allowed=false`;
  - `production_activation_allowed=false`.

## Desired Output

```text
Verdict:
- branch triage: approve / fix
- W1 plan: approve / fix
- W7 service snapshot: approve / fix

Blocking issues:
-

PRs to merge / keep / close:
-

Smallest next Codex fix:
-
```

---

# GPT_PRO_GOVERNANCE_PACKET

## Ask

Please review this as a governance/service contract question, not a code
review.

Decisions needed:

1. Should `broker_ledger_next_close_cash_carry` become the official research
   baseline after user approval, while production stays blocked by PIT
   membership?
2. Should Concentrated MDD use the canonical `-25%` mission bar or an interim
   operating risk cap such as `-28%` until PIT-clean evidence exists?
3. Does the user want a long-only/no-hedge official policy, or is the
   fast-crash hedge allowed as part of the Main research baseline? If long-only,
   require a hedge-OFF baseline replay before quoting Main MDD as long-only.
4. What exactly can be shown on a public website today?
5. What disclosures are required so current holdings are not interpreted as
   guaranteed CAGR/MDD?
6. What minimum forward paper-tracking period should be required before public
   service claims are made?

## Facts

- Latest zero-yield official metrics from run `28436307420`:
  - Main 34.27% CAGR / -24.11% MDD.
  - Concentrated 47.46% CAGR / -24.08% MDD.
- Cash-carry replay improves:
  - Main to about 35.11% / -23.99%.
  - Concentrated to about 48.83% / -23.79%.
- Production remains blocked:
  - `pit_universe_label_clean=false`.
- Website snapshot exists but is review-only:
  - `public_display_allowed=false`;
  - no forward track record has elapsed yet.

## Desired Output

```text
Governance verdict:
- cash-carry research baseline: approve / reject / conditionally approve
- MDD contract: keep -25 / interim cap / rewrite required
- website display today: internal only / public with disclaimers / not allowed

Required disclosures:
-

Minimum forward-service readiness gates:
-
```

---

# Immediate Next Step

Codex should not start a new fullrun or alpha hook. The next concrete work is:

```text
P0 branch/PR hygiene index
P1 target-book control reproduction root cause
P3 forward paper ledger append-only seed
```

These can proceed without disturbing strategy or production state.
