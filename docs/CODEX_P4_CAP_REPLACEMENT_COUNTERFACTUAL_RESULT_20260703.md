# P4 Cap/Replacement Counterfactual Result - 2026-07-03

## Summary

Research-only fixed-book broker counterfactual was extended to support the same
cash-carry accounting used by the Phase 1 research baseline. The initial
counterfactual replay was directionally useful, but it compared cash-carry
challenger metrics against no-carry baseline metrics. That is not an acceptable
delta basis. The tool now emits `baseline_cash_carry_comparable`, and the final
verdict below uses only comparable cash-carry-vs-cash-carry runs.

No fullrun, production mutation, live trading, or target-book mutation was
performed.

## Method

- Portfolio: Concentrated only.
- Book: fixed official operating target book; no vNext regeneration.
- Transformation: swap a PIT-filtered `cap_or_replacement` missed leader into an
  existing non-cash slot at the donor slot weight.
- Cash and total exposure: preserved.
- Cap breach: not allowed.
- Forward returns: copied only to swap audit tables; never used for ranking.
- Cash-carry: `risk_free_rate`, DGS3MO, 1 business day PIT lag, 50 bps haircut,
  ACT/365.

## Comparable Results

### Latest failed fullrun artifact - run 28616190134

Cash-carry control:

- CAGR: 49.3378%
- MaxDD: -23.0181%
- End date: 2026-07-02

| Arm | Swaps | CAGR | Delta | MaxDD | Delta | IS Delta | OOS Delta | Top ticker share | Top era share | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| rank_top15_and_revenue_ge10 | 17 | 51.2250% | +1.8872pp | -23.0186% | -0.0005pp | +1.1970pp | +4.8484pp | 17.6% | 47.1% | candidate |
| rs3_ge30_and_revenue_ge10 | 11 | 50.4804% | +1.1427pp | -23.0235% | -0.0054pp | +0.7149pp | +2.9984pp | 18.2% | 45.5% | backup |
| rs3_ge20_and_revenue_ge10 | 15 | 49.8489% | +0.5111pp | -22.9878% | +0.0302pp | +0.8449pp | -1.2501pp | 20.0% | 46.7% | reject: OOS weak |
| broad rank/RS arms | 19-22 | 48.64%-49.22% | negative to small | about -23.0% | neutral | weak | weak | mixed | mixed | reject |

### Reference artifact - run 28436307420

Cash-carry control:

- CAGR: 48.8322%
- MaxDD: -23.7934%
- End date: 2026-06-29

| Arm | Swaps | CAGR | Delta | MaxDD | Delta | IS Delta | OOS Delta | Top ticker share | Top era share | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| rank_top15_and_revenue_ge10 | 19 | 50.0430% | +1.2108pp | -23.7842% | +0.0092pp | +0.5959pp | +3.9352pp | 15.8% | 47.4% | candidate |
| rs3_ge30_and_revenue_ge10 | 14 | 49.9373% | +1.1051pp | -23.7831% | +0.0104pp | +0.6167pp | +3.2216pp | 21.4% | 50.0% | near miss / backup |
| rs3_ge20_and_revenue_ge10 | 18 | 49.8392% | +1.0070pp | -23.7812% | +0.0122pp | +0.6236pp | +2.6631pp | 16.7% | 44.4% | near miss |
| broad rank/RS arms | 25-30 | 48.44%-49.23% | negative to small | about -23.8% | neutral | weak to negative | positive | mixed | mixed | reject |

## Verdict

`rank_top15_and_revenue_ge10` is the first Concentrated replay-stage candidate
that clears the research headline on both the latest and reference artifacts
under comparable cash-carry accounting:

- Run 28616190134: 51.2250% CAGR / -23.0186% MaxDD.
- Run 28436307420: 50.0430% CAGR / -23.7842% MaxDD.

The result is not production evidence. It is a fixed-book counterfactual based
on already-generated missed-leader audit rows. It should be treated as a
candidate for default-OFF implementation only.

## Guardrails

- Do not revive broad rank/RS rescue. Broad arms are unstable and fail the
  reference artifact.
- Do not use no-carry baseline deltas for cash-carry challenger results.
- Do not run a fullrun yet. The next step is to implement a default-OFF hook
  that can produce the same predicate at decision time without reading forward
  labels or post-hoc audit outputs.
- Before any fullrun, verify `applied_count > 0`, `baseline_cash_carry_comparable=true`,
  cash/total exposure preservation, no cap breach, and no production mutation.
- The top era share is high but below or near 50%. This requires robustness
  review, not automatic rejection.

## Next Engineering Step

Design a default-OFF Concentrated replacement-quality hook:

- Predicate: `leader_rank_ex_ante <= 15` and `revenue_growth >= 0.10`.
- Candidate universe: only names available in the decision-time candidate lane,
  not post-hoc missed-leader audit labels.
- Replacement: existing non-cash slot only, same donor weight, cash preserved.
- Telemetry: applied count, donor/added tickers, donor score, added ex-ante
  rank, revenue growth, RS, cash delta, total exposure delta, cap breach flag.
- Acceptance before fullrun: fixed-book replay-equivalent behavior, broker
  delta passes, OOS does not collapse, not one ticker/one era.
