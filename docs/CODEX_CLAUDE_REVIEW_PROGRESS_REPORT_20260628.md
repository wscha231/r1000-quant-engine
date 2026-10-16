# Claude Review Progress Report - 2026-06-28

## Purpose

This report summarizes what Codex has done since the last Claude/GPT Pro review
cycle, why each path was tested, what passed or failed, and what needs another
review before the next implementation step.

This is not a production-promotion report. It is a research progress packet.

## Standing Targets And Guardrails

Canonical mission targets remain unchanged unless the user explicitly approves a
governance rewrite:

| Sleeve | CAGR Target | MDD Target |
|---|---:|---:|
| Main | >= 35% | >= -25% |
| Concentrated | >= 50% | >= -25% |

Hard guardrails:

- Use broker-ledger metrics as the only performance evidence.
- No live trading.
- No production mutation.
- No proxy 8Y/10Y work.
- No answer-sheet/ticker/date hardcoding.
- Forward returns remain audit labels only.
- `pit_universe_label_clean=false` continues to block production promotion even
  if research metrics improve.
- Fullrun is expensive; do not dispatch one unless cheap broker A/B shows a
  concrete reason.

## Current Baseline

Clean 7Y artifact used throughout:

- `artifacts/28074476465/outputs`
- metric mode: `broker_ledger_next_close`
- broker start: `2019-06-03`
- valid research window: about 7.06 years
- production blocker: `pit_universe_label_clean=false`

Core baseline observed across recent broker A/B tools:

| Sleeve | CAGR | MaxDD | Interpretation |
|---|---:|---:|---|
| Main | about 33.9% | about -26.0% | MDD problem remains; CAGR close but still not solved in canonical baseline |
| Concentrated | about 47.2% in latest broker A/B replay baseline | about -25.8% | CAGR gap remains; MDD already too close to the limit |

The exact baseline can differ slightly by artifact end date and replay path
(`2026-06-22` vs `2026-06-25`), but the conclusion is stable: neither sleeve
has a production-ready target pass, and PIT membership is still not clean.

## Why The Work Took This Direction

Claude/GPT Pro pushed three useful corrections:

1. Do not keep adding broad alpha levers. First prove `applied_count > 0`, then
   broker A/B, then fullrun only if justified.
2. Separate apparent right-tail capture from robust skill. OOS-heavy or
   winner-heavy results are not auto-reject, but they trigger skill-vs-luck
   audits.
3. Treat the current problem as two separate tracks:
   - substrate/evidence cleanup: PIT universe membership and signal carry-through;
   - performance improvement: targeted broker-ledger candidates only.

Codex followed that by moving from broad ideas to cheap, narrow,
broker-ledger-verifiable tests.

## Substrate And Measurement Work

### PIT universe evidence

Relevant paths:

- `tools/run_universe_health_audit.py`
- `tests/pit_membership_audit_smoke.py`
- `tests/pit_membership_producer_smoke.py`
- `docs/CODEX_WORKORDER_PIT_CLEAN_UNIVERSE_20260626.md`

Purpose:

- Stop treating current-constituents backfills as production evidence.
- Earn `pit_universe_label_clean=true` only from an auditable PIT membership
  substrate.

Current status:

- Audit/producer scaffolding exists.
- It blocks static/current-constituents proxy paths.
- It still depends on trustworthy historical membership source provenance before
  `clean=true` should be trusted as production-grade.

Open review question:

- Is the current PIT audit strict enough on `available_from`, membership
  end-date handling, delisted/ticker-change coverage, and source provenance, or
  should those become hard blockers before any `pit_universe_label_clean=true`
  is accepted?

### SHAKEOUT signal carry-through and applied-count discipline

Relevant paths:

- `tests/alphaops_vnext_policy_replay_smoke.py`
- `docs/CODEX_WORK_ORDER_CAGR_MDD_LEVERS.md`
- `docs/CODEX_RESEARCH_LEADER_CAPTURE.md`

Purpose:

- Fix the earlier no-op risk where `smart_money_evidence_confidence` existed in
  the market leader engine but was not carried into replay rows used by
  production holding-state logic.

Result:

- Signal carry-through is present in the code/tests.
- SHAKEOUT itself later measured as no-op on the clean 7Y artifact:
  `suppressed_rows=0`.

Conclusion:

- No broker A/B was justified for SHAKEOUT until applied rows exist.
- This is a good process result: no-op levers are stopped before fullrun.

## Concentrated Sleeve Work

### Broad hold-duration / leader persistence

Relevant artifact:

- `artifacts/28074476465/hold_duration_leak_screen/`

Result:

