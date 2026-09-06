# H1a: current research score handoff and internal report

## Purpose and implemented boundary

The AI fund-manager service needs current data, model diagnostics, a continuous
accepted account, and attributable performance before publishing portfolio
claims. This first implementation removes the monitor's unconditional null
engine-score field and adds an internal HTML report to the existing daily job.

Base: `8cd11a5f749a0996e41fbae9499e445bee5adde6`.
Branch: `codex/run287-research-score-handoff-20260906`.
Related roadmap: issue #396 and the user's September 6 implementation plan.

The consumer reads the existing final score-stack export. It does not change
the active model, recalibrate its scale, add a 13F/Form 4 bonus, select holdings,
assign portfolio weights, or treat the export as a validated return forecast.
The producer's status explicitly remains NONRANKING.

## Data contract

1. Select the latest eligible master workflow run, including failures. Verify
   artifact run/commit identity and the complete ZIP SHA-256.
2. Read the attempt-specific upstream receipt. Its exact source-bundle path
   and SHA-256 select the bundle; the bundle selects decision and score-stack
   manifests. The stack selects its score-only manifest and ticker-order CSV.
3. Verify every consumed member hash and both decision-manifest relations.
   Only explicit `outputs/` members or their canonical Linux Actions checkout
   paths are accepted. No ZIP extraction, basename search or latest-file
   discovery is performed. Same-close reuse keeps the original producer paths.
4. Require ready schemas, the expected US close, ordered availability/decision/
   execution times, six active prediction heads, finite values, unique tickers,
   matching row counts, code identity and consistent frozen model metadata.
5. Preserve the original score, including zero and negative values. Display
   eligibility, quarantine, missing-field and neutralization diagnostics.
   Missing or blocked inputs remain null with an explicit reason.

The hash checks establish the exported evidence's provenance. They do not
recompute all model inputs, establish historical PIT universe completeness, or
validate the model's investment performance. Original producer blockers apply.

## Daily outputs and failure handling

The existing 08:25 UTC / 17:25 KST schedule produces `report.json`, `report.md`,
`research_queue.csv` and the new `report.html` in a new run-attempt directory.
The HTML report works offline and supports ticker, market and score-coverage
filters. It makes no provider, model, telemetry or account requests.

`current_engine_scores_ready` means the complete consumed score export passed
the consumer contract; it is not full watchlist coverage. Each watchlist row
reports its own availability. `current_investment_ranking_ready` and
`current_portfolio_ready` remain false for this source contract.

A broken score graph does not discard independently verified price or recovery
diagnostics. A failed upstream run cannot supply current scores. The monitor
still emits an attention report, so successful report generation cannot hide
source failure. The next scheduled attempt rereads current metadata and emits
a separate snapshot; it never reruns a transactional operating job. Artifacts
retain the existing 45-day policy; they are not permanent customer history.

## Current operational evidence

On September 6, master remained the base above. The latest operating run
`33947924742` failed; artifact `9964270735` has SHA-256
`f1fac17d42f0be50e627a58b9ac641f1491ac85779b4c9573e84ef193bc192f3`.
This is failure evidence, not a current accepted-account receipt. H1a must show
that limitation even after its code and tests pass.

## Validation and next implementation gates

Local validation passed the 18 monitor regressions, the registered workflow
artifact smoke suite, Python compilation, report JavaScript syntax, and diff
whitespace checks. No browser rendering or investment performance test was run.

Transport note: the local Git push lacked credentials. The connected GitHub
Git-data transport may publish only the already-committed local blobs/tree,
with exact blob and tree identity comparisons before advancing the review
branch. This preserves the local worktree, explicit-path staging and validation
path; it is not a remote per-file editing workflow. User-owned dirty data is
excluded. A remote commit may have different author/time metadata; its source
tree must be identical before review.

The existing registered monitor smoke entry now exercises the complete ZIP
collection path and the valid score handoff, including absolute paths and
original-attempt reuse. Negative cases cover cross-attempt relations, bad
hashes, traversal, duplicate members/tickers, size limits, stale/future data,
failed runs, code mismatch, constant/nonfinite predictions and unsafe flags.
HTML checks cover escaped evidence and missing-versus-zero rendering. Test
fixtures contain artificial values and are never published as live evidence.

Next causal increments, each with its own evidence and review:

- H1b: expose a verified accepted-account read projection with source authority,
  immutable head/session identity, reconciled cash/positions and transaction
  history. The existing recovery blocker must be handled with its exact
  recovery packet; a monitor must not bypass it.
- H2: maintain a separate service-owned $100,000 representative paper account
  with an immutable launch and daily book/trade/valuation snapshots. Preserve
  separate historical experiment and forward-operation performance labels.
- H3: record SEC acceptance times and stable identities for 13F/Form 4 and
  earnings evidence; use AI for cited extraction and challenger proposals.
  Validate coverage and licensing before displaying paid-provider data.
- H4: preregister challenger experiments, keep a final untouched evaluation
  period and compare net costs, CAGR, MDD and turnover before any promotion.
- H5: publish the verified read projection through authenticated website/API
  access, add subscriptions, and operate scheduled data-quality and recovery
  monitoring. Long-term customer history requires durable storage beyond
  Actions artifact retention.

No current holdings, CAGR/MDD, profitability improvement, commercial launch or
autonomous operating recovery is claimed by this first increment.
