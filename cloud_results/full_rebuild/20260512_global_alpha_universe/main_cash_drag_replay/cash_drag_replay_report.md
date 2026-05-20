# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 34.40% / 2.3147029355936604 / -5.42%
- production CAGR / Sharpe / MaxDD: 29.19% / 1.7248976396719429 / -17.46%
- base-vs-production CAGR / MaxDD delta: 5.21% / 12.04%
- base avg cash: 20.93%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 35.87% / 1.875055428601023 / -13.96%
- best avg cash: -0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 20.93%
- avg explicit monthly-book cash before alignment: 5.03%
- avg cash gap before alignment: 15.90%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 35.87% | 1.875 | -13.96% | -0.00% | 1.47% | -8.54% |
| cash0.00_cap0.22 | 35.86% | 1.875 | -13.97% | -0.00% | 1.46% | -8.54% |
| cash0.00_cap0.25 | 35.86% | 1.876 | -13.97% | 0.00% | 1.46% | -8.55% |
| cash0.00_cap0.33 | 35.86% | 1.876 | -13.98% | 0.00% | 1.46% | -8.55% |
| cash0.03_cap0.18 | 35.05% | 1.882 | -13.52% | 2.75% | 0.65% | -8.10% |
| cash0.03_cap0.22 | 35.04% | 1.882 | -13.53% | 2.75% | 0.64% | -8.11% |
| cash0.03_cap0.25 | 35.04% | 1.883 | -13.53% | 2.75% | 0.64% | -8.11% |
| cash0.03_cap0.33 | 35.03% | 1.883 | -13.54% | 2.75% | 0.63% | -8.12% |
| cash0.05_cap0.18 | 34.59% | 1.890 | -13.23% | 4.43% | 0.19% | -7.81% |
| cash0.05_cap0.22 | 34.58% | 1.890 | -13.24% | 4.43% | 0.18% | -7.82% |
| cash0.05_cap0.25 | 34.58% | 1.890 | -13.24% | 4.43% | 0.18% | -7.82% |
| cash0.05_cap0.33 | 34.57% | 1.890 | -13.25% | 4.43% | 0.17% | -7.83% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
