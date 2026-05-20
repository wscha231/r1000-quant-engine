# AutoLearning v2 Anomalies

Research-only anomaly inventory. These observations generate hypotheses; they do not activate production rules.

## 1. concentrated_alpha_underallocated

- Category: `capital_allocation_mismatch`
- Severity: `high`
- Confidence: 0.80
- Observation: Concentrated has materially stronger standalone return/Sharpe but the orchestrator keeps it small.
- Broken assumption: High alpha sources should be tested with dynamic risk budgets instead of permanently small fixed capacity.
- Suggested hypothesis types: concentrated_neutral_20_25, bear_top2_survivor, dynamic_concentrated_n

Evidence:

```json
{
  "concentrated_cagr": 0.4894016706042674,
  "concentrated_max_dd": -0.38448929995729797,
  "concentrated_sharpe": 1.1855100487526875,
  "latest_concentrated_capacity": 0.1,
  "main_cagr": 0.20347971738915804,
  "main_max_dd": -0.3345476089128743,
  "main_sharpe": 0.9914893272915797
}
```

## 2. main_broad_high_turnover

- Category: `portfolio_construction_drag`
- Severity: `high`
- Confidence: 0.78
- Observation: Main remains broad while monthly turnover is high, which can dilute future_winner alpha.
- Broken assumption: A broad one-flow main portfolio is not guaranteed to be the best carrier for sleeve-specific alpha.
- Suggested hypothesis types: main_future_alpha_concentration, target_n_compression, sleeve_orchestrator_inside_main

Evidence:

```json
{
  "main_avg_stock_names": 26.216867469879517,
  "main_avg_turnover_monthly": 0.529198387898223,
  "main_cagr": 0.20347971738915804,
  "main_max_dd": -0.3345476089128743
}
```

## 3. sidecar_without_counterfactual_replay

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

## 4. risk_sensing_defense_return_tradeoff

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

## 5. cluster_conviction_asymmetry

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
      "avg_realized_return": 0.08932513058663706,
      "cluster_id": "0",
      "n": 130,
      "win_rate": 0.6307692307692307
    }
  ],
  "weak_clusters": [
    {
      "avg_realized_return": 0.05118162073121035,
      "cluster_id": "7",
      "n": 83,
      "win_rate": 0.4939759036144578
    }
  ]
}
```

## 6. explosion_stack_dormant

- Category: `dormant_signal_stack`
- Severity: `medium`
- Confidence: 0.68
- Observation: Explosion entry/exit rows exist in the trade journal IC matrix but have no numeric IC evidence.
- Broken assumption: Alpha Sprint cannot depend on explosion_* alone until the feature stack produces usable nonzero evidence.
- Suggested hypothesis types: alpha_sprint_breakout_fallback, explosion_feature_repair

Evidence:

```json
{
  "explosion_entry_n_all": 887,
  "explosion_exit_n_all": 887
}
```
