# SEC current source freshness — Form345 Source scope

Current source admission is separate from historical data-anchor research.
The existing collector refreshes submissions, reuses accession XML and parser
checkpoints, and parses newest filings across issuers before the older backlog.
A successful no-new-filing check differs from source failure or an unchecked cache.

Current merge requires hash-bound source/parser receipts, completed accessions
inside the decision window, and matching checked/index/parser CIK/ticker scope.
CSV, Parquet and table summaries share a generation. Partial writes revoke old
success. Joint owners, holdings, derivatives, amendments, codes and notes survive;
ambiguous owner fields and unavailable numeric values stay unknown.

The existing 20-issuer/500-filing workflow remains a bounded batch. Its coverage
receipt is never whole-universe coverage. For incremental expansion, pass the
existing collector a deduplicated, identity-reviewed fixed-universe/candidate
cohort in bounded batches; keep prior accession checkpoints. This PR does not
automatically approve or schedule a larger universe. Unresolved identities must
be recorded and reviewed before their source batch is admitted.

The daily workflow uses the existing collector's acceptance-based history start
at execution time minus 90 days and the nonnegative safety delay. This is a
conservative superset of the later decision window, so old backlog does not
consume the 500 new-parse budget before current filings. It does not erase
retained history. A batch above the cap remains incomplete and blocked until
resumed; a larger checked list does not imply complete parsing.

Form3 initial holdings and Form5 late/supplementary reports are retained as
evidence, excluded from the legacy Form4 signal calculation. P-code score names
are compatibility research proxies and do not certify public-market execution.
No score weights/live switches, A2/A3 Registry state, portfolio or orders change.

Main typed-event/reassessment changes remain with the existing Main owner.
No current real disclosure-to-A3 claim follows from these Source-only fixtures.

## Exact CUSIP mapping and actual consumer diagnostic (2026-10-21)

The original BRK 89-row proof was the first, unmapped parse: no `cusip_map`
was supplied. The existing workflow already performs raw parse, map building,
then a mapped parse. Missing map input is not missing SEC XML or evidence that
a new collector is needed. Preserve the original source receipt unchanged.

The scheduled map-building call now uses `--exact-cusip-only`: reuse the
existing explicit CUSIP overrides without issuer-name/CIK or candidate-name
inference, seed reads or a fresh company-ticker request. Issuer CIK does not
resolve a security/share class. This is explicit mapping evidence, not historical
identity/PIT approval. Missing overrides stay unresolved; conflicting tickers
for one CUSIP refuse in both the builder and parser rather than choosing a row.
Same-ticker duplicates remain reusable. Builder and consumer preserve Parquet null identities.
The mapped parser also enforces exact-CUSIP policy: embedded-only tickers stay
unmapped, contradictory XML tickers refuse, and the policy is checkpoint-bound.
The legacy name-matching mode remains available only as a separate diagnostic;
it is not used by the canonical quarterly workflow. No new mappings are added.

Offline Native replay reused the original BRK Q2 XML and original decision
clock 2026-10-20T18:43:10.927864Z. Existing override file SHA256
`6b9aac75913dfbc22591bb53071ed6d666c49c0d2e732c46abbb774d57b98f6e`
maps 45/89 rows, 11/29 unique CUSIPs, and 61.431% of original value. The other
44 rows/18 CUSIPs remain unresolved. One local derivation reflects changed
mapping/code; the next replay uses its checkpoint with zero reparses. Both use
zero provider calls. This one-manager sample does not replace the distinct
10-manager/260-row coverage or waive current Form4/ETF/manager gates.

Actual read-only calls to the unchanged Main-owned builders reveal blockers:

- AAPL original 78 rows contain Form3=8 and Form4=70; 9 rows are holdings.
  `build_form4_events` emits 78 legacy events but drops `form_type`, `row_kind`,
  `transaction_id`, document/owner/footnote provenance, derivative identity and
  market-verification fields. No P-code occurs in this bounded actual sample;
  its legacy unconditional P/open-market rule is not validated by that absence.
- `build_position_events` emits 11 legacy events from the 45 explicitly mapped
  BRK rows, dropping 34 repeated manager/accession/ticker rows by keep-last.
  Whether those source positions are distinct, overlapping, or aggregable needs
  original investment-discretion/other-manager/voting/class evidence. Do not
  interpret the keep-last output as a certified position or blindly sum it.
- Repeating the same input yields identical output; this is not persistent
  new/replay/amendment/stale/unavailable idempotency proof.
- Current Shared Reader registry supports only `ds.us.prices.daily`, with no
  admitted frozen generations. An explicit unregistered SEC negative request
  refuses `UNKNOWN_DATASET` before transport. No SEC Reader consumption occurs.

Source raw verification, explicit identity mapping, typed-event admission and
economic interpretation remain separate gates. Existing Main owner must retain
all Source semantics, reconcile repeated holdings, bind actual frozen SEC
manifest and genuine A2/Registry/A3 references, and test persistent lifecycle
cases. No Main files or Registry entries were changed, no metadata/exposure or
A3 references invented. Economic approval and task-wide completion remain open.

