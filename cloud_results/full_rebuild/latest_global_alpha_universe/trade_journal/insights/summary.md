# Trade Insights Summary

- trades analyzed: **935**
- generated: 2026-05-10 10:56 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **neutral**: IC = -0.066
- `theme_phase_multiplier_primary` in **bear**: IC = -0.057
- `entry_quality_score` in **neutral**: IC = -0.040

**Best signal x regime cells (amplify candidates)**:
- `entry_quality_score` in **strong_bull**: IC = +0.350
- `rs_acceleration_score` in **strong_bull**: IC = +0.209
- `theme_phase_multiplier_primary` in **strong_bull**: IC = +0.108

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 7: win_rate=0.51, n=152, signature: rs_acceleration_score=+0.72, theme_phase_multiplier_primary=+0.56, theme_phase_multiplier_max=+0.56
- cluster 0: win_rate=0.56, n=247, signature: entry_quality_score=+1.28, selection_confirmation_score=+0.63, theme_phase_multiplier_primary=+0.53

**Best pattern clusters (amplify candidates)**:
- cluster 1: win_rate=0.63, n=114, signature: portfolio_risk_entry_block_score=+2.45, portfolio_monster_early_score=+1.82, theme_phase_multiplier_primary=-1.76
- cluster 6: win_rate=0.61, n=96, signature: h6_dynamic_leader_score=+2.08, rs_acceleration_score=+1.02, selection_confirmation_score=+0.72

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.