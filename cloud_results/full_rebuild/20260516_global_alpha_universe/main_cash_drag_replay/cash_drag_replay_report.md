# Main Cash Drag Replay

Research-only pre-fullrun diagnostic. No production behavior is changed.

- base CAGR / Sharpe / MaxDD: 26.17% / 2.1520026153811638 / -7.34%
- production CAGR / Sharpe / MaxDD: 20.29% / 1.4848607897809738 / -15.28%
- base-vs-production CAGR / MaxDD delta: 5.88% / 7.94%
- base avg cash: 19.39%
- best model: `cash0.00_cap0.18`
- best CAGR / Sharpe / MaxDD: 25.87% / 1.6617175292542905 / -14.08%
- best avg cash: 0.00%
- cash source: `reported_regime_by_month`
- avg reported cash before alignment: 19.39%
- avg explicit monthly-book cash before alignment: 4.88%
- avg cash gap before alignment: 14.51%

## Top Grid Rows

| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| cash0.00_cap0.18 | 25.87% | 1.662 | -14.08% | 0.00% | -0.30% | -6.74% |
| cash0.00_cap0.22 | 25.86% | 1.662 | -14.06% | -0.00% | -0.31% | -6.73% |
| cash0.00_cap0.25 | 25.86% | 1.662 | -14.06% | -0.00% | -0.31% | -6.72% |
| cash0.00_cap0.33 | 25.85% | 1.662 | -14.04% | -0.00% | -0.32% | -6.70% |
| cash0.03_cap0.18 | 25.35% | 1.672 | -13.67% | 2.50% | -0.82% | -6.33% |
| cash0.03_cap0.22 | 25.35% | 1.672 | -13.65% | 2.50% | -0.83% | -6.32% |
| cash0.03_cap0.25 | 25.34% | 1.672 | -13.65% | 2.50% | -0.83% | -6.31% |
| cash0.03_cap0.33 | 25.33% | 1.672 | -13.63% | 2.50% | -0.84% | -6.29% |
| cash0.05_cap0.18 | 25.08% | 1.681 | -13.40% | 4.01% | -1.10% | -6.07% |
| cash0.05_cap0.22 | 25.07% | 1.681 | -13.38% | 4.01% | -1.10% | -6.05% |
| cash0.05_cap0.25 | 25.06% | 1.681 | -13.38% | 4.01% | -1.11% | -6.04% |
| cash0.05_cap0.33 | 25.06% | 1.681 | -13.36% | 4.01% | -1.12% | -6.02% |

## Limits

- This replay reallocates only within already-selected monthly holdings.
- Base replay may not match production metrics exactly because it uses exported holdings and monthly forward returns, not the full portfolio accounting path.
- It does not discover missed winners such as a future SNDK-like setup.
- A full rebuild/challenger replay is still required before activation.
