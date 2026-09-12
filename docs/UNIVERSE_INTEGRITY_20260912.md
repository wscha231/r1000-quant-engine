# [PROJECT_HANDOFF] Whole-universe integrity and financial coverage / 2026-09-12

## Decision and authority

RESEARCH_ONLY. No orders, broker-book changes, official targets, champion changes or production promotion. The earlier eight-stock/30%-cash proposal is not an approved target. A universe-wide comparison must precede a replacement portfolio.

Base master: `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
Issue: https://github.com/wscha231/r1000-quant-engine/issues/414
Source review used a locally edited, exact-hash verified bounded source snapshot, not a claimed full repository clone. Unmodified remote tree entries are preserved by Git data tree commits. Public-source snapshot artifact: 10287379096, SHA256 `5613f88b807bef26d934f46619095d81d208c7315100224a1f0de2ac30193eed`.

## Actual real-data collection completed

Run: https://github.com/wscha231/r1000-quant-engine/actions/runs/34663478663
Source commit: `d8362f4cc57c15ef8ad71e9301d154083fc1809d`.
The verify job, 14 financial fixtures and the full SEC/macro collection completed successfully. This is not a backtest and not the latest bridge-change CI.

| Coverage item | Count |
|---|---:|
| Requested securities | 1,118 |
| Requested distinct mapped CIKs | 1,106 |
| Securities with parsed SEC companyfacts | 1,115 |
| Current quarter usable under this generic mapper | 786 |
| Revenue YoY available, including some stale quarters | 989 |
| Revenue growth acceleration available, including some stale quarters | 831 |
| TTM CFO-minus-capex available | 574 |
| Macro series fetched | 8 |

All requested identities are retained: 1 missing CIK and 2 HTTP-404 companyfacts failures. Of the 1,115 collected securities, 216 have stale/incomplete quarters and 113 have unresolved quarterly/currency mapping. These are data/normalization states, NOT an investment rejection of those businesses. Q4 derived from annual-minus-nine-months, alternative capex tags, banks/insurers and foreign interim reporting require explicit adapters.

Financial cutoff: 2026-09-11 filed DATE; collected 2026-09-12T01:05:39Z. Exact filing acceptance timestamps are not certified.
Financial artifact: 10288561789, `whole-cohort-financials-d8362f4cc57c15ef8ad71e9301d154083fc1809d`.
ZIP SHA256: `0a53071b65e800544e98c4774d89eb740f0ae285664a2ed084aad60b86a912f3` independently verified after download.
Files: `coverage_summary.json`, `whole_cohort_financials.json`.

The input cohort is reused from PR412 artifact 10177609847 / run34541821739. Its ZIP SHA256 is `591cd0c10b2eb42e0b8ceeb7c1b6ec90f292d021f17d81119281d9c90a1c67e5`; `all_us_relative_strength.json` SHA256 is `4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4`.
Price date remains 2026-09-09, NOT 2026-09-11. RS240 is available for 1,100 names. Price adjustments and historical universe membership are not independently reconciled. 1,118 is the available cohort, not all US listings or a hard upper limit.

## H1 changes in this branch

`r1000_unified_universe.py` no longer creates $10B capitalization, forward PE from TTM PE, missing RS=0, missing percentile=0.5, uncalibrated model scores or fake sleeve confidence. A real observed zero remains zero. Supplied live price is retained.

Missing candidates remain in a separate inventory, including no-Finnhub names. Duplicate identities, upstream-ineligible rows and previous synthetic scores cannot be promoted as scored coverage. A themes fallback or fewer than 1,000 raw requested names fails explicitly rather than masquerading as the full universe. Partial compatible score exports fail before replacing the prior output, with a separate coverage receipt. Consumers still need their own stale-output gates; preserving an old file is not permission to trade it.

`tools/universe_integrity/financial_coverage.py` maps EVERY requested security to CIK, shares requests across classes, rate-limits public SEC GETs, preserves current filing-date and currency identities, detects conflicting fact versions, computes comparable revenue growth and annual+YTD-priorYTD flows, and retains missing reasons. It is an explicit one-off current coverage audit, not a scheduled production collector or a historical PIT engine.

Offline checks in the publishable patch: 14 financial + 13 bridge tests = 27. Full repository tests, independent review and exact-head CI remain separately required. The current benchmark/price collection draft was not published after the connector blocked its write; it is not included as implemented functionality. No attempt was made to bypass that block.

## Macro evidence

| Series | Observation date | Value |
|---|---|---:|
| DGS2 | 2026-09-10 | 4.56 |
| DGS10 | 2026-09-10 | 4.95 |
| DFII10 | 2026-09-10 | 2.55 |
| T10YIE | 2026-09-11 | 2.36 |
| BAMLH0A0HYM2 | 2026-09-10 | 2.70 |
| VIXCLS | 2026-09-10 | 17.84 |
| DCOILWTICO | 2026-09-09 | 97.26 |
| DTWEXBGS | 2026-09-04 | 118.0732 |

Sources: https://fred.stlouisfed.org/series/ followed by each series ID. All are context-only, selection weight zero; observation dates differ. Units depend on the series (yields/spread %, VIX index, WTI USD/bbl, broad dollar index). No causal alpha or official regime classification has been approved.

## Remaining blockers and next work

1. Reuse this entire 1,118-name coverage, not a new handpicked 8/32-name watchlist. Extend the eligible exchange-listed common/ADR universe with explicit identity/liquidity exclusions.
2. Fix the canonical historical pipeline regressions already recorded in PR412: future Q1 revisions affecting earlier Q2, and integer FSDS YYYYMMDD parsed as nanoseconds. This PR's current-date mapper does NOT silently fix that existing backtest engine.
3. Normalize outstanding quarterly/annual/IFRS and sector-specific metrics without treating missing CFO/capex as zero. Keep bank/insurance evaluation separate from industrial FCF filters.
4. Align latest completed-session prices, point-in-time earnings/guidance revisions, current share counts/ADR ratios and valuation. SEC facts alone are not analyst consensus estimates.
5. Preserve raw observations in an approved durable private store and use changed-accession incremental updates. This run retained raw only in runner temporary storage; derived artifacts exist, durable raw persistence is NOT verified. Do not call the existing Drive OAuth problem repaired.
6. Compare positive-cash-flow growth, early growth, quality compounders, recoveries and other approved lanes across the eligible universe. Add business/technical moat, industry/bottleneck and normalized-earnings review for finalists.
7. Only then estimate scenario/1-3-6-12-month rewards and downside, correlations, liquidity/costs and market risk to size positions. Cash is a residual of investable opportunity and risk constraints, not a pre-fixed 30%.

Do not publish optimal weights, CAGR35%, MDD25% compliance or strategy performance from these diagnostics. H2 selection/weight changes remain a separate experiment/PR. Preserve rejected experiments and do not merge any older PR without exact-head independent review.
