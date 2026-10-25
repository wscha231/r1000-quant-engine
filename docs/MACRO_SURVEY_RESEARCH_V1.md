# Supplemental macro survey research V1

Scope: RESEARCH_ONLY; synthetic arithmetic and qualification diagnostics only.
This change has no Source admission, scheduler, market regime,
portfolio weights, automatic sales or economic promotion.

The existing FRED30 registry and its bytes remain unchanged. ISM/AAII are separate
providers, not invented FRED codes. Existing ALFRED and Chameleon semantic pins
remain unchanged. In particular, the current PAYEMS-derived
economic_diffusion_stress is not presented as an actual manufacturing PMI.

## Decision purpose

A4 can propose entry-pace, sector research, common-risk and reentry reviews.
A3 retains company thesis/ER review and A5 retains portfolio authority.
Macro/sentiment weakness alone cannot liquidate a healthy Winner. Headline ISM
composites and their components are not16 independent alpha hypotheses.
Supplier deliveries need supply/demand interpretation. AAII expectations are
not positions. No new scoring weights or PMI50 buy/sell rule are introduced.

## Implemented candidate

- ISM manufacturing7: PMI, new orders, production, employment, inventories,
  prices, supplier deliveries.
- ISM services6: PMI, business activity, new orders, employment, prices,
  supplier deliveries.
- AAII3: bullish, neutral, bearish; derive bull-minus-bear spread and
  consecutive-release changes without imputing missing components.
- Keep revisions, explicit reference/release/availability/collection/decision
  clocks; reject malformed/nonfinite/boolean values and incompatible units.
- Missing/stale/conflicting groups have null values. Repeated daily decisions
  do not manufacture independent release samples. Revision-only updates do not
  add new reference periods. No provider or flash/final splicing.
- ACTUAL is the default and returns BLOCKED_SOURCE_ADMISSION before reading an
  input file. Caller VERIFIED flags cannot activate source/PIT/rights.
- SYNTHETIC_FIXTURE is explicit, survives normal/-O checks, always marks raw
  bytes unverified and all source/economic/selector permissions false.

Freshness bounds45 monthly /10 weekly days are supplemental research
qualification defaults, not changes to existing risk thresholds. Compare both
reference age and original publication age; new collection cannot freshen an
old survey. Review them before actual integration.

## Evidence acquisition

| Missing item | Acquisition place | Existing responsible role | Success criterion |
|---|---|---|---|
| ISM storage/derivation rights and release archive | ISM or existing authorized licensed feed | A1 Source; account rights owner | Written usable rights plus original per-release bytes, revisions and published clocks; no unauthorized public-page scraping |
| AAII history, automated-use scope and release clocks | Official AAII results/archive and existing approved Source | A1 Source | Complete dated raw3 shares, rounded totals, original release/collection lineage and authorized use; an observation date alone is insufficient |
| NAAIM current weekly values | Existing entitled member/subscriber access, if any | Account rights owner then A1 | Current history/API rights and clocks; public3-month-delayed page never admitted as current |
| State Street flows/holdings history | Official monthly indicator archive or authorized existing feed | A1 Source | Separate holdings/flows identities, full actual history, clocks and rights; no splice with old ICI |
| Put/call archive | Existing Cboe contract and authorized archive | A1 then A4 | Equity/index separated, original dates/volume caveats; satisfy existing unsupported component contract |
| Regional manufacturing proxy | Philadelphia Fed MBOS official historical CSV/XLS/TXT | A1 then A4 | Region clearly labeled, release/revision clocks; no substitution for national ISM |
| Actual supplemental Source binding | Existing Lake/receipt/rights path under Source owner | Existing Source and Main serialized; independent A6 | Real raw hash/pack/catalog/execution/rights/clock validation, reviewed minimal adapter; fixture labels never accepted |
| Sector effects and Shadow economics | Existing index/ETF/history, experiment and cost books | A4/A8 with A1/A5 and independent A6 | Eligible price-vs-TR/CA/universe, matched PIT/cost/period/entry and frozen OOS; net-inferior Shadow rejected, Control retained |

## Validation and next implementation boundary

Existing registered tests/macro_technical_evidence_smoke.py calls the new
standalone survey suite; no common runner/frozen inventory edit.
Run the new suite and registered program under normal Python and python -O.
A fixed candidate tree is not a canonical Main Native run, hosted CI, independent
A6 or actual data qualification.

Existing Main owner must first verify the prior writer's terminal release.
Then recheck master/AGENTS/status/diff/lease and take only this causal six-path
delta, including this guide and lesson append. Do not overwrite a moved base or
create another worktree/writer. Publication is Draft first and needs exact-head
CI, independent A6 and genuine review gates. No general user reapproval is
needed for the already authorized code work.

The research comparison is only a prepared preregistration: Control,
Control+ISM and Control+ISM+AAII. Freeze one aligned release/event family and
chronological purged walk-forward/OOS before outcome access. Preserve existing
336/384 negative results. No new backtest, sector alpha or net CAGR is claimed.

## Existing AAII library reuse and local export review

Current master already has tools.free_market_context.aaii_observations. Reuse
that native parser for both fixture arithmetic and supplied standardized CSVs;
do not duplicate its percent/fraction or rounded-total guard. The earlier
candidate's0.2pp rounding acceptance is narrowed to the existing0.1pp contract.
Original28 regression methods remain unchanged and nine cases prove reuse.

LOCAL_EXPORT_REVIEW_ONLY accepts the existing date,bullish,neutral,bearish CSV,
an exact expected SHA256, explicit unit, collection time and current decision.
It keeps original publication unknown and availability at collection only.
The review has a distinct schema and exits2: matching bytes are not publisher,
license, PIT or portfolio approval. ACTUAL still refuses before reading input.
No current market regime is produced, and source/economic authority stays false.

On2026-10-25 official AAII page and its publicly linked sentiment.xls each
returned403 to one direct read, without retries/proxies/login or bulk capture.
Web-readable figures are not relabelled original byte evidence. Three existing
Drive handoffs describe authorized CSV import, not actual AAII originals.
A finite AAII/sentiment filename search found no original; this does not prove
absence from all Drive/catalog objects. Exact publication and historical PIT
remain unknown. No paid subscription, email registration or external inquiry.

The missing SciPy obstacle is resolved for T2 tests by read-only reuse of an
already installed pinned wrapper (Python3.12.10/numpy2.2.6/pandas2.3.3/
scipy1.15.3). No owner environment, package install or network download changes.
T2 proof alone is not Main integration. The current user-authorized intake uses
the released existing Main only, after676 terminal closure and current-master
refresh. Keep the six-path cause, exact committed Native tests and independent
review separate from Source acquisition and hosted CI.

Independent A6 reproduced a P2 on predecessor46b1: the original20,060-byte
JSON with10,000levels (a distinct compact regression is retained) escaped as RecursionError without a BLOCKED report in both
modes. Preserve that exact failure. The correction bounds decoded JSON to24
levels/300,000nodes, translates decoder recursion to a finite refusal and
guards the CLI. Three added regressions retain every prior37/28 and original16
test method. New exact-code normal/-O and independent A6 must qualify this
correction; earlier fixture success is not its acceptance.
