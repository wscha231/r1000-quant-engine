## Native library-only adoption — 2026-10-05

The original full library and source register are adopted with 78 unchanged
library-boundary cases in tests/free_market_context_library_smoke.py. Seventeen
parent CLI/transport cases and the parent runner are explicitly unadopted;
the CLI instructions below remain author-package reference, not native commands.
All adopted cases register through the accepted H1 wrapper; the existing full
#388 helper and H1 implementation are reused without dependency fixtures.
No capture, provider HTTP, scheduler or archive publication is activated.
Licensed supplied Cboe/AAII, CFTC/FINRA and price context remain report-only,
current-vintage inputs. Native source identity, currentness and PIT admission
are separate from parser and in-memory compatibility.

# Free market context V1 — source observations beside Calendar C1

Task: `R1000-H1-FREE-MARKET-CONTEXT-V1-20261004`  
Base inspected: `6129f16b3d09cb7367b0a25f126a5ec28f905ff7`  
Classification: **H1 / local implementation candidate / REPORT_ONLY**

## What this implements

The new module adds CFTC TFF/disaggregated futures-only and FINRA CNMS parsers,
bounded opt-in public GET preparation, authorized Cboe and AAII CSV importers,
as-of/freshness diagnostics, and a paired price/earnings-expectations research
context. It does NOT implement a new market-state engine or modify any portfolio.
The source register is `docs/free_market_context_sources_v1.json`.

`price_theme_context` imports the existing PR388
`tools.build_run287_chameleon_macro_inputs.compute_universe_components`.
MA50/MA200, historical close-high/low proxy, dollar-turnover ratio, volatility
breadth and correlation calculations are reused. Additional outputs are MA20,
advancers/decliners/unchanged, missing-return count and median daily return.
The existing FRED/macro collectors, theme membership sources, 13F and Form4
are unchanged. This package does not certify their current data completeness.

## #450 integration boundary

`calendar_theme_context` calls the exact shared C1 `build_h1_batch` and H1
normalizer in memory. No C1 file is edited. It keeps provider EPS current vs
30-day lookback diagnostics separate from our own collected-vintage revisions.
A fraction of **symbols** with increasing provider values is not analyst
revision breadth. Negative/zero old EPS, missing fields and overflow have no
percentage change. Fiscal windows ending before collection are excluded.
Other C1 EPS/revenue fields remain in C1's upstream schema: this V1 paired
context focuses on EPS lookback breadth, not a new revenue revision model.

`compose_research_context` pairs a theme's price participation with Calendar
context only for explicitly mapped, identical member sets and the requested
price session. It carries CFTC/FINRA/survey context as separate sections, not
independent votes for the same stock. Mapping is caller supplied, versioned
by content hash and time, not independently authenticated security identity.
Neither high breadth nor option put/call generates BUY, SELL, ER, ranks, new
regime state, weights or entry/exit rules.

**C1 is presently a shared local package, not an accepted runtime feed. Its
published source probe contains diagnostic counts, not archived estimates or
raw response values.** This new code consumes an explicitly supplied licensed
raw response or a future reviewed in-memory capture hook; it cannot manufacture
values from an existing C1 diagnostic report. Native runtime capture/retention,
source admission and downstream economic consumption remain separate tasks.

## Source semantics and limits

| Source | Implemented | Boundaries |
|---|---|---|
| CFTC TFF/disaggregated | Futures-only CSV/JSON parsing; net contracts and net/OI for each class; explicit opt-in GET | Report-date is not publication-time. PRE response schema/endpoint live success remains unverified here. Recent 21 calendar days, one 5,000-row bounded query; reaching row cap blocks rather than claiming completeness. No long-history pagination. |
| FINRA CNMS | Pipe-file with row-count trailer; short fraction; per-symbol source record; opt-in GET | ShortVolume includes ShortExemptVolume already. Denominator is reported FINRA facility volume, not entire US market. Not short interest, buyer/seller intent, retail flow or institution flow. CNMS and component venue files must never be summed. |
| Cboe | Authorized legacy DATE/CALL/PUT/TOTAL/P-C CSV, separate EQUITY/INDEX/TOTAL | Import only. Some legacy histories are stale. Website availability is not an approved current API or redistribution license. |
| AAII | Authorized standardized CSV with explicit percent/fraction | Import only; not a subscription bypass. Survey sentiment is not investment positions. |
| Existing price cache | Explicit full session grid, expected universe, caller theme membership; native helper reuse | Current-cohort diagnostic, not historical index membership. Session grid supplied by caller must come from admitted native exchange calendar. Missing names remain in denominators; no filling prices or manufacturing sessions. |
| EODHD C1 | Reuse existing bounded parser and H1; EPS theme observations | No additional EODHD HTTP, credentials, purchase, archive or activation. Vendor lookback remains unverified historical-vintage metadata. |

