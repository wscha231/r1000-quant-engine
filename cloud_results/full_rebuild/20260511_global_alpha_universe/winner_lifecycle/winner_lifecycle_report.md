# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-11T12:04:15Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `731`
- held_tickers: `20`
- missed_winner_count: `30`
- stale_winner_count: `1`
- leadership_rotation_count: `15`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| STX | Information Technology | 5.4905 | 0.8262 | 1.8504 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.2352 | 1.2221 | 1.1785 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 5.105 | 1.0202 | 1.7992 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| AMD | Information Technology | 5.0587 | 1.1838 | 0.7758 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.0455 | 0.6373 | 2.8831 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| BE | Industrials | 4.7743 | 0.825 | 0.8459 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 4.5012 | 1.2491 | 0.9593 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| STM | Semiconductors | 4.4074 | 0.9879 | 1.4809 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,ranking_mismatch | fundamental_acceleration_override_replay |
| MRVL | Information Technology | 4.3337 | 1.1203 | 0.8336 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| RKLB | Industrials | 4.1329 | 0.4584 | 0.8694 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,engine_likes_nonheld_name,ranking_mismatch | concentrated_or_alpha_sprint_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NXPI | 0.0675 | 0.1013 | 0.3208 | 0.4142 | 0.4775 | high_weight_low_relative_strength | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HPE | LITE | Information Technology | 4.2298 | 0.0359 | 0.301 | 2.5444 | leadership_rotation_shadow_replay |
| ENTG | LITE | Information Technology | 3.7979 | 0.0359 | 0.418 | 2.1957 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 3.2035 | 0.0675 | 0.6671 | 1.0667 | leadership_rotation_shadow_replay |
| TXN | LITE | Information Technology | 3.1708 | 0.0528 | 0.3311 | 2.1032 | leadership_rotation_shadow_replay |
| LRCX | LITE | Information Technology | 2.7432 | 0.0523 | 0.3629 | 2.0965 | leadership_rotation_shadow_replay |
| AKAM | LITE | Information Technology | 2.5243 | 0.0359 | 0.0838 | 1.8592 | leadership_rotation_shadow_replay |
| MLI | MTZ | Industrials | 2.4603 | 0.04 | 0.3999 | 0.7692 | leadership_rotation_shadow_replay |
| TKR | MTZ | Industrials | 2.2898 | 0.04 | 0.4825 | 0.5659 | leadership_rotation_shadow_replay |
| ON | LITE | Information Technology | 2.1206 | 0.0359 | 0.0545 | 1.8224 | leadership_rotation_shadow_replay |
| GLW | LITE | Information Technology | 1.7342 | 0.0512 | 0.1042 | 1.7255 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
