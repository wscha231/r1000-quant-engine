# Fusion Candidate Review

Research-only intersection of independent diagnostics.

Forward returns are audit labels only. They are not used in ranking,
target construction, cash policy, production decisions, or live signals.

- status: `completed`
- fusion_review_candidate_count: 97
- segment_review_candidate_count: 13
- used_forward_return_in_ranking: `False`
- outcome_selected_candidate_count: 97
- forward_blind_policy_design_required: `True`
- full_population_walkforward_required: `True`

## Inputs

- right_tail_entry_signal_audit/winner_entry_signals.csv: rows=10 path=`/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/right_tail_entry_signal_audit/winner_entry_signals.csv`
- right_tail_entry_signal_audit/drop_signal_reviews.csv: rows=8 path=`/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/right_tail_entry_signal_audit/drop_signal_reviews.csv`
- right_tail_drop_counterfactual_audit/drop_counterfactuals.csv: rows=237 path=`/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/right_tail_drop_counterfactual_audit/drop_counterfactuals.csv`
- concentrated_cap_replacement_audit/top_missed_cap_replacement.csv: rows=0 path=`/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/concentrated_cap_replacement_audit/top_missed_cap_replacement.csv`
- alpha_beta_attribution/*/name_contribution.csv: rows=220 path=`/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alpha_beta_attribution/<portfolio>/name_contribution.csv`

## Interpretation

- `fusion_review_candidate=true` means at least two independent diagnostics
  point to the same ticker and at least one source is PIT signal evidence.
- `policy_eligible=false` is intentional. A future policy still needs a
  default-OFF implementation and broker-ledger A/B acceptance.
- Outcome-selected sources such as positive realized contribution are
  confirmatory diagnostics only. They may bias the review queue toward
  past winners, so any derived predicate must be designed forward-blind
  from PIT columns and validated on the full candidate population.
