# Run287 Multi-Source Fusion Screen

Date: 2026-07-08 KST

Status: research-only source evidence.

No fullrun was dispatched. No hook was added. No threshold tuning was performed. Production promotion, live trading, and public return claims remain blocked.

## Objective

Test whether the best available source families can be combined without leakage:

- W4 SEC: Form4 + 13F combined source score.
- Financial statements: existing PIT/proxy financial actuals and growth/margin fields.
- Technical indicators: momentum, relative strength, breakout, trend, and entry-quality fields.
- Macro/regime: style/regime fit and rate/inflation/overheat pressure.
- Risk control: existing risk/overheat/ATR/event-risk penalties inverted into a defensive score.

This is a candidate-row source screen. `period_forward_return` is audit-only and is not used to rank, weight, or fit the signal.

## Results

| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `w4_sec_score` | true | 0.39% | 0.27% | 0.72% | 2,205 | 54.15% |
| `financial_statement_proxy_score` | true | 0.45% | 0.44% | 0.41% | 2,889 | 53.82% |
| `technical_momentum_score` | false | 0.24% | -0.09% | 0.97% | 2,889 | 53.48% |
| `macro_regime_score` | true | 0.18% | 0.08% | 0.35% | 2,888 | 53.36% |
| `risk_control_score` | false | -0.46% | -0.05% | -1.11% | 2,886 | 53.40% |
| `all_source_equal_score` | true | 0.14% | 0.12% | 0.18% | 2,889 | 52.75% |
| `growth_confirmation_score` | true | 0.47% | 0.30% | 0.85% | 2,889 | 54.41% |
| `drawdown_aware_fusion_score` | true | 0.13% | 0.16% | 0.08% | 2,889 | 52.34% |
| `three_plus_sleeve_consensus_score` | true | 0.14% | 0.13% | 0.24% | 2,701 | 53.09% |

## Interpretation

The best combined source is `growth_confirmation_score`, not the drawdown-aware variant.

`growth_confirmation_score` combines:

- 25% W4 SEC
- 25% financial statement proxy
- 30% technical/momentum
- 20% macro/regime

This stack has the strongest OOS high-low spread among the broad fusion scores: +0.85%.

`risk_control_score` is negative in full, IS, and OOS high-low. The current risk fields do not behave like a clean source-level alpha or drawdown shield in this screen. Adding them reduces the fusion edge: `drawdown_aware_fusion_score` falls to only +0.08% OOS high-low.

Technical/momentum is mixed. It is positive OOS but negative IS, so it should not be used standalone. Its role is only as a partial confirmation component inside the growth stack.

## Decision

Decision label: `multisource_fusion_positive_requires_broker_ab_review`

Allowed next action:

- Run a cheap default-off fixed-book broker A/B review for `growth_confirmation_score`.
- Keep `w4_sec_score` and `financial_statement_proxy_score` as comparison arms.
- Report Main and Concentrated separately.

Blocked actions:

- Do not use `risk_control_score` as a MDD fix yet.
- Do not use `technical_momentum_score` standalone.
- Do not add a hook from this source screen.
- Do not dispatch a fullrun.
- Do not promote to production while `pit_universe_label_clean=false`.

## Next Broker A/B Arms

Recommended cheap-review arms:

1. `baseline_generated_book_cash_carry`
2. `w4_sec_score_top_quintile_tilt`
3. `financial_statement_proxy_score_top_quintile_tilt`
4. `growth_confirmation_score_top_quintile_tilt`
5. `growth_confirmation_score_consensus_only_tilt`

The expected useful test is whether `growth_confirmation_score` improves CAGR without worsening MDD on the official fixed books. If it only improves source-screen forward labels but fails broker-ledger A/B, it must be rejected like prior source candidates.
