# Run287 capital-action timing and semiconductor damage result (2026-07-17)

## Decision

1. The rejected SEC capital-allocation signal was not merely priced before the filing. Positive events were already weak before acceptance and remained weak through 252 sessions.
2. The 2026-07-16 semiconductor decline is both a broad factor event and an issuer-specific residual event in WDC/SNDK.
3. Historical shock episodes usually rebounded, so this evidence does not authorize an immediate semiconductor exit or big-tech rotation rule.
4. The safe improvement is a factor/residual advisory layer plus first-disclosure and fundamental-break evidence. Holdings, weights, cash, and orders remain unchanged.

## Capital-action timing decomposition

The frozen exact-accepted events were decomposed into pre-filing 5/21/63D, acceptance reaction, and post-filing 1/5/21/63/126/252/504D SPY-excess returns. Companyfacts acceptance is not assumed to be the first public disclosure.

### OOS positive-event path

| Window | Mean SPY excess return |
|---|---:|
| Pre-21D | -0.63% |
| Acceptance reaction | -0.11% |
| Post-1D | -0.10% |
| Post-5D | -0.25% |
| Post-21D | -0.04% |
| Post-63D | -2.01% |
| Post-126D | -2.31% |
| Post-252D | -5.27% |

Positive-minus-negative spreads are -0.78pp at 21D, -2.16pp at 63D, -5.01pp at 126D, and -22.09pp at 252D. The signal does not reveal a delayed positive horizon. The evidence is more consistent with composition: buybacks can be a response to weak/mature-price regimes, while issuance can be undertaken by strong growth firms.

## Exact 2026-07-16 close

| Portfolio | 2026-07-16 return | Equity from USD 100,000 seed | Seed return | Cash weight |
|---|---:|---:|---:|---:|
| Main | -2.41% | $98,718 | -1.28% | 1.38% |
| Concentrated | -8.99% | $85,473 | -14.53% | 0.84% |

These are forward paper-account marks, not a change to the historical generated-book CAGR/MDD series.

### Concentrated damage

| Ticker | Weight | 1D | 21D | 63D drawdown | Existing watch | SOXX residual state |
|---|---:|---:|---:|---:|---|---|
| WDC | 39.32% | -9.15% | -28.57% | -37.44% | ALERT | residual ALERT |
| CIEN | 40.03% | -7.09% | -16.10% | -37.99% | ALERT | not a semiconductor mapping |
| SNDK | 19.81% | -12.63% | -33.06% | -39.57% | WATCH | residual ALERT |

Concentrated hardware exposure is 99.16%; direct WDC/SNDK semiconductor exposure is 59.13%. WDC and SNDK underperformed SOXX by 4.69pp and 8.17pp on the day, placing both at approximately their own past residual 2.5% tail.

### Main damage

Main direct semiconductor exposure is 25.70%, and the broader hardware mapping is 37.12%. Existing ALERT names are GLW, GOOG, and ON; WATCH names are ECG, LRCX, MLI, NXPI, and TER. The largest 1D contribution was GOOG at -0.83%p, so Main's decline was not solely semiconductor exposure.

## Factor state and historical shock behavior

SOXX closed -4.46% on 2026-07-16, returned -15.59% over 21 sessions, and was -19.01% from its 63-session high. It is below both moving averages and triggers trend and drawdown damage. It does not trigger the rolling 1D tail because repeated crashes lowered the past-only 2.5% threshold to -4.93%.

| Historical event | Resolved full n | Resolved OOS n | 21D SOXX excess mean | 63D SOXX excess mean | Verdict |
|---|---:|---:|---:|---:|---|
| Daily SOXX tail shock | 53 / 52 | 22 / 21 | +3.17% | +11.61% | selling edge rejected descriptively |
| Trend + drawdown transition | 18 | 3 | +3.83% | +5.08% | underpowered OOS |
| Two tail shocks within 21D transition | 16 | 5 | +1.30% | +7.30% | underpowered OOS |

The current recurrent-shock episode began on 2026-06-16. From the next close through 2026-07-16, the memory basket lost 26.87% while the AAPL/GOOG/META diagnostic basket gained 9.13%. This counterfactual is severe, but it is one inspected episode: historically the rotation basket lagged semiconductor rebounds after the same classes of shock.

## Current fundamental cross-check

The price damage is real, but the latest official company disclosures do not yet establish a fundamental collapse:

