# Real source connection for the USD 100,000 study

This connection begins on master `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
It collects research inputs without restoring or modifying an accepted ledger.
The requested investment study remains 7–8 years, after-cost USD CAGR first,
with stock selection, sales and cash decisions through the previous completed
close. Collection success is not a passing backtest or an investment target.

## Active mandate: US listings, including foreign companies

On September 10 the user selected **US-only**, including TSM, ASML and similar
US-listed foreign securities. The default is now `--universe-mode us_listed`.
The pool is IWB equity members **union** the existing foreign-company seed
verified against the current SEC exchange map. This is a broad candidate pool,
not an exhaustive list of every US stock or ADR, and not a recommendation.
Seed market caps, listing-month guesses and speculative future watchlists do
not establish eligibility. OTC/unresolved entries are retained in private
exclusion diagnostics. Missing TSM/ASML or a source failure is reported explicitly.
Current SEC observations keep their actual retrieval time, not yesterday's date.

`docs/research_us_fund_config.json` sets US trading-market capacity to 100%, KR
to zero, and selection targets to five US securities and zero KR securities.
All securities and account cash must be USD. This mandate is about the listing
market, not issuer domicile: Taiwan/Netherlands and other business exposures
remain relevant. It does not require fully invested equities. Existing single
security, common-exposure, stress, liquidity, cost and regime cash limits remain.
The US workflow makes no KRX calls and requires no USD/KRW feed.

The shared checked-in core supports the US profile in both current decisions
and chronological fund replay. `tools/research_us_decision.py` and
`tools/research_us_fund_replay.py` enforce US scope and reuse the same financial,
quality, provenance and accounting implementation. The report identifies core,
entry-point and config hashes. Actual US next-close fills, cash and costs are
regression-tested; real source collection is still not a completed fund.
See [continuation and results](US_RESEARCH_CONTINUATION_20260910.md).

The current `us_listed` collector limits SEC financial collection to TSM and
ASML through `FOREIGN_REPORTING`; it does not collect fundamentals for the
whole price cohort. This is a scope defect, not merely a parsing priority or
evidence that other issuers' filings are unavailable. The
[September 11 financial-history audit](FINANCIAL_HISTORY_REUSE_AUDIT_20260911.md)
traces existing bulk/backfill collectors and defines the replacement with an
all-issuer inventory plus filing-driven updates. That replacement is not yet
implemented. TSM/ASML parsing uses native TWD/IFRS and EUR/US GAAP respectively.
Six-K facts are accepted only when actually present
and filed by the cutoff. Older annual values stay explicitly annual; they are
not relabelled current TTM. US share/ADS ratios, reporting-currency conversion,
dividend withholding and depositary fees still require dated reconciliation.
No company-total native-currency metric is used as USD per-share value.
Company review notes: [US foreign candidates](US_FOREIGN_CANDIDATES_20260910.md).

## Current sources

| Input | Source | What collection alone does not establish |
|---|---|---|
| US raw and adjusted daily bars | Alpaca SIP, paginated and end-date checked | Action cash flows, historical entity continuity, full daily coverage |
| Filed financial facts | SEC companyfacts plus submissions | Original filing acceptance timing and normalized complete H1 packets |
| Macro first releases | FRED observations `output_type=4` | Intraday release timestamps and complete vintage coverage |
| Historical active/delisted reference | Alpha Vantage LISTING_STATUS with explicit date | Russell membership, stable issuer identities and the full eligible universe |
| Korean close | KRX, KRW | Historical prices, actions, FX and Korean financial packets |

The 24 US and nine KR names are the current research watchlist, not a historical
universe. They must not be used to claim an unbiased historical selection test.
The provider financial statement connector was also tested on September 10:
Financial Datasets returned a zero-credit account message rather than data.
Alpaca connector short bars worked; longer bar requests returned connector
internal errors. This REST path uses existing repository credentials and real
pagination, preserving those failure classifications.

## Run and inspect

```
python tests/research_source_connection_smoke.py
python tools/research_source_connection.py --private-dir /private/run-unique \
  --universe-mode us_listed --start 2025-05-01 --end 2026-09-09 \
  --historical-probe-date 2019-05-31 --report /private/report.json
