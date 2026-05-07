# Current System Map

Date: 2026-05-03 KST
Branch: `codex/integrate-phase17-19`
Mode: research and planning only

## Executive View

The branch preserves the production baseline and adds Phase 17-19 layers as
sidecars, reports, proposal generators, or shadow targets. That separation is
intentional and should remain intact until challenger backtests pass explicit
gates and a human approves promotion.

The current system is not missing one obvious factor. The main issue is that
many useful capabilities now exist, but they are not yet connected to the
selection, sizing, timing, and risk path in a controlled champion/challenger
framework.

## Latest Baseline Registry

Source: `cloud_results/full_rebuild/latest_global_alpha_universe/reports/baseline_registry.json`

| Track | CAGR | Sharpe | MaxDD | Notes |
| --- | ---: | ---: | ---: | --- |
| Phase 15-D control | 24.51% | 1.2453 | -25.79% | Historical control in registry |
| 2026-04-30 control | 23.35% | 1.2949 | -23.74% | Phase 17-19 sidecar validation run |
| Latest main | 21.40% | 1.1831 | -27.27% | Current run, 83 months |
| Latest concentrated | 34.85% | 1.4287 | -22.94% | Strongest current alpha source |

Latest diagnostics:

- Scored latest rows: 673.
- Regime distribution: `neutral` for all 673 rows.
- Explosion columns present: `explosion_entry_score`,
  `explosion_exit_score`, `explosion_net_score`.
- Explosion nonzero: `false`.
- ADR rows: 28.
- ADR selected count: 2.
- Main average monthly turnover: 48.59%.
- Main average stock names: 25.51.

## Production Path Today

The production path is still the legacy portfolio construction path:

```text
run_local.py
  -> r1000_pipeline.run_all()
    -> collect or reuse data
    -> build feature store
    -> compute features and sleeve scores
    -> train or score model
    -> run main backtest
    -> run concentrated comparison
    -> export latest portfolio, metrics, reports
```

Primary files:

- `r1000_pipeline.py`
- `r1000_top30_institutional.py`
- `r1000_config.py`
- `r1000_features.py`
- `r1000_signals.py`

Important production constraints:

- Do not change `DEFAULT_FEATURES` without explicit approval.
- Do not change active sleeve weights, target N, sector caps, or gates directly.
- Do not auto-promote generated gates.
- Do not replace current portfolio construction with orchestrator output yet.

## Current Mandate Registry

Source: `r1000_config.py`

`MANDATE_REGISTRY` is metadata for inspection and shadow composition. It is not
a proven 83-month production allocation engine yet.

| Mandate | Default target N | Deep bear | Bear | Neutral | Bull | Strong bull |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 20 | 35% | 50% | 65% | 75% | 80% |
| concentrated | 5 | 5% | 5% | 10% | 10% | 10% |
| tactical | 5 | 0% | 0% | 0% | 5% | 10% |

The latest orchestrator shadow output used neutral capacities:

- main: 65%
- concentrated: 10%
- tactical: 0%
- cash target after max-merge: 27.56%
- unique tickers: 22
- conflicts: 1

This is useful as a review target, but it is too conservative for a CAGR-push
production replacement without a historical orchestrator backtest.

## Feature Store Surface

The integration exposes these research columns:

- `regime_state`
- `regime_state_score`
- `explosion_entry_score`
- `explosion_exit_score`
- `explosion_net_score`

Current status:

- These are surfaced for scanners, diagnostics, trade journal analysis, and
  future A/B tests.
- They are not added to `DEFAULT_FEATURES` in this branch.
- If explosion models are missing, explosion scores fall back to zeros.
- Latest registry confirms all latest rows are neutral and explosion scores are
  effectively dormant.

## Sidecar And Shadow Components

| Component | Files | Current status | Production impact |
| --- | --- | --- | --- |
| Trade journal | `r1000_trade_journal.py`, `tools/grade_trades.py` | Generates trades, grades, holdings history | Diagnostic only |
| Trade insights | `tools/trade_insights.py` | IC and cluster reports | Research only |
| Feature gate proposal | `tools/feature_gate_proposal.py` | Generates candidate YAML | Proposal only |
| Auto-learning promote | `tools/auto_learning_promote.py` | Checks gates and can copy candidate if allowed | Blocked in latest dry run |
| Tactical backtester | `r1000_tactical_backtest.py` | Research sleeve backtest | Not production allocation |
| Tactical monitor | `r1000_tactical_alpha.py` | Daily tactical candidates and trade plan | Separate sidecar |
| Explosion stack | `tools/build_explosive_pattern_db.py`, `tools/train_explosion_classifier.py`, `tools/explosive_mover_scan_daily.py` | Miner/trainer/scanner | Dormant in latest scores |
| Macro daily | `tools/macro_daily_snapshot.py` | Daily macro snapshot | Sidecar |
| ETF leadership | `tools/etf_leadership_snapshot.py` | ETF relative leadership | Sidecar |
| Risk sensing | `r1000_risk_sensing.py`, `r1000_risk_sensing_backtest.py` | Risk actions and partial DD backtest | Not fully wired to production |
| Orchestrator | `r1000_orchestrator.py`, `tools/run_orchestrator.py` | Shadow unified target | Report-only |

