# Research Decision V1 — H2

Parent: H1 PR #399, published source `9fb2bd5c5640d5c20015d96745ad015d706ad488`.
Related issue #396. The fixed config was locally committed as
`a4b5d8c06225823a4af93da638053c053d71c1dc` before any scenario/ranking test output.
No coefficients were selected from the fixture outcomes.

## Run boundaries

1. Materialize and reconcile provider/cache inputs to the H1 contract. Preserve
   original source responses separately; a canonical payload hash is not proof
   that a human extraction or the provider is correct. Incomplete reconciliation
   must set that block `unverified`.
2. Run each market's exporter in its own repository. The KR wrapper checks the
   shared package's exact source hash before importing it.
3. `python tools/run_research_decision_v1.py --market-export <US-export.json>
   --market-export <KR-export.json> --context <context.json>`
4. Optionally pass `--previous <report.json>` to explain component/rank changes.
   Different input-kind or future/tampered previous records are rejected.

The output directory is content addressed under `outputs/research_decision_v1`.
It includes frozen evidence/config, source hashes, per-field coverage, industry
discovery, ranking, proposal, decision ledger, Markdown/JSON report and immutable
source-commit receipts. Identical fixed inputs produce identical decision hashes.
Exit 2 means the actual proposal is blocked/partial, even though a diagnostic
artifact was saved. No mutable `latest` writer, scheduling or operating imports.
An uncommitted or untracked research source file instead yields
`BLOCKED_SOURCE_MISMATCH` before reading inputs or writing artifacts. The check
compares source bytes/file sets to Git HEAD, including `tools/__init__.py`, and
does not trust skip-worktree or assume-unchanged flags. Unrelated dirty files do
not block a research run. Custom settings undergo the same credential and legacy
score rejection as evidence before they can be persisted.

## Interpretation

12-month `EV_EBITDA` and `PE` scenarios require revenue, appropriate margin,
multiple, future diluted shares, net debt, dividend and explicit subjective
probabilities. Debt is subtracted only in the enterprise-value method. No extra
buyback yield is allowed when future shares already include it. Reverse valuation
is conditional on Base margin/multiple/shares/debt; it is not a forecast.

Investment utility = expected total return - assumed round-trip costs
- 0.5 * Bear downside - 0.1 * scenario dispersion - 0.1 * uncertainty.
This is an explicit decision preference in return units, not a calibrated return
or loss-probability model. Total-return rank and investment rank are distinct.
Industry and theme equal/current-cap weighted returns, RS and breadth are solely
candidate-discovery diagnostics. Missing group coverage remains missing.
No ownership, news, options or NONRANKING alpha points are used.

US returns are also translated into KRW under each scenario's explicit FX rate.
Global rank/weights require valid FX; local country ranking survives FX failure.
Entry and hold hurdles use expected net return in portfolio currency (KRW).
The report labels local-currency and KRW total returns and shows both global
return and investment ranks. The four investment questions are displayed apart.
Costs are conservative research assumptions, not validated tax estimates.
Benchmark excess return exists only with an explicit benchmark scenario.
1/3/6-month forecasts and statistical loss probability remain null.

New-capital allocation uses positive utility, thesis confidence and downside,
then applies single-name/country/industry/theme/customer/liquidity/regime/stress
caps. Constraint shrinkage leaves the residual in cash. Counts are maxima, never
country weights. Above 5% produces a risk review; above 10% adds concentration
review fields. All proposed weights plus cash equal one, with no short/leverage.

An existing-book proposal requires a recent, complete submitted book and no
unreconciled pending orders. It compares replacement utility to incumbent utility
after cost/buffer, preserves small changes, and requires strengthened thesis for
adds. Short RS alone is not an exit. Missing incumbent evidence preserves the
submitted book and blocks changes. If preserving an incumbent conflicts with hard
risk caps, the conflict is displayed and the proposal is not marked ready. This
is a review proposal, never an actual broker reconciliation or an order.
Replacement reduction can consume only feasible final new-buy weight, once per
unit of capacity. Candidates clipped to zero cannot justify sales. Retained
holdings consume the country count; an already oversized book is blocked for
review. Trade liquidity checks use the actual buy/sell change, including full
liquidations. An intact holding below the distinct hold hurdle is preserved but
requires a valuation review; this is not a ready HOLD recommendation.

Industry equal-weight returns give each constituent equal weight. Cap-weight
returns require a verified current market-cap observation for every member;
TTM diluted shares are not a market-cap proxy. Removed candidates remain in the
decision ledger as missing from the research universe, without implying a sale.

Scenario stress is not pathwise MDD; the 25% MDD goal remains OOS-unvalidated.
Eight one-at-a-time revenue/margin/multiple/share perturbations show rank ranges;
they are neither confidence intervals nor post-hoc parameter optimization.

## Remaining scope

This implements the deterministic research calculation for reconciled inputs.
It does not automatically reconcile arbitrary SEC/DART/FMP statement taxonomies,
retrieve missing long raw price/corporate-action archives, establish a complete
historical universe, calibrate returns, validate OOS performance, or promote a
model. Current-data completion depends on those required source records.
Real pilot failures stop expansion to 5+2; synthetic tests cannot replace them.

Cadence design only (disabled): daily price/risk observations, event financial
and thesis updates, weekly research review, biweekly weight proposals. No new
schedule was installed or activated by this PR.

Branch boundary: the first unpublished H2 branch at
`61af490a79ebf79d5fa75afae80fa447cc6bd1e6` is retained as provenance. The reviewed
H2 branch reapplies only that locally committed scope onto the corrected H1
ancestor. No other active PR's files or user-edited CSVs are included.

Change attribution separates material price/financial/estimate/thesis/risk and
missing-data changes from an evidence-provenance-only refresh. Sensitivity
perturbations outside the supported valuation domain are null with a reason;
they do not invalidate the unperturbed scenario.

H2 validation registration is causally published at
`163e1a4ae764f506f19a5150df72a8ced2a05b3f`. Only the protected-publication pin and
matching regression constant advance to that ancestor; no verifier logic changes.

Second H1 review restack: original H2 head 88d4dfa1322d816481452d16928eb40678a0e999
is retained in codex/research-decision-v1-ranking-before-h1-review2-20260907.
The active dependent PR replays the same H2 capability on corrected H1, with
content-addressed synthetic input paths to preserve prior fixture versions.

Final reviewed-scope registration is published in causal ancestor
`57bb001cc6902d83516c3eb0df319ca0d5a9b880`; the protected-publication pin and
matching regression advance to it. Previous heads remain provenance only.
