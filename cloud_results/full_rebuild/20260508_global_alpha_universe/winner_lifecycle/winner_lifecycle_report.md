# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-08T12:20:47Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `714`
- held_tickers: `20`
- missed_winner_count: `30`
- stale_winner_count: `0`
- leadership_rotation_count: `16`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LITE | Information Technology | 5.9377 | 1.0284 | 3.7313 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.7144 | 0.8818 | 1.9744 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| MU | Information Technology | 5.5089 | 0.7577 | 1.8425 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.2402 | 1.2902 | 1.1085 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| BE | Industrials | 5.0961 | 0.9374 | 1.0051 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| MRVL | Information Technology | 4.8645 | 1.336 | 0.9073 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| AMD | Information Technology | 4.7274 | 1.105 | 0.6229 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| AMKR | Information Technology | 4.6242 | 0.7636 | 1.0488 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| FIX | Industrials | 4.488 | 0.7972 | 1.0598 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STM | Semiconductors | 4.4608 | 0.9814 | 1.3899 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,ranking_mismatch | fundamental_acceleration_override_replay |

## Stale Winners

_none_

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AMAT | LITE | Information Technology | 3.9466 | 0.0633 | 0.5863 | 2.9224 | leadership_rotation_shadow_replay |
| LRCX | LITE | Information Technology | 3.6445 | 0.0633 | 0.6101 | 2.8831 | leadership_rotation_shadow_replay |
| TER | LITE | Information Technology | 3.2805 | 0.04 | 0.6063 | 2.6396 | leadership_rotation_shadow_replay |
| ON | LITE | Information Technology | 3.2296 | 0.04 | 0.324 | 2.6352 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 2.9276 | 0.0611 | 0.6364 | 0.9331 | leadership_rotation_shadow_replay |
| GLW | LITE | Information Technology | 2.9245 | 0.0626 | 0.37 | 2.6453 | leadership_rotation_shadow_replay |
| MLI | MTZ | Industrials | 2.8451 | 0.04 | 0.6229 | 0.8539 | leadership_rotation_shadow_replay |
| TKR | MTZ | Industrials | 2.4361 | 0.04 | 0.6271 | 0.6017 | leadership_rotation_shadow_replay |
| DTM | PBR | Energy | 1.3709 | 0.04 | 0.2377 | 0.4746 | leadership_rotation_shadow_replay |
| GEV | MTZ | Industrials | 0.9835 | 0.0633 | 0.3399 | 0.2215 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
