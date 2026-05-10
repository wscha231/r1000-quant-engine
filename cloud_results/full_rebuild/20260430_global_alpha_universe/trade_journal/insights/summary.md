# Trade Insights Summary

- trades analyzed: **696**
- generated: 2026-04-30 15:26 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_max` in **neutral**: IC = -0.096
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.081
- `h6_dynamic_leader_score` in **bear**: IC = -0.019

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.145
- `theme_phase_multiplier_max` in **bear**: IC = +0.093
- `theme_phase_multiplier_primary` in **bull**: IC = +0.085

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 5: win_rate=0.00, n=12, signature: theme_phase_multiplier_max=-5.87, theme_phase_multiplier_primary=-5.81, h6_dynamic_leader_score=-0.60
- cluster 1: win_rate=0.50, n=22, signature: theme_phase_multiplier_max=-2.82, theme_phase_multiplier_primary=-2.78, rs_acceleration_score=+0.22

**Best pattern clusters (amplify candidates)**:
- cluster 7: win_rate=0.68, n=77, signature: h6_dynamic_leader_score=+1.87, rs_acceleration_score=+1.08, theme_phase_multiplier_max=+0.30
- cluster 2: win_rate=0.67, n=132, signature: rs_acceleration_score=+1.08, h6_dynamic_leader_score=-0.49, theme_phase_multiplier_primary=+0.28

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.