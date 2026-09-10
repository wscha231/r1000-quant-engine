# Real source connection for the USD 100,000 study

This connection begins on master `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
It collects research inputs without restoring or modifying an accepted ledger.
The requested investment study remains 7–8 years, after-cost USD CAGR first,
with stock selection, sales and cash decisions through the previous completed
close. Collection success is not a passing backtest or an investment target.

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
  --start 2018-05-01 --end 2026-09-09 --report /private/report.json
```

Every run needs a new private directory. Hashed raw responses and receipts must
stay private; the PR workflow uploads only the controlled aggregate report.
API keys, query strings, provider error bodies and raw market data do not enter
public artifacts. Failed data does not become a synthetic 100% cash allocation.

## Remaining fund integration gates

1. Date-indexed eligible securities and entity/action histories, including exits.
2. Original publication timestamps, actual later retrieval timestamps and a
   separately labelled archive reconstruction mode. Do not backdate retrieval.
3. Complete raw closes, actual action payment dates, benchmark total returns,
   cash rate and USD/KRW FX aligned with each decision and next-close execution.
4. Reviewed, dated quality evidence and valuation scenarios; today's judgments
   cannot be represented as judgments recorded in 2019.
5. Bind those inputs to the decision and USD fund manifests, run preflight and
   execute the chronological replay. Report CAGR, MDD, Sharpe, annual/monthly
   results, exposure, turnover, costs, attribution and final holdings.

Source references: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[Alpaca bars](https://docs.alpaca.markets/us/reference/stockbars),
[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html),
[Alpha Vantage listing status](https://www.alphavantage.co/documentation/#listing-status).
