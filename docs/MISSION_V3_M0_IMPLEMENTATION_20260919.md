# Mission v3 M0-A implementation — 2026-09-19

Refs: Issue #458, Issue #448 Mission v3. Audited base:
`90b55fe92f25236c663a71cad7ab9138da497919`.

## Implemented, not merely proposed

`research_only/mission_v3/mission_metrics.py` implements the numeric precheck
specified in Issue #458 comments 5739373724 and 5739377845. The original
23 unittest methods were reconstructed and executed before changes. The
committed suite includes 24 additional methods (47 unique methods total).
All generated calendars and NAVs are synthetic, never investment evidence.

The scope is intentionally M0-A only: measure a **supplied** NAV series and
check pairwise declared contracts. There is no new investment strategy,
accounting engine, historical backtest, or production gate replacement.
M0-B evidence admission, M1 shared accounting and M2 PIT remain separate work.

## Reference research contract

`contracts/mission_v3.research.json` exactly matches the read-only code mapping:
- Main net CAGR >= 35%, MDD loss <= 20%.
- Concentrated net CAGR >= 50%, MDD loss <= 25%.
- Reference window 2018-09-17 through 2026-09-16, USD 100,000 per independent book.
- First NAV row is a start-of-measurement anchor. Its NAV equals initial capital.
- No external cash flows. Flow-bearing accounts require a separate TWR engine.

These are reference research inputs, not an assertion that an eight-year
dataset exists or authorization to execute a strategy. Existing operating
settings, targets and historical experiments are not rewritten.

## Calculation and admission boundaries

CAGR uses `365.2425 / elapsed_calendar_days`, not observation_count / 12.
Drawdown includes initial capital and every supplied NAV, including the first
loss after the anchor. Zero NAV is total loss, not missing. In this reference
contract a zero-NAV account cannot revive without external flow; late recoveries
or unpriced receivables require the accounting engine, not an invented value.

No missing/invalid/duplicate/out-of-order NAV is filled with zero or silently
dropped. The supplied date grid and both NAV date arrays must match exactly.
Both books declare the same run, source, kernel, data release, execution and
cost identities; each portfolio may have its own portfolio-policy hash.
Hash syntax and matching strings do NOT establish authentic source bytes.

A declared DAILY_EOD_LEDGER and even a caller-supplied two-point grid can lie.
M0-A cannot authenticate them. Every successful result therefore retains all
seven unverified evidence domains, `mission_status=NOT_PROVEN`,
`orders_allowed=false`, `production_promotion_allowed=false`, and
`calendar_and_accounting_authenticated=false`.

`numeric_status` is only METRIC_FAIL or METRIC_PASS_UNVERIFIED. Invalid input
returns INVALID_INPUT from the CLI. No HISTORICAL_REVIEW_ELIGIBLE status exists
here. Do not use exit code zero as investment approval.

NAV must ALREADY be net of the declared costs. This module cannot establish
that fills, spread, impact, fees, dividends, cash interest or corporate actions
were accounted for. No double-count or actual price provenance claim is made.

## Hardening beyond the unexecuted draft

- A caller's Decimal precision/rounding/traps/exponent limits cannot alter or
  crash ordinary calculation: each calculation uses its own fixed Context.
- Boolean, underscore/Unicode numeric text, excessive number length and extreme
  exponents are rejected. Explicit zero remains valid.
- Strict JSON rejects duplicate keys, nonstandard constants, oversized inputs
  and nesting deeper than 64 (string contents are not nesting).
- Threshold mapping is read-only; the JSON contract is checked against it.
- Output carries a detached copy of declared metadata, clearly not a receipt.
- CLI invalid inputs are controlled JSON errors; no inputs or outputs are written.

The first extended local run was 44 passes / 1 failure: deep JSON did not exceed
this interpreter's recursion limit. The fix is an explicit pre-decoding depth
bound, not weakening the test. Two string/depth-limit regressions were added.
The original failure log is kept with the private handoff evidence.

## Run and test

From repository root:

```sh
python research_only/mission_v3/mission_metrics.py /path/to/pair_bundle.json
python -m unittest discover -s tests -p 'mission_v3_*test.py' -v
python -O -m unittest discover -s tests -p 'mission_v3_*test.py' -v
```

The bundle has exact keys `contract`, `sessions`, `portfolios`. Each portfolio
has exact keys `metadata`, `nav_rows`; each NAV row has `date`, `nav`,
`external_flow`. See the original specification in Issue #458 and the synthetic
fixture factory in `tests/mission_v3_metrics_test.py` for the exact layout.

A zero CLI exit code means successful numeric processing, even for METRIC_FAIL.
Exit 2 means invalid input. Consumers must read the status and authority fields.

Tests use the standard library only. The new read-only PR/manual workflow runs
Python 3.11/3.13, normal and optimized. No schedule, secret, vendor call,
accepted-state write or protected validation file is changed. Dedicated CI does
not replace full repository CI or independent exact-head review.

## Next actual integration gate

M0-B must bind an independently expected manifest hash to exact calendar,
NAV, raw source and policy bytes. It must validate provenance and producer
receipts separately from transport integrity. Even perfect hashes do not prove
that data is PIT, fills are real, or an outcome was not used in selection.
Existing account_evaluation will receive a parallel reviewed reader, never a
silent replacement of old results with a new certification label.

M1 should reuse the existing broker-ledger/cost/reserve code with six golden
fixtures (first loss, drifted-weight costs, integer shares/cash, split/dividend,
partial fills, restart) before claiming replay/forward parity. M2 separately
repairs financial PIT and the canonical universe/collector path. No new alpha
module or legacy-score reuse is hidden in this metric slice.

## Source publication and limits

Development used an approved isolated local Git workspace. Container DNS
blocked native GitHub clone/push. Connected Git-data publication, if completed,
must preserve the audited base tree and reproduce every locally committed blob.
This is not a reconstruction of the user's original PC or a full source checkout.
Local results, remote CI, review, merge and real economic operation are separate.
Shared lesson: executing the numeric test suite is necessary, but it cannot
certify calendar, ledger, costs, PIT or trading performance.
