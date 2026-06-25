# Claude Handoff - AlphaOps vNext Fusion Review - 2026-06-26

## Purpose

Please review the current AlphaOps vNext direction after the 2026-06-25
ChatGPT Pro + Claude synthesis work.

The user goal is not to blindly keep adding layers. The goal is:

1. merge the best parts of ChatGPT Pro and Claude guidance,
2. reject failed broad layers,
3. preserve any useful PIT-visible diagnostic signal from failed layers,
4. strengthen only evidence-supported candidates,
5. judge all performance claims with reliable, non-leaky evidence.

Production promotion is **not** in scope. Live trading is **not** in scope.

## Current Authoritative Baseline

Official research baseline is GitHub Actions run `28074476465`.

Use this as research evidence only:

| Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Years | Status |
|---|---|---:|---:|---:|---:|---|
| Main | `broker_ledger_next_close` | 33.15% | -26.02% | 1.219 | 7.055 | research only |
| Concentrated | `broker_ledger_next_close` | 46.24% | -25.82% | 1.421 | 7.055 | research only |

Production remains blocked because PIT universe membership is not clean enough.
Do not treat these metrics as production promotion evidence.

## Current PR State

### PR #171 - Layer decision ledger

URL: https://github.com/wscha231/r1000-quant-engine/pull/171

Status at handoff:

- open
- ready, not draft
- mergeable
- CI green:
  - PR Validation (Fast): success
  - Portfolio System Guard: success

Purpose:

- Freezes keep/reject decisions from the 2026-06-25 synthesis pass.
- Separates official broker-ledger evidence from local target-book/proxy screens.
- Adds a salvage/fusion policy:
  - `discard`: failed broad policy rule
  - `keep`: measurement plumbing, telemetry, or PIT-visible signal
  - `fuse`: future candidate only if multiple independent diagnostics agree

Important conclusions in PR #171:

- Reject broad gross floor/cash reduction for Concentrated.
- Reject broad leadership persistence.
- Reject broad concentrated selective leader capture.
- Reject broad dropped-winner continuation.
- Keep diagnostics from #172, #175, #176, and #177.
- Keep small default-OFF research levers #166 and #170.
- Main risk overlay is an MDD repair screen only, not a standalone solution.
- Future fused rule must be PIT-observable, cross-confirmed, `applied_count > 0`,
  and accepted only through broker-ledger CAGR/MDD.

### PR #178 - Fusion candidate review audit

URL: https://github.com/wscha231/r1000-quant-engine/pull/178

Status at handoff:

- open
- draft
- mergeable
- CI green:
  - PR Validation (Fast): success
  - Portfolio System Guard: success

Purpose:

- Implements a review-only sidecar that intersects independent diagnostics
  before any new capture-continuity policy is designed.
- It turns the #171 salvage/fusion policy into a concrete artifact.
- It does **not** create or activate a trading rule.

Files changed in PR #178:

- `tools/run_fusion_candidate_review.py`
- `tests/fusion_candidate_review_smoke.py`
- `tools/run_pr_validation.py`
- `tools/run_full_rebuild_sidecars.py`
- `tests/workflow_artifact_smoke.py`
- `.github/workflows/full_rebuild_manual.yml`

Outputs added by PR #178:

- `outputs/fusion_candidate_review/candidate_signals.csv`
- `outputs/fusion_candidate_review/segment_fusion_summary.csv`
- `outputs/fusion_candidate_review/summary.json`
- `outputs/fusion_candidate_review/report.md`
- `outputs/full_rebuild_logs/fusion_candidate_review.log`

Artifact persistence added in:

- `.github/workflows/full_rebuild_manual.yml`
  - upload artifacts include `outputs/fusion_candidate_review/`
  - upload artifacts include `outputs/full_rebuild_logs/fusion_candidate_review.log`
  - cloud-results copy includes `outputs/fusion_candidate_review`

Full rebuild sidecar wiring:

- `tools/run_full_rebuild_sidecars.py`
  - after `run_alpha_beta_attribution.py`
  - before `run_era_leadership_sidecar.py`
  - command:

