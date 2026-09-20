# Multi-Asset Leadership Engine V1 — implementation and remaining gates

Tracking issue: [#465](https://github.com/wscha231/r1000-quant-engine/issues/465).
Implementation PR: [#466](https://github.com/wscha231/r1000-quant-engine/pull/466).
Audited master: `4494d108a7ee535bae0bb50b594bd8cfb8164402`.
Branch: `codex/multi-asset-leadership-v1-20260920`.

This is a research extension inside R1000, not a new portfolio authority.
The complete user acceptance criteria have **not** yet been met. Tested code,
observed provider data, calibrated expected returns, accepted targets and
historical strategy performance are separate evidence levels.

## A. Starting state and reuse

- H1 #463 is merged. The supplied INPUT_INTEGRITY_FIX handoff predates that
  publication and is not the current source status.
- Registered champion remains `run287-generated-book-champion-20260710`,
  policy source `819cbaa905bab6a455ed3e7c2a2a90ae2824833a`.
  Production, live orders and automatic promotion remain disabled.
- Reuse `theme_etf_runtime_v1.strict.compute_leadership` for fixed-horizon
  log relative total returns and strict ETF snapshot normalization.
- Reuse `r1000_legacy_input_guard.latest_completed_close` and the NYSE
  exchange calendar, including holidays and early closes.
- Reuse `macro_history_sources.request_bytes`, `parse_graph`, immutable byte
  storage and bounded no-redirect HTTP handling.
- The existing daily research monitor is the scheduling parent. No second
  cron or broker caller is introduced. The follow-on workflow publishes its
  own `daily_monitoring_report.md` and machine-readable multi-asset artifacts.
- Current selector/exact-packet, current crisis sidecars, next-close ledger
  and benchmark policy remain the production interfaces. They are not
  replaced by this research proposal function.
- Existing ER challenger has only 1/3/6-month horizons and the historical
  `cross_sectional_percentile_rank_missing_to_neutral_0_5` rule. It is **not**
  imported as a cross-asset evaluator or used to invent a 12-month forecast.
- Existing news PR #459, unified-universe #445, control-plane #451 and
  theme-source bridge #464 were unmerged at audit. Their source stacks are
  not copied. Normalized event/evaluation/base-universe interfaces are ready
  for their accepted outputs; producer wiring remains a separate dependency.
- Do-not-repeat registry was inspected. No RS-only replacement rule,
  broad gross floor, fixed commodity sleeve or historical threshold fit is
  activated. The risk packet supplies ceilings, never allocation floors.

Latest inspected scheduled evidence (not an exhaustive current run census):

| Run | Result | Relevant boundary |
|---|---|---|
| 35443247344 | success | Daily research report creation only |
| 35440144851 | failure | Collect full history / persist / clean consumption step |
| 35424976962 | failure | Restore verified risk-outcome accepted head; prices, targets and paper transaction skipped |
| 35412739085 | success | Free-data workflow status, not certified current complete coverage |

Canonical Drive accepted book/catalog were not restored in this task. Existing
failure states were not rerun or bypassed. No actual holdings are inferred from
the historical FTI/CACI/FLEX/NVT/CLS/ONTO/RBRK research examples.

## B. Implementation

| Path | Purpose |
|---|---|
| `research/multi_asset_v1/contracts.py` | Strict IDs, classes, units, timestamps, source roles and separate reviewed pins |
| `research/multi_asset_v1/prices.py` | Complete session grids, reused log-RS, volatility/drawdown/MA, acceleration, winsorized z/percentiles and correlated horizon block |
| `research/multi_asset_v1/decisions.py` | Event clusters, reviewed multi-horizon ER, candidate states, recursive ETF exposure, constrained research proposals |
| `research/multi_asset_v1/runtime.py` | Common candidate table, underlying/network metrics, separate crypto clocks, diagnostics and replay blockers |
| `research/multi_asset_v1/sources.py` | Coinbase UTC bars/recent NY snapshots, explicit UTC proxy fallback and FRED oil/gas observations |
| `tools/run_multi_asset_leadership.py` | Pinned input/capture CLI, immutable attempts and failure revocation |
| `docs/multi_asset_registry_v1.json` | 12 underlying research seeds and 32 instruments including SPY benchmark |
| `docs/multi_asset_policy_v1.json` | Fixed baseline, source roles, units; empty evaluator/risk/holdings approval pins |
| `.github/workflows/multi_asset_leadership_v1.yml` | Python 3.11/3.13 PR checks and read-only capture after existing daily monitor |

The normalized input is `multi-asset-input-v1`. Required input hash is supplied
outside the payload. Evaluator/model/risk/holdings approvals live in a separately
reviewed policy; an input cannot approve itself. These pins still depend on
reviewed producers: byte hashes alone do not authenticate economic claims.

Candidate discovery and expected-return rank have different columns. Incomplete
base-universe coverage suppresses global rank. A proposal requires admitted
existing equity comparisons, reviewed net expected returns for every selected
asset, liquidity, same-grid correlations, risk ceilings and complete ETF
look-through. A commodity or crypto allocation can be zero. No proposal writes
an accepted target, paper fill or actual broker book.

## C. Asset scope

| Underlying | Registered research vehicles |
|---|---|
| Gold | GLDM, WPM |
| Silver | SIVR, PAAS |
| Copper | CPER, FCX |
| Uranium / fuel chain | CCJ, LEU, URNM |
| Natural gas | EQT, AR |
| Oil | XLE, XOM |
| Lithium | ALB, SQM |
| Rare earth | MP |
| Potash | NTR, MOS |
| Nitrogen | CF |
| BTC | BTC-USD, IBIT, COIN (company exposure kept separate) |
| ETH | ETH-USD, ETHA |

The seven example equity candidates are seed references, not a replacement for
the complete existing universe. Registry supports all requested asset-class
labels; specific non-MVP underlyings and futures contracts are not silently
treated as supported live products. Every seed has `tradable=false` until
account eligibility is established. SOL is not admitted.

Official product identity references read on 2026-09-20:
[GLDM](https://www.ssga.com/us/en/individual/etfs/spdr-gold-minishares-gldm),
[CPER](https://www.uscfinvestments.com/cper),
[IBIT](https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf),
[ETHA](https://www.ishares.com/us/products/337614/ishares-ethereum-trust-etf).
Other seed listing checks are pending; registration is not a current tradability
claim. ETHA's issuer notice announces a reverse split after the 2026-10-05
close; no ratio is inferred. ETHA stays in corporate-action quarantine.

## D. Data integrity and collection limits

- Inputs carry observed/available/collected times, source, data quality and raw
  hash. No naive/future time, wrong currency/unit, boolean numeric, synthetic
  source, duplicate identity or stale/latest-date substitution is accepted.
- Equity/ETF Yahoo adjusted-close history is explicitly a
  `PROVIDER_ADJUSTED_CLOSE_PROXY`. Research RS can be computed and labeled, but
  these proxy inputs cannot admit ER or a target proposal.
- Coinbase daily bars use UTC boundaries; hourly bars ending at the true NYSE
  close produce a separate NY snapshot. Hourly volume is never daily volume.
  V1 capture requests 280 daily bars and 120 hourly bars per token. That is **not**
  a full NY-close history or multi-venue admission. Missing history remains
  blocked. [Official candle semantics](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles).
- When Coinbase fails, a separately labeled Yahoo crypto UTC proxy may be
  captured. Partial calendar days and null closes are omitted, never filled.
  Failed primary-source receipts remain visible. This fallback cannot supply
  NY snapshots, network fundamentals or a total-return admission.
- [FRED gas](https://fred.stlouisfed.org/series/DHHNGSP) and
  [FRED WTI](https://fred.stlouisfed.org/series/DCOILWTICO) adapters reuse the
  current-history reader. Observation date is a date label; availability is
  actual retrieval. They do not manufacture original publication timestamps.
  Spot prices are not supply-demand, inventory or scarcity scores.
- Unit-aware metric admission supports commodity/network observations, but
  LME/SHFE inventories, uranium term/SWU/HALEU prices, WASDE/CFTC vintages,
  mining costs/CAPEX, ETF flows, ETH/BTC network metrics and company analyses
  are not automatically collected by this patch.
- Article events propose thesis review and affected-asset recomputation.
  Syndicated duplicates cannot multiply a catalyst score. No sentiment-to-buy
  path exists. Canonical news collection still awaits its accepted producer.
- Source errors are controlled labels. Old successes retain their original
  bytes; the current attempt revokes consumption before input reads/capture.
  Only complete admitted output may advance `last_success.json`.
- Workflow artifacts retain diagnostics for 45 days. Raw provider snapshots
  are local to the attempt and **not** yet durably archived to Drive; this is a
  blocker for longitudinal shadow operation. No durable-history claim is made.

## E. Validation

The offline smoke suite uses explicitly synthetic fixtures. Unique test count
and final execution evidence are recorded in the PR/handoff update, not inferred
from a workflow title. It tests time/units/missing data, exchange sessions,
independent RS formula parity, reviewed evaluation pins and costs, RS-only
hold, no commodity floor, cross-asset competition, ETF overlap, failed refresh,
tamper detection, both crypto clocks and source parsers. Existing strict
Theme/ETF regressions are also run. Python `-O` is a rerun, not extra tests.

The protected full Tier-1 registry and gate policy are not altered. The new
dedicated required-by-path workflow executes the new tests. Remote CI and
exact-head independent review remain separate from local results.

## F–G. Actual result and historical validation

At the first direct probe the Financial Datasets SPY history request returned
an insufficient-credit response. Local public Yahoo/Coinbase HTTP probes could
not initially connect. A subsequent real capture completed on
`2026-09-20T04:26:16.884123+00:00`, through the `2026-09-18` NYSE close:

- 30 US-listed instruments including SPY, 281 rows each: **8,430 price rows**.
- 28 non-benchmark assets have computed proxy RS20/60/120/240. ETHA remains
  quarantined; direct BTC/ETH source calls failed on both clocks.
- Two actual FRED observations: gas **2.97 USD/MMBtu**, WTI **107.02 USD/barrel**,
  both observed **2026-09-15**, collected on September 20. Their observation
  dates were not advanced to the collection date.
- Input SHA256: `e4bd9a0d666129f9b3263f0486d68a1ac9a2f2d3d0dd8f2b6a3a38ed9ff2b682`.
- Reprocessed the exact captured input from the committed implementation tree;
  output remains `PARTIAL_RESEARCH`, global rank false and all ER fields null.
- A separate real BTC/ETH UTC fallback probe captured 729 rows per token.
  Both feeds had no September 19 close; the unfinished September 20 quote was
  excluded. These histories therefore remain blocked as current inputs.
  Combined input contains 9,888 price rows, SHA256
  `92a7438d61e4dd8e998e14155a7462c560a0dd26749c98cdf7efc7448fbdad6a`.

Within this **28-name seed cohort only**, the proxy discovery order began
RBRK, FCX, NTR, WPM, XLE, CPER, IBIT, NVT. This is a measured price/volatility
screen, not the requested whole-universe expected-return investment rank.
RBRK and CPER were classified Emerging; FCX and WPM Established. NTR and XLE
had weaker acceleration/longer-horizon state despite a high composite rank.
There were **zero BUY_CONSIDERATION** rows. No fundamentals or news score was
invented to turn these observations into a buy proposal.

Local initial publication evidence: 45 distinct new tests plus 12 existing
tests passed. Follow-up regressions bring this to **58 distinct new tests plus
12 existing tests**. Python `-O` repeats the same 58 cases. The first remote
matrix run `35489119713` exposed one packaging omission: the test reads its
workflow YAML but sparse checkout omitted `.github`. Added the declared path;
the test remains mandatory and unchanged. This does not weaken a data gate.

Independent Codex review of initial head `516c15fc2faf2f2f31ebfd0726630dcf5a303796`
identified four P1 defects. The follow-up adds regressions and fixes: risk-blocked
results cannot return CLI success or be consumed, normalized ETF availability
must precede the cutoff, carried ETF vehicle weights obey the security ceiling,
and payload flags cannot override a registry corporate-action quarantine.
The updated head requires its own CI and independent review before merge.

The second independent review (`f7b9587fe3`) found seven further issues, all
addressed with focused coverage: fail closed when a held benchmark lacks a
correlation comparator; require full source/time metadata on base-universe
and position receipts; retain the authorized input byte hash separately from
canonical payload identity; strictly type identity flags; date merged event
attributes at their latest contributing availability; publish sanitized source
receipts in result artifacts; and trigger integration tests on shared dependency
changes. A held asset also cannot receive an addition when its reviewed thesis
is negative/missing or valuation is unacceptable. Short-RS hold preservation
and separately authorized risk reduction still apply.

No verified current Top Leaders, BUY_CONSIDERATION, replacement trades or
CAGR/MDD are reported. The replay preflight exposes A–E comparisons and six
ablations as **BLOCKED**. It is not a newly implemented portfolio backtester.
Reuse of the canonical next-close/cost kernel requires admitted PIT universe,
price/corporate actions, vintage fundamental/news data, model validation,
cost receipts and the named replay preflight. Current downloaded histories
cannot be relabeled PIT. No fullrun was executed.

## H–I. Publication and remaining gates

Publication follows local diff/tests -> branch/PR -> exact-head independent
review -> required checks -> expected-head merge -> post-merge check. User
authorization covers this sequence; no gate is removed to finish it.

| Priority | Remaining item |
|---|---|
| P0 | Existing accepted-state recovery and full-equity current evaluation remain blocked upstream |
| P1 | Current confirmed listing/account eligibility; full NY crypto history and multi-venue/liquidity admission |
| P1 | Genuine total-return/corporate-action evidence; durable source archive and restore |
| P1 | Canonical news, commodity/network fundamentals, company and underlying thesis evaluators |
| P1 | Calibrated 1/3/6/12-month net ER and separate reviewed risk packets |
| P1 | Complete PIT 7–10-year replay, A–E/ablation/walk-forward evidence and shadow period |
| P2 | Broad commodity/group benchmarks, incremental execution cache, richer daily transition alerts and UI |

## J. [PROJECT_HANDOFF]

- Date: 2026-09-20 UTC.
- Fact: canonical master includes #463; new multi-asset research extension is
  based on that exact source. Accepted production policy is unchanged.
- Inference: reuse of strict RS/calendar/input contracts avoids a second
  selector and limits duplicate development against pending news/theme PRs.
- Decision: no fixed sleeve, no RS-only sells, no missing-to-neutral scoring,
  no invented ER, no orders and no model promotion.
- Changes/artifacts: paths in section B; immutable attempt outputs and status
  receipts. Code/source/config/input/output hashes are separate fields.
- Unverified: live full-cohort data, accepted books, durable new source history,
  model calibration, portfolio OOS performance, remote review/merge until linked.
- Next: finish exact-head review/CI; connect accepted whole-universe and news
  producers, actual source archives and validated ER model; then named replay
  and shadow validation before a production-promotion review.
- Stop condition: invalid/stale/future/unit-conflicting input, missing reviewed
  evaluator/risk/holdings evidence, failed accepted-state or replay preflight.
- Confidence: high only for the tested rejection and deterministic calculation
  boundaries; no current investment ranking or return target is certified.
