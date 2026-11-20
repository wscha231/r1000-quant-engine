# PR #201 Body Update Draft - 2026-06-29

## Summary

This PR is not an alpha-promotion PR.

It is a research-only negative-evidence PR documenting that the cheap Main MDD
repair path is exhausted under the current long-only monthly target-book
architecture.

Implemented scope:

- `tools/run_main_crash_fragility_screen.py`
- `tools/run_main_stress_window_attribution.py`
- `tools/run_main_stress_condition_cap_broker_ab.py`
- `tools/run_main_event_defense_broker_ab.py`
- smoke tests for each tool
- `docs/CODEX_MAIN_MDD_REPAIR_TRIAGE_20260628.md`
- Claude/GPT Pro governance notes

No production policy is enabled.
No live trading is enabled.
No fullrun is justified from this PR.

## Baseline

Clean 7Y artifact:

- `artifacts/28074476465/outputs`
- metric mode: `broker_ledger_next_close`
- Main baseline replay used in these A/B tools:
  - CAGR: `33.93%`
  - MaxDD: `-26.02%`
  - Sharpe: `1.239`

Production promotion remains blocked by `pit_universe_label_clean=false`.

## Main Findings

The following Main MDD repair paths were tested and rejected on broker-ledger or
cheap screen evidence:

1. broad stop / position-risk overlays;
2. broad cash / crisis floors;
3. simple SPY drawdown-trigger cash overlays;
4. simple crash-fragility trimming;
5. blunt Main single-name cap reduction;
6. stress-condition monthly caps;
7. intramonth event-defense and daily crisis-cash target books.

The conclusion is not "tune the parameter harder."

The conclusion is that Main MDD repair through small long-only cash/cap/stop
variants is not mission-quality.

## Event-Defense Broker A/B Results

Artifact:

`artifacts/28074476465/main_event_defense_broker_ab_20260628`

| Arm | Events | Exits | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `baseline_monthly` | 0 | 0 | 33.93% | -26.02% | 1.239 | reference |
| `crisis_cash_preserve_default` | 82 | 0 | 32.93% | -26.99% | 1.219 | reject, MDD worse and CAGR damage |
| `crisis_cash_preserve_strict` | 88 | 0 | 31.47% | -25.49% | 1.197 | reject, partial MDD improvement but CAGR damage |
| `crisis_cash_preserve_strict_fast_release` | 81 | 0 | 31.73% | -25.49% | 1.203 | reject, partial MDD improvement but CAGR damage |
| `event_default` | 449 | 314 | 24.22% | -42.85% | 1.022 | reject |
| `crisis_cash_strict` | 186 | 98 | 32.17% | -36.33% | 1.118 | reject |
| `crisis_cash_strict_fast_release` | 179 | 98 | 32.46% | -36.95% | 1.123 | reject |
| `event_default_no_cluster_caps` | 449 | 314 | 24.33% | -49.55% | 0.961 | reject |

Interpretation:

- Intramonth cash overlays do fire, so this is not a no-op.
- The strict cash-only arms improve MaxDD only to `-25.49%`, still missing the
  old `-25%` target, and damage CAGR by more than 2pp.
- Position-exit event books overtrade heavily and produce severe whipsaw.
- Therefore event-defense is not a mission-quality Main MDD solution.

## Stress-Condition Cap Results

Artifact:

`artifacts/28074476465/main_stress_condition_cap_broker_ab_20260628`

| Arm | Applied Rows | CAGR | MaxDD | Sharpe | Verdict |
|---|---:|---:|---:|---:|---|
| `baseline` | 0 | 33.93% | -26.02% | 1.239 | reference |
| `large_ext_cap10` | 79 | 33.04% | -26.02% | 1.225 | reject, CAGR damage |
| `large_ext_cap11` | 67 | 33.56% | -26.02% | 1.234 | reject, no MDD edge |
| `large_ext_weak_cap10` | 32 | 33.83% | -26.02% | 1.239 | reject, no MDD edge |
| `large_ext_weak_cap11` | 27 | 33.96% | -26.02% | 1.241 | reject, no MDD edge |
| `large_ext_vol_cap10` | 32 | 33.72% | -26.02% | 1.241 | reject, no MDD edge |
| `large_ext_fragile_cap10` | 0 | 33.93% | -26.02% | 1.239 | blocked, no applied rows |

Interpretation:

- The predicates fired, so these are not no-op arms.
- MaxDD remained unchanged.
- Monthly stock-level conditional caps are not a useful Main MDD repair path.

## Governance Note

GPT Pro and Claude agree on the negative evidence:

- do not keep tuning small cash/stop/cap parameters;
- PR #201 has merge value as a negative-evidence research ledger;
- no fullrun is justified from this PR.

They differ on next step:

- GPT Pro suggests a research-only hedge overlay before relaxing MDD governance.
- Claude, aligned with the user's latest no-hedge/long-only direction, suggests
  converting MDD into a realistic risk cap and focusing on CAGR.

Current user direction:

- CAGR priority;
- long-only;
- hedge disabled unless explicitly reopened;
- MDD bar realism / governance review.

Therefore this PR does **not** implement a hedge overlay.

## Next Step After Merge

Do not create more Main cash/stop/cap/event-defense variants.

Recommended next work:

1. Formalize a production/governance acceptance contract:
   - long-only;
   - MDD as risk cap, not main optimization target;
   - relative/risk-adjusted gates;
   - `pit_universe_label_clean=false` remains production blocker.

2. Continue CAGR work:
   - Main: AI Capex / generic theme momentum tilt from PR #199 as CAGR candidate.
   - Concentrated: narrow winner-retention / actual-results-confirmed hold
     candidate, after PIT availability and applied-count checks.

3. Keep hedge overlay as explicit opt-in backlog only:
   - only if the user reopens hedge research or insists on old hard
     `Main MDD >= -25%`;
   - first step would be hedge price-history preflight because the current
     artifact does not list common inverse ETF tickers in the price-cache
     manifest.

## Validation

Validated during this PR:

```powershell
python tools/run_pr_validation.py --only main_crash_fragility_screen --only main_stress_window_attribution --only main_stress_condition_cap_broker_ab --only main_event_defense_broker_ab --only event_target_books_smoke --only workflow_artifact_smoke
```

No fullrun was run.
No workflow was dispatched.
No production or live-trading path was changed.

