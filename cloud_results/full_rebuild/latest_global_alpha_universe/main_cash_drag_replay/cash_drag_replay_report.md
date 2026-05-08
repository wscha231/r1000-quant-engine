# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 33.88% / 2.192621473577403 / -5.04%
- production CAGR / Sharpe / MaxDD: 28.12% / 1.6202096991237043 / -15.92%
- base-vs-production CAGR / MaxDD delta: 5.76% / 10.88%
- base avg cash: 19.72%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 33.94% / 1.807305924058752 / -13.36%
- best avg cash: -0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 19.72%
- avg explicit monthly-book cash before alignment: 4.32%
- avg cash gap before alignment: 15.40%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 33.94% | 1.807 | -13.36% | -0.00% | 0.06% | -8.31% |
| cash0.00_cap0.22 | 33.93% | 1.807 | -13.36% | -0.00% | 0.05% | -8.31% |
| cash0.00_cap0.25 | 33.93% | 1.807 | -13.36% | -0.00% | 0.05% | -8.32% |
| cash0.00_cap0.33 | 33.93% | 1.806 | -13.36% | 0.00% | 0.05% | -8.32% |
| cash0.03_cap0.18 | 33.08% | 1.811 | -13.01% | 2.79% | -0.80% | -7.97% |
| cash0.03_cap0.22 | 33.08% | 1.811 | -13.01% | 2.79% | -0.80% | -7.96% |
| cash0.03_cap0.25 | 33.07% | 1.811 | -13.00% | 2.79% | -0.81% | -7.96% |
| cash0.03_cap0.33 | 33.07% | 1.810 | -13.00% | 2.79% | -0.81% | -7.96% |
| cash0.05_cap0.18 | 32.55% | 1.816 | -12.78% | 4.55% | -1.33% | -7.73% |
| cash0.05_cap0.22 | 32.55% | 1.815 | -12.77% | 4.55% | -1.33% | -7.73% |
| cash0.05_cap0.25 | 32.54% | 1.815 | -12.77% | 4.55% | -1.34% | -7.73% |
| cash0.05_cap0.33 | 32.54% | 1.815 | -12.77% | 4.55% | -1.34% | -7.73% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
