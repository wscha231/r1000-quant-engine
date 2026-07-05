# Run287 Survivorship Inflation Bound

Status: `completed`

Research-only R2 audit. This is a one-sided proxy lower bound. It does
not recover delisted-name exclusion and does not make PIT membership clean.

## Summary

| Portfolio | Metric | Current CAGR | Measurable inflation pp | Deflated lower-bound CAGR | Current target gap pp | Bound target gap pp | Late-inclusion rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | broker_ledger_next_close_cash_carry | 33.81% | 0.00 | 33.81% | 1.19 | 1.19 | 0 |
| concentrated | broker_ledger_next_close_cash_carry | 48.41% | 0.00 | 48.41% | 1.59 | 1.59 | 0 |

## Interpretation

- `survivorship_inflation_estimate_cagr_pp` is a measured lower bound
  from first-price-date late-inclusion only.
- `unmeasured_component=delisted_exclusion`: free-tier artifacts cannot
  reconstruct deleted historical R1000 members or full ticker lifecycles.
- Label remains `proxy`; `pit_universe_label_clean=false` and production
  promotion remains blocked.
