# AlphaOps vNext Layer Decision Ledger - 2026-06-25

This ledger freezes the current evidence after merging the ChatGPT Pro and
Claude review guidance. It separates official full-run evidence from local
target-book screens so future work does not promote a layer from the wrong
measurement mode.

## Non-Negotiable Evidence Rules

- Primary strategy performance must be read from `broker_ledger_next_close`.
- Daily risk overlays must be labelled separately as
  `broker_ledger_position_risk_next_close`.
- Proxy, weight-level, forward-return, and overlay-only metrics are screening or
  audit evidence only.
- Forward returns may be written as audit labels, but must not affect ranking,
  target books, cash policy, or live signals.
- `pit_universe_label_clean=false` continues to block production promotion.
- No layer below is a live-trading or production-promotion approval.

## Authoritative Baseline

Source: run `28074476465`, official broker-ledger artifact.

| Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Years | Status |
|---|---:|---:|---:|---:|---:|---|
| Main | broker_ledger_next_close | 33.15% | -26.02% | 1.219 | 7.055 | research only |
| Concentrated | broker_ledger_next_close | 46.24% | -25.82% | 1.421 | 7.055 | research only |

Production remains blocked because the evidence contract is not PIT-universe
clean enough. The 7Y window is useful for research and A/B, not automatic
promotion.

## Layer Decisions

### 2026-06-25 Follow-Up Screens

These local screens reuse run `28074476465` artifacts. They are research-only
and do not create production approval. They update the earlier layer decisions
so failed layers are not retried unchanged, while useful diagnostics are kept.

| Layer | Result | Decision | Reusable part |
|---|---|---|---|
| SHAKEOUT_GUARD production wiring | Safe but `shakeout_guard_applied_count=0`; both portfolios had unchanged broker metrics. Main/concentrated blocks were mostly `classifier_not_shakeout:WARNING:relative_weakness_no_add`. | Do not treat as alpha lever. | Keep default-OFF plumbing and applied-count diagnostics; only revisit if replay rows carry stronger PIT leadership/smart-money fields and `applied_count > 0`. |
| Leadership-persistence hold | `0.75σ` applied but broker metrics were unchanged; `1.10σ` worsened both sleeves (Main CAGR 33.78%, Concentrated CAGR 39.72%). | Reject broad persistence rule. | Keep the principle that intact leaders deserve higher replacement proof, but future work must be ticker/era/PIT-signal targeted, not broad gap inflation. |
| Concentrated selective leader capture | Broad rule applied heavily and worsened Concentrated CAGR/MDD; tightened rank/top-RS version still failed once rank fallback made it active. | Reject current implementation. | Keep applied-count/rank/RS telemetry and the lesson that stronger candidates must be proven by ex-ante PIT signal quality, not just RS/rank replacement pressure. |
| Concentrated gross-floor sweep after env-wire fix | Floor `0.70/0.80/0.85/0.90` reduced CAGR from 41.67% to 39.92%/39.29%/38.54%/37.86% and worsened MaxDD to -32.69%/-34.97%/-36.60%/-38.16%. | Reject broad cash reduction. | Keep PR #174 wiring fix because it makes future sweeps honest; current cash is not idle drag in this screen. |
| Main position-risk grid follow-up | Best ranked hard `-30%` + trailing `-20%` improved Main MaxDD to -24.34% but CAGR fell to 33.08%; no gate-passing champion. | Reject as target-achieving layer. | Keep risk-exit artifact persistence/per-era diagnostics; a risk overlay may repair MDD only after a separate CAGR-positive lever exists. |
| Alpha/beta attribution name-contribution fallback | `positions_latest.csv` fallback produced non-zero partial name-contribution evidence where `holdings_daily.csv` was absent. Concentrated residual alpha annualized 29.18%, but top-5 contribution is partial and open-position biased. | Keep as diagnostic. | Use it to identify right-tail winners for a PIT entry-signal audit; do not use partial top-winner contribution as ship evidence. |
| Right-tail entry/capture audit | Run `28074476465` top open winners had PIT-visible entry signals: Main 5/5 and Concentrated 5/5 skill-evidence flags. But capture was fragmented: Main top-5 avg presence blocks 3.2 with 31 sells, 6 target-book drops, 6 reentries; Concentrated avg presence blocks 2.2 with 15 sells, 1 target-book drop, 1 reentry. Drop-date review found Main 6/6 drops still had skill-evidence signals and 2/6 were still rank >= 80th percentile; Concentrated 1/1 drop still had skill-evidence signal. | Keep as diagnostic and sidecar artifact. | Next lever should target fragmented capture of already-identified winners that still show PIT evidence at drop time, not broad exposure, broad persistence, or broad replacement acceleration. |
| Right-tail drop counterfactual audit | Full target-book drop scan found many missed-rebound examples, but broad continuation did not pass the average test. Main had 517 drops, 393 skill-signal drops, 140 high-signal drops; high-signal avg 63d/126d SPY excess was -1.03pp/-1.52pp. Concentrated had 190 drops, 153 skill-signal drops, 72 high-signal drops; high-signal avg 63d/126d SPY excess was -1.41pp/-0.73pp. Segment review found possible narrow leads, including Main high-signal `Capital Goods - Machinery` (n=5, avg 126d SPY excess +33.7pp, positive rate 80%) and Concentrated high-signal `Capital Goods - Machinery` (n=3, avg +19.6pp, positive rate 100%). Concentrated `Biotechnology` had high average (+52.0pp) but only 50% positive rate, so it is event-dependent. | Keep as diagnostic; reject broad drop-continuity hold. | Use segment summaries to audit rare large misses by theme, regime, event, and entry quality. Do not convert "dropped winner later rebounded" into a broad hold policy. A future rule must first prove a segment-level average advantage and PIT explanation. |

