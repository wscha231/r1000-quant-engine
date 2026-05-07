# Regression Attribution Plan

Date: 2026-05-03 KST
Branch: `codex/integrate-phase17-19`
Mode: research and planning only

## Purpose

Explain why latest main results regressed versus the 2026-04-30 run and the
Phase 15-D control. This plan defines the evidence to collect before changing
any production behavior.

Primary output to create after approval:

```text
reports/regression_attribution_20260430_vs_latest.md
```

Optional machine-readable output:

```text
reports/regression_attribution_20260430_vs_latest.json
```

## Baseline Facts

Sources:

- `cloud_results/full_rebuild/20260430_global_alpha_universe/backtest_metrics.json`
- `cloud_results/full_rebuild/20260430_global_alpha_universe/concentrated_backtest_metrics.json`
- `cloud_results/full_rebuild/latest_global_alpha_universe/backtest_metrics.json`
- `cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json`
- `cloud_results/full_rebuild/latest_global_alpha_universe/reports/baseline_registry.json`

| Metric | Phase 15-D control | 2026-04-30 | Latest | Latest vs 2026-04-30 | Latest vs Phase 15-D |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main CAGR | 24.51% | 23.35% | 21.40% | -1.95 pp | -3.11 pp |
| Main Sharpe | 1.2453 | 1.2949 | 1.1831 | -0.1118 | -0.0622 |
| Main MaxDD | -25.79% | -23.74% | -27.27% | -3.53 pp worse | -1.48 pp worse |
| Main monthly turnover | 48.54% | 48.73% | 48.59% | -0.14 pp | +0.05 pp |
| Main avg stock names | 24.33 | 25.40 | 25.51 | +0.11 | +1.18 |
| Concentrated CAGR | n/a | 37.33% | 34.85% | -2.48 pp | n/a |
| Concentrated Sharpe | n/a | 1.4471 | 1.4287 | -0.0184 | n/a |
| Concentrated MaxDD | n/a | -23.06% | -22.94% | +0.12 pp better | n/a |

Initial read:

- Main regression is real and broad: CAGR, Sharpe, and MaxDD all worsened.
- Turnover did not materially improve, so the regression was not a tradeoff for
  lower churn.
- Concentrated stayed strong, but its CAGR also declined versus 2026-04-30.
- Latest main is also below Phase 15-D on CAGR and MaxDD.

## Attribution Questions

1. Did the latest run add one month that was unusually bad, or did the whole
   curve shift?
2. Did holdings composition change materially between 2026-04-30 and latest?
3. Did main become more diluted by lower-ranked names?
4. Did sleeve allocation or sleeve-level return contribution change?
5. Did candidate counts, gate pass rates, or score distributions shift?
6. Did regime state or explosion fallback behavior change?
7. Did ADR/global alpha names help or hurt the latest run?
8. Did trade journal outcomes differ by regime, cluster, or signal?
9. Did config fingerprint, engine version, fast mode, or artifact paths change?
10. Did concentrated alpha fall because of selection, timing, or a new window?

## Required Comparisons

### Run Identity

Compare:

- `run_ts`
- git commit
- engine version
- config fingerprint
- universe mode
- backtest years
- fast mode
- trade cost
- available months
- benchmark source

Source:

- `reports/baseline_registry.json`
- `job_status.txt`
- `run_log_tail.txt`
- `reports/config_audit.json`

### Metrics

Compare main and concentrated:

- CAGR
- Sharpe
- Sortino
- MaxDD
- Calmar
- IR
- volatility
- beat month ratio
- monthly turnover
- average cash
- average stock names
- ending capital
- benchmark CAGR

Source:

- `backtest_metrics.json`
- `concentrated_backtest_metrics.json`
- `reports/backtest_window_comparison.csv`
- `reports/global_alpha_sleeve_audit_summary.csv`
- `reports/global_alpha_sleeve_audit_by_month.csv`

### Equity Curve And Stress Windows

Needed stress windows:

- 2020 COVID crash and rebound.
- 2022 bear market.
- 2025-2026 momentum window.
- Latest month added between 2026-04-30 and latest.

Required outputs:

- Monthly return delta table.
- Drawdown delta table.
- Worst 10 relative months.
- Best 10 relative months.
- Stress window contribution summary.

