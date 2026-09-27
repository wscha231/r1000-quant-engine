# [PROJECT_HANDOFF] SYSTEM_STATE materializer — 2026-09-27

Task: R1000-P0-H2-SYSTEM-STATE-V2-20260927. Issue #533 / #505.
WORK_NEEDED=YES. CODEX_REQUIRED=YES, one final exact-head review.

Initial live master and implementation base:
`3d76ee345a3fda8c242435d70aae07f6475c8221` (merged #554).
Mission derived from config and the merged canonical serializer:
`portfolio-mission-v1`, `broker_ledger_next_close`,
`01a5f5bd57305f0b066664689b96d0935e3467f6ad55055d98463ec99a56913e`.

## Verified source evidence

GitHub run 36318688815 attempt 1, code
`22056e0931f2953cbeb0f0526069c3e28edcd564`: completed / failure.
History job 108618187308 failed collection/verification; diagnostic artifact
10932887058 was published. Its ZIP hash was independently checked.

The latest Drive execution/commit/catalog/quality objects were downloaded via
connected Drive, and each SHA-256 matched its immutable name. Cross-links match
the existing GitHub `publication.json`:

| Role | SHA-256 |
| --- | --- |
| Execution history-36318688815-1 | `10880eb916cd463ec4246f1f7aeb6d2384c40df632a30b4fca148e7aa6c09914` |
| Durable commit | `d2583562f21c56ff939aac235412e5a0dba7102e36360e6ee78e0ab55c82c371` |
| Catalog | `ce0d64e6066018ce04869850c479d2eb944b2864bf16f97788f5e2166dd42530` |
| Quality | `1c323ff5f765f237bee115c18aee7883a4fcdf1941abef1071c1f5848699863b` |
| GitHub diagnostic ZIP | `f46a9b6d9f1d0749fe8b1053cfcebf9bf8d4f763e2f6ffc2e175df16d4b50540` |

Actual classification: PARTIAL_COVERAGE, selector eligibility false, remote
readback true, study_recomputed_from_drive true, consumer_rows 631403.
Two SEC gaps: 0001103838 Companyfacts unavailable with issuer filings present;
0001569650 fundamental entity role unresolved. 1,151 collected dataset entries,
two coverage gaps, no provider failures in the quality report. No full retained
pack replay was performed by this implementation task.

CURRENT_STATUS's operational snapshot remains 2026-08-23 01:05 UTC. No current
Actual Broker, Approved Target, Verified Paper or regime receipt was verified.
The discovered paper immutable-head namespace still lists historical July/August
heads; its existence does not verify a current book. States remain UNKNOWN.

Open issue observations: #505/#506/#529/#531/#533/#535/#536/#537/#538;
#528 is closed by #554. Open issue closure is not certification evidence.
Historical membership, historical universe PIT and final >=8Y flags remain false.

## Causal implementation and limits

Reuse the existing system-state-v2 schema and A0 module, add a read-only source
loader/materializer, semantic hash and deterministic Markdown projection. Require
a fresh, independently supplied canonical intake at the public A0 consumption
boundary. Keep the old routing function private for isolated unit tests, with no
canonical-state authority. Bind new dependency identity into task keys.

Missing/stale/conflicting/hash-mismatched sources remain explicit. Research
capability is scoped to admitted datasets and independent of missing actual
holdings; it does not change A5 business logic, ER, ranking or weights.
Optional present but unadmitted book/regime receipts are BLOCKED until an existing
domain verifier is connected. No new receipt or accepted book architecture is
introduced. See SYSTEM_STATE_MATERIALIZER.md for the complete input contract.

Focused tests cover deterministic replay, current-source changes, mission
mismatch, independent G0/readback/conclusion, missing/stale/conflicting books,
legacy-state rejection, A0 reuse identity and mutation prohibitions. Registered
Tier-1 agent_board_smoke includes the suite without changing the frozen runner.

PR/head/CI/A6/Codex/review-complete/merge evidence and final generated state hash
must be recorded after the actual checks; this document does not pre-attest them.
No G0 rerun, source collection, Drive write, target/paper/broker mutation,
fullrun, production activation, protected-evidence rewrite or alpha change.

Next action: exact-head independent QA, local/remote required gates, then gated
expected-head merge only if clean. After merge, refresh intake and report to L0;
do not automatically start another investment slice. Candidate sequence remains
#536/#538 → #537 → #535 → A2/#503 → #510 → A4 → #526, subject to live L0 judgment.
