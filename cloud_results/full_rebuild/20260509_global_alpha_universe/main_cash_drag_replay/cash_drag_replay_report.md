# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 33.95% / 2.2948019659218 / -4.74%
- production CAGR / Sharpe / MaxDD: 27.86% / 1.6498608070881968 / -16.84%
- base-vs-production CAGR / MaxDD delta: 6.09% / 12.09%
- base avg cash: 20.16%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 34.54% / 1.8036406720480906 / -13.18%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 20.16%
- avg explicit monthly-book cash before alignment: 4.67%
- avg cash gap before alignment: 15.49%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 34.54% | 1.804 | -13.18% | 0.00% | 0.59% | -8.43% |
| cash0.00_cap0.22 | 34.52% | 1.804 | -13.21% | 0.00% | 0.58% | -8.46% |
| cash0.00_cap0.25 | 34.51% | 1.803 | -13.22% | -0.00% | 0.57% | -8.48% |
| cash0.00_cap0.33 | 34.50% | 1.803 | -13.25% | 0.00% | 0.56% | -8.50% |
| cash0.03_cap0.18 | 33.72% | 1.810 | -12.82% | 2.68% | -0.22% | -8.08% |
| cash0.03_cap0.22 | 33.70% | 1.810 | -12.85% | 2.68% | -0.24% | -8.10% |
| cash0.03_cap0.25 | 33.70% | 1.810 | -12.86% | 2.68% | -0.25% | -8.12% |
| cash0.03_cap0.33 | 33.68% | 1.809 | -12.88% | 2.68% | -0.26% | -8.14% |
| cash0.05_cap0.18 | 33.28% | 1.816 | -12.58% | 4.30% | -0.67% | -7.84% |
| cash0.05_cap0.22 | 33.26% | 1.816 | -12.60% | 4.30% | -0.68% | -7.86% |
| cash0.05_cap0.25 | 33.25% | 1.816 | -12.62% | 4.30% | -0.69% | -7.87% |
| cash0.05_cap0.33 | 33.24% | 1.816 | -12.64% | 4.30% | -0.71% | -7.90% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