### Holdings And Contributions

Compare latest and historical holdings:

- `portfolio_latest.csv`
- `concentrated_portfolio_latest.csv`
- `trade_journal/holdings_history.csv`
- `trade_journal/trades.csv`
- `trade_journal/grades.csv`

Required outputs:

- Added tickers.
- Removed tickers.
- Weight deltas.
- Top holdings contribution.
- Sleeve membership changes.
- Concentrated overlap with main.
- ADR/global names contribution.

### Score And Gate Distribution

Compare:

- `scored_latest.csv`
- score quantiles
- factor quantiles
- gate pass counts
- sleeve candidate counts
- target N realized
- score spread between rank 1-5, 6-15, 16-30

Focus on whether latest main is diluted by names beyond rank 15.

### Dormant Feature State

Compare:

- `regime_state` distribution.
- `regime_state_score` distribution.
- max absolute `explosion_entry_score`.
- max absolute `explosion_exit_score`.
- max absolute `explosion_net_score`.
- `live_event_alert_distribution`.

If latest remains all-neutral and explosion all-zero, those features did not
drive the regression directly. They remain dormant or sidecar.

### Trade Journal Evidence

Compare 2026-04-30 and latest:

- trade count
- win rate
- average return by trade
- signal IC by regime
- cluster win rates
- cluster counts
- proposal gates
- promotion decision

Known latest evidence:

- 695 trades analyzed.
- Bear `rs_acceleration_score` and `h1_oversold_value_score` are amplify
  candidates.
- Bear theme multipliers are disable candidates.
- Cluster 5 and cluster 1 are positive.
- Cluster 0 and cluster 6 are caution or block candidates.

## Hypotheses To Test

### H1: Main is too broad

Evidence to look for:

- Lower return contribution from ranks 16-30.
- Similar or worse turnover despite more names.
- Weak score spread after top 15.

Experiment link:

- `E2_main_v2_balanced`
- `E3_main_v2_aggressive`

### H2: Latest regression is window or month sensitivity

Evidence to look for:

- 2026-04-30 has 82 months; latest has 83 months.
- One added month changes CAGR and MaxDD materially.
- Stress window comparison isolates the added drawdown.

Experiment link:

- `E0_baseline_latest`
- regression attribution report

### H3: Concentrated alpha remains valid but needs sizing and caps

Evidence to look for:

- Concentrated MaxDD is still better than main.
- CAGR is still far above main.
- Selection overlap with main can be unified with caps.

Experiment link:

- `E4_concentrated_balanced`
- `E5_orchestrator_balanced`

### H4: Sidecar gates contain useful signal but main challenger failed

Evidence to look for:

- Gate proposals are directionally supported by trade journal IC.
- Promotion failed due to main metrics.
- Candidate gates need a full isolated challenger, not direct activation.

Experiment link:

- `E1_auto_feature_gates_on`

### H5: Orchestrator max-merge creates too much cash drag

Evidence to look for:

- Latest orchestrator cash target is 27.56%.
- Duplicate ticker conflict reduces invested capital.
- Neutral concentrated capacity is only 10%.

Experiment link:

- `E5_orchestrator_balanced`
- merge mode A/B

## Implementation Sketch After Approval

Build a report-only attribution tool:

```text
tools/regression_attribution.py
```

Inputs:

```text
--left cloud_results/full_rebuild/20260430_global_alpha_universe
--right cloud_results/full_rebuild/latest_global_alpha_universe
--phase15-control cloud_results/full_rebuild/latest_global_alpha_universe/reports/baseline_registry.json
--out reports/regression_attribution_20260430_vs_latest.md
```

Required behavior:

- Read JSON and CSV artifacts only.
- Do not recompute portfolios.
- Do not change production outputs.
- Tolerate missing optional artifacts.
- Emit a Markdown report and optional JSON.

## Acceptance Criteria

The attribution report is complete when it answers:

1. Which metrics regressed and by how much.
2. Whether the regression is concentrated in one period or broad.
3. Which holdings, sleeves, or ranks explain the largest differences.
4. Whether dormant features were active enough to explain the difference.
5. Which experiment should be run first based on evidence.

No production default should change as part of this work.
