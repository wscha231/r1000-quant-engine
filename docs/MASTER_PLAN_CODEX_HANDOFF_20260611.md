# MASTER SYSTEM PLAN — Codex 5.5 Implementation Handoff

> Date: 2026-06-11 · Author: Claude (session 01EFuqqTBYNezRzskPLMHdKU)
> Branch context: `claude/analyze-updated-code-OfEbu` (HEAD f7306b2) on top of master
> Implementer: Codex 5.5 writes the detailed code. This document is the spec.

---

## 한국어 요약 (Executive Summary)

**목표**: 전 기간 CAGR·MDD를 리얼 거래소 검증 기준(broker-ledger)으로 최대화하고,
**미래에도 성과가 유지**되도록 (과적합 방지·매크로 역사 학습·복잡도 축소) 시스템을 재구성한다.

**핵심 진단** (이번 세션 실측 증거 기반):
1. **최대 알파 풀은 새 시그널이 아니라 측정 갭**: target-weight 30.62%/-17.73% vs
   broker-ledger 20.80%/-32.65% (main). CAGR 9.8pp / MDD 14.9pp가 체결 음영에서 증발.
   현금 28% (target) vs 5.9% (broker 평균) 불일치가 1순위 용의자.
2. **위기 방어는 지금까지 휴면이었다**: crisis_score 천장 0.43 < defense 게이트 0.50
   (실데이터 확정) + 위기 엔진이 SHA1 해시 가격 캐시를 못 읽음. 둘 다 수정됨, 검증 대기.
3. **SHIP 판정이 잘못된 지표를 본다**: target-weight로 SHIP 선언하는 동안 broker-ledger는
   평탄. 게이트 자체를 broker-ledger로 교체해야 함.
4. **과적합 위험**: 같은 8년 윈도에서 베이스라인을 반복 회전. 2020+ holdout 잠금 필요.
5. **복잡도 부채**: 27k줄 모놀리스, 사이드카 67개, price IO 4중 중복, REJECTED phase
   코드 잔존. 삭제가 알파다.

**버릴 것**: Phase 3/5/11 코드 표면, 중복 replay 사이드카(~20개), run_local.py 과거
baseline dict 3개 중 2개, 중복 price reader.

**작업 순서**: W0 측정 무결성 → W1 broker 갭 → W2 위기 검증 → W3 리더 수명주기 측정
→ W4 데이터 해자 → W5 빼기 정리 → W6 미래 견고성.

---

## 0. Evidence Base (do not re-derive; cite these runs)

| Fact | Source |
|---|---|
| Target-weight: CAGR 30.62%, Sharpe 1.745, MDD -17.73% | run 27247439447 verdict.log |
| Broker-ledger main: CAGR 20.80%, MDD -32.65%, fees $40.1k, avg cash 5.9% | broker_replay/main/metrics.json |
| Broker-ledger concentrated: CAGR 31.50%, MDD -38.26%, fees $78.6k/408 trades | broker_replay/concentrated/metrics.json |
| Latest target book carries 28% CASH | verdict.log Top-10 table |
| Crisis score OLD max 0.43 (< defense 0.50), NEW renormalized 0.956 on same features | run 27313522414 crisis-diagnose line |
| Dead crisis components were market_trend+breadth (price-cache SHA1 filename miss), NOT FRED | same |
| Governor deltas while dormant: main +0.45pp CAGR / +0.00pp MDD | run 27247439447 [integrated] lines |
| Leader hardening (WARNING no-add, prev-first, pool×4, smart-money clip, holding diags) already merged on master | r1000_market_leader_engine.py:26-27,580-686 |
| Crisis walk-forward splits exist: train 1990-2002 / val 2003-2009 / test 2010-2019 / holdout 2020+ | r1000_long_crisis_liquidity.py:16-22 |
| Price cache depth: `price_history_years: 15` (≈2011+) — 2008 equity replay impossible today | r1000_config.py:2065 |
| Price IO duplicated: 4× `px_cache_name`, 2× `load_price_series` + crisis builder's broken 3rd variant | grep audit 2026-06-11 |
| research_full profile: 67 sidecar invocations | run_full_rebuild_sidecars.py |
| Phase 11 multibagger: A/B REJECT (-1.73pp CAGR + sleeve_cap bug) | CHANGELOG 13448 |
| Phase 3 (renorm), Phase 5 (leader/laggard): REJECTED, default OFF, config surface remains | r1000_config.py:98,1941,2592 |
| Fast loop exists: sidecar_only_verify.yml (collector-cache restore + fixed-builder rebuild) | master b8e645c |

