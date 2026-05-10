# Regression Attribution: 20260430 vs Latest

Mode: report-only. No production files were changed.

- Left run: `cloud_results/full_rebuild/20260430_global_alpha_universe`
- Right run: `cloud_results/full_rebuild/latest_global_alpha_universe`
- Phase 15-D control: CAGR 24.51%, Sharpe 1.2453, MaxDD -25.79%

## Main Metrics

| Metric | 20260430 | Latest | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 23.35% | 21.40% | -1.94 pp |
| Sharpe | 1.2949 | 1.1831 | -0.1117 |
| MaxDD | -23.74% | -27.27% | -3.53 pp |
| Monthly turnover | 48.73% | 48.59% | -0.14 pp |
| Avg stock names | 25.4024 | 25.5060 | +0.1036 |
| Ending capital | 419437.9343 | 382467.5869 | -36970.3474 |

## Concentrated Metrics

| Metric | 20260430 | Latest | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 37.33% | 34.85% | -2.48 pp |
| Sharpe | 1.4471 | 1.4287 | -0.0184 |
| MaxDD | -23.06% | -22.94% | +0.12 pp |
| Selected names | 5.0000 | 5.0000 | +0.0000 |

## Holdings Diff

- Left positions: 17
- Right positions: 18
- Common positions: 12
- Added: DTM, FIX, LRCX, PWR, TER, WELL
- Removed: BE, CASY, DAL, ETR, VTR

Largest common-name weight changes:

| Ticker | 20260430 weight | Latest weight | Delta | Rank change |
| --- | ---: | ---: | ---: | ---: |
| GEV | 10.52% | 13.39% | +2.87 pp | -1 |
| TSM | 5.90% | 4.14% | -1.76 pp | +1 |
| GOOG | 10.52% | 9.05% | -1.47 pp | +2 |
| AMZN | 7.77% | 6.49% | -1.28 pp | +2 |
| ZTO | 6.44% | 5.18% | -1.26 pp | +1 |
| KIM | 3.84% | 3.28% | -0.56 pp | +4 |
| NVDA | 9.63% | 9.71% | +0.09 pp | -1 |
| FTI | 4.00% | 4.00% | +0.00 pp | +0 |
| MLI | 4.00% | 4.00% | +0.00 pp | +1 |
| MRVL | 7.00% | 7.00% | +0.00 pp | -1 |

## Latest Diagnostics

- Scored rows: 673
- Regime distribution: `{'neutral': 673}`
- Explosion columns present: `['explosion_entry_score', 'explosion_exit_score', 'explosion_net_score']`
- Explosion nonzero: `False`
- ADR indicator rows: 28
- ADR fallback pass count: 11

## Trade Journal And Auto-Learning

- Latest trade insight path: `cloud_results\full_rebuild\latest_global_alpha_universe\trade_journal\insights\summary.md`
- Latest trades analyzed: 695
- Auto-learning approved: `False`
- Auto-learning promoted: `False`
- Block reasons: `['main_cagr_floor', 'main_sharpe_floor', 'main_max_dd_floor']`

## Orchestrator Shadow State

- Regime: `neutral`
- Cash target: 27.56%
- Mandate capacity: `{'main': 0.65, 'concentrated': 0.1, 'tactical': 0.0}`
- Actual invested after merge: 72.44%
- Merge conflict drag: 2.56%

## Initial Attribution Read

- Latest main regressed on CAGR, Sharpe, and MaxDD versus 20260430.
- Turnover stayed near the same high level, so regression was not compensated by lower churn.
- Concentrated remains stronger than main, but its CAGR also declined from the 20260430 control.
- Latest regime and explosion diagnostics show no active non-neutral or explosion signal contribution.
- The highest-priority next experiment is not another production full rebuild; it is isolated Main v2 and orchestrator challenger testing.
