# Run287 chronological paper recovery — owner-only operational runbook (2026-11-21)

**Authority:** Existing Run287 contracts, #324 (single-use owner scope) and #448 / #670 (coordinated user-approved scope). This is a non-executable operating record, not permission to change an accepted ledger, relax a protected gate, run a full backtest, place orders, or activate live trading.

## Grounded observation

- Canonical immutable paper frontier observed in run [44702908551](https://github.com/wscha231/r1000-quant-engine/actions/runs/44702908551): 2026-07-27, terminal SHA-256 `761cf62e2e4b405d9a22d878b35dec38b95b10f17ccc12cdd4bdceb85d175b46`, seven immutable heads. Next exact NYSE successor: 2026-07-28.
- The 2026-11-20 scheduled workflow requested 2026-11-19 and failed `BLOCKED_SESSION_GAP`. Exact close prices available at the later session cannot authorize a jump in accepted paper account time.
- User-authorized sequential 2026-07-28 through 2026-10-28 recovery and previously verified **read-only** 66-session preparation are recorded in [#670](https://github.com/wscha231/r1000-quant-engine/issues/670#issuecomment-6499204951) and [follow-up](https://github.com/wscha231/r1000-quant-engine/issues/670#issuecomment-6508802204). That is not a single unlimited batch execution grant.
- Old candidate capture workflow run `36989287810` completed success on 2026-10-02, historically referencing artifact `11219955566` and digest `sha256:ded0c699a9b7001044f4e3b7ad35d888849b7bc6218623b2dc22f1cc3a348df0`. **Live GET for the workflow's artifact listing on 2026-11-21 returned `total_count=0`.** Therefore this old run/digest pair cannot currently be admitted as a present artifact. Do not reuse a recorded digest when the matching original is absent.
- The existing owner-context metadata preflight previously returned GitHub HTTP 403 for repository/environment secret *names*; no secret values were accessed. A GitHub App missing that metadata permission cannot substitute for the owner `gh` session, and neither an existing user approval nor an old attestation is a credential.

## Recovery order — repeat only after each exact readback

1. **Read-only identity and accepted-state check:** On the owner machine, inspect clean current `master`, `git status/diff`, `AGENTS.md`, active Main/Source/transactional writer, current Drive immutable terminal, and current NYSE calendar. Never force this document's old master SHA or old terminal hash if a newer accepted head exists.
2. **Check current capture artifact before any scope post:** `gh api repos/wscha231/r1000-quant-engine/actions/runs/36989287810/artifacts` currently returned an empty list. Confirm this and any other eligible existing capture. If none matches its exact artifact name, digest, session range, and expiry, use only the pre-existing *capture-only* workflow.
3. **Read-only capture only if required:** The workflow contract in `.github/workflows/daily_operating_selection_refresh.yml` requires `capture_catchup_evidence_only=true`, `force_run=false`, and `session_date` equal to the **latest completed NYSE session at dispatch**, with all evidence/scope IDs blank, all three migration/bootstrap flags false, `latest_run=outputs` and `strict_selection=true`. Example **valid only while 2026-11-20 remains the latest completed NYSE session**:

   ```sh
   gh workflow run daily_operating_selection_refresh.yml \
     --repo wscha231/r1000-quant-engine --ref master \
     -f capture_catchup_evidence_only=true \
     -f force_run=false -f session_date=2026-11-20 \
     -f latest_run=outputs -f strict_selection=true \
     -f allow_risk_outcome_genesis_bootstrap=false \
     -f allow_quarantined_legacy_outcome_parent=false \
     -f allow_verified_paper_canonical_head_bootstrap=false
   ```

   This capture is **read-only on Drive/paper** but produces a GitHub Actions artifact; run only in the existing authorized owner environment. Inspect the new run/attempt, successful capture job, artifact ID/digest, exact selected-session coverage, and unexpired artifact. Do not label failure as successful source evidence. The capture is not a backtest or a trade.
4. **Repair metadata access, not the safety rules:** With the owner-authenticated `gh` session, run both inventory commands (only names and timestamps, never values). If either returns 403, stop and correct that owner's GitHub authorization/connection:

   ```sh
   gh secret list --repo wscha231/r1000-quant-engine
   gh secret list --repo wscha231/r1000-quant-engine --env run287-paper-durable
   ```

   Never copy secrets into GitHub issues, logs or ChatGPT. Do not add a broad PAT to the normal workflow, change attestation HMACs, or replay another actor's comment.
5. **Exact one-session owner attestation:** Verify fresh run/digest and current `master`/Drive parent. Use the existing `tools/create_run287_catchup_scope_attestation.py` with **fresh** capture run ID/digest, current exact default SHA and `--session-date 2026-07-28`; first run without `--post`. The revised helper checks artifact availability **before** secret-scope metadata. If dry-run fails, stop. If valid and owner is ready for immediate execution, use `--post` for a new, time-limited #324 comment, verify and consume it only once through the exact original workflow.
6. **Exact transactional dispatch only after scope is fresh:** `force_run=true`, `session_date=2026-07-28`, `capture_catchup_evidence_only=false`, newly verified capture run ID/digest, the newly posted comment ID, `latest_run=outputs`, `strict_selection=true`, all bootstrap/migration flags false. Verify original price Evidence, the before/after immutable chain, the accepted manifest and durable Drive readback. Only after the accepted July 28 descendant exists, examine whether July 29 is the next exact NYSE session and run the same per-session process with a **new** short-lived scope. Never blindly rerun a transactional workflow.
7. **Stop at authorization boundary:** Pre-approved chronological scope ends **2026-10-28**, not November 20 or a future close. Continued history requires a separately bounded current authorization and authentic price evidence; an unchanged strategy or user's request for current research does not permit backdating unknown decisions. Pattern/ER/A5 readiness and current broker holdings remain independent.
8. **Current market research:** Keep `run287_daily_research_monitor.yml` separate from paper replay. Its current US market observation is neither an approved portfolio nor an actual broker book. A1/A3/A4/A5 sources must independently satisfy G0/PIT/currentness and their own approval criteria.

## Fail-closed statuses and durable record

- `PAPER_GAP`: first missing NYSE session and backlog count; no earlier dates marked complete.
- `CAPTURE_ARTIFACT_MISSING_OR_EXPIRED`: the old run is not a usable source even if historic digest matches a previous note; use existing capture-only path.
- `OWNER_SCOPE_METADATA_403`: current owner cannot complete the required secret-name read; fix connection, **not** attestation rules.
- `PR_REVIEW_PENDING`: local/CI success is not approval to merge into protected master.
- `DATA_BLOCKED`: market/ER/portfolio claims remain withheld until real source and domain evidence pass.

Link current exact master SHA, capture run/attempt/artifact digest, attestation comment ID (not secret values), one-session dispatch ID, selected parent/new head hash and readback receipt to the existing #670 coordination issue. This file documents the verified pathway, not proof that it has run.
