# Codex Directive — Post-Run287 Reinforcement (R1–R5)

> Author: Claude Code (web reviewer), 2026-07-06. Consumes the pushed run287
> evidence on `codex/integration-fullrun-clean-20260630` @ `d21b9858`
> (measurement contract, generated-book negative evidence, forensics, rolling
> deficit, W1 double-run, exit-latency audit, candidate-1 rejection).
> This directive is **measurement/research only**. It authorizes **no fullrun,
> no production mutation, no threshold tuning, no new alpha promotion**.
> It is the follow-through after the honest state below was established.

## 0. Established state (do not re-litigate — these are settled by measurement)

Latest-basis generated book (run287 / GHA `28725350727`), broker-ledger:

| Portfolio | zero-yield | cash-carry | Target | Rolling last-252 pass rate |
|---|---|---|---|---|
| Main | 32.94% / −25.65% | 33.81% / −25.36% | 35% / −25% | **0.0%** |
| Concentrated | 47.00% / −23.22% | 48.41% / −22.96% | 50% / −25% | **2.8%** |

Settled facts (from `d21b9858`):
- **Cash-carry does not close the gap.** Decision label `alpha_candidate_rejected_on_generated_book`.
- **~60–70% of the frozen→generated drop is the honest 2026-07-02 window** (late-June/early-July shock), not a proven hook failure. Frozen `36.33/52.14` stopped at `2026-06-29`.
- **Main MDD is structural, not a July shock.** MaxDD window `2021-11-19 → 2022-09-26` (2022 bear). Exit-latency audit: `hard_signal_count=12`, `material_latency_count=0`, alignment 1–3 days → **exit-timing is NOT a Main MDD lever.**
- **Conc cap/replacement with rank/RS/revenue is exhausted.** `concentrated_cap_replacement_leader_capture_v1` best arm `+0.01pp` → rejected.
- **W1: local same-input determinism proven (0/0/0, Δw=0.0); official runner parity NOT proven** (local candidate cache smaller than the runner cache).
- Both headline numbers are **survivorship-inflated** (`pit_universe_label_clean=false`, `current_constituents_proxy`).

Conclusion driving this directive: **the obvious alpha levers are spent.** The
leverage is now (R1) making local == runner, (R2) sizing the true survivorship
gap, (R3) the one remaining legitimate Main MDD lever, (R4) a user decision on
Conc's data source, (R5) contract hardening. Grinding more rank/RS/revenue
variants is forbidden.

## Global non-negotiables (inherited; apply to every item below)

- No new fullrun dispatch. No production promotion. No live trading. No public/service performance wording while `pit_universe_label_clean=false`.
- No falsified-lever revival: broad bull-floor/gross-floor, broad hold/exit-delay, **cap-safe per-name sizing**, crash predictors, VIX/DD breakers fitted to the July or 2022 path, tighter stops, revision-proxy confirmation.
- Forward returns are **audit labels only**, never live ranking inputs.
- No hand-edited hindsight: never preserve/drop a ticker because it later won/lost; never pick `2026-06-29` to avoid the July shock; never re-pick a threshold after observing run287 losses.
- Every performance table carries the run287 measurement-contract required fields (`metric_mode`, `target_book_source`, `replay_end_date`, `actual_equity_curve_end_date`, `price_cache_status`, `pit_universe_label_clean`, `production_promotion_allowed`, …).
- One WIP pair at a time (≤2 in flight). Each item terminates in a committed verdict (pass → candidate; fail → negative-evidence doc).

---

## R1 — Runner-parity price cache (FIRST; removes the asterisk on every local result)

**Why.** All current attribution (window, drift, exit-latency, rolling deficit)
runs on a **local** generated book whose price cache is smaller than the
`28725350727` runner cache. Local book ≠ runner book is an uncontrolled
confound under every local conclusion.

**Work.**
- Restore the run287 runner price cache locally (source: the run's committed
  `cloud_results/.../reports/*` price manifests + `outputs/run287_price_cache_latest/cache_prices`), OR enumerate exactly which tickers/bars the local cache is missing versus the runner manifest.
