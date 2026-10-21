# Return-ranked manager review and holdings-driven universe research

Task: R1000-SEC-13F-FORM345-FRESHNESS-CONSUMPTION-CLOSURE-20261020; control #448.
Design clarification: 2026-10-22 KST. Source implementation base:
`ca37fa7138ccd81f8cbb74ecb92a503979d4bb11`.

## Intended behavior and current implementation

Every six months, rank comparable fund returns and propose at least ten verified
managers to follow. Between reviews, process their new filings when available.
New positions, exits, additions, trims and weight changes request security
universe research through existing A2/Registry/A3; they do not automatically
change the trading universe, scores, portfolio or orders.

| Concern | Existing behavior | This change / remaining boundary |
| --- | --- | --- |
| Review schedule | June 5 / December 5, 05:00 UTC | Reuse the same workflow and cron; fixed calendar cycle, no 183-day drift |
| Manager ordering | Quality 40%, AUM 18%, hit rate 14%, sample 12%, concentration 8%, coverage 5%, seed priority 3% | Keep as explicitly legacy diagnostics; a separate output in the same tool orders comparable total returns only |
| Claimed performance | `avg_excess_return` measures candidate forward-return observations | Never treat it as fund NAV or a cutoff-bound selection history |
| Static watch ten | Draft #661 adds a public 13F holdings-proxy watch cohort | It is not actual top-ten fund NAV or dynamic half-year selection; the receipt path here supersedes that claim |
| Minimum size | At most 40 diagnostic rows; no ten-manager eligibility floor | Default ten, configurable upward; insufficient evidence blocks the selection |
| Replay | Candidate CSV overwritten | Freeze per-cycle JSON; identical replay preserves it, changed evidence conflicts and blocks current consumption |
| Collection | Existing manager builder and 13F refresh/parser | Preserve them; selection is a proposal and never overwrites active `managers.csv` |
| Research consumption | Legacy 13F event builder and pure A2/A3 interfaces exist | Actual authenticated admission and persistent consumption remain Main-owned and NOT_RUN here |

Actual fund performance and returns on disclosed long holdings are different
measurement bases. The default requested basis is `FUND_NAV_NET_TOTAL_RETURN`.
An explicitly requested `DISCLOSED_13F_LONG_PROXY_TOTAL_RETURN` cohort must keep
that label. There is no automatic substitution. Matching observation window,
currency and methodology are mandatory within each ranking. AUM, fame and
missing-return zero imputation cannot affect return rank. Ties use CIK for
determinism. The ranking covers the supplied verified manager universe, not
every hedge fund in the world. Inactive but identity-verified seeds may be
considered for a new research cohort; no seed is automatically activated.

A three-year common return window is a proposed research default for the
performance producer, with shorter-window stability diagnostics kept separate.
This PR does not invent a historical return series or approve an economic
selection policy. Fund/share-class identity, fees, distributions, currency,
backfill/survivorship and provider methodology require Source review before
actual use. The selector verifies declared fields and evidence byte identity;
it does not authenticate a provider or independently recompute NAV.

## Performance input and output

The existing workflow restores `outputs/sec_evidence_signal_audit`, including
`manager_performance_evidence/receipt.json` and its relative evidence objects.
No new collector or scheduler is introduced. An upstream reviewed performance
producer must supply the missing comparable returns; the old manager-alpha CSV
is diagnostic only. Missing receipt means BLOCKED, even when seeds exist.

The following is a schema example, **not measured fund performance**:

```json
{
  "schema": "sec-manager-performance-evidence-v1",
  "selection_cycle": "2026-12-05",
  "performance_basis": "FUND_NAV_NET_TOTAL_RETURN",
  "window_start": "2023-11-30",
  "window_end": "2026-11-30",
  "currency": "USD",
  "methodology_id": "reviewed-net-total-return-method-version",
  "calculated_at": "2026-12-04T00:00:00Z",
  "managers": [{
    "manager_cik": "0000000001",
    "status": "COMPLETE",
    "total_return": 0.0,
    "window_start": "2023-11-30",
    "window_end": "2026-11-30",
    "currency": "USD",
    "methodology_id": "reviewed-net-total-return-method-version",
    "performance_basis": "FUND_NAV_NET_TOTAL_RETURN",
    "source_available_at": "2026-12-03T00:00:00Z",
    "evidence_file": "immutable-source-object.json",
    "evidence_sha256": "<actual SHA256 of source bytes>"
  }]
}
```

`total_return` is a decimal cumulative total return over the stated common
window, not a percentage string, average event alpha, AUM growth or a missing
value. Real zero is valid. Null, nonfinite, stale/incomplete, unverified identity,
incomparable records and invalid source bytes are excluded with reasons.
Duplicate CIKs or malformed receipts refuse the attempt. Source paths must
remain below the receipt's directory. All available/calculated timestamps must
be aware and no later than the cycle cutoff. Today's ranking therefore cannot
silently rewrite a past June selection using October data.
The common window must end within 92 calendar days before its cycle cutoff;
this explicit Source research freshness guard accommodates a latest-quarter-end
window and rejects old performance relabeled by a recent calculation timestamp.

