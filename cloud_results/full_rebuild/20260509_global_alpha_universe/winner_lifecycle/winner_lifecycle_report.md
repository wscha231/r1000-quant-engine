# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-09T11:10:59Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `734`
- held_tickers: `20`
- missed_winner_count: `30`
- stale_winner_count: `0`
- leadership_rotation_count: `14`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MU | Information Technology | 5.8964 | 0.8929 | 2.1471 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.5288 | 0.8262 | 1.8504 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.245 | 1.2221 | 1.1785 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 5.1143 | 1.0202 | 1.7992 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| AMD | Information Technology | 5.0766 | 1.1838 | 0.7758 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.07 | 0.6373 | 2.8831 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| BE | Industrials | 4.7896 | 0.825 | 0.8459 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 4.5239 | 1.2491 | 0.9593 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| RKLB | Industrials | 4.1421 | 0.4584 | 0.8694 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,engine_likes_nonheld_name,ranking_mismatch | concentrated_or_alpha_sprint_replay |
| MTSI | Information Technology | 4.0929 | 0.5258 | 1.4043 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |

## Stale Winners

_none_

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LRCX | LITE | Information Technology | 2.7395 | 0.0556 | 0.3629 | 2.0965 | leadership_rotation_shadow_replay |
| AKAM | LITE | Information Technology | 2.4773 | 0.04 | 0.0838 | 1.8592 | leadership_rotation_shadow_replay |
| MLI | MTZ | Industrials | 2.396 | 0.04 | 0.3999 | 0.7692 | leadership_rotation_shadow_replay |
| TKR | MTZ | Industrials | 2.2071 | 0.04 | 0.4825 | 0.5659 | leadership_rotation_shadow_replay |
| MRVL | LITE | Information Technology | 2.1371 | 0.0644 | -0.4829 | 2.0496 | leadership_rotation_shadow_replay |
| ON | LITE | Information Technology | 2.109 | 0.038 | 0.0545 | 1.8224 | leadership_rotation_shadow_replay |
| GLW | LITE | Information Technology | 1.734 | 0.0644 | 0.1042 | 1.7255 | leadership_rotation_shadow_replay |
| NXPI | UMC | Semiconductors | 1.5567 | 0.04 | 0.212 | 0.5729 | leadership_rotation_shadow_replay |
| PWR | BE | Industrials | 1.2113 | 0.0419 | 0.3585 | 0.2022 | leadership_rotation_shadow_replay |
| GEV | BE | Industrials | 0.948 | 0.1519 | 0.4896 | -0.015 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
