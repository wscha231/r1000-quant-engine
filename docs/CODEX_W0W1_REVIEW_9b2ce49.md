# Code Review: AlphaOps vNext v2.1 W0/W1 Implementation (commit 9b2ce49)

> Reviewer: Claude (session 01EFuqqTBYNezRzskPLMHdKU)
> Branch: codex/alphaops-integrated-replay
> Method: code grep + diff (29c2df0..9b2ce49) + automated workflow inventory
> No research/proxy metric is proposed as production evidence in this review.

---

## Critical findings

### C1 — `run_local.py` broker gate has a closed seam, but two production paths still surface legacy metrics
**Severity: medium.** The verdict block (lines 491-535) refuses to SHIP unless
`official_metric_mode == broker_ledger_next_close` AND
`valid_for_production == true` AND broker metrics file exists. That seam is tight.

But two adjacent paths still expose target-weight numbers and `CURRENT_BASELINE`
side-by-side in the printed report. They are labelled "research-only" but a human
reading the output may treat the legacy SHIP line just above as authoritative.
The legacy block (`run_local.py:419-468`) still computes `dCAGR`/`dSharpe`/`dMaxDD`
vs target-weight `CURRENT_BASELINE` and prints SHIP/PARTIAL/REGRESS — i.e. the
SAME verdict vocabulary as the broker block 70 lines below.

This is not a code bug — it is a `print()` UX trap that has already caused at
least one false SHIP claim in this project's history (run 27247439447, target
SHIP at +6.11pp while broker was +0.25pp). Two readers may legitimately disagree
about which block to believe.

### C2 — `portfolio_system_guard.error_checks` flips `main_metrics_available` to broker path, but `broker_or_legacy_metrics()` still falls back to legacy when broker missing
**Severity: medium.** `tools/run_portfolio_system_guard.py:257-263` (the diff): on
broker absence, legacy metrics are loaded and tagged `valid_for_production=False`
plus `DO_NOT_USE_FOR_PRODUCTION=True`. The downstream `portfolio_status()`
(:177-203) gates `cagr_pass`/`max_dd_pass` on `official_source`, so a legacy
fallback CANNOT produce target_pass=True. **The gate itself is correct.**

The hole: `--strict-targets` is the boolean that decides whether `target_pass=
False` raises a workflow error. In the workflow `.github/workflows/
portfolio_system_guard.yml`:14 it **defaults to false**, and pull_request events
do not set it. So a PR with legacy-only metrics → target_pass=false → workflow
green. The contract validator never fires in CI on PRs.

### C3 — Four new smoke tests are NOT registered in `tools/run_pr_validation.py`
**Severity: high (automation regression risk).** Codex's "72/72 PASS" came from
running the validation tool with these four smokes added locally. But
`tools/run_pr_validation.py` on commit 9b2ce49 does NOT contain entries for:
- `tests/broker_gate_contract_smoke.py`
- `tests/cash_contract_smoke.py`
- `tests/fast_full_drift_audit_smoke.py`
- `tests/broker_gap_attribution_smoke.py`

`.github/workflows/pr_validation.yml` calls `run_pr_validation.py` and that is
the only canonical Tier-1 list. **So today's CI on a new PR does NOT exercise
these new contracts.** Anyone can land a regression that breaks the cash
contract validator and CI will stay green.

### C4 — `cash_drift_summary()` compares apples to oranges on the time axis
**Severity: medium-to-high.** `tools/validate_target_book_cash_contract.py:188-228`:
- target side: `target.groupby("month_end").agg(target_cash_weight=("cash_weight","mean"))`
  — `cash_weight` PER REBALANCE DATE is averaged within the month it falls into.
- broker side: `cash_ledger.csv` resampled to month-end via daily `.mean()`.

These are not the same physical quantity. **Target cash is INSTANTANEOUS at
rebalance** (the policy weight on the day the book is set). **Broker cash is
ROLLING DAILY AVERAGE within the month**, which compresses across the month and
naturally diverges from the rebalance-day target by some amount (e.g. equity
drift, in-month price moves).

The 16pp / 23pp drifts Codex reported are partially **methodological**, not
purely operational. The fair comparison is one of:
  (a) compare target at rebalance_date to broker cash on `next_close` of that
      rebalance_date (the day the book was actually executed); or
  (b) compare month-AVERAGED target (forward-filled between rebalances) to
      month-AVERAGED broker (current implementation), but document this is a
      lower bound on "agreement" not the true drift.

Today's threshold (mean ≤ 2pp, max ≤ 5pp) was calibrated to method (b)
implicitly. Switching to (a) will likely TIGHTEN the realistic drift toward
<5pp, which is a sharper diagnostic. If we stay on (b), the thresholds need
re-derivation from a known-good run.