```bash
python tools/run_fusion_candidate_review.py --base-dir outputs --output-dir outputs/fusion_candidate_review 2>&1 | tee outputs/full_rebuild_logs/fusion_candidate_review.log || true
```

## What PR #178 Actually Does

`tools/run_fusion_candidate_review.py` reads available outputs from:

- `outputs/right_tail_entry_signal_audit/winner_entry_signals.csv`
- `outputs/right_tail_entry_signal_audit/drop_signal_reviews.csv`
- `outputs/right_tail_drop_counterfactual_audit/drop_counterfactuals.csv`
- `outputs/right_tail_drop_counterfactual_audit/segment_summary.csv`
- `outputs/concentrated_cap_replacement_audit/top_missed_cap_replacement.csv`
- `outputs/alpha_beta_attribution/<portfolio>/name_contribution.csv`

It emits candidates only when independent diagnostics overlap.

Candidate logic:

- `fusion_review_candidate=true` requires:
  - at least two independent evidence sources, and
  - at least one PIT-signal source.
- `fusion_review_score` uses:
  - independent diagnostic source count,
  - PIT signal source count.
- `fusion_review_score` does **not** use forward return labels.

Safety fields:

- `research_only=true`
- `policy_eligible=false`
- `production_mutation_allowed=false`
- `live_trading_enabled=false`
- `used_forward_return_in_ranking=false`
- `forward_blind_policy_design_required=true`
- `full_population_walkforward_required=true`

Forward returns:

- carried only in `audit_forward_*` columns,
- not used in ranking,
- not used in target construction,
- not used in cash policy,
- not used in live signals.

Outcome-selected diagnostics:

- `positive_name_contribution` is deliberately marked as an
  outcome-selected source.
- It can only confirm another PIT-visible source. It cannot create a review
  candidate by itself because `pit_signal_source_count >= 1` is required.
- The summary emits `outcome_selected_candidate_count` and a
  `queue_bias_warning`.
- Any policy derived from the queue must be designed from PIT columns with
  forward/audit columns hidden, then frozen, then validated on the full
  candidate population with walk-forward/OOS evidence.

If producer artifacts are missing, the sidecar emits an empty queue instead of
mutating policy.

## Local Validation Already Run

Use bundled Python, not system Python, because system Python may not have
`pandas`.

Commands run successfully:

```powershell
& 'C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tests\fusion_candidate_review_smoke.py
& 'C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tests\workflow_artifact_smoke.py
& 'C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools\run_pr_validation.py --only fusion_candidate_review --only workflow_artifact --quiet
& 'C:\codex-shadow\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m py_compile tools\run_fusion_candidate_review.py tests\fusion_candidate_review_smoke.py
```

The smoke test intentionally includes a `LUCK` ticker with huge forward return
labels but weak PIT evidence. It verifies that `LUCK` is **not** promoted to a
fusion candidate. This is the key leakage guard.

Additional leakage edge cases now covered:

- `ONEPIT`: huge forward audit label plus exactly one PIT source. It is not a
  candidate because it lacks two independent sources.
- `OUTCOME`: two non-PIT/outcome-selected sources and zero PIT sources. It is
  not a candidate because outcome evidence cannot substitute for PIT evidence.

## Current Open Merge Queue

Recommended order from the current evidence ledger:

1. #171 - decision ledger
2. #167 - official metrics fallback for position risk baseline
3. #169 - missed-leader forward audit labels
4. #172 - concentrated cap/replacement miss audit
5. #174 - gross-floor sweep override wiring
6. #175 - alpha/beta name contribution fallback
7. #176 - right-tail entry signal audit
8. #177 - right-tail drop counterfactual audit
9. #178 - fusion candidate review audit
10. #166 - earnings revision break warning lever, default OFF
11. #170 - dynamic leader candidate rescue gate, default OFF

Rationale:

- #167/#169 improve measurement correctness.
- #172/#175/#176/#177 produce the independent diagnostic inputs.
- #178 intersects those diagnostics into a fusion queue.
- #166/#170 are small default-OFF levers; they should not be treated as solved
  target improvements without broker-ledger A/B.
