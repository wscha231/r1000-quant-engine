# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 29.66% / -15.66%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 31.35% | 1.973 | -12.62% | 8.40% | 52.45% | false |
| `bargain_reentry` | 30.13% | 1.977 | -11.87% | 11.35% | 51.24% | false |
| `crisis_ladder` | 29.86% | 1.972 | -11.37% | 12.41% | 50.23% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
