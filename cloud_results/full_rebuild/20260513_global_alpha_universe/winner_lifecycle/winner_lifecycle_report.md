# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-13T14:42:20Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `732`
- held_tickers: `15`
- missed_winner_count: `30`
- stale_winner_count: `2`
- leadership_rotation_count: `11`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 7.1051 | 1.6808 | 5.0632 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.8302 | 1.0448 | 1.908 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.4839 | 0.7685 | 3.133 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 5.1452 | 0.9322 | 1.8965 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.1318 | 1.1728 | 1.23 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 5.0439 | 1.368 | 1.3477 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| BE | Industrials | 5.0394 | 0.8876 | 1.076 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| AMD | Information Technology | 4.9693 | 1.099 | 0.9195 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| COHR | Information Technology | 4.1143 | 0.6377 | 1.4206 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| FIX | Industrials | 3.9617 | 0.5889 | 1.1131 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLTR | 0.0831 | 0.9749 | -0.0252 | -0.2357 | -0.9092 | weak_3m_absolute_momentum,negative_6m_absolute_momentum,under_benchmark_3m,under_benchmark_6m,high_weight_low_relative_strength,broken_momentum_penalty | trim_or_replace_replay |
| AMZN | 0.1195 | 0.1847 | 0.2844 | 0.0876 | 0.354 | under_benchmark_6m,high_weight_low_relative_strength | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLTR | SNDK | Information Technology | 8.7788 | 0.0831 | 1.7059 | 5.2989 | leadership_rotation_shadow_replay |
| AKAM | SNDK | Information Technology | 5.9094 | 0.04 | 1.0965 | 4.2772 | leadership_rotation_shadow_replay |
| LRCX | SNDK | Information Technology | 5.7483 | 0.0657 | 1.4029 | 4.2429 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 4.9406 | 0.04 | 1.1357 | 3.8866 | leadership_rotation_shadow_replay |
| GLW | SNDK | Information Technology | 4.479 | 0.0711 | 1.1304 | 3.7318 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 2.8734 | 0.04 | 0.4874 | 1.0251 | leadership_rotation_shadow_replay |
| MLI | BE | Industrials | 2.8529 | 0.04 | 0.7221 | 0.7748 | leadership_rotation_shadow_replay |
| AMZN | MUSA | Consumer Discretionary | 1.4053 | 0.1195 | 0.306 | 0.5042 | leadership_rotation_shadow_replay |
| GEV | BE | Industrials | 1.3174 | 0.1317 | 0.5312 | 0.2096 | leadership_rotation_shadow_replay |
| FTI | XOM | Energy | 0.3565 | 0.0514 | -0.2164 | -0.4065 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
