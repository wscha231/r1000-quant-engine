# Public dashboard freshness incident — 2026-09-12

Default branch audited: `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.

The directly fetched public `data/dashboard.json` declares
`as_of_close=2026-07-10`, `generated_at_utc=2026-07-13T05:12:45+00:00`.
Never relabel this old snapshot September 11.

## Evidence

- [Daily run 34567855835](https://github.com/wscha231/r1000-quant-engine/actions/runs/34567855835),
  job `103163542997`, stops at `Restore verified risk-outcome accepted head`:
  `BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED`.
  The run selected paper session `2026-07-24`; its most recent completed
  NYSE session was `2026-09-10`. Prices, targets, paper transaction, accepted
  artifact, and persistence were skipped. This is run evidence, not an
  independent acceptance of the current Drive account.
- [Pages run 34570235185](https://github.com/wscha231/r1000-quant-engine/actions/runs/34570235185)
  was skipped because the daily producer failed.
- [Free data run 34664794782](https://github.com/wscha231/r1000-quant-engine/actions/runs/34664794782),
  job `103474431014`, fails during Drive synchronization with
  `unauthorized_client`.
- After-close artifact `10288116233`, run `34662298786`, was downloaded and
  its ZIP SHA256 verified as
  `012504cde5a5c96713245d8308e3f9f94e686b25d5399f8b2fdc29f6a70c222b`.
  Its tactical summary targets `2026-09-11` but declares `data_as_of=2026-08-24`.
  Its freshly built macro file has an unavailable SPY close. Neither proves
  September 11 portfolio performance.
- Pages sparse checkout omitted transitive imports of the publisher and its
  smoke test. The workflow now includes transitive root modules, tools and tests,
  plus calendar, parquet, and HTTP dependencies.

## Repair boundary

Independent price observations have their own schema and dates. They update
without advancing the account date or changing weights, trades, or metrics.
The last deployed portfolio is restored before static publication. Stale
account state gets a notice, and stale target deltas/proposals are hidden.

Account recovery still requires the migration-only contract, a freshly
verified durable parent, and chronological processing after July 24. No ledger
migration, catch-up, fullrun, target generation, or broker transaction was
executed for this website repair. Deployment and actual quote coverage must
be verified separately from offline tests and PR checks.

## Verified local results

- Yahoo daily raw closes were collected for all 15 distinct published holding
  tickers at the exact September 11, 2026 NYSE session; no missing ticker.
  Actual observations and response hashes are in public/data/market-quotes.json.
- Existing public dashboard smoke and the new quote contract smoke pass.
  A temporary checkout-shaped copy containing only workflow-listed source
  patterns also passes, resolving the transitive dependency failure.
- JavaScript runtime checks pass for separate price/account dates, stale banner,
  quote rows, suppressed stale proposals, duplicate rejection and null values.
- Shell syntax, JavaScript syntax and diff checks pass.
- Remote CI/review/deployment are separate gates; these results do not claim
  that the site or account has already been updated.