---

## 1. North Star & Gate Redefinition (W0 — do this FIRST)

### 1.1 The only official metric is broker-ledger next-close
**Problem**: `run_local.py` SHIP/PARTIAL/REGRESS gates compare target-weight metrics.
Run 27247439447 declared SHIP at +6.11pp while broker-ledger moved +0.25pp.

**Spec for Codex**:
- File: `run_local.py`. Replace the gate inputs: read
  `outputs/broker_replay/{main,concentrated}/metrics.json` and gate on those.
  Keep target-weight numbers as informational lines (the cross-check block from
  commit 628822e already prints both — invert which one decides).
- New gate constants (vs the broker baseline to be locked in W0.3):
  `SHIP: dCAGR_broker >= +0.5pp AND dSharpe_broker >= -0.05 AND dMDD_broker >= -3pp`.
- Add `--gate-mode {broker,target}` flag defaulting to `broker` (escape hatch for
  research comparisons).
- Acceptance: verdict.log on next full run shows `gate_mode=broker_ledger` and the
  SHIP line cites broker numbers.

### 1.2 Out-of-sample lock (anti-overfit)
**Problem**: every baseline rotation tuned on the same 8y window. Future performance
is the user's stated priority; in-sample SHIPs do not predict it.

**Spec**:
- New file: `tools/run_oos_lock_audit.py`.
- Lock definition file `research/oos_lock.yaml`:
  `oos_start: 2024-07-01` (final 2 years of the 8y window untouched by tuning).
- The tool recomputes broker-ledger metrics twice from `equity_curve.csv`:
  in-sample (start..oos_start) vs OOS (oos_start..end), emits
  `outputs/oos_lock/oos_report.json` with `cagr_is, cagr_oos, mdd_is, mdd_oos,
  oos_degradation_pp = cagr_is - cagr_oos`.
- HARD RULE for all future SHIPs: `oos_degradation_pp <= 8` else verdict capped at
  PARTIAL. Wire into run_local.py verdict and the full-rebuild Verdict step.
- Acceptance: smoke test with synthetic equity curve verifying split math + gate.

### 1.3 Lock the broker baseline
- Add `BROKER_BASELINE` dict to run_local.py:
  `{main: {cagr: 0.2080, sharpe: 0.991, max_dd: -0.3265}, concentrated: {cagr: 0.3150, sharpe: 1.050, max_dd: -0.3826}}`
  (source: run 27247439447). All W1+ work measures against THIS, not target-weight.

---

## 2. W1 — Close the target-vs-broker gap (largest pool: ~10pp CAGR / ~15pp MDD)

### 2.1 Gap attribution tool (build FIRST, fix SECOND — no blind fixes)
**Spec**:
- New file: `tools/run_broker_gap_attribution.py`.
- Inputs: `outputs/reports/main_monthly_weights.csv` (target),
  `outputs/broker_replay/main/{equity_curve,trades,holdings_daily,cash_ledger}.csv`,
  `cache_prices/` (sha1-named — use shared loader from W5.1).
- Decompose monthly return difference target_minus_broker into additive terms:
  1. `fee_drag` (from trades.csv fees / equity)
  2. `integer_share_residual` (target weight − achievable weight at fill price)
  3. `fill_lag_slippage` (signal-close→fill-close price move × turnover)
  4. `cash_timing` (target CASH weight − broker cash weight) × period return
  5. `residual` (unexplained — must be < 30% of total gap or the model is wrong)
