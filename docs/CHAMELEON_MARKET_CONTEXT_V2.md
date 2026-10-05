## Native library-only adoption — 2026-10-05

The full supplied library and source register are adopted with 72 unchanged
library-boundary cases; ten parent CLI cases and the parent runner are explicitly
unadopted. Native tests use tests/chameleon_market_context_v2_library_smoke.py
through the accepted H1 wrapper. The original author package below describes
the broader CLI candidate and its historical fixture verification.

Seven separate regressions cover two source-proved corrections. Prices use a
copied, normalized numeric row under the original number() string contract;
caller rows remain untouched. Canonical int/float/string representations may
change digest bytes and are deliberate. Public rows retain each original
parser/register provider-specific dataset/entity/metric/unit/range contract,
including signed CFTC contracts, zero/missing OI, all three Cboe universes and
AAII endpoints. Null/stale evidence remains null/stale and authority stays false.

Existing macro/VIX/VIX3M/VVIX and licensed supplied sentiment are research context,
not independent duplicate votes, stock option chains, consensus or expected
returns. No producer, provider, A4/A3/A5 authority or PIT admission is activated.

## Native review-boundary corrections - 2026-10-05

Breadth requires at least one valid member return or a non-null metric with a
positive eligible count in the current market row. An all-missing return row
with no eligible metric does not complete breadth. Fresh CFTC evidence supplies
positioning; FINRA venue short-sale activity is a separate optional diagnostic.
Its presence cannot replace positioning, and its absence is not a new required
family. The original five required context families remain required.

When optional Calendar pairing consumes an explicit security map, the final
context retains its canonical mapping hash and UTC availability clock in
`security_map_binding`. Both participate in context_delta's semantic identity;
a same-theme member permutation or mapping-clock change requires review.
Canonical key order and equivalent UTC instants remain unchanged controls.
Without Calendar there is no consumed map binding. These are research-context
checks, not source authentication, producer/PIT admission or Calendar activation.

# Chameleon Market Context V2 — #576 successor to #388

TASK_KEY: `R1000-H1-CHAMELEON-MARKET-CONTEXT-V2-20261004`  
Coordination: https://github.com/wscha231/r1000-quant-engine/issues/576  
Status: LOCAL_IMPLEMENTED_TESTED / SHARED_CANDIDATE / NATIVE_APPLY_REQUIRED.  
Not a merged engine, accepted source receipt, independent A6, or operating investment capability.

## Purpose and ownership

Reuse #388's normalizers and #450's Calendar C1 / Free Market Context V1. Assemble macro, market-option context, breadth, positioning and paired theme earnings observations at one decision cutoff. Do not create another portfolio engine or cron.

#450 owns earnings semantics. #576 owns A4 context. A2 owns themes/business membership; A3 owns thesis/ER; A5 owns portfolio. Closed #388 stays closed. Existing #447/#543 fiscal/sovereign research retains its collector/experiment scope. A composition cannot grant upstream or downstream authority.

## Additive implementation

- `tools/chameleon_market_context_v2.py`: raw macro wrapper, visible-vintage panel, date-matched derived metrics, source-family context, price/Calendar bridge, descriptive disagreement tags and change-only review suggestions.
- `tools/run_chameleon_market_context_v2.py`: bounded hash-bound local manifest input and research report output. No HTTP path, no credentials, no scheduler.
- `tests/chameleon_market_context_v2_smoke.py`: 82 author-written synthetic tests; native registration remains a separate integration step.
- this contract and the companion JSON source register.

No edits to existing #388, C1/H1, Free Market Context, daily operating workflows, accepted archives, price caches, shared protected test runner, selector, ER, weight, ledger or risk policy.

## Sources and free-data scope

19 raw macro/volatility source routes resolve to 17 logical series (VIX and VIX3M each have an explicit FRED-or-Cboe choice). The source register is authoritative for these routes, units and age bounds. Do not read both providers as two independent votes or silently switch histories. Missing inputs produce explicit partial context.

Existing macro/price caches feed the new offline composer. CFTC and FINRA collection, where separately authorized, reuses V1's bounded opt-in capture functions. Cboe put/call and AAII are authorized-file imports only. No new automatic scraping is implemented. Individual-stock options/Greeks and dealer GEX are unavailable, not synthesized from aggregate series.

A free base run works without Calendar. When a licensed Calendar raw response exists, the composer invokes the actual unchanged C1/H1 functions through Free Market Context V1. The C1 access probe only emits diagnostic counts; those counts cannot reconstruct a consensus-value response. A durable, approved runtime producer and storage entitlement remain required before operating use.

## Exact calculations and their meaning

- `vix30_to_vix3m = VIX / VIX3M` and `vix9d_to_vix30 = VIX9D / VIX`. These are ratios of annualized implied-volatility indices, NOT futures-curve roll yields, realized dealer positions or individual-stock Greeks.
- `sofr_minus_iorb = SOFR - IORB`, in percentage points.
- `yield10y_minus_2y = DGS10 - DGS2`, in percentage points.
- Derived inputs must have the exact same observation date, units and fresh usable levels. No older-date fallback to force a ratio.
- Raw null rows discarded by legacy normalization are retained by the new strict wrapper. A null latest observation blocks stale-value resurrection.
- Current-vintage trailing midrank is a context statistic, not historical PIT evidence or a calibrated probability. A single capture may contain revised history.
- All market breadth denominators are exposed. A cohort metric's valid-members denominator is not the complete requested universe.
- Calendar comparison uses a symbol count with positive vendor-reported EPS lookbacks, NOT individual analyst revision counts.

