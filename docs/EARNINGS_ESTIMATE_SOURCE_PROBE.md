# Registered estimate-source keys and bounded validation

This source-only probe connects the existing `FMP_API_KEY`, newly registered
`FMP_API_KEY2` and `EODHD_API_KEY` to explicitly selected sample requests. It
reuses the accepted H1 snapshot builder and existing FMP/JSON fetch functions;
it is not a second archive collector. The daily transaction and default vendor
order are unchanged. Its new manual `fmp_key_name` input/collector
`--fmp-key-name` argument permits explicit `FMP_API_KEY2` selection, with the
primary remaining the schedule/default and no missing-secondary fallback.
No Drive, overlay, ER, target, paper or consumer admission
is performed.

## Exact scope

- `fmp2` selects only `FMP_API_KEY2`; an absent or rejected secondary key never
  falls back to the primary. There is no quota pooling or key rotation.
- `fmp` selects only `FMP_API_KEY`. Both use the existing annual estimate request.
- `eodhd` selects `EODHD_API_KEY`, checks `GET /api/user` once, and requests only
  v1.1 `General,Earnings` for explicit simple US symbols. Annual and quarterly
  Trend estimates remain separate. History/Annual actuals are never consensus.
- Unknown economic identity, accounting basis, currency or share/ADR unit stays
  unknown. No identity is invented from a provider plan, security type or price.
- Ambiguous punctuation/numeric/global symbols require a separately approved
  mapping; the bounded sample rejects them instead of guessing or deleting
  securities from the canonical universe.

## Budget and access contract

Each invocation is capped at 24 source HTTP attempts, including EODHD's usage
query. The attached task also caps all invocations together at 24 attempts;
the coordinator must subtract recorded attempts before approving another run.
This script does not reserve a persistent budget across separate invocations.
There are zero retries and zero redirects. Reservations occur before network
access, including failures and timeouts; the report shows reserved upper bounds,
not an unverified provider invoice. Responses are limited to 4 MB. Proxy
environment variables are not inherited. The workflow uses the daily collector's
existing concurrency group, preventing concurrent collection/probe workers in
this repository from spending the same shared quota.

FMP requires a positive verified shared API-unit budget and a timezone-aware
verification timestamp within 15 minutes. Registration alone is insufficient.
EODHD requires a positive authorized budget and validated account counters.
Documented string counters are normalized from bounded ASCII digits; numeric
integers remain supported. Booleans, signs, decimals, whitespace, non-ASCII
digits, missing counters and values outside the allowed range are rejected.
Fundamentals costs 10 API calls per ticker, while `/api/user` costs zero. The
entire reported last-active-day counter is subtracted conservatively rather
than pretending it reset. Undated zero usage is accepted only when the reported
counter normalizes to exactly integer zero. Future/invalid dates and UTC-reset crossings
fail closed. Extra/bonus calls are excluded from the probe's quota calculation;
external account usage outside repository concurrency is not reserved by this
job. A free plan or 500 bonus calls does not prove Fundamentals entitlement.

FMP security-specific 402 failures remain separate from successful securities.
All other HTTP failures, local safety blocks and network/schema errors terminate
the sample with nonzero CLI status while retaining earlier parsed observations.
401/403 stop this one endpoint/account sample without trying another key. The
probe uses the accepted low-level fetch/parser so the collector's catch-all
recovery cannot hide a safety block. No provider is globally disabled or
reactivated by the probe.

## Outputs and approval

Only `outputs/earnings_estimate_source_probe/*.json` controlled diagnostics may
be written. Output admission precedes network access. Atomic replacement writes
a new inode instead of truncating an existing hard-linked report, preserving
any operational file sharing its old inode. The report includes
per-security EPS/revenue value-presence counts and unknown identity status, not
raw payloads, account profile details or consensus values. Normalized snapshots
exist only in memory; archival/storage rights and durable promotion remain
separate. A zero-valued EPS remains an explicit observation; missing remains
missing. `SAMPLE_PROBED` is an access diagnostic, not usable coverage, historical
PIT, consumer connection, full-universe completion or an investment approval.

The new workflow is manual-only and requires repository/master/exact-head
equality. Secret values are runner environment variables, not command arguments.
No operational secrets are injected. It uploads only the controlled report even
when access fails. Merging, review-complete signalling and dispatch require the
attached task's separate approval; none is performed by adding this code.

Example reviewed EODHD execution scope, after authorization: provider `eodhd`,
ticker `AAPL`, maximum 2 HTTP attempts, authorized budget 10 API units. The live
usage check must admit that budget before the data request. FMP examples need
fresh dashboard/account quota evidence; the old 60/250 screenshot is insufficient.

## Verification and reusable lesson

The source-probe tests are imported by the H1 smoke wrapper, which is explicitly
listed in `tools/run_pr_validation.py`'s `DEFAULT_TESTS`. The required PR workflow
therefore executes these regressions. Synthetic fixtures test new-key
selection, missing-key rejection, bounded failed requests, no fallback, mixed
FMP 402/success, EODHD quota/403, v1.1 annual-quarter separation, missingness,
unknown identity, unsafe output rejection and secret-free diagnostic reports.
Live registered-key validation and production data growth remain `NOT_RUN`
until an authorized exact-head execution supplies actual evidence.

The first offline run reproduced a mismatched H1 builder argument. The adapter
now uses the exact accepted signature and both provider paths are tested. Do not
confuse green workflow status, secret registration or a parsed sample with a
new current-usable estimate universe.

Official references:
- https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds
- https://eodhd.com/financial-apis/api-limits
- https://eodhd.com/financial-apis/user-api
- https://site.financialmodelingprep.com/developer/docs/pricing
