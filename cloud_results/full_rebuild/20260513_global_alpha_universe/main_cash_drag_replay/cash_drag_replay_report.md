# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 34.25% / 2.281581457696593 / -6.04%
- production CAGR / Sharpe / MaxDD: 28.31% / 1.682607622313662 / -16.24%
- base-vs-production CAGR / MaxDD delta: 5.94% / 10.21%
- base avg cash: 19.21%
- best model: `cash0.00_cap0.33`
- best CAGR / Sharpe / MaxDD: 34.80% / 1.8225053431308806 / -14.08%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 19.21%
- avg explicit monthly-book cash before alignment: 4.96%
- avg cash gap before alignment: 14.25%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.33 | 34.80% | 1.823 | -14.08% | 0.00% | 0.55% | -8.04% |
| cash0.00_cap0.25 | 34.79% | 1.822 | -14.09% | -0.00% | 0.53% | -8.06% |
| cash0.00_cap0.22 | 34.78% | 1.821 | -14.10% | 0.00% | 0.53% | -8.06% |
| cash0.00_cap0.18 | 34.76% | 1.820 | -14.12% | -0.00% | 0.51% | -8.08% |
| cash0.03_cap0.33 | 34.08% | 1.834 | -13.53% | 2.51% | -0.17% | -7.49% |
| cash0.03_cap0.25 | 34.07% | 1.833 | -13.54% | 2.51% | -0.18% | -7.50% |
| cash0.03_cap0.22 | 34.06% | 1.833 | -13.54% | 2.51% | -0.19% | -7.51% |
| cash0.03_cap0.18 | 34.05% | 1.832 | -13.56% | 2.51% | -0.20% | -7.52% |
| cash0.05_cap0.33 | 33.66% | 1.843 | -13.15% | 4.07% | -0.59% | -7.12% |
| cash0.05_cap0.25 | 33.65% | 1.843 | -13.16% | 4.07% | -0.60% | -7.12% |
| cash0.05_cap0.22 | 33.65% | 1.842 | -13.17% | 4.07% | -0.60% | -7.13% |
| cash0.05_cap0.18 | 33.64% | 1.841 | -13.18% | 4.07% | -0.61% | -7.14% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
