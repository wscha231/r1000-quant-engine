# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 33.83% / 2.2023372923811837 / -5.34%
- production CAGR / Sharpe / MaxDD: 28.47% / 1.6505880825201922 / -15.42%
- base-vs-production CAGR / MaxDD delta: 5.36% / 10.08%
- base avg cash: 20.25%
- best model: `cash0.00_cap0.33`
- best CAGR / Sharpe / MaxDD: 34.12% / 1.8093658397507664 / -11.72%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 20.25%
- avg explicit monthly-book cash before alignment: 4.29%
- avg cash gap before alignment: 15.96%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.33 | 34.12% | 1.809 | -11.72% | 0.00% | 0.28% | -6.38% |
| cash0.00_cap0.25 | 34.11% | 1.809 | -11.71% | -0.00% | 0.28% | -6.37% |
| cash0.00_cap0.22 | 34.11% | 1.809 | -11.70% | -0.00% | 0.28% | -6.36% |
| cash0.00_cap0.18 | 34.11% | 1.809 | -11.69% | 0.00% | 0.28% | -6.35% |
| cash0.03_cap0.33 | 33.22% | 1.813 | -11.38% | 2.84% | -0.61% | -6.04% |
| cash0.03_cap0.25 | 33.22% | 1.813 | -11.37% | 2.84% | -0.61% | -6.03% |
| cash0.03_cap0.22 | 33.22% | 1.813 | -11.36% | 2.84% | -0.61% | -6.02% |
| cash0.03_cap0.18 | 33.22% | 1.813 | -11.35% | 2.84% | -0.62% | -6.01% |
| cash0.05_cap0.18 | 32.69% | 1.817 | -11.12% | 4.62% | -1.14% | -5.78% |
| cash0.05_cap0.22 | 32.69% | 1.817 | -11.13% | 4.62% | -1.14% | -5.79% |
| cash0.05_cap0.25 | 32.69% | 1.817 | -11.14% | 4.62% | -1.14% | -5.80% |
| cash0.05_cap0.33 | 32.69% | 1.817 | -11.15% | 4.62% | -1.14% | -5.81% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
