# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-14T07:54:26Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `732`
- held_tickers: `20`
- missed_winner_count: `30`
- stale_winner_count: `1`
- leadership_rotation_count: `10`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 7.0546 | 1.4147 | 4.4011 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.8151 | 1.0105 | 1.7924 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.7593 | 0.7947 | 2.9646 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 5.4695 | 1.4952 | 1.5861 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.2381 | 1.2178 | 1.2596 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 5.21 | 0.9442 | 1.7685 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| AMD | Information Technology | 4.8876 | 1.0859 | 0.826 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| BE | Industrials | 4.5983 | 0.8629 | 1.0812 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| COHR | Information Technology | 4.5634 | 0.8048 | 1.4215 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| MTSI | Information Technology | 3.9117 | 0.6103 | 1.1385 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TKR | 0.04 | 0.0728 | 0.0671 | 0.4782 | 1.2728 | under_benchmark_3m | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HPE | SNDK | Information Technology | 6.1799 | 0.04 | 1.0591 | 4.0414 | leadership_rotation_shadow_replay |
| ARM | SNDK | Information Technology | 5.4484 | 0.0568 | 0.649 | 3.9725 | leadership_rotation_shadow_replay |
| MRVL | SNDK | Information Technology | 3.7028 | 0.0568 | 0.2259 | 3.4901 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 3.6864 | 0.04 | 0.7891 | 3.0173 | leadership_rotation_shadow_replay |
| MLI | BE | Industrials | 2.8494 | 0.04 | 0.7018 | 0.7787 | leadership_rotation_shadow_replay |
| TKR | BE | Industrials | 2.695 | 0.04 | 0.7959 | 0.603 | leadership_rotation_shadow_replay |
| GEV | BE | Industrials | 1.4968 | 0.14 | 0.5721 | 0.2461 | leadership_rotation_shadow_replay |
| VRT | BE | Industrials | 0.7212 | 0.0568 | 0.3737 | 0.1102 | leadership_rotation_shadow_replay |
| PR | CHRD | Energy | 0.4879 | 0.04 | 0.1899 | 0.1089 | leadership_rotation_shadow_replay |
| FIX | BE | Industrials | 0.4107 | 0.0568 | 0.3422 | -0.0099 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
