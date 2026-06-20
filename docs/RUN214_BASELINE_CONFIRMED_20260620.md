# run #214 — Confirmed master clean-7Y broker-ledger baseline

- run: `27873592126` (Full Rebuild Manual), commit `a3dbd01` (master), success 4h37m
- window: **2019-07-01 → 2026-06-18, 6.965y**, broker-ledger next-close, 25bps/side, integer shares
- output dir: `cloud_results/full_rebuild/latest_global_alpha_universe/` (bot commit `3622d20`)
- This supersedes the run #213 (clean7y branch) provisional numbers as the honest baseline for the 7Y A/B plan.

## Headline (official broker-ledger)

| metric | Main | Conc | target |
|---|---:|---:|---|
| CAGR | **34.73%** | **45.47%** | 35% / 50% |
| MaxDD | **−26.05%** | −24.59% | −25% / −25% |
| Sharpe | 1.267 | 1.412 | — |
| IS CAGR | 20.37% | 18.85% | ≥25% / ≥30% |
| OOS CAGR | 80.68% | 144.5% | — |
| **OOS/IS ratio** | 3.96x | **7.66x** | ≤3.0 |
| avg cash | 26.4% | **41.9%** | — |
| SPY beta | 0.512 | 0.318 | — |
| alpha (daily) | 0.000482 | 0.000969 | — |
| trades | 1657 | 589 | — |
| ending $ (100k start) | $797k | $1.36M | — |

## Acceptance gap
- **Main**: CAGR 34.73% (−0.27pp vs 35% canonical); **MaxDD −26.05% breaches −25% by 1.05pp**.
- **Conc**: CAGR 45.47% (−4.53pp vs 50%); MaxDD −24.59% **passes**.
- Tier-2 gates FAIL: conc `is_cagr_min` (18.85% < 30%), conc `oos_is_cagr_ratio_max` (7.66x > 3.0), main `is_cagr_min`. conc `sharpe_min` 1.412 ≥ 1.4 passes (barely).

## Both diagnosed failure axes confirmed by data

### Family A — fast-crash defense (Main MDD breach)
- Main MaxDD −26.05% = **COVID**: peak `2020-02-19` → trough `2020-03-18` = **28 days**.
- avg cash 26.4% but the multi-level breaker / VIX guard fired too slowly to catch a 28-day crash → −25% target breached.
- → **A1 (DD-breaker faster/stronger) + A2 (VIX floor higher)** target exactly this.

### Family B — bull cash drag + overfit (Conc CAGR shortfall)
- Conc avg cash **41.9%** — structural underinvestment.
- Conc MaxDD is a 21-month grind: peak `2021-11-18` → trough `2023-08-17` (2022 bear).
- IS CAGR only 18.85% with OOS/IS **7.66x** = classic over-reliance on the OOS window / underinvested IS regime.
- → **B1/B2/B3 (relax conc cash-vix threshold, faster reentry, bull-only VIX floor)** + C1 attribution to pick the dominant knob.

## Status of levers
- Family A env-override hook **shipped** (PR #147, commit `70538b9`): `R1000_<FIELD>` for all 23 fast-crash fields. A1/A2 can launch via `experiment_env_json` with **no code change**.
- Baseline numbers above are the comparison point for every A/B delta.

## Next-step launch spec (Family A, MDD-repair priority)
```
# A1 — multi-level DD breaker faster + stronger
experiment_env_json={"R1000_DRAWDOWN_BREAKER_LEVEL_1_THRESHOLD":"0.08",
                     "R1000_DRAWDOWN_BREAKER_LEVEL_1_CASH_FLOOR":"0.25"}
# A2 — VIX-level guard floor higher
experiment_env_json={"R1000_VIX_LEVEL_TIER1_CASH_FLOOR":"0.20",
                     "R1000_VIX_LEVEL_TIER2_CASH_FLOOR":"0.40"}
```
Dispatch: `full_rebuild_manual.yml` (skip_collector=true to reuse #214 caches → faster). Gate: Main MaxDD ≥ −25% AND ΔCAGR ≥ −1.0pp AND 2022-DD not worse (crisis-cash regression guard).
