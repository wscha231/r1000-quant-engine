# Daily Crisis Monitor: B1 report clock and history

Task: R1000-MACRO-AB-B1-REPORT-CLOCK-HISTORY-20261015. Control #448, plan #617.
US equities/USD cash, RESEARCH_ONLY, explicit dry-run route. No delivery,
portfolio sizing, accepted-state write, policy promotion or scheduler change.

## Entry and authority

`tools/run_daily_crisis_monitor.py --report-slot INTRADAY|AFTER_CLOSE` selects
the adapter. Supply `--report-session YYYY-MM-DD`, `--report-now` (explicit
offset timestamp), `--report-recipient`, an unused `--output-dir`, and
`--history` pointing to an independently approved report-history anchor.
The legacy invocation remains available for compatibility; its date-derived
availability and per-invocation hysteresis are **not certified by B1**. A0 must
authorize any scheduled cutover separately after real-input validation.

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

Intraday is INTRADAY_PROVISIONAL and references only the last completed daily
snapshot. It does not invent intraday axis values or advance EOD confirmations.
After-close requires the exact session snapshot; old successful artifacts cannot
be emitted as current success. Restored Chameleon history must be contiguous,
calendar-bound, and reproduce existing 2-session entry/5-session release logic.
The report anchor separately pins recipient/mode, parent and content hashes,
slot keys, completed count and `last_counted_completed_session`.

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