### Keep As Measurement / Plumbing

| PR | Layer | Decision | Reason |
|---:|---|---|---|
| #167 | Position-risk official baseline fallback | Keep, merge candidate | Prevents risk-grid screens from comparing against a zero or blocked baseline when official broker metrics live in `account_evaluation/official_metrics.json`. |
| #169 | Stock-selection forward audit labels | Keep, merge candidate | Adds review-only `forward_21d/63d/126d_excess` labels with `used_forward_return_in_ranking=false`; needed to identify missed-leader leaks without live lookahead. |
| #174 | Gross-floor sweep env wiring | Keep, merge candidate | Fixes a measurement no-op: `R1000_CONC_GROSS_CAP_FLOOR` now reaches the regime-capacity overlay. The measured broad floor lever failed, but the wiring fix is necessary for any future gross-exposure screen. |
| #175 | Alpha/beta name-contribution fallback | Keep, merge candidate after CI | Uses `positions_latest.csv` when `holdings_daily.csv` is absent so top-winner contribution does not silently report zero. Output is partial and labelled as such. |
| #176 | Right-tail entry signal audit | Keep, merge candidate after CI | Turns #175's top-winner contribution into a PIT entry-signal and drop-date audit. Realized PnL only chooses names for review; candidate/target-book fields at entry and drop dates decide whether the winner was ex-ante identifiable and whether dropped winners still had PIT-visible evidence. |
| #177 | Right-tail drop counterfactual audit | Keep, merge candidate after CI | Measures all target-book drop events with PIT-visible signal context plus forward-return audit labels and segment summaries. It preserves large missed-rebound examples while showing broad high-signal drop continuation has negative average SPY excess and should not be shipped as a broad hold lever. |

### Keep As Small Research Levers

| PR | Layer | Local broker-screen result | Decision |
|---:|---|---|---|
| #166 | Earnings revision break warning | Concentrated +0.22pp CAGR, -0.027pp MaxDD worse, Sharpe +0.006 | Keep default-OFF. Useful small component, not a standalone target fix. |
| #170 | Dynamic leader candidate rescue | Main-only replacement-gap credit +0.23pp CAGR, unchanged MaxDD, Sharpe +0.005 | Keep default-OFF and Main-scoped. Broad score bonus was rejected. |

### Keep As Main MDD Candidate, Not Production

Official artifact Main target book with daily trailing-stop overlay. The later
grid follow-up supersedes any loose "candidate" interpretation: no configuration
currently passes both Main CAGR and MDD gates.

| Trailing stop | Metric mode | CAGR | Delta CAGR | MaxDD | Delta MaxDD | Sharpe | Risk exits | Decision |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| Baseline | broker_ledger_next_close | 33.15% | - | -26.02% | - | 1.219 | - | Baseline |
| -25% | broker_ledger_position_risk_next_close | 34.26% | +1.11pp | -26.46% | -0.45pp | 1.277 | 11 | Reject: MDD worse |
| -30% | broker_ledger_position_risk_next_close | 34.46% | +1.31pp | -24.34% | +1.68pp | 1.271 | 6 | MDD repair screen only; not a champion |
| -35% | broker_ledger_position_risk_next_close | 34.85% | +1.70pp | -25.01% | +1.01pp | 1.279 | 2 | Near-target, but thin exit evidence and slightly misses MDD |
| -45% | broker_ledger_position_risk_next_close | 34.62% | +1.47pp | -25.70% | +0.32pp | 1.269 | 1 | Reject: MDD still fails |

Interpretation:

- `-30%` is the cleanest Main drawdown repair screen, but the follow-up grid
  found no gate-passing champion once CAGR target is enforced.
- `-35%` has better CAGR but only two exits and still does not clearly pass the
  -25% MDD gate on official artifact evidence.
- This is a daily risk overlay candidate, not a primary monthly target-book
  promotion.

### Reject / Do Not Recycle As-Is

