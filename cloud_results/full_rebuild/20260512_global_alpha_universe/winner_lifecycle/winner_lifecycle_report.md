# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-12T08:12:56Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `734`
- held_tickers: `20`
- missed_winner_count: `30`
- stale_winner_count: `1`
- leadership_rotation_count: `13`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| STX | Information Technology | 5.497 | 0.8262 | 1.8504 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.2279 | 1.2221 | 1.1785 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 5.0879 | 1.0202 | 1.7992 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| AMD | Information Technology | 5.0586 | 1.1838 | 0.7758 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.0461 | 0.6373 | 2.8831 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| BE | Industrials | 4.7724 | 0.825 | 0.8459 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 4.5058 | 1.2491 | 0.9593 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| STM | Semiconductors | 4.413 | 0.9879 | 1.4809 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,ranking_mismatch | fundamental_acceleration_override_replay |
| MRVL | Information Technology | 4.337 | 1.1203 | 0.8336 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| RKLB | Industrials | 4.1337 | 0.4584 | 0.8694 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,engine_likes_nonheld_name,ranking_mismatch | concentrated_or_alpha_sprint_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AMZN | 0.1126 | 0.1748 | 0.2965 | 0.0898 | 0.3696 | under_benchmark_6m,high_weight_low_relative_strength | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TSM | LITE | Information Technology | 3.9439 | 0.0775 | 0.4539 | 2.4734 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 3.2081 | 0.0429 | 0.6671 | 1.0667 | leadership_rotation_shadow_replay |
| TXN | LITE | Information Technology | 3.1702 | 0.0509 | 0.3311 | 2.1032 | leadership_rotation_shadow_replay |
| LRCX | LITE | Information Technology | 2.7395 | 0.0463 | 0.3629 | 2.0965 | leadership_rotation_shadow_replay |
| AKAM | LITE | Information Technology | 2.506 | 0.0383 | 0.0838 | 1.8592 | leadership_rotation_shadow_replay |
| MLI | MTZ | Industrials | 2.4844 | 0.04 | 0.3999 | 0.7692 | leadership_rotation_shadow_replay |
| ON | LITE | Information Technology | 2.1109 | 0.0362 | 0.0545 | 1.8224 | leadership_rotation_shadow_replay |
| GLW | LITE | Information Technology | 1.734 | 0.0507 | 0.1042 | 1.7255 | leadership_rotation_shadow_replay |
| AMZN | MUSA | Consumer Discretionary | 1.2487 | 0.1126 | 0.2352 | 0.4944 | leadership_rotation_shadow_replay |
| PWR | BE | Industrials | 1.2113 | 0.0452 | 0.3585 | 0.2022 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