- Western Digital reported 45% year-over-year revenue growth, 50.2% non-GAAP gross margin, and USD 978 million of free cash flow for fiscal Q3 on 2026-04-30. Its fiscal Q4 guide called for 36% to 44% revenue growth and a 51% to 52% gross margin. The next scheduled results are 2026-08-05.
- Sandisk reported USD 5.95 billion of fiscal Q3 revenue, 97% sequential growth, and 233% sequential data-center growth on 2026-04-30. Its fiscal Q4 guide was USD 7.75 billion to USD 8.25 billion of revenue and USD 30 to USD 33 of non-GAAP EPS. The next scheduled results are 2026-08-05.
- Micron reported record fiscal Q3 results and said HBM4 high-volume shipments had begun on 2026-06-24.

Therefore, the working interpretation is a broad semiconductor valuation/capital-spending/positioning repricing with additional WDC/SNDK issuer residual damage, not a confirmed issuer fundamental break. The guidance is stale relative to the 2026-07-16 close, so it is evidence against a panic-sell conclusion, not evidence that the names are safe. The 2026-08-05 WDC/SNDK results are the next hard decision-time checkpoints.

## What the system caught and missed

- At the 2026-07-15 close, WDC was already ALERT and CIEN/SNDK were WATCH. The system correctly blocked incremental WDC buying but intentionally had no sell authorization.
- On 2026-07-16, WDC and CIEN are ALERT. SNDK remains WATCH because its -12.63% absolute return narrowly missed its unusually low -12.81% own-history threshold even though its SPY-relative loss breached the relative threshold.
- A sector-residual diagnostic catches both WDC and SNDK. This is the immediate monitoring improvement.
- The daily rolling quantile adapts downward during repeated crashes. Multi-session factor trend/drawdown must therefore be displayed alongside the 1D shock flag.
- Next-close execution cannot avoid the 2026-07-16 loss from a signal generated at the 2026-07-15 close; it can only change exposure at the 2026-07-16 close. Any claim of earlier protection needs an earlier, PIT-clean signal.

## Improvement sequence

### P0: advisory monitoring, now

- Publish SOXX/SMH trend, drawdown, 21D tail-shock count, and WDC/SNDK sector-residual percentile beside each held name.
- Escalate a residual-tail name to `FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW`; do not auto-sell or add cash.
- Track each factor-damage episode append-only, including maximum adverse excursion, time to trough, recovery, and replacement counterfactual.

### P1: semantically new evidence

- Replace backward-looking Companyfacts action amounts with actual first-disclosure events: accepted-time 8-K/press-release repurchase authorizations, convertible offerings, pricing, cancellation, and retirement announcements.
- Combine sector residual damage with a real fundamental break only: accepted-time negative guidance/earnings revision, margin or cash-flow deterioration, or financing need. Missing remains neutral.
- A replacement is eligible only if the existing selector already approves it; the risk layer cannot invent AAPL/GOOG/META purchases.

### P2: fixed shadow gate

Only after at least 12 independent OOS factor episodes and 200 resolved security outcomes, test one shadow rule: freeze incremental buys and allow scheduled selector replacement only when both sector-residual tail and exact fundamental-negative evidence are present. Use next-close, integer shares, 25/50/100bps, cash-carry/zero-yield, and ticker/era attribution.

No same-day stop, sector cap, cash floor, threshold grid, or fullrun is authorized.

## Evidence

- `outputs/sec_capital_allocation_timing_20260717/summary.json`
- `outputs/run287_holding_risk_watch_full_20260717_close_20260716/summary.json`
- `outputs/run287_semiconductor_damage_20260717_close_20260716/summary.json`
- `tools/analyze_sec_capital_action_timing.py`
- `tools/analyze_run287_semiconductor_damage.py`
- Western Digital fiscal Q3 2026 results: <https://investor.wdc.com/news-releases/news-release-details/wd-reports-fiscal-third-quarter-2026-financial-results>
- Western Digital investor relations calendar: <https://investor.wdc.com/investor-relations>
- Sandisk fiscal Q3 2026 results: <https://investor.sandisk.com/news-releases/news-release-details/sandisk-reports-fiscal-third-quarter-2026-financial-results>
- Sandisk investor relations calendar: <https://investor.sandisk.com/>
- Micron fiscal Q3 2026 results: <https://investors.micron.com/node/50671>
