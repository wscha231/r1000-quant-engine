# A2/A8 research intake H1

Task: `R1000-A2-A8-RESEARCH-INTAKE-CONTRACT-H1-20261015`.
Base: current master `8a30f94f4d8b30b8f93791d85b9abe15ae83e8f5`.
Classification: supplied-byte research proposals only; no deployment approval.

## Existing boundaries and inputs

`research/a2_research_intake_v1.py` reuses the existing A3 source-graph and ER
validators and `candidate_registry_v1.build_reference_index`. It creates no
second persistent registry, source adapter, risk engine, scheduler or writer.

Callers supply exact JSON bytes, an explicit timezone-aware cutoff, a
`MemoryArtifacts` inventory of already-held bytes, and identity-assertion JSON.
Arbitrary resolver callbacks are refused. The inventory is bounded and sealed;
this is an in-process pure API, not a sandbox against malicious Python code.
The module performs no network, filesystem, subprocess, persistence or wallclock
access. Schema files must be supplied as `SCHEMA:<filename>` inventory entries
with their exact code-pinned SHA256. Schema resolution cannot fetch remote refs.

Identity assertions have exactly `scope=SUPPLIED_US_IDENTITY_ASSERTIONS` and
`rows`, each containing `security_id`, `issuer_id`, `tickers`, `country=US` and
`currency=USD`. These caller assertions do not authenticate identity, historical
listing, corporate actions, rights, PIT, source review or a canonical current
pointer. Missing mappings are refused; ticker-only inference is absent.

## API and semantics

All public validation functions return proposals or raise bounded `IntakeError`.
All inputs use strict duplicate-key decoding. Byte, lexical depth and token
limits are checked before allocating the JSON tree. Unknown fields, nonfinite
numbers, number/boolean confusion and naive clocks are rejected. No guard uses
Python `assert`. Default bounds: 4MiB/object, depth32, 50,000 lexical tokens,
10,000 in-memory artifacts and 32MiB total artifact bytes; lexical array
entries1000 (identity-assertion decoding explicitly allows10000). The byte/token
bounds still apply to identity assertions. Native test corpora may restore
CRLF schema checkout bytes to LF only when the result matches the exact static
schema hash; the runtime API never normalizes evidence.

- `validate_events(raw, cutoff=..., artifact_resolver=..., identities=...)`:
  validates the event schema, publication <= availability <= collection <=
  supplied as_of <= cutoff, observation <= collection and expiry >= collection.
  The canonical direct-score field is `score_contribution=0`. Old aliases are
  unknown fields. V0 requires null graph references and null verified_fact,
  assessment=false and a discovery/watch/refusal state. Telegram/community
  stays discovery-only even when its tier is relabeled. V1/V2 requires exact
  graph/raw bytes, matching subjects and the existing A3 source rules. Identical
  raw bytes and repeated publisher families cannot manufacture independent
  groups. Semantic independence and authentic reviewer identity remain separate
  upstream gates. Even graph-consistent input emits assessment=false and
  canonical_verified=false; this H1 does not execute admission transitions.
- Clusters sort by aware available_at then immutable event_id. The key is the
  sorted issuer/security set plus event_family. The first event anchors an
  inclusive24h interval; headlines cannot extend the interval by chaining.
  Ticker aliases do not multiply security identities. Active research watches
  are capped at30 securities and10 themes. Expiry <= cutoff and rejected/stale/
  blocked events do not consume active capacity; every original event remains
  in the denominator. These caps do not limit the investment universe.
- `validate_queue(...)`: validates the existing queue preview meaning in a
  closed typed envelope. Required channels and statuses must match. Missing
  consumer receipts remain DATA_PENDING. Unknown expiry from the Theme preview
  is permitted only in DATA_PENDING, not certified as fresh. Supplied item
  identities are unique by security. Different securities of one issuer remain
  distinct. An upstream Theme preview needs an explicit caller envelope and
  actual supplied identity mapping; this module does not invent either.
- `reference_preview(raw, ...)`: the only field is `entries`, passed to the
  existing Registry adapter. Null means RECONCILE_PENDING. The existing replay
  result preserves SUPPLIED_REFERENCE_SET_ONLY, NOT_VERIFIED review/current/
  domain selection and closed reuse/economic authority. It never means CURRENT.
