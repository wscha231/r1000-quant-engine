# Liquidity driver context V1 — implementation and handoff

Status: RESEARCH_ONLY, additive candidate; not an operating allocation change.
Tracking issue: #430. Related coordination: #424 / #426 / #429.
Base: `bcb14c06613e34420ce7988e5bb1ac5547b22b57`.

## Implemented

- `tools/liquidity_driver_context.py`: 17 source contracts; cutoff-aware current,
  archived-vintage and published-snapshot selection; six separated context axes;
  independent review flags for cash defense, duration extension and equity reentry.
- `tools/liquidity_driver_io.py`: existing Lake receipt/identity adapter; optional
  six-source collection callback; immutable local diagnostics and CLI.
- Two smoke files: 56 distinct offline tests, including fixture CLI execution,
  repeated publication, source corruption, future/withdrawn values and failed writes.
- Dedicated secret-free, schedule-free Python 3.11/3.13 PR CI invokes the existing
  protected validation runner through `--include` / `--only`. It does not edit the
  runner, its frozen anchors, canonical risk policy or production configuration.

The source callback stages TOTCI, DPSACBW027SBOG, DRTSCILM, DRSDCILM, WLCFLPCL
and T10YIE through the existing bounded FRED fetch/parser and `Lake.dataset`.
It does not call publish, issue a receipt, alter a scheduler, or write a portfolio.
These callback/parser tests mock the network/parser boundary; they are not a live
FRED collection or a test of every existing parser implementation.

## Decision contract

| Situation | Candidate diagnostic, not an order |
|---|---|
| Fed balance sheet shrinks, bank credit expands, funding stable | Bank-credit-supported hypothesis; no forced cash increase |
| Fed assets expand while funding/credit stress rises | Stress evidence is not neutralized by balance-sheet growth |
| RRP near zero | Dollar change and remaining-buffer ratio; no percentage explosion |
| Policy discussion only | Stage and source metadata, no inferred new dollars |
| Inflation/yields rise | Duration risk; not automatically a sell-everything signal |
| Credit contracts while inflation moderates | Review duration independently of the cash decision |
| Funding/spreads/breadth recover | Two new daily observations before reentry review |
| A new download repeats the same SLOOS observation | Not a new confirmation |
| Critical data missing | DEGRADED; no new reentry confirmation, no forced liquidation |
| Existing canonical CRISIS or kill switch | Preserved exactly by read-only context attachment |

Multiple evidence families are not proof of statistical independence. The baseline
thresholds and data-age tolerances are proposals, not fitted or OOS-approved alpha.
Cash/duration/reentry flags never assign percentages, choose securities, issue
orders, lower an existing cash minimum or modify the canonical regime.

## Provenance and temporal controls

Current revised histories are admitted no earlier than their retrieval. The Lake
adapter restores retrieval/availability fields that the existing collector removes
from normalized current rows. It rejects uncommitted pending data, mismatched
receipts, invalid source units, stale-retained datasets and corrupt raw hashes.
`Lake.verified_execution()` and the complete Lake restore remain prerequisites;
there is no macro-only shortcut around retained financial-pack validation.

Archived vintages use the existing conservative end-of-New-York-day convention.
Overlapping intervals, invented intraday availability, expired vintages without
successors and explicit withdrawals cannot become numeric current observations.
Growth windows reject flagged structural breaks, null observations and large gaps.
Source funding rates must share an economic day. Daily refresh of the same source
session cannot increment reentry confirmation. Future prior-state timestamps,
changed code/config identity and regressed observations cannot restore old approval.

The generic input CLI validates the packet contract, not the economic correctness
of arbitrarily caller-supplied values. A hash does not authenticate a publisher.
Synthetic fixtures remain labeled `SYNTHETIC_FIXTURE`; other unbound caller packets
remain `CALLER_PACKET_NOT_INDEPENDENTLY_VERIFIED`. Policy metadata needs an upstream
verified document-ingestion/review path. No output certifies historical PIT or
completeness of all economically relevant liquidity channels.

## Use from the existing research cycle

```python
from tools.liquidity_driver_context import evaluate, attach_to_canonical
from tools.liquidity_driver_io import from_verified_lake, publish_diagnostic

# lake must already be restored through the approved existing read-only path.
packet = from_verified_lake(lake, mode="current")
# Supply BREADTH_ABOVE_200D only from the existing point-in-time universe/price
# producer, retaining its evidence. Missing breadth deliberately blocks reentry.
context = evaluate(packet, as_of=decision_time_utc, source_commit=exact_code_sha)
monitor_copy = attach_to_canonical(existing_crisis_state, context)
# This copy preserves every canonical field. Do not replace an accepted book.
manifest = publish_diagnostic(research_output_directory, context)
```

