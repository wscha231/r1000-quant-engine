# Follow-up Review: Codex W0/W1 remediation + cash/count guard (4ca027fd..385634f1)

> Reviewer: Claude (session 01EFuqqTBYNezRzskPLMHdKU)
> Branch reviewed: `codex/alphaops-integrated-replay` @ `385634f1`
> Prior review: `docs/CODEX_W0W1_REVIEW_9b2ce49.md` (commit `0a70ff4`)
> Method: per-finding diff verification (`git diff 9b2ce49..385634f1`) + workflow/wiring grep
> No research/proxy metric is treated as production evidence in this review.

---

## 1. Scorecard vs prior review (what Codex closed)

| Prior finding | Status at 385634f1 | Evidence |
|---|---|---|
| C1 — legacy verdict vocabulary ambiguity | **CLOSED** | `run_local.py:654,656` relabeled `PARTIAL`/`REGRESS` → `RESEARCH_ONLY_PARTIAL`/`RESEARCH_ONLY_REGRESS` |
| C2 / Patch 2 — strict-targets off on PR | **CLOSED** | `portfolio_system_guard.yml:71` now `github.event_name == 'pull_request' || inputs.strict_targets` |
| C3 / Patch 1 — 4 smokes unregistered | **CLOSED** | `tools/run_pr_validation.py` registers all four; 72→76 tests (matches reported 76/76 PASS) |
| C4 / Patch 3 — cash drift time-axis bias | **CLOSED** | `validate_target_book_cash_contract.py` emits dual-method drift: `rebalance_day_*` (merge_asof forward, ≤2d tolerance, limits 2/5pp) + `month_mean_*` (ffill-then-month-mean, limits 5/10pp). Both must pass. Documented in `docs/METRIC_HYGIENE.md`; both methods propagated into `run_broker_gap_attribution` summary |
| C8 — validators not auto-wired | **MOSTLY CLOSED** | `run_full_rebuild_sidecars.py` calls `run_cash_contract_validator` in both operating_minimal/official and full profiles; `alphaops_replay_sidecars_manual.yml` calls cash contract + `run_fast_full_drift_audit.py` |
| C5 — fast/full drift not causally attributed | **OPEN** | no `tools/run_score_drift_audit.py`; audit still emits symptom (metric drift + jaccard) without per-(date,ticker) cause. User confirms drift remains unexplained |
| C6 — `fill_lag_slippage` is metadata, not measurement | **OPEN** (minor) | field not renamed; still listed among decomposed terms |
| C7 — `sidecar_only_verify.yml` missing on codex branch | **PARTIALLY CLOSED** | now registered on master (`8eb4ad5`, `9d34e73`, `b8e645c`) but still MISSING on `codex/alphaops-integrated-replay` |
| OOS lock (W0 spec §2.3) | **OPEN** | no `oos_start` reference anywhere in tools/ or run_local.py |

Bottom line: all three suggested patches were applied essentially verbatim, with
the exact thresholds proposed (rebalance-day 2/5pp, month-mean 5/10pp). The two
structural items I called "necessary for a defensible forward-robustness claim"
— C5 root-cause audit and the OOS lock — are both still missing.

---

## 2. New code reviewed: `main_cash_position_count_contract` ladder

`tools/run_portfolio_system_guard.py:183-202` adds a hard-error check on the
latest main target book shape:

- cash ≥ 25% → stock_count ≤ 8
- cash ≥ 20% → stock_count ≤ 12  (the check that fired on run 27350855795)
- cash ≥ 15% → stock_count ≤ 15

Exit semantics (`:1226-1229`): hard errors fail the process only under
`--strict-targets` or `--require-latest-artifacts`. Smoke coverage added in
`tests/portfolio_system_guard_smoke.py`. The harmful auto-narrowing generator
from `fda47429`/`3ffaf09b` was correctly reverted in `385634f1`.

**Verdict: KEEP as tripwire, with two flags that need a decision.**

### F1 — Guard hard-error × Patch 2 will turn ALL PRs red once the violating book is published
The guard's default `--latest-run` is
`cloud_results/full_rebuild/latest_global_alpha_universe`. The currently
committed artifact predates the contract (its `error_check.json` has no
`main_cash_position_count_contract` row). The next full rebuild that publishes
the current best book — **cash 20.00%, 15 stocks** (run 27350855795) — will
commit a violating artifact. From that moment, `portfolio_system_guard.yml`
runs `--strict-targets` on every `pull_request` (Patch 2), sees the
pre-existing hard error, and **fails every PR regardless of the PR's content**.

This may be intentional (a forcing function: nothing merges until the
shape question is resolved). If so, accept the triage cost explicitly. If not,
the fix is to distinguish *pre-existing artifact violations* from *violations
introduced by the PR*: on `pull_request` events, compare `error_check.json`
hard errors against the same check run on the base ref's artifact, and only
fail on NEW violations (or downgrade pre-existing ones to `warning` with a
visible banner).

### F2 — The contract encodes a shape the A/B evidence says is optimal to violate
The three-run experiment chain is unusually clean evidence:

| Run | SHA | Change | Main CAGR | Main MDD |
|---|---|---|---|---|
| 27346338968 | fda47429 | narrow to 12, cash lowered | 31.62% | **-43.70%** |
| 27348552261 | 3ffaf09b | narrow to 12, cash preserved | 30.80% | **-33.59%** |
| 27350855795 | 385634f1 | narrowing removed (15 names, 20% cash) | **33.12%** | **-24.31%** (Sharpe 1.329) |

