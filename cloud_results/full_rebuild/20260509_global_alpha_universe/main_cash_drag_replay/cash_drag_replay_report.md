# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 35.76% / 2.269813587112939 / -4.81%
- production CAGR / Sharpe / MaxDD: 30.91% / 1.6999187026810325 / -16.38%
- base-vs-production CAGR / MaxDD delta: 4.85% / 11.57%
- base avg cash: 22.04%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 37.95% / 1.8422137823583056 / -13.24%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 22.04%
- avg explicit monthly-book cash before alignment: 4.83%
- avg cash gap before alignment: 17.21%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 37.95% | 1.842 | -13.24% | 0.00% | 2.19% | -8.42% |
| cash0.00_cap0.22 | 37.94% | 1.841 | -13.25% | 0.00% | 2.18% | -8.43% |
| cash0.00_cap0.25 | 37.93% | 1.841 | -13.25% | 0.00% | 2.17% | -8.44% |
| cash0.00_cap0.33 | 37.92% | 1.840 | -13.26% | 0.00% | 2.16% | -8.45% |
| cash0.03_cap0.18 | 36.99% | 1.845 | -12.85% | 2.75% | 1.23% | -8.03% |
| cash0.03_cap0.22 | 36.98% | 1.844 | -12.86% | 2.75% | 1.22% | -8.04% |
| cash0.03_cap0.25 | 36.97% | 1.844 | -12.86% | 2.75% | 1.21% | -8.05% |
| cash0.03_cap0.33 | 36.96% | 1.843 | -12.87% | 2.75% | 1.20% | -8.06% |
| cash0.05_cap0.18 | 36.39% | 1.847 | -12.59% | 4.49% | 0.63% | -7.78% |
| cash0.05_cap0.22 | 36.38% | 1.847 | -12.60% | 4.49% | 0.62% | -7.79% |
| cash0.05_cap0.25 | 36.37% | 1.846 | -12.61% | 4.49% | 0.61% | -7.79% |
| cash0.05_cap0.33 | 36.36% | 1.846 | -12.62% | 4.49% | 0.60% | -7.80% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
