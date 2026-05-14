# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 30.87% / -18.51%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 32.63% | 1.917 | -14.88% | 8.88% | 53.53% | false |
| `bargain_reentry` | 31.47% | 1.921 | -14.04% | 11.88% | 52.20% | false |
| `crisis_ladder` | 31.19% | 1.919 | -13.55% | 12.89% | 51.17% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