### C5 — `run_fast_full_drift_audit.partial_fast_only` masks the deeper question
**Severity: medium.** `tools/run_fast_full_drift_audit.py:184` declares
`partial_fast_only` if fast passes broker gate but full does not — i.e. the
**measurement** is that fast outperforms full. The decomposition does NOT
attribute the gap. The audit emits:
- `metric_drift` (raw CAGR/MDD deltas)
- `target_jaccard` (set similarity of held tickers)
- `artifact_summary` (file presence)

It does NOT emit: candidate score drift between fast and full at matching
(date, ticker), rebalance schedule drift, fill-price drift on identical
positions, fee/turnover drift. These are the four mechanisms by which an
"identical policy" can produce different broker numbers. Without them, the
audit names the symptom (fast > full by N pp) without locating the cause.

### C6 — `fill_lag_slippage` is a placeholder, not a measurement
**Severity: low (honest but unfixed).** `run_broker_gap_attribution.py:343-347`:
```python
fill_lag = {
    "fill_mode": broker.get("fill_mode"),
    "max_fill_lag_days": broker.get("max_fill_lag_days"),
    "reason": "per-fill price slippage attribution is not emitted by broker replay yet",
}
```
Honest comment, but the gap decomposition now claims this term as one of nine
attributable components in `run_broker_gap_attribution.summary.json`. A reader
of the summary may assume slippage is being measured at 0 when it is actually
unmeasured. The residual term absorbs it, but residual >30% disqualifies the
decomposition per its own contract.

### C7 — `sidecar_only_verify.yml` is NOT on the codex branch
**Severity: medium (operations).** Confirmed via `git cat-file -e
9b2ce49:.github/workflows/sidecar_only_verify.yml` → MISSING. The codex review's
earlier instinct to fall back to `alphaops_replay_sidecars_manual.yml` was
correct for THIS branch even though the file exists on claude/master. If W0/W1
work continues on the codex branch only, the fast-loop sidecar workflow is
unavailable until merged.

### C8 — Automated wiring does not enforce the new validators on the right cadence
**Severity: high.** Inventory of where the new tools fire automatically:
| Tool | full_rebuild_manual.yml | alphaops_replay_sidecars_manual.yml | pr_validation.yml | portfolio_system_guard.yml (auto on PR) |
|---|---|---|---|---|
| run_broker_gap_attribution.py (extended) | ✅ called | ✅ called | n/a | ❌ not called |
| validate_target_book_cash_contract.py | ❌ not called | ❌ not called | ❌ not registered as smoke | ❌ not called |
| run_fast_full_drift_audit.py | ❌ not called | ❌ not called | ❌ not registered as smoke | ❌ not called |
| 4 new smokes | n/a | n/a | ❌ not registered | n/a |

So the contract validator and drift audit will only run when a human explicitly
invokes them. The whole point of W0/W1 was to make broker gate **automated**.
This is the single largest hole in the implementation.

---

## Suggested patches (smallest first — three high-leverage)

### Patch 1 — Register the four new smokes in PR validation (1 file, 4 lines)
**Why first**: zero risk, unblocks automated CI enforcement of contracts that
already work.

File: `tools/run_pr_validation.py`. Append to the test list (any position):
```python
    ("tests/broker_gate_contract_smoke.py", []),
    ("tests/cash_contract_smoke.py", []),
    ("tests/fast_full_drift_audit_smoke.py", []),
    ("tests/broker_gap_attribution_smoke.py", []),
```
Verification: `python tools/run_pr_validation.py --quiet` → 76/76 PASS. CI on
the next PR runs them automatically.

### Patch 2 — Make `portfolio_system_guard.yml` enforce strict-targets on pull_request
**Why second**: closes C2 — the gate itself is correct, but isn't gated on
the cadence where most regressions arrive (PR review).

File: `.github/workflows/portfolio_system_guard.yml`. In the "Run portfolio
system guard" step, change:
```yaml
STRICT="${{ inputs.strict_targets || false }}"
```
to:
```yaml
STRICT="${{ inputs.strict_targets || (github.event_name == 'pull_request' && 'true') || 'false' }}"
```
Result: every PR runs `--strict-targets`, which causes `target_pass=false` to
fail the workflow. Manual dispatches keep their explicit choice.

### Patch 3 — Add the rebalance-day cash comparison method to the cash contract
**Why third**: closes C4 (methodological bias). The current month-mean vs
month-mean comparison conflates rebalance timing with cash drift.