Legacy macro helper `new_high_minus_new_low` uses closing levels and a
252-row rolling window with 200 observations minimum; it is not a guaranteed
full-252-session intraday annual-high/low count. `index_concentration` is the
existing **dollar-volume concentration proxy**, not market-cap concentration.
Dollar-volume metrics require separately supplied unadjusted turnover prices;
no adjustment of share volume is guessed. Without turnover prices these
metrics remain null. Historical current-cohort membership stays non-PIT.

The scalar parsers reject booleans, nonfinite numbers, underflow and fractional
counts. CSV truncation, duplicate keys, inconsistent units, missing timestamps,
conflicting aliases and duplicate market/period records fail closed.
As-of views exclude future collections. New null evidence does not recover an
old favorable observation. Stale values are returned with `current_value=null`.

## Availability and data retention

For free public downloads, `available_at=collected_at`; original publication
is null. This is conservative prospective visibility, not a reconstruction of
what was known on an old Tuesday or trade date. For local imports the time is
caller-attested and explicitly not verified. A source hash authenticates
bytes, not original publication or an economic classification.

Capture is default-off. Only CFTC public PRE and FINRA CNMS are allowlisted.
One HTTP request per invocation, timeout 5/20 seconds, no redirects, no retries,
no environment proxies, no keys, no paid fallback, <=8 MB response; account
budgets across processes are not reserved by this module. Existing native owner
must keep one capture writer and bound a later approved sample across invocations.
No long-running daemon, new cron or workflow has been installed.

CLI emits a new immutable-by-no-overwrite local attempt directory under
`outputs/free_market_context/`. It writes normalized diagnostic observations
and source hash, not raw bytes, source-of-truth generations or accepted heads.
This is not a durable source archival protocol, and a current download alone
cannot certify historical PIT. Dataset source retention must reuse a separately
reviewed existing storage contract. Single-writer trusted worktree is required;
this is not a hardened hostile-filesystem transaction service.

## Callable interfaces

```python
from tools.free_market_context import (
    cot_observations, finra_observations, cboe_observations, aaii_observations,
    trailing_context, price_theme_context, calendar_theme_context,
    compose_research_context,
)
```

`price_theme_context(close, volume, sessions, universe, themes, cutoff=...,
collected_at=..., membership_available_at=..., source_sha256=...,
turnover_close=None)` expects pandas DataFrames on the same explicit daily
session index. `themes` maps native security ID to a list of theme IDs.
`calendar_theme_context(raw, requested_symbols, theme_map, observed_at=...,
collected_at=..., cutoff=..., mapping_available_at=...)` expects C1-format raw
JSON and vendor symbols as keys. `compose_research_context` requires explicit
vendor-to-native `security_map`, mapping availability, and `expected_session`.
Empty or mismatched coverage never becomes an approved economic result.

The CLI allows an authorized operator, AFTER native code review and source
scope approval, to run a bounded public sample:

```bash
python tools/run_free_market_context.py --source cot_tff --capture \
  --http-budget 1 --cutoff collection --output-label cot-tff-sample-001 \
  --licensed-internal-research
```

This sample is documented, NOT executed by this package. `--cutoff collection`
uses actual completion time. FINRA additionally needs `--trade-date YYYY-MM-DD`.
Existing attempts are never overwritten. Other sources require `--input`,
`--expected-sha256`, caller-attested `--collected-at` and exact `--cutoff`.
Calendar also requires `--symbols`, `--theme-map`, its hash and mapping clock.
There is no CLI network mode for AAII/Cboe/Calendar.

## Native acceptance still required

1. Recheck current master, AGENTS, native status/diff, source lane and overlapping
   work. Do not make a remote-file commit to bypass the user's existing worktree.
2. Reconcile this add-only patch against current code, then separately apply
   approved C1 if absent. Dependency fixture files NEVER replace native files.
3. Register `tests/free_market_context_smoke.py` through the existing approved
   test-registration path. The patch does not edit protected test-runner paths.
4. Run native normal/-O tests including C1 and the existing macro suite. Every
   new commit must pass all required CI anew, plus independent exact-head review.
5. Only after native approval, perform a separately bounded real sample and
   verify schema, actual coverage, freshness, units and source rights. Bind
   outputs to existing storage and read-only A2/A4 interfaces in a later slice.
6. H2 strategy effects, A3/ER/ranking, A5, official portfolio and production are
   NOT approved by source parsing or these tests. No historical A/B/fullrun.

All current outputs have `h2_eligible=false`, `ranking_allowed=false`,
`portfolio_mutation_allowed=false`, `historical_pit_certified=false`,
`production_activation_allowed=false`.
