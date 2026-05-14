# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 30.99% / -17.41%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 32.72% | 1.897 | -14.09% | 8.40% | 53.04% | false |
| `bargain_reentry` | 31.55% | 1.900 | -13.28% | 11.35% | 51.94% | false |
| `crisis_ladder` | 31.25% | 1.900 | -12.79% | 12.41% | 50.91% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
