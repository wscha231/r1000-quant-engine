# Run287 Current Portfolio and CAGR/MDD Research — 2026-07-16

## Valuation contract

- Operating paper seed: 2026-07-13 exact close
- Current mark: 2026-07-15 exact completed close
- Price coverage: 20/20 holdings plus SPY and QQQ, exact-date missing 0
- Mode: review-only mark-to-market; no order, rebalance, cash mutation, or live execution
- Canonical generated baselines remain unchanged:
  - Main: CAGR 34.4032%, MDD -25.3619%
  - Concentrated: CAGR 49.0971%, MDD -22.9552%

The daily forward return below is not a replacement for the seven-year CAGR/MDD result.

## Current operating paper accounts

| Portfolio | Equity | Since 2026-07-13 | 2026-07-15 day | Current cash | Positions |
|---|---:|---:|---:|---:|---:|
| Main | $101,151.72 | +1.15% | -0.91% | 1.35% | 17 |
| Concentrated | $93,915.00 | -6.08% | -7.65% | 0.76% | 3 |
| SPY | — | +0.75% | +0.40% | — | — |
| QQQ | — | +0.84% | -0.27% | — | — |

### Main holdings

| Ticker | Current weight | Since seed | 2026-07-15 day | Current risk state |
|---|---:|---:|---:|---|
| GOOG | 18.67% | +5.57% | +3.60% | NORMAL |
| AMAT | 6.30% | +0.70% | -2.73% | NORMAL |
| LRCX | 6.30% | +1.67% | -3.08% | NORMAL |
| GEV | 6.26% | +1.22% | -1.01% | NORMAL |
| VRT | 6.02% | -0.43% | +0.33% | WATCH |
| FTI | 6.00% | -1.05% | -3.08% | NORMAL |
| WELL | 6.00% | -0.54% | -1.15% | NORMAL |
| GLW | 5.86% | -4.75% | -7.05% | WATCH |
| NXPI | 5.79% | +0.22% | -1.71% | NORMAL |
| ECG | 4.11% | +3.86% | +0.13% | WATCH |
| ON | 4.03% | +2.40% | -1.27% | WATCH |
| MLI | 3.98% | +1.90% | -1.51% | WATCH |
| KIM | 3.94% | -0.08% | -0.63% | NORMAL |
| PR | 3.93% | -0.15% | 0.00% | NORMAL |
| DTM | 3.88% | -0.55% | -2.00% | NORMAL |
| TKR | 3.86% | +0.82% | -0.09% | NORMAL |
| TER | 3.72% | +0.30% | -3.15% | WATCH |
| Cash | 1.35% | — | — | — |

Main has 11 NORMAL and six WATCH names. GOOG contributed approximately +1.00 percentage point since the seed; GLW contributed approximately -0.30 point.

### Concentrated holdings

| Ticker | Current weight | Since seed | 2026-07-15 day | Current risk state | Reason |
|---|---:|---:|---:|---|---|
| WDC | 39.39% | -7.51% | -8.78% | ALERT | idiosyncratic shock, trend damage, drawdown damage |
| CIEN | 39.21% | -6.06% | -6.37% | WATCH | trend damage, drawdown damage |
| SNDK | 20.64% | -3.52% | -8.12% | WATCH | trend damage, drawdown damage |
| Cash | 0.76% | — | — | — | — |

The risk engine's action for WDC is `FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW`; it does not authorize a sale. All three names are below their 20-day and 50-day averages. No automatic order was generated.

## New exact-selector advisory shadows

The following shadows use the 2026-07-13 selector, 2026-07-14 next close, integer shares, and 25 bps entry cost. They are not operating portfolios.

| Shadow | Holdings | Target cash | Actual cash after integer shares/cost | 2026-07-15 net return |
|---|---|---:|---:|---:|
| Main strict | AMAT, AMD, ARM, COHU, DELL, FLEX, FTNT, MRVL, MU, PANW, SNDK, STX, UMC, WDC | 8.60% | 12.75% | -3.40% |
| Main prior-hold bridge | ALAB, AMD, ARM, DELL, FLEX, FTNT, HPE, MRVL, MU, PANW, SNDK, STX, UMC, WDC | 7.59% | 12.43% | -3.22% |
| Concentrated strict | AMD, ARM, DELL, MU, UMC | 34.09% | 36.55% | -1.66% |

The high Concentrated advisory cash was protective in this one session. Its invested sleeve lost about 2.48% before integer-share/cost effects, while the total shadow lost 1.66%. UMC gained 4.53%; DELL, MU, AMD, and ARM declined.

## First causal attribution

The decision/outcome ledger now contains 2,967 decision events and 888 resolved one-session outcome events. This is still underpowered for the primary 63-session gate.

| Portfolio/scenario | Selected mean 1D | Matched control mean 1D | Selection spread |
|---|---:|---:|---:|
| Main strict | -4.00% | -1.62% | -2.37 pp |
| Main prior-hold bridge | -4.24% | -1.87% | -2.37 pp |
| Concentrated strict | -3.65% | -4.96% | +1.32 pp |

Advisory-to-operating gross absolute weight divergence is 179.8% for Main strict, 192.4% for the Main bridge, and 165.9% for Concentrated. The current advisory selector and operating books are therefore materially different portfolios.

## CAGR/MDD improvement decision

One policy cannot be promoted across both portfolios from this evidence:

- Main operating was materially more defensive than both Main advisory shadows on 2026-07-15.
- Concentrated advisory shadow was materially more defensive than the three-name operating book.
- The result is only one decision day and one resolved session, so it cannot establish a durable CAGR or MDD edge.

The next admissible candidate is therefore **Concentrated advisory-transition shadow only**, while Main remains unchanged. It must accumulate fixed 21/63/126-session outcomes and compare against the operating account. No cash threshold, cluster cap, stop, or exit-delay grid is opened.

The most immediate system fix is operational rather than a new alpha: keep exact per-ticker close coverage healthy so the current holding-risk monitor can run. With sufficient history it detected WDC ALERT and eight WATCH names; with a short cache all 20 names failed as `DATA_INSUFFICIENT`.

## Promotion gate

Do not change operating weights from this result. Review can open only after the preregistered forward gate: at least 26 distinct decision weeks, 200 resolved 63-session observations, 50 distinct tickers, positive matched-control spread with a non-negative week-block bootstrap lower bound, 50 bps direction preserved, no MDD degradation, and separate user approval.
