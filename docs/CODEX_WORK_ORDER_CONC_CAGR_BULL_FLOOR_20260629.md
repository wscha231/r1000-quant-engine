# Codex Work Order — close the Concentrated CAGR gap (bull-floor A/B)

> Author: Claude Code (web), 2026-06-29. Handoff: Codex (local, has price cache + scored artifacts).
> Companions: `docs/CODEX_MEASUREMENT_PROTOCOL.md` (the acceptance gate), `CLAUDE.md` (ship gate).
> Evidence base: full-rebuild run **28360773460** (PR #212 integration), branch
> `codex/integration-main-conc-target-hooks-20260629`, committed under
> `cloud_results/full_rebuild/20260629_28360773460_global_alpha_universe/`.

## 0. Goal (one gap)

- **Concentrated CAGR 46.66% → ≥ 50.00% (+3.34pp)** on `broker_ledger_next_close`, valid window.
- **Main is already SHIP (35.28% / −24.25%)** — do NOT regress it.
- Concentrated MaxDD is −24.12% (only **0.88pp** of headroom to −25%): any CAGR lever must not push MaxDD past −25%.

## 1. Where the CAGR is leaking (run 28360773460 evidence)

1. **Cash drag is the dominant leak.** Concentrated `avg_cash_weight = 40.5%`. `stock_selection_quality/summary.json`
   `rejection_reason_counts` → **`cash`: 1,493** selections rejected for lack of capital (vs candidate_gate 1,654,
   cap_or_replacement 656). A 50%-CAGR-target sleeve idling 40% in cash bleeds compounding in risk-on regimes.
2. **Winners are right-tail and bull/neutral-entered.** `trade_attribution/concentrated/findings.json`
   `top_10_winners`: LITE ×4 (~$286k), WDC ×2, CIEN ×2, SMCI, MU — most entered in `bull`/`neutral` regimes and
   held 28–181d to `target_rebalance`. avg_winner $5,336 vs avg_loser −$1,605, profit_factor ~4.0, win_rate 57.5%.
   `loss_by_regime`: bull −$103k / neutral −$157k, but the bull winners dwarf bull losses → **being 40% cash during
   confirmed bull is pure drag.**
3. Secondary (MaxDD-side, not CAGR): `target_exit` losers −$234k over 141 trades ("exits firing too late", F3);
   IT loss cluster DDOG/NVDA/NET/ACLS drove the MDD window (F8).

## 2. Primary lever — regime-capacity **bull-floor** (already built, default OFF)

`tools/run_alphaops_vnext_policy_replay.py::apply_regime_capacity_overlay` (called for every variant at the replay
stage, both sleeves, ~L3003). Two-way door: the existing overlay only dampened in bear; the bull-floor lifts a
**thinned book up to a gross floor via capped water-filling, only in confirmed bull regimes**, respecting per-name
caps (`effective_single_weight_cap` / `DEFAULT_BULL_FLOOR_SINGLE_CAP`).

- Knob: `DEFAULT_REGIME_CAPACITY_BULL_FLOOR = {"main": 0.90, "concentrated": 0.85}`.
- Gate: env `PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1` (alias `BULL_FLOOR=1`), default OFF.
- Fires only when `regime_state ∈ {bull, strong_bull, exceptional_bull}` AND current stock weight < floor.
- **Replay-stage lever** → A/B is a cheap broker-ledger replay on the SAME scored artifacts. **No full rebuild
  needed** (no feature_store change).

This directly targets leak #1: in confirmed bull it deploys idle cash into the already-selected leaders (the LITE/
WDC/CIEN class), without touching the cash defense in bear/neutral that holds MaxDD at −24%.

## 3. A/B protocol (strict — per `CODEX_MEASUREMENT_PROTOCOL.md`)

1. **Same scored artifacts, one flag.** Baseline = bull-floor OFF; treatment = `PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1`.
   Everything else identical. Re-run the policy replay + broker-ledger only (cheap).
2. **No-op proof FIRST.** In `regime_capacity_overlay` summary, require `rebalance_dates_bull_floor_lifted > 0` and a
   measurable drop in concentrated `avg_cash_weight`. If 0 lifts → wiring no-op (check `regime_state` is populated on
   the concentrated book), not "no effect".
3. **Delta on the canonical metric** from `broker_replay/concentrated/metrics.json`: ΔCAGR, ΔMaxDD, ΔSharpe.
   Report Main too (must not regress).
4. **Floor sweep, gate-first.** If default 0.85 helps but falls short, sweep concentrated floor ∈ {0.85, 0.90, 0.95}
   (lever-sweep harness). Filter to `max_dd ≥ −0.25 AND cagr ≥ 0.50` FIRST, then rank within the passing set. Never
   crown a MaxDD violator.

## 4. Ship gate (this lever)

- `rebalance_dates_bull_floor_lifted > 0`, AND
- Concentrated **ΔCAGR ≥ +0.5pp toward 50%** AND final **MaxDD ≥ −25%** (ΔMaxDD ≥ −3pp), AND
- ΔSharpe ≥ −0.05, AND Main metrics non-regress, AND
- `stock_selection_quality/theme_leader_capture.csv` non-regress, AND `early_scout` count ≥ 4, AND
- **OOS/era robustness (mandatory — this lever leans into deployment):** the gain must appear in the OOS fold and
  hold across **≥ 2 bull eras** (2019–21, 2023–24, 2025+), not only the 2025 OOS right tail. Report
  `rebalance_dates_bull_floor_lifted` and contribution by era. **Reject if the CAGR gain is confined to a single era
  or a single name (LITE).** OOS/IS CAGR ratio must not worsen vs the 46.66% baseline's 4.92x.

## 5. Guardrails

- PIT-only (regime_state is a PIT signal); no hardcoded tickers/dates/sectors; lever stays env-gated default OFF
  until an A/B SHIP verdict.
- **Acceptance is broker-ledger only.** Cheap replay was **optimistic by ~3.4pp on Concentrated** for run 28360773460
  (cheap ~50.07% → full rebuild 46.66%). A cheap-replay bull-floor win MUST be reproduced on a full rebuild before
  any promotion claim.
- Production promotion remains separately blocked by `pit_universe_label_clean = false` regardless of CAGR.

## 6. If bull-floor is insufficient (secondary, lower priority)

Exit-timing on `target_exit` losers (F3: −$234k, firing late) is a MaxDD/loss-reduction lever, not a CAGR adder —
pursue only after the bull-floor A/B, and measure as a MaxDD-target lever (ΔMaxDD improves, ΔCAGR ≥ −0.5pp).

## TL;DR

Enable `PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED=1` (concentrated floor 0.85), prove `bull_floor_lifted > 0` +
cash drops, measure ΔCAGR/ΔMaxDD on the broker ledger, sweep the floor gate-first if short, and confirm the gain is
multi-era OOS (not just LITE/2025) before calling it real.