- Broad "hold leaders longer" was negative:
  - Main PIT leader candidates: mean 126d excess about `-2.81pp`.
  - Concentrated PIT leader candidates: mean 126d excess about `-4.02pp`.

Conclusion:

- Broad rescue is rejected.
- Future hold-extension must be narrow and evidence-confirmed.

### Score-sizing path

Relevant paths:

- `tools/run_sizing_signal_screen.py`
- `tools/run_concentrated_sizing_ab_screen.py`
- `tools/concentrated_score_sizing_reweight.py`
- `tools/run_concentrated_score_sizing_broker_ab.py`
- `tests/sizing_signal_screen_smoke.py`
- `tests/concentrated_sizing_ab_screen_smoke.py`
- `tests/concentrated_score_sizing_broker_ab_smoke.py`
- `docs/CODEX_CLAUDE_MIDREPORT_20260627_SIZING.md`

Why tested:

- Claude/GPT Pro agreed that Concentrated CAGR was more likely a sizing/hold
  problem than a "find totally new names" problem.
- Audit-label score-family signals looked promising, especially
  `alphaops_vnext_score`.

Broker A/B artifact:

- `artifacts/28074476465/concentrated_score_sizing_broker_ab/`

Broker A/B result:

| Arm | CAGR | MaxDD | Cap Breach | Verdict |
|---|---:|---:|---:|---|
| baseline | 47.20% | -25.82% | 0 | reference |
| blend75 uncapped | 47.46% | -25.76% | 30 | research-pass-uncapped-only |
| blend75 cap30 | 46.43% | -25.94% | 0 | reject, no CAGR edge |
| blend50 cap30 | 46.94% | -25.34% | 0 | reject, no CAGR edge |

Interpretation:

- Uncapped sizing shows slight edge but breaches the 30% cap and is not a
  policy-safe candidate.
- Cap-safe sizing loses the edge.
- Therefore score-sizing is rejected as a production-quality path for now.

Open review question:

- Should uncapped research be kept only as a diagnostic for "winner
  concentration matters", or is there a controlled cap-relaxation study worth
  doing later after MDD/PIT issues are resolved?

### Earnings/guidance hold screen

Relevant artifact:

- `artifacts/28074476465/earnings_guidance_hold_screen_20260627/summary.json`

Why tested:

- User and Claude both observed that the system often captures leaders but may
  sell or under-hold them through normal volatility.
- Broad hold failed, so the next hypothesis was a narrow PIT-confirmed hold:
  actual-results positive and thesis intact.

Screen result:

| Predicate | Rows | Positive Rate | Mean 126d Excess | Split |
|---|---:|---:|---:|---|
| actual_results_positive_pit_hold | 52 | 53.85% | +10.39% | full |
| actual_results_positive_pit_hold | 41 | 53.66% | +9.83% | IS |
| actual_results_positive_pit_hold | 11 | 54.55% | +12.50% | OOS |

Verdict:

- `screen_pass=true`
- next action: design default-OFF hook candidate

Important limitation:

- This is still a forward-label screen, not a broker A/B pass.
- `actual_results_score` must be verified as truly PIT-available at each
  decision date before it can drive any live-style hook.

Open review question:

- Is this the best next Concentrated hook candidate, or should it wait until
  more robust earnings/revision data is available?

## AI Capex / Late-Cycle Theme Work

Relevant artifacts:

- `artifacts/28074476465/ai_capex_tilt_broker_ab_20260628/main/summary.json`
- `artifacts/28074476465/ai_capex_tilt_broker_ab_20260628/concentrated/summary.json`

Why tested:

- User uploaded research packets supporting a late-cycle AI Capex bottleneck
  framework.
- The correct implementation principle was: do not buy PDF top picks; convert
  the idea into reusable structured signals and cheap screens.

Main broker A/B result:

| Arm | CAGR | MaxDD | Verdict |
|---|---:|---:|---|
| baseline | 33.93% | -26.02% | reference |
| AI bottleneck + momentum tilt | 34.58% | -25.93% | research-pass policy candidate |
| AI bottleneck + momentum + earnings | 33.93% | -26.00% | reject OOS/CAGR |

Concentrated broker A/B result:

| Arm | CAGR | MaxDD | Verdict |
|---|---:|---:|---|
| baseline | 47.20% | -25.82% | reference |
| AI bottleneck + momentum tilt | 46.82% | -25.94% | reject |
| AI bottleneck + momentum + earnings | 46.12% | -25.82% | reject |

Interpretation:

- AI Capex tilt is currently a Main CAGR candidate only.
- It does not solve Main MDD.
- It should not be applied to Concentrated.
- True EPS/revision feed is still missing or empty in the tested artifact, so
  the earnings-confirmed variant is not yet a real FactSet-style signal.

