# Trade Insights Summary

- trades analyzed: **918**
- generated: 2026-05-14 07:36 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bear**: IC = -0.043
- `rs_acceleration_score` in **bear**: IC = -0.038
- `h6_dynamic_leader_score` in **bear**: IC = -0.036

**Best signal x regime cells (amplify candidates)**:
- `selection_confirmation_score` in **bear**: IC = +0.088
- `entry_quality_score` in **bull**: IC = +0.082
- `selection_confirmation_score` in **neutral**: IC = +0.074

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 4: win_rate=0.51, n=76, signature: theme_phase_multiplier_max=-2.04, theme_phase_multiplier_primary=-2.04, portfolio_monster_early_score=+1.76
- cluster 5: win_rate=0.51, n=76, signature: selection_confirmation_score=-1.10, h6_dynamic_leader_score=-0.58, theme_phase_multiplier_max=+0.48

**Best pattern clusters (amplify candidates)**:
- cluster 1: win_rate=0.63, n=95, signature: portfolio_risk_entry_block_score=+2.69, portfolio_monster_early_score=+2.13, theme_phase_multiplier_max=-2.04
- cluster 2: win_rate=0.61, n=185, signature: h6_dynamic_leader_score=+1.88, selection_confirmation_score=+0.66, theme_phase_multiplier_max=+0.49

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.