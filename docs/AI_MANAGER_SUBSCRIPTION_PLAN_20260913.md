# [PROJECT_HANDOFF] AI manager subscription: implementation plan and first slice

Date: 2026-09-13 KST. Issue: #424.
Inspected master: `e39d4f5338b186acdd7753a6007dfbea92211a51`.
Scope: RESEARCH_ONLY, internal development; not commercial launch or broker automation.

## 1. Product decision

The user is building a paid subscription to AI-managed MODEL PORTFOLIOS and
investment research, not an automatic broker-order program. Customers receive
common research, allocation rationale, thesis changes, risk commentary and
properly labelled model results. No customer funds, broker credentials, personal
account-based allocation, automatic execution or guaranteed return is in this
initial product. The existing broker/accepted account ledger stays untouched.

A model portfolio still requires explicit accounting of simulated holdings,
corporate actions, cash and costs. Such an account is not a customer account and
its performance is not an investor's actual return. Paid release and performance
advertising require separate legal and data-distribution reviews.

## 2. Grounded current state and reuse

- PR415 is Draft/unmerged at `e39387bbc442e4de35d771ee19ba7487c5683555`.
  Its REAL current audit provides 1,118 securities / 1,106 mapped CIKs,
  1,115 parsed Companyfacts securities, 786 usable current generic quarters,
  989 revenue YoY observations (some stale), 831 accelerations (some stale),
  and 574 CFO-minus-capex TTM observations. This is NOT complete financial history.
- PR405 is Draft/unmerged at `9435b2c1f04f9a0c82f8c1ce74ddd55bdfe0a3ef`.
  Reuse reviewed quality/evidence/scenario and funded research decision contracts;
  do not merge the entire old dependency stack or call its synthetic tests alpha.
- Current Pages contract `docs/PUBLIC_PROJECT_RESULTS_20260912.md` connects
  read-only project diagnostics. It documents 33-name monitoring, not a
  whole-universe AI manager, and separates account performance from fresh quotes.
- Read-only Drive inspection on this task confirmed a retained Companyfacts ZIP
  (1,375,516,516 bytes, modified 2026-05-07). Metadata is not restored bytes or
  current coverage. Private Drive IDs are intentionally absent from this file.
- The actual Sept11 Drive estimate queue lists 993 names, 50 fresh successes,
  10 stale successes and 932 uncovered retries plus one placeholder. This is a
  DIFFERENT identity set from the 1,118-name financial cohort; counts are not a join.
- The user supplied historical audit says PR263 previously connected 990/992 raw
  Companyfacts, PR295 adds changed-filing updates and PR411 adds immutable/dedup
  storage. Preserve these as HISTORICAL AUDIT INPUTS until the exact required paths
  are checked during integration. Do not label them newly re-run in this slice.

## 3. Implemented now

`tools/subscription_manager/readiness.py` is a standard-library, offline adapter.
It does not call a model, vendor, broker or Drive and does not generate stock picks.

1. Pin BOTH input-file SHA256s and bind financials to their exact source cohort.
2. Reconcile every requested identity and declared count; reject a small watchlist,
   duplicates, invalid CIKs, future observation/filing dates and bad reporting units.
3. Keep source/current-quarter/FCF/RS coverage separate. Keep missing firms in the
   denominator and issuer-deduplicate the reuse queue, not the security inventory.
4. Retain the embedded raw-fact EXCERPTS already present in the supplied derived
   snapshot. Index CIK, accession, namespace, tag, currency, period, filed date,
   observation time and source hash claims in SQLite. Reject conflicting values
   within one accession/period; retain distinct amendment versions.
5. Exact accepted_at is NULL. All copied excerpts remain current observations,
   not authenticated SEC raw-body recovery or retrospective PIT approval.
6. Generate one reuse/verification task per issuer plus unresolved identity tasks,
   beginning at 2016 with lookback-specific earlier warm-up. Actual missing periods
   and historical coverage remain NULL pending a full raw inventory. No first-N
   fetch list or inferred ten-year coverage from `quarters_observed` is created.
7. Write a new immutable-by-policy local run directory, private input snapshots,
   coverage/queue, SQLite index, aggregate readiness JSON and internal HTML preview.
   Verify copies using an externally pinned export-manifest hash and every member
   digest. Existing output directories are rejected; no latest pointer is advanced.