## Canonical Drive selective-restore replay (2026-10-21)

Native execution restored only three selected manager submissions and their
Q2 2026 XMLs from the existing canonical SEC Drive folders: BRK, Whale Rock,
and Atreides; six files, 456,457 bytes. The existing parser stored 173 rows
(89/35/49) with matching CSV/Parquet/summary hashes and counts. Existing exact
CUSIP overrides map 65/173 rows (37.57%) and 58.92% of reported value. This
bounded replay does not replace the distinct ten-manager/260-row cohort.

The restored submissions remain `CACHED_NOT_CHECKED`; Drive read time is not
a successful SEC check. Three separate actual SEC submissions checks then
confirmed Whale Rock/Atreides timestamps but exposed a BRK source-clock
conflict for accession `0001193125-26-352200`: the old Drive JSON says
`2026-08-14T20:05:04.000Z`, while the current SEC response says
`2026-08-15T00:05:04.000Z`. Preserve both original payloads and their hashes;
do not infer the upstream cause or silently correct/re-admit the old snapshot.
The current-source index uses the current response and separate actual check
receipt; cache-only reconstruction does not manufacture collector check times.

The first unchanged replay reused all three checkpoints with zero parses and
zero parser provider requests. Reconstructing the index with the newly observed
BRK clock invalidated only its checkpoint (one parse), retained the same XMLs,
and the next replay again needed zero parses/provider requests. Original Drive
bytes remained unchanged. This proves direct selective Drive restoration and
Native save/resume, not hosted/rclone execution or accepted SEC Lake generation
admission. Combined manager/mapping/Form4/ETF gates and actual Main consumption
remain blocked or pending; no frozen SEC dataset or A2/A3 references are created.

## Standalone source-bound 13F generations (2026-10-24)

The existing position builder now has an explicit `--disclosure-research` mode;
see `SEC_MAIN_CONSUMPTION_V1.md` for the command and storage contract. It reads
only the supplied selected-manager bundle, including the original submissions,
XML, checkpoint and exact map. Direct XML reparse and CSV/Parquet/receipt parity
are prerequisites for a typed, self-contained generation. Physical raw bytes
are distinguished from the parser's newline-normalized text hash. A complete
input timeline is required for incremental comparison. Missing history, changed
same-accession content, map/code context conflicts and unproved amendment covers
refuse; replay emits no duplicate events or intents.

`generated_at`, `decision_at`, selected-manager `last_successful_source_check`,
`latest_accepted_at` and scoped `source_coverage` remain distinct. A fresh
CHECKED_NO_NEW_FILINGS is a successful check; CACHED_NOT_CHECKED, STALE and
SOURCE_UNAVAILABLE are refusals. BUILDING or failed current attempts cannot use
a previous successful pointer as a new current result, including CLI missing
arguments for an explicitly named owned store. Historical readback remains
available with an explicit historical flag and confers no current authority.

The actual bounded check on 2026-10-24 at 04:05 UTC used three existing
submissions GETs: BRK, Whale Rock and Atreides. Their latest observed 13Fs remain
Q2 2026. Original three restored XML files were unchanged; the existing parser
saved 173 rows with 65 explicit mappings. BRK had ten newly observed submissions
accessions of any form; this does not mean ten new 13Fs or ten newly bought
stocks. Whale Rock and Atreides returned no new submissions. Actual
standalone storage/readback completed for all 173 typed review events; identical
replay added zero events and preserved the pointer/event bytes. All events are
`DISCLOSURE_REVIEW_INCOMPLETE` because the full reports are not completely mapped;
no removal/trade or aggregate-analysis admission follows. Three single-manager
stores are separate readback diagnostics of the same originals, not extra
coverage. Amendment, stale/unavailable and interrupted-write tests use fixtures.
Current execution, per-store admission/refusal, artifacts and replay results are recorded
in `ACTUAL_SOURCE_PREPARATION.json` / `ACTUAL_STANDALONE_STORAGE.json` of the
2026-10-24 task receipt directory. These are local research observations, not a
frozen shared-reader generation, complete manager universe, due-quarter
certification, admitted performance cohort or A2/Registry/A3 consumption.


## Main clock reconciliation boundary (2026-10-28)

Source generation verification and a committed Main request can disagree on
acceptance/availability clocks even when document and event IDs are identical.
The explicit immutable correction in SEC_MAIN_CONSUMPTION_V1 preserves the
original request and both submissions, binds the current canonical JSON
content hash to source_checks, and reuses the existing A2/Registry/A3 adapters.
A physical raw SHA256 is not the collector content hash. Current source-check
expiry and all nonclock semantic guards remain; old artifact readback cannot
renew freshness. The derived view stays pending research, with no official
assessment, ER, economic or trading admission.
