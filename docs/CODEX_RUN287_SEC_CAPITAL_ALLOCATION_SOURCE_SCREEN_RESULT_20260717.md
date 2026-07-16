# Run287 SEC capital-allocation source-screen result (2026-07-17)

## Decision

`REJECT_SOURCE_SCREEN`. Do not create a Main or Concentrated portfolio arm from this signal and do not tune its 1% materiality threshold.

This result is research-only. It does not change selection, holdings, target weights, cash, orders, fullrun, production, or live trading.

## Frozen signal

- Availability: Companyfacts `accn` joined to exact SEC submissions `accepted_at`; `filed` fallback forbidden.
- Positive action: common-share repurchase cash/value. Retirement facts confirm a repurchase but are not double-counted.
- Negative action: common-equity issuance proceeds plus convertible-debt and convertible-preferred proceeds.
- Intensity: annualized net action amount divided by contemporaneous market cap.
- Market cap: exact-available shares outstanding times the unadjusted close at the last completed NYSE session at or before acceptance.
- Return label: adjusted-close SPY excess return beginning at the first NYSE close strictly after acceptance.
- Classification: positive at `>= +1%`, negative at `<= -1%`, neutral otherwise. No grid was run.

## Data result

| Item | Result |
|---|---:|
| Exact SEC filing rows eligible | 115,185 |
| Capital-action event states | 21,893 |
| Issuers/tickers represented | 895 / 895 |
| History | 2018-01-04 to 2026-07-02 |
| Valid contemporaneous market cap | 80.99% |
| Invalid or missing market cap neutralized | 4,162 |
| Positive / negative / neutral | 9,914 / 1,418 / 10,561 |
| Repurchase / common issuance / convertible observations | 17,223 / 6,257 / 354 |

The initial real-data pass exposed invalid class-specific share contexts such as one or 100 shares. The final frozen run requires at least 100,000 shares and market cap between USD 1 million and USD 20 trillion. Rows outside that broad data-quality range are neutral; no later share value is backfilled.

## Primary 63-session result

All returns below are mean SPY excess returns. The spread is positive events minus negative events.

| Segment | Positive n | Negative n | Positive mean | Negative mean | Spread | Filing-week bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| Full | 9,485 | 1,385 | -0.31% | +0.58% | **-0.89%p** | [-2.79%, +0.91%] |
| OOS2 (2023-01-01+) | 4,990 | 567 | -2.04% | -0.40% | **-1.64%p** | [-4.71%, +1.20%] |
| OOS (2024-07-01+) | 2,915 | 332 | -2.00% | +0.22% | **-2.22%p** | [-7.06%, +1.62%] |

Power gates are satisfied, but full, OOS2, and OOS direction is negative and both OOS lower bounds are below zero. This is a directional rejection, not `UNDERPOWERED`.

## Diagnostic interpretation

- Repurchase-any 63D mean SPY excess return is -0.51% full, -2.17% OOS2, and -2.03% OOS.
- Common-issuance-any is -0.01% full, -1.28% OOS2, and -1.15% OOS.
- Convertible-any appears positive on the mean, but only 98 OOS rows have resolved 63D labels and the OOS2 median is negative. It was not a preregistered standalone signal and must not be mined after observing this result.
- The economic explanation is plausible but not promotion evidence: repurchases often occur in mature/expensive regimes, while issuance can finance value-creating growth. Direction alone is not sufficient alpha.

## Closure

The exact do-not-repeat key is:

`sec_capital_allocation_event+exact_accepted_market_cap_normalized_source_screen+single_source_sec_events+2018-01-04_2026-07-02`

Reopening requires at least five percentage points of genuine component coverage or a semantic change supported before outcome inspection. Renaming the signal, changing the 1% threshold, splitting the same rows after seeing returns, or inserting it directly into a portfolio does not qualify.

## Evidence hashes

- `capital_facts_accession_cache.parquet`: `a246d91336e3870257a25630b926bd971326eb8177e0c368baceda834e90cfcd`
- `sec_capital_allocation_events.parquet`: `f35882c738bc19d6213a91b4e9bac6b93a31e09c3c32c66a2e8766304156e753`
- `source_screen_event_returns.csv`: `16db9f38a48cef567adca016dbb7836ca2a5d51bc11f595a560423fcf4b656ea`
- `source_screen_summary.json`: `6a74f13ef409d874d1c9939660ddcf2ec342569e1e1da9ed29de232d729c32a0`
