# Daily Crisis Monitor: B1 report clock and history

Task: R1000-MACRO-AB-B1-REPORT-CLOCK-HISTORY-20261015. Control #448, plan #617.
US equities/USD cash, RESEARCH_ONLY, explicit dry-run route. No delivery,
portfolio sizing, accepted-state write, policy promotion or scheduler change.

## Entry and authority

`tools/run_daily_crisis_monitor.py --report-slot INTRADAY|AFTER_CLOSE` selects
the adapter. Supply `--report-session YYYY-MM-DD`, `--report-now` (explicit
offset timestamp), `--report-recipient`, an unused `--output-dir`, and
`--history` pointing to an independently approved report-history anchor.
The legacy invocation remains available for compatibility. Its current-report
boundary now uses the independent host clock and completed XNYS session rather
than the source's own date. Its declared availability and per-invocation
hysteresis are still **not certified by B1**. A0 must authorize any scheduled
cutover separately after real-input validation.

Add `--report-source-view`, `--expected-source-view-sha256`,
`--report-source-root`, `--expected-history-sha256` and, for a non-root anchor,
`--expected-history-parent-sha256`. Hashes are read pins, not approval tokens.
No implicit anchor/reset or accepted-pointer discovery is performed. Missing
source produces REAL_INPUT_WAIT. Missing history produces HISTORY_UNAVAILABLE.
`--update-history` is refused. Output must be outside the immutable input root;
an existing output directory is refused. Only summary, Markdown and optional
`report_history.candidate.json` are written to the new output directory.

## Existing producer contract

The source view schema is `daily-crisis-source-view-v1`, containing:

- `input_kind`: FIXTURE or ACTUAL, consistently across all clock records.
- `chameleon_manifest`: path/SHA256/size reference to the existing
  `build_run287_chameleon_macro_risk.py` manifest.
- `source_clocks`: bounded metadata records keyed by consumed source SHA256.

The adapter pins the manifest, calendar, metrics, optional context, snapshot
and full market-state history. The producer must match the current reviewed
Chameleon builder bytes (Native or Git LF), with all economic execution flags
false. The canonical risk contract is the sole permitted reference outside the
approved source root; its path, byte hash and semantic hash must match.
The existing producer validators and state-history replay are reused. B1 adds
no thresholds, weighting model, calendar store or risk engine.

Each clock record requires source identity/hash, explicit published/available/
collected/expiry timestamps, SECOND or MICROSECOND precision, verified
availability evidence reference, private research rights, purpose eligibility,
revision evidence, unit and seasonal basis matching their approved expectations.
Every consumed metric and context row must resolve to a clock, available by its
historical decision and the report cutoff. A date-only FRED/ALFRED vintage never
becomes an invented release time. Provider acquisition and verification of these
records remain upstream responsibilities; setting booleans is not new evidence.
ACTUAL additionally requires `--report-expectations` and a separately accepted
`--expected-report-expectations-sha256`. This is A0/Source configuration supplied
outside the source view; B1 neither invents financial units nor writes the registry.
Schema `daily-crisis-expectations-v1` binds purpose US_MACRO_REPORT, producer hash,
canonical risk-contract semantic hash, `sources` keyed by exact source SHA with
source_id/source_kind, `components` keyed by canonical metric name with axis/unit/
seasonal_basis/explicit source_ids, and separate `context_fields` specifications.
The independently accepted config also pins metrics/context/calendar input bytes
and each original source-clock record hash. Nontext/empty/unknown identities or
units are refused; equality of two unknown values never verifies a source.
Each ACTUAL clock carries observed `units` keyed by the consumed component or
context field. All consumed identities/fields must match; no wildcard or fallback.
Missing registry, coverage or independent acceptance keeps ACTUAL blocked.
Market breadth needs a verified denominator of at least 500 eligible symbols.
Source-view hashes must be accepted through independent QA before ACTUAL use.

Inputs are stable bounded regular files; JSON duplicate keys/nonfinite numbers,
outside-root paths and hash mismatches refuse. CSV logical-record, field and
cell limits apply before parsing. Oversized histories require a separately
reviewed adapter change; truncating history to claim restored state is forbidden.

