# Run287 Latest-Close Research Revaluation - 2026-07-06 Close

## Verdict

This is a research-only latest-close revaluation of the official run287 target
books. It is not a new fullrun, not a production promotion, and not a public
performance claim.

As of the 2026-07-06 US market close:

- Main cash-carry: 34.25% CAGR / -25.36% MDD / 1.28 Sharpe.
- Concentrated cash-carry: 48.66% CAGR / -22.96% MDD / 1.49 Sharpe.
- Main still fails the 35% CAGR and -25% MDD contract.
- Concentrated still fails the 50% CAGR contract, while MDD remains inside -25%.
- Cash-carry improves the marks, but still does not restore the mission targets.

## Measurement Contract

- Source target books: run287 official generated target books.
- Price source: refreshed local replay cache through 2026-07-06 close.
- Price cache manifest status: completed, 336 tickers written, 0 failed.
- Rate source: DGS3MO materialized from FRED graph CSV.
- Cash-carry mode: risk-free cash carry, 1BD lag, 50 bps haircut, ACT/365.
- Requested replay end date: 2026-07-06.
- Actual equity curve end date: 2026-07-06 for all arms.
- Official run287 source end date: 2026-07-02.
- Metric modes: `broker_ledger_next_close` and `broker_ledger_next_close_cash_carry`.
- Production promotion allowed: false.
- Production activation allowed: false.
- Research only: true.

## Current Performance

| Portfolio | Mode | CAGR | MDD | Sharpe | Target verdict |
| --- | --- | ---: | ---: | ---: | --- |
| Main | zero-yield | 33.38% | -25.65% | 1.25 | fail CAGR, fail MDD |
| Main | cash-carry | 34.25% | -25.36% | 1.28 | fail CAGR, fail MDD |
| Concentrated | zero-yield | 47.26% | -23.22% | 1.46 | fail CAGR, pass MDD |
| Concentrated | cash-carry | 48.66% | -22.96% | 1.49 | fail CAGR, pass MDD |

## Cash-Carry Effect

| Portfolio | CAGR delta | MDD delta | Cash interest accrued |
| --- | ---: | ---: | ---: |
| Main | +0.87 pp | +0.29 pp | 13,682.64 USD |
| Concentrated | +1.40 pp | +0.27 pp | 26,580.45 USD |

## Interpretation

The latest-close result confirms the earlier run287 forensic conclusion:
cash-carry is valid research accounting, but it is not enough by itself. The
remaining deficit is not a measurement-only mismatch.

Main remains structurally short of the current research contract. The cash-carry
arm misses 35% CAGR by about 0.75 pp and breaches the -25% MDD limit by about
0.36 pp.

Concentrated remains closer, but still misses the 50% CAGR contract by about
1.34 pp on the same latest-close cash-carry basis.

No alpha hook, threshold retuning, production mutation, or fullrun dispatch was
performed for this revaluation.

## Artifacts

- `outputs/run287_latest_close_20260706/cash_carry_measurement/summary.json`
- `outputs/run287_latest_close_20260706/cash_carry_measurement/arm_metrics.csv`
- `outputs/run287_latest_close_20260706/cash_carry_measurement/report.md`
- `outputs/run287_latest_close_20260706/cash_rate_materialization/summary.json`
- `outputs/run287_latest_close_20260706/cache_prices/replay_price_cache_manifest.json`
