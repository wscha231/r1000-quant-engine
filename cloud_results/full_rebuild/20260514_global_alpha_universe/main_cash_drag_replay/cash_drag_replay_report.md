# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 36.40% / 2.2861273777431577 / -6.40%
- production CAGR / Sharpe / MaxDD: 30.99% / 1.7070972870997103 / -17.41%
- base-vs-production CAGR / MaxDD delta: 5.41% / 11.00%
- base avg cash: 21.05%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 37.55% / 1.8707564425072392 / -14.45%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 21.05%
- avg explicit monthly-book cash before alignment: 4.99%
- avg cash gap before alignment: 16.06%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 37.55% | 1.871 | -14.45% | 0.00% | 1.15% | -8.04% |
| cash0.00_cap0.22 | 37.54% | 1.870 | -14.47% | -0.00% | 1.14% | -8.06% |
| cash0.00_cap0.25 | 37.54% | 1.870 | -14.48% | -0.00% | 1.13% | -8.08% |
| cash0.00_cap0.33 | 37.53% | 1.870 | -14.50% | 0.00% | 1.13% | -8.10% |
| cash0.03_cap0.18 | 36.75% | 1.879 | -14.03% | 2.72% | 0.34% | -7.63% |
| cash0.03_cap0.22 | 36.73% | 1.878 | -14.06% | 2.72% | 0.33% | -7.65% |
| cash0.03_cap0.25 | 36.72% | 1.878 | -14.07% | 2.72% | 0.32% | -7.66% |
| cash0.03_cap0.33 | 36.71% | 1.877 | -14.09% | 2.72% | 0.31% | -7.68% |
| cash0.05_cap0.18 | 36.28% | 1.885 | -13.73% | 4.42% | -0.12% | -7.32% |
| cash0.05_cap0.22 | 36.26% | 1.885 | -13.75% | 4.42% | -0.14% | -7.34% |
| cash0.05_cap0.25 | 36.26% | 1.884 | -13.76% | 4.42% | -0.15% | -7.36% |
| cash0.05_cap0.33 | 36.24% | 1.884 | -13.78% | 4.42% | -0.16% | -7.37% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