- Output: `outputs/broker_gap_attribution/attribution_monthly.csv` + summary.json
  with per-term annualized pp + report.md ranking the terms.
- Acceptance: synthetic-fixture smoke (known fee/lag/cash inputs → exact terms);
  on real data, terms sum to total gap within 1pp/yr.

### 2.2 Cash-handling audit (suspect #1)
**Hypothesis**: `build_operating_target_books.py` drops or renormalizes CASH rows,
so broker replay stays ~94% invested while the target backtest enjoyed up to 28%
defensive cash (this alone could explain a large share of the 15pp MDD gap).

**Spec**:
- Audit `tools/build_operating_target_books.py`: trace what happens to rows with
  `ticker == CASH` / weight sums < 1.0 from `main_monthly_weights.csv` into
  `operating_main_target_book.csv`. Likely culprit: a weight renormalization to 1.0.
- Fix: preserve explicit CASH rows end-to-end; `run_broker_ledger_replay.py` already
  treats CASH tickers as uninvested (CASH_TICKERS set) — verify and add a regression
  test: a book with 30% CASH must produce ~30% avg cash in the replay over a flat
  price fixture.
- Acceptance: gap attribution `cash_timing` term shrinks toward 0 on re-run;
  broker MDD improves materially (expected: several pp).

### 2.3 Fee/turnover drag (concentrated $78.6k)
**Spec**:
- Reuse `tools/run_broker_execution_policy_replay.py` (bands exist). Add a grid run
  for concentrated: `buy_band ∈ {0.03,0.05,0.08}`, `sell_band ∈ {0.05,0.08,0.12}`,
  `min_trade_value_usd ∈ {500, 1000}` (new param to skip dust trades).
- Output comparison vs no-band baseline; select by top-3-median CAGR with
  MDD no worse than +1pp.
- Acceptance: fees reduced ≥30% with CAGR loss ≤0.3pp on the same book, else reject.

---

## 3. W2 — Crisis defense: verify the resurrection + learn from macro history

### 3.1 Re-run the fast verify loop (already built; first action after W0)
- Dispatch `sidecar_only_verify.yml` (master b8e645c): source_run_id=27247439447,
  ref=claude/analyze-updated-code-OfEbu, rerun_long_crisis_learning=true.
- Read: `crisis_features_diagnosis_fixed.json` must show market_trend+breadth LIVE
  (the sha1 fix) and score percentiles; `delta_report.md` must show governed MDD
  delta ≠ 0; reentry diagnostics populated.
- Gate (report-only): main mdd_delta ≥ +5pp, concentrated ≥ +8pp on the leader books.

### 3.2 Macro-history learning hardening (사용자 요구: 역사상 매크로 변화 학습)
The walk-forward scaffolding exists (1990-2002 train / 2003-2009 val / 2010-2019
test / 2020+ holdout). Gaps to close:

**Spec**:
- a) **Re-learn thresholds on the renormalized score** (distribution shifted ~2.2×).
  Already auto-runs in the official profile; verify `best_thresholds.json`
  validation row uses the new score (check `crisis_gate` > 0.45 — old-scale values
  near 0.3 indicate stale learning).
- b) **Per-crisis-type replay matrix**: extend
  `tools/run_long_crisis_validation_report.py` to emit per-episode rows
  (2000 dot-com, 2008 GFC, 2011 debt-ceiling, 2015-16 China, 2018 Q4, 2020 COVID,
  2022 inflation) with: days-to-defense from episode start (목표: 사전/초기 진입),
  max cash reached, days-to-reentry after bottom, false-positive episodes/yr
  (defense entered, SPY 3m later +5% → false alarm).
  Crisis features reach 1990 via FRED even though equity replay is 15y — label
  episodes on features, replay equity only where prices exist.
- c) **VIX-only rule already enforced** (`requires_liquidity_trend_credit_confirmation`)
  — add a unit test asserting a VIX-spike-only fixture does NOT cross the cash gate.
- Acceptance: validation-report shows defense triggered in ≥5/7 episodes with
  false-positive rate ≤ 1/yr on test+holdout splits.

