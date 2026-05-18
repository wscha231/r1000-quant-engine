# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-16T18:50:39Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `746`
- held_tickers: `24`
- missed_winner_count: `30`
- stale_winner_count: `3`
- leadership_rotation_count: `15`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 6.8192 | 1.2466 | 3.9721 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| INTC | Information Technology | 6.2446 | 1.3246 | 1.8707 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.4445 | 0.8706 | 1.8205 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 5.3011 | 1.4689 | 1.5079 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| LITE | Information Technology | 5.2811 | 0.725 | 2.8245 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| RKLB | Industrials | 5.1922 | 0.8501 | 1.4969 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| WDC | Information Technology | 5.1473 | 0.7127 | 1.9055 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| PL | Information Technology | 5.0609 | 0.8564 | 2.3457 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 5.0276 | 1.146 | 1.191 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| BE | Industrials | 4.8755 | 0.9747 | 1.1776 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |

## Stale Winners

| ticker | weight | stale_winner_score | mom_3m | mom_6m | relative_strength_composite | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLTR | 0.0518 | 0.867 | 0.0196 | -0.2725 | -0.6625 | weak_3m_absolute_momentum,negative_6m_absolute_momentum,under_benchmark_3m,under_benchmark_6m,high_weight_low_relative_strength,broken_momentum_penalty | trim_or_replace_replay |
| APP | 0.1048 | 0.509 | 0.2828 | -0.1434 | -0.0217 | negative_6m_absolute_momentum,under_benchmark_6m,high_weight_low_relative_strength,broken_momentum_penalty | trim_or_replace_replay |
| AMZN | 0.078 | 0.1171 | 0.3287 | 0.0817 | 0.3824 | high_weight_low_relative_strength | trim_or_replace_replay |

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PLTR | SNDK | Information Technology | 7.4783 | 0.0518 | 1.2269 | 4.2446 | leadership_rotation_shadow_replay |
| APP | SNDK | Information Technology | 6.7708 | 0.1048 | 0.9638 | 4.1155 | leadership_rotation_shadow_replay |
| MLI | RKLB | Industrials | 3.4699 | 0.04 | 0.7043 | 1.2398 | leadership_rotation_shadow_replay |
| VRT | SNDK | Information Technology | 3.4404 | 0.0518 | 0.6646 | 2.8312 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 3.3558 | 0.039 | 0.6802 | 2.6764 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 3.2967 | 0.0337 | 0.6336 | 1.1326 | leadership_rotation_shadow_replay |
| CAT | RKLB | Industrials | 2.7199 | 0.1036 | 0.7005 | 0.9401 | leadership_rotation_shadow_replay |
| NVT | RKLB | Industrials | 2.2803 | 0.0518 | 0.3555 | 0.9755 | leadership_rotation_shadow_replay |
| PWR | RKLB | Industrials | 2.0034 | 0.0323 | 0.3806 | 0.7828 | leadership_rotation_shadow_replay |
| GEV | RKLB | Industrials | 1.9954 | 0.0886 | 0.5412 | 0.671 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
