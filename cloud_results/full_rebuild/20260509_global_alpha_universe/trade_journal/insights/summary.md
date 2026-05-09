# Trade Insights Summary

- trades analyzed: **995**
- generated: 2026-05-09 11:07 UTC

## 1. Signal IC by regime (rank correlation)
Top actionable findings:

**Worst signal x regime cells (potential gate candidates)**:
- `selection_confirmation_score` in **deep_bear**: IC = -0.548
- `h6_dynamic_leader_score` in **deep_bear**: IC = -0.274
- `h1_oversold_value_score` in **deep_bear**: IC = -0.137

**Best signal x regime cells (amplify candidates)**:
- `theme_phase_multiplier_max` in **deep_bear**: IC = +0.214
- `rs_acceleration_score` in **deep_bear**: IC = +0.200
- `rs_acceleration_score` in **bull**: IC = +0.118

Full matrix in `ic_matrix.csv`.

## 2. Trade pattern clusters
**Worst pattern clusters (block candidates)**:
- cluster 5: win_rate=0.52, n=159, signature: rs_acceleration_score=+0.80, theme_phase_multiplier_max=+0.61, theme_phase_multiplier_primary=+0.61
- cluster 0: win_rate=0.56, n=161, signature: rs_acceleration_score=-1.56, theme_phase_multiplier_max=+0.57, portfolio_monster_early_score=-0.56

**Best pattern clusters (amplify candidates)**:
- cluster 7: win_rate=0.67, n=107, signature: h6_dynamic_leader_score=+2.11, rs_acceleration_score=+0.90, selection_confirmation_score=+0.75
- cluster 1: win_rate=0.62, n=178, signature: portfolio_risk_entry_block_score=+1.97, portfolio_monster_early_score=+1.76, theme_phase_multiplier_max=-1.66

Full table in `cluster_winrate.csv`.

## 3. SHAP / model importance
_(no SHAP - no data)_

---

**Phase 18c next**: feed `ic_matrix.csv` + `cluster_winrate.csv` to `tools/feature_gate_proposal.py` to auto-draft `research/auto_feature_gates.yaml`.