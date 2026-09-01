# Claude Mid-Review Packet - AlphaOps vNext Strengthening (2026-06-26)

## Purpose

Please review the latest Codex work before we continue implementation.

This is **not** a production promotion review. Current objective is:

1. Clean up production evidence substrate, especially PIT universe membership.
2. Keep clean 7Y research/A-B work moving.
3. Avoid adding endless weak levers.
4. Only promote alpha levers after `applied_count > 0`, target-book delta, and broker-ledger delta are proven.

## Current Baseline

Clean 7Y research baseline from run `28074476465`:

- `metric_mode`: `broker_ledger_next_close`
- Main: `33.15% CAGR / -26.02% MDD`
- Concentrated: `46.24% CAGR / -25.82% MDD`
- Window gate: valid 7Y research baseline
- Production promotion: still blocked
- Main target gap: CAGR below `35%`, MDD worse than `-25%`
- Concentrated target gap: CAGR below `50%`, MDD worse than `-25%`
- Standing substrate blocker: `pit_universe_label_clean=false`

Interpretation:

- This is usable for research/A-B.
- It is not production evidence.
- Both sleeves still miss the current mission target.

## PR Status

### PR #184 - PIT membership audit + producer

URL: <https://github.com/wscha231/r1000-quant-engine/pull/184>

Status at review packet creation:

- state: open
- draft: false
- mergeable: true
- CI: green
  - PR Validation Fast: success
  - Portfolio System Guard: success

Branch:

- `codex/pit-membership-audit-20260626`
- head: `909f5ff980dc25c5140b03f9f367a26e530737ea`

Files changed:

- `tools/run_pit_membership_audit.py`
- `tools/build_pit_membership_by_month.py`
- `tools/run_universe_health_audit.py`
- `tools/run_pr_validation.py`
- `tests/pit_membership_audit_smoke.py`
- `tests/pit_membership_producer_smoke.py`

What it does:

- Adds a diagnostic-only PIT membership audit.
- Adds a producer that converts a historical membership source into monthly per-ticker membership rows.
- Blocks clean PIT labels when:
  - `membership_available_from > rebalance_date`
  - `membership_available_from` missing or unknown
  - current constituents are backfilled
  - static seeds/proxy rows are used as if official
  - lifecycle coverage is unknown/bad
  - coverage floor fails
- Integrates optional PIT audit into `run_universe_health_audit.py`.
- Adds `production_promotion_allowed` separately from breadth-only `promotion_allowed`.
- Keeps `tools/run_account_evaluation.py` unchanged. Clean labels must be earned upstream.

Important current artifact check:

Running the audit against `artifacts/28074476465/outputs/universe_health/universe_membership_by_month.csv` correctly blocks clean PIT status because that file is monthly aggregate health, not per-ticker PIT membership.

Observed blocker examples:

- `required_columns_missing`
- `membership_source_kind_not_clean:unknown`
- `unknown_membership_available_from`
- `membership_coverage_floor_failed`

Validation run locally:

- `python tests/pit_membership_audit_smoke.py`
- `python tests/pit_membership_producer_smoke.py`
- `python tests/universe_health_audit_smoke.py`
- `python -m py_compile tools/run_pit_membership_audit.py tools/build_pit_membership_by_month.py tools/run_universe_health_audit.py tests/pit_membership_audit_smoke.py tests/pit_membership_producer_smoke.py`
- `python tools/run_pr_validation.py --only universe_health_audit --only pit_membership_audit --only pit_membership_producer`

Safety:

- No scoring changes.
- No target-book policy changes.
- No cash policy changes.
- No broker replay changes.
- No workflow dispatch changes.
- No live trading or production mutation.

Review questions for Claude:

1. Is PR #184 safe to merge as Track A evidence tooling?
2. Does the producer/audit separation correctly prevent `current_constituents_proxy` from becoming production evidence?
3. Is it correct that `run_account_evaluation.py` remains untouched and clean labels are emitted upstream?
4. Are there missing blockers before we can ever set `pit_universe_label_clean=true`?

## PR #185 - SHAKEOUT_GUARD input carry-through

URL: <https://github.com/wscha231/r1000-quant-engine/pull/185>

Status at review packet creation:

- state: open
- draft: true
- mergeable: true
- CI: green
  - PR Validation Fast: success
  - Portfolio System Guard: success

Branch:

- `codex/shakeout-carrythrough-20260626`
- head: `fe9c84696a670629fe75478d548fc445d4ad954f`

Files changed:

- `tools/run_alphaops_vnext_policy_replay.py`
- `tests/alphaops_vnext_policy_replay_smoke.py`

Why this exists:

Earlier A1 SHAKEOUT measurement showed `shakeout_guard_prod_applied=0`.

Root cause from code/artifact check:

- `candidate_replay_book.csv` contains only limited leader columns:
  - example observed columns include `oneil_leadership_score`, `h6_dynamic_leader_score`
  - missing `sector_leadership_score`
  - missing `smart_money_evidence_confidence`
  - missing direct `leader_tier`
- `sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv` contains SEC/ETF/smart-money evidence columns.
- Candidate resolver already prefers the SEC-enriched candidate book.
- But `tools/run_alphaops_vnext_policy_replay.py::score_month()` only called `score_candidate_lanes()` and then `classify_leader_tier()`.
- It did not compute `sector_leadership_score` or `smart_money_evidence_confidence` first.
- Therefore `SHAKEOUT_GUARD` could be wired but practically no-op.

What changed:

In `tools/run_alphaops_vnext_policy_replay.py`:

