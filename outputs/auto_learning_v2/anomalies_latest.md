# AutoLearning v2 Anomalies

Research-only anomaly inventory. These observations generate hypotheses; they do not activate production rules.

## 1. bear_rs_theme_inversion

- Category: `signal_regime_inversion`
- Severity: `high`
- Confidence: 0.82
- Observation: Bear-regime trade journal IC favors RS acceleration while theme multipliers are negative.
- Broken assumption: The static rule that theme phase should help selection in every regime is not reliable in bear regimes.
- Suggested hypothesis types: bear_rs_reversal, theme_disable_in_bear, bear_type_classifier

Evidence:

```json
{
  "h1_oversold_value_ic_bear": 0.1190297821818777,
  "n_bear": 138,
  "rs_acceleration_ic_bear": 0.1406098382423332,
  "theme_phase_multiplier_max_ic_bear": -0.08739061496865037,
  "theme_phase_multiplier_primary_ic_bear": -0.11910615493551965
}
```

## 2. concentrated_alpha_underallocated

- Category: `capital_allocation_mismatch`
- Severity: `high`
- Confidence: 0.80
- Observation: Concentrated has materially stronger standalone return/Sharpe but the orchestrator keeps it small.
- Broken assumption: High alpha sources should be tested with dynamic risk budgets instead of permanently small fixed capacity.
- Suggested hypothesis types: concentrated_neutral_20_25, bear_top2_survivor, dynamic_concentrated_n

Evidence:

```json
{
  "concentrated_cagr": 0.3484912610130364,
  "concentrated_max_dd": -0.22940113109440408,
  "concentrated_sharpe": 1.4286886669635341,
  "latest_concentrated_capacity": 0.1,
  "main_cagr": 0.21403316158616126,
  "main_max_dd": -0.2727261662085777,
  "main_sharpe": 1.1831414285357171
}
```

## 3. main_broad_high_turnover

- Category: `portfolio_construction_drag`
- Severity: `high`
- Confidence: 0.78
- Observation: Main remains broad while monthly turnover is high, which can dilute future_winner alpha.
- Broken assumption: A broad one-flow main portfolio is not guaranteed to be the best carrier for sleeve-specific alpha.
- Suggested hypothesis types: main_future_alpha_concentration, target_n_compression, sleeve_orchestrator_inside_main

Evidence:

```json
{
  "main_avg_stock_names": 25.50602409638554,
  "main_avg_turnover_monthly": 0.4858881015027757,
  "main_cagr": 0.21403316158616126,
  "main_max_dd": -0.2727261662085777
}
```

## 4. sidecar_without_counterfactual_replay

- Category: `research_infrastructure_gap`
- Severity: `high`
- Confidence: 0.76
- Observation: Several high-impact sidecars produce snapshots but still lack historical challenger replay.
- Broken assumption: Creative policy generation is unsafe without counterfactual replay for each capital-allocation change.
- Suggested hypothesis types: counterfactual_replay_priority, shadow_only_until_replay

Evidence:

```json
{
  "missing_count": 8,
  "missing_replay": [
    {
      "experiment_id": "E4_concentrated_balanced",
      "status": "standalone_sleeve_policy_audit"
    },
    {
      "experiment_id": "E1_auto_feature_gates_on",
      "status": "candidate_only"
    },
    {
      "experiment_id": "E2_main_v2_balanced",
      "status": "snapshot_report_only"
    },
    {
      "experiment_id": "E3_main_v2_aggressive",
      "status": "snapshot_report_only"
    },
    {
      "experiment_id": "E5_orchestrator_balanced",
      "status": "snapshot_report_only"
    },
    {
      "experiment_id": "E7_tactical_bull_only",
      "status": "sidecar_latest_only"
    },
    {
      "experiment_id": "E8_alpha_sprint_sidecar",
      "status": "sidecar_latest_only"
    },
    {
      "experiment_id": "E9_kitchen_sink_all_on",
      "status": "snapshot_discovery_only"
    }
  ]
}
```

## 5. bear_oversold_value_positive_ic

- Category: `counter_consensus_factor`
- Severity: `medium`
- Confidence: 0.74
- Observation: Oversold value has positive IC in bear months, suggesting bear is not purely momentum-off.
- Broken assumption: The engine should not assume all bear exposure must be cash/core only.
- Suggested hypothesis types: bear_oversold_value_recovery, defensive_leader_substitution

Evidence:

```json
{
  "h1_oversold_value_ic_bear": 0.1190297821818777,
  "n_bear": 138
}
```

## 6. risk_sensing_defense_return_tradeoff

- Category: `risk_policy_tradeoff`
- Severity: `medium`
- Confidence: 0.72
- Observation: Simplified risk sensing improves drawdown but reduces CAGR/Sharpe in the aggressive matrix.
- Broken assumption: A blunt portfolio breaker may protect capital but suppress upside without position-aware exits and swaps.
- Suggested hypothesis types: risk_governor_layered_exit, better_replacement_swap, drawdown_kill_switch

Evidence:

```json
{
  "cagr_delta_pp": -2.937219575004235,
  "maxdd_delta_pp": 5.64744405347003,
  "sharpe_delta": -0.0636541409809035,
  "status": "simplified_layer2_backtest"
}
```

## 7. cluster_conviction_asymmetry

- Category: `trade_pattern_asymmetry`
- Severity: `medium`
- Confidence: 0.70
- Observation: Trade clusters show large dispersion between strong amplification candidates and weak/caution patterns.
- Broken assumption: Signal IC alone misses pattern-level context; cluster routing can amplify winners and block traps.
- Suggested hypothesis types: cluster_conviction_router, pattern_block_or_amplify

Evidence:

```json
{
  "strong_clusters": [
    {
      "avg_realized_return": 0.11644388673530486,
      "cluster_id": "1",
      "n": 125,
      "win_rate": 0.632
    },
    {
      "avg_realized_return": 0.10466274381235224,
      "cluster_id": "5",
      "n": 94,
      "win_rate": 0.6702127659574468
    }
  ],
  "weak_clusters": [
    {
      "avg_realized_return": 0.0,
      "cluster_id": "6",
      "n": 19,
      "win_rate": 0.0
    },
    {
      "avg_realized_return": 0.039281889331689426,
      "cluster_id": "0",
      "n": 56,
      "win_rate": 0.48214285714285715
    },
    {
      "avg_realized_return": 0.019201390284308666,
      "cluster_id": "3",
      "n": 26,
      "win_rate": 0.5
    }
  ]
}
```

## 8. explosion_stack_dormant

- Category: `dormant_signal_stack`
- Severity: `medium`
- Confidence: 0.68
- Observation: Explosion entry/exit rows exist in the trade journal IC matrix but have no numeric IC evidence.
- Broken assumption: Alpha Sprint cannot depend on explosion_* alone until the feature stack produces usable nonzero evidence.
- Suggested hypothesis types: alpha_sprint_breakout_fallback, explosion_feature_repair

Evidence:

```json
{
  "explosion_entry_n_all": 695,
  "explosion_exit_n_all": 695
}
```
