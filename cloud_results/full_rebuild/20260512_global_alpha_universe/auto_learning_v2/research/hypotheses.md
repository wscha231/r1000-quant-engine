# AutoLearning v2 Hypotheses

Each hypothesis is falsifiable and proposal-only. Backtests and human approval are required before use.

## 1. main_future_alpha_concentration_v1

- Status: `proposal_only`
- Hypothesis: Main alpha is diluted by broad target N; an internal sleeve orchestrator can concentrate future_winner while capping early_scout.
- Observations: main_broad_high_turnover
- Exploration stage: `shadow`

Test plan:

- Windows: all_months, 2022, 2024_ai_bull
- Metrics: CAGR, MaxDD, Sharpe, turnover, sleeve_attribution
- Falsify if: turnover_not_reduced, future_winner_contribution_not_positive

## 2. concentrated_neutral_25_v1

- Status: `proposal_only`
- Hypothesis: Concentrated should use a dynamic 20-30% risk budget when caps, entry quality, and weekly exits pass.
- Observations: concentrated_alpha_underallocated
- Exploration stage: `shadow`

Test plan:

- Windows: all_months, all_bear_months, 2022, 2024_ai_bull
- Metrics: portfolio_CAGR, portfolio_MaxDD, cap_violations, cash_drag, turnover
- Falsify if: unified_maxdd_below_floor, single_name_cap_violation, stress_window_worsens

## 3. risk_governor_layered_exit_v1

- Status: `proposal_only`
- Hypothesis: Risk sensing needs position-aware exits and better-replacement swaps rather than blunt portfolio cash cuts.
- Observations: risk_sensing_defense_return_tradeoff
- Exploration stage: `shadow`

Test plan:

- Windows: 2020, 2022, all_drawdown_windows
- Metrics: MaxDD, CAGR, Sharpe, late_exit_rate, swap_hit_rate
- Falsify if: cagr_delta_pp < -1.0, sharpe_delta < 0.0

## 4. cluster_conviction_router_v1

- Status: `proposal_only`
- Hypothesis: Trade clusters can route risk: strong clusters get conviction boost, weak clusters trigger caution/block rules.
- Observations: cluster_conviction_asymmetry
- Exploration stage: `shadow`

Test plan:

- Windows: all_months, all_bear_months
- Metrics: cluster_hit_rate, loss_rate, avg_return, turnover
- Falsify if: strong_cluster_bonus_reduces_avg_return, block_rule_removes_winners

## 5. alpha_sprint_breakout_fallback_v1

- Status: `proposal_only`
- Hypothesis: Alpha Sprint should use breakout/RS/catalyst fallback signals until explosion_* features become nonzero and validated.
- Observations: explosion_stack_dormant
- Exploration stage: `shadow`

Test plan:

- Windows: bull_months, strong_bull_months, 2024_ai_bull
- Metrics: standalone_CAGR, hit_rate, avg_loss, portfolio_contribution
- Falsify if: hit_rate < 0.45, maxdd_worsens_by_more_than_2pp

## 6. counterfactual_replay_priority_v1

- Status: `proposal_only`
- Hypothesis: Policy creativity should be blocked from promotion until each sidecar has historical replay evidence.
- Observations: sidecar_without_counterfactual_replay
- Exploration stage: `shadow`

Test plan:

- Windows: all_months
- Metrics: artifact_completeness, backtest_executed, stress_window_coverage
- Falsify if: none
