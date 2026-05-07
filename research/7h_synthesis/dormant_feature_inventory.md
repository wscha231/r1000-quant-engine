# Dormant Feature Inventory

Date: 2026-05-03 KST
Branch: `codex/integrate-phase17-19`
Mode: research and planning only

## Inventory Summary

This branch has many capabilities that are useful but intentionally dormant,
sidecar-only, report-only, or proposal-only. That is the right state for now.
The next step is to test them in `research/aggressive_lab_202605`, not to wire
them directly into production.

Status definitions:

- `production`: currently affects main or concentrated backtest behavior.
- `shadow`: creates an alternative output from production artifacts.
- `sidecar`: creates diagnostic, monitor, or research output.
- `proposal-only`: generates inactive candidates for review.
- `dormant`: code or columns exist, but latest artifacts show no live signal or
  no active consumer.

## Feature Inventory

| Capability | Main files or artifacts | Status | Evidence | Activation blocker | First lab experiment |
| --- | --- | --- | --- | --- | --- |
| Main portfolio baseline | `r1000_pipeline.py`, `r1000_top30_institutional.py`, `r1000_config.py` | production | Latest main metrics in baseline registry | None, this is the champion | `E0_baseline_latest` |
| Concentrated alpha | `concentrated_portfolio_latest.csv`, concentrated backtest logic | production comparison, separate sleeve | Latest CAGR 34.85%, Sharpe 1.4287 | Larger allocation needs caps and unified risk budget | `E4_concentrated_balanced` |
| `MANDATE_REGISTRY` | `r1000_config.py` | shadow metadata | Comment says orchestrator uses it for inspection reports | Not historically backtested as allocation engine | `E5_orchestrator_balanced` |
| Orchestrator unified target | `r1000_orchestrator.py`, `tools/run_orchestrator.py` | report-only shadow | Code comment says no order routing consumes it | Needs 83-month backtest and merge mode A/B | `E5_orchestrator_balanced` |
| Max-merge conflict handling | `r1000_orchestrator.py` | shadow | Latest cash target 27.56%, one conflict | Could under-invest after duplicate tickers | `E5_orchestrator_balanced` |
| Regime state classifier | `r1000_features.py`, `PHASE17_REGIME_STATE_COLUMNS` | surfaced, dormant as allocator | Latest 673 rows all neutral | Regime health and historical distribution tests | `E5`, `E6`, `E7`, `E8` |
| Explosion score columns | `r1000_features.py`, `PHASE17_EXPLOSION_COLUMNS` | surfaced, dormant | Latest `explosion_nonzero=false` | Trained model availability and signal validation | `E7`, `E8` |
| Explosive mover miner | `tools/build_explosive_pattern_db.py` | research sidecar | Historical explosion event builder exists | Needs maintained pattern DB and leakage checks | `E8_alpha_sprint_sidecar` |
| Explosion classifier | `tools/train_explosion_classifier.py` | research sidecar | Entry/exit model trainer exists | Latest score fallback is zero | `E7`, `E8` |
| Explosive mover daily scan | `tools/explosive_mover_scan_daily.py` | sidecar | Warns when explosion scores are all zero | Needs nonzero scores and gate evidence | `E8_alpha_sprint_sidecar` |
| Tactical backtester | `r1000_tactical_backtest.py` | research-only | Header says backtest before trusting production signal | Needs standalone after-cost edge and drawdown gate | `E7_tactical_bull_only` |
| Tactical daily monitor | `r1000_tactical_alpha.py` | sidecar | Writes tactical candidates, portfolio, trade plan | Does not change core portfolio export | `E7_tactical_bull_only` |
| Daily macro snapshot | `tools/macro_daily_snapshot.py` | sidecar | Writes `cloud_results/macro_daily` | Not connected to production sizing or no-buy flags | `E6_risk_sensing_on` |
| ETF leadership snapshot | `tools/etf_leadership_snapshot.py` | sidecar | Tracks sector/theme ETFs | Does not alter sector caps | Later theme/risk experiments |
| Risk sensing engine | `r1000_risk_sensing.py` | logic present, partly dormant | Four layers defined | Not wired into historical position-level backtest or operator path | `E6_risk_sensing_on` |
| Risk sensing backtest | `r1000_risk_sensing_backtest.py` | partial report-only | File notes full position-level backtest is future work | Only Layer 2 DD simulation is covered | `E6_risk_sensing_on` |
| Layer 4 swap bridge | `r1000_layer4_swap.py` | suggestions and optional executor | Comments say suggestions by default; executor exists | Broker execution excluded, needs report-only use | `E6_risk_sensing_on` |
| Trade journal | `r1000_trade_journal.py`, trade journal artifacts | sidecar | Latest 695 trades analyzed | Must avoid direct overfit gates | All experiments output summary |
| Trade insights | `tools/trade_insights.py` | research report | IC and cluster reports exist | Needs challenger run before acting | `E1_auto_feature_gates_on` |
| Feature gate proposal | `tools/feature_gate_proposal.py` | proposal-only | Generates candidate YAML and diff | Candidate must pass promotion gates | `E1_auto_feature_gates_on` |
| Auto-learning promote | `tools/auto_learning_promote.py` | guarded proposal promotion | Latest dry run blocked | Main CAGR, Sharpe, MaxDD floors failed | AutoLearning v2 design |
| Active auto gates | `research/auto_feature_gates.yaml` path | inactive or absent in production path | Latest candidate path is under outputs | Human approval required | `E1_auto_feature_gates_on` |
| Alpha Sprint | not implemented as production sleeve | design-only | Requested as new sidecar | Needs standalone module and backtest | `E8_alpha_sprint_sidecar` |
| Order tickets | no approved production order path | design-only | User requested preview-only order tickets | Broker execution explicitly excluded | Later execution realism stage |

