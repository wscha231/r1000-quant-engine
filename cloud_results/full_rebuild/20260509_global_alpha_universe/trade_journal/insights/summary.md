# Trade Insights Summary

- trades analyzed: **927**
- generated: 2026-05-09 02:45 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `entry_quality_score` in **bear**: IC = -0.088
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.075
- `rs_acceleration_score` in **bull**: IC = -0.072

**Best signal x regime cells (amplify candidates)**:
- `selection_confirmation_score` in **strong_bull**: IC = +0.592
- `h6_dynamic_leader_score` in **strong_bull**: IC = +0.465
- `entry_quality_score` in **strong_bull**: IC = +0.423

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 7: win_rate=0.47, n=88, signature: selection_confirmation_score=-1.13, h6_dynamic_leader_score=-0.59, theme_phase_multiplier_max=+0.47
- cluster 5: win_rate=0.47, n=53, signature: theme_phase_multiplier_max=-2.10, theme_phase_multiplier_primary=-2.09, selection_confirmation_score=-1.77

**Best pattern clusters (amplify candidates)**:
- cluster 2: win_rate=0.63, n=158, signature: rs_acceleration_score=-1.49, entry_quality_score=-0.45, theme_phase_multiplier_primary=+0.45
- cluster 6: win_rate=0.61, n=181, signature: h6_dynamic_leader_score=+1.88, selection_confirmation_score=+0.64, theme_phase_multiplier_max=+0.47

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.