# AutoLearning System Review

This document records the current state and the next expansion path for R1000
auto-learning. It is research-only and does not authorize production policy
changes.

## Current Scope

The current auto-learning path is a feature-gate proposal loop:

```text
trade_journal
-> tools/trade_insights.py
-> ic_matrix.csv / cluster_winrate.csv
-> tools/feature_gate_proposal.py
-> auto_feature_gates_candidate.yaml
-> challenger rebuild
-> tools/auto_learning_promote.py
-> active feature gates only if explicit gates pass
```

`tools/feature_gate_proposal.py` proposes three gate types:

- `signal_regime_disable`
- `signal_regime_amplify`
- `pattern_block`

`tools/auto_learning_promote.py` is intentionally conservative. It promotes
only an already-tested candidate artifact when main metrics, concentrated
metrics, and trade-count floors pass. It does not invent weights and does not
touch model code.

## Latest Candidate Evidence

The latest feature-gate candidate proposes four bear-regime gates:

- amplify `rs_acceleration_score` by 1.3 in bear
- amplify `h1_oversold_value_score` by 1.3 in bear
- disable `theme_phase_multiplier_primary` in bear
- disable `theme_phase_multiplier_max` in bear

These are grounded in trade-journal IC evidence, but prior promotion was
blocked because champion/challenger safety gates did not pass.

## Gap

The current loop learns signal usage, not full operating policy. It does not
learn:

- main target N
- core/future/early sleeve allocation
- concentrated capacity, caps, and timing rules
- alpha sprint activation
- orchestrator capital allocation
- cash floors
- entry/exit timing
- execution policy

These areas drive realized performance and risk more directly than individual
signal multipliers.

## Target Architecture

The next layer is the R1000 AutoLearning Policy Engine:

```text
trade journal
sleeve audit
main/concentrated metrics
main_v2 audit
concentrated policy audit
alpha_sprint audit
orchestrator audit
risk actions
execution logs
-> evidence loader
-> policy proposal builder
-> auto_learning_policy_candidate.yaml
-> challenger backtest
-> promotion gate
-> human approval
-> active policy
```

The invariant is unchanged:

```text
Auto-learning can propose policy.
Auto-learning cannot directly change production behavior.
```

## New Proposal Areas

The policy candidate schema covers:

- `feature_gates`
- `sleeve_policy`
- `target_n`
- `orchestrator_policy`
- `entry_timing`
- `exit_rules`
- `cash_policy`
- `execution_policy`
- `promotion_gates`

## Initial Implementation Scope

This stage adds:

- `r1000_auto_learning_policy.py`
- `r1000_auto_learning_evidence.py`
- `tools/auto_policy_proposal.py`
- `research/auto_learning_policy_candidate.yaml`
- `outputs/auto_learning/evidence_snapshot.json`
- `outputs/auto_learning/policy_proposal_diff.md`
- `outputs/auto_learning/policy_candidate_summary.md`

It does not add the challenger runner or promotion tool yet.

## Required Next Gate

Before any policy can be promoted, add:

```text
tools/auto_policy_challenger.py
tools/auto_policy_promote.py
```

The challenger must compare champion vs candidate across:

- main metrics
- concentrated metrics
- orchestrator metrics
- stress windows
- turnover and cost sensitivity
- rolling 3-year and 5-year stability

Capital allocation, leverage, and broker execution must remain human-approved.
