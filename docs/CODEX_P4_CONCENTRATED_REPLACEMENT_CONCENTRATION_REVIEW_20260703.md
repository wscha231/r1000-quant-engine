# P4 Concentrated Replacement-Quality Concentration Review - 2026-07-03

## Context

This records the follow-up after the fixed-book Concentrated cap/replacement
counterfactual was rerun with portfolio concentration telemetry.

The goal was not to approve a policy hook or dispatch a fullrun. The goal was to
answer a narrower question:

> Did the surviving replacement-quality candidate improve CAGR by secretly
> increasing Concentrated single-name concentration?

Answer: **No.** The strongest candidate improves broker-ledger CAGR while
leaving latest top1/top3/top5/HHI essentially unchanged.

## Method

- Tool:
  `tools/run_concentrated_cap_replacement_broker_counterfactual.py`
- Added telemetry:
  - baseline broker portfolio concentration from `holdings_daily.csv`
  - challenger broker portfolio concentration from `holdings_daily.csv`
  - latest top1/top3/top5 raw account weights
  - stock-book HHI excluding cash
  - stock gross
  - position count
  - concentration deltas vs baseline
- No fullrun.
- No production mutation.
- No live trading.
- Forward labels remain audit-only.

Two aligned datasets were rerun:

| Label | Output | Replay end | Baseline |
|---|---|---:|---|
| latest 286 | `outputs/p4_cap_replacement_broker_counterfactual_28616190134_cash_carry_aligned` | 2026-07-02 | cash-carry control |
| reference 284 | `outputs/p4_cap_replacement_broker_counterfactual_28436307420_cash_carry_aligned` | 2026-06-29 | cash-carry control |

## Best Arm

The strongest arm remains:

`rank_top15_and_revenue_ge10`

It uses PIT columns only:

- `leader_rank_ex_ante <= 15`
- `revenue_growth >= 10%`
- cap/replacement missed leader rows only

## Results

### Latest Run 286 Aligned

Baseline concentration:

- latest top ticker: `SNDK`
- latest top1: `31.37%`
- latest top3: `70.71%`
- latest stock HHI: `0.2802`

`rank_top15_and_revenue_ge10`:

| Metric | Value |
|---|---:|
| Full CAGR | 51.22% |
| Full CAGR delta | +1.887pp |
| Full MaxDD | -23.02% |
| IS CAGR delta | +1.197pp |
| OOS CAGR delta | +4.848pp |
| OOS2 CAGR delta | +2.336pp |
| Swaps | 17 |
| Top added ticker share | LRCX 17.65% |
| Top era share | 2019-2020 47.06% |
| Latest top1 | 31.38% |
| Latest top3 | 70.71% |
| Latest stock HHI | 0.2802 |
| Latest top1 delta | +0.0068pp |
| Latest HHI delta | +0.000007 |
| Portfolio concentration warning | false |

### Reference Run 284 Aligned

Baseline concentration:

- latest top ticker: `SNDK`
- latest top1: `39.17%`
- latest top3: `80.65%`
- latest stock HHI: `0.2831`

`rank_top15_and_revenue_ge10`:

| Metric | Value |
|---|---:|
| Full CAGR | 50.04% |
| Full CAGR delta | +1.211pp |
| Full MaxDD | -23.78% |
| IS CAGR delta | +0.596pp |
| OOS CAGR delta | +3.935pp |
| OOS2 CAGR delta | +1.895pp |
| Swaps | 19 |
| Top added ticker share | LRCX 15.79% |
| Top era share | 2019-2020 47.37% |
| Latest top1 | 39.08% |
| Latest top3 | 80.56% |
| Latest stock HHI | 0.2825 |
| Latest top1 delta | -0.0877pp |
| Latest HHI delta | -0.000608 |
| Portfolio concentration warning | false |

## Interpretation

This is a meaningful diagnostic candidate:

- It clears `50% CAGR / -25% MDD` in both aligned books.
- It does not raise cash or gross exposure.
- It does not create a new latest single-name concentration problem.
- It does not rely on a single added ticker.
- It is still research-only and PIT-clean production remains blocked.
- Round-2 concentration gates are now stricter and machine-readable:
  - top1 delta > +5pp: warning
  - top3 delta > +10pp: warning
  - stock HHI delta > +0.05: warning
  - absolute top1 > 40%: warning
  - absolute top1 > 45%: block
  - absolute top3 > 85%: warning
  - absolute top3 > 90%: severe warning
  - top added ticker share > 35%: warning
  - top added ticker share > 50%: block
  - top era share > 70%: block
  - top year share > 70%: block
  - bucket delta > +10pp: reserved config, pending bucket mapping

However, it is **not yet a fullrun candidate**.

## Remaining Blockers

