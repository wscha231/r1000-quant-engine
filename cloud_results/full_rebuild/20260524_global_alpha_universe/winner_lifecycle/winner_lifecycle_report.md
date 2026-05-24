# Winner Lifecycle Daily Diagnostics

Research-only. No production rules, weights, features, or execution behavior are changed.

- generated_at_utc: `2026-05-24T18:51:41Z`
- latest_run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored_rows: `725`
- held_tickers: `15`
- missed_winner_count: `30`
- stale_winner_count: `0`
- leadership_rotation_count: `13`

## Missed Winners

| ticker | sector | missed_winner_score | mom_3m | mom_6m | entry_quality_score | diagnosis | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SNDK | Information Technology | 6.8926 | 1.2186 | 5.0119 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| MU | Information Technology | 5.8731 | 0.7847 | 2.3269 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| STX | Information Technology | 5.803 | 0.9984 | 2.15 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| HIMX | Information Technology | 5.7211 | 1.7648 | 1.9182 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| ALAB | Information Technology | 5.2556 | 1.393 | 1.161 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| WDC | Information Technology | 5.1631 | 0.7278 | 2.1493 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| BE | Industrials | 5.0878 | 0.8873 | 1.7769 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name,ranking_mismatch | fundamental_acceleration_override_replay |
| CIEN | Information Technology | 4.9136 | 0.6928 | 2.0922 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| FLEX | Information Technology | 4.8602 | 1.0927 | 1.2722 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |
| LITE | Information Technology | 4.783 | 0.4034 | 2.5211 | 0.0 | strong_3m_momentum,strong_6m_momentum,strong_12m_momentum,high_relative_strength,entry_quality_chase_penalty,engine_likes_nonheld_name | fundamental_acceleration_override_replay |

## Stale Winners

_none_

## Leadership Rotation Candidates

| held_ticker | challenger_ticker | sector | rotation_score | held_weight | mom_3m_delta | mom_6m_delta | policy_probe |
| --- | --- | --- | --- | --- | --- | --- | --- |
| HPE | SNDK | Information Technology | 4.7536 | 0.0384 | 0.3275 | 4.1648 | leadership_rotation_shadow_replay |
| MLI | BE | Industrials | 3.8687 | 0.0386 | 0.7557 | 1.5217 | leadership_rotation_shadow_replay |
| ON | SNDK | Information Technology | 3.7119 | 0.0384 | 0.546 | 3.4924 | leadership_rotation_shadow_replay |
| AMD | SNDK | Information Technology | 3.6822 | 0.0744 | -0.1594 | 3.9206 | leadership_rotation_shadow_replay |
| ARM | SNDK | Information Technology | 3.4585 | 0.0744 | -0.2576 | 3.7744 | leadership_rotation_shadow_replay |
| NXPI | STM | Semiconductors | 3.4075 | 0.046 | 0.5965 | 1.329 | leadership_rotation_shadow_replay |
| MRVL | SNDK | Information Technology | 3.1834 | 0.0744 | -0.3065 | 3.5947 | leadership_rotation_shadow_replay |
| TKR | BE | Industrials | 3.1759 | 0.0386 | 0.7677 | 1.1563 | leadership_rotation_shadow_replay |
| GEV | BE | Industrials | 2.6251 | 0.1153 | 0.6376 | 1.0299 | leadership_rotation_shadow_replay |
| VRT | BE | Industrials | 1.9871 | 0.1244 | 0.5527 | 0.8568 | leadership_rotation_shadow_replay |

## Suggested Next Experiments

1. Replay `fundamental_acceleration_override` for missed winners with high momentum and low entry quality.
2. Replay `trim_or_replace` for stale high-weight holdings with negative 3-6 month relative strength.
3. Replay `leadership_rotation` by replacing stale same-sector holdings with stronger challengers.
4. Keep all three proposal-only until historical replay, shadow, and canary gates pass.