## Slots, history and partial reports

NYSE calendar governs holidays, DST and early closes. Normal intraday is 13:00
New York; early-close intraday is min(13:00, close minus 60 minutes). After-close
is actual close plus 60 minutes. Holidays produce no report candidate. Late
intraday is not backfilled; ACTUAL runs must target the current New York date.

Intraday is INTRADAY_PROVISIONAL and requires the exact previous NYSE session's daily
snapshot. It does not invent intraday axis values or advance EOD confirmations.
After-close requires the exact session snapshot; old successful artifacts cannot
be emitted as current success. Restored Chameleon history must be contiguous,
calendar-bound, cover exactly the validated metric dates, and reproduce existing
2-session entry/5-session release logic. Ready axes must have the canonical
minimum actual metric components and match the pinned producer axis artifact.
Claimed-ready components also need the canonical 252 observations in the
5-year/1,260-session window. The existing engine's latest-session reducer checks
consumed score/observed-state consistency. Full metrics→percentiles→axes→history
are also verified with the existing deterministic engine, including every past
observation/counter. A two-entry process-local cache stores only pure derivations
bound to immutable inputs, producer/contract and verifier code. Claimed outputs,
source clocks, safety flags, registry and runtime validity are checked each call.
This verification does not publish or advance a canonical risk calculation.
ACTUAL mode refuses explicitly synthetic/fixture and current-vintage source kinds.
ACTUAL time is the independent host UTC clock; a supplied time must be within
60 seconds and the slot/date must be current. Expiry covers collection and actual
evaluation, not only the logical report cutoff. Decoder recursion fails structured.
The report anchor separately pins recipient/mode, parent and content hashes,
slot keys, completed count and `last_counted_completed_session`. Each successor
must preserve its accepted source-history prefix (metrics, context, axes, states
and consumed clocks/expectations); append-only calendar hash changes are normalized.
A correction/truncation/revision requires a separate explicit A0 anchor decision,
otherwise SOURCE_HISTORY_PREFIX_CHANGED blocks. Duplicate or previously partial
slots cannot silently increment completion when no new candidate is produced.
An existing completed anchor advances only to the next NYSE session. A missed
completed session requires an explicit A0 recovery decision, not a silent skip.
Before the first completion, only an empty anchor or this same session's
INTRADAY key can precede a ready AFTER_CLOSE increment. An earlier partial or
unresolved opaque slot requires an explicit A0 recovery decision and returns
INITIAL_COMPLETION_REQUIRES_A0_RECOVERY; B1 never clears or resets those slots.
Blocked producer manifests cannot supply report prerequisites; optional null
context remains supported. Immutable Source-root separation also applies when
the source view is missing and only a diagnostic report could be generated.

The delivery key is recipient/session/logical slot. Source/code/config changes
affect the analysis artifact key, never this delivery key. Advancing the verified
candidate receipt between dry runs prevents repeat preparation. No sender/ACK
store is implemented or activated: distributed exactly-once delivery and
ACK_UNKNOWN recovery remain a later delivery gate. Candidates are not canonical
history. Without an accepted next anchor, unattended continuation is blocked.

All ten canonical axes remain present. At least eight and mandatory breadth,
volatility and credit must be ready. Otherwise data health is DATA_PARTIAL,
current score/state are NULL and completed count does not advance. This is data
insufficiency, not a crisis or recovery signal. Legacy crisis state and project
A4 regime stay NULL until an explicit enum mapping is reviewed.

## Company/action boundary and verification

Company relations remain WAIT_VERIFIED_RELATIONS with no invented impacts.
Existing Candidate Reassessment Bridge can later consume verified SEC/IR/company
relations; B1 does not extract or approve them. Missing book, net ER, downside or
cost evidence blocks quantitative weights. Reports retain qualitative winner,
thesis, alternative, cost and reentry review only.

