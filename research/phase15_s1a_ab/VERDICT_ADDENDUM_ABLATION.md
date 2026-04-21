# Phase 15-S1a Ablation Verdict — 2026-04-22 overnight

Follow-up to `VERDICT.md` (full 3-factor prune A/B `b2zq3xkam`, verdict: main FAIL, concentrated STRONG PASS).

Run `bbl6mkuiq` + follow-up `bhyyse6xs`: five variants on the same QUICK pipeline cache.

## Results matrix (all deltas vs baseline)

| Variant | Env vars | Main CAGR | Main MaxDD | Conc CAGR | Conc Sharpe | Main ship |
|---|---|---|---|---|---|---|
| full_prune (b2zq3xkam) | `FUTURE_PRUNE=1` | -0.46pp | **+4.03pp** | **+3.25pp** | +0.118 | FAIL |
| drop_ft only (A) | `DROP_FT=1` | -0.12pp | **+4.01pp** | +2.97pp | +0.111 | FAIL |
| drop_cf only (B) | `DROP_CF=1` | +0.15pp | -0.08pp | +0.80pp | +0.022 | FLAT |
| **drop_ub only (C)** | `DROP_UB=1` | **+0.36pp** | -0.08pp | +0.77pp | +0.021 | **FLAT (best single)** |
| drop_cf+ub (D) | `DROP_CF=1 DROP_UB=1` | +0.16pp | -0.19pp | +0.80pp | +0.022 | FLAT |

## Key findings

1. **`fundamental_turnaround_acceleration_score` (FT) is the pivotal factor.**
   Dropping FT alone accounts for **91% of the concentrated +3.25pp** and **99% of the main MaxDD +4.03pp** improvement in the full prune. BUT FT drop alone still costs **-0.12pp main CAGR**.
   FT is carrying both the concentrated alpha AND the main-CAGR cost simultaneously.

2. **Sub-additive interaction** on main CAGR:
   - Linear sum of individual drops: -0.12 + 0.15 + 0.36 = **+0.39pp** expected
   - Observed full-prune result: **-0.46pp**
   - Interaction penalty: **-0.85pp**
   - Dropping 3 correlated factors together overcorrects — they appear to jointly encode useful regime signal that the 1m IC audit missed.

3. **CF and UB are effectively redundant** on main (B alone: +0.15pp; D combined B+C: +0.16pp).
   Their noise patterns are correlated; dropping both adds almost nothing vs dropping CF alone.

4. **Best single-factor ship: drop_ub** (main +0.36pp, conc +0.77pp, MaxDD neutral).
   Doesn't clear strict ship gate (+0.50pp CAGR) but provides directional positive lift on BOTH blends with zero main regression risk.

## Ship decision

| Option | Action | Pro | Con |
|---|---|---|---|
| Flip `drop_ub` cfg default to True | ship C | +0.36pp main, +0.77pp conc, MaxDD flat | ΔCAGR < +0.5pp strict gate — no formal ship |
| Flip `drop_cf + drop_ub` cfg default to True | ship D | roughly same as C (interaction nearly flat) | same CAGR concern |
| Keep all defaults OFF (current) | no-op | strict gate adherence, A/B env var still works | Leave +0.36pp on the table |
| Concentrated-exclusive FT drop | code refactor | Cleanly ship +2.97pp conc with no main touch | Requires structural change in r1000_pipeline.py ~11939 |

**Autonomous decision (user offline, strict ship-gate discipline)**: Option 3 — **keep all cfg defaults OFF**. Gate is clean. Env sub-toggles remain available for opt-in A/B.

**Recommended next step**: **Concentrated-exclusive FT drop** (Option 4). Implementation:
- Compute a second `future_score_conc` inside concentrated_score construction (r1000_pipeline.py:11939) using the pruned weights.
- Keep the main composite's `portfolio_future_winner_engine_score` untouched.
- Expected: concentrated +2.97pp (same as A) without main regression.
- Complexity: ~1-2 hours of careful edits, need new smoke test.

Alternative: **Phase 15-S1b horizon realign** (FULL rebuild, 2-3h). IC audit root finding was that factors have 3m alpha, not 1m. Train `pred_future_winner_ret` on `r_3m` and measure. Higher expected impact but longer cycle.

## Files
- `research/phase15_s1a_ab/ablation/A_ft_*.json` (drop_ft only)
- `research/phase15_s1a_ab/ablation/B_cf_*.json` (drop_cf only)
- `research/phase15_s1a_ab/ablation/C_ub_*.json` (drop_ub only)
- `research/phase15_s1a_ab/ablation/D_cfub_*.json` (drop_cf+drop_ub, FT kept)
- `research/phase15_s1a_ab/ablation_summary.py` — run to reproduce the summary table

## Runs
- `bbl6mkuiq` (overnight, ~60min): variants A + B + C sequential
- `bhyyse6xs` (morning, ~20min): variant D
- Engine commit during runs: `2cc2a76` (ablation sub-toggle refactor), `b002f8a` gate state

## Status
Final verdict for the three-factor drop hypothesis recorded. All cfg defaults remain OFF.
No production behavior change. Next alpha work should pivot to either concentrated-exclusive FT drop OR 15-S1b ML target horizon realign.
