# Run287 Multi-Source Fusion Screen

- Status: `completed`
- Decision label: `multisource_fusion_positive_requires_broker_ab_review`
- Candidate allowed: `False`
- Forward returns audit only: `True`

| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| w4_sec_score | True | 0.39% | 0.27% | 0.72% | 2205 | 54.15% |
| financial_statement_proxy_score | True | 0.45% | 0.44% | 0.41% | 2889 | 53.82% |
| technical_momentum_score | False | 0.24% | -0.09% | 0.97% | 2889 | 53.48% |
| macro_regime_score | True | 0.18% | 0.08% | 0.35% | 2888 | 53.36% |
| risk_control_score | False | -0.46% | -0.05% | -1.11% | 2886 | 53.40% |
| all_source_equal_score | True | 0.14% | 0.12% | 0.18% | 2889 | 52.75% |
| growth_confirmation_score | True | 0.47% | 0.30% | 0.85% | 2889 | 54.41% |
| drawdown_aware_fusion_score | True | 0.13% | 0.16% | 0.08% | 2889 | 52.34% |
| three_plus_sleeve_consensus_score | True | 0.14% | 0.13% | 0.24% | 2701 | 53.09% |

## Interpretation

- This is a candidate-row source screen, not broker-ledger evidence.
- The fusion scores use fixed source buckets: W4 SEC, financial proxy, technical/momentum, macro/regime, and risk control.
- A positive screen only permits a default-off broker A/B review on official fixed books.
- No fullrun, production promotion, live trading, or public performance claim is allowed from this artifact.
