# Trade Insights Summary

- trades analyzed: **926**
- generated: 2026-05-07 14:05 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.078
- `entry_quality_score` in **neutral**: IC = -0.049
- `theme_phase_multiplier_max` in **neutral**: IC = -0.043

**Best signal x regime cells (amplify candidates)**:
- `entry_quality_score` in **bull**: IC = +0.099
- `h6_dynamic_leader_score` in **neutral**: IC = +0.065
- `theme_phase_multiplier_max` in **bear**: IC = +0.062

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 6: win_rate=0.51, n=57, signature: theme_phase_multiplier_max=-2.08, theme_phase_multiplier_primary=-2.08, selection_confirmation_score=-1.77
- cluster 5: win_rate=0.54, n=158, signature: rs_acceleration_score=-1.45, h6_dynamic_leader_score=-0.48, entry_quality_score=-0.47

**Best pattern clusters (amplify candidates)**:
- cluster 4: win_rate=0.65, n=101, signature: h6_dynamic_leader_score=+1.86, rs_acceleration_score=+0.93, selection_confirmation_score=+0.64
- cluster 1: win_rate=0.61, n=110, signature: portfolio_risk_entry_block_score=+2.54, portfolio_monster_early_score=+2.24, theme_phase_multiplier_max=-2.08

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.