1. **Policy hook breadth mismatch**

   The current hook path has previously fired much more broadly than this
   counterfactual. Code inspection shows the hook now requires the rejected
   ticker to be present in policy-path `month_rejections`, but that event set is
   still not the same as the fixed-book `missed_leaders_audit` event set used by
   this counterfactual. The next implementation must event-match the
   counterfactual source, not merely any policy-path rejection:

   - same month
   - same cap/replacement rejection class
   - rejected ticker itself must satisfy the PIT rule
   - rejection source must be traceable to the fixed-book missed-leader event
     definition, or the hook/counterfactual event sets must be reconciled by a
     readiness audit
   - max one swap per date
   - no broad cash/gross change

   The readiness audit now also requires hook swap-count parity within +/-10%
   of the fixed-book counterfactual. A hook that is a subset but materially
   under-fires is not accepted as equivalent.

2. **W1 target-book reproducibility**

   Regenerated selection-side books remain diagnostic until W1 control
   reproduction is resolved. This fixed-book result is valid as a counterfactual,
   but the policy path must not be treated as accepted until replay/control
   parity is proven.

3. **Multiple-testing / grid choice**

   `rank_top15_and_revenue_ge10` was selected from a small rule grid. The
   adjacent cells are not all equally strong. Before policy work, the rule must
   be frozen and treated as a hypothesis, not as an optimized production rule.

4. **Latest official cash-carry level**

   A 2026-07-03 attempt to run `run_cash_carry_measurement.py` on the #239
   official book was blocked by stale price-cache coverage for many official
   target-book tickers. The DGS3MO rate cache was refreshed to 2026-07-01
   (`available_from` 2026-07-02), but the available replay price cache still
   contains many official target tickers only through 2026-06-30. Therefore the
   latest-book 51.22% level remains an internally aligned harness result until
   a complete #239 official-book cash-carry measurement reproduces the control.
   The reference-book 50.04% result remains the cleaner level claim because its
   control equals the official cash-carry baseline.

5. **Production blocker**

   `pit_universe_label_clean=false` remains a standing production blocker.

## Claude/GPT Pro Question Packet

Use this narrow packet rather than asking for broad strategy:

1. Given the new broker-holdings concentration telemetry, is
   `rank_top15_and_revenue_ge10` still a valid research candidate?
2. Is latest/reference cross-book pass enough to justify building a
   default-OFF event-matched hook, or should W1 be completed first?
3. Are the concentration thresholds sufficient?
   - top1 delta warning > +5pp
   - top3 delta warning > +10pp
   - HHI delta warning > +0.05
   - absolute top1 warning > 40%
   - absolute top1 block > 45%
   - absolute top3 warning > 85%
   - absolute top3 severe warning > 90%
   - top added ticker share warning > 35%, block > 50%
   - top era/year share block > 70%
   - bucket delta warning > +10pp once bucket mapping is wired
4. Should the hook acceptance require exact event-log inclusion:
   every hook swap must be present in the fixed-book counterfactual swap set,
   and total hook swap count must be within +/-10% of fixed-book swaps?
5. If accepted for implementation, should the first hook be limited to
   `rank_top15_and_revenue_ge10` only, with all other arms rejected?

## Verdict

Status: `diagnostic_candidate_survives_concentration_check`

Next engineering step:

Build a default-OFF **event-matched** hook only if the external red-team agrees
that W1 can remain parallel. Otherwise, finish W1 first and keep this as a
fixed-book diagnostic candidate.

## 2026-07-04 Event-Match Gate Update

Implemented:

- `tools/run_replacement_quality_event_reconciliation.py`
- `tools/run_event_matched_replacement_quality_broker_ab.py`

Validation:

- `tests/replacement_quality_event_reconciliation_smoke.py`
- `tests/event_matched_replacement_quality_broker_ab_smoke.py`

### Event Reconciliation, Latest 286 Hook Probe

Command output:

`outputs/concentrated_replacement_quality_event_reconciliation_286`

Result:

| Metric | Value |
|---|---:|
| Fixed-book events | 17 |
| Hook events | 71 |
| Exact matches | 1 |
| Same ticker/month but different source | 12 |
| Policy-only hook events | 58 |
| Fixed-book-only events | 16 |
| Hook count delta | 317.65% |

Blockers:

- `hook_swaps_not_subset_of_fixed_book_counterfactual`
- `hook_swap_count_outside_tolerance`

PIT audit found no future `available_from` or forward-label ranking use in the
available rows, but the current artifact does not carry explicit
`available_from` columns for these event fields, so it records the warning
`no_available_from_columns_observed`.

Interpretation:

The current policy-path hook is still too broad. It must not be accepted or
fullrun-tested. The event source must be narrowed until hook swaps are a subset
of fixed-book counterfactual swaps and total hook count is within +/-10%.

### Event-Matched Fixed-Book Broker A/B

The new A/B tool applies the fixed swap list directly to the official target
book. It does not use regenerated selection logic.

| Book | Baseline | Event-matched result | Full CAGR delta | MaxDD delta | Applied |
|---|---:|---:|---:|---:|---:|
| Latest 286, 2026-07-02 | 49.34% / -23.02% | 51.22% / -23.02% | +1.887pp | ~0.000pp | 17/17 |
| Reference 284, 2026-06-29 | 48.83% / -23.79% | 50.04% / -23.78% | +1.211pp | +0.009pp | 19/19 |

Outputs:

- `outputs/event_matched_replacement_quality_broker_ab_28616190134`
- `outputs/event_matched_replacement_quality_broker_ab_28436307420`

