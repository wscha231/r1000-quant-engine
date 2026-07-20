# Run287 P3 canonical crisis policy result — 2026-07-20

## Decision

The duplicated crisis, defense, and re-entry logic now has one pure canonical
policy, but the first fixed historical portfolio arm is rejected. The engine
and audit contract remain available for shadow research; it is not permitted
to overwrite the operating champion, production, or live trading.

The rejection is important: the arm improved Main drawdown but sacrificed too
much CAGR, worsened Concentrated drawdown slightly, created cash traps, and had
insufficient holding-level historical evidence to exercise the intended first
four selective-sell reasons. No threshold retuning was performed.

## Canonical behavior

- States: `GREEN`, `WATCH`, `DEFENSE`, `CRISIS`, `REENTRY_STAGE_1/2/3`,
  `DEGRADED_DATA`.
- Re-entry score thresholds remain fixed at `0.40 / 0.60 / 0.75`; the actual
  target gross multipliers are `0.25 / 0.60 / 1.00` of normal policy gross.
- Missing components keep their fixed zero contribution; remaining weights are
  never renormalized.
- Missing or future-dated critical SPY/QQQ, HY OAS, or VIX inputs produce
  `DEGRADED_DATA`.
- SPY drawdown is not reused as universe breadth or leadership.
- Future-label columns are physically removed before state inference.
- WATCH blocks new risk but does not sell an intact winner because of broad
  weakness alone.
- DEFENSE/CRISIS sell order is thesis break, RS/trend break, loss/beta/vol,
  duplicated exposure, low conviction, then emergency proportional reduction.
- Reserve reconciles to six explicit reasons; capacity cash is never relabeled
  crisis cash.

## Current bounded result

The no-network 2026-07-16 current sidecar passed with canonical `GREEN`:

- crisis score `0.0310582380`;
- re-entry score `0.7000000000` and multiplier `1.0`;
- no missing critical component;
- noncritical universe/sector/leadership breadth remains missing in the crisis
  sidecar and is supplied later by the 988-row decision cross-section;
- future labels excluded: 9 columns;
- state extension deterministic across 34 business dates;
- network requests: 0.

The prior P2 packet predates the v2 crisis sidecar and therefore correctly
reports missing QQQ/VIX as `DEGRADED_DATA`. Its operating targets remain
unchanged; a separately named crisis shadow is emitted. This prevents stale
state evidence from changing the champion.

## Fixed-book broker replay

Inputs were the exact generated-book hashes already registered for Run287:

- Main: `356bac22ec55090b2d2da882c7505b1460973227639a5d0b7a4c59c25c0ccff9`;
- Concentrated: `848c1bac00985ab0b132794ee3e1c2942c1561d2f728b0a89778bd6c4e63660e`.

The comparison below is zero-yield on both sides, next-close, integer shares,
25 bps per side, ending 2026-07-10. Cash-asset policy is intentionally deferred
to P4.

| Portfolio | Baseline CAGR / MDD | P3 arm CAGR / MDD | Delta CAGR | Delta MDD | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Main | 33.5352% / -25.6527% | 22.7351% / -21.5507% | -10.8002%p | +4.1020%p | Reject |
| Concentrated | 47.6898% / -23.2216% | 31.4555% / -23.2630% | -16.2343%p | -0.0414%p | Reject |

Stress windows available in the 2019–2026 book:

| Portfolio | 2020 baseline / P3 MDD | 2022 baseline / P3 MDD |
| --- | ---: | ---: |
| Main | -22.4014% / -20.7993% | -13.9996% / -13.4591% |
| Concentrated | -20.8617% / -18.2615% | -10.6983% / -10.5763% |

The 2011, 2015–16, and 2018 windows are unavailable because the canonical book
starts in 2019; they are `UNAVAILABLE`, not zero.

## Episode and implementation diagnostics

| Diagnostic | Main | Concentrated |
| --- | ---: | ---: |
| State snapshots: degraded / defense / crisis | 52 / 13 / 7 | 52 / 8 / 3 |
| Re-entry stage 1 / 2 / 3 | 14 / 28 / 0 | 14 / 28 / 0 |
| False-defense episodes | 11 of 17 | 11 of 11 |
| False re-entry/re-defense | 9 | 9 |
| Green cash-trap snapshots | 4 | 7 |
| Selective sells: low conviction | 606 | 259 |
| Selective sells: thesis / trend / risk / duplicate | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Uniform noncash scaling used | 0 | 0 |
| Trades / fees | 1,713 / $36,058.07 | 720 / $47,996.72 |

The absence of thesis/trend/risk/duplicate firings is not interpreted as proof
that those mechanisms add no value. The historical target books do not contain
the required holding evidence, so the arm fell through to low conviction. This
is a data-contract failure for promotion and must not be hidden by tuning.

Median recovery to 25/50/75/95% of prior normal gross was `2/2/23/110`
business days for Main and `7/20/25/57` for Concentrated. Maximum 95% recovery
was 1,259 and 1,305 business days respectively, confirming a severe cash trap.

## Migration and safety

- `tools/run287_crisis_policy.py` is the canonical pure state/weight contract.
- Replay state construction, the current monitor, the current exact sidecar,
  historical target construction, and same-close shadow construction use it.
- `r1000_crisis_governor.py` remains only as a compatibility facade; its old
  uniform noncash scaling implementation is removed.
- The rejected arm is emitted only as `*_crisis_shadow_target_book.csv`.
- `crisis_policy_applied_to_operating_target=false` is mandatory.
- No threshold grid, fullrun, production activation, or live order was run.

## Next gate

P3 infrastructure can be merged as a fail-closed, shadow-only foundation. The
policy itself remains rejected. P4 may now compare Reserve assets on an
unchanged stock target book; it may not use cash carry to rescue this rejected
P3 arm.

## Verification

- Focused canonical-policy, state-engine, same-close, monitor, workflow, and
  ledger contract tests passed.
- Repository smoke tests passed `129/129`.
- Full Tier-1 PR validation passed `181/181` in `576.74s`.