```

Every run needs a new private directory. Hashed raw responses and receipts must
stay private; the PR workflow uploads only the controlled aggregate report.
API keys, query strings, provider error bodies and raw market data do not enter
public artifacts. Failed data does not become a synthetic 100% cash allocation.

## Candidate scope and the former 33-name sample

The former 24 US / nine KR set is exactly the `watchlist` in
`docs/run287_daily_research_monitor_contract.json`. It is an inherited theme
watchlist, with no recorded per-name quantitative selection thresholds, full
market comparison, historical membership or investment approval. It overweights
semiconductors, AI infrastructure, power, construction and resources. Its size
was a connection-test scope, not a limit on the strategy or a selected top 33.

`current_markets` is the earlier opt-in US/KR path. That collector reads all provider equity
members of the live IWB proxy and all KOSPI/KOSDAQ daily share records; there is
no theme whitelist or fallback to the sample. IWB is a broad US base, not all
US listings, exact index membership or an exhaustive ADR universe. Korean share
classes, SPACs, halted securities and missing quotes remain visible for later
eligibility review. A non-empty partial board is not complete market coverage.

US bars use every resolved source member plus SPY, in batches with independent
pagination. The current collection window supplies 20/60/120/240-session price
inputs for broad discovery; it does **not** change the intended June 3, 2019
fund investment start or claim a shorter backtest as the requested study.
Reviewed official interim tables now normalize TSM/ASML through Q2 2026 for
current research. Broad company normalization and historical underwriting
remain incomplete. The all-candidate RS continuation reuses captures and
collects the missing earlier window for 504-session discovery, reconciling
overlapping raw prices and adjusted-price scaling before joining it.
The current broad-source job only requests those two issuers' SEC data; its
price coverage must not be reported as broad financial-history coverage.

To reproduce the connection sample, explicitly pass
`--universe-mode connection_sample --start 2018-05-01`; the report carries the
monitor-file hash and states that no quantitative sample-selection rule exists.

`universe_snapshots.json` privately retains member records and references to
original source receipts, with actual dates and current/past snapshots separate.
Historical KRX probe dates never get unioned into the current pool. A 2019 US
listing request is audited for IPO-after-request, delisted-before-request and
status contradictions. Passing those checks alone does not certify historical
completeness, stable entity history or contemporaneous publication timing.
IWB's reported date is never replaced by the requested date. Current membership
must not be used to select the historical fund. Two probe dates are not a
continuous seven-year membership series.

Public artifacts report counts, dates, sectors, exclusions and failure classes;
the full broad inventory, quotes and per-company admission diagnostics remain
private. Source selection, quantitative discovery, qualitative investment
approval and final allocation are distinct stages.

References: [IWB provider download](https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv),
[KRX services](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd).

## Remaining fund integration gates

1. Date-indexed eligible securities and entity/action histories, including exits.
2. Original publication timestamps, actual later retrieval timestamps and a
   separately labelled archive reconstruction mode. Do not backdate retrieval.
3. Complete raw closes, actual action payment dates, benchmark total returns,
   cash rate and foreign-issuer reporting currency/ADS basis aligned with each
   decision and next-close execution. USD/KRW is outside the US-only mandate.
4. Reviewed, dated quality evidence and valuation scenarios; today's judgments
   cannot be represented as judgments recorded in 2019.
5. Bind those inputs to the decision and USD fund manifests, run preflight and
   execute the chronological replay. Report CAGR, MDD, Sharpe, annual/monthly
   results, exposure, turnover, costs, attribution and final holdings.

Source references: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[Alpaca bars](https://docs.alpaca.markets/us/reference/stockbars),
[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[Alpha Vantage listing status](https://www.alphavantage.co/documentation/#listing-status).


## First actual collection and follow-up

- Source head: `23ef3700979c79b1dce1dfce33f9e6702e38c2f2`.
- [Run 34486807630](https://github.com/wscha231/r1000-quant-engine/actions/runs/34486807630),
  job `102903057383`, completed successfully on 2026-09-10 at 14:10:35 UTC.
- 49,968 US raw daily rows plus the same adjusted-row count across 24 watchlist
  securities and SPY. All 25 have a 2026-09-09 bar. Requested history begins
  2018-05-01; IPO/spin-off histories begin later and are not backfilled.
- SEC facts and submissions obtained for all 24 US issuers. These are raw
  sources, not 24 complete normalized financial packets. Initial parsing could
  select a discontinued tag (NVDA revenue, among others); the follow-up parser
  evaluates equivalent tags independently and discards stale TTM observations.
- Nine Korean closes obtained from 943 KRX daily records for 2026-09-09.
- UNRATE: 100 initial-release records, 99 numeric. DGS3MO/DGS2/DGS10 returned
  HTTP 400 for the wide vintage window. Alpha Vantage listing parsing failed.
  Neither input is represented as complete. Follow-up bounds the vintage
  requests and emits controlled response-shape diagnostics.
- 63 raw-source receipts; canonical receipts SHA-256:
  `b28ad71d5e168c531a162dabb5796c6fa2f52041c14b4f7691435f1dbdfadae7`.
- Private snapshot `34486807630-1-23ef3700979c79b1dce1dfce33f9e6702e38c2f2`
  uploaded under the isolated research prefix and byte-checked successfully.

The follow-up also queries actual corporate-action records and runs source
observations through the real H1/H2 admission code pinned to PR #409 commit
`3eb068e76d676ec3fc75288b645db8448615aa2d`. Its package/config digest is checked
before import. This is an admission probe: it preserves missing complete
financials, reviewed thesis/risk/scenarios, FX and official-close/action
reconciliation. It cannot silently manufacture an investable packet.

The USD engine's 31 synthetic accounting/chronology regressions passed locally
again against that exact source tree. Those tests include next-close fills,
whole shares, costs, unpaid dividend rights, splits, cash delistings, cross-market
cash timing and future-information perturbation. They are not actual returns.

Current study outputs remain `metrics=null` and `portfolio_weights=null` until
the real input gates pass. No hand-selected seven-name allocation is relabelled
as an engine result. The intended investment start is 2019-06-03, with earlier
price warm-up data and a new $100,000 continuous USD account, through 2026-09-09.


## Second actual run: connected admission remains blocked

[Run34488760178](https://github.com/wscha231/r1000-quant-engine/actions/runs/34488760178)
completed on 2026-09-10 at 14:29:46 UTC using source head
`55bc6ba989311f27e621d636ef9333171a605e07` and pinned PR409 engine source.

- The bounded FRED requests succeeded: DGS3MO/DGS2/DGS10 each returned 2,181
  dated records through 2026-09-08; UNRATE returned 100 through August2026.
  Counts include explicit missing values. Original intraday release timing is
  still a separate gate.
- Corporate actions: 566 cash dividends, 2 cash mergers, 8 forward splits,
  3 name changes, 2 spin-offs, 2 stock-and-cash mergers and 4 stock mergers.
  Several cash payment dates are absent (NVDA7, EME7, SPY6); unsupported merger
  and spin-off accounting also needs treatment before a full replay.
- Real H1/H2 call completed over 33 current research securities: admitted0,
  valuation0, quality eligible0, portfolio ready=false. Weights and performance
  metrics are null. The function call succeeding does not make the inputs ready.
- Complete financial packets, official-close/action reconciliation, thesis,
  exposure/stress and scenarios remain missing or unverified per security.
  FX and a verified regime context are also absent from this admission probe.
- 98 source receipts, SHA-256
  `00031cb6bdeb7132690b5b4c496bffef32fa82157e2ca60f27375c3f5781c9ab`.
- This run's private persistence did NOT verify. Its success conclusion only
  means the diagnostic job finished; the previous run's verified snapshot is
  separate. The follow-up reports failure stage/size, preserves successful
  active-listing collection when delisted parsing fails, and gives the private
  immutable copy ten minutes plus a separate five-minute byte-check budget.