File: `tools/validate_target_book_cash_contract.py`, function
`cash_drift_summary()` (around :186). Compute BOTH methods and emit them:
```python
# (a) rebalance-day method
rebal_target = target.copy()
rebal_target["rebalance_date"] = pd.to_datetime(rebal_target["rebalance_date"])
# broker daily cash → reindex on rebalance dates, take next-business-day close
broker_daily = read_csv(...)  # already read above as cash_ledger
broker_daily["date"] = pd.to_datetime(broker_daily["date"])
rebal_compare = pd.merge_asof(
    rebal_target.sort_values("rebalance_date"),
    broker_daily.sort_values("date").rename(columns={"date": "rebalance_date"}),
    on="rebalance_date",
    direction="forward", tolerance=pd.Timedelta(days=2),
)
rebal_drift_abs_pp = (rebal_compare["broker_cash_weight"]
                     - rebal_compare["cash_weight"]).abs() * 100.0
# emit alongside the existing month-mean drift
```
Threshold proposal: BOTH must pass.
- rebalance-day method: mean ≤ 2pp, max ≤ 5pp (today's limits — likely fits
  tighter on this method).
- month-mean method: mean ≤ 5pp, max ≤ 10pp (relaxed because methodologically
  it includes legitimate within-month drift).

Acceptance: re-run the validator on full 27088007617. If rebalance-day mean
drift stays large (>2pp), it is operational drift; if it collapses, the prior
flag was largely the time-axis artifact.

---

## Tests / commands

Local (before push):
```bash
python tools/run_pr_validation.py --quiet              # → 76/76 PASS after Patch 1
python tests/cash_contract_smoke.py                    # standalone
python tests/fast_full_drift_audit_smoke.py            # standalone

# On an existing artifact (Patch 3 verification):
python tools/validate_target_book_cash_contract.py \
  --target-book outputs/reports/operating_main_target_book.csv \
  --broker-dir outputs/broker_replay/main \
  --output outputs/cash_contract/main.json
# Confirm both rebalance_day_* and month_mean_* keys appear in the JSON.
```

CI verification:
- Open a PR with Patch 1 + 2 + 3 → `pr_validation.yml` shows the four new
  smokes pass; `portfolio_system_guard.yml` runs with `--strict-targets` and
  fails on cash drift if any.
- Dispatch `alphaops_replay_sidecars_manual.yml` to regenerate broker
  artifacts, then trigger `portfolio_system_guard.yml` against that artifact.

---

## Ranked hypotheses for the fast/full drift (C5 root-cause hunt)

Without per-(date,ticker) score comparison the audit cannot decide. Likelihood
ranking based on fast vs full mechanics:

1. **Candidate freshness / score recomputation drift** (highest). Fast replay
   reuses the previous full rebuild's `feature_store_latest.parquet` and
   `scored_latest.csv`. Full rebuild rebuilds them from scratch with current
   data (different SEC filing cutoffs, different FRED revisions). A name
   ranked #5 in fast can sit at #15 in full purely because the underlying
   data updated. Jaccard 0.77 (main) / 0.69 (concentrated) is consistent with
   this — same policy, different inputs.
