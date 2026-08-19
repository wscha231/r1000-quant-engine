# Run287 Macro Risk-Budget Shadow Result — 2026-08-19

## Conclusion

The latest completed NYSE session is `2026-08-18`. A bounded current macro
sidecar completed with `9/9` market components, `13/13` FRED components, no
critical missing field, and a `1.0` finite ratio. The separate balanced macro
risk-budget router returned a proposal of:

| Sleeve | Shadow weight |
|---|---:|
| Risk assets | 60% |
| Short Treasury category | 20% |
| Intermediate Treasury category | 5% |
| Cash or broker MMF | 15% |

This is a research-only moderate baseline, not a personalized allocation and
not an instruction to trade. The current `BROKER_CASH_OR_MMF` Reserve default
is unchanged. No ETF or security was selected for the stability sleeves.

## Current evidence available at the decision cutoff

- The Federal Reserve held the target range at `3.50%-3.75%` on 2026-07-29;
  three voters preferred a 25 bp increase. This is a hawkish risk signal, but
  it is not an actual July rate increase.
- The 2026-08-17 Treasury curve, safely available before the decision cutoff,
  was `3.87%` at 3 months, `4.19%` at 2 years, `4.72%` at 10 years, and `5.31%`
  at 30 years. The curve was upward sloping while long yields remained high.
- June PCE inflation was `3.7%` headline and `3.3%` core year over year. The
  BLS public API snapshot available after the 2026-08-12 release showed July
  CPI near `3.4%` headline and `2.5%` core year over year. Inflation therefore
  remained above the Federal Reserve's 2% objective.
- The July unemployment rate was `4.1%`. The preliminary payroll employment
  level declined by about 23 thousand from June to July in the BLS snapshot, so the
  labor signal was not strong enough to justify an aggressive risk-on tilt.
- High-yield OAS was `2.70%` on 2026-08-17 and VIX was `15.19`; both indicated
  contained rather than crisis-level market stress.
- WTI was `$84.77` on the latest EIA/FRED observation available in the packet.
  The market proxy showed oil up about `4.1%` over one month but down about
  `12.5%` over three months, which did not meet a persistent oil-shock reading.
- The current market packet had SPY up about `3.4%` over one month and `4.2%`
  over three months and above its 200-day average. This does not confirm a
  broad completed-session crash even if a later intraday selloff feels sharp.
- Liquidity was mixed: the Fed balance sheet was about `$6.760T`, reverse repo
  was near zero, and the Treasury General Account was about `$0.959T`. The
  engine's liquidity family was mildly defensive, primarily because the TGA
  rebuild drained net liquidity.

Primary sources:

- Federal Reserve FOMC statement:
  https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm
- U.S. Treasury daily rates:
  https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve
- BEA June 2026 Personal Income and Outlays:
  https://www.bea.gov/news/2026/personal-income-and-outlays-june-2026
- BLS public data API and August 2026 release calendar:
  https://www.bls.gov/developers/
  https://www.bls.gov/schedule/2026/08_sched.htm
- FRED high-yield OAS, VIX, and EIA WTI series:
  https://fred.stlouisfed.org/series/BAMLH0A0HYM2
  https://fred.stlouisfed.org/series/VIXCLS
  https://fred.stlouisfed.org/series/DCOILWTICO

## Scientific mapping

The router does not add macro points to any stock. It forms four equal-weight
families: market stress, liquidity stress, inflation stress, and labor stress.
Robust z-like values are transformed monotonically with `tanh(x/1.5)`, then
averaged. The raw current stress was `-0.022799`, which by itself would be a
very small risk-on tilt. The preregistered inflation guard was active because
observed CPI exceeded `2.5%`, so unvalidated risk-on expansion was suppressed
and the balanced neutral budget remained `60/25/15`.

Current family scores were:

| Family | Stress score |
|---|---:|
| Market | -0.274060 |
| Liquidity | +0.206854 |
| Inflation | -0.013837 |
| Labor | -0.010153 |

Negative is risk-supportive; positive is defensive. The mapping is frozen in
`docs/run287_macro_risk_budget_shadow_contract.json`. It was not optimized
against historical returns, and post-outcome threshold tuning is prohibited.

## Execution evidence

- Current macro packet:
  `H:\codex\run287_macro_sidecar_20260818_shadow_v2`
- Balanced shadow proposal:
  `H:\codex\run287_macro_risk_budget_shadow_20260818_balanced_v3`
- Router code commit:
  `4a987ee66b8c50af4ad9a0a8b2bda6ff405f5139`
- Macro-current SHA-256:
  `7653b3850134b037d620620ade4c976c2cf3882ddbb9aaeec6ba3f15e163d013`
- Proposal SHA-256:
  `d8fbea00f43e44968e0c77a3302ac8305ba5c1bf9b07a4f720d25bf80bb4614d`
- Source inputs mutated: `false`
- Stock ranking executed: `false`
- Target books written: `false`
- Orders generated: `false`
- Operating ledger mutated: `false`
- Fullrun executed: `false`
- Production/live trading enabled: `false`

Validation:

- focused macro router, current macro sidecar, scientific readiness, shared
  ledger, JSON, compilation, and diff checks: pass
- full local PR validation: `222/224` pass in `775.26s`
- the two failures are the unchanged Windows CRLF/LF byte-identity mismatch in
  the independently pinned OHLCV pattern-memory contract; the same issue was
  already present on PR #367 and is outside this causal change

## Performance boundary

The macro proposal executed, but historical performance validation did not.
The scientific weighting gate still reports `BLOCKED_DATA_READINESS` because
historical PIT universe/lifecycle truth is not clean, only one decision date is
materialized, zero dates have mature 63/126-session labels, quality/valuation/
growth-revision/13F components are missing, and event actual coverage is only
`74.6208%`. Overriding that gate would manufacture a backtest rather than
validate one.

The next legitimate performance step is to complete those PIT inputs, freeze
one independent macro replay that does not reuse rejected P3/P4 thresholds,
and compare it with equal weight and the accepted champion at 25/50/100 bps.
Until then this allocation is a shadow control and cannot be promoted.
