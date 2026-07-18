# Run287 PIT estimate/guidance provider cost screen - 2026-07-15

> Supersession note: the later GPT Pro P1 review raised the minimum from a
> 50-row schema sample to **50 unique securities plus at least 200 historical
> event rows**. The provider ranking below remains useful, but a 50-row result
> can now be only a diagnostic precursor. The controlling contract and result
> are `docs/run287_pit_estimate_guidance_sample_contract_v2.json` and
> `docs/CODEX_RUN287_PIT_ESTIMATE_GUIDANCE_SAMPLE_V2_RESULT_20260715.md`.

## Decision

Do not purchase or subscribe to a historical estimate/guidance feed yet.  The
public schemas reviewed below do not prove Run287's decisive requirements:
100% exact timezone-bearing `observed_at`/`available_from`, stable historical
security identity, delisted outcomes, ADR/global identity, and point-in-time
revision history. A paid plan is considered only after a zero-cost
50-security/200-event sample passes the frozen source-data gate.

## Provider ranking

### 1. Nasdaq Data Link ZACKS/EEH - bounded sample candidate only

Public metadata identifies the continuously updated premium estimates-history
table and a primary key containing `m_ticker, per_end_date, obs_date,
per_type`.  Actual entitled rows have not been observed.  The existing probe
makes at most two requests and retains at most 50 rows.  It made zero requests
locally because `NASDAQ_DATA_LINK_API_KEY` is absent.

Action: run the existing bounded probe only if an already-entitled key becomes
available.  Do not buy entitlement from metadata alone, and do not fabricate a
time from a date-only `obs_date`.

Official references:

- <https://data.nasdaq.com/databases/ZEEH/documentation?anchor=master-table-zacks-mt->
- <https://docs.data.nasdaq.com/docs/data-organization>

### 2. Intrinio Zacks estimates - free custom sample only

The official EPS endpoint exposes an Intrinio company ID, ticker, LEI, CIK,
fiscal period end date, estimate distribution, and 7/30/60/90-day-ago means.
The documented `date` is the fiscal period end date, not an exact observation
or availability timestamp.  The public response schema therefore cannot yet
satisfy the PIT gate.  Intrinio advertises 20+ years of EPS and sales estimate
history, but places estimate feeds in its Enterprise catalog; its current
Enterprise pricing starts at USD 1,250 per month.

Action: accept only a free 50-row export that adds the frozen exact-time,
security-lifecycle, delisted, and ADR fields.  Do not subscribe or request a
quote before that sample passes.

Official references:

- <https://docs.intrinio.com/documentation/web_api/get_zacks_eps_estimates_v2>
- <https://docs.intrinio.com/documentation/web_api/get_zacks_sales_estimates_v2>
- <https://intrinio.com/pricing>

### 3. Alpha Vantage - public schema insufficient; security pause remains

The official documentation says `EARNINGS_ESTIMATES` supplies annual and
quarterly EPS/revenue estimates, analyst counts, and revision history, but it
does not publish exact historical observation/availability fields or stable
security-history joins.  Its separate `LISTING_STATUS` endpoint can query
active or delisted US securities for historical dates after 2010-01-01; this
does not prove that estimate rows can be joined without ticker or survivorship
leakage.  The public demo request returned only a key-acquisition notice, so no
50-row schema was obtained.  Paid plans currently start at USD 49.99 per
month.

Action: do not spend on Alpha Vantage for this lane.  The repository's existing
Alpha Vantage use also remains paused until exposed-key rotation is confirmed.
Only after rotation may a bounded, secret-safe schema sample be considered.

Official references:

- <https://www.alphavantage.co/documentation/>
- <https://www.alphavantage.co/premium/>

### Closed or non-qualifying existing paths

- FMP historical earnings-calendar collection returned HTTP 402 for all 993
  universe names in successful collection run `29064427303`; current snapshots
  are forward-only and sparse.  Do not retry that historical endpoint.
- Finnhub historical estimate entitlement is unavailable under the tested key.
- SEC accepted-time filing quality failed the preregistered OOS source screen.
- The SEC management-guidance keyword scout failed its 90% precision gate.

## Cost-efficient order of work

1. Continue the already automated, bounded forward risk/outcome and estimate
   archives at no new data cost.
2. If an existing ZACKS/EEH entitlement appears, run exactly one 50-row probe.
3. Otherwise accept only a no-cost provider export against the frozen schema.
4. Join returns only after `READY_FOR_SOURCE_SCREEN`.
5. Open one fixed-book A/B only after a separate preregistered source screen
   passes full, OOS, and OOS2.  A successful fixed-book result is then required
   before a generated-book A/B.

No email, signup, purchase, return join, portfolio A/B, fullrun, production, or
live-trading action was performed in this review.