- `plan_delta(previous_raw, current_raw, cutoff=...)`: pure comparison of
  explicit subject/fingerprint/expiry/exception assertions. Null prior means
  RECONCILE_PENDING. Price changes refresh market/valuation/ER; earnings refresh
  earnings/valuation/ER; industry changes refresh affected pillars; regime
  refreshes downside/overlay. Source, identity or accounting breaks require full
  A3 review. Expiry/catalyst/correction/retraction/source failure/outcome maturity
  prevent blind skip despite unchanged fingerprints. SKIP_UNCHANGED is a plan
  over supplied research_reuse_ready assertions, never a freshness certificate,
  authenticated gate, A0 completion, current write or execution authorization.
- `er_preview(ref_raw, ...)`: absent ER stays null. Internally consistent
  original net WALK_FORWARD_VALIDATED bytes may expose `declared_er`, preserving
  a genuine numeric zero. `validated_er` stays null and BLOCKED_RESEARCH_ONLY
  because independent review/model/config/data/PIT admission is not implemented.
  Wrong identity/benchmark, gross/scenario/stale inputs are refused. A shortened
  A3 result cannot substitute for the original risk/ER artifact.
- `validate_cohort(...)`: rows link event/cohort/decision/subject/benchmark/model/
  config/data/calendar/code identities. `calendar_ref` resolves a closed
  `h1-supplied-target-calendar-v1` object with targets keyed
  `<decision_id>:<horizon>`, each exactly `{session, close_at}`. `outcome_ref`
  resolves `h1-supplied-outcomes-v1` rows containing exactly the row's identity,
  session and return fields, excluding status/authority/denominator/source hash.
  Every MATURED row must match those bytes, exact target session, actual supplied
  availability after the supplied close, and asset minus benchmark return.
  No NYSE calendar or performance computation is introduced; supplied calendars
  and outcomes still require independent upstream admission. Complete exact
  seven-horizon coverage creates only `maturity_candidate=true`, while
  outcome_admission=NOT_VERIFIED and learning_eligible=false. Partial/missing/
  delisted/exited outcomes remain null and in the denominator. WATCH, REJECT,
  BLOCKED and NOT_SELECTED are retained. Late-session substitution is refused.

All root and investment-object authority flags are mandatory exact false,
including selector/ER/target/portfolio/paper/broker/orders/promotion/execute/
production/dispatch/admission/ledger/canonical_write/learning. No automatic A3,
A0, A5, champion, paper or broker operation is connected.

## Existing candidate producers to the pending queue (2026-10-27)

Task: `R1000-A2-EXISTING-CANDIDATE-QUEUE-CONNECTION-20261027`.
Audit base: `12556c6253e54a4d5a20a3dcf8cf247ad7a48a56`, #448 / #670.

| Family | Existing producer / consumer | Boundary still requiring evidence |
|---|---|---|
| Form3/4/5, including amendments | `run_sec_form4_parser` -> `build_ownership_research_events` -> `run_sec_research_consumption` -> existing A2 / Registry filing request / A3 filing reference | Pending content review is not a completed Thesis; P code is not verified execution venue. |
| 13F | `run_sec_13f_parser` -> `run_13f_position_event_builder` -> post-disclosure candidates; `build_top_manager_discovery_signals` -> SEC-enriched replay -> candidate lanes | Authenticated 13F Main admission remains blocked in the existing SEC consumer; mapping, report completeness and amendment lineage cannot be bypassed. |
| Financial quality / operating acceleration | `r1000_candidate_lanes.score_candidate_lanes` quality, emerging and cyclical lanes | Existing replay inputs and missing-value defaults do not establish current financial coverage, source clocks or research eligibility. |
| Earnings estimates | `collect_earnings_estimates_finnhub.compute_estimate_revision_features` -> free-data selection overlay | Two comparable vintages, explicit validity and confirmation are necessary; no analyst-breadth source remains UNKNOWN. |
| Relative strength / leadership | `r1000_candidate_lanes` market-leader / emerging lanes, existing technical Reader route | Benchmark, sessions, price basis and actual consumer receipts remain separate gates. |
| Cross-source shortlist | `run_post_disclosure_alpha_candidates`, `run_fusion_candidate_review` | Their ranked CSV/replay outputs previously had no shared file-to-pending-queue caller. |

