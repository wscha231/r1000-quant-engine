# [PROJECT_HANDOFF] Conditional contrarian exposure overlay V1

Date: 2026-09-08. Tracking issue: #402.
Repository: `wscha231/r1000-quant-engine`.
Inspected master: `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.
Proposed branch: `codex/contrarian-overlay-v1-20260908`.
Status: **RESEARCH IMPLEMENTATION, SYNTHETIC TESTED, DEFAULT UNWIRED**.
No live market classification or historical performance is reported.

## 1. Decision and existing capabilities

The user requests buying qualified excessive fear and trimming qualified
excessive greed rather than maintaining an arbitrary permanent cash balance.
This is an incremental H2 experiment, not H1 operating recovery or promotion.

Existing master already contains:
- `r1000_signals.py`: a legacy fear/greed cash adjustment. The inspected fear
  branch subtracts `0.12 * ((25 - fear_greed) / 25) * (0.60 + 0.40 * recovery_bonus)`
  below 25, with a systemic-crisis check. Presence is not proof of activation,
  independent performance or current-book application. Do not apply both tilts.
- `r1000_crisis_governor.py`: normal-market low cash / selective crisis defense.
- `tools/run287_crisis_policy.py`: pure canonical state, selective defense,
  missing-critical-data checks and staged re-entry; not replaced here.
- `tools/run_crisis_reentry_replay.py`: research replay of staged bargain re-entry.

Open PRs #375/#389/#399/#400/#401 have separate scope and gates. Do not merge their
unreviewed stacks or use their synthetic results as actual holdings. The root
CURRENT_STATUS snapshot is dated August 23, not a current September regime.
The real research pilot described in #400 is still data-blocked, not a valid
current stock allocation. Earlier chat macro/price figures are NOT model input.

## 2. Research and competing hypotheses

**H1 sentiment reversal:** crowd pessimism can signal an attractive entry,
particularly when valuation and business prospects diverge from price.
**H2 persistent crisis:** deep pessimism can coexist with an unfinished credit,
liquidity or earnings deterioration; buying each decline can breach the loss cap.
**H3 trend persistence:** elevated optimism may persist through a genuine earnings
expansion; unconditional selling creates cash drag and truncates winners.

Primary references, consulted September 8, 2026:
1. AAII, *Is the AAII Sentiment Survey a Contrarian Indicator?*
   https://www.aaii.com/journal/article/is-the-aaii-sentiment-survey-a-contrarian-indicator
   Its historical analysis explicitly notes overlap and excludes trading costs;
   high optimism and pessimism can persist. It is not a standalone timing model.
2. Daniel & Moskowitz, *Momentum Crashes* (Journal of Financial Economics, 2016):
   https://business.columbia.edu/faculty/research/momentum-crashes
   Panic rebounds are a momentum-risk setting. This does not prove that every
   high-VIX reading forecasts a positive long-only equity return.
3. Moreira & Muir, *Volatility-Managed Portfolios* (Journal of Finance, 2017):
   https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12513
   Evidence supporting lower risk at high volatility is a counterargument to
   mechanically increasing risk with fear, not a claim about this new module.
4. Cboe, *Volatility Trading*:
   https://www.cboe.com/tradable-products/volatility-trading/
   VIX measures expected movement magnitude, not direction or intrinsic value.

None of these papers validates the numeric thresholds below or a 35%/50% CAGR.

## 3. Frozen initial hypothesis, not fitted parameters

Input sentiment is our own 0-100 greed-oriented percentile composite, NOT the
CNN index or a return probability. Equal fixed weight on three families:
`positioning_greed_pct`, `options_greed_pct`, `internals_greed_pct`.
All three are required. One options family can incorporate VIX/term structure/
put-call measures internally; it must not count them as independent full votes.
Do not add CNN's composite on top of overlapping components. Distinct source
identifiers catch exact reuse but cannot prove statistical independence.

Daily normalization proposal: trailing 756 PRIOR sessions, minimum 252.
Weekly positioning: trailing 156 PRIOR releases, minimum 52; never multiply the
sample size by forward-filling weekly releases. Use a market-specific fixed
family mapping. `historical_percentile()` implements only the midrank arithmetic;
upstream adapters must prove PIT vintage, calendar, direction and membership.

| Condition | Absolute tilt to contrarian-free baseline |
|---|---|
| Normal / optimism supported by earnings | No new contrarian tilt |
| Greed <=20, two consecutive valid sessions, qualified opportunity | Up to +10 percentage points equity |
| Greed >=80, two sessions, valuation stretched AND breadth or earnings worsening | -10 percentage points equity |
| Systemic/credit/liquidity worsening, no-buy flag, broken business | No increased exposure |
| Kill switch | Delegate to existing emergency policy; no numeric order |
| Missing/stale/future/conflicting evidence | Abstain, never manufacture 35% cash |

Fear exits below-zone status at 35; greed exits at 65 (hysteresis). Exposure
moves by at most 5 percentage points per decision, with a 1-point no-trade
buffer, except an upstream hard cap/capacity reduction takes precedence.
Fear opportunities require intact fundamentals, attractive valuation, no
earnings deterioration, and at least TWO of breadth improving, volatility
abating, price stabilizing. A 200-day moving-average recovery is NOT required.

The desired tilt is absolute, not added to yesterday's tilt every day.
Panic additions are not sold merely because sentiment normalizes. A negative
greed tilt is released when greed ends and business/risk/value conditions permit;
the same gradual ladder limits re-entry. Upstream baseline changes still apply.
The upstream risk ceiling and eligible-stock capacity always bound exposure.
No leverage, ticker selection, stock-specific sell order or funded hedge is
implemented here. Portfolio hedges need their own cost/collateral contract.

## 4. Evidence and authority boundary

`overlay.py` is standard-library-only and deterministic. Every component needs
value, observation timestamp, public availability timestamp, market, source ID
and SHA-256. Booleans must be actual JSON booleans. Daily maximum observation
age is 96 hours; positioning maximum is 240 hours. Age uses the observation,
not a recent re-download date. Long holiday gaps may block a tilt, not force a
sale. These conservative wall-time limits need calendar-aware adapter review.

Top-level inputs include a verified upstream-manifest reference, baseline,
current exposure, risk ceiling, eligible total exposure, no-buy and kill flags.
`baseline_excludes_contrarian=true` explicitly excludes the legacy adjustment.
False blocks the proposal. Current exposure must come from the correct book;
a prior proposal is NOT an actual or simulated fill. Actual, paper and research
state must never share this field implicitly.

The module validates schema, hash syntax and decision-time consistency. It does
NOT fetch or authenticate source bytes, recompute business gates, establish the
exchange calendar, check real fills, or verify that a supplied baseline actually
excluded the old tilt. These are upstream integration tasks. Output explicitly
sets `source_authenticity_verified=false`, `historical_pit_verified=false`,
`production_activation_allowed=false`, and `orders_allowed=false`.

US and KR packets/states cannot be mixed. KR requires its own KRX/VKOSPI,
positioning, credit/liquidity and KST cutoff adapters; US sentiment is not a
Korean trading signal. Shared research evaluator support is not live KR wiring.

## 5. Files and reproduction

```bash
python research/contrarian_v1/test_overlay.py
python research/contrarian_v1/overlay.py research/contrarian_v1/synthetic_input.json
python -m py_compile research/contrarian_v1/overlay.py research/contrarian_v1/test_overlay.py
```

`synthetic_input.json` contains fabricated fixture observations clearly marked
SYNTHETIC, not historical vendor observations. `validation_receipt.json` binds
source/test/fixture hashes and local results. `experiment.json` preregisters the
comparison and gates. CLI writes JSON to stdout only; it never writes a target.
Do not redirect synthetic stdout into an accepted monitoring/portfolio path.

Validation: 41 unittest methods passed, including 1,000 deterministic randomized
safety cases. Subcases exercise every missing input and multiple bad number types.
Compile and standalone synthetic CLI passed. A standard-library isolated runtime
is sufficient. No external provider, historical backtest, OOS, fullrun or broker
simulation was executed. No return advantage or MDD guarantee is claimed.

## 6. Publication / source integration still required

This ChatGPT runtime had no existing user worktree and git network DNS failed.
No user worktree was created, changed or discarded. New files were prepared and
tested in an isolated local package, staged explicitly in a local validation Git
repository, and their Git blob identities are preserved for Git-object publication
on a new branch. This is not an edit of remote operating files or a bypass of
review. Existing master paths, protected validation pins, workflows, target/books,
Drive and broker paths are unchanged.

Before merge: inspect exact PR head/diff; independent review; register the new
fast test through `tools/run_pr_validation.py` under its protected-publication
ancestry contract; run the full required checks. This registration is NOT included
here, to avoid modifying a protected runner without its full local checkout.
Existing PR CI being green would NOT prove it executed these new 41 tests.
No self-attested `review_complete`, auto-merge or production promotion.

Before operating use: implement/reuse verified raw adapters from the appropriate
H1 data work, bind runtime source commit/config/data hashes, define one canonical
writer, and run the preregistered historical/forward experiments. Data missing means
no contrarian instruction; the existing risk system remains responsible for risk.

## 7. Lessons / do-not-repeat

- Existing code was found: do not report sentiment logic as wholly absent.
- Unit safety tests are not profitability/OOS tests; three attractive toy regimes
  are not three independent market experiments.
- A close-derived CNN/VIX composite is not independent of breadth/price risk.
- An early review found that a broken-business packet could still increase toward
  its baseline. The final version blocks ALL increases on that condition; a
  regression covers it. Another regression rejects duplicate families using the
  same source ID even with different hashes.
- Never remove an upstream crisis/MDD cap to make fear buying pass. Rejected
  fixed-book crisis results must remain rejected until independently revalidated.
- Do not relabel stale/missing evidence as fear or promote current snapshots into
  historical observations. Do not reset past portfolios to current constituents.

## 8. Next action and stop conditions

Next: exact-head review + protected CI registration, then verified US/KR adapter
fixtures and a named preflight-approved OOS experiment. Use the experiment file
for transaction costs, cash carry, attribution, stress and holdout criteria.
Stop on missing provenance, divergent input markets, duplicated tilt, unresolved
review, capacity/risk violation, failed G0, or an OOS MDD above 25%.
Implementation confidence: moderate pending independent review.
Profitability confidence: unestablished. Live readiness: false.
