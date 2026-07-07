# CODEX_RUN287_BEST_PATH_SEARCH_20260708

## Verdict

The best next path is not another direct alpha hook. It is a research-only, MDD-neutralized Main growth design plus a near-miss W4 SEC Concentrated lane.

Do not dispatch a fullrun from this package. Do not add a hook. Do not tune the 5%/10% tilt, the top-quintile cutoff, or the end date.

## Current Measurement Contract

- Source run: `28725350727`
- Metric mode: `broker_ledger_next_close_cash_carry`
- Replay end date: `2026-07-02`
- Runner parity status: `parity_documented_gap`
- PIT universe label clean: `false`
- Production promotion allowed: `false`
- Measurement acceptance allowed: `false`

All outputs are research-only. They are valid for diagnosis and human review, not production acceptance.

## Main: Best Path

The direct `growth_confirmation_score` tilt proves that a growth signal exists, but it fails the joint contract because it worsens the structural 2022 drawdown.

| Arm | CAGR | MDD | Delta CAGR pp | Delta MDD pp | Contract pass |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline | 33.81% | -25.36% | +0.00 | +0.00 | false |
| Growth confirmation tilt 10% | 35.79% | -25.93% | +1.98 | -0.56 | false |

MDD attribution window: `2021-11-19` to `2022-09-26`.

Top drawdown-worsening names in the tilt:

| Ticker | Delta price contribution pp | Avg weight delta pp | Target delta sum pp |
| --- | ---: | ---: | ---: |
| AMD | -0.62 | -0.13 | -0.17 |
| BLDR | -0.57 | -0.33 | -1.30 |
| NET | -0.56 | +3.19 | +5.26 |
| CHRW | -0.40 | +1.32 | +4.43 |
| NVDA | -0.38 | +0.61 | -2.12 |
| KMI | -0.34 | +1.66 | +3.49 |
| MA | -0.29 | +0.38 | +2.40 |
| MEDP | -0.24 | -0.21 | -0.42 |
| AVGO | -0.18 | +0.23 | +0.92 |
| FICO | -0.12 | -0.15 | -0.27 |

Interpretation: the direct growth tilt should stay rejected. The next defensible Main experiment is not "more growth tilt"; it is an ex-ante drawdown-neutralized growth design that keeps the CAGR effect while proving it does not increase the 2022 MDD episode or another held-out drawdown episode.

## Concentrated: Best Path

The source-by-source broker A/B shows that W4 SEC is the only useful Concentrated near-miss. It improves full-window CAGR and MDD, but it still fails the 50% CAGR target and worsens OOS CAGR.

| Signal | Arm | CAGR | MDD | Delta CAGR pp | Delta MDD pp | OOS Delta CAGR pp | Contract pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `w4_sec_score` | 10% tilt | 49.56% | -22.26% | +1.16 | +0.70 | -3.06 | false |
| `w4_sec_score` | 5% tilt | 49.37% | -22.60% | +0.97 | +0.35 | -1.21 | false |
| `macro_regime_score` | 5% tilt | 47.76% | -23.13% | -0.64 | -0.17 | negative | false |
| `technical_momentum_score` | 5% tilt | 47.50% | -22.13% | -0.91 | +0.82 | negative | false |
| `risk_control_score` | 5% tilt | 47.37% | -22.27% | -1.03 | +0.68 | negative | false |
| `financial_statement_proxy_score` | 5% tilt | 47.09% | -23.32% | -1.32 | -0.36 | negative | false |

Interpretation: W4 SEC is the best Concentrated lane, but it is not a candidate. It can justify a narrower W4 event-quality audit, not a policy hook.

## Best Path Ranking

1. Main: design one ex-ante MDD-neutralized growth experiment. It must keep the `growth_confirmation_score` CAGR lift and prove no MDD worsening across the 2022 episode plus at least one additional drawdown episode.
2. Concentrated: preserve W4 SEC as a near-miss lane. The next step is event-quality attribution, not threshold retuning.
3. Reject direct standalone tilts for financial proxy, technical momentum, macro regime, and risk control on Concentrated.
4. Keep runner parity and PIT membership caveats visible; nothing here is production evidence.

## Non-Negotiables

- No fullrun.
- No production promotion.
- No live trading.
- No public return claim.
- No post-hoc percentile or endpoint selection.
- No direct edit of losing dates or losing tickers.
- No hook until a new cheap evidence package clears the joint contract.