8. Publication is always disabled in this first slice: no weights, no performance,
   no paid access, no orders, no customer asset-management flag. A successful audit
   process exit means only audit success. It never changes a blocked upstream flag.

No original pipeline, selector, model, benchmark, accepted ledger, Pages deployment
or protected validation path is modified. New dedicated CI runs offline fixtures
on Python 3.11 and 3.13, normal and -O. Central Tier-1 integration remains subject
to the existing protected-path contract; no existing required check is removed.

## 4. Actual data use and validation

The prior conversation package was used after SHA256 verification; no broad vendor
re-download and no two-ticker substitution occurred.

- Cohort SHA256:
  `4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4`
- Derived financial snapshot SHA256:
  `0bbf35ca1aa08f107785ad36555e8846fcd1f1ebf7a5e7fefe0fa71ab4aef321`
- Price date: 2026-09-09. Financial filed-date cutoff: 2026-09-11.
- Original observation time: 2026-09-12T01:05:39.720637+00:00.
- Recomputed retained distinct fact versions: 14,704.
- Requested/mapped/collected/current quarter/FCF counts remain 1118/1106/1115/786/574.
- Exact accepted-at verified: 0. Historical cell coverage: unknown, NOT 100% or 0%.
- 36 offline regression cases, including >1,000 identities, missing/null/zero,
  share-class dedup, issuer/currency/period/version conflict, date parsing,
  hash binding, tamper, unlisted files, symlinks and clean-copy restoration.

The SQLite index preserves excerpts already in the input, not 14,704 newly downloaded
filings, companies or full financial statements. A repeated local copy/restore test
is not proof of an authenticated Drive upload or restore. SQLite is a local rebuildable
index, not a shared database operated in a Drive sync folder.

## 5. Full data plan (not completed by the first slice)

### Historical scope and point-in-time correctness

Build a security master with permanent IDs, CIK, share classes, issuer life cycle,
listings/delistings/mergers/spin-offs, home market, currency and dated ADS ratios.
Use 2016 through the latest completed reporting period as the default core window;
fetch earlier years when five-year factors or model warm-up require them. Do not
impose nonexistent pre-IPO reports or apply today's 1,118 names to historical years.
Macro research needs 20-30 years where available, with ALFRED vintages/release times.

Inventory existing SEC Companyfacts/Submissions/FSDS/notes archives by bytes and
hash first. Stream a restored bulk ZIP once to inventory all needed issuers. Raw
income/balance/cash-flow/equity/comprehensive-income statements and notes/business
text are separate from standard extracted XBRL facts. Companyfacts alone does not
certify complete statements, company extensions, dimensions, notes or transcripts.
Use original filing exhibits for gaps. 20-F/40-F and financial 6-K/official IR need
native currency, ADS, annual/semiannual/quarter distinctions; no fictional quarters.

Separate H1 repairs MUST reproduce and correct the canonical pipeline's future-Q1
revision changing old Q2 and integer FSDS YYYYMMDD issues. This slice's defensive
parser does NOT repair `r1000_pipeline.py`. Derived quarterly facts must join each
component to accession accepted_at, select versions as of a cutoff and use max
component availability. Amendments create new versions; never rewrite past facts
with the old availability time. Normalize fiscal-year rollovers, EPS definitions,
restatements, units and signs. Missing observations must not become zero.

Coverage matrix: security x issuer x fiscal period x statement x metric, with
OBSERVED/DERIVED/STALE/NOT_YET_REPORTED/NOT_APPLICABLE/UNAVAILABLE/UNVERIFIED states.
Not-yet-public future periods and pre-listing periods are not ordinary provider
failures; failures remain reported. Publish denominators and source limitations.

### Storage and incremental reuse

GitHub stores code, schema, tests, plans, model/review versions and receipts.
An authorized PRIVATE durable store stores content-addressed raw objects,
normalized Parquet versions, event history, quality evidence and model records.
Drive is an archive/restore transport, not the website API, a multiwriter SQLite
volume or a private paywall implemented with public share links. Snapshot SQLite
only after a clean transaction/close; restore locally, verify, then query.

