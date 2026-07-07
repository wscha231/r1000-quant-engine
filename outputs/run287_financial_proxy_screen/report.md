# Run287 Financial Proxy Screen

- Status: `completed`
- Decision label: `diagnostic_positive_requires_broker_ab_review`
- Candidate allowed: `False`
- Forward returns audit only: `True`
- OOS start: `2024-07-01`

| Signal | Candidate positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| actual_results_score | True | 0.34% | 0.36% | 0.24% | 2889 | 53.69% |
| eps_revision_score | False | 0.00% | 0.00% | 0.00% | 0 | 0.00% |
| sales_growth_yoy | False | 0.04% | -0.25% | 0.55% | 2143 | 53.48% |
| eps_growth_yoy | False | 0.33% | -0.08% | 1.30% | 1228 | 57.65% |
| op_income_growth_yoy | False | -0.93% | -1.31% | 0.40% | 158 | 51.27% |
| ocf_growth_yoy | False | -0.09% | -1.43% | 2.58% | 180 | 56.11% |
| gross_margins | False | 0.00% | 0.00% | 0.00% | 0 | 0.00% |
| operating_margins | False | 0.00% | 0.00% | 0.00% | 0 | 0.00% |
| rev_growth_accel_4q | False | 0.11% | -0.28% | 1.44% | 224 | 56.70% |
| capital_efficiency_score | False | 0.22% | 0.53% | -0.33% | 2889 | 53.41% |
| profitability_inflection_score | True | 1.04% | 0.57% | 2.03% | 2889 | 56.70% |
| selection_confirmation_score | False | -0.15% | -0.33% | 0.22% | 8212 | 53.42% |

## Interpretation

- This is not broker-ledger evidence.
- Financial actual/proxy fields remain diagnostic until a true PIT revision/guidance feed is available.
- A positive screen can only justify a default-off broker A/B design review, not a fullrun.
- A negative or mixed screen blocks hook design from this source family.
