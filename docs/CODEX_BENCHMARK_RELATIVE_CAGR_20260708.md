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
- `benchmark_max_dd`
- `relative_max_dd_vs_benchmark`
- `down_capture_vs_benchmark`
- `up_capture_vs_benchmark`
- `beta_vs_benchmark`
- `beta_adjusted_alpha_annualized`
- `tracking_error_vs_benchmark`
- `information_ratio_vs_benchmark`
- `absolute_mission_pass`
- `absolute_mission_cagr_pass`
- `absolute_mission_max_dd_pass`

The fields are computed for the full replay window and for IS/OOS/OOS2 windows when those windows are emitted.

## Governance Red-Team Follow-Up

Benchmark-relative CAGR is not sufficient in a falling market. A positive excess CAGR can come from lower beta, cash weight, or benchmark weakness rather than durable stock-selection skill. Broker replay therefore also emits benchmark-relative risk diagnostics:

- `down_capture_vs_benchmark`: how much of benchmark down days the strategy captured.
- `up_capture_vs_benchmark`: how much of benchmark up days the strategy captured.
- `relative_max_dd_vs_benchmark`: strategy MaxDD minus benchmark MaxDD, where positive means the strategy drawdown was less severe.
- `beta_adjusted_alpha_annualized`: annualized daily-return alpha after removing linear benchmark beta, with no separate risk-free adjustment.
- `information_ratio_vs_benchmark`: annualized active return divided by tracking error against the same benchmark.

These fields are diagnostics, not gates. They must not be used to choose a favorable endpoint, select an easier benchmark, or override the absolute mission contract.

The broker replay top-level metrics also emit `absolute_mission_pass`, `absolute_mission_cagr_pass`, and `absolute_mission_max_dd_pass` next to the benchmark-relative fields so that an excess-return headline cannot hide an absolute CAGR/MDD failure.

Public or production wording must not use "S&P 500 outperformance" style claims while the system remains research-only, PIT universe membership is not clean, and benchmark-relative metrics are proxy measurements. Shared governance fields now include `benchmark_relative_public_claim` in `forbidden_labels`.

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