## Trade Journal Evidence

Source: `cloud_results/full_rebuild/latest_global_alpha_universe/trade_journal/insights/summary.md`

The latest trade journal analyzed 695 trades.

Actionable signal findings:

- Bear `rs_acceleration_score`: IC +0.141, n=138.
- Bear `h1_oversold_value_score`: IC +0.119, n=138.
- Bear `theme_phase_multiplier_primary`: IC -0.119, n=138.
- Bear `theme_phase_multiplier_max`: IC -0.087, n=138.
- Bear `h6_dynamic_leader_score`: IC -0.026, weak as a standalone signal.

Actionable cluster findings:

- Cluster 5: win rate 67%, n=94, positive `h6_dynamic_leader_score` plus
  positive `rs_acceleration_score`.
- Cluster 1: win rate 63%, n=125, strong `rs_acceleration_score`.
- Cluster 0: win rate 48%, n=56, positive `h6_dynamic_leader_score` but weak
  `rs_acceleration_score`.
- Cluster 6: win rate 0%, n=19, very weak theme multipliers.

Interpretation:

- In bear regimes, theme multipliers should be tested as disabled or reduced.
- In bear regimes, RS acceleration and H1 oversold value deserve challenger
  amplification tests.
- `h6_dynamic_leader_score` should not be used alone without confirming RS
  acceleration.
- Clusters 5 and 1 are amplify candidates.
- Clusters 0 and 6 are caution or block candidates.

## Current Auto-Learning Status

Source: `cloud_results/full_rebuild/latest_global_alpha_universe/auto_learning/`

Latest generated candidate gates:

- Amplify bear `rs_acceleration_score` by 1.3.
- Amplify bear `h1_oversold_value_score` by 1.3.
- Disable bear `theme_phase_multiplier_primary`.
- Disable bear `theme_phase_multiplier_max`.

Latest promotion decision:

- Candidate exists: true.
- Trade count floor: pass.
- Concentrated CAGR floor: pass.
- Main CAGR floor: fail.
- Main Sharpe floor: fail.
- Main MaxDD floor: fail.
- Approved: false.
- Promoted: false.

This is the correct behavior. Auto-learning is currently a proposal engine, not
an autonomous production policy system.

## Main Diagnosis

Main is broad and high-turnover:

- Average names: 25.51.
- Monthly turnover: 48.59%.
- Latest CAGR: 21.40%, down from Phase 15-D 24.51% and 2026-04-30 23.35%.
- Latest MaxDD: -27.27%, worse than Phase 15-D -25.79% and 2026-04-30 -23.74%.

Candidate direction:

- Reframe main from a broad baseline into `Main v2`, a 12-15 name
  high-conviction winner book.
- Keep `Main v2` shadow-only until backtested.
- Test internal sleeve allocation rather than adding more raw factors.

## Concentrated Diagnosis

Concentrated is the strongest current alpha source:

- Latest CAGR: 34.85%.
- Latest Sharpe: 1.4287.
- Latest MaxDD: -22.94%.
- Latest selected names: 5.

Required before larger capital allocation:

- Single-name cap.
- Theme cap.
- Sector cap.
- Weekly review and event-driven exit.
- Staged entry and replacement logic.
- Unified cap when combined with main and tactical sleeves.

## Orchestrator Diagnosis

The orchestrator is currently an inspection scaffold:

- It scales main, concentrated, and tactical by regime capacity.
- It uses max-merge for duplicate tickers.
- It writes JSON and CSV shadow targets.
- It does not replace the production backtest or latest portfolio.

The latest neutral output leaves 27.56% cash because policy capacity is
conservative and max-merge loses exposure on conflicts.

Required before promotion:

- 83-month orchestrator backtest.
- Merge mode A/B: `max`, `sum_then_cap`, `priority_concentrated`,
  `risk_budget_blend`.
- Unified single-name cap.
- Stress window attribution.

## Safe Next Step

Create an aggressive challenger lab that can turn dormant capabilities on in
isolated experiments while preserving production defaults.

The lab should test:

- Auto feature gates on.
- Main v2 balanced and aggressive.
- Concentrated balanced with caps.
- Orchestrator balanced.
- Risk sensing historical integration.
- Tactical bull-only.
- Alpha Sprint sidecar.
- Kitchen sink discovery-only combination.

No production activation should happen until a candidate passes discovery gates,
then production gates, then human approval.
