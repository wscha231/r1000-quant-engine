# Trade Insights Summary

- trades analyzed: **1216**
- generated: 2026-05-11 07:47 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `entry_quality_score` in **deep_bear**: IC = -0.578
- `h6_dynamic_leader_score` in **deep_bear**: IC = -0.247
- `h6_dynamic_leader_score` in **bear**: IC = -0.169

**Best signal x regime cells (amplify candidates)**:
- `rs_acceleration_score` in **deep_bear**: IC = +0.619
- `rs_acceleration_score` in **strong_bull**: IC = +0.268
- `entry_quality_score` in **strong_bull**: IC = +0.225

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 0: win_rate=0.53, n=177, signature: rs_acceleration_score=+0.78, theme_phase_multiplier_primary=+0.60, theme_phase_multiplier_max=+0.59
- cluster 2: win_rate=0.55, n=189, signature: rs_acceleration_score=-1.57, theme_phase_multiplier_max=+0.58, theme_phase_multiplier_primary=+0.58

**Best pattern clusters (amplify candidates)**:
- cluster 3: win_rate=0.69, n=132, signature: h6_dynamic_leader_score=+1.95, rs_acceleration_score=+0.98, selection_confirmation_score=+0.76
- cluster 1: win_rate=0.63, n=219, signature: portfolio_risk_entry_block_score=+1.98, portfolio_monster_early_score=+1.72, theme_phase_multiplier_max=-1.65

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.