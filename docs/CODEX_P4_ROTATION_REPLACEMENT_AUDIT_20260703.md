# P4 Rotation / Replacement Audit - 2026-07-03

## Verdict

P4 read-only audit is useful and should continue, but it is not yet a policy
candidate. The current evidence is forward-label diagnostic evidence only.

The strongest recurring signal is not broad hold-duration and not broad cash
deployment. It is missed cap/replacement leaders with strong ex-ante rank or
3-month relative strength.

Do not implement a selection hook or dispatch a fullrun from this alone.

## Inputs

Latest run inspected:

- run: `28616190134`
- source:
  `artifacts/run_28616190134_download/user-operating-minimal-global_alpha_universe-28616190134/outputs/stock_selection_quality`

Reference run inspected:

- run: `28436307420`
- source:
  `artifacts/fullrun_28436307420/user/outputs/stock_selection_quality`

Tool:

- `tools/run_concentrated_cap_replacement_audit.py`

Outputs:

- `outputs/p4_rotation_replacement_audit_28616190134`
- `outputs/p4_rotation_replacement_audit_28436307420`

## Validation

Existing P2/P4-adjacent smoke validation passed:

```powershell
python -B tools/run_pr_validation.py --only pit_membership_audit_smoke --only pit_membership_producer_smoke --only universe_health_audit_smoke
```

P4 audit execution is read-only:

- `production_activation_allowed=false`
- `policy_mutation_allowed=false`
- `forward_return_is_audit_label_only=true`
- `forward_labels_used_for_ranking=false`

## Run 28616190134 Result

Broad cap/replacement missed-leader baseline:

- rows: `310`
- labelled 126d rows: `270`
- mean 126d excess: `9.45%`
- positive rate: `55.56%`
- sum 126d excess: `25.52`

Best selective rule:

- rule: `rs3_ge_20pct`
- rows: `172`
- labelled 126d rows: `143`
- mean 126d excess: `14.28%`
- median 126d excess: `6.15%`
- positive rate: `59.44%`
- sum 126d excess: `20.42`

Other strong slices:

- `rs3_ge_30pct`: mean `24.32%`, positive rate `66.25%`
- `rank_top_15`: mean `12.08%`, positive rate `57.76%`
- `rank_top_10`: mean `16.11%`, positive rate `62.04%`
- `rank_top_15_and_revenue_growth_ge_10pct`: mean `23.97%`, positive rate `74.55%`
- `rank_top_10_and_revenue_growth_ge_10pct`: mean `30.66%`, positive rate `80.49%`

Top missed names include multiple eras and sectors, but the strongest recent
cluster is semiconductor/AI-capex adjacent:

- `MU`
- `TER`
- `LRCX`
- `COHR`
- `NVDA`

Also present from prior eras:

- `Z`
- `ROKU`
- `XYZ`
- `DXCM`
- `RUN`

## Reference Run 28436307420 Result

Broad cap/replacement missed-leader baseline:

- rows: `336`
- labelled 126d rows: `296`
- mean 126d excess: `10.67%`
- positive rate: `54.73%`
- sum 126d excess: `31.59`

Best selective rule:

- rule: `rank_top_15`
- rows: `213`
- labelled 126d rows: `189`
- mean 126d excess: `14.46%`
- positive rate: `57.14%`
- sum 126d excess: `27.34`

Other strong slices:

- `rs3_ge_20pct`: mean `16.90%`, positive rate `58.23%`
- `rs3_ge_30pct`: mean `28.83%`, positive rate `64.77%`
- `rank_top_10`: mean `18.57%`, positive rate `60.33%`
- `rank_top_15_and_rs3_ge_30pct`: mean `29.75%`, positive rate `63.24%`
- `semiconductors`: mean `41.33%`, positive rate `75.68%`

The same broad pattern appears in both runs: missed cap/replacement candidates
with strong PIT rank/RS later performed well on forward-label audit metrics.

## Interpretation

This supports a narrow next research question:

> When the concentrated book rejects an ex-ante leader due to cap/replacement
> constraints, is there a PIT-only rule that admits a small candidate slot or
> replacement review without spending the load-bearing cash cushion?

This does not support:

- broad hold-duration rescue;
- broad bull-floor/gross-floor;
- using forward 126d excess in ranking;
- ticker-specific exceptions;
- fullrun dispatch.

## Next Cheap Research Candidate

Design a fixed-book or broker-replay-compatible read-only challenger with:

- trigger family: `cap_or_replacement` missed leader;
- PIT filters:
  - `leader_rank_ex_ante <= 15`, or
  - `rs_spy_3m >= 0.20`, with stricter `>=0.30` arm;
  - optional `revenue_growth >= 0.10` confirmation if available;
- portfolio: Concentrated only;
- cash: do not lower broad cash floor;
- cap: no cap breach;
- forward labels: audit/report only, not ranking;
- acceptance: broker-ledger CAGR/MDD improvement, OOS/IS non-worsening,
  not one ticker/one era.

The first implementation should be a cheap broker replay or fixed-book
counterfactual, not a production policy hook.

## External Review Routing

Do not use Claude yet. The calculation is simple and the result is not
ambiguous enough to justify spending limited Claude review.

Useful GPT Pro/governance question after a challenger is drafted:

> Given repeated forward-label evidence that missed cap/replacement leaders
> with strong PIT rank/RS outperform, should the next research candidate be a
> small extra review slot, a replacement-gap credit, or a cash-funded entry?
> Constraint: do not consume the defensive cash cushion broadly, and do not
> accept any candidate without broker-ledger evidence.

Useful local Codex task:

> Build a research-only fixed-book/broker-replay counterfactual for
> Concentrated cap/replacement missed leaders using PIT-only filters
> (`leader_rank_ex_ante`, `rs_spy_3m`, optional `revenue_growth`) and report
> broker-ledger deltas. No fullrun, no production mutation.

