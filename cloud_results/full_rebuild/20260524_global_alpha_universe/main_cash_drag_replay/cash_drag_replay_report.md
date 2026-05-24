# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 35.14% / 2.464335809422853 / -6.85%
- production CAGR / Sharpe / MaxDD: 28.45% / 1.7143210142406808 / -18.05%
- base-vs-production CAGR / MaxDD delta: 6.69% / 11.20%
- base avg cash: 20.21%
- best model: `cash0.00_cap0.33`
- best CAGR / Sharpe / MaxDD: 34.99% / 1.912804569389479 / -15.93%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 20.21%
- avg explicit monthly-book cash before alignment: 4.92%
- avg cash gap before alignment: 15.29%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.33 | 34.99% | 1.913 | -15.93% | 0.00% | -0.15% | -9.08% |
| cash0.00_cap0.25 | 34.98% | 1.912 | -15.94% | -0.00% | -0.16% | -9.09% |
| cash0.00_cap0.22 | 34.97% | 1.912 | -15.95% | -0.00% | -0.17% | -9.10% |
| cash0.00_cap0.18 | 34.94% | 1.910 | -15.96% | -0.00% | -0.20% | -9.11% |
| cash0.03_cap0.33 | 34.29% | 1.923 | -15.45% | 2.63% | -0.85% | -8.60% |
| cash0.03_cap0.25 | 34.29% | 1.923 | -15.46% | 2.63% | -0.85% | -8.61% |
| cash0.03_cap0.22 | 34.28% | 1.923 | -15.46% | 2.63% | -0.86% | -8.62% |
| cash0.03_cap0.18 | 34.27% | 1.922 | -15.48% | 2.63% | -0.87% | -8.63% |
| cash0.05_cap0.33 | 33.92% | 1.934 | -15.13% | 4.19% | -1.22% | -8.28% |
| cash0.05_cap0.25 | 33.92% | 1.933 | -15.13% | 4.19% | -1.22% | -8.29% |
| cash0.05_cap0.22 | 33.92% | 1.933 | -15.14% | 4.19% | -1.22% | -8.29% |
| cash0.05_cap0.18 | 33.91% | 1.933 | -15.15% | 4.19% | -1.23% | -8.30% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