Both available paths to *satisfy* the contract (cut cash, or cut names)
degrade MDD by 9-19pp. So the contract currently asserts "this shape is
suspicious" while the broker evidence says "this shape is the best measured
configuration". The thresholds (25→8, 20→12, 15→15) were chosen, not derived —
the same failure mode I flagged for the original 2pp/5pp cash thresholds.

**The only legitimate exit is threshold re-derivation from attribution, not
book modification.** Until then the guard is a deliberate red light, which is
honest — but F1 means that red light blocks unrelated merges.

---

## 3. The decisive next test (sharpens Codex's stated next action)

Codex's stated next step — "trade attribution으로 분해: why 15 names/20% cash
defends MDD, which 3 names break MDD if removed" — is right but
under-specified. The direct instrument is **leave-k-out broker replay** on the
27350855795 main book:

1. **k=1 sweep** (15 replays): drop each name, re-normalize remaining weights
   per existing book rules, run `run_broker_ledger_replay.py` next_close,
   record ΔMDD/ΔCAGR per dropped name. Names whose removal worsens MDD by
   >1.5pp are the defensive core.
2. **Greedy k=3** (≤39 more replays): iteratively remove the name whose
   removal *least* damages MDD. If a 12-name book exists with MDD ≤ -27%
   (within 3pp of -24.31%), the contract threshold `20%→12` is achievable and
   the guard stands. If every 12-name book has MDD > -30%, the threshold is
   wrong and should be re-derived to `20% → ≤15` (or conditioned on a measured
   diversification statistic, e.g. max pairwise sector correlation, rather
   than raw count).
3. Each replay is ~minutes on cached prices; the whole sweep fits in one
   sidecar dispatch. Output: `outputs/leave_k_out_attribution/summary.json`
   with per-name ΔMDD ranking — which is *exactly* the user's "which 3 names"
   question, answered with broker evidence instead of reasoning.

This also resolves F2 with data: either the ladder gets a justified threshold,
or the 15-name shape gets a justified exemption.

---

## 4. Assessment of the user's four improvement directions

1. **Single-name cap (LRCX 50%) before broker MDD pass — AGREE, cheap.** The
   concentrated book has no max-weight error check in the guard today. A
   `concentrated_max_single_name_weight` hard check (e.g. ≤ 40% pre-pass) is
   ~10 lines next to the cash/count ladder, with the same strict-only exit
   semantics. Also worth a sector-concentration variant: LRCX/AMAT/SNDK is one
   semi-equipment bet; `concentrated_max_single_industry_group_weight ≤ 60%`
   would have flagged it.
2. **Stability bonus / turnover penalty — AGREE on the diagnosis, but it is a
   scoring-policy change**, which means full A/B under the broker gate, not a
   guard patch. Cheaper first step is pure measurement: extend
   `run_fast_full_drift_audit.py` to emit per-name appearance counts across
   the last N (fast, full) run pairs. Names like SNDK/WDC/CIEN/LITE/MU/AMAT/LRCX
   that recur across both modes get a `persistence_score`; one-run wonders are
   visible before any policy change is attempted. This is also the C5
   instrument — one tool serves both.
3. **Leader-persistence criteria (vs raw score) — defensible but blocked on
   C5.** Until score drift between fast/full is attributed, adding persistence
   features risks rewarding *stale data* (a name persists because the fast
   path reuses last month's feature store) rather than true leadership.
   Sequence: C5 score-drift audit → then persistence features.
4. **HOLD/WARNING/TRIM/EXIT state machine forced into broker replay — already
   ~70% exists, in the right place.** `hold_replace_decision` is produced
   upstream and consumed throughout `run_alphaops_vnext_policy_replay.py`
   (8 call sites) and carried by `run_trade_attribution_analysis.py`. The
   broker replay itself is a dumb executor by design — forcing state
   transitions there would duplicate policy in the measurement layer. The
   actual gap is *enforcement*: nothing today fails a target book whose
   month-over-month exits violate the state machine (e.g. HOLD → absent with
   no TRIM/EXIT_REVIEW intermediate). A `hold_replace_transition_contract`
   check in the system guard (validate transitions between consecutive
   committed target books) gets the user's intent without touching broker code.

---

## 5. Priority order (recommendation)

1. **Decide F1 before the next full rebuild publishes artifacts** — otherwise
   PR CI goes red repo-wide and the team starts overriding the guard, which
   destroys its value. (1-line decision: forcing function vs base-ref diff.)
2. **Leave-k-out replay sweep (§3)** — answers the user's "which 3 names"
   question AND re-derives or retires the 20%→12 threshold. Everything else
   downstream depends on this evidence.
3. **C5 score-drift audit + persistence measurement (§4.2)** — one tool, two
   findings closed; precondition for any stability-bonus policy work.
4. **Concentrated max-name/max-industry guard checks (§4.1)** — cheap, closes
   the LRCX-50% class of books at the gate.
5. **OOS lock** — still the only defense against window overfitting; three
   review cycles have now deferred it.

Items NOT recommended right now: any new scoring features (blocked on 3), any
further book-shape generators (the fda47429/3ffaf09b evidence is conclusive
that shape surgery without attribution destroys MDD).
