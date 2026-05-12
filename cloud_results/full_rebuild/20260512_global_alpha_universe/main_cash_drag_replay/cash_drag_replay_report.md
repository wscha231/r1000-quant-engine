# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 34.31% / 2.2892447163866385 / -5.16%
- production CAGR / Sharpe / MaxDD: 28.91% / 1.7438756765602594 / -13.56%
- base-vs-production CAGR / MaxDD delta: 5.40% / 8.40%
- base avg cash: 18.94%
- best model: `cash0.00_cap0.33`
- best CAGR / Sharpe / MaxDD: 34.85% / 1.8468507104653387 / -11.90%
- best avg cash: -0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 18.94%
- avg explicit monthly-book cash before alignment: 4.86%
- avg cash gap before alignment: 14.08%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.33 | 34.85% | 1.847 | -11.90% | -0.00% | 0.54% | -6.74% |
| cash0.00_cap0.25 | 34.84% | 1.846 | -11.92% | 0.00% | 0.54% | -6.76% |
| cash0.00_cap0.22 | 34.84% | 1.845 | -11.93% | -0.00% | 0.53% | -6.78% |
| cash0.00_cap0.18 | 34.83% | 1.844 | -11.96% | -0.00% | 0.53% | -6.80% |
| cash0.03_cap0.33 | 34.20% | 1.857 | -11.52% | 2.59% | -0.11% | -6.36% |
| cash0.03_cap0.25 | 34.20% | 1.856 | -11.54% | 2.59% | -0.11% | -6.39% |
| cash0.03_cap0.22 | 34.20% | 1.856 | -11.56% | 2.59% | -0.11% | -6.40% |
| cash0.03_cap0.18 | 34.19% | 1.855 | -11.58% | 2.59% | -0.11% | -6.42% |
| cash0.05_cap0.18 | 33.83% | 1.864 | -11.33% | 4.16% | -0.47% | -6.17% |
| cash0.05_cap0.22 | 33.83% | 1.865 | -11.30% | 4.16% | -0.47% | -6.15% |
| cash0.05_cap0.25 | 33.83% | 1.865 | -11.29% | 4.16% | -0.47% | -6.13% |
| cash0.05_cap0.33 | 33.83% | 1.866 | -11.27% | 4.16% | -0.48% | -6.11% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