- Re-run the W1 double-run (`R1000_CATBOOST_TASK_TYPE=CPU`, `shadow_only`) and the metric sidecar on the **parity** cache.
- Compare the parity-cache generated book to the run287 runner target book (ticker set, per-date weights).

**Files.**
- `tools/run287_parity_cache_restore.py` (new)
- `outputs/run287_parity/{missing_bars.csv, book_parity.csv, summary.json, report.md}`
- extend `tools/run287_forensics.py` to accept a `--parity-cache` path

**Acceptance (numeric).**
- Local generated book matches the run287 runner book within the W1 tolerance
  (`0/0/0` date/ticker mismatch, `max_weight_delta_abs ≤ 1e-9`), **OR**
- a documented `missing_bars.csv` listing every differing ticker/bar **and** a
  measured `book_parity.csv` quantifying the CAGR/MDD impact of the difference.
- `summary.json` emits `runner_parity_status ∈ {parity_exact, parity_documented_gap, blocked}`.

**Anti-leakage gate.** Parity restore must not silently drop tickers to force a
match; every excluded bar is listed with a reason. No end-date change.

---

## R2 — Survivorship inflation bound (sizes the TRUE gap before any alpha spend)

**Why.** `48.41` is treated as "−1.59pp from target," but the book is
survivorship-inflated. If inflation is +3pp the real number is ~45% and the gap
is ~5pp — which changes whether alpha grinding is even rational.

**Work.**
- Measure current-constituents-proxy run (what we have) vs a stricter arm that
  admits, at each rebalance date, only names with actual price history as of
  that date (reuse `apply_historical_membership_filter` /
  `load_historical_universe_membership`, `r1000_pipeline.py`).
- Report the CAGR/MDD delta as the **late-inclusion (one-sided) inflation**.
- Explicitly state the un-measurable component: delisted-name exclusion cannot
  be recovered on free tier → this is a **partial lower bound**, labelled `proxy`.

**Files.**
- `tools/run287_survivorship_bound.py` (new)
- `tests/run287_survivorship_bound_smoke.py` (new)
- `outputs/run287_survivorship/{summary.json, report.md, membership_delta.csv}`

**Acceptance.**
- `summary.json` emits `survivorship_inflation_estimate_cagr_pp` (one-sided
  lower bound), `method`, `unmeasured_component="delisted_exclusion"`,
  `label="proxy"`.
- `report.md` states the real (deflated) Main/Conc gap range.

**Anti-leakage gate.** The stricter arm uses only `available_from`/first-bar
dates known at each rebalance date — no forward membership, no delisted
backfill invented from current data.

---

## R3 — Main correlated-cluster exposure cap (the one remaining legitimate MDD lever)

**Why.** The 2022 MaxDD was a **single correlated cluster** (long-duration
growth: NET/ENPH/U/DDOG/SNOW fell together). Exit-timing cannot help — trend
breaks only after the correlated gap-down. The sole ex-ante defense is
**entry-time diversification** (cap aggregate weight in one correlated cluster),
which is decision-time observable and distinct from the falsified per-name
cap-safe sizing.

**Work.**
- Define cluster ex-ante from existing taxonomy (`themes.yaml` / industry
  group) **or** rolling trailing-return correlation (decision-time only).
- Add a rebalance-time cap on aggregate weight per cluster (default OFF, env
  `PHASE_MAIN_CLUSTER_EXPOSURE_CAP_ENABLED`, `R1000_MAIN_CLUSTER_CAP`).
- Test hook-off vs hook-on on the parity generated book (post-R1), cash-carry,
  `2026-07-02`, across **≥2 drawdown eras** (2022 and one other).

**Files.**
- cluster-cap hook in the existing sizing path (reuse cluster-HHI infra); guard with `phase_is_enabled`
- `tools/run287_cluster_cap_counterfactual.py` (new)
- `tests/run287_cluster_cap_smoke.py` (new)
- `outputs/run287_cluster_cap/{summary.json, report.md, arm_metrics.csv}`

