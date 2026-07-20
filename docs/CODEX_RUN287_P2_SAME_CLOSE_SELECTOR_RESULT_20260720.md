# Run287 P2 same-close selector result — 2026-07-20

## Decision

P2 is implemented as a fail-closed forward-paper boundary.  Repricing or
redating a restored target is now explicitly
`RESTORED_TARGET_REVALUATION_ONLY` and can never set
`same_close_selector_recomputed=true`.  A new paper target is written only
after the current cross-section, six active model heads, frozen selector,
marked account, holding risk, proposed-candidate risk, and all input hashes
agree on one completed NYSE session.

This change does not promote a strategy, run a historical backtest, or alter
the frozen CAGR/MDD evidence.

## Canonical timestamp contract

Every selector projection, target row, and decision snapshot carries:

- `signal_source_date`
- `feature_as_of_date`
- `valuation_close_date`
- `selector_decision_time_utc`
- `target_effective_date`
- `order_eligible_close_date`
- `same_close_selector_recomputed`

The order-eligible date is the first NYSE session strictly after the valuation
close.  Future features, a date mismatch, inactive/constant prediction head,
missing risk provenance, or any hash mismatch writes no target and permits no
new order.

## Daily sequence

1. Confirm the completed NYSE close and exact prices.
2. Transactionally resolve prior pending orders and mark both accounts with
   new-order generation suppressed.
3. Build the exact-date holding-risk view from those marked accounts.
4. Rebuild the PIT feature frame, all six model heads, score stack, and frozen
   Main/Concentrated selector.
5. Run proposed-candidate risk review and the same-close target gate.
6. Only on `READY_SAME_CLOSE_PAPER_TARGETS`, enqueue review-only orders for the
   next NYSE close.  Otherwise retain the mark with zero new orders.

## Fixed risk intersection

- Main uses the preregistered `prior_hold_transition_bridge`; Concentrated uses
  `strict_registered_current`.
- A proposed new entry is retained only when candidate risk is `NORMAL`.
- An existing `ALERT`/`WATCH` holding may not receive incremental weight; its
  proposed increment is capped at the marked weight.
- Vetoed or capped weight remains cash and is not reassigned.
- Cash is included in one-way turnover but excluded from equity transaction
  fees.  Cost diagnostics are fixed at 25/50/100 bps.

## Bounded actual-data verification

The pre-existing exact 2026-07-16 packet was rebuilt with zero network
requests.  The first attempt correctly exposed a false mismatch caused by
provider dividend restatements of historical adjusted closes for MRVL, MU, and
UMC.  The source-identity gate now compares raw closes, replaces the provider
overlap, and rebases only older adjusted history.  The focused restatement
fixture and rebuilt packet then passed.

The resulting paper-only risk-intersected snapshot was:

| Portfolio | Equity names | Cash | One-way turnover vs marked | 25 bp estimated drag |
| --- | --- | ---: | ---: | ---: |
| Main | PANW, DELL, DINO, FTNT, ALAB, AMAT, AMD, HPE | 46.7804% | 93.5948% | 0.3545% |
| Concentrated | DELL, AMD | 88.6000% | 99.1646% | 0.2764% |

Target hashes:

- Main: `b771bf9046d113d2780f05954df810577914f6e0660cb29c6e391a97d8a277f1`
- Concentrated: `0f1bf3afa242825241615606744685e734d387dea0eab39bceea245def5e815b`

These very high cash and turnover readings are useful shadow evidence, not a
recommendation to transition the operating portfolio.  They show why P3–P6
must add a coherent defense/re-entry state machine, long-hold/replacement
logic, and candidate-gate diagnostics before any champion decision.

## Verification and safety

- Same-bundle target and decision hashes are deterministic.
- Synthetic checks cover stale prediction collision upstream, all-zero heads,
  future features, date mismatch, incomplete provenance, restored-target
  revaluation, no-op/cash turnover, fail-closed target creation, and one allowed
  suppressed-mark-to-fresh-target transition.
- Paper state remains transactional across both portfolios.
- Full Tier-1 PR validation passed `179/179` in `555.59s`.
- No fullrun, production activation, live order, or historical CAGR/MDD run was
  executed.
- `pit_universe_label_clean=false` remains unchanged.

## Evidence

- `docs/run287_same_close_target_contract.json`
- `tools/build_run287_same_close_target_books.py`
- `tools/run_run287_current_selector_no_write.py`
- `tools/run_daily_simulated_fill_ledger.py`
- `tests/run287_same_close_target_books_smoke.py`
- `tests/daily_simulated_fill_ledger_smoke.py`
- `.github/workflows/daily_operating_selection_refresh.yml`