The daily operating workflow calls SEC-enriched replay on its restored-target
revaluation book. That is not a fresh broad-universe discovery run. The full
rebuild sidecar also calls the existing manager and fusion producers; this audit
does not authorize executing that full rebuild or promote any legacy blend.

At the audit observation, Form345 run40436717028/head2144fb9 succeeded, including
its Drive sync step; this alone does not certify every form or full coverage.
13F run40270200680/head55c35a2 preserved collected Source independently, then
failed combined weighted analysis: required-period parsed-manager coverage
0.1470588235, mapped-row coverage0.0376809578, one parse-error manager and no
parsed required amendment. Earnings run40455721621/head2144fb9 failed before
collection with `missing_collector_transaction_marker`. Preserve these
failures and held data; neither a queue proposal nor a new observation clock
repairs them. No workflow was dispatched or rerun for this connection.

`tools/run_a2_research_intake.py` now also accepts a closed request:

```json
{
  "schema": "a2-candidate-queue-files-v1",
  "identities": {"path": "identities.json", "sha256": "<actual SHA256>"},
  "sources": [{
    "kind": "RELATIVE_STRENGTH",
    "file": {"path": "scored_latest.csv", "sha256": "<actual SHA256>"},
    "ticker_column": "ticker",
    "tickers": ["MU"],
    "polarity": "CANDIDATE",
    "observed_at": "<explicit aware time this output was observed>"
  }]
}
```

Use the same CLI below with the actual request hash and cutoff. Supported kinds
are SEC_OWNERSHIP, SEC_13F, POST_DISCLOSURE, FUNDAMENTAL_EARNINGS,
RELATIVE_STRENGTH, ESTIMATE_REVISION and FUSION_REVIEW. Kinds and CANDIDATE or
RISK_WATCH polarity are caller assertions, not inferred favorable signals.
By default the exact selected tickers must exist in the held CSV and map
unambiguously through the existing supplied US/USD identity contract. No new ranking,
threshold, CUSIP inference or automatic universe/Registry membership is added.

The adapter hashes every complete source file and selected data row, records
all source-row and selected-row denominators, combines reasons by exact
security, and calls the existing `validate_queue`. Aliases share a security;
different securities do not. Native scores and blank cells remain in the
hash-bound originals and never become direct scores or fabricated zeros.
Output includes the original queue envelope and validated proposal so an
existing A0/A1 consumer can inspect required channels and reuse held inputs.

All items remain DATA_PENDING with missing consumer receipts and unknown source
publication/expiry. observed_at is an output-observation assertion, never a
fresh filing, price, revision or publication clock. This permits review of an
old output without certifying it as current. There is no collector, persistent
watch, recurring producer delivery, consumer ACK, dispatch or current pointer.
Authenticated Form345 consumption and the blocked 13F admission path remain
unchanged. A pending queue does not substitute for either.

### Preserve candidates when financial or technical outputs are missing

Set `"retain_missing_candidates": true` on the same file request when its
explicit ticker list is the tracked research roster, including names without
financial, price or technical outputs. The roster must come from the existing
tracked universe and discovery evidence, rather than only the rows that earned
a score. Select the complete intended roster on every such request; this is
not a persistent store or an automatic merge with an earlier output.

With this option, an absent CSV row stays in the existing queue as DATA_PENDING
with REQUESTED_CANDIDATE_DATA_PENDING / MISSING_PRODUCER_ROW evidence. The exact
request hash binds the user's requested scope. An empty selected-row list
records the absence; it never fabricates a producer event or metric. The
producer binding distinguishes requested tickers from observed selected rows
and names every missing ticker. A valid header-only CSV can retain a roster
when no observations were produced. Missing files, hash/CSV failures and
unknown or ambiguous identities still refuse the invocation; the create-only
output path does not replace an earlier result on failure.

Blank financial/price/RS cells, a negative profit/FCF, or no producer row do not
remove a candidate. Existing quality and emerging research lanes remain
separate. Missing inputs remain unknown, not zero or an optimistic runway;
the next action remains LOOKUP_EXISTING_INPUTS_BEFORE_COLLECTION. Candidate
retention grants no current price, accepted Source/PIT, completed A3, ER, A5,
collection dispatch, order or portfolio authority. Keep any rejected company
assessment and identity/lifecycle findings separately evidenced; this option
does not authenticate or overturn them.

