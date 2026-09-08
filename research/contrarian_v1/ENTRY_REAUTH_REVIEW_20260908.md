# Conditional contrarian overlay: entry reauthorization review

[PROJECT_HANDOFF]

Date: 2026-09-08. Scope: `RESEARCH_ONLY`, isolated H1 correction to H2 PR #403.
Repository: `wscha231/r1000-quant-engine`.
Reviewed parent: `f62252fb90039c4eeccd4dc6b63026ca99bf1c67`.
Parent full tree: `95ec4ac6c4f1ac67ca6260ffe92e03740de1a46f`.
Default-branch audit: `8ccbd478e05ff34c6dd70e410be0cae793c9863e`.

## Decision

Use conditional contrarian exposure as a research overlay, not an automatic
fear-buy / greed-sell strategy. Existing master has legacy fear/greed handling;
PR #403 already contains the isolated V1. This review reuses that work rather
than claiming the capability was absent or duplicating its implementation.

This H1 changes no numeric parameter, selector, stock score, market regime,
production setting, workflow, official target, broker/paper ledger or order.
A proposed weight is not an executed fill. No historical alpha, OOS result or
current market classification has been established by these synthetic tests.

## Reproduced defect

V1 retains a positive fear tilt after sentiment normalization, intentionally
avoiding automatic disposal of a sound investment. However, the retained tilt
also continued to authorize NEW exposure even when the old proposal was not
filled and current entry criteria were no longer satisfied.

Example (synthetic): baseline 0.85, actual 0.85, stored tilt +0.10. Sentiment
normalizes to 50, yet original code proposes 0.90. The same failure occurs when
valuation attractiveness or stabilization disappears, or a session gap resets
confirmation. Retaining holdings and authorizing fresh purchases are different
permissions. Original tests covered no forced sale, but not this distinction.

## Minimal correction

After the normal baseline-plus-tilt desired weight is calculated:

```python
if tilt > 0 and "qualified_fear_add" not in reason:
    desired = min(desired, max(current, base))
    reason.append("retained_fear_tilt_hold_only")
```

Seven lines are added including explanatory comments. A retained fear tilt
cannot take exposure above both actual exposure and the independent approved
baseline unless the current packet requalifies. Existing risk/capacity ceilings,
no-buy veto, 5 percentage-point ladder and no-trade buffer still apply.

| Case | Result after fix |
|---|---|
| Actual 85%, baseline 85%, old fear tilt, now neutral | Hold 85%; do not execute stale addition |
| Actual 90%, baseline 85%, now neutral | Hold 90%; neither complete to 95% nor dump to 85% |
| Actual 95%, baseline 85%, now neutral | Hold 95% subject to upper risk/thesis rules |
| Actual 80%, independent baseline 85% | Baseline restoration to 85% is not blocked |
| Current fear qualification valid | Existing 85% -> 90% -> 95% ladder still works |
| Session gap | New fear increments wait for renewed consecutive confirmation |
| Upper risk cap 88%, actual 95% | Cap remains binding; proposed exposure 88% |

These are conditional arithmetic examples, not approved live allocations.

## Validation actually performed

Source was read through the connected GitHub tool at the exact parent SHA.
No user checkout is mounted and container DNS cannot reach GitHub. An isolated
local reconstruction was used for edits/tests, not a claim of a full repository
checkout. Reconstructed original files were verified against Git blob identity:

- `overlay.py` before fix: `70503171871e79a0bff5aa78d9168f6a7f2d03d9`.
- Existing `test_overlay.py`: `20496fcbe79b6758017485bd4acd2eb4b2dcded8`.
- Existing `synthetic_input.json`: `381aa8836af0761da1f8ca05ecc0d6c5a3ba682c`.

The new regression suite has 13 test methods. Against original code seven
methods fail. Against the corrected code all 13 pass. The exact original
41-method suite plus the new suite passes **54/54** via:

```bash
python -m unittest discover -v
python -m py_compile overlay.py test_overlay.py test_entry_reauthorization.py
```

The original and new suites each embed 1,000 deterministic randomized safety
cases (seeds 402 and 20260908): 2,000 cases total, not 2,000 market observations.
These are functional/safety checks, NOT profitability evidence.

Changed-code SHA-256:
`276c93a5d95bec55b06c60b7beb83aab5567a212f3790017bf6d32467cdbeeb7`.
New regression-file SHA-256:
`4e1f34143e94ba0b6f64402926c27c639265ad3aefbfecf1527b28a5cb19d51c`.

Explicit-path local staging and `git diff --cached --check` passed before
publishing identical blobs through Git object APIs. The staging index belongs
to an isolated bare object store; no new user worktree was created. The dependent PR must be reviewed on
its own exact head; this report is not an independent approval or
`review_complete` attestation.

## Research basis and limitations

