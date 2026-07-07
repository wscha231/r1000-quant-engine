# Run287 W4 Form4 + 13F Source Screen

- Status: `completed`
- Decision label: `w4_combined_positive_requires_broker_ab_review`
- Candidate allowed: `False`
- Forward returns audit only: `True`
- Same-day disclosure policy: `excluded_no_intraday_rebalance_contract`

## Signal Screen

| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| w4_form4_score | False | -0.34% | 0.62% | -1.12% | 490 | 53.27% |
| w4_13f_score | True | 0.57% | 0.14% | 1.69% | 2087 | 53.67% |
| w4_combined_score | True | 0.39% | 0.27% | 0.72% | 2205 | 54.15% |
| w4_consensus_score | True | 1.52% | 1.33% | 1.20% | 58 | 50.00% |

## Coverage

- Candidate rows: `47435`
- Form4 signal rows: `4566`
- 13F signal rows: `33643`
- Combined signal rows: `34835`

## Interpretation

- Form4 contributes timelier insider transaction evidence.
- 13F contributes slower but broader institutional position-change evidence.
- The combined score is a fixed source-screen blend, not a tuned policy threshold.
- Any positive result can only justify a default-off broker A/B design review after OOS review.
- A mixed or negative result blocks W4 hook design from this Form4/13F source family.