## Synergy and disagreement diagnostics

The output puts distinct horizons next to each other without pretending they agree on a single timescale. A one-session median price return and a vendor 30-calendar-day EPS comparison are labeled separately.

Descriptive tags include front-IV inversion, market median price down with credit spread rising, theme price up with a positive vendor-revision majority, theme price down despite that majority, market price up with front-IV inversion, and a bullish weekly survey with a down price session. Price/earnings joint tags require complete respective coverage in the same cohort. Majority is a descriptive >50% count, not a fitted trading threshold.

These tags identify questions to review. They do NOT mean buy, sell, hold, increase cash, tighten stops or liquidate a winner. No numeric alpha score or forecast probability is created. `regime=null`; `regime_authorized=false`; all trading/portfolio/historical-PIT authority flags remain false. RISK_ON/CAUTION/RISK_OFF/RECOVERY require a separate reviewed A4 decision consumer, not a direct mapping from this H1 output.

VIX, VIX3M, VIX9D and VVIX share an option-variance family. NFCI overlaps credit/rates. Theme prices and market breadth share stock prices. No independent-vote count is inferred.

## Input and output contract

Manifest schema: `chameleon-context-input-plan-v2`. It supplies cutoff, expected completed price session, <=64 input descriptors and optional explicit Calendar-to-price security mapping. Descriptors bind source kind, path, SHA256, collection time and source-specific mapping/identity. All collection/mapping clocks are checked before source-file reads. Each source <=8MB; aggregate <=32MB. Relative bounded paths, no symlink/traversal, strict JSON, distinct source paths and at most one Calendar/price panel.

Output is written only under `outputs/chameleon_market_context_v2/<new-label>/`; no overwrite and no accepted/latest alias. Output contains raw-plan hash, local module/dependency file hashes and source-byte bindings. These are not authentication of a provider, a Git commit, a calendar, a producer receipt or a license. `input_producer_authenticated=false` is deliberate.

`RESEARCH_CONTEXT_COMPOSED` only means at least one usable observation in each broad family; it does not certify full series/cohort/source coverage. `PARTIAL_RESEARCH_CONTEXT` reports absent families. A later failure produces BLOCKED rather than a new success. Native consumers must bind their current attempt and verify freshness; they must not substitute an older successful report after a failed current attempt.

`context_delta()` detects semantic/context changes and expiry while ignoring mere transport timestamp/hash churn. It only suggests A4/A2/A3 review; it executes nothing. The eventual native event path must additionally bind code/config/dependency identity, correction/source-failure/catalyst/outcome-expiry events before allowing SKIP_UNCHANGED. This library is not a persistent workflow idempotency ledger.

## Native usage after integration

From the EXISTING canonical worktree, after applying dependencies and this scoped patch:

```sh
python tests/chameleon_market_context_v2_smoke.py
python -O tests/chameleon_market_context_v2_smoke.py
python tools/run_chameleon_market_context_v2.py --plan <licensed-local-plan.json> --expected-plan-sha256 <verified-raw-plan-hash> --output-label <new-label> --licensed-internal-research
```

The rights flag is caller acknowledgement, not a license or a technical paywall bypass. Use an existing permitted capture workflow and pass its exact artifacts; no second cron. Native integration must register these tests using the actual permitted macro validation wrapper/path. Do not change protected runner or gates just to register a test. The packaged `dependency_fixture` MUST NOT be copied over native modules.

## What was actually tested

82 new tests pass normally and with Python -O. The same 95 predecessor regressions pass again in both modes. A 15-input synthetic example executes raw macro normalization, original CFTC/FINRA/Cboe/AAII parsing, original price helper, and actual C1/H1 pairing.

The four full C1/H1/FreeContext modules are byte-identical dependencies. The #388 dependency is a clearly labeled source-function test fixture: predecessor breadth excerpts plus transcribed normalizer functions, not the full native module or all its imports. Tests are author verification, not independent A6. No new source has been collected or current data coverage certified. The example securities, values and regular weekday grid are SYNTHETIC, not an actual market observation or exchange calendar receipt.

An initial 72-case run exposed one CLI output-root/source-hash path bug. Source keys now remain independent of the output root; the whole-CLI test verifies normal output and overwrite rejection. The failed initial log is retained.

## Remaining work

Verify current native worktree and source lane, current master/dependencies, and apply only this add-only candidate after C1 and FreeContext. Run full native macro/H1 integration and all required checks afresh on the new commit, with independent exact-head review. Separately validate real source bytes, identities, availability, licensed retention, durable restore and current consumer binding. These steps must precede a production or economic capability claim. No fullrun, operational dispatch, merge or trading activation happened here.