Use append-only accession/accepted/observed manifests; one publisher advances the
verified pointer with compare-and-swap semantics. Store checkpoints only after
verified durable writes, not merely after choosing a queue batch. Resume interrupted
batches without duplicates and alert on missing scheduled executions. Reuse PR295
changed-accession and PR411 object/manifest concepts after exact-source inspection;
do not create overlapping schedulers. Prices update independently of fundamentals.
New earnings/amendments invalidate only affected features and thesis assumptions.
Vendor estimates need fixed fiscal-period keys, analyst-count/definition controls,
fetch timestamps and same-target revisions. Current estimates cannot backfill 2016.

## 6. Data-to-AI-manager integration (separate H2)

Keep existing leadership baseline weights until preregistered OOS evidence justifies
change. Observe RS5/10/20/60/120/240; study nonoverlapping blocks and volatility/beta
adjustments without counting the same move repeatedly. Compare broad and equal-weight
industry/technology-basket breadth. No short-RS automatic sell rule.

Evaluate actual fundamentals AND change: organic growth vs M&A/FX, margin bridge,
OCF working-capital effects, FCF definition/capex, debt maturity/interest, ROIC,
share-count/SBC/dilution, forward guidance/consensus. Distinguish observed/proxy/missing.
Use sector/life-stage adapters; no bank/insurance/REIT assessment by industrial FCF
and no negative-EPS P/E shortcut for early growth.

AI roles: source extractor, business/technical analyst, accounting/valuation checker,
independent counter-thesis and risk/editorial reviewer. Deterministic code validates
numbers/time/units/cash/weights. Two AI agreements do not authenticate independent
sources. Treat retrieved instructions as untrusted content. Save provider/model,
prompt/config hash, source excerpts, review receipt, assumptions and contradictions.
Keep customers' and competitors' evidence, not just management claims. Review changes
on all eligible names; use multiple discovery lanes and rotating under-reviewed firms
rather than only the best historical RS or familiar names.

Bind supported evidence to growth, retention, ASP, margin, reinvestment, dilution
and valuation assumptions; never multiply vague moat points into arbitrary success
probabilities. Reuse PR405 quality_bundle and scenario contracts on the current base,
with dependency and full test review. Preserve 1/3/6/12-month forecast targets and
separate multi-year 5x/10x research. Do not use retrospective peak labels or later
LLM knowledge as evidence of an ex-ante early-winner hit rate.

## 7. Subscription model book, publication and performance

Desired books: research signals, reviewed model targets, publication receipts,
simulated model fills/holdings and benchmark/cost series. Never relabel historical
backtests or a personal account as this product's post-publication track record.

A future release state machine is DRAFT -> VALIDATED -> EDITORIALLY_REVIEWED ->
DELIVERED, with CORRECTED/SUPERSEDED versions retained, not silently edited. Only an
authenticated delivery receipt establishes published_at. A model implementation
session must be after both information availability and delivery using the relevant
exchange calendar, buffer and declared cost/slippage rule. Do not claim the prior
close or an already-realized earnings gap as purchasable after publication.

Compute self-financing model cash, quantities, corporate actions, dividends, fees,
turnover and MDD from the same declared convention as the total-return benchmark.
Report USD and separately FX-adjusted KRW, absolute/excess return, gross/net model
results, inception date and full available history. Subscriber fees are a separate
fee assumption, not a universal basis-point deduction. Customer taxes/execution
will differ. Display backtest, paper and prospective model results separately.
No fabricated 1/3/6-month probabilities, fixed cash30% or guaranteed MDD/CAGR.

Subscriber experience: daily manager brief, thesis/risk changes and dated model
positions; weekly company/industry review; biweekly target review; event-driven
exceptions; monthly attribution and error review. No forced daily turnover. Later
forecast views must separate calibrated distributions from analyst scenarios.

Public site: product description/methodology/data-health/demo only until reviewed.
Member content: backend authorization on every API request, expiring sessions,
subscription entitlement/revocation, audited delivery, versioned correction notices.
Do not hide paid data in a public repository, Pages JSON, frontend JS or Drive links.
Payment integration needs verified webhook signatures/idempotency, cancellation and
refund policy; user/transaction data belongs in a properly secured service database,
not the investment research archive. No billing implementation or purchase today.

## 8. Implementation work packages and acceptance