CSV input is capped at16MiB/file,10000 data rows and2048 distinct columns to
accommodate the incumbent7.48MB scored table. JSON retains4MiB/object; total
held input remains32MiB. There are at most10 sources and1000 explicitly selected
tickers/source. Duplicate sources, ambiguous identities, missing selections,
malformed CSV, mismatched hashes, traversal and future observations refuse.
An identical path/hash CSV reused for several reason families is read once in
that execution; relabeling the same bytes cannot certify independent sources.
The existing create-only output writer and closed authority flags apply.

## Bounded file caller (2026-10-27)

`tools/run_a2_research_intake.py` loads already-held event evidence into the
same `validate_events` API. It supplies no collector, new Registry or scheduler.
The caller owns a stable read-only tree and pins the request file's SHA256.
The closed request has `schema=a2-file-intake-v1`, `events` and `identities`
references (each exactly `path` and `sha256`), `artifacts` (each exactly
`artifact_id`, `path`, `sha256`), and `event_sources` mapping every event ID to
one through ten supplied artifact IDs. Paths are relative, without traversal,
URLs, symlinks or Windows reparse points. The reviewed event schema is loaded
by its existing exact code pin; supplied artifacts cannot replace it.

All selected files are hash checked. Files are bounded before allocation to
4MiB each and 32MiB total, including request, events and identity bytes; the
existing API additionally enforces its sealed inventory/schema budgets. Each
event must bind held source bytes, but this binding alone authenticates neither
the publisher/publication clock nor the claim, identity, independence or rights.
A caller-supplied label stays an assertion. V0 stays DISCOVERY_ONLY, assessment
false and score zero. Missing publication time, malformed input or conflicting
bytes are refused by the existing checks.

Example (explicit paths and actual hashes must be supplied):

```sh
python tools/run_a2_research_intake.py --input-root /held/evidence \
  --request request.json --request-sha256 <actual-request-sha256> \
  --cutoff 2026-10-27T06:01:34.219574+00:00 --output /scratch/new-proposal.json
```

The parent output directory must exist. The caller creates one new local result
file only; an existing path is refused before recomputation and never replaced.
The final name is created only after an isolated temporary file has completed
write/flush/fsync/close. Atomic create-only hard-link publication fails closed
when unsupported; the result is not a durable account commit. A later temporary
cleanup failure is separate metadata, not a reversal of successful publication.
Its read set, request hash, source bindings and actual code-file hashes support
reproduction. The caller prints only bounded status/hash metadata. A filesystem
write failure is not a completed result. No canonical queue/current pointer,
accepted source, paper/book, learning or A3/ER/A5 admission is written. This
manual caller closes the file-to-A2 edge; recurring upstream delivery and
authenticated downstream admission remain separate work.

## Validation and real-data boundary

The new synthetic suite is registered through the existing A3 `load_tests`
without removing RegistryTests or AuditTests or changing protected runners.
Run the intake, full registered A3 route and Control Plane smoke normal and -O.
The external successor evidence maps the original40 planned families to actual
methods and modes, including full registered regressions, output parity and
proof inventory omission/stale/delete/rename attacks. Counts are test methods,
not proof of40 completed investment-data families.

The original preparation packet remains immutable:
SHA256 `20e1c906b7f90c64b70bde91ab5c6476d4a865b4de111effd0cac8a9d6eb9e21`.
Actual37-name/23-earnings-pair research is not synthesized into valid input:
missing raw/time/identity/review/market evidence stays BLOCKED_PROOF and is
reported separately from fixtures. Source #618 and Main #620/#621 are separate
unmerged scopes; this branch is not their integrated master or deployment.

The original H1 preparation was NO_CODEX and Draft-only; that historical label
is not the current branch/PR status. Read current GitHub HEAD, reviews and checks
for integration evidence. Native and independent A6 evidence alone do not
authorize merge, fullrun, collection, learning, Source/PIT promotion,
portfolio/book/order changes or notifications.

## Pre-ranking observations to the existing queue (2026-10-30)

