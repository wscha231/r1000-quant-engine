# Dormant Feature Inventory

This inventory lists features that exist in code or artifacts but are not
production defaults. The aggressive lab may turn them on in isolated research
outputs only. Production defaults remain protected.

## Summary

| Feature | Current State | Aggressive Lab Action | Production Status |
| --- | --- | --- | --- |
| Auto feature gates | proposal-only | E1 forces candidate gates as challenger evidence | blocked until promotion gates pass |
| Main v2 internal orchestrator | sidecar/latest shadow | E2/E3 create isolated Main v2 snapshots | not production |
| Concentrated policy | strong standalone sleeve, cap warnings | E4 audits expanded capacity/caps/timing | not production |
| Orchestrator | latest report-only target | E5/E9 run latest sum-then-cap shadow merge | not production |
| Risk sensing | simplified L2 backtest output exists | E6 normalizes risk-sensing compare output | not production |
| Tactical sleeve | sidecar/review-ready | E7 copies tactical latest candidate/portfolio outputs | not production |
| Alpha Sprint | sidecar/latest shadow | E8/E9 include sprint candidates and activation gate | not production |
| Explosion signals | feature store exposed, latest mostly zero | E7/E8 use RS/breakout/catalyst fallbacks | not model default |
| Trade insights | IC/cluster reports | E1 copies IC/cluster evidence into lab outputs | proposal evidence only |
| AutoLearning policy | proposal-only policy YAML | policy candidate informs lab hypotheses | not production |

## Details

### Auto Feature Gates

Artifacts:

- `cloud_results/full_rebuild/latest_global_alpha_universe/auto_learning/auto_feature_gates_candidate.yaml`
- `outputs/experiments/E1_auto_feature_gates_on/*`

Latest candidate:

- bear `rs_acceleration_score` factor 1.3
- bear `h1_oversold_value_score` factor 1.3
- bear `theme_phase_multiplier_primary` factor 0
- bear `theme_phase_multiplier_max` factor 0

Status: useful research hypothesis. Production promotion remains blocked by
main CAGR/Sharpe/MaxDD gates.

### Main v2

Artifacts:

- `r1000_main_v2.py`
- `tools/run_main_v2_shadow.py`
- `outputs/main_v2/*`

Status: latest shadow only. Needs historical Main v2 backtest before
production consideration.

### Concentrated Policy

Artifacts:

- `r1000_concentrated_policy.py`
- `tools/run_concentrated_policy_audit.py`
- `outputs/concentrated_policy/*`

Latest issue: current concentrated book has cap and entry/risk gate warnings.
This does not invalidate the alpha source; it means capital expansion needs cap
and timing tests first.

### Orchestrator

Artifacts:

- `r1000_orchestrator.py`
- `cloud_results/full_rebuild/latest_global_alpha_universe/orchestrator/*`
- `outputs/experiments/E5_orchestrator_balanced/*`

Status: latest shadow merge only. Needs monthly replay of main/concentrated/
tactical/sprint books for an 83-month orchestrator backtest.

### Risk Sensing

Artifacts:

- `r1000_risk_sensing.py`
- `r1000_risk_sensing_backtest.py`
- `outputs/strategy_backtest/risk_sensing_compare.json`

Current backtest covers simplified Layer 2 drawdown breaker only. Layers 1, 3,
and 4 need per-position state.

### Tactical Sleeve

Artifacts:

- `r1000_tactical_backtest.py`
- `cloud_results/tactical_alpha/latest/*`

Status: sidecar/review-ready. Needs tactical contribution attribution inside
the orchestrator.

### Alpha Sprint

Artifacts:

- `r1000_alpha_sprint.py`
- `tools/run_alpha_sprint_shadow.py`
- `outputs/alpha_sprint/*`

Status: neutral regime keeps sprint at 0% capacity. Candidates are useful for
bull/strong-bull replay tests.

## Lab Rule

Aggressive lab can turn these on in isolated outputs. It cannot mutate:

- production defaults
- active feature-gate files
- broker execution
- leverage or options behavior

Failed experiments are kept and must explain the blocker.