| Layer | Evidence | Decision |
|---|---|---|
| Broad gross-floor / cash reduction | Concentrated floor 0.60-0.75 lowered CAGR to about 38.5-38.6% and worsened MaxDD to about -36.5%. | Reject. The cash was not idle in this implementation; broad exposure increase destroys drawdown. |
| Verified broad concentrated gross floor after PR #174 wiring | Floor `0.70` produced 39.92% CAGR / -32.69% MaxDD; floor `0.90` produced 37.86% CAGR / -38.16% MaxDD. | Reject. Keep only the env wiring. |
| Broad dynamic-leader score bonus | Main CAGR -0.61pp and MaxDD -1.82pp worse; Concentrated CAGR -4.35pp despite MDD improvement. | Reject. Keep only the narrower replacement-gap idea. |
| PR166 + PR170 combined screen | Main CAGR improved locally, but Main MaxDD stayed around -26%; Concentrated only +0.22pp. | Do not create combo PR. Merge and test independently. |
| Concentrated weak-only rescue local patch | Changed telemetry/rows but broker metrics were exactly unchanged. | Reject as no-op. |
| Shakeout guard as alpha lever | Plumbing is safe, but screens showed no material broker delta/no effective suppression. | Keep draft/plumbing only; not a priority alpha lever. |
| Broad leadership-persistence hold | `0.75σ` did not move broker metrics; `1.10σ` lowered Main to 33.78% CAGR and Concentrated to 39.72% CAGR. | Reject broad hold inflation. Future hold logic must be tied to PIT winner evidence, not broad state protection. |
| Concentrated selective leader capture | Broad and tightened variants failed to improve Concentrated CAGR and worsened drawdown when active. | Reject current form. Retain telemetry for diagnosing which replacement pressures are harmful. |
| Main position-risk grid as standalone solution | Best ranked grid improved MDD but lowered CAGR to 33.08%, leaving no gate-passing champion. | Reject as standalone. May be re-tested only after a CAGR-positive layer lifts Main above target. |
| Broad right-tail drop-continuity hold | Counterfactual audit found large individual missed rebounds, but the high-signal dropped subset averaged negative 63d/126d SPY excess in both portfolios. | Reject broad form. | Only segment-specific, PIT-explained rules may be considered later; broad "keep dropped winners" is not supported. |
| Segment examples from right-tail drop audit | Some high-signal segments had positive averages, but sample sizes are small and forward returns are audit labels. | Do not implement yet. | Treat as the next research queue: Main machinery/industrial infrastructure, Main energy, and concentrated machinery/biotech event cases should be reviewed with PIT entry quality, regime, and event evidence before any policy lever exists. |

## Current Ready / Near-Ready Merge Candidates

Ready, mergeable, CI green unless explicitly noted:

1. PR #167 - measurement correctness for position-risk baseline fallback.
2. PR #169 - missed-leader forward audit labels.
3. PR #166 - default-OFF earnings revision break warning.
4. PR #170 - default-OFF Main-only dynamic leader replacement-gap credit.
5. PR #174 - gross-floor env override wiring; measurement correctness only.
6. PR #175 - alpha/beta name-contribution fallback, if CI passes.
7. PR #176 - right-tail entry signal audit, if CI passes.
8. PR #177 - right-tail drop counterfactual audit, if CI passes.

Recommended merge order:

1. #167 and #169 first, because they improve measurement quality.
2. #174, #175, #176, and #177 next, because they close measurement blind
   spots found during the failed gross-floor, attribution, and right-tail
   screens.
3. #166 and #170 next, because they are default-OFF research levers.
4. Keep SHAKEOUT plumbing default-OFF unless a new screen proves
   `applied_count > 0` and broker-ledger behavior changes.

## Next Work Order

### Main

1. Do not ship `daily trailing -30%` as a standalone layer. It is an MDD repair
   screen that still misses the Main CAGR target.
2. Re-run risk overlays only after a separate CAGR-positive layer is found,
   ensuring:
   - baseline source is not zero or blocked,
   - `risk_exit_count > 0`,
   - `metric_mode=broker_ledger_position_risk_next_close`,
   - report remains review-only.
3. Do not combine with PR #170 until the interaction is explicitly measured,
   because the combo screen failed to keep Main MaxDD inside -25%.

### Concentrated

1. Do not use gross-floor/cash reduction as the next lever.
2. Do not retry the current selective leader capture rule unchanged.
3. Use #169, #175, and #176 together to isolate right-tail winner skill:
   - identify top contribution winners from labelled, partial name-contribution
     evidence,
   - inspect their entry-date PIT signals rather than their future returns,
   - compare missed leaders and selected leaders by era/theme,
   - audit drop dates where the dropped winner still had PIT skill evidence,
   - reject broad drop-continuity unless a segmented subset has positive
     average excess return and ex-ante PIT explanation,
   - only then design a narrower capture-continuity rule.
4. Any future capture rule must require applied-count telemetry, no forward
   returns in ranking, and broker-ledger CAGR improvement without MaxDD damage.

## Current State Summary

- The system is no longer missing one large obvious toggle.
- Main needs a CAGR-positive layer before risk overlays can finish the MDD
  repair without falling below the CAGR target.
- Concentrated needs evidence-driven right-tail capture diagnostics, not more
  gross exposure or broad replacement pressure.
- The current top right-tail names were generally identified ex ante; the
  stronger leak is fragmented capture after entry, especially drops where
  PIT-visible skill evidence was still present.
- The most important infrastructure now is accurate measurement: baseline
  fallback, forward audit labels, and strict separation of official target-book
  metrics from daily risk-overlay metrics.