- imports:
  - `compute_sector_leadership_score`
  - `compute_smart_money_confirmation_score`
- in `score_month()`:
  - computes `sector_leadership_score` if missing
  - computes `smart_money_evidence_confidence` if missing
  - then continues existing vNext scoring and leader-tier classification

New test:

- `test_score_month_populates_shakeout_guard_inputs_from_enriched_candidate_rows`

It proves enriched candidate rows can populate:

- `sector_leadership_score`
- `smart_money_evidence_confidence`
- `leader_tier`

Validation run locally:

- `python tests/alphaops_vnext_policy_replay_smoke.py`
- `python -m py_compile tools/run_alphaops_vnext_policy_replay.py tests/alphaops_vnext_policy_replay_smoke.py`
- `python tools/run_pr_validation.py --only alphaops_vnext_policy_replay`
- `git diff --check`

Safety:

- Default OFF behavior remains intact.
- Does not enable `PHASE_SHAKEOUT_GUARD_PROD_ENABLED`.
- Does not change production/live/workflow dispatch.
- This is not a performance win yet.
- It only removes an input no-op before A1 can be measured honestly.

Important failed/aborted local check:

I tried to run `tools/run_shakeout_guard_ab.py` against `artifacts/28074476465/outputs`, but it exceeded 10 minutes and was stopped. I also tried vNext-only with `--skip-broker-replay`; it still exceeded 5 minutes and was stopped. Remaining Python processes were killed. No full rebuild was dispatched.

Interpretation:

- A1 should not be accepted yet.
- After PR #185 merges, the next check must be a bounded target-book screen or A1 A/B that first verifies:
  - `shakeout_guard_prod_applied > 0`
  - target-book rows changed for explainable dates/events
  - then, and only then, broker-ledger A/B.

Review questions for Claude:

1. Is #185 safe to mark ready/merge as a default-OFF no-op prerequisite fix?
2. Is computing `sector_leadership_score` and `smart_money_evidence_confidence` inside `score_month()` the right location?
3. Does this risk changing baseline behavior when `PHASE_SHAKEOUT_GUARD_PROD_ENABLED=0`?
4. Should we require a target-book-only applied-count screen before any broker A/B?
5. Do we need additional PIT guards for these computed fields, or are they derived only from current row PIT fields already present in the candidate book?

## Alpha Lever Status

### Dropped-leader rescue

PR #182 merged.

Result:

- strict screen: `no_segment_candidate`
- relaxed screen: `inconclusive_oos_sample`

Decision:

- Do not run target-book/broker A-B for dropped-leader rescue now.
- Treat as a useful negative result.

### Earnings revision break

PR #166 remains lower priority.

Observed local measurement:

- Concentrated CAGR delta about `+0.16pp`
- MDD delta about `+0.45pp`
- Too small to close mission gap

Decision:

- Park as default-OFF infra if merged.
- Do not call it performance improvement.

### Dynamic leader rescue

PR #170 remains lower priority.

Known PR body result:

- Main CAGR delta about `+0.23pp`
- Below ship gate `+0.5pp`

Decision:

- Park as default-OFF infra if merged.
- Do not prioritize over larger bottlenecks.

### A1 SHAKEOUT_GUARD

Current status:

- Logic exists.
- PR #185 fixes the input carry-through no-op risk.
- Not measured yet after fix.

Next acceptance sequence:

1. Merge #185 only if safe.
2. Run target-book-only screen first.
3. Require `shakeout_guard_prod_applied > 0`.
4. If applied count is zero, stop and inspect field availability.
5. If applied count is positive, run broker-ledger A/B.
6. Accept only if:
   - broker metric mode is `broker_ledger_next_close`
   - CAGR improves or does not regress materially
   - MDD degradation remains within gate
   - `pct_held_365d_plus` increases
   - premature sell / EXIT_REPLACE 126d excess improves
   - theme leader capture does not regress

## Current Recommended Sequence

1. Merge #184 if Claude agrees it is safe.
2. Mark #185 ready/merge if Claude agrees it is safe.
3. Run A1 applied-count screen, not fullrun.
4. If A1 applies, run broker-ledger A/B on existing clean 7Y artifact.
5. In parallel, continue Track A data work:
   - source real historical membership file
   - run `build_pit_membership_by_month.py`
   - run `run_pit_membership_audit.py`
   - wire clean artifact into future full rebuild only when source is clean
6. Do not dispatch a new 4-6 hour fullrun until cheap screen shows a real reason.

## What Not To Do

- Do not claim production promotion.
- Do not call 2026 partial-year annualized CAGR evidence.
- Do not use `current_constituents_proxy` as official historical R1000 membership.
- Do not run proxy 8Y/10Y work.
- Do not run T3/recovery.
- Do not enable live trading or production mutation.
- Do not interpret A1 metrics if `shakeout_guard_prod_applied == 0`.
- Do not interpret proxy/weight-level improvements as broker-ledger improvements.

## Specific Claude Verdict Requested

Please answer:

1. `PR #184`: PASS / PASS_WITH_FIXES / BLOCK?
2. `PR #185`: PASS / PASS_WITH_FIXES / BLOCK?
3. If #185 passes, is the next step target-book-only applied-count screen before broker A/B?
4. What is the highest-value next alpha task after #184/#185?
   - A1 SHAKEOUT applied-count screen
   - concentrated sizing / score_power grid
   - regime-gated gross floor
   - another task
5. Are there any leakage or governance gaps in the PIT membership producer/audit?
