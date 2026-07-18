# Run287 candidate evaluation gap and full-history result - 2026-07-15

## Decision

Do not append memo names directly to the 993-name operating universe. Preserve
them in a tracked research intake, identify the exact stage at which each name
is absent, repair only objective data gaps, and then build a separate shadow
feature context. No candidate in this package changes a target book, weight,
cash allocation, order, backtest, fullrun, production setting, or live-trading
setting.

The current-universe identity is still a current snapshot rather than PIT
historical membership. Delisted-return and symbol-predecessor coverage are not
repaired. Therefore the new histories cannot be projected backward into an
official seven-year portfolio test.

## What was missing and why

The tracked intake contains 45 AI-infrastructure candidates from the 2026-07-15
memo. Thirty-one already have a current 993-name score context and fourteen do
not:

`000660.KS, AEIS, BELFB, CAMT, CLS, CRWV, FN, FORM, IESC, MOD, NBIS, RMBS, SKHY, TSEM`.

The final same-date diagnostic classifies the 45 names as follows:

`outputs/run287_candidate_evaluation_funnel_20260715_v7/`

| Stage | Count | Names |
|---|---:|---|
| Current operating target | 7 | Main: `AMAT, GEV, GLW, LRCX, VRT`; Concentrated: `SNDK, WDC` |
| Current score gate rejected | 6 | `CDNS, COHR, ETN, INTC, LITE, SNPS` |
| Same-date advisory selector rejected | 13 | `ANET, APH, AVGO, BE, CEG, EME, FIX, KLAC, MTSI, NVT, PWR, TLN, TSM` |
| Same-date advisory selected but operating book differs | 5 | `COHU, DELL, FLEX, MRVL, UMC` |
| Research-context onboarding required | 14 | the fourteen outside-context names above |

The current operating artifact is selected-only. It does not contain an exact
same-date causal rejection ledger. The advisory selector's reasons are useful
diagnostics, but are deliberately marked non-causal for the operating book.
The dominant advisory reasons are `hold_replace_threshold_not_met` and, for
Concentrated challengers, `concentrated_requires_dual_leader`; `CEG` instead
fails `price_trend_not_alive`. Historical May rejection rows are also marked
non-causal. `LRCX` is a concrete proof: it was historically rejected but is in
the current Main target.

The five advisory-selected/operating-book divergences are a provenance and
same-date pipeline reconciliation task. They are not permission to trade.

## Full available history acquired

All collection was bounded and written to new append-only directories under:

`outputs/run287_candidate_full_history_20260715/`

### Price

- 45/45 tickers downloaded successfully with request start `1900-01-01` and
  end-exclusive `2026-07-15`, fixing the last completed common session at
  2026-07-14.
- The settled cache contains 285,987 observed daily rows. No pre-listing rows were
  fabricated.
- 38 names have the canonical seven-year price span.
- Seven have all available history but are structurally too young for the
  canonical comparison:

| Ticker | First observed | Last observed | Rows |
|---|---|---|---:|
| `CEG` | 2022-01-19 | 2026-07-14 | 1,124 |
| `CRWV` | 2025-03-28 | 2026-07-14 | 324 |
| `GEV` | 2024-03-27 | 2026-07-14 | 575 |
| `NBIS` | 2024-10-21 | 2026-07-14 | 432 |
| `SKHY` | 2026-07-10 | 2026-07-14 | 3 |
| `SNDK` | 2025-02-13 | 2026-07-14 | 354 |
| `TLN` | 2023-06-02 | 2026-07-14 | 780 |

The price cache builder now preserves non-US exchange suffixes such as `.KS`
while retaining the US class-share conversion such as `BRK.B -> BRK-B`.

### SEC accepted-time filings

- New targeted indexes contain 4,994 rows across 15 SEC tickers/issuers.
- Every new row has exact `accepted_at`; the observed range is
  1999-05-13 through 2026-07-14.
- The combined candidate coverage audit reports exact accepted-time coverage
  for 44/45 candidate tickers after joining the existing canonical index.
- `TSM` and `UMC`, initially exposed as gaps, received 770 and 596 rows
  respectively.

`000660.KS` remains the single explicit filing gap. `SKHY` provides an SEC
issuer proxy, but a new US ADR filing cannot be relabeled as historical Korean
home-market listing evidence. A future home-market collector must preserve the
actual DART receipt/availability timestamp and listing identity.

### Companyfacts

- Full per-CIK Companyfacts JSON was fetched for 15 bounded SEC CIKs; the
  remaining covered candidates use the frozen canonical SEC bulk archive.
- Coverage is 44/45. The only missing listing-specific route is again
  `000660.KS`.
- `SKHY` has a valid response but only 10 fact rows across two accessions. This
  is sparse new-ADR evidence, not a seven-year fundamental history.
- Companyfacts is issuer-level evidence. ADR and home-market listings must not
  silently inherit listing-specific history from one another.

The combined coverage freeze is:

`outputs/run287_candidate_full_history_20260715/coverage_audit_settled_20260714/manifest.json`

It hashes the candidate audit, 45-name price manifest, three accepted-time SEC
indexes, the 1.389 GB canonical Companyfacts archive, and two bounded
Companyfacts manifests.

An earlier append-only 45-name cache included a 2026-07-15 Korean intraday bar
while the Korean session was still open. It is retained for provenance but is
not authoritative. The settled `price_cache_all45_settled_20260714` cache is
the only price root used by the final v7 diagnostic and coverage freeze.

## Reusable implementation

- `docs/run287_candidate_evaluation_intake_20260715.csv` is a research-only
  intake; both promotion flags are fixed false.
- `tools/audit_run287_candidate_evaluation_funnel.py` emits the complete stage
  audit, bounded acquisition queue, fourteen-name shadow-context queue, and
  five-name selector-reconciliation queue. It separates operating causality,
  advisory diagnostics, historical diagnostics, missing data, and short
  listing history.
- `tools/fetch_companyfacts_for_sec_index.py` fetches full Companyfacts JSON
  only for CIKs in an explicit SEC index and enforces a request budget.
- `tools/audit_run287_candidate_full_history.py` freezes price, accepted-time
  SEC and Companyfacts coverage with hashes and explicit structural gaps.
- Focused smokes verify append-only behavior, no portfolio/universe mutation,
  suffix handling, short-listing classification, issuer-proxy isolation, and
  bounded Companyfacts collection.

## Next gate

1. Build a shadow feature context for the fourteen outside-context names using
   the same decision-time technical, fundamental, macro and risk contracts as
   the current universe. Missing components remain neutral.
2. Require component-level parity and record every gate outcome. Do not insert
   the names into the operating universe merely to make the existing selector
   score them.
3. Reconcile the five advisory-selected/operating divergences with an exact
   same-session selector-input and rejection archive before interpreting any
   selection difference.
4. Treat the seven short-history names as forward/available-history candidates;
   do not manufacture a seven-year comparison or replace them with an issuer
   proxy return series.
5. Keep historical portfolio A/B blocked until PIT membership, delisted returns
   and symbol predecessors are supplied. A shadow rank or good recent return is
   not CAGR/MDD evidence.

This is the closest safe route to evaluating names that the current fixed
universe misses while preserving the lessons from prior failed direct tilts and
avoiding survivorship leakage.