Interpretation:

The fixed-event candidate remains economically real and cross-book positive.
The blocker is not the fixed-book A/B; it is the current hook event source. The
next implementation step is therefore **not another screen**. It is to make the
default-OFF hook consume an event-matched source equivalent to the fixed-book
swap set, then rerun event reconciliation.

## 2026-07-04 Hook Event-Allowlist Implementation

Implemented in `tools/run_alphaops_vnext_policy_replay.py`:

- New optional env: `R1000_CONC_REPLACEMENT_QUALITY_EVENT_ALLOWLIST`.
- When set, the default-OFF replacement-quality hook only admits fixed-event
  allowlist rows keyed by `(rebalance_date, added_ticker, removed_ticker)`.
- The hook must use the allowlist `removed_ticker` as the donor. It no longer
  chooses an arbitrary weakest existing slot in allowlist mode.
- The loader ignores any forward-return columns in the allowlist file; those
  remain audit labels only.
- Added telemetry:
  - `concentrated_replacement_quality_event_source`
  - `concentrated_replacement_quality_event_allowlist_path`
  - `concentrated_replacement_quality_event_match_status`
  - `concentrated_replacement_quality_event_removed_ticker`

Validation:

- `tests/alphaops_vnext_policy_replay_smoke.py` now verifies that allowlist
  mode forces the fixed-event donor and blocks when that donor is not in the
  current book.
- PR validation passed for:
  - `alphaops_vnext_policy_replay_smoke`
  - `replacement_quality_event_reconciliation_smoke`
  - `event_matched_replacement_quality_broker_ab_smoke`

Remaining acceptance gate:

Rerun the hook probe with
`R1000_CONC_REPLACEMENT_QUALITY_EVENT_ALLOWLIST` pointing to the fixed-event
swap list, then rerun event reconciliation. The hook remains **not accepted**
until its swap set is a subset of the fixed-book counterfactual and total hook
count is within +/-10%.

### Allowlist Probe Result

Reran the latest 286 hook probe with:

`R1000_CONC_REPLACEMENT_QUALITY_EVENT_ALLOWLIST=outputs/event_matched_replacement_quality_broker_ab_28616190134/event_matched_swaps.csv`

Output:

- Hook probe:
  `outputs/replacement_quality_hook_probe_286_allowlist_v2`
- Reconciliation:
  `outputs/concentrated_replacement_quality_event_reconciliation_286_allowlist_v2`

Result:

| Metric | Prior broad hook | Allowlist v2 |
|---|---:|---:|
| Fixed-book events | 17 | 17 |
| Hook events | 71 | 12 |
| Exact matches | 1 | 12 |
| Policy-only hook events | 58 | 0 |
| Fixed-book-only events | 16 | 5 |
| Hook subset of fixed | false | true |
| Count delta | 317.65% | 29.41% |

Interpretation:

The over-fire blocker is fixed: every hook swap is now a fixed-book event. The
remaining blocker is under-fire. All 5 missing events are
`blocked_event_donor_not_in_book`, meaning the generated policy book does not
contain the fixed-book donor ticker for that month:

- 2021-06-30 `NDAQ` replacing `ROKU`
- 2024-05-31 `GOOGL` replacing `THC`
- 2025-08-29 `LRCX` replacing `TLN`
- 2025-09-30 `LRCX` replacing `TLN`
- 2025-10-31 `LRCX` replacing `ALAB`

This should not be "fixed" by choosing a different donor, because that would no
longer match the validated fixed-book counterfactual. The next blocker is W1
target-book reproduction / official-book event source, not another selection
screen.

### W1 Donor-Missing Audit

Implemented:

- `tools/run_replacement_quality_donor_missing_audit.py`
- `tests/replacement_quality_donor_missing_audit_smoke.py`

Latest run:

- Output: `outputs/replacement_quality_donor_missing_audit_286_allowlist_v2`
- Runtime after normalization fix: about 40 seconds on the latest 286 inputs.

Result:

| Classification | Count |
|---|---:|
| `exact_match` | 12 |
| `generated_book_missing_fixed_donor` | 5 |

The audit confirms the remaining five under-fired fixed events are not missing
because the candidate disappears. Each added ticker is present in the candidate
book, and each removed ticker is present in the fixed official book. The blocker
is that the generated policy book does not contain the fixed-book donor, and the
generated policy rejection log does not carry the exact fixed event:

| Date | Add | Fixed donor | Finding |
|---|---|---|---|
| 2021-06-30 | `NDAQ` | `ROKU` | donor in fixed book, absent from generated book |
| 2024-05-31 | `GOOGL` | `THC` | donor in fixed book, absent from generated book |
| 2025-08-29 | `LRCX` | `TLN` | donor in fixed book, absent from generated book |
| 2025-09-30 | `LRCX` | `TLN` | donor in fixed book, absent from generated book |
| 2025-10-31 | `LRCX` | `ALAB` | donor in fixed book, absent from generated book |

Conclusion:

The remaining blocker is W1 control reproduction / official-book event source.
Do not broaden the hook and do not substitute alternate donors. The economically
validated object is still the fixed-book event set.
