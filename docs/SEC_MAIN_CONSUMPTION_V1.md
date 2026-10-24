# SEC disclosure research consumption in the incumbent Main

Task: `R1000-SEC-MAIN-CONSUMPTION-AND-MANAGER-CYCLE-CLOSURE-20261022`.
Control: #448 / #617. Research-only, Draft-only development.
Base: `71111d1bd2d43bdb84915fa2aa82af04cd80bd3a`.

The incumbent `H:/workspace/r1000-main-a4-20261020` was clean, on
`task/main-e2-rf-optional-h1-20261021` / `08b3fbaf73d5a8d4ea38ea68d7d4e7f2d8b9ba4d`.
Its prior owner had released custody. The exclusive existing `.git` integration
lease belongs to `EXISTING_MAIN_SEC_20261022` during implementation. No second
checkout, collector, scheduler or Main writer was created.

## Existing capability reuse

Source #655 `567e1fb9` and #658 `cbd982ee` causal deltas are integrated;
#666 `c89a082b` supplies the existing June/December return-selection path.
Shared inventories are reconciled with current master. #650 is already merged
and is untouched. #661's static watch list is source research context, not an
active return-ranked cohort; its active managers.csv change is not imported.

`run_form4_transaction_event_builder.build_ownership_research_events` preserves
every original parsed field and missing value. IDs bind issuer, accession,
form, raw-document SHA256 and document-local row identity. P remains a purchase
code with unknown venue. Form3 initial holdings, Form4 transaction/holding rows,
and Form5 delayed/supplemental reports keep their separate meanings. Derivatives,
joint owners, acquisition/disposition codes and footnotes remain in source_row.
The legacy scored alpha-study builder is separate and confers no score policy
change or automatic investment authority.

`run_13f_position_event_builder.build_disclosure_research_events` retains CUSIP,
security class, share type, option side, discretion and other-manager identity.
Ambiguous duplicates refuse. Complete comparable snapshots can distinguish
initial, new reported position, reported removal, shares increase/decrease and
weight-only change. The recorded denominator is the disclosed manager report,
not a fund NAV. No trade, total liquidation or particular fund attribution is
inferred. Incomplete mapping/parsing cannot replace a complete boundary or prove
an exit. Additive amendments cannot delete/overwrite constituents; corrections
need original accession lineage. The explicit standalone mode below now stores
and independently re-reads these typed disclosures. Main A2/Registry/A3 admission
still requires the existing coverage/mapping and authenticated adapter contract;
the Main consumer retains `13F_AUTHENTICATED_ADAPTER_NOT_YET_AVAILABLE`.

## Persistent path and authority

`tools/run_sec_research_consumption.py` reads the actual completed Source
generation, checks CSV/Parquet/summary hashes, counts and generation, and binds
the eligible issuer/accession/form/document/event scope. It reparses original
Form345 XML and compares the event's complete semantics before writing.

It calls the existing A2 `validate_events`, Registry `filing_request_record`,
A3 `filing_review_reference`, and FILING reassessment bridge. The existing
agent-board research root stores content-addressed bytes in `artifacts/` and
commits `control_plane/candidate_registry/filing_requests.json` last. The reader
rehashes stored event, intake, Registry, A3, raw and source-receipt references.
One exclusive lock covers the serial transaction. A failed attempt invalidates
current success; uncommitted artifacts cannot substitute for a committed manifest.

One accession/security produces one request, even with multiple transaction
rows. Replay across source generations preserves requests and notification
intent identity. No notification is sent. Explicit amendments retain parent
request and original submission-date relationships. Supplied existing thesis
references must match security, issuer and schema; otherwise intake refuses.

These are persistent **local research requests**, not a canonical A0 current
selection or accepted Drive generation. A2 remains V0 discovery-only. A3's
single filing reference remains `FILING_CONTENT_REVIEW_PENDING`; it does not
fabricate independent corroboration, Methodology, Moat, market/valuation or ER.
Full `evaluate_packet` and `build_reference_index` gates are unchanged. The SEC
acceptance clock is explicitly a publication proxy, never original publication
precision or historical PIT certification.

Fresh check, no-new-filings, stale and source-unavailable are distinct. The
36-hour source-check guard is independent of latest filing acceptance or a
historical data endpoint. Old successful artifacts remain historical; current
attempt state refuses fresh consumption after a failed prerequisite.

Example (actual caller paths and aware current time are required):

```text
python tools/run_sec_research_consumption.py --pit-root <verified-pit> --raw-dir <existing-xml-cache> --identities <supplied-identity-json> --accession <exact-accession> --decision-at <actual-aware-UTC>
```

