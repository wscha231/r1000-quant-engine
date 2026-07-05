# Run287 Generated-Book Negative Evidence

Status: research-only, production-blocked.

Run: `28725350727`

Latest measurement basis:

- target book source: run287 generated operating target books
- replay end: `2026-07-02`
- price cache: `outputs/run287_price_cache_latest/cache_prices`
- cash rate: `cache_macro/fred_dgs3mo_DGS3MO.parquet`
- metric mode: `broker_ledger_next_close_cash_carry`
- cash-carry contract: DGS3MO, 1BD lag, ACT/365, 50 bps haircut

## Result

| Portfolio | Zero-yield CAGR / MaxDD | Cash-carry CAGR / MaxDD | Target pass |
| --- | ---: | ---: | --- |
| Main | 32.94% / -25.65% | 33.81% / -25.36% | false |
| Concentrated | 47.00% / -23.22% | 48.41% / -22.96% | false |

Decision label: `alpha_candidate_rejected_on_generated_book`.

## Interpretation

The frozen-book candidate was not merely missing cash-carry in the fullrun
artifact. On the latest regenerated book and latest replay window, cash-carry
does not restore the 35/50 CAGR target, and Main still breaches the -25% MDD
contract.

This is not primarily a "hook failed" result. It is the first honest
latest-window baseline:

- frozen cash-carry combo stopped at `2026-06-29`
- run287 latest-basis generated-book measurement runs through `2026-07-02`
- the `2026-06-30` through `2026-07-02` window shock explains most of the
  headline gap
- regenerated-book drift remains secondary and diagnostic
- hook applied counts are not hook contribution evidence without a same-book
  hook-off counterfactual

Current official research baseline for run287 latest-basis generated-book
measurement is therefore:

| Portfolio | Zero-yield CAGR / MaxDD | Cash-carry CAGR / MaxDD |
| --- | ---: | ---: |
| Main | 32.94% / -25.65% | 33.81% / -25.36% |
| Concentrated | 47.00% / -23.22% | 48.41% / -22.96% |

Rolling endpoint attribution under
`outputs/run287_rolling_window_deficit` refines the failure:

- Main at `2026-06-29`: 35.57% / -25.36%; CAGR passes but MDD already fails.
- Main at `2026-07-02`: 33.81% / -25.36%; CAGR drops -1.77pp, MDD unchanged.
- Concentrated at `2026-06-29`: 50.67% / -22.96%; passes.
- Concentrated at `2026-07-02`: 48.41% / -22.96%; CAGR drops -2.27pp.

Therefore Main should not be treated as a July-only shock problem. Concentrated
does show end-date shock sensitivity, but its last-252 endpoint pass rate is
only 2.8%, so one-endpoint 50% recovery is not robust enough for promotion.

## Anti-Leakage Boundary

Do not:

- dispatch another fullrun for this candidate
- tune rank or threshold values from run287 losers
- relabel the 2026-06-29 clamp as a current pass
- use frozen-book cash-carry metrics as regenerated-book acceptance
- make production, live-trading, or public return claims

Allowed next actions:

- keep the negative evidence
- use the W1 double-run result as local determinism evidence, while keeping
  official artifact parity as a separate cache/provenance issue
- continue rolling multi-window deficit attribution before designing alpha
- use `outputs/run287_exit_latency` as negative evidence that Main
  exit-timing latency was not a material MDD lever on the top drawdown
  contributors
- only propose a new ex-ante rule after the failure mode is decision-time
  observable and separately testable

## Main Exit-Latency Negative Evidence

`outputs/run287_exit_latency` audited the Main max-drawdown window
(`2021-11-19` to `2022-09-26`) from the generated-book cash-carry broker
artifacts and the run287 operating Main target book.

Summary:

- MaxDD: `-25.36%`
- hard exit/reduction signals found: `12`
- material latency count: `0`
- latency candidate present: `false`
- diagnosis:
  `hard_signals_found_but_latency_or_post_signal_loss_not_material`

This means Main drawdown repair should not proceed by fitting a new
crash/shock guard or directly editing losing drawdown tickers. The existing
target/actual path reacted quickly enough that latency is not the identified
failure mode.
