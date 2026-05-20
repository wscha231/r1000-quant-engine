# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 34.60% / 2.383382826841457 / -5.46%
- production CAGR / Sharpe / MaxDD: 29.66% / 1.7776333218625067 / -15.66%
- base-vs-production CAGR / MaxDD delta: 4.94% / 10.19%
- base avg cash: 20.63%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 36.37% / 1.8975517353013238 / -12.88%
- best avg cash: -0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 20.63%
- avg explicit monthly-book cash before alignment: 4.63%
- avg cash gap before alignment: 16.00%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 36.37% | 1.898 | -12.88% | -0.00% | 1.77% | -7.42% |
| cash0.00_cap0.22 | 36.36% | 1.898 | -12.89% | 0.00% | 1.76% | -7.42% |
| cash0.00_cap0.25 | 36.36% | 1.898 | -12.89% | 0.00% | 1.76% | -7.42% |
| cash0.00_cap0.33 | 36.36% | 1.899 | -12.89% | 0.00% | 1.76% | -7.43% |
| cash0.03_cap0.18 | 35.43% | 1.904 | -12.49% | 2.73% | 0.83% | -7.03% |
| cash0.03_cap0.22 | 35.42% | 1.905 | -12.49% | 2.73% | 0.82% | -7.03% |
| cash0.03_cap0.25 | 35.42% | 1.905 | -12.49% | 2.73% | 0.82% | -7.03% |
| cash0.03_cap0.33 | 35.42% | 1.905 | -12.49% | 2.73% | 0.82% | -7.03% |
| cash0.05_cap0.18 | 34.86% | 1.910 | -12.17% | 4.43% | 0.26% | -6.71% |
| cash0.05_cap0.22 | 34.85% | 1.911 | -12.17% | 4.43% | 0.25% | -6.71% |
| cash0.05_cap0.25 | 34.85% | 1.911 | -12.17% | 4.43% | 0.25% | -6.71% |
| cash0.05_cap0.33 | 34.85% | 1.911 | -12.18% | 4.43% | 0.25% | -6.72% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
