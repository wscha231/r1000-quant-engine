# Run287 next scheduled artifact gate result (2026-07-15)

## Outcome

A single fail-closed auditor now joins the next scheduled estimate archive and
completed-close daily evidence without searching for a latest directory. Every
input path, the expected estimate fetch date, and the expected NYSE session date
must be supplied explicitly.

The audit classifies evidence into three operational states plus one failure:

- `PENDING_MISSING_ARTIFACT` when a named artifact has not arrived;
- `PENDING_1D_NOT_ELAPSED` when all artifacts are valid but no 1D close has
  elapsed;
- `READY_NEXT_SCHEDULED_EVIDENCE_REVIEW_ONLY` when the 150-name estimate attempt,
  exact packet, archive chain, and at least one 1D result are present; and
- `BLOCKED_NEXT_SCHEDULED_ARTIFACT_CONTRACT` when an artifact exists but violates
  its schema, same-session, completeness, circuit, or safety contract.

Pending evidence does not fail a scheduled process. Invalid present evidence
does fail closed.

## Estimate gate

The frozen queue acknowledgement is exactly `150/150/150` selected, attempted,
and acknowledged names over the current `993`-name universe (`992` eligible plus
one non-equity placeholder). Positive estimate coverage is not required:
unavailable vendor data remains neutral and the observed collector status and
coverage counts are retained as diagnostics.

The gate separately requires the new run-scoped entitlement-circuit evidence:

- threshold: three distinct tickers;
- circuit-eligible HTTP statuses: `401` and `403` only;
- HTTP `402`: visible coverage warning, never a global circuit trip;
- persistent vendor disable: forbidden; and
- unmasked secrets: forbidden.

This checks completion and request-cost behavior without turning missing
estimates into an alpha signal.

## Daily exact-packet and first-1D gate

The daily side requires one exact expected session across:

1. completed NYSE session gate;
2. exact close coverage, including one unique row per required ticker;
3. bounded upstream source-bundle status;
4. exact input registry;
5. exact selector/risk packet producer;
6. append-only decision observation archive; and
7. forward risk-outcome archive.

Every component must preserve its no-backtest, no-fullrun, no-order,
no-target-book, no-weight, no-cash, no-production, and no-live-trading boundary.
The auditor exposes 1D warning/normal counts and their differences, but hard
codes `rule_change_allowed=false` and `historical_ab_allowed=false`. Only the
pre-existing 63D gate can make a forward mechanism review available, and that
still cannot become historical CAGR/MDD evidence by itself.

## Negative real-artifact proof

The prior scheduled estimate artifact `29304288757` was audited against its
actual archive manifest. It was correctly classified
`BLOCKED_NEXT_SCHEDULED_ARTIFACT_CONTRACT` because only `36/150` selected names
were attempted and acknowledged. It also predates the new explicit circuit
fields, so the missing run-scoped circuit evidence was reported separately.

This is the intended negative control. The upcoming scheduled artifact, rather
than a manual provider rerun, must prove `150/150` acknowledgement and record
the actual tripped-vendor and avoided-request counts.

## Verification

- ready synthetic chain: passed;
- missing explicit input remains pending: passed;
- valid chain with no elapsed 1D remains pending: passed;
- partial acknowledgement and stale session block: passed;
- an HTTP 402 circuit trip blocks: passed;
- unsafe cash-policy mutation flag blocks: passed;
- focused estimate, exact-packet, archive, and outcome smokes: passed;
- full local PR validation: `176/176` test files passed in `232.42` seconds;
- fullrun, backtest, provider dispatch, order, target-book, weight, cash,
  production, and live-trading actions: none.

Historical generated-book metrics are unchanged:

- Main: CAGR `34.4032%`, MDD `-25.3619%`;
- Concentrated: CAGR `49.0971%`, MDD `-22.9552%`.

The next action is to let the post-settlement scheduled estimate and daily
workflows finish, download their exact artifacts, and run this auditor with
their explicit paths. No portfolio rule is eligible to change from the first
1D diagnostic.

## Evidence files

- `docs/run287_next_scheduled_artifact_gate_contract.json`
- `tools/audit_run287_next_scheduled_artifact_gate.py`
- `tests/run287_next_scheduled_artifact_gate_smoke.py`
- `tools/run_pr_validation.py`
- `_tmp_tests/run287_next_scheduled_old_artifact_audit/summary.json`
