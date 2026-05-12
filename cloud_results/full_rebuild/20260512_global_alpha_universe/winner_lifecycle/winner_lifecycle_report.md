# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-12T23:26:26Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `730`
- held_tickers: `19`
- missed_winner_count: `30`
- stale_winner_count: `1`
- leadership_rotation_count: `16`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 7.0586 | 1.6243 | 4.9355 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.7952 | 1.0238 | 1.8781 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.4 | 0.7232 | 3.0271 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.0777 | 1.1492 | 1.2059 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 5.0548 | 0.9016 | 1.8506 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| RKLB | Industrials | 4.9729 | 0.6563 | 1.3103 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 4.9642 | 1.3326 | 1.3125 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| BE | Industrials | 4.9109 | 0.8504 | 1.0351 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| AMD | Information Technology | 4.8675 | 1.0594 | 0.8833 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| COHR | Information Technology | 4.0043 | 0.6057 | 1.3732 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLTR | 0.061 | 0.96 | -0.0388 | -0.2463 | -0.8456 | weak_3m_absolute_momentum,negative_6m_absolute_momentum,under_benchmark_3m,under_benchmark_6m,high_weight_low_relative_strength,broken_momentum_penalty | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLTR | SNDK | Information Technology | 8.6701 | 0.061 | 1.6631 | 5.1818 | leadership_rotation_shadow_replay |
| AKAM | SNDK | Information Technology | 5.6701 | 0.04 | 1.0612 | 4.1734 | leadership_rotation_shadow_replay |
| LRCX | SNDK | Information Technology | 5.6101 | 0.061 | 1.3506 | 4.1212 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 4.8323 | 0.04 | 1.0907 | 3.775 | leadership_rotation_shadow_replay |
| GLW | SNDK | Information Technology | 4.3723 | 0.0595 | 1.0901 | 3.6286 | leadership_rotation_shadow_replay |
| MLI | RKLB | Industrials | 2.8818 | 0.04 | 0.4858 | 1.0036 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 2.838 | 0.04 | 0.4785 | 1.0122 | leadership_rotation_shadow_replay |
| TKR | RKLB | Industrials | 2.7549 | 0.04 | 0.5844 | 0.8191 | leadership_rotation_shadow_replay |
| PWR | RKLB | Industrials | 1.4922 | 0.0566 | 0.1562 | 0.5885 | leadership_rotation_shadow_replay |
| OKE | CHRD | Energy | 1.2878 | 0.0562 | 0.3601 | 0.3376 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
