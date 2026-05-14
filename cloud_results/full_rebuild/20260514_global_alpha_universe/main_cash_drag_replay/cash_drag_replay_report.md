# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 35.23% / 2.294864771678963 / -6.40%
- production CAGR / Sharpe / MaxDD: 29.79% / 1.7111635028673302 / -16.65%
- base-vs-production CAGR / MaxDD delta: 5.45% / 10.25%
- base avg cash: 20.23%
- best model: `cash0.00_cap0.33`
- best CAGR / Sharpe / MaxDD: 35.88% / 1.8464682385140603 / -14.82%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 20.23%
- avg explicit monthly-book cash before alignment: 5.00%
- avg cash gap before alignment: 15.24%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.33 | 35.88% | 1.846 | -14.82% | 0.00% | 0.65% | -8.42% |
| cash0.00_cap0.25 | 35.87% | 1.846 | -14.83% | 0.00% | 0.64% | -8.43% |
| cash0.00_cap0.22 | 35.87% | 1.846 | -14.84% | -0.00% | 0.64% | -8.43% |
| cash0.00_cap0.18 | 35.86% | 1.845 | -14.85% | 0.00% | 0.63% | -8.45% |
| cash0.03_cap0.33 | 35.07% | 1.854 | -14.36% | 2.81% | -0.16% | -7.95% |
| cash0.03_cap0.25 | 35.07% | 1.854 | -14.37% | 2.81% | -0.17% | -7.96% |
| cash0.03_cap0.22 | 35.07% | 1.854 | -14.37% | 2.81% | -0.17% | -7.97% |
| cash0.03_cap0.18 | 35.07% | 1.853 | -14.38% | 2.81% | -0.17% | -7.98% |
| cash0.05_cap0.18 | 34.65% | 1.862 | -14.01% | 4.45% | -0.59% | -7.60% |
| cash0.05_cap0.22 | 34.64% | 1.862 | -14.00% | 4.45% | -0.59% | -7.59% |
| cash0.05_cap0.25 | 34.64% | 1.862 | -13.99% | 4.45% | -0.59% | -7.59% |
| cash0.05_cap0.33 | 34.64% | 1.862 | -13.98% | 4.45% | -0.59% | -7.58% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
