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

2. **W1 target-book reproducibility**

   Regenerated selection-side books remain diagnostic until W1 control
   reproduction is resolved. This fixed-book result is valid as a counterfactual,
   but the policy path must not be treated as accepted until replay/control
   parity is proven.

3. **Multiple-testing / grid choice**

   `rank_top15_and_revenue_ge10` was selected from a small rule grid. The
   adjacent cells are not all equally strong. Before policy work, the rule must
   be frozen and treated as a hypothesis, not as an optimized production rule.

4. **Production blocker**

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
   - absolute top1 warning > 50%
4. Should the hook acceptance require exact event-log inclusion:
   every hook swap must be present in the fixed-book counterfactual swap set?
5. If accepted for implementation, should the first hook be limited to
   `rank_top15_and_revenue_ge10` only, with all other arms rejected?

## Verdict

Status: `diagnostic_candidate_survives_concentration_check`

Next engineering step:

Build a default-OFF **event-matched** hook only if the external red-team agrees
that W1 can remain parallel. Otherwise, finish W1 first and keep this as a
fixed-book diagnostic candidate.