Broader design question from the user:

- If the next rally is not AI, can the system still find leaders?

Current answer:

- The AI Capex work should be generalized into a reusable theme-leadership
  ontology:
  - theme bucket;
  - bottleneck/pricing-power evidence;
  - positive revision/guidance evidence;
  - RS/momentum confirmation;
  - risk telemetry.
- The same screen structure should support biotech, energy, materials,
  crypto-infrastructure, space, power, or any future leading theme, as long as
  the evidence is PIT and not hardcoded to winners.

Open review question:

- Should we refactor AI-specific taxonomy into a generic
  `theme_leadership_registry` before implementing any AI-only policy hook?

## Main Sleeve MDD Work

The latest Claude/GPT Pro feedback pushed us not to keep trying broad cash/stop
rules unless they can prove broker-ledger edge. Codex implemented this as a
sequence of cheap screens and broker A/B tests.

Main evidence document:

- `docs/CODEX_MAIN_MDD_REPAIR_TRIAGE_20260628.md`

### Existing rejected paths before PR #201

Already rejected:

- broad position-risk / stop overlays;
- parabolic risk replay;
- broad cash/crisis floors;
- SPY drawdown-trigger cash overlays.

Why:

- They either failed MDD or fixed MDD by destroying CAGR.

### Crash-fragility screen

Paths:

- `tools/run_main_crash_fragility_screen.py`
- `tests/main_crash_fragility_screen_smoke.py`
- artifact: `artifacts/28074476465/main_crash_fragility_screen_20260628/`

Result:

- high-fragility rows: 67
- high minus low 42d downside gap: about `-0.82pp`
- verdict: `screen_reject_no_material_fragility_edge`

Conclusion:

- Simple volatility/ATR/MA/RS/cluster/market-state fragility is not enough.

### Stress-window attribution

Paths:

- `tools/run_main_stress_window_attribution.py`
- `tests/main_stress_window_attribution_smoke.py`
- artifact: `artifacts/28074476465/main_stress_window_attribution_20260628/`

Stress windows:

- `2020-02-19:2020-03-18`
- `2025-02-18:2025-04-04`

Result:

- The biggest recurring stress attribution was large position size:
  `weight_top20` loss share about `57.10%`.

Conclusion:

- The signal is not broad fragility; it is large position size into stress.
- But large positions also drive compounding, so blunt caps needed broker proof.

### Blunt and conditional Main cap tests

Paths:

- `tools/run_main_stress_condition_cap_broker_ab.py`
- `tests/main_stress_condition_cap_broker_ab_smoke.py`
- artifact:
  `artifacts/28074476465/main_stress_condition_cap_broker_ab_20260628/`

Broker result:

| Arm | Applied Rows | CAGR | MaxDD | Verdict |
|---|---:|---:|---:|---|
| baseline | 0 | 33.93% | -26.02% | reference |
| large_ext_cap10 | 79 | 33.04% | -26.02% | reject |
| large_ext_cap11 | 67 | 33.56% | -26.02% | reject |
| large_ext_weak_cap10 | 32 | 33.83% | -26.02% | reject |
| large_ext_weak_cap11 | 27 | 33.96% | -26.02% | reject |
| large_ext_vol_cap10 | 32 | 33.72% | -26.02% | reject |
| large_ext_fragile_cap10 | 0 | 33.93% | -26.02% | blocked no-op |

Conclusion:

- Conditional monthly caps fired but did not move the Main max drawdown.
- Monthly stock-level cap variants are exhausted.

### Intramonth event-defense / crisis-cash broker A/B

Paths:

- `tools/run_main_event_defense_broker_ab.py`
- `tests/main_event_defense_broker_ab_smoke.py`
- artifact: `artifacts/28074476465/main_event_defense_broker_ab_20260628/`

Why tested:

- The 2020 MaxDD happened fast. Monthly caps cannot react quickly enough.
- The next honest question was whether intramonth/daily crisis defense can move
  the drawdown without destroying CAGR.

Broker result:

| Arm | Events | Exits | CAGR | MaxDD | Verdict |
|---|---:|---:|---:|---:|---|
| baseline_monthly | 0 | 0 | 33.93% | -26.02% | reference |
| crisis_cash_preserve_default | 82 | 0 | 32.93% | -26.99% | reject |
| crisis_cash_preserve_strict | 88 | 0 | 31.47% | -25.49% | reject |
| crisis_cash_preserve_strict_fast_release | 81 | 0 | 31.73% | -25.49% | reject |
| event_default | 449 | 314 | 24.22% | -42.85% | reject |
| crisis_cash_strict | 186 | 98 | 32.17% | -36.33% | reject |
| crisis_cash_strict_fast_release | 179 | 98 | 32.46% | -36.95% | reject |
| event_default_no_cluster_caps | 449 | 314 | 24.33% | -49.55% | reject |