The smoke entrypoint already registered in PR validation loads the new B1 suite.
It runs the actual existing Chameleon producer on clearly marked FIXTURE inputs,
then tests two-slot counting, hash/parent restore refusal, stale success,
source/context clocks, rights/revision/unit/expiry, breadth, partial readiness,
DST/holiday/early-close/late-slot behavior and immutable-output integration.
Native normal and `-O` run the same unittest assertions. The frozen validator
and workflow logic are unchanged. Proof inventories add only consumed B1 and
preexisting master Theme/Alpaca dependencies; unmerged Source campaign files are
excluded. Green fixtures/CI do not establish REAL_INPUT_VERIFIED.

Independent B2 read-only audit found Paper Bridge selective-trim drift and
unconditional numeric output with missing economic evidence. B2 implementation
requires B1 terminal evidence and a separate A0 file scope. No B2 code changes
are included here.

## Legacy currentness integrity — 2026-10-17

The existing calendar determines the last completed session and its unchanged
AFTER_CLOSE cutoff (one hour after the actual close, including early closes).
The legacy current report uses the host UTC clock; caller report-now does not
backdate it. Old/missing/malformed/future source sessions, unavailable calendar,
future or malformed declared component clocks and missing critical components
return BLOCKED/DATA_BLOCKED with current state NULL and no paper-action candidates.
Declared availability requires complete, unique known component names, strict
boolean flags and parseable clocks for available values. Critical availability
is recomputed from canonical inputs and cross-checked against those declarations;
an empty or incomplete metadata record cannot authorize current history updates.
Every available state-driving component must be fresh, including optional inputs
such as liquidity. Explicit canonical component clocks must match the consumed
availability declarations. Malformed inputs stay on the blocked-output path;
blocked health never reprocesses their invalid clocks outside that boundary.
STALE_SUCCESS_NOT_CURRENT_REPORT retains the explicit B1 stale-success meaning.
No blocked observation calls current hysteresis or rewrites its history bytes.
Current legacy diagnostics additionally require a typed history from the
immediately preceding XNYS session, valid state/streak and an aware update clock.
Missing/legacy untyped, malformed, gapped or same-session history requires explicit
recovery; this patch never initializes, catches up or restores history.
Current updates and prior history are each bounded to their own XNYS-session
New York calendar date, after the existing after-close cutoff. A weekend/holiday
can identify the last completed session but cannot retroactively advance it.
The existing bounded history counter may reach its cap but cannot increment
beyond it; a changed raw state still resets the streak normally.

All four decoded raw-state sidecars (risk controls, safety audit, macro policy,
portfolio snapshot) must declare the same `report_session`, `available_from` and
`generated_at_utc` clocks between that session's close and existing report cutoff.
The clocks are captured from the payloads actually used for inference, not later
file rereads. Missing/unclocked sidecars block current history/actions even if the
long-crisis row is current. These are declared diagnostic clocks, not authenticated
Source/PIT. The existing workflow is unchanged; until producers provide those
clocks and a recovered typed prior history, this legacy route remains BLOCKED.
The existing pinned B1 report route remains available under its own strict contract.

The existing cadence consumer treats explicit BLOCKED as a data boundary: it
does not fall back to diagnostic raw state or integrated historical GREEN/reentry
state, and its build entry point refuses before decision computation. Before
failing it invalidates only the six known cadence outputs, writes blocked JSON/
Markdown markers and empty CSVs, so a wrapper that continues after failure cannot
publish surviving BUY/reentry decisions. Unrelated files are preserved. This is
a Main data boundary, not a new portfolio policy or trading action.
Missing, malformed, untyped or aged monitor summaries also block: the consumer
rechecks the generated clock and source session against its own host/XNYS clock.
The old cadence smoke uses an explicit pinned historical clock fixture, not
implicit current eligibility. An inference/input exception similarly writes a
blocked monitor summary without exposing private exception text.
Both current state fields must be exact canonical enum strings; missing values
and legacy aliases are refused. Reentry metadata comes from that typed current
monitor, never a historical integrated-state fallback.

Combined raw state remains an UNVERIFIED_LEGACY_INPUT_DIAGNOSTIC; individual
long-crisis metadata and source clocks retain their source-session scope.
Fresh legacy output is only
CURRENT_LEGACY_DIAGNOSTIC/DATE_CURRENT_DIAGNOSTIC, never authenticated Source/PIT,
an approved A4 enum, canonical regime or economic approval. The explicit pinned
report-slot route and historical risk inference remain separate and unchanged.
Risk thresholds, selective defense/hold/reentry policies and the canonical ten
axes, minimum eight and mandatory breadth/volatility/credit gates are unchanged.

