# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 34.26% / 2.3474657070901004 / -5.01%
- production CAGR / Sharpe / MaxDD: 27.32% / 1.6397079003602735 / -17.87%
- base-vs-production CAGR / MaxDD delta: 6.94% / 12.86%
- base avg cash: 19.37%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 33.23% / 1.7954551092671176 / -15.00%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 19.37%
- avg explicit monthly-book cash before alignment: 3.65%
- avg cash gap before alignment: 15.73%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 33.23% | 1.795 | -15.00% | 0.00% | -1.03% | -9.99% |
| cash0.00_cap0.22 | 33.22% | 1.795 | -15.01% | 0.00% | -1.04% | -10.00% |
| cash0.00_cap0.25 | 33.22% | 1.795 | -15.02% | 0.00% | -1.04% | -10.01% |
| cash0.00_cap0.33 | 33.21% | 1.795 | -15.03% | -0.00% | -1.04% | -10.02% |
| cash0.03_cap0.18 | 32.38% | 1.799 | -14.58% | 2.80% | -1.88% | -9.57% |
| cash0.03_cap0.22 | 32.37% | 1.799 | -14.59% | 2.80% | -1.89% | -9.58% |
| cash0.03_cap0.25 | 32.37% | 1.799 | -14.60% | 2.80% | -1.89% | -9.59% |
| cash0.03_cap0.33 | 32.37% | 1.799 | -14.61% | 2.80% | -1.89% | -9.60% |
| cash0.05_cap0.18 | 31.90% | 1.803 | -14.29% | 4.56% | -2.36% | -9.28% |
| cash0.05_cap0.22 | 31.90% | 1.803 | -14.30% | 4.56% | -2.36% | -9.29% |
| cash0.05_cap0.25 | 31.89% | 1.803 | -14.31% | 4.56% | -2.37% | -9.30% |
| cash0.05_cap0.33 | 31.89% | 1.803 | -14.32% | 4.56% | -2.37% | -9.31% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