2. **Operating target export drift** (high). The export path
   `build_operating_target_books.py` is invariant code; if it produced different
   books fast vs full, the cause is upstream (#1) plus possibly different
   selection_audit/champion-filter inputs.
3. **Broker fill / rebalance path** (low). The same `run_broker_ledger_replay.py`
   runs in both modes with identical params. Differences here would imply a
   non-deterministic ordering or floating-point sensitivity — unlikely
   dominant.
4. **Price cache drift** (medium). If `cache_prices/` was extended between fast
   replay (run 27086825471) and full rebuild (run 27088007617), late-window
   bars differ. This affects late-window MDD calculation more than CAGR.
5. **Cash ledger timing** (low). Same broker code, same fill mode; unlikely
   to materially differ given same target book.
6. **Pure target book difference** (covered by #1).

**Concrete next test** (small, decisive): write
`tools/run_score_drift_audit.py` that joins fast's `scored_latest.csv` with
full's on (date, ticker) and emits the top-30 by absolute rank change. If
hypothesis #1 is correct, rank changes will be concentrated on names whose
fundamentals/SEC overlay changed (visible in `data_pit/sec/*` mtime). Then a
PARTIAL_FAST_ONLY verdict resolves to "underlying data refreshed between fast
and full" rather than "implementation drift" — which is a different kind of
acceptable.

---

## Overfitting / complexity risks

- **Cash contract thresholds (2pp/5pp) were not derived from data**, they were
  chosen. C4 patch will surface whether the methodology — not the policy —
  drove the 16-23pp drifts. If after Patch 3 the rebalance-day drift is still
  >5pp, retain the threshold; if it collapses to <2pp, the original threshold
  was matching the wrong method.
- **`partial_fast_only` is a new verdict bucket**. Adding verdict states without
  a clear forward action (when does a partial become a full SHIP? what causes
  rollback?) is complexity debt. Recommend documenting transition rules in
  `docs/METRIC_HYGIENE.md` (already added by 9b2ce49 — extend it).
- **No OOS lock** despite W0 spec calling for it. v2 plan §2.3 proposed
  `oos_start: 2024-07-01` with `max(5pp, IS_CAGR × 0.20)`. Not implemented.
  Without this rail, repeated SHIP retries on the same window will eventually
  overfit even under the new broker gate.

## Auto-execution audit (사용자 추가 요청)

자동 워크플로우 인벤토리 30개 중 새 contracts와 직접 관련된 4개:

| Workflow | trigger | 새 contract 호출? | 보완 필요 |
|---|---|---|---|
| `pr_validation.yml` | pull_request | ❌ 4개 smoke 미등록 | **Patch 1** |
| `portfolio_system_guard.yml` | pull_request + dispatch | ✅ guard 자체는 broker gate, but ❌ strict-targets off on PR | **Patch 2** |
| `alphaops_replay_sidecars_manual.yml` | dispatch only | ✅ gap_attribution 호출, ❌ cash_contract / drift_audit 호출 안 함 | gap_attribution 다음 줄에 cash_contract + drift_audit 호출 추가 |
| `full_rebuild_manual.yml` | dispatch | ✅ gap_attribution, ❌ 나머지 | 위와 동일 |

스케줄 자동 실행 (`after_close_daily`, `data_readiness_preflight`,
`daily_crisis_monitor`, `weekly_data_refresh`, `monthly_research`,
`quarterly_auto_learning` 등 12개) 중 broker gate를 자동으로 검증하는
워크플로는 **없음**. 야간 자동 회귀가 broker gate를 통과하는지 매일
확인하려면 `after_close_daily.yml` 또는 `data_readiness_preflight.yml`에
짧은 broker gate check 단계를 추가하는 것이 다음 단계.

---

## Verdict per Codex's request

| Component | Decision |
|---|---|
| W0 broker gate in `run_local.py` (broker-only SHIP path) | **KEEP** — closed seam, no false-positive route. C1 is a UX nit, not a correctness bug. |
| Legacy verdict block still printed | **REVISE** — relabel printed banner to `RESEARCH-ONLY DELTA REPORT` and suppress SHIP/PARTIAL/REGRESS vocabulary in the legacy block to remove ambiguity. |
| `portfolio_system_guard` broker-gate logic | **KEEP** — correct. |
| `portfolio_system_guard.yml` default `strict_targets=false` on PR | **REVISE** — Patch 2. |
| `validate_target_book_cash_contract.py` core logic | **KEEP** with **REVISE** to add rebalance-day comparison (Patch 3); month-mean alone is biased. |
| `run_fast_full_drift_audit.py` (current decomposition) | **REVISE** — add per-(date,ticker) score-drift and rebalance-schedule comparisons before the audit is decisive. |
| `run_broker_gap_attribution.py` extension (9 decomposed terms) | **KEEP** with one **honest fix**: rename `fill_lag_slippage` to `fill_lag_metadata` until actual per-fill slippage is computed (the field today is metadata only). |
| Four new smoke tests | **KEEP**, must be **REGISTERED** (Patch 1). |
| `sidecar_only_verify.yml` absent on codex branch | **REVISE** — either merge from master or use `alphaops_replay_sidecars_manual.yml` consistently. Don't reference both in plans without a path discipline. |
| OOS lock | **MISSING** — implement before any further SHIP retry. Three sessions of broker gate hardening without OOS lock will still overfit the same 8y window. |
| Sidecar wiring of new contract validators | **REVISE** — add `validate_target_book_cash_contract.py` + `run_fast_full_drift_audit.py` to both `alphaops_replay_sidecars_manual.yml` and `full_rebuild_manual.yml` right after the `run_broker_gap_attribution.py` invocation. |

**Bottom line on user's CAGR/MDD-and-future-robustness ask**: This commit makes
the gate honest (the biggest blocker to future improvement was a wrong gate
declaring SHIP at +6pp while broker was +0.25pp). It does NOT yet measure
fast/full drift causally, and it does NOT yet have an OOS lock — both are
necessary for "앞으로도 계속 성과를 낼 수 있을지" to be a defensible claim.
The three small patches above plus an OOS-lock implementation push the system
into a state where every SHIP claim is verifiable and every regression has a
named root cause.