Conclusion:

- Intramonth defense does fire; this is not a no-op.
- The cleanest cash-only arms partially improve MDD to about `-25.49%` but cut
  CAGR by more than 2pp and still miss the `-25%` target.
- Event exits introduce too much whipsaw and are much worse.
- This closes the cheap Main MDD repair paths currently tested.

## Current State After This Work

### What is still alive

1. Main AI Capex momentum tilt:
   - useful Main CAGR candidate;
   - not MDD repair;
   - should not be applied to Concentrated.

2. Concentrated actual-results-confirmed hold:
   - screen pass;
   - not broker A/B evidence yet;
   - needs PIT availability check and default-OFF hook design.

3. PIT universe Track A:
   - still required for any production evidence;
   - audit tooling exists but source/provenance work remains.

4. Generic theme-leadership framework:
   - AI Capex implementation should generalize to future non-AI rallies.

### What is rejected for now

1. Broad hold leaders longer.
2. Broad cash/crisis floors.
3. Broad stop/parabolic overlays.
4. Simple crash-fragility trimming.
5. Blunt Main cap reduction.
6. Conditional monthly Main cap reduction.
7. Intramonth event exits.
8. Concentrated cap-safe score-sizing.
9. Concentrated AI Capex tilt.

## Main Discussion Points For Claude

### 1. Main MDD: keep searching or change mechanism?

Cheap Main MDD paths are now exhausted. The remaining honest options are:

1. research-only explicit hedge overlay;
2. structural redesign of Main selection/risk objective;
3. governance review of whether `Main MDD >= -25%` is realistic for current
   long-only monthly target-book architecture.

Question:

- Should Codex implement a hedge-overlay research harness next, or stop Main MDD
  work and move to governance/structural redesign?

### 2. Hedge overlay design

If hedge research is allowed, it must remain research-only and broker-ledger
measured. Possible approaches:

- allocate to explicit inverse/index hedge ETF proxies if available in price
  cache;
- or build a synthetic overlay outside production broker logic and mark it
  non-production.

Question:

- Is a hedge overlay acceptable under the current "no production mutation"
  discipline, and what instruments/proxies are acceptable for a research-only
  test?

### 3. Main AI Capex tilt

It improves Main CAGR by about `+0.65pp` and slightly improves MDD in broker A/B,
but it still does not reach the canonical Main target alone.

Question:

- Should this be carried forward as a default-OFF Main CAGR candidate while MDD
  remains unresolved, or should it wait until a combined Main solution exists?

### 4. Concentrated next lever

Score-sizing failed when cap-safe. Broad hold failed. Earnings/guidance hold
screen passed but has not yet become broker evidence.

Question:

- Should the next Concentrated implementation be the actual-results-confirmed
  hold-extension hook, with strict PIT availability and applied-count gates?

### 5. Generic theme leadership vs AI-specific policy

The AI Capex research packet produced a useful Main screen but failed for
Concentrated. User also asked whether the system can catch biotech or another
future rally.

Question:

- Should the AI Capex layer be refactored into a generic theme-leadership
  registry before any policy hook is implemented?

### 6. PIT universe acceptance

PIT audit scaffolding exists, but production trust still depends on the quality
of historical membership sources.

Question:

- What exact evidence is sufficient to accept `pit_universe_label_clean=true`?
  Should source-provenance/manual-review become a separate hard gate?

## Proposed Next Codex Sequence

Recommended next sequence unless Claude objects:

1. Stop adding Main cash/cap/stop variants.
2. Ask for explicit decision: hedge research vs Main target governance.
3. In parallel, design a generic theme-leadership abstraction so AI is not
   hardcoded as the only future-rally path.
4. For Concentrated, implement only one narrow default-OFF candidate next:
   actual-results-confirmed hold-extension, after verifying PIT availability.
5. Continue PIT universe source/provenance work as production critical path.
6. No fullrun until one of the above has a broker-ledger candidate that is close
   enough to mission targets.

## Review Request

Please review the following:

1. Is the conclusion correct that Main long-only monthly target-book MDD repair
   is exhausted without hedge/structural redesign?
2. Is the Main AI Capex tilt worth carrying forward as a CAGR candidate even
   though it does not fix MDD?
3. Is actual-results-confirmed hold-extension the best next Concentrated
   candidate?
4. Should the AI Capex layer be generalized before implementation so future
   non-AI rallies can be captured?
5. What is the minimum acceptable PIT membership evidence standard before any
   production claim?

