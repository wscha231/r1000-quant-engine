## Native library-only adoption — 2026-10-05

Only tools/eodhd_calendar_trends.py and its 53 durable parser/H1 library cases
are adopted as pure metadata dependencies of the SEC-first core. The native
probe, KEY_NAMES, workflow, credentials and collector are unchanged. The 23
parent probe cases and three workflow cases are explicitly unadopted activation
boundaries; they are not skipped native tests or prerequisites for free SEC core.
Native registration uses tests/eodhd_calendar_trends_library_smoke.py through
the existing H1 wrapper. The original proposal below describes a broader parent
package: its manual sample, provider choice, transport and workflow instructions
are not installed or authorized by this library-only adoption. No purchase,
provider request, entitlement or collected-value claim follows from this code.

# EODHD Calendar Trends V1 — isolated H1 source adapter

Task: R1000-H1-EODHD-CALENDAR-TRENDS-V1-20261004
Repository: wscha231/r1000-quant-engine
Audited base: 6129f16b3d09cb7367b0a25f126a5ec28f905ff7 (merged #575)
Revision: C1 — shared-package reconciliation and bounded semantic correction
Status: LOCAL_CORRECTED_TESTED / NATIVE_APPLY_AND_REVIEW_REQUIRED
Scope: H1 / source sample only. This document grants no runtime or financial authority.

## What changes

`tools/eodhd_calendar_trends.py` parses the documented Calendar endpoint, separate
from the existing EODHD Fundamentals route. The existing manual source probe gains
an explicit `eodhd_calendar` choice using only `EODHD_API_KEY`. Default provider
remains fmp2 and default verified API budget remains zero. No scheduler is added.
The operational earnings collector, H1 contract, queue, accepted archive, ranking,
ER, portfolio, ledger and protected validation runner are unchanged.

## Data semantics

The response must have type Trends, an exact echoed symbol set, and one nested
trends group per echoed symbol. Every row must explicitly match that group's code.
Echo order may differ from request order; request order is retained in output.
Missing, duplicate, extra or cross-symbol records fail closed. Empty groups are
reported as no estimate observation, never usable coverage.

Each row's ISO date remains its fiscal window anchor. `0q` / `+1q` are QUARTERLY;
`0y` / `+1y` are ANNUAL. They are not proof of an independently verified issuer
fiscal calendar. Historical fiscal windows do not become historical snapshots.
Actuals/year-ago fields are not consensus. Per-security identity, accounting basis,
currency, share/ADR unit and provider publication precision stay unknown if absent.
No issuer/security metadata is broadcast from a batch envelope. Simple US symbols
only are admitted in this slice; punctuation/ADR mappings need a later reviewed map.

EPS and revenue avg/low/high/counts are normalized for the existing H1 builder.
Missing and malformed numeric values do not become zero; explicit zero is kept.
Nonfinite JSON, duplicate JSON keys, excessive payloads, inconsistent ranges,
duplicate fiscal identities and malformed dates are rejected. No source mutation
or network access occurs in the parser.

Embedded EPS current/7/30/60/90-day values and up/down counts are retained in a
separate in-memory vendor-observation structure with per-field raw/value/status.
They are provider-reported lookbacks, not independently captured historical
vintages and not an admitted analyst-breadth signal. Their anchor remains
UNVERIFIED_PROVIDER_ANCHOR. They are not inserted as extra columns in the existing
H1 snapshot, which intentionally rejects unknown non-null fields.

The existing full H1 builder and persisted validator are used unchanged. Collection
completion is the first-seen lower bound. Fiscal dates never become publication
clocks; date-only publication metadata remains imprecise. Even complete identity
fields are not independent source authentication or an investment approval.
All results remain h2_eligible=false and historical_pit_certified=false.

## Bounded manual sample

The live path supports at most three explicitly named symbols. It makes one
`/api/user` quota read followed by at most one `/api/calendar/trends` batch.
Budget is reserved before each HTTP attempt. The Calendar data request consumes
one documented API unit; the quota request uses zero units. Two HTTP requests are
needed. No retries, redirects, bonus allowance, key rotation, provider fallback,
or hidden Fundamentals requests are permitted. UTC reset/clock reversal blocks.
The existing shared collector/probe concurrency group remains unchanged.

The first response can establish quota only, not paid Calendar entitlement.
The second request tests endpoint access. Responses are bounded to 4 MB and no
raw financial values, raw responses, secrets or account profiles are persisted.
Only count/status/hash diagnostics are written to the existing probe output path.
All groups must validate before a sample is reported as parsed. No sample may
publish to accepted research_state or the operational earnings archive.

## Tests and native registration

`tests/eodhd_calendar_trends_smoke.py` contains 79 tests (64 original + 15 corrections) across parser/H1, mocked
transport and actual workflow structure. In the native repository, import these
classes alongside SourceProbeTests at the bottom of the existing registered H1
smoke wrapper (tests/earnings_consensus_h1_smoke.py):

```python
from tests.eodhd_calendar_trends_smoke import (
    CalendarTrendsTests, CalendarProbeTests, CalendarWorkflowTests,
)
```

Do not replace existing imports. Do not modify tools/run_pr_validation.py or
protected publication pins for this registration. The handoff package contains
the code patch and this exact insertion instruction, but does not claim the full
native wrapper was applied or the full required CI was run in the scratch host.

Native validation after scoped apply:

```bash
python -B tests/eodhd_calendar_trends_smoke.py
python -O -B tests/eodhd_calendar_trends_smoke.py
python -B tests/earnings_consensus_h1_smoke.py
python -O -B tests/earnings_consensus_h1_smoke.py
git diff --check
```

Then run all required checks on the new commit. Previous 231/232, 232/232 or
233/233 results never substitute for new-head CI. Independent A6 and required
exact-head review remain separate. This author supplies neither independent A6
nor a review-complete signal. No automatic Codex invocation is included.

## Later use — not dispatched by this implementation

After native integration/review and separate authorization of a real sample,
select the existing Earnings Estimate Source Probe workflow with:

- provider: eodhd_calendar
- tickers: AAPL,MSFT,A (or another approved maximum-three simple-symbol sample)
- expected_head: actual reviewed, merged master SHA (never the old base by habit)
- max_http_requests: 2
- verified_api_units: 1
- EODHD_API_KEY: existing account token in Actions secrets, never chat/CLI/logs

The sample is not a rollout. Paid access, exact live response shape, per-field
freshness, broad-universe coverage, storage/retention and commercial redistribution
rights are not verified by synthetic tests. Do not buy or activate anything as a
side effect of applying this patch.

## Follow-on, not implemented here

1. Bind verified issuer/security/fiscal/basis/currency/share metadata to actual
   responses without inferring identity from ticker or plan name.
2. Measure actual endpoint/value/identity/freshness coverage on a diverse sample.
3. Propose one bounded operational-collector integration using the existing queue,
   transaction, generation manifest and immutable archive; do not create a second
   collector or parallel accepted store.
4. Design/review a versioned sidecar and consumer contract for vendor lookbacks.
   Record actual collected vintages from now onward; no backdated history.
5. Connect A2/A3/Registry only after source admission. ER/ranking/portfolio changes
   and economic testing remain a separate H2 task.

## Corrections to earlier chat expectations

SEC file presence is not proof of 20 continuous quarters or complete field-level
PIT. Legacy `60/993` observations are not certified current V2 usable coverage.
This code does not claim coverage growth. Batching 25/50 symbols and immediate
993-symbol collection are not approved or implemented in this initial sample.

## Official schema references inspected 2026-10-04

- https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits
- https://eodhd.com/financial-apis/api-limits
- https://eodhd.com/financial-apis/user-api
- https://eodhd.com/lp/calendar-and-news-api

Public documentation supplies schema and product descriptions, not account-specific
entitlement, independent PIT evidence or blanket rights to republish vendor data.


## C1 correction — 2026-10-04

The already-published parent ZIP was downloaded in full: 70,605 bytes; its SHA256
is e3049949020d02b25a2830f96aec80d775efa5221b5614828264427a80ba6548.
All 19 indexed member hashes and three exact base blobs matched. Its 64 tests
passed again in both modes, but four additional synthetic probes reproduced:
nonzero decimal underflow becoming EXPLICIT_ZERO, conflicting fiscal end ignored,
conflicting annual/quarterly metadata ignored, and is_estimate=false admitted.

C1 changes only this new adapter, its test module and this contract relative to
the shared parent. It uses exact decimal checks before float conversion (also
for counts), rejects JSON float underflow before loss of information, validates
redundant fiscal metadata, and rejects explicit actual/non-estimate classification.
Supplied metadata conflicts must not be silently replaced by the period label.

The shared probe and workflow are byte-identical to the shared parent; H1 is
byte-identical to master. Fifteen regressions are added within the same three
classes, so native H1 registration instructions do not change. Total 79 tests
pass in normal and -O Python with socket/request calls disabled. This is author
validation, not an independent A6 or full native CI.

Use implementation.patch from the pinned master OR correction_from_shared_v1.patch
when the parent patch is already locally applied. Never apply both blindly.
Check the current native diff/owner first. No native worktree was modified here.
