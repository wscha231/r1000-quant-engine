# Run287 daily ETF rotation and A3 review

The existing scheduled After-Close job reuses its Yahoo ETF history for overlap.
For the remaining symbols and uncovered windows it calls the existing batch
downloader for the shortest required date range, and only uses adjusted USD
closes. The old ETF snapshot retains its prior date boundary and output. Manual
After-Close runs do not activate the new research collection.

The monitor's configured scope is 3 comparison ETFs, 11 sector ETFs, 28 theme
ETFs, and the existing US stock watchlist. SPY is the primary benchmark; QQQ
and RSP are comparison context. Each horizon (1, 5, 20) divides the symbol's
gross return by SPY's over the same exchange dates. A prior-session comparison
requires 22 consecutive NYSE closes. No forward fill, calendar-day
substitution or earlier successful run can complete a missing window.
Sector, theme, and stock ranks use a separate fixed cohort for each, with 5-day
relative strength first and 20-day strength as the tie-break. Partial cohorts
retain observed relative strength and withhold rank changes.

A top-fifth entry/exit or a crossing into +/-0.25% five-session relative
strength requests review. For a stock, its own change or a change against or
in its explicitly named reference ETF can request A3 review. The reference is
comparison context; it asserts no holding, exposure or security identity.
Each stock/session has one stable request ID for deduplication. The request
uses the existing PRICE/LEADERSHIP review slices (RS, timing, valuation, ER).
A3 still requires verified security identity, current A1 evidence and relevant
A2/A4 evidence. Nothing dispatches a worker or completes a company assessment.

The public Actions receipt contains scope counts, session, exact run/attempt,
hashes and review status. Prices, relative strengths and detailed requests
remain in the existing private research Drive namespace, under
"etf-rotation-v1/objects/<private_payload_sha256>". Immutable upload and
readback precede ready status. A3 resolves that exact object and uses
"decode_a3_review_requests(observation, raw, contract)" to verify the package
before using its requests. The existing daily "research_queue.csv" includes
the batch status and exact private hash for US rows, linking the watch queue
to this A3 review input. The report's "observations.etf_rotation" binds its
run, attempt, clocks and counts. When private delivery fails, the monitor reports it
separately from price coverage. A later Paper failure does not invalidate the
verified research receipt and remains a failure in its own report.

These are forward research observations. They do not establish historical PIT,
Source admission, accepted Registry state, expected returns or trading authority.