## Standalone 13F management (2026-10-24)

Per the user's separation from the ongoing 7.1 integration, this stage completes
bounded disclosure storage before connecting it to system research consumption.
It reuses the existing collector, parser and typed event builder. It introduces
no scheduler, collector, active cohort or Main writer. The incumbent Main was
acquired from the released ETF owner, and current master
`edf85940f8908e1986158de76c2c25caf745f7d5` was integrated before implementation.

`tools/run_13f_position_event_builder.py --disclosure-research` requires explicit
holdings/index pairs, cached raw root, exact CUSIP map, manager CIK10 scope,
aware decision time and a separate output directory. The legacy scored event
mode is unchanged. The new mode is offline: no provider or Drive request occurs.
For example, substitute verified actual paths and current UTC for all brackets:

```text
python tools/run_13f_position_event_builder.py --disclosure-research --holdings <parser-root>/institutional_13f_holdings.parquet --filings-index <index-root>/sec_filings_index.parquet --raw-dir <selected-cache> --cusip-map <exact-map.csv> --manager-ciks <CIK10,CIK10> --decision-at <aware-UTC> --disclosure-output-dir <separate-owned-research-store>
```

The verifier recomputes selected-manager source checks from their retained
submissions bytes, index identities and clocks, CSV/Parquet hashes and complete
row parity. It requires the latest observed eligible filing in that manager's
recent submissions payload, plus every observed 13F in the selected comparison
interval (earliest selected acceptance through decision). A paired index/parser
omission cannot erase an intervening amendment even on the first generation.
A deliberately latest-only initial observation does not claim older comparisons;
the committed-prefix guard separately protects previously stored history.
It reparses each original XML with the exact map
and compares every declared column with parser rows and checkpoint semantics.
Physical document hashes and the legacy universal-newline parser text hashes
are separate. Amendments require an earlier original in the same period and a
cover bound to filer CIK, report period, amendment flag and form; the physical
cover hash accompanies the constituent evidence. Archives outside `recent`
are explicitly unsupported by this mode and refuse rather than guessing a link.

An exclusive store lock protects content-addressed source/event/table artifacts.
`pending_generation.json` is independently read and recomputed before the atomic
`current_generation.json` pointer is committed. `attempt.json` distinguishes
BUILDING, completed storage and refusal. Readers require both the verified
pointer and the matching successful current attempt. Stale, unavailable, cached
unchecked or malformed prerequisites block current reads; named owned-store
CLI prerequisite failures revoke old current success. Lock contention and
unowned paths remain untouched. Explicit `historical=True` preserves prior
evidence without certifying freshness. Readers recheck the 36-hour source clock
against actual current UTC, so backdating a decision cannot revive a stale store.

Each generation contains the full verified comparison prefix. A missing or
changed prior accession refuses incremental processing; an old filing cannot
be inserted behind the committed acceptance boundary. Code or map changes
require explicit new derivation handling and cannot masquerade as SEC amendments.
Same input replay preserves pointer/event bytes and produces zero new events or
notification intents. A refreshed check may produce a new generation with zero
new events. No notifications are sent. Parent generation IDs are history links;
comparison operands and their originals are self-contained in each generation.

Empty reports require explicit verified `PARSED_EMPTY` receipts. Quarter gaps
start a new observation boundary. NEW HOLDINGS retains constituent provenance
from earlier reports; a removal keeps the previous source row and both source
documents. All referenced constituents of the weight denominator remain bound.
Mapping-incomplete reports permit content review and cannot prove removals.
Known incomplete revisions with verified original lineage also block that
period as a next-quarter comparison operand. A later additive report cannot
skip the missing revision or restore
completeness; a fully verified RESTATEMENT can establish a complete boundary
again. Verified original identity is retained separately from complete snapshots:
even an original with unmapped constituents can anchor a full same-root
RESTATEMENT. The restatement records the original's document evidence and starts
an observation boundary; the next quarter can compare against that complete
restatement. Additive, unknown-type and wrong-parent reports cannot recover an
incomplete original. Blocked comparisons retain every unresolved accession and raw evidence
and produce an initial observation without a shares delta.
Wrong-parent or unlinked revisions remain unaccepted review and cannot poison
an accepted comparison boundary.
Ambiguous duplicate security/class/discretion rows refuse; no keep-last or
unreviewed aggregation is used. Missing quantities remain missing and refuse
position comparisons. Due-quarter coverage and aggregate analysis are separate
existing gates; this store declares both unadmitted, without requiring fund NAV
to discover otherwise eligible disclosures. No A2, canonical Registry, A3,
portfolio, scores, targets, orders or accepted Drive state is written here.

