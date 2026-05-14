# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 36.63% / 2.3486792271163557 / -6.43%
- production CAGR / Sharpe / MaxDD: 30.87% / 1.7202960298994148 / -18.51%
- base-vs-production CAGR / MaxDD delta: 5.76% / 12.08%
- base avg cash: 21.41%
- best model: `cash0.00_cap0.33`
- best CAGR / Sharpe / MaxDD: 37.33% / 1.876526242015704 / -15.40%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 21.41%
- avg explicit monthly-book cash before alignment: 4.98%
- avg cash gap before alignment: 16.43%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.33 | 37.33% | 1.877 | -15.40% | 0.00% | 0.70% | -8.97% |
| cash0.00_cap0.25 | 37.32% | 1.877 | -15.37% | 0.00% | 0.69% | -8.95% |
| cash0.00_cap0.22 | 37.32% | 1.877 | -15.36% | 0.00% | 0.69% | -8.93% |
| cash0.00_cap0.18 | 37.31% | 1.877 | -15.33% | 0.00% | 0.68% | -8.90% |
| cash0.03_cap0.33 | 36.51% | 1.884 | -14.99% | 2.77% | -0.12% | -8.56% |
| cash0.03_cap0.25 | 36.50% | 1.884 | -14.97% | 2.77% | -0.13% | -8.54% |
| cash0.03_cap0.22 | 36.50% | 1.884 | -14.96% | 2.77% | -0.13% | -8.53% |
| cash0.03_cap0.18 | 36.50% | 1.884 | -14.93% | 2.77% | -0.13% | -8.50% |
| cash0.05_cap0.18 | 36.06% | 1.892 | -14.61% | 4.48% | -0.57% | -8.19% |
| cash0.05_cap0.22 | 36.06% | 1.892 | -14.64% | 4.48% | -0.57% | -8.21% |
| cash0.05_cap0.25 | 36.06% | 1.891 | -14.65% | 4.48% | -0.57% | -8.22% |
| cash0.05_cap0.33 | 36.06% | 1.891 | -14.67% | 4.48% | -0.57% | -8.24% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