In the existing collection function, the optional
`stage_liquidity_sources(lake, start, through)` callback belongs before the existing
single publish/restore/study/receipt sequence. Reader and writer roles must remain
separate. The callback is NOT scheduled or wired into that daily function by this
PR. Review and test its full-cycle integration before activation; do not add a
second cron or pretend that staged records are durably accepted.

CLI for a prepared packet:

```bash
python tools/liquidity_driver_io.py \
  --input input.json --as-of 2026-09-14T20:00:00Z \
  --source-commit <exact-implementation-commit> --output-dir research-output
```

Optional `--prior` accepts the previous diagnostic, not a portfolio state.
`--expected-input-sha256` binds raw input bytes separately from the decoded data
hash. Exit 0 means the selected input contracts are complete; exit 2 means a
PARTIAL/DEGRADED diagnostic was written; exit 3 blocks on input or persistence.
None means trading readiness. `context.json` and `report.md` are written under a
content-addressed directory, verified before `manifest.json`. There is no mutable
latest pointer, accepted ledger, source deletion or implicit Drive upload.

## Validation performed

Python 3.13.5: all 56 unique tests passed in normal and `-O` modes, treating
ResourceWarning as an error. CLI fixture runs produce immutable reports and
reject hash mismatches. This is code/contract evidence only. Python 3.11 and
remote full-repository CI require their own observed run; local results do not
claim independent review or a completed GitHub merge.

Reproduce locally in the complete repository:

```bash
python -W error::ResourceWarning -m unittest discover -s tests -p 'liquidity_driver_*smoke.py' -v
python -O -W error::ResourceWarning -m unittest discover -s tests -p 'liquidity_driver_*smoke.py' -v
```

No real Drive archive was revalidated end-to-end in this implementation session.
The connected folder/commit inventory was located; this is not a new 503 MB pack
verification. No actual current-market portfolio, fullrun, OOS return, paper event,
accepted state or source-secret access occurred. Public-source download from this
runtime failed, so dependency integration is delegated to the complete-repository
CI rather than misrepresented as a locally reproduced full checkout.

## Remaining gates and scope limits

Actual daily-cycle wiring, real-source collection/receipt validation, the verified
breadth producer, policy ingestion and immutable previous-diagnostic restoration
remain integration work. Nonbank credit/issuance, NDFI lending, Treasury settlement
and maturity composition, real yields, institutional constraint mapping and bank
valuation are not implemented as complete standalone models here. HY spread is
only a market-credit proxy. Aggregate loan growth is not certified organic growth.

No bank stock ranking, all-universe portfolio weights, CAGR gain or MDD reduction
was calculated. Evaluate baseline vs credit addition vs full context with genuine
vintages, execution lags, costs and cash carry before changing the champion. Track
missed rebounds and excessive-cash opportunity cost as well as MDD.

## Shared lesson entry — 2026-09-14 / issue #430

First 28-test pass found an expired archived vintage incorrectly remaining usable;
fixed by explicit expiry/withdrawal handling and added overlap tests. A test also
incorrectly demanded a fatal error for a boolean source: source quarantine is the
intended result; NaN/Infinity still fail canonical serialization. Further checks
prevent known funding/credit stress disappearing when companion history is missing
and prevent sustained high primary credit looking safe because its delta is zero.

Use TOTCI for weekly C&I, not monthly BUSLOANS. Separate SLOOS tightening from
stronger demand. Missing is not zero. An immutable file is not an accepted trading
record. Never count the same release twice or turn a policy headline into money.

## Primary metadata references

- https://fred.stlouisfed.org/series/TOTCI
- https://fred.stlouisfed.org/series/BUSLOANS
- https://fred.stlouisfed.org/series/DPSACBW027SBOG
- https://fred.stlouisfed.org/series/DRTSCILM
- https://fred.stlouisfed.org/series/DRSDCILM
- https://fred.stlouisfed.org/series/WLCFLPCL
- https://fred.stlouisfed.org/series/WALCL
- https://fred.stlouisfed.org/series/WRESBAL
- https://fred.stlouisfed.org/series/WTREGEN
- https://fred.stlouisfed.org/series/RRPONTSYD
- https://fred.stlouisfed.org/series/T10YIE

Metadata was consulted for source meanings/units, not to certify the cached web
page's observation as today's market. Raw redistribution rights remain source-
specific; this public PR contains synthetic tests, not licensed source histories.