Outputs under the existing institutional-signals directory:

- `manager_performance_selection.json`: current attempt, including blockers,
  coverage and evidence hash. This is not an accepted-state pointer.
- `manager_selection_YYYY-MM-DD.json`: frozen successful research proposal.
- `manager_performance_selected.csv`: the same selected rows, empty on refusal.
- Existing `manager_reselection_candidates.csv`: legacy diagnostic inventory,
  clearly distinguished from the return-ranked selection in summary/report.

Success means a research proposal was built, not active roster publication.
`source_authenticated`, `canonical_write_allowed`, and
`production_activation_allowed` remain false. The summary is invalidated before
work starts, together with current selection JSON and selected CSV, including
when timestamp parsing or universe loading fails. A failed current attempt cannot reuse an old successful selection
CSV as current success; frozen cycle bytes remain preserved.

## Main connection using existing paths

No replacement Main writer/worktree is authorized by this Source implementation.
The existing Main owner must first admit exact source generations and identity
mapping, then implement the remaining adapter at the existing interfaces.

| Stage | Reuse | Required linkage |
| --- | --- | --- |
| Cohort proposal | `run_sec_13f_manager_reselection.py` | Cycle, selection ID, basis/window, ranked CIKs and evidence hashes |
| Active research cohort | Existing reviewed manager control plane/builder | Exact proposal admission; preserve prior cohort history and old holdings |
| Filing source | Existing submissions collector, scoped restore, parser/checkpoints | Manager, expected quarter, accession, accepted/available clocks, amendment type, raw hash, complete parsing and storage receipt |
| Typed position event | `run_13f_position_event_builder.py` | Comparable manager/security snapshots, mapping version and constituent row provenance; retain distinct classes/options/discretion/other managers |
| Existing security review | `candidate_reassessment_bridge.py` | `FILING` observation and stable causal event; affected thesis/risk slices with source refs |
| New security discovery | `research/a2_research_intake_v1.py` | Existing typed event schema and authenticated identity/source graph; discovery/assessment proposal only |
| Candidate reference | `research/candidate_registry_v1.py` | Existing reference bundle and state-delta rules; no fabricated current pointer |
| Research evidence | `research/a3_candidate_packet_v1.py` | `SEC_FILING` graph rows with actual raw/extracted evidence and affected pillar references |

Main's legacy normalization currently keeps the last manager/accession/ticker
row and can discard distinct disclosed positions. It must not be used as a
certified aggregate until that ambiguity is resolved. Weight is computed from a
complete comparable report with its denominator recorded. Preserve both shares
delta and weight percentage-point delta: weight changes can also reflect price
or denominator changes and cannot alone prove a trade. New/exit classification
requires two comparable complete snapshots. The first observed report is an
initial boundary, not evidence of new buying. Partial/mapping-failed/missing
reports cannot establish an exit. A manager leaving the selected cohort cannot
establish that its securities were sold. NEW HOLDINGS amendments are additive;
RESTATEMENT corrections supersede explicitly, with correction lineage retained.

Stable review identity must bind manager, report period, accession/revision,
security identity and semantic position change. It must not depend on DataFrame
row number, processing clock or the current cohort generation. Multiple selected
managers changing one security should aggregate supporting references without
duplicating a security review for the same causal filing event. Persistent
replay and notification deduplication require the existing Main durable path.

Required Main lifecycle receipts:

1. New qualified filing: source bytes → typed event → A2 candidate or existing
   security reassessment → Registry reference → A3 actual evidence reference.
2. Same filing replay: no second candidate/review/notification; refs unchanged.
3. Correction: explicit revision link and one affected review, old refs retained.
4. Stale: no actionable discovery; existing research is flagged for review.
5. Source unavailable/partial: unknown with cause; no zero holdings, false exit,
   removal or adverse score.

Form3 initial ownership, Form4 transactions and Form5 delayed/supplemental
reports remain a parallel source family through those same Main interfaces.
Preserve codes, derivative status, owners and footnotes. P alone does not certify
open-market execution. Existing Source #655/#658 freshness and restore fixes are
separate pending Drafts, not silently deployed dependencies of this PR.

## Execution limits

Native contract fixtures validate selection/order/replay/refusal only. Real
comparable fund-performance evidence is unavailable in this workspace. No actual
return-ranked top ten, current cohort admission, authenticated SEC frozen
generation, persistent A2/Registry/A3 consumption or notification is claimed.
Existing prior real filing receipts cover 20 checked Form345 issuers and eleven
distinct 13F managers across separate generations; those counts do not establish
fund performance, complete historical comparison or whole-universe coverage.

The incumbent Main H: worktree is inaccessible here. Main admission/connection
and its independent lifecycle validation remain pending that owner/environment.
No fullrun, live score/weight activation, target, paper/broker/order execution,
gate relaxation, promotion or merge is part of this implementation.

The new active unittest suite runs through the existing registered filing-
freshness smoke. The frozen 235-program Tier-1 count is preserved; only the
Manual Foundation dependency inventory gains this suite and its producer.
