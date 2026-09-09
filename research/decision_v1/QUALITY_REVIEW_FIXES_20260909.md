# [PROJECT_HANDOFF] Quality V1 review repairs — 2026-09-09

Scope: bug fixes to existing PR #405. No new alpha rule, rank weight, trade,
production readiness, account, schedule or merge. This is measurable correctness
improvement, NOT evidence of improved CAGR, alpha or a future MDD guarantee.

## Starting authority and environment

- Default master observed: `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
- Target #405 observed: `6a671033cc74265a2d370fc05c05898b2a4a0043` (Draft).
- Direct #400 dependency observed: `52b119ab653016bb1706cf4ff706890e820e131d`.
- Six unresolved exact-head review findings were read from GitHub.
- Original user worktree is unavailable in this session; container network DNS
  failed. The previously delivered source archive was copied into a separate
  patch workspace, and eight relevant original blobs were compared to exact
  GitHub identities. No user worktree was created or changed. Validation is a
  partial source replay, not a full-checkout or native-Windows validation.
- Publication uses only explicitly staged, locally tested blobs via Git objects;
  the local patch tree is NOT claimed to be the full repository tree. The target
  branch must advance without force and only from the inspected causal parent.

## Repairs and review mapping

| Review comment | Repair | Verification |
|---|---|---|
| 3960195367 | Closed baseline schema binds security, market, currency, REAL/SYNTHETIC and cutoff | Cross-identity and missing/extra-field rejection |
| 3960195372 | Every evidence role has a source-kind and issuer relationship rule | Issuer cannot claim customer/industry independence; valid third parties retained |
| 3960195379 | Validate all security IDs and uniqueness before deriving paths or writing anything | Traversal and duplicate IDs create no output directory |
| 3960195386 | Numeric links require the existing scenario envelope gate and valid scenario domains | Stale/future/hash/cutoff/semantic/duplicate payload rejection |
| 3960195392 | Input and text manifest explicitly use UTF-8 | Non-ASCII replay plus checked read/write encoding calls |
| 3960195401 | Report price-only AND price-plus-dividend value/return changes | Base dividend 0→1 at price 10 and probability 0.5 gives +0.05 expected-return delta in synthetic data |

The dividend example is exact fixture arithmetic, not a 5% investment forecast.
Current-price absence preserves a valid scenario value link but percentage-return
fields stay null. The numerical comparison still reuses the existing V1 valuation
functions and is not a second portfolio optimizer.

## Actual checks

- Original 47-test suite on the original code: 47 passed.
- The SAME expanded 65-test suite on original code: FAILED (22 failures,
  5 errors, including subtests and intentionally absent new output fields).
- Expanded 65-test suite on repaired code: 65 passed normally, with Python -O,
  and with default-encoding warnings enabled. These are 65 unique tests, NOT 195.
- Compiled the affected source, replay helper and tests.
- Guarded archived-capture replay runs inside the tests. It reads existing
  saved data; no new vendor/market snapshot or complete H1 admission was run.
- Detailed code/log hashes and scope are in
  `quality_evidence_20260909/review_fix_validation.json`.

## Review-version compatibility

The method is now `quality-evidence-v1.1`. Old v1.0 review receipts are not silently
reissued or accepted under changed interpretation checks. Archived real captures
still match seven retained excerpts, but their old receipts require re-review.
This is not new negative evidence about EME/NVDA/SK hynix. Existing historical
snapshots, execution artifacts and RESEARCH_INDEX are left unchanged. Consumers
must follow their pinned code/method rather than re-label old approvals current.

## Improving without prematurely claiming profitability

Use two evidence tracks, not one all-purpose green flag:

1. Correctness/data track: a reproduced error, its causal fix, exact regression
   checks, independent review, coverage and source-to-decision traceability.
2. Economic track: freeze a baseline and one challenger before observing future
   outcomes; record both decisions with identical information availability and
   the same execution/cost definitions. Evaluate earnings/FCF forecast errors,
   rank discrimination, costs, turnover, drawdowns and realized outcomes only
   as each horizon matures. Keep losing/no-effect experiments. Early operating
   evidence is not mature 12-month return evidence. No experiment is activated
   by this repair.

No-trade/cost/FX and whole-portfolio fixes still belong to their existing H1/H2
scopes. A more restrictive admission rate is not automatically investment
improvement; false rejection and lost opportunities must also be tracked. Never
fill unknown inputs merely to make 0/3 become 3/3 or to force seven positions.

## Shared lesson

Hashes identify captured bytes, not semantic truth. A passing narrow test suite
can miss cross-identity leakage and total-return attribution. Tie comparison
identity and data provenance to each computed quantity, test the negative cases,
and keep correctness PASS separate from PROFITABILITY_NOT_VALIDATED.

## Remaining gates / next action

Full checkout protected test registration and original H1/H2 suites, native
Windows, exact-new-head independent review, actual raw-price/TTM/FX integration,
whole-portfolio execution and OOS/profitability remain incomplete. Do not bypass
these gates, mark review_complete, enable orders or merge automatically.

Next: independently review these fixes; address remaining upstream cash/FX/data
issues in their own scopes; complete one real-company data-to-decision chain;
then freeze a research baseline/challenger and start attributable forward records.
