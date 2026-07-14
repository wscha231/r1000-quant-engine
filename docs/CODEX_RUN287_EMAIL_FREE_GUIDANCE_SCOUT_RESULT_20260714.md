# Run287 email-free SEC management-guidance scout result - 2026-07-14

## Decision

An exact accepted-time management-guidance history can be built without
emailing or buying from a data vendor. SEC EDGAR is the source: its public APIs
and filing archive require no login or API key, and the filing index supplies
the exact acceptance timestamp used as `available_from`.

The bounded scout passed document-discovery feasibility and may advance only to
manual schema review and deterministic guidance parsing. It did not join
returns, run an alpha screen, run portfolio A/B, mutate a book, run fullrun, or
activate production/live trading.

This free lane does **not** reconstruct historical analyst consensus. It is a
separate `management-guidance revision versus prior management guidance`
signal, and it does not replace or weaken the existing provider-neutral
consensus/guidance pair gate.

## Preregistered boundary

The exact no-repeat key is:

`sec_management_guidance_revision + accepted_time_source_screen_no_portfolio_mutation + run287_source_only + 2019-06-03_2026-07-10`

The preflight returned `ALLOWED_NEW_COMBINATION`. The machine-readable contract
is `docs/run287_sec_management_guidance_scout_contract.json`.

Candidate discovery requires, in one bounded text window:

- an explicit guidance/outlook or company/management expectation phrase;
- a registered financial metric;
- a numeric value or range;
- a future fiscal year or quarter reference.

Forward-looking-statement boilerplate alone is rejected. Candidate passages
remain untrusted until manual schema review.

## Actual zero-cost run

The first stage selected the first five ADR/global rows from the frozen 50-row
request and the next five domestic rows:

`NVS, YMM, SLF, CCJ, RIO, VZ, PHM, PG, TPL, RITM`

The existing accepted-time indexes initially covered 8 of 10 names and 3 of 5
ADR/global names. A bounded SEC submissions collection filled only the two
missing ADR routes:

- NVS: 125 rows (`6-K`, `20-F`, `20-F/A`) from 2019-06-07 through 2026-06-11;
- RIO: 212 rows (`6-K`, `20-F`, `20-F/A`) from 2019-06-03 through 2026-07-01.

The final scout inspected at most eight recent 8-K/6-K submissions per ticker:

- selected/indexed tickers: `10/10`;
- indexed ADR/global tickers: `5/5`;
- complete submissions downloaded: `80/80`;
- exact accepted-time coverage: `80/80` (`100%`);
- untrusted heuristic candidate filings: `17` across `5` tickers;
- candidate passage rows: `42`;
- status: `READY_FOR_MANUAL_SCHEMA_REVIEW`.

Heuristic candidate filing counts were:

| Ticker | Candidate filings | Registered metric evidence |
|---|---:|---|
| NVS | 3 | EPS, sales |
| PG | 4 | EPS, sales, margin |
| RIO | 1 | sales |
| VZ | 2 | EPS, EBITDA |
| YMM | 7 | revenue, capex |

SLF, CCJ, PHM, TPL, and RITM had no heuristic candidate in their
eight most recent eligible submissions. Missing remains neutral; absence in
this small scout is not a negative event.

## Post-run hardening audit

The 17 filings are discovery candidates, not 17 validated numeric guidance
events. Review found likely false positives from calendar years, qualitative
outlook text, physical-volume disclosures, one-time transaction effects, and
same-event republications. Same-metric and same-fiscal-period prior guidance
may reduce the number of pairable revision events much further.

The integrated scanner therefore fails closed when any bounded row lacks exact
acceptance or when the SEC complete-submission acceptance header disagrees with
the index. It no longer treats a calendar year alone as a numeric value and no
longer stops after the first three text windows.

The hardened v2 offline rerun reused the same cached documents and complete
indexes without a network call:

- indexed/scanned issuers: `10/10`, including ADR/global `5/5`;
- bounded submissions: `80/80`;
- exact index acceptance: `80/80`;
- raw SEC header acceptance match: `80/80`;
- missing or mismatched acceptance: `0`;
- heuristic candidate filings: `16` (`NVS 3, PG 4, RIO 1, VZ 2, YMM 6`);
- candidate passage windows: `73`, including overlaps and therefore not unique events;
- status: `READY_FOR_MANUAL_SCHEMA_REVIEW`.

The reduction from 17 to 16 candidate filings came from rejecting a year-only
qualitative YMM passage. No return label or portfolio result was consulted.

## What is and is not solved

Solved without vendor email or an API key:

- exact accepted-time event availability;
- append-only source documents and SHA-256 provenance;
- US 8-K and foreign-issuer 6-K coverage;
- current ADR identity for all five ADR sample names;
- a bounded set of real numeric guidance documents ready for parsing.

Not solved:

- historical analyst-consensus revisions;
- stable historical listing membership and complete symbol history;
- verified delisting returns or cash-merger proceeds;
- the five historical-delisted sample slots;
- 2019-2026 full-history guidance coverage for all 45 active sample names.

SEC filings can preserve inactive issuers and accepted-time disclosures, but
SEC alone is not an exchange-price or delisting-return database. Therefore this
run cannot pass the existing PIT+delisted+consensus provider gate.

## Other self-service routes checked

Alpha Vantage publicly documents `EARNINGS_ESTIMATES` with EPS/revenue,
analyst counts, and revision history, plus `LISTING_STATUS` with historical
active/delisted queries. It still requires an API key, its exact observation
availability semantics have not been proven by a returned sample, and the
repository contract pauses Alpha Vantage until the previously exposed key is
rotated. It was not called.

The existing FMP/Finnhub forward archive remains usable only from each fetch
date. The broad catch-up found true estimates for 13 of 863 names and cannot be
back-projected into 2019-2026.

## Cost-efficient next gate

Do not scan all issuer histories yet. First label all 80 inspected filings so
false-negative recall can be measured, and apply detailed schema labels to the
16 candidate filings. Then build an exact parser for:

- metric (`eps` or `revenue` first);
- fiscal period and period type;
- low, high, and midpoint;
- currency and unit;
- accepted-time source accession and hash;
- revision pairing against the prior management guidance for the same metric
  and fiscal period.

Expansion to all 45 active names is allowed only if the frozen 80-filing review
reaches at least 90% precision, at least 80% recall, and at least 80% registered
schema completeness for true EPS/revenue guidance. Raw-header PIT agreement
must remain 100%. Those thresholds must be checked before any return labels
are joined.

Only after the active-sample source screen passes may the fixed 63-session
primary outcome and 21/126/252/504-session direction checks run. Portfolio A/B
remains prohibited until that separate source screen passes.

## Evidence

- `docs/run287_sec_management_guidance_scout_contract.json`
- `tools/run_sec_management_guidance_scout.py`
- `tests/sec_management_guidance_scout_smoke.py`
- `outputs/run287_sec_guidance_foreign_gap_index_20260714/`
- `outputs/run287_sec_management_guidance_scout_20260714/`
- `outputs/run287_sec_management_guidance_scout_20260714_hardened_v2/`