1. Baker and Wurgler, *Investor Sentiment and the Cross-Section of Stock Returns*:
   sentiment predicts relative returns particularly in difficult-to-value stocks.
   This is not evidence that a 20/80 index rule times aggregate equities or that
   all high-quality large caps respond identically.
   Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=464843
2. Daniel and Moskowitz, *Momentum Crashes*: market declines/high volatility and
   rebounds can coincide with momentum crashes. This motivates not extrapolating
   a momentum rank mechanically into panic selling, but is not a proof of a
   long-only contrarian timing rule.
   Source: https://business.columbia.edu/faculty/research/momentum-crashes
3. Moreira and Muir, *Volatility Managed Portfolios*: volatility scaling offers
   evidence for adapting risk rather than treating all fearful markets alike.
   Source: https://www.nber.org/papers/w22208
4. Cederburg et al., *On the performance of volatility-managed portfolios*:
   analysis of 103 strategies finds no systematic direct outperformance and
   weaker performance in reasonable out-of-sample implementations. This is
   contrary evidence against presuming any dynamic exposure rule must help.
   Source: https://experts.arizona.edu/en/publications/on-the-performance-of-volatility-managed-portfolios/
5. Cboe: VIX measures expected volatility, not the sign of the next stock return.
   High VIX alone cannot certify a bottom.
   Source: https://www.cboe.com/tradable-products/volatility-trading/

V1's 20/80 entries, 35/65 exits, +/-10 percentage-point tilt, two-session
confirmation and 5 percentage-point steps are frozen research choices, not
thresholds established by the cited papers. This H1 does not retune them.

## Existing V1 design retained

Three equally weighted, greed-direction percentile families: positioning,
options, market internals. This is NOT the CNN Fear & Greed Index. Authentic
market-specific upstream adapters must define family membership and redundancy.

Fear deployment requires attractive value, intact fundamentals, no deterioration
in earnings/credit/liquidity and two of breadth improvement, easing volatility,
price stabilization. Greed trimming requires stretched value plus breadth or
earnings deterioration. Healthy optimism alone does not force selling.

Upper risk and eligible-capacity constraints dominate. Missing evidence means
abstention, not a fabricated 50 sentiment reading or a 35% cash target. Previously
adjusted baselines are rejected to avoid double-counted contrarian exposure.
US/KR evidence and state are separated; Korean real-data integration is not
claimed by a fixture accepting `market="KR"`.

## Remaining blockers and stop conditions

- Full current-checkout CI / protected Tier-1 registration and independent
  exact-head review remain incomplete. Green legacy CI alone would not prove
  this new regression suite ran.
- No authentic source-byte replay, real live/historical adapter, daily signal
  freshness certification or exchange-calendar admission is added. The existing
  96-hour daily TTL is not sufficient by itself to prove a fresh observation on
  each confirmed session. Do not count a copied daily observation twice; weekly
  positioning needs its own release cadence. Upstream integration must test it.
- Hash syntax and distinct source-name strings are not proof of authentic data
  or independent economic information. Audit raw-byte lineage and correlated
  family overlap before promotion.
- Current positive-tilt state is not a holdings lot ledger; baseline changes,
  actual fills, capacity and thesis ownership remain upstream responsibilities.
- If all risk caps forbid recovery deployment, test a separately registered
  risk-policy challenger. Never silently override a canonical crisis veto.
- Confirmation can miss an abrupt rebound; unconditional contrarian entry can
  buy too early. Compare both against the same risk-matched selector and cost
  contract instead of selecting an outcome retrospectively.
- Before deployment compare the four preregistered arms in `experiment.json`:
  fixed 95/5, frozen selector+risk baseline, naive sentiment tilt, conditional V1.
  Include genuine cash interest, taxes/fees/slippage, delayed execution, total
  returns, PIT universe, corporate actions, drawdowns and recovery duration.
- Main CAGR 35%, Concentrated 50% and MDD <=25% remain unproven research goals.
  Known 2008/2020/2022 stress windows are not unseen OOS.

## Shared operational lesson

A persistent investment HOLD decision must never be reused as a perpetual
BUY authorization. Test partial and unfilled proposals, revoked entry criteria,
session gaps and independent baseline changes, not just fully executed paths.
Keep H1 repairs separate from H2 parameter/alpha changes.

## Next action / handoff

Review and merge the dependent H1 only into the H2 branch after its gates pass;
then rerun and independently review the new H2 head. Do not merge either into
master or wire an operating writer based on this report alone. Preserve existing
PRs #375/#389/#399/#400/#401 and all production/accepted-book identities.

Confidence: high in the reproduced narrow defect and these tested boundaries;
unknown for net alpha, future returns, current market regime or MDD compliance.

Safety: no fullrun, dispatch, orders, promotion, official target/book changes,
credential access or user-worktree edits performed.
