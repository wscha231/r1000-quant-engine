# Run287 CAGR/MDD Search Status - 2026-07-09

## Verdict

No acceptable CAGR/MDD candidate has been found yet.

The best nominal Concentrated result currently observed is:

- `w4_sec_top_quintile_tilt10`
- metric mode: `broker_ledger_next_close_cash_carry`
- Concentrated CAGR: `49.56%`
- MaxDD: `-22.26%`
- Sharpe: `1.534`
- full-window delta: `+1.16pp CAGR`, `+0.70pp MDD`

It is not an accepted candidate because OOS attribution is negative:

- OOS dCAGR: `-3.06pp`
- OOS2 dCAGR: `-0.28pp`
- verdict: `reject_oos_cagr_worse`

No tested arm currently reaches `CAGR >= 50%` with `MaxDD >= -25%`.

## Current Baseline

Generated run287 Concentrated, official target book, cash-carry:

- CAGR: `48.41%`
- MaxDD: `-22.96%`
- Sharpe: `1.488`

Generated run287 Concentrated, official target book, zero-yield:

- CAGR: `47.00%`
- MaxDD: `-23.22%`
- Sharpe: `1.455`

These remain research-only and production-blocked.

## Fixed-Book 13F Result

13F confirmation did not improve the official book:

| arm | metric mode | CAGR | MaxDD | Sharpe | verdict |
| --- | --- | ---: | ---: | ---: | --- |
| official baseline | cash-carry | 48.41% | -22.96% | 1.488 | baseline |
| 13F confirmed | cash-carry | 48.21% | -22.96% | 1.475 | worse CAGR |
| official baseline | zero-yield | 47.00% | -23.22% | 1.455 | baseline |
| 13F confirmed | zero-yield | 46.83% | -23.21% | 1.443 | worse CAGR |

This closes the current 13F fixed-book path as positive evidence.

## Other Tested Paths

Several cheap or existing paths remain rejected:

- actual-results one-pass tilt: OOS CAGR worse
- profitability one-pass tilt: CAGR and/or MDD worse
- evidence fusion: OOS CAGR worse
- smart-money shadow / combined evidence: OOS CAGR worse
- technical momentum / macro / risk control variants: OOS CAGR worse
- W4 consensus: `blocked_no_signal`

The local inventory generated for review is:

- `outputs/run287_cagr_mdd_best_inventory/summary.json`
- `outputs/run287_cagr_mdd_best_inventory/ranked_candidates.csv`
- `outputs/run287_cagr_mdd_best_inventory/best_per_study.csv`

## Forward Estimate Archive

The latest Concentrated book on `2026-07-02` held:

- `MU`
- `SNDK`
- `AMD`
- `UMC`
- `TXN`
- cash

Forward archive workflow run `28997279936` collected those five stock tickers
using the default post-pause vendor order `fmp,finnhub`.

Result:

- status: `blocked_partial_coverage`
- reason: `coverage_below_80pct_warn_only`
- estimate coverage: `1/5`
- usable forward estimate ticker: `AMD`
- raw key pattern scan: clean
- `backtest_acceptance_allowed=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`

Corrected latest-only confirmation after the coverage guard:

| ticker | has forward estimate | confirmation |
| --- | ---: | ---: |
| AMD | 1 | pass |
| MU | 0 | neutral |
| SNDK | 0 | neutral |
| TXN | 0 | neutral |
| UMC | 0 | neutral |

This is forward-only archive evidence. It cannot change historical 7Y CAGR/MDD.

## Guard Fix

The first read of run `28997279936` exposed a bug: tickers without forward
estimate rows could be marked as estimate-confirmed because recommendation
breadth was positive. That is not acceptable.

The collector and latest-confirmation helper now require
`has_forward_estimate > 0` before:

- `estimate_revision_confirmed=1`
- `estimate_revision_replacement_gate_pass=1`
- `estimate_revision_future_winner_multiplier` can move away from `1.0`

This keeps missing estimate coverage neutral.

## Next Action

Do not dispatch a fullrun.

Best next steps:

1. Merge the estimate confirmation coverage guard.
2. Rotate `ALPHAVANTAGE_API_KEY` before any Alpha Vantage-only smoke or
   `LISTING_STATUS` work.
3. Continue forward archive collection for Concentrated current holdings and
   replacement candidates, but treat it as paper-ledger evidence only.
4. If historical CAGR/MDD must improve, obtain true PIT estimate history or
   another decision-time source. Current free snapshots are insufficient.

## Labels

- `no_accepted_cagr_mdd_candidate_yet`
- `best_nominal_candidate_rejected_oos`
- `forward_archive_partial_coverage`
- `estimate_confirmation_guard_fixed`
- `research_only`
- `production_blocked`