`tools.run_theme_leadership_tape.prepare_research_roster` accepts explicit
pre-ranking roster JSON bytes (`scope=PRE_RANKING_RESEARCH_ROSTER`, `rows`),
the existing supplied US/USD identity-assertion bytes, and exact generation
hashes keyed by security ID. Each roster row has `ticker` and optional `Name`,
`sector`, `industry`. Unknown or ambiguous identity and duplicate securities
are refused before source reads. Classification is descriptive; a missing
sector remains unclassified, rather than removing the security. The supplied
roster is the denominator, including names without inputs or with negative
observations. A scored top-N or ETF seed is not substituted for that roster.

The adapter calls the existing `research_feature_snapshot`, which uses public
`ResearchDataReader.read_components(purpose=research,
consumer_id=ohlcv-technical-feature-h1)`. Supply the already-authorized reader,
original subject/optional-benchmark generations, explicit session and source
decision `as_of`. Existing identity, rights, original clocks, windows, raw/split
lineage, same-generation receipts and archival trust requirements apply.
No manifest field creates trust. An absent subject generation produces an
explicit pending row. A supplied generation refused by Feature stops the
handoff with its refusal codes; it is never downgraded to ordinary missing
data. Missing optional SPY leaves its RS features null while subject features
remain usable. No Reader, Feature, Registry or Source gate is changed.

Feature's native 5/20/60/120/240-session fields, feature statuses and complete
snapshots are retained; they are not relabeled as legacy 21/63-day metrics.
This route computes no new ranking, score, liquidity filter or trading policy,
and preserves `ranking_allowed=false`. Actual zero and negative returns stay
numeric; unavailable observations stay null (blank in CSV), never zero.

Supply separate `observed_at` and `intake_cutoff` for the newly produced
handoff, with `as_of <= observed_at <= intake_cutoff`. Output observation time
does not replace original source publication, availability or collection
clocks, and a historical source cutoff is not the new output's observation
time. `source_kind` is an explicit existing A2 kind assertion, not certification
of favorable signals or formal RS. The caller creates a new local output
directory containing exact observation JSON/CSV, identities, request and the
existing A2 result. Existing directories are refused; partial files after a
failure are not a completed handoff. No canonical queue is written.

The existing `prepare` file API reads those hash-bound bytes with the complete
explicit roster and `retain_missing_candidates=true`. Queue items remain
`DATA_PENDING` with missing consumer receipts. Repeated exact requests replay
the same proposal; changed bytes require changed hashes. Existing hash,
identity, scope, expiry and clock refusals are retained. A3 must actually read
the observation and queue bytes and return their hashes with its partial
research result or exact refusal. The adapter returns `a3_consumer_ack=null`;
neither a proposal nor a prepared prompt is an A3 ACK or Registry current.

The legacy cache/report route now performs no implicit ETF provider fetch.
Missing/nonfinite returns display `UNKNOWN`; observed zero displays `0.00%`.
Breadth exposes total/observed/missing/positive counts and its observed-liquid
denominator. Partial required observations produce `data_pending`, not neutral
or a leadership score; observed-only breadth is not whole-market breadth.
`--comparison-session` explicitly bounds stock and ETF cache rows. Row dates,
stale/missing counts and `MIXED_AS_OF`/`PARTIAL` qualify the summary; `completed`
means computation finished, while max-date is only a watermark. Cache rows do
not authenticate Source/PIT or currentness. The legacy scored-input scope is
explicitly labeled separately from the pre-ranking roster API.

Cache-owned dates, returns and volume fields always replace scored CSV fields,
including a complete null record when the cache is missing/short. Old producer
metadata cannot impersonate a successful cache read. Unobserved ETF attention
and combined watch scores remain null. ETF row dates/as-of statuses are shown;
stale ETFs are excluded from current attention when a comparison session is
supplied, without blocking independent stock observations.
Attention also requires its actual current/prior20 volume observations and
finite dollar-volume input. Missing volume is not observed zero; real zero
volume stays valid without a new positive-volume or liquidity threshold.
Incomplete/stale rows remain in observation outputs but are excluded before
the existing score normalization. They cannot change a valid row's score by
altering an invalid comparison population; existing weights stay unchanged.

Synthetic regressions extend existing registered `ThemeTests`; no test registry
or protected workflow changes are required. Actual Source-to-A3 wiring, three
different economic-profit-source examples, independent A6, Registry current,
validated ER/A5 and repeated operation require their separate actual evidence.
