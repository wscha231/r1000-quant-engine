# Trade Insights Summary

- trades analyzed: **540**
- generated: 2026-05-06 07:50 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.108
- `h6_dynamic_leader_score` in **bear**: IC = -0.094
- `theme_phase_multiplier_max` in **bear**: IC = -0.086

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bull**: IC = +0.214
- `h1_oversold_value_score` in **bear**: IC = +0.104
- `theme_phase_multiplier_max` in **bull**: IC = +0.101

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 1: win_rate=0.00, n=16, signature: theme_phase_multiplier_primary=-5.15, theme_phase_multiplier_max=-5.14, h6_dynamic_leader_score=-0.66
- cluster 5: win_rate=0.25, n=8, signature: theme_phase_multiplier_max=-2.46, theme_phase_multiplier_primary=-2.46, rs_acceleration_score=+0.85

**Best pattern clusters (amplify candidates)**:
- cluster 2: win_rate=0.66, n=85, signature: h6_dynamic_leader_score=+1.73, rs_acceleration_score=+0.85, theme_phase_multiplier_primary=+0.29
- cluster 4: win_rate=0.65, n=65, signature: rs_acceleration_score=+1.38, h6_dynamic_leader_score=-0.60, theme_phase_multiplier_primary=+0.26

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.