| ID | Scope | Acceptance | Current status |
|---|---|---|---|
| S0 | Product boundary + offline full-cohort readiness/index/reuse queue | 1118 identities, no fabricated history, reproducible files | Implemented in this branch; not deployed |
| H1-1 | Existing archive inventory/restore + security master | Exact raw hash and issuer-period coverage, recoverable missing queue | Required |
| H1-2 | Canonical PIT, date, currency/ADR and revision-definition fixes | Original failures reproduce; future amendments do not change old decisions | Required, separate causal PRs |
| H1-3 | Incremental collectors + shared universe + durable recovery | New accession only, failed writes do not advance checkpoint | Required; reuse existing paths |
| H2-1 | Business evidence + dynamic financial/forecast adapters | Reviewed real company packets with false/unknown states preserved | Required; reuse PR405 |
| H2-2 | Expected-return/risk/model target research | OOS ablations, costs/common risks, no fixed name/cash mandates | Required |
| S1 | Publication-first model journal and daily brief | No pre-publication fill; idempotent records and corrections | Required |
| S2 | Member delivery/billing/disclosures | Server-side access tests, entitlement/refund/license/legal approval | Required |
| S3 | Internal shadow -> controlled service launch | Restorable daily cycle, verified editorial release, honest track record | Not authorized by this slice |

Historical backtest incompleteness blocks historical performance CLAIMS, not all
internal contemporary research. Partial data must not be sold as a whole-market
optimal portfolio. Each selected investment still needs current sources, appropriate
valuation and risk review before a genuine model publication. Missing optional
analyst consensus is not an economic rejection; route it to a distinct evidence mode.

## 9. Legal and licensing boundaries (sources checked 2026-09-13 KST)

No-auto-trading is NOT by itself exemption from investment-advice regulation.
Korean FSC guidance distinguishes one-way nonindividual paid advice from paid
interactive/personalized advice and prohibits misleading/guaranteed performance
advertising. Legal review must decide registration/reporting, permissible product
functions and advertising before paid release. Chat-based portfolio-specific advice
is not included in the first scope. Model/paper labelling alone is not permission
to advertise hypothetical or unrealized returns. Do not present the research CAGR
35/50% or tenbagger aims as customer performance promises.

Data/API access does not establish commercial display, redistribution, derived-use
or document-reproduction rights. Maintain rights per vendor/source/field/use and
contract version; seek affirmative permitted uses instead of inferring rights from
an API plan. Public SEC facts do not grant third-party quote/consensus licences.

Primary sources:
- SEC APIs/bulk limits and standard fact scope: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- FSC scope and advertising rules: https://www.fsc.go.kr/edu/news/83077
- FSC 2026 supervision: https://www.fsc.go.kr/po010103/86747
- Market data vendor policy illustrating separate redistribution rights (NOT a ruling on another provider's contract): https://www.marketdata.app/docs/account/data-policies/data-redistribution/

## 10. Reproduction and publication caveats

Run on private copies, not public market-data fixtures:

```sh
python tests/subscription_manager_readiness_smoke.py -v
python -O tests/subscription_manager_readiness_smoke.py -v
python tools/subscription_manager/readiness.py \
  --cohort /private/all_us_relative_strength.json \
  --cohort-sha256 4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4 \
  --financials /private/whole_cohort_financials.json \
  --financials-sha256 0bbf35ca1aa08f107785ad36555e8846fcd1f1ebf7a5e7fefe0fa71ab4aef321 \
  --source-commit IMPLEMENTATION_COMMIT_SHA \
  --decision-at 2026-09-13T05:10:00+09:00 --output /private/new-readiness-run
```

The exact-file hashes are dataset versions, not claims of today's prices. Only code,
synthetic tests and this plan belong in the public PR. Do not upload `private/`,
SQLite, quote rows, original archives or private Drive identifiers there.

The original PC/worktree was unavailable and direct git network access failed in
this environment. All NEW files were edited/tested/explicitly committed in an isolated
offline source workspace; unmodified current-master tree entries are preserved in
GitHub publication. No original user's local modifications are claimed recovered.
Exact blob parity, PR CI and independent review are separate recorded steps. No
master merge, production, schedule/fullrun, customer order or accepted-book write.

Reusable lessons: A parsed company is not ten years of normalized statements;
a dashboard refresh is not a new model portfolio; SQLite backups are not raw SEC
archives; a deterministic HTML preview is not a delivered subscription service.
