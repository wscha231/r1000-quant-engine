# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-14T16:27:37Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `744`
- held_tickers: `19`
- missed_winner_count: `30`
- stale_winner_count: `2`
- leadership_rotation_count: `12`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 7.041 | 1.4147 | 4.4011 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| INTC | Information Technology | 6.7258 | 1.491 | 2.1285 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.8006 | 1.0105 | 1.7924 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.703 | 0.7947 | 2.9646 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 5.4538 | 1.4958 | 1.5867 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| RKLB | Industrials | 5.2448 | 0.7833 | 1.3921 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.2233 | 1.2178 | 1.2596 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| PL | Information Technology | 5.1572 | 0.8818 | 2.0426 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| AMD | Information Technology | 4.8496 | 1.0859 | 0.826 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| BE | Industrials | 4.5869 | 0.8629 | 1.0812 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NXPI | 0.0548 | 0.0821 | 0.201 | 0.4688 | 0.4474 | high_weight_low_relative_strength | trim_or_replace_replay |
| TKR | 0.04 | 0.0728 | 0.0671 | 0.4782 | 1.2516 | under_benchmark_3m | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HPE | SNDK | Information Technology | 6.1636 | 0.04 | 1.0591 | 4.0414 | leadership_rotation_shadow_replay |
| LRCX | SNDK | Information Technology | 5.1702 | 0.0621 | 1.1567 | 3.6203 | leadership_rotation_shadow_replay |
| MRVL | SNDK | Information Technology | 3.7012 | 0.0621 | 0.2259 | 3.4901 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 3.6966 | 0.04 | 0.7891 | 3.0173 | leadership_rotation_shadow_replay |
| MLI | RKLB | Industrials | 3.2067 | 0.04 | 0.6222 | 1.0896 | leadership_rotation_shadow_replay |
| TKR | RKLB | Industrials | 3.1216 | 0.04 | 0.7162 | 0.9139 | leadership_rotation_shadow_replay |
| WDC | SNDK | Information Technology | 2.7798 | 0.0585 | 0.6089 | 2.5615 | leadership_rotation_shadow_replay |
| GEV | RKLB | Industrials | 1.8664 | 0.12 | 0.4924 | 0.557 | leadership_rotation_shadow_replay |
| VRT | RKLB | Industrials | 1.0933 | 0.0621 | 0.2941 | 0.4212 | leadership_rotation_shadow_replay |
| FIX | RKLB | Industrials | 0.7726 | 0.0563 | 0.2626 | 0.3011 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
