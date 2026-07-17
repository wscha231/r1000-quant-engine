# Run287 durable-quality and trade-learning result (2026-07-17)

## Decision

The review-only durable-quality and buy/hold/sell learning layer is ready. It did not alter either portfolio, cash, score, rank, selector, model, or order path. Historical CAGR/MDD therefore remains unchanged.

The layer fixes two measurement errors before it searches for companies:

- total liabilities is no longer described as debt;
- a quantitative moat proxy is evidence for review, not proof of a business moat.

The selection context is frozen at the 2026-07-13 close with decision time `2026-07-14T05:00:00Z`. Holding risk uses the completed 2026-07-16 close. These dates must not be mixed into a claim that the candidate list is a 2026-07-16 rebalance recommendation.

## Exact accepted-time debt substrate

The SEC sidecar joins Companyfacts facts to the submissions index by accession and uses only exact `accepted_at == available_from <= decision_time`. It supports `10-Q`, `10-K`, `20-F`, `40-F`, and `6-K`, including amendments from their own acceptance times.

| Item | Result |
|---|---:|
| Universe | 989 |
| Exact-acceptance statement | 921 |
| Exact assets/cash/debt complete | 729 |
| Partial exact debt | 189 |
| Companyfacts archive member missing | 2 |
| Filed-date fallback | 0 |
| Future rows | 0 |

Missing debt remains missing and never becomes zero. A repeat run reuses an exact-complete row only if the SEC index contains no newer accepted statement for that issuer. The real incremental validation reused 723 names, refreshed 266, and finished in about 20 seconds; six previously complete issuers were deliberately refreshed because a newer accepted statement existed.

## Current durable-company review queue

The complete quantitative queue contains four securities but three companies because GOOG and GOOGL share one CIK.

| Company/security | Review score | Balance | Economic durability | Market confirmation | Debt/assets | Net debt/assets | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| GOOG / Alphabet | 0.397 | 0.177 | 0.580 | 0.386 | 0.113 | 0.059 | complete quantitative review |
| EXPE / Expedia | 0.370 | 0.519 | 0.342 | 0.218 | 0.169 | -0.040 | complete quantitative review |
| LIN / Linde | 0.277 | 0.061 | 0.325 | 0.489 | 0.286 | 0.240 | complete, leverage needs human review |

High-scoring partial names include MU, FTNT, FIX, AYI, NVDA, GNTX, and DECK. `partial` is not a weaker buy signal: it is a fail-closed data/evidence state. For example, MU has exact debt and strong quantitative values but lacks the current context's accepted fundamental timestamp required by the complete gate.

KGC, PLTR, MLI, SYK, PDD, YMM, FSLR, MCO, and RMD are examples of quality/market divergence. They are manual research candidates, not immediate buys, because current market confirmation is negative. ADR/foreign issuers remain subject to incomplete identity, home-listing, and historical-membership coverage.

Before any candidate can enter an A/B arm, a human must review accepted-time 10-K/20-F evidence for pricing power, switching costs, network/data advantages, cost leadership, IP/process advantages, customer concentration, cyclicality, and disruption risk. Quantitative scores alone cannot clear that gate.

## Current holdings: what the new layer says

- WDC and SNDK do not show a leverage crisis. WDC exact net debt/assets is about -3.1% and SNDK about -21.9%. Their current problem is concentration, cyclicality/economic durability, and price-risk damage.
- WDC is `ALERT`, SNDK is `WATCH`, and CIEN is `ALERT`. The checklist freezes incremental buying and requires manual review. It does not authorize an automatic sale.
- GOOG passes the complete quantitative company gate but is currently `ALERT`; therefore even a high-quality company is not automatically an add.
- Main names such as DTM, GLW, NXPI, TKR, WELL, and PR have materially more net debt than WDC/SNDK. The score routes balance-sheet concerns into review without pretending one universal leverage cutoff fits every sector.
- A price alert by itself never creates a sell. Sale/replacement requires an exact fundamental break plus a selector-qualified challenger and scheduled next-close execution.

This is intentionally asymmetric: new or incremental risk is blocked when evidence is missing, but an existing position is not dumped merely because the new sidecar is incomplete.

## Historical buy/sell answer notebook

The notebook reads the actual Google Drive Main trade journal rather than reconstructing trades from today's selected book.

| Item | Result |
|---|---:|
| Trades | 740 |
| Unique tickers | 338 |
| Entry range start | 2019-04-30 |
| Last exit | 2026-02-27 |
| Exit outcomes resolved | 723 |
| Good defensive exits versus SPY after exit | 446 |
| Possible premature-exit reviews | 277 |
| Wrong entries: holding loss and lagged SPY | 263 |

The strongest diagnosis is entry quality and churn, not a blanket rule to hold every winner longer:

- 317 positive-alpha entries earned mean holding alpha of +15.86%; 48.10% continued to beat SPY after exit, with mean post-exit excess of +2.28%.
- 263 wrong entries lost money and lagged SPY; only 25.20% later beat SPY and mean post-exit excess was -8.91%.
- One-period holds had a 51.36% wrong-entry rate, versus 34.14% for two-to-three periods, 19.01% for four-to-six, and 9.80% for seven-plus periods.
- Scheduled rebalances had a 27.12% wrong-entry rate, versus 51.36% for single-period holds.

These are descriptive cohorts. A stock outperforming after sale is only a `possible premature exit`, because the realized replacement portfolio return is not yet joined. No fixed checklist proposal met the evidence gate, so this run makes zero automatic rule changes.

## Fixed buy/hold/sell checklist

1. Verify completed-close and PIT timestamps; reject every future row.
2. Require exact debt/cash/assets for a new-buy promotion. Total-liabilities proxy or missing debt blocks promotion.
3. Require sufficient economic-durability coverage and sector-relative balance resilience.
4. Complete the accepted filing textual moat review; quantitative moat evidence is not proof.
5. Require market confirmation and a clear holding-risk state. `WATCH` or `ALERT` freezes incremental buying.
6. For an owned position, distinguish price damage from an exact fundamental break. Price damage alone is not an automatic sell.
7. A replacement must already satisfy the selector and must be evaluated against the actual sold position/replacement counterfactual at next close and costs.
8. Grade decisions at 63 sessions primarily and 21 sessions secondarily. A one-day result may update observation state but never the checklist.
9. Keep changes review-only until at least 26 distinct decision weeks, 200 resolved 63D outcomes, 50 tickers, nonnegative week-block bootstrap lower bound, positive 50 bps direction, and no ticker/week above 10% of the contribution.
10. Even after those gates, human approval is required; automatic retraining, checklist mutation, and champion promotion remain forbidden.

## Next highest-value work

The next task is not another threshold or immediate portfolio A/B. First join each historical exit to the actual replacement basket and compute replacement-relative 21/63/126D opportunity cost. In parallel, append structured accepted 10-K/20-F textual moat evidence for the company-deduplicated review queue.

Only after that evidence exists should one preregistered challenger be considered: retain or replace a proven winner when its durable-quality state remains intact and the challenger lacks a superior selector-plus-quality state. The current results do not authorize this arm yet.

## Evidence

- `docs/run287_durable_quality_learning_contract_v1.json`
- `tools/build_run287_exact_debt_snapshot.py`
- `tools/build_run287_durable_quality_learning.py`
- `tools/build_run287_historical_trade_answer_notebook.py`
- `outputs/run287_exact_debt_snapshot_20260717/`
- `outputs/run287_exact_debt_snapshot_20260717_incremental/`
- `outputs/run287_durable_quality_learning_20260717_close_20260716/`
- `outputs/run287_historical_trade_answer_notebook_20260717/`
