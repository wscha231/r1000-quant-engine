# Trade Insights Summary

- trades analyzed: **535**
- generated: 2026-05-06 11:33 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.140
- `theme_phase_multiplier_max` in **bear**: IC = -0.140
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.089

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.152
- `h1_oversold_value_score` in **bear**: IC = +0.084
- `rs_acceleration_score` in **bear**: IC = +0.073

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=16, signature: theme_phase_multiplier_max=-5.01, theme_phase_multiplier_primary=-4.99, h6_dynamic_leader_score=-0.63
- cluster 6: win_rate=0.25, n=12, signature: theme_phase_multiplier_primary=-2.37, theme_phase_multiplier_max=-2.19, rs_acceleration_score=+0.65

**Best pattern clusters (amplify candidates)**:
- cluster 3: win_rate=0.69, n=65, signature: h6_dynamic_leader_score=+1.80, rs_acceleration_score=+1.08, theme_phase_multiplier_primary=+0.31
- cluster 7: win_rate=0.58, n=64, signature: h6_dynamic_leader_score=+1.55, rs_acceleration_score=-0.29, theme_phase_multiplier_primary=+0.19

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.