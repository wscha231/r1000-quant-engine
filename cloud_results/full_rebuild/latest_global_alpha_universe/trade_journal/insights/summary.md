# Trade Insights Summary

- trades analyzed: **937**
- generated: 2026-05-14 16:10 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `theme_phase_multiplier_primary` in **bull**: IC = -0.043
- `theme_phase_multiplier_primary` in **bear**: IC = -0.039
- `h6_dynamic_leader_score` in **bear**: IC = -0.034

**Best signal x regime cells (amplify candidates)**:
- `h6_dynamic_leader_score` in **bull**: IC = +0.078
- `selection_confirmation_score` in **bull**: IC = +0.072
- `rs_acceleration_score` in **neutral**: IC = +0.059

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 6: win_rate=0.46, n=80, signature: selection_confirmation_score=-1.11, rs_acceleration_score=-0.69, h6_dynamic_leader_score=-0.59
- cluster 2: win_rate=0.51, n=132, signature: rs_acceleration_score=+1.09, theme_phase_multiplier_max=+0.46, theme_phase_multiplier_primary=+0.46

**Best pattern clusters (amplify candidates)**:
- cluster 1: win_rate=0.65, n=110, signature: portfolio_risk_entry_block_score=+2.56, portfolio_monster_early_score=+2.23, theme_phase_multiplier_max=-2.11
- cluster 0: win_rate=0.59, n=186, signature: h6_dynamic_leader_score=+1.88, selection_confirmation_score=+0.66, theme_phase_multiplier_max=+0.48

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.