**Acceptance (JOINT + MULTI-ERA — all must hold to become a candidate).**
- MDD pulled inside −25% in **≥2 distinct drawdown eras** (not just 2022), AND
- Main CAGR stays **≥35%** (headroom is only ~0.57pp at 06-29 — report ΔCAGR AND ΔMDD), AND
- effect present on both zero-yield and cash-carry arms.
- Single-era-only improvement, or CAGR breach, → **reject; write negative evidence.**

**Anti-leakage gate.** Cluster membership defined **only** from data observable
at the rebalance date. The cap is a general threshold predeclared before replay;
it may **not** be tuned to the 2022 names. Distinguish in the doc from
"cap-safe sizing" (falsified) — this is aggregate-cluster diversification, not a
per-name safety cap. Honest prior: **likely to fail the joint gate** (capping a
winning cluster costs CAGR); this earns exactly one cheap counterfactual.

---

## R4 — Concentrated alpha source decision (USER DECISION — do not proceed unilaterally)

**Why.** The forward-label screen shows Conc's missed leaders are real
(`cap_or_replacement` 126d excess +9.26%), but candidate-1 proved they are
**unreachable by rank/RS/revenue**. Conc CAGR alpha is therefore a **data-feed
problem, not a threshold problem** — it needs a decision-time source stronger
than rank/RS/revenue (earnings/guidance event, insider, 13F = the deferred W4
feed).

**Action = surface to the user, then stop.** Two options; the user chooses:
- **(a) Unblock the W4 EPS/guidance (or insider/13F) feed** and build the Conc
  hook on that new decision-time source.
- **(b) Accept Conc ~48% as the honest ceiling on this book** and stop Conc
  alpha work.

**Forbidden without a decision.** Any further rank/RS/revenue cap-replacement
variant (dead vein), any Conc hook that merely restores a one-endpoint 50% print.

**Files (documentation only until the user decides).**
- `docs/CODEX_CONC_ALPHA_SOURCE_DECISION_20260706.md` stating the two options,
  the evidence, and `status=awaiting_user_decision`.

---

## R5 — Measurement-contract hardening (closes the last leakage seams)

**Why.** The contract is strong; two required fields and one gate are missing so
that no headline can be quoted without the survivorship + parity caveats, and so
forward-label-sourced ideas are always OOS-revalidated.

**Work — extend `docs/CODEX_RUN287_MEASUREMENT_CONTRACT_20260706.md` and the emitters.**
- Add REQUIRED performance fields: `survivorship_inflation_estimate` (from R2)
  and `runner_parity_status` (from R1) — assert their presence in the forensics/
  sidecar `summary.json`.
- Add an explicit written gate: **any forward-label-identified opportunity
  requires the capturing rule to be re-validated OOS before promotion** (record
  the candidate-1 case as the worked example — screen said +9.26%, ex-ante rule
  delivered +0.01pp).
- Wire the two new fields into `tests/run287_forensics_smoke.py` (fail if absent).

**Files.**
- `docs/CODEX_RUN287_MEASUREMENT_CONTRACT_20260706.md` (edit)
- `tools/run287_forensics.py`, `tools/alphaops_governance.py` (emit fields)
- `tests/run287_forensics_smoke.py` (assert fields)

**Acceptance.** `run_pr_validation` selected smokes pass; forensics `summary.json`
carries both new fields; contract text includes the forward-label OOS gate.

---

## Sequencing & verdict gates (Claude will check)

1. **R1 ∥ R2 first** — parity + true-gap are the foundation for every later judgment.
2. **R3** after R1 (needs the parity book) — one cheap joint+multi-era counterfactual.
3. **R4** is a user decision, surfaced in parallel; no code until answered.
4. **R5** once R1/R2 emit their fields.

Verdict gates:
- R1: `runner_parity_status` emitted; exact match OR a quantified documented gap.
- R2: one-sided inflation bound with method + `proxy` label; deflated gap stated.
- R3: JOINT (ΔMDD inside −25 in ≥2 eras) AND (CAGR ≥35) on both accounting modes, else negative evidence.
- R4: decision doc with `awaiting_user_decision`; no rank/RS/revenue variants shipped.
- R5: two required fields asserted in smoke; forward-label OOS gate written.

Every item ends in a committed verdict. No fullrun until R1–R3 land, a candidate
clears its gate, and the user explicitly approves one run.