## Dormant Signal Details

### Regime State

`regime_state` and `regime_state_score` exist in the feature surface, but latest
diagnostics show all rows are `neutral`.

Before any regime-conditioned allocation is trusted:

- Verify historical monthly regime distribution.
- Confirm regimes vary in 2020, 2022, and 2025-2026 windows.
- Compare classifier state against macro daily snapshot.
- Check whether all-neutral latest state is expected or a sensitivity issue.

### Explosion Scores

`explosion_entry_score`, `explosion_exit_score`, and `explosion_net_score` are
present, but latest diagnostics show `explosion_nonzero=false`.

Before these can drive selection:

- Confirm explosion model files exist and load in the target environment.
- Compare fallback-zero behavior against explicit missing-model warnings.
- Measure standalone tactical/Alpha Sprint performance with and without
  explosion scores.
- Keep scores out of `DEFAULT_FEATURES` until challenger evidence exists.

## Proposal-Only Gates

Latest candidate gates:

```yaml
bear:
  rs_acceleration_score: x1.3
  h1_oversold_value_score: x1.3
  theme_phase_multiplier_primary: 0.0
  theme_phase_multiplier_max: 0.0
```

Latest promotion was blocked because:

- Main CAGR floor failed.
- Main Sharpe floor failed.
- Main MaxDD floor failed.

This means the proposal mechanism is working as a safety system. The next step
is a challenger experiment, not a direct copy to active gates.

## Production, Shadow, Sidecar, Research-Only Map

| Artifact type | Allowed to affect production today | Examples |
| --- | --- | --- |
| Production | Yes, existing behavior only | Main backtest, concentrated comparison |
| Shadow | No | Orchestrator unified targets |
| Sidecar | No | Trade journal, macro daily, ETF leadership, tactical monitor |
| Proposal-only | No | Auto feature gate candidate YAML |
| Research-only | No | Tactical backtester, explosion trainer, Alpha Sprint design |

## Promotion Rules

No dormant feature can become production unless all are true:

1. It is activated only through an experiment override or config flag.
2. It writes isolated outputs.
3. It is compared against `E0_baseline_latest`.
4. It passes discovery gates.
5. It passes production gates.
6. It has a written failure mode and rollback path.
7. Human approval is recorded before changing production defaults.

## Immediate Lab Priorities

1. `E1_auto_feature_gates_on`: test the current proposal in challenger mode.
2. `E2_main_v2_balanced`: reduce broad main dilution without over-concentrating.
3. `E4_concentrated_balanced`: increase concentrated allocation only with caps.
4. `E5_orchestrator_balanced`: prove historical allocation and merge behavior.
5. `E6_risk_sensing_on`: test risk actions historically before operator use.
6. `E8_alpha_sprint_sidecar`: create a small bull-only research sleeve.
