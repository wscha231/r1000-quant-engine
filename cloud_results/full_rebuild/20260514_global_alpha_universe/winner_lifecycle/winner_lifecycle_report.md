# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-14T21:09:59Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `745`
- held_tickers: `20`
- missed_winner_count: `30`
- stale_winner_count: `0`
- leadership_rotation_count: `12`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 6.8444 | 1.2311 | 4.178 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| INTC | Information Technology | 6.6451 | 1.5133 | 2.084 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.6814 | 0.8912 | 1.8389 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| RKLB | Industrials | 5.6592 | 0.9874 | 1.5603 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.6419 | 0.7345 | 3.0084 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| PL | Information Technology | 5.6274 | 1.0127 | 2.4379 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 5.5294 | 1.6886 | 1.6955 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| BE | Industrials | 5.4787 | 1.1828 | 1.3882 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.3819 | 1.3022 | 1.3427 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| WDC | Information Technology | 5.252 | 0.7451 | 1.9188 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |

## Stale Winners

_none_

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HPE | SNDK | Information Technology | 5.2941 | 0.04 | 0.7108 | 3.6946 | leadership_rotation_shadow_replay |
| LRCX | SNDK | Information Technology | 4.523 | 0.0658 | 0.9304 | 3.2849 | leadership_rotation_shadow_replay |
| MLI | BE | Industrials | 3.6546 | 0.04 | 1.0 | 1.0871 | leadership_rotation_shadow_replay |
| TKR | BE | Industrials | 3.4371 | 0.04 | 1.0893 | 0.8806 | leadership_rotation_shadow_replay |
| AMD | SNDK | Information Technology | 3.2693 | 0.04 | 0.048 | 3.2852 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 3.084 | 0.04 | 0.5474 | 2.7225 | leadership_rotation_shadow_replay |
| MRVL | SNDK | Information Technology | 2.9432 | 0.067 | -0.13 | 3.1088 | leadership_rotation_shadow_replay |
| PWR | BE | Industrials | 2.2746 | 0.064 | 0.6792 | 0.6599 | leadership_rotation_shadow_replay |
| VRT | BE | Industrials | 1.2158 | 0.067 | 0.6011 | 0.2982 | leadership_rotation_shadow_replay |
| FIX | BE | Industrials | 1.1056 | 0.0645 | 0.6103 | 0.2452 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
