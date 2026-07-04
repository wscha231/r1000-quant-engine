# Track C Rotation Latency Counterfactual Closeout — 2026-07-04

## Verdict

`screen_reject_no_rotation_latency_edge`

The 2026-06-29 operating Concentrated book was not proven too sticky. A research-only broker replay compared three fixed-book alternatives:

1. `june_operating_hold`: carry forward the 2026-06-29 operating holdings.
2. `june_raw_rotation`: apply the 2026-06-29 raw target rotation early (`AMD/AMAT/GLW`).
3. `july_actual_rotation_applied_early`: apply the 2026-07-02 actual target mix early (`MU/SNDK/AMD/UMC/WDC/CASH`).

The valid replay window available from the local replay cache is 2026-07-01. A 2026-07-02 replay attempt is blocked by price/cache calendar coverage and must not be interpreted.

## Output

- Tool: `tools/run_rotation_latency_counterfactual.py`
- Output: `outputs/rotation_latency_counterfactual_28616190134_replay_end_20260701/`
- Metrics CSV: `outputs/rotation_latency_counterfactual_28616190134_replay_end_20260701/metrics.csv`
- Report: `outputs/rotation_latency_counterfactual_28616190134_replay_end_20260701/report.md`
- Cash-carry mode: `risk_free_rate`
- Production activation allowed: `false`
- Fullrun executed: `false`

## Results

| Arm | CAGR | MaxDD | Sharpe | ΔCAGR vs Hold | ΔMDD vs Hold | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `june_operating_hold` | 48.50% | -23.79% | 1.430 | 0.00pp | 0.00pp | control |
| `june_raw_rotation` | 47.80% | -23.79% | 1.412 | -0.70pp | 0.00pp | reject |
| `july_actual_rotation_applied_early` | 48.31% | -23.79% | 1.426 | -0.19pp | 0.00pp | reject |

## Interpretation

- The raw June rotation did not beat the operating hold; it reduced full-window CAGR by about 0.70pp.
- Applying the later July target early also did not beat the operating hold; it reduced CAGR by about 0.19pp.
- Therefore, the measured issue is not that the 2026-06-29 operating book was too sticky through this shock window.
- Do not authorize C2 anti-stickiness rules from this evidence.

## Caveat

The originally requested 2026-07-02 crash-inclusive replay is blocked locally because the replay cache used for this counterfactual has an `actual_cached_bars` end date of 2026-07-01, and the artifact cache lacks the SPY/QQQ calendar series required for cash-carry replay. This is a data/cache contract issue, not a policy pass.

Until a 2026-07-02-compatible replay cache is materialized, the 2026-07-01 result is the valid Track C evidence and should be treated as negative evidence against a broad anti-stickiness rule.

## Next

1. Keep the Concentrated event-matched replacement-quality candidate as the only live CAGR policy candidate.
2. Do not add raw-rotation anti-stickiness to the fullrun payload.
3. Move next to Track D only if we want a risk-side test; otherwise continue A1/A2/W1 infrastructure.

