# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 28.12% / -15.92%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 29.87% | 1.922 | -10.76% | 8.47% | 51.12% | false |
| `bargain_reentry` | 28.62% | 1.921 | -10.45% | 11.35% | 50.09% | false |
| `crisis_ladder` | 28.25% | 1.905 | -10.49% | 12.31% | 49.42% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
