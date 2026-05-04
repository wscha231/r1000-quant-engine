# Trade Insights Summary

- trades analyzed: **561**
- generated: 2026-05-04 10:29 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `rs_acceleration_score` in **neutral**: IC = -0.068
- `theme_phase_multiplier_max` in **neutral**: IC = -0.059
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.034

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **bear**: IC = +0.182
- `theme_phase_multiplier_primary` in **bear**: IC = +0.032
- `theme_phase_multiplier_max` in **bear**: IC = +0.032

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 2: win_rate=0.00, n=10, signature: theme_phase_multiplier_max=-5.97, theme_phase_multiplier_primary=-5.84, h6_dynamic_leader_score=-0.64
- cluster 7: win_rate=0.50, n=197, signature: h6_dynamic_leader_score=-0.55, theme_phase_multiplier_primary=+0.18, theme_phase_multiplier_max=+0.16

**Best pattern clusters (amplify candidates)**:
- cluster 6: win_rate=0.69, n=75, signature: h6_dynamic_leader_score=+1.75, rs_acceleration_score=+1.04, theme_phase_multiplier_max=+0.28
- cluster 5: win_rate=0.66, n=89, signature: rs_acceleration_score=-1.58, h6_dynamic_leader_score=-0.59, theme_phase_multiplier_primary=+0.12

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.