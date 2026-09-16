# H1 Unified Candidate Universe — 2026-09-16

Status: `RESEARCH_ONLY` / candidate-discovery plumbing only.

Stack order: parent #437 (13F parser integrity) -> parent #439 (13F security identity) -> this change.

## Purpose

Create an explicit research universe contract for:

`R1000 base ∪ curated ADR base ∪ validated event-discovered securities`

without turning event membership into an automatic buy signal or portfolio weight.

## Membership semantics

Each ticker can retain multiple independent membership reasons.

- `R1000_BASE`: base coverage reason. It does not expire because an event disappears.
- `ADR_BASE`: curated US-listed ADR/foreign-security coverage reason.
- `SEC_13F_EVENT_RESEARCH`: H1-validated cash-equity 13F change. H2 manager skill is still pending and is **not** claimed.
- `FORM4_EVENT`: schema is supported but activation requires a dedicated H1 receipt with `status=VERIFIED_H1` and `eligible_for_candidate_universe=true`. The current legacy Form4 output is therefore not silently promoted.

Event polarity is independent from membership:

- positive/new/accumulation-only -> `CANDIDATE`
- sale/reduction-only -> `RISK_WATCH`
- simultaneous positive and negative -> `MIXED_REVIEW`

An event-only `RISK_WATCH` security is retained in the monitoring/data queue but is not passed to the buy-candidate scanner solely because of the negative event. A base R1000/ADR member remains scan-eligible even when a risk event is attached.

## 13F provenance boundary

The candidate-universe CLI does **not** trust mutable `13f_latest.csv` or a hand-authored boolean summary as proof of H1 verification.

For 13F expansion it now consumes the existing `sec-13f-publication-verification-v2` receipt plus the exact canonical holdings artifact and verifies:

- receipt schema and `ready` status;
- research-only / no-production / no-live-trading boundary;
- empty verification failure list;
- exact expected/observed workflow run, head SHA and branch identity;
- exact holdings SHA256 against the receipt;
- current H1 security-identity/numeric semantics while rebuilding the stock-level signal directly from holdings.

The manifest records the verification-receipt SHA, holdings SHA, recomputed signal-content SHA, upstream workflow identity, candidate cutoff and lookback. Therefore an arbitrary summary file alone cannot expand the CLI-produced universe.

If only part of the 13F evidence chain is present, the R1000/ADR base remains available while `sec_13f` is labelled `BLOCKED_UNVERIFIED_INCOMPLETE_EVIDENCE_CHAIN`. With `--require-13f`, the run fails closed instead.

## Actual scanner connection

`tools/run_candidate_universe_scan.py` reads the hash-bound `candidate_universe.csv`, selects only `candidate_scan_eligible=true`, then invokes the existing `aggressive.scanner.scan(tickers=<explicit union>, universe_source="custom")`.

This proves the event-discovered ticker is supplied to the existing scanner function rather than merely appearing in a side report. The runner attaches membership/risk metadata to returned candidates but sets `event_membership_score_bonus=0.0`; no scoring weights are changed in H1.

## Data queue

The refresh emits `data_queue.csv` for every active monitoring ticker:

- base-only -> `BASE_COVERAGE`
- event-discovered -> `EVENT_REVIEW`
- event-only negative/risk -> `RISK_REVIEW_MONITOR_ONLY`

`data_status=REQUIRED_OR_REUSE_VERIFIED_CACHE` means the ticker must either have verified reusable data or be collected by a later data-refresh step. This H1 slice does not claim that every ticker already has complete price/fundamental/estimate coverage.

## Source gates

- R1000 `themes_fallback` is rejected for this registry. A deprecated theme fallback must not masquerade as the requested R1000 base.
- The CLI 13F path requires a verified publication receipt + exact holdings hash and recomputes the event signal using current H1 code.
- 13F membership reason is labelled `H1_VERIFIED_H2_MANAGER_SKILL_PENDING`; it is not a verified top-manager alpha claim.
- Form4 stays `BLOCKED_UNVERIFIED` until its separate collector/freshness/semantic H1 work produces the required receipt.
- Future-dated events, malformed tickers/numerics, duplicate reason identities and hash-tampered universe artifacts fail closed.

## Validation

Existing/new contract coverage includes:

- base-reason union and no duplicate ticker;
- event-only risk monitoring vs buy-candidate eligibility;
- event-discovered ticker propagation into the existing scanner with zero event score bonus;
- manifest tamper detection, themes-fallback rejection and overwrite blocking;
- verified holdings successfully recomputing an event-discovered security;
- wrong holdings hash rejection;
- blocked publication receipt rejection;
- expected/observed upstream identity mismatch rejection;
- receipt failure-list rejection even when the status string says `ready`.

The candidate-universe suites are invoked from existing `tests/sec_candidate_enrichment_smoke.py`, already registered in `tools/run_pr_validation.py`. Exact-head CI is authoritative; earlier pre-provenance test counts are historical evidence only.

## Explicit non-claims / next work

This change does **not**:
- repair/activate the current Form4 daily collector;
- validate H2 manager rankings or call a 13F source a skilled/top manager;
- collect all missing data for event-added tickers yet;
- modify the production selector, target books, manager roster, paper/broker ledger, orders or live trading;
- add event score weights or claim portfolio/CAGR improvement.

Next causal slices are: Form4 H1 freshness/universe expansion, explicit candidate data-refresh queue consumption for price/fundamental/estimate channels, and then verified propagation into the full company evaluator. H2 manager-skill/rotation remains a separate research PR family.
