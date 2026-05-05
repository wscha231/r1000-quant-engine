# Trade Insights Summary

- trades analyzed: **688**
- generated: 2026-05-05 02:24 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `h6_dynamic_leader_score` in **neutral**: IC = -0.073
- `theme_phase_multiplier_max` in **neutral**: IC = -0.072
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.058

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.195
- `theme_phase_multiplier_max` in **bull**: IC = +0.095
- `theme_phase_multiplier_max` in **bear**: IC = +0.088

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 5: win_rate=0.00, n=9, signature: theme_phase_multiplier_max=-6.76, theme_phase_multiplier_primary=-6.66, h6_dynamic_leader_score=-0.66
- cluster 1: win_rate=0.47, n=15, signature: theme_phase_multiplier_max=-3.28, theme_phase_multiplier_primary=-3.21, rs_acceleration_score=+0.38

**Best pattern clusters (amplify candidates)**:
- cluster 6: win_rate=0.68, n=99, signature: h6_dynamic_leader_score=+1.68, rs_acceleration_score=+1.03, theme_phase_multiplier_max=+0.25
- cluster 0: win_rate=0.66, n=131, signature: rs_acceleration_score=+1.02, h6_dynamic_leader_score=-0.59, theme_phase_multiplier_primary=+0.26

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.