### 3.3 Liquidity component (currently a structural zero)
- Implement SPY dollar-volume z-score (60d) as the `liquidity` sub-score in
  `run_crisis_signal_builder.py` (volume column already in the price cache parquets;
  verify via shared loader). Keep renormalization so absence still degrades safely.
- Acceptance: component_coverage shows liquidity live; 2020-03 fixture scores >0.5.

---

## 4. W3 — Leader lifecycle: measure what's built (이탈 늦지 않게 / 너무 빨리 안 팔기)

The state machine (HOLD / WARNING no-add / EXIT_REPLACE / SHAKEOUT_GUARD) is merged
but UNMEASURED. Build the measurement, then tune only what the data indicts.

**Spec**:
- New file: `tools/run_leader_lifecycle_audit.py`.
- Inputs: `outputs/market_leader_challenger/{leader_state_history,churn,target books}`
  + price cache.
- Emit per-event analytics:
  1. **Rotation lag**: for each EXIT_REPLACE, days from that name's relative peak
     (vs QQQ) to exit fill; distribution + median (목표 중앙값 ≤ 40 거래일).
  2. **Premature-sell counterfactual**: for each exit, the exited name's next-126d
     excess return vs its replacement's — negative mean = exits добавляют alpha,
     positive = selling too early.
  3. **Shakeout-guard hit rate**: names held via SHAKEOUT_GUARD — % that recover to
     new 6m relative highs within 90d (목표 ≥ 55%) vs WARNING-trimmed names.
  4. **Re-entry capture**: after crisis reentry events, % of prior leaders
     re-acquired within 2 rebalances.
- Output: `outputs/leader_lifecycle_audit/{events.csv,summary.json,report.md}`.
- Wire into official sidecar profile after the challenger. Smoke with synthetic
  state histories.
- Only AFTER this data exists: tune `classify_leader_state` thresholds (one knob at
  a time through the fast loop, never the full grid at once).

---

## 5. W4 — Data moat completion (already-built, needs one live pass each)

| Item | State | Action |
|---|---|---|
| ETF N-PORT historical PIT (`build_etf_nport_history.py`, codex branch) | built+tested, never run live | dispatch ETF monthly refresh on the branch carrying it; confirm `coverage_etf_ratio ≥ 0.30` |
| Top7 manager lane (`build_top_manager_discovery_signals.py`, codex branch) | wired, needs full-run proof | confirm `coverage_top_manager_ratio ≥ 0.05` next full run |
| Coverage gate warn→fail flip | warn-only | per `docs/DATA_COVERAGE_GATE_LOCKDOWN.md` after layers prove |
| R1000 membership PIT-safety | flagged "not proven PIT-safe" (free-tier history) | new audit: compare membership snapshot dates vs usage dates; quantify survivorship bias on 1 backtest (replay with membership lagged +1 quarter; if CAGR delta > 1pp, prioritize a PIT membership source) |
| Branch unification | data-moat work on `codex/alphaops-integrated-replay`, leader/crisis on `claude/...` | merge codex branch → claude branch (or master) BEFORE W4 verification so one full run exercises everything |

---

## 6. W5 — Subtractive cleanup (버릴 것·생략할 것) — complexity is negative alpha

### 6.1 Unify price IO (bug factory: the sha1 miss came from here)
- New module `r1000_price_io.py`: single `px_cache_name(ticker)` +
  `load_price_series(cache_dir, ticker)` (sha1-first, plain-name fallback).
- Replace the 4 duplicate definitions (run_weekly_evaluation, long_crisis_dataset,
  shakeout_disclosure, crisis_signal_builder) with imports. Behavior-identical;
  lock with a smoke test asserting all callers resolve the same file for "SPY".

### 6.2 Delete rejected-phase surfaces (keep git history as the archive)
- Phase 11 multibagger: remove config fields + pipeline branches + workflow inputs
  (REJECTED -1.73pp + bug). research/ CSVs stay.
- Phase 3 renorm + Phase 5 leader/laggard: remove dual-gate code paths and the
  zero-fill placeholder columns they inject.
