# CODEX_BENCHMARK_RELATIVE_CAGR_20260708

## Verdict

Add benchmark-relative CAGR as a reporting metric.

This should not become an alpha-selection objective by itself. It is a measurement hygiene field that prevents absolute CAGR from being misread when the broad market is unusually strong or weak.

## Benchmark Contract

- Benchmark ticker: `SPY`
- Metric mode: `etf_adjusted_close_total_return_proxy`
- Price field: adjusted close via the existing price cache loader
- Excess CAGR field: `excess_cagr_vs_benchmark = strategy_cagr - benchmark_cagr`
- Excess total return field: `excess_total_return_vs_benchmark = strategy_total_return - benchmark_total_return`

`SPY` adjusted close is an ETF total-return proxy. It is practical for the current free-data price cache, but it is not the same object as the official S&P 500 Total Return index.

## Implemented Fields

Broker replay metrics now include:

- `benchmark_ticker`
- `benchmark_metric_mode`
- `benchmark_status`
- `benchmark_start_date`
- `benchmark_end_date`
- `benchmark_start_price`
- `benchmark_end_price`
- `benchmark_total_return`
- `benchmark_cagr`
- `excess_total_return_vs_benchmark`
- `excess_cagr_vs_benchmark`

The fields are computed for the full replay window and for IS/OOS/OOS2 windows when those windows are emitted.

## Run287 Reference Values

For the run287 available price-cache window `2019-06-03` to `2026-07-02`, SPY adjusted-close TR proxy CAGR is approximately `16.89%`.

Reference excess CAGR:

| Arm | Strategy CAGR | Excess CAGR vs SPY pp |
| --- | ---: | ---: |
| Main baseline | 33.81% | +16.92 |
| Main growth confirmation tilt 10% | 35.79% | +18.90 |
| Concentrated baseline | 48.41% | +31.52 |
| Concentrated W4 SEC tilt 10% | 49.56% | +32.67 |

## Guardrail

This metric is reporting-only. Do not use it to hide a failed absolute mission contract:

- Main still fails the `35% CAGR / -25% MDD` joint contract when MDD is breached.
- Concentrated still fails the `50% CAGR / -25% MDD` joint contract when CAGR is below 50%.
- Production remains blocked while `pit_universe_label_clean=false`.