## Earlier Form345 execution and remaining dependencies

The existing collector checked MU, CIK `0000723125`, on
`2026-10-22T10:51:25.328042Z`. It returned 27 Form4 accessions; all 27 original
XML files were reused and freshly parsed into 227 rows. Coverage is exactly one
checked issuer. The current SEC submissions bytes report latest accession
`0001568238-26-000003` accepted `2026-10-21T03:03:21Z`; its three S-code rows
produce one stored candidate research request. The historical Source packet's
`2026-10-20T23:03:21Z` clock is retained as a conflicting old observation and
does not supply the fresh generation. Resume entries now bind source clocks
and parser bytes and replace the whole reparsed accession, including empty rows.

Actual first local persistence created request
`SEC_REQUEST:37098deef9dd06f16567325bc02423d62f16a71177421904fc7344531632b6c7`.
It has three typed events and three pending A3 source references, an A2 handoff
and a Registry record. Subsequent actual replay, final Native/CI and independent
A6 evidence are recorded in the task's final execution receipt and Draft PR.
Form3/5, amendment, stale/unavailable and corruption cases are separately labeled
fixtures unless an actual-source execution receipt says otherwise.

The imported 13F sample remains partial: three-manager original restore had
173 rows/65 mappings and substantive coverage 1/3; the static ten-manager
sample had 260 rows/48 mappings. These are separate historical generations,
not current complete coverage. The Q3 2026 filing deadline is not yet due at
this decision time; absence of that quarter alone is not an error. Current
13F authenticated Main comparison admission, actual full A3 and accepted Drive
research admission remain open. Standalone comparison/storage is described
above. Source collection eligibility does not require fund NAV.

## Performance sources observed 2026-10-22

| Source | Material actually observed | Method and date | Access / use boundary |
| --- | --- | --- | --- |
| [HFR fields](https://www.hfr.com/database/hfr-database/field-definitions/) | Field definitions only; no fund return records acquired | Fund ID, reporting style, currency, monthly ROR/NAV and product-class fields are documented | No database subscription/API entitlement established |
| [With Intelligence](https://www.withintelligence.com/solutions/hedge-funds/) | Product page only; no fund return records acquired | Manager-sourced fund/allocator intelligence and index products advertised | Demo/subscription; export and automation terms not established |
| [HedgeFollow method](https://hedgefollow.com/how-we-rank-hedge-funds.php), [screen](https://hedgefollow.com/top-hedge-funds.php) | Public screen of 20 manager-weighted three-year disclosed-stock return estimates observed | Top20 stock proxy, beginning-of-Q3-2026 label; MW and EW are distinct; stars incorporate risk | [Terms](https://hedgefollow.com/terms.php) prohibit automated access and restrict copying/commercial use; no further automation or admitted data producer is configured |
| [WhaleWisdom features](https://whalewisdom.com/info/features), [API](https://whalewisdom.com/shell/api_help) | Features/API documentation only; no performance export acquired | Holdings clone/backtest results are not fund NAV | API account/key required; subscription coverage differs; documented 20 requests/minute; no account created |
| [PSH NAV](https://pershingsquareholdings.com/performance/nav/) | One actual fund's published NAV/return series observed: public shares, USD, 20 Oct 2026 NAV78.88 and YTD -6.9% | Net-of-fees dollar return includes distributions; estimates unaudited unless noted | [Terms](https://pershingsquareholdings.com/terms-of-use/) restrict use to private informational purposes and prohibit scraping; no automated producer or republication of a dataset |

PSH fund/share-class results cannot be attributed to every position in PSCM's
manager-wide 13F or to its other funds merely by matching CIK. Different
strategies/vehicle types require separate comparable groups. No combined
actual-fund-NAV ranking was acquired. Observed public screen values do not
establish exact window endpoints, currency, access rights or the June cutoff.
They are not relabeled as a reviewed performance receipt.

The existing selection tool's actual current attempt therefore returns
`missing_comparable_performance_evidence`, selected **0**, next cycle
`2026-12-05`. Successful fixtures select ten or more by same-window, currency,
method and total return, with CIK tie-breaking and a 92-day window-age bound;
they do not certify actual performance. October observations cannot be backdated
into June's frozen selection. No AUM/fame/mixed-score substitute is admitted.
Required next input is a rights-cleared, identity-bound comparable performance
receipt, not another generic development permission or a paid purchase.

No fullrun, score-weight activation, target, portfolio, paper/broker/order,
promotion, Ready, review-complete attestation or merge is authorized here.