- Acceptance: ENGINE_REUSE_VERSION bump + one full run reproducing broker baseline
  within noise (±0.3pp) proves the deletions were truly dormant.

### 6.3 Sidecar diet (67 → ~25)
- Classify every sidecar in run_full_rebuild_sidecars.py research_full path:
  KEEP (feeds verdict/operating/leader/crisis/audits), MERGE (overlapping replay
  variants: main_v2 / concentrated_policy / position_aware_risk / monster_lifecycle /
  alpha_sprint → one parametrized replay), DROP (outputs nobody reads — verify via
  cloud_results/Drive access patterns).
- Deliverable: `docs/SIDECAR_AUDIT.md` table + the trimmed script. Official profile
  untouched until one clean run validates.

### 6.4 run_local.py baseline dicts: keep CURRENT + BROKER_BASELINE; move the other
three historical dicts to `research/baseline_archive.py`.

### 6.5 The 27k-line monolith split (REFACTOR_PLAN.md exists)
- Defer until W0-W2 land (measurement first). Then execute the existing 5-module
  plan with the no-behavior-change gate: byte-identical scored_latest.csv on a
  fixed seed before/after.

---

## 7. W6 — Future robustness (미래에도 좋은 성과)

1. **Parameter stability as a gate**: challenger already computes
   `parameter_stability.csv` (top-3 median). Promote to a SHIP gate: champion
   variant's metric must be within 15% of the top-3 median (no lone-spike configs).
2. **Rolling re-verdict**: monthly scheduled workflow re-runs `--verdict-only`
   against the locked broker baseline + OOS lock; REGRESS for 2 consecutive months
   → auto-open a review issue. (No auto-trading, no auto-rollback.)
3. **Decay monitoring**: extend weekly_evaluation with 12m-rolling IC of the top-5
   signal families; IC halving vs backtest → flag the family for review.
4. **Data redundancy**: yfinance is a single point of failure → keep Alpaca keys
   warm as fallback in collector (config exists; add failover path + audit line).
5. **Honesty rails** (already in place, keep): promotion_allowed=False hardcoded in
   research tools; coverage gate; STALE_PRICE_REVIEW; PIT leakage audit in CI.

---

## 8. Sequencing & effort

| Order | Work | Size | Verify via |
|---|---|---|---|
| 1 | W0.1-0.3 gate redefinition + OOS lock | S (1 session) | verdict-only on existing outputs |
| 2 | W3.1 re-dispatch fast verify loop (no code) | dispatch | delta_report.md |
| 3 | W1.1 gap attribution tool | M | fixture smoke + real artifact |
| 4 | W1.2 cash-handling fix | S-M | attribution re-run; broker MDD |
| 5 | W2.2-2.3 macro-history validation + liquidity | M | per-episode matrix |
| 6 | W3 leader lifecycle audit | M | synthetic smoke + official run |
| 7 | W5.1-5.4 subtractive pass | M | baseline reproduction run |
| 8 | W4 data-moat live passes + branch merge | dispatch-heavy | coverage gate |
| 9 | W1.3 fee bands, W6 robustness rails | S each | fast loop |
| 10 | W5.5 module split | L | byte-identical gate |

**Dev-loop rule**: sidecar-stage changes → `sidecar_only_verify.yml` (15-30min).
Signal/model/feature-store changes → Full Rebuild (4h). Never burn a 4h run to test
sidecar code.

## 9. Hard rules for Codex
- Broker-ledger next-close is the only SHIP evidence. Target-weight is informational.
- No production default mutation without a SHIP verdict under the NEW gates.
- Every new tool: research-only header, `promotion_allowed=False`, fail-soft CLI,
  smoke test registered in `tools/run_pr_validation.py`, artifact + cloud_results
  allowlist entries.
- PIT: signal at T close → fill at T+1 close; `available_from` = public timestamp;
  no future labels as live features; VIX-only cash raise forbidden.
- One knob per experiment through the fast loop; grids only with top-3-median gates.
