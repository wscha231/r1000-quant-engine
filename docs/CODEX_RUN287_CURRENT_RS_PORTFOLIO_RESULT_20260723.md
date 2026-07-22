# Run287 current relative-strength portfolio result — 2026-07-23

## Outcome

The stale concentrated target has been replaced by review-only current
proposals built from the verified 2026-07-21 close. The builder did not run a
backtest/fullrun, mutate canonical target books or paper accounts, or place
orders.

The recommended concentrated shape is N=5 rather than the stale N=3 book.

| Ticker | Target | Optimization rank | RS vs SPY 1M | RS vs SPY 3M |
|---|---:|---:|---:|---:|
| AAPL | 13.96% | 1 | +9.77% | +14.29% |
| PANW | 13.87% | 2 | +18.69% | +95.93% |
| UNH | 13.60% | 5 | +8.62% | +29.81% |
| WELL | 13.17% | 10 | +19.01% | +12.17% |
| NBIX | 12.91% | 13 | +12.91% | +30.21% |
| CASH | 32.50% | — | — | — |

The explicit 32.50% reserve comprises 8.00% data-block reserve, 2.00%
transaction buffer, and 22.50% re-entry-pending reserve. All five selected
stocks are currently classified `B_PULLBACK_WATCH`, so only 75% of their
score-sized allocations are deployed before a full validation/backtest.

## Current paper accounts marked at the same close

### Concentrated

| Ticker | Current weight |
|---|---:|
| WDC | 41.46% |
| CIEN | 37.77% |
| SNDK | 20.03% |
| CASH | 0.75% |

The N=5 preview exits WDC 72 shares, CIEN 88 shares, and SNDK 12 shares. It
then previews buys of AAPL 40, PANW 38, UNH 29, WELL 50, and NBIX 68 shares,
using 25 bps per side and integer shares. These are preview rows only, not
orders.

### Main

| Ticker | Current | Proposed |
|---|---:|---:|
| AMAT | 6.18% | — |
| DTM | 3.81% | — |
| ECG | 4.06% | — |
| FTI | 6.23% | — |
| GEV | 6.44% | 4.35% |
| GLW | 5.49% | — |
| GOOG | 17.56% | — |
| KIM | 4.13% | 5.41% |
| LRCX | 6.08% | — |
| MLI | 4.34% | — |
| NXPI | 5.71% | — |
| ON | 3.98% | — |
| PR | 4.24% | 4.50% |
| TER | 4.09% | — |
| TKR | 3.87% | 4.15% |
| VRT | 6.06% | — |
| WELL | 6.37% | 4.65% |
| AAPL | — | 4.93% |
| PANW | — | 4.90% |
| FTNT | — | 4.87% |
| UNH | — | 4.80% |
| NBIX | — | 4.56% |
| ABBV | — | 4.53% |
| TRP | — | 5.92% |
| TRV | — | 4.38% |
| PM | — | 5.61% |
| THG | — | 4.18% |
| CASH | 1.36% | 28.26% |

The main proposal keeps or resizes GEV, KIM, PR, TKR, and WELL; adds ten new
names; and removes twelve old names. Its explicit reserve is 28.26%.

## Selection and safety contract

- Ranked universe: 314 eligible names.
- Scoring: model 42%, index-relative strength 33%, quality 15%, trend/entry
  10%, less an 8% risk penalty.
- Relative-strength horizons: 1D 10%, 1M 35%, 3M 30%, 6M 15%, 12M 10%.
- Main: 15 stocks, maximum three per sector and two per industry group.
- Concentrated N=5: maximum two per sector and one per industry group; 30%
  single-name cap.
- The verified close is two calendar days old as of 2026-07-23. The builder
  rejects inputs older than three calendar days.
- The upstream full source bundle remains incomplete, hence the explicit
  data-block reserve and `production_activation_allowed=false`.

The generated review artifact is
`outputs/run287_current_portfolio_proposals_20260723_close_20260721/summary.json`.

## H3 integration validation

The final H3 risk/Reserve branch was merged into this proposal branch, and the
ranking plus all three proposal variants were regenerated from the same
verified 2026-07-21 close. Validation passed: focused current-portfolio,
Reserve, preview, and fullrun-guard smoke suites; repository pytest `129/129`;
and full Tier-1 `192/192` in `424.04s`. Python compilation and
`git diff --check` passed. No fullrun or live/production mutation was executed.
