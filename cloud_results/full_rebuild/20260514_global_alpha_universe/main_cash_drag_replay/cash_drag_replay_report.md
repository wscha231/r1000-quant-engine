# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 36.60% / 2.293363382441726 / -5.09%
- production CAGR / Sharpe / MaxDD: 30.62% / 1.687330574762984 / -16.88%
- base-vs-production CAGR / MaxDD delta: 5.98% / 11.80%
- base avg cash: 21.99%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 37.06% / 1.847556729931794 / -13.40%
- best avg cash: -0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 21.99%
- avg explicit monthly-book cash before alignment: 4.97%
- avg cash gap before alignment: 17.02%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 37.06% | 1.848 | -13.40% | -0.00% | 0.46% | -8.31% |
| cash0.00_cap0.22 | 37.05% | 1.848 | -13.41% | -0.00% | 0.45% | -8.33% |
| cash0.00_cap0.25 | 37.05% | 1.848 | -13.42% | -0.00% | 0.45% | -8.34% |
| cash0.00_cap0.33 | 37.05% | 1.848 | -13.44% | 0.00% | 0.45% | -8.35% |
| cash0.03_cap0.18 | 36.17% | 1.853 | -12.99% | 2.80% | -0.43% | -7.90% |
| cash0.03_cap0.22 | 36.16% | 1.853 | -13.00% | 2.80% | -0.44% | -7.92% |
| cash0.03_cap0.25 | 36.16% | 1.853 | -13.01% | 2.80% | -0.44% | -7.93% |
| cash0.03_cap0.33 | 36.15% | 1.853 | -13.03% | 2.80% | -0.45% | -7.94% |
| cash0.05_cap0.18 | 35.65% | 1.857 | -12.72% | 4.56% | -0.95% | -7.63% |
| cash0.05_cap0.22 | 35.65% | 1.857 | -12.73% | 4.56% | -0.96% | -7.65% |
| cash0.05_cap0.25 | 35.64% | 1.857 | -12.74% | 4.56% | -0.96% | -7.65% |
| cash0.05_cap0.33 | 35.63% | 1.857 | -12.75% | 4.56% | -0.97% | -7.67% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
