# Codex 13F Fixed-Book A/B Result — 2026-07-08

This records the one-pass pure-13F Concentrated A/B authorized by
`CODEX_DIRECTIVE_13F_FIXEDBOOK_AB_20260708.md`.

## Verdict

`reject_oos2_worse`

The 13F source passed the PIT gate and the source-screen mechanism check, but
the fixed-book broker A/B did not beat the run287 official baseline on the
required OOS2 gate and did not restore the 50% Concentrated CAGR mission.

No fullrun was dispatched. No hook was promoted. No threshold grid was run. No
production state was changed.

## G0 PIT Gate

- `pit_gate_status=clean`
- `available_from_field=available_from`
- `uses_period_end=false`
- median report-period-to-available lag: `45.0` days
- rows with `available_from` after decision date: `0`

The 13F source is decision-time gated by filing availability, not quarter-end
holdings dates.

## G2 Power Guard

- broad OOS `w4_13f_score` high-low: `+1.69%`
- broad OOS high quantile count: `2087`
- miss-set confirmed mean forward return, audit-only: `+3.17%`
- miss-set unconfirmed mean forward return, audit-only: `+2.24%`
- confirmed-minus-unconfirmed, audit-only: `+0.93%`
- sign agreement: `true`

Forward returns remain audit labels only and were not used for ranking.

## G3 Broker A/B

Substrate:

- official run287 fixed Concentrated book
- replay end: `2026-07-02`
- pure signal: `w4_13f_score > 0`
- confirmed swaps: `36`
- unconfirmed replacement-quality rows reverted: `15`

Cash-carry result:

| Arm | CAGR | MaxDD | dCAGR vs official | OOS dCAGR | OOS2 dCAGR |
| --- | ---: | ---: | ---: | ---: | ---: |
| official_baseline | 48.41% | -22.96% | +0.00pp | +0.00pp | +0.00pp |
| rq_hook_off_reconstructed | 45.59% | -23.86% | -2.82pp | -6.03pp | -2.97pp |
| 13f_confirmed_candidate | 48.21% | -22.96% | -0.20pp | +0.65pp | -0.06pp |

Zero-yield result:

| Arm | CAGR | MaxDD | dCAGR vs official | OOS dCAGR | OOS2 dCAGR |
| --- | ---: | ---: | ---: | ---: | ---: |
| official_baseline | 47.00% | -23.22% | +0.00pp | +0.00pp | +0.00pp |
| rq_hook_off_reconstructed | 44.23% | -24.11% | -2.77pp | -5.94pp | -2.92pp |
| 13f_confirmed_candidate | 46.83% | -23.21% | -0.17pp | +0.68pp | -0.04pp |

## Interpretation

13F confirmation is a valid source-screen signal, but it is not a broker-ledger
improvement over the current run287 official fixed book. It helps versus a
reconstructed hook-off book, which confirms that the existing replacement-quality
path was load-bearing, but filtering that path with pure 13F confirmation gives
up too much full-window and OOS2 CAGR.

This closes the pure Form4/13F route as negative evidence for Concentrated unless
a new true PIT earnings/guidance revision feed is supplied. Do not iterate
thresholds on this result.

## Artifacts

- `outputs/run287_13f_pit_gate/summary.json`
- `outputs/run287_13f_pit_gate/report.md`
- `outputs/run287_13f_fixedbook_ab/summary.json`
- `outputs/run287_13f_fixedbook_ab/report.md`
- `outputs/run287_13f_fixedbook_ab/arm_metrics.csv`
- `outputs/run287_13f_fixedbook_ab/swaps.csv`