The registered monitor smoke preserves its two original model cases and B1 suite,
and adds unittest clock refusals active in normal and -O. A hash-verified real
artifact's March20 source/October17 execution can be replayed through this clock
boundary without fetching providers or treating archived inference as a new model
recomputation. No actual workflow, collector, history catch-up or book is invoked.

### Current producer/config/holdings integrity correction

Long-crisis features now preserve a `source_clocks_json` column. Each input's
`observation_clocks` Series metadata is matched to the exact raw value observation
before forward fill; M2 clocks follow the same monthly lag as its value. The
index establishes observation date only. Missing publication, collection,
expiry or immutable source hash is not fabricated from the feature row date.
Current inference carries these original clocks into component availability.
Current reports refuse absent, inconsistent, future or expired source records;
historical inference retains its separate behavior. These declared clocks still
do not authenticate a Source receipt or admit a historical PIT vintage.
Expiry extension alone cannot prove current observation coverage. Current
reports additionally require `--current-source-expectations` and its externally
accepted `--expected-current-source-expectations-sha256`. This dated
`current-macro-observation-coverage-v1` snapshot binds `report_session` and each
source's `expected_observation_date`, exact canonical clock-record SHA256 and
`freshness_basis_sha256`. Its source set must match the ten consumed inputs.
The caller must supply accepted current coverage; runtime never builds an
acceptance file from its own inputs. Absent/mismatched proof blocks current
history/actions with `CURRENT_SOURCE_COVERAGE_PROOF_REQUIRED`. No per-series
age interval or expiry-renewal rule is invented; actual coverage proof remains
an upstream requirement, distinct from fixture acceptance and Source/PIT.

The current monitor requires `--expected-thresholds-sha256` from the accepted
immutable config and all six numeric governor/cash gate fields. The decoded
inference config hash must match; current reports cannot authorize a missing,
partial, string/bool-valued or changed config through historical defaults.
No threshold value or risk-policy formula is changed. Missing approval/pin
keeps current output BLOCKED rather than creating an accepted config.

Action candidates additionally require `--expected-snapshot-sha256` bound to
the exact decoded portfolio summary used in raw inference. Its `report_session`
and `book_session` must match the current session; `holdings_sha256` must match
the exact CSV bytes decoded for actions. An absent or mismatched binding yields
`BLOCKED_HOLDINGS_PROOF` and no action candidates. It does not invent a book or
turn a hash into investment approval. Existing producers without this accepted
binding cannot generate actions.

The daily FRED helper retains its scalar API and numeric definitions. Snapshot
metadata separately preserves response observation date, realtime start/end,
response hash and actual fetch time. Snapshot `asof` remains generation time;
unknown publication/availability remains UNKNOWN/null and current-vintage
retrieval is not historical PIT. No provider request is needed to test this.

Paper consumer review 4301684126 remains a separate B2 gate. File-scope
allocation does not supply B1 terminal/actual coverage proof. Until that proof
is verified, only fixture/design preparation is allowed; no actual preview runs.

## Legacy macro snapshot input guard (2026-10-20)

`macro_daily_snapshot.py` emits `macro-daily-research-snapshot-v2`. SPY and
VIX need finite positive complete-window prices, the latest completed NYSE
session, exact collection/decision ordering and a frozen provider-frame digest.
The original five numerical market thresholds remain unchanged. Missing,
stale, future, inconsistent or degenerate inputs produce `BLOCKED_INPUT`, a
null regime, strict JSON and no transition/Telegram; blocked CLI runs exit 2
and replace the previous current report.

Source availability is explicitly collection-only. Original publication is
unknown; the frame hash is a derived payload identity, not a raw vendor receipt.
Valid outputs remain unauthenticated research proxies: Source/PIT, portfolio,
order and production authority are false. `current_snapshot_reasons` is the
same reusable clock/numeric contract for the separately scoped CLI consumer.
Neither the legacy five states nor a valid proxy grants A5 approval.