- #174 has been checked as measurement plumbing only: it wires the
  `R1000_CONC_GROSS_CAP_FLOOR` override into an already gated sweep path and
  explicitly reports that broad Concentrated gross floor should not be
  activated.

## Layers Rejected So Far

Do not retry these unchanged:

- broad gross floor / broad cash reduction,
- broad leadership-persistence hold,
- broad concentrated selective capture,
- broad dropped-winner continuation,
- Main daily trailing risk overlay as a standalone solution,
- SHAKEOUT as alpha lever without `applied_count > 0`,
- broad dynamic leader score bonus,
- PR166 + PR170 unverified combo.

Important nuance:

Rejected does not mean every signal is useless. It means the broad policy failed.
Reusable pieces are:

- PIT entry signal stack,
- drop-date still-skill evidence,
- cap/replacement high-RS missed-leader rows,
- alpha/beta name contribution,
- segment summaries,
- honest applied-count telemetry,
- measurement plumbing.

## Specific Questions For Claude

Please review the current direction and answer these:

1. Is PR #178's fusion candidate sidecar correctly scoped as review-only?
2. Does the `fusion_review_score` avoid forward-return leakage strongly enough?
3. Is the smoke test sufficient to prove a high-forward-return but weak-PIT
   candidate cannot become a fusion candidate?
4. Should PR #178 remain draft until #172/#175/#176/#177 merge, or can it be
   marked ready because it emits empty queues when producer artifacts are absent?
5. Is the recommended merge order correct?
6. After #178, what should the first actual default-OFF policy candidate be?
   Candidate ideas:
   - segment-scoped continuity review for machinery/industrial infrastructure,
   - high-RS cap/replacement miss rescue with PIT entry-stack requirement,
   - Main CAGR-positive layer first, then re-test MDD risk overlay,
   - earnings revision break warning as a small component only.
7. Are there remaining leakage paths not covered by:
   - `used_forward_return_in_ranking=false`,
   - `policy_eligible=false`,
   - no target/cash/scoring/live mutation,
   - forward returns only in `audit_*` columns?

## Current Direction After Claude Review

Claude's current review is accepted:

- #178 can be marked ready because it is review-only and empty-queue safe.
- Do not interpret an empty queue before producer PRs #172/#175/#176/#177 land.
- Stop audit proliferation after the producer set and #178: generate the fusion
  queue once, then design exactly one default-OFF candidate.
- First candidate should target the larger clean-7Y gap: Concentrated CAGR.
- Preferred candidate shape: high-RS cap/replacement miss rescue with a PIT
  entry-stack requirement, segment scoped, not a broad selective-capture layer.
- The candidate must be designed forward-blind, then tested on the full
  candidate population with broker-ledger A/B.

Clean 7Y target gap to keep in view:

- Main: 33.15% CAGR / -26.02% MaxDD, so both CAGR and MDD miss.
- Concentrated: 46.24% CAGR / -25.82% MaxDD, so CAGR is about 3.76pp short
  and MDD is about 0.82pp outside the target.

## Non-Negotiables To Preserve

- Do not claim production promotion.
- Do not enable live trading.
- Do not mutate production targets.
- Do not use 8Y/10Y proxy work.
- Do not use partial-year annualized returns as proof.
- Do not use forward returns in live ranking or historical ex-ante selection.
- Evaluate real improvement only with broker-ledger mechanics.
- Treat PIT universe incompleteness as production blocker.

## Suggested Next Step After Claude Review

If Claude agrees:

1. Merge #171.
2. Merge measurement inputs #167/#169/#172/#174/#175/#176/#177.
3. Mark #178 ready and merge after its producer PRs or immediately if accepted.
4. Run the sidecar on the next full/replay artifact to generate
   `outputs/fusion_candidate_review/`.
5. Review `candidate_signals.csv` and `segment_fusion_summary.csv`.
6. Only then design one small default-OFF candidate rule with:
   - PIT predicate,
   - `applied_count > 0`,
   - broker-ledger A/B,
   - no MDD damage,
   - no forward-label leakage.
