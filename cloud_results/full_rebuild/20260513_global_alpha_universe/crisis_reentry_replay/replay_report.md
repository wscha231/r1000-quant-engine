# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 28.31% / -16.24%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 30.24% | 1.877 | -13.64% | 8.40% | 52.14% | false |
| `bargain_reentry` | 29.14% | 1.881 | -12.79% | 11.35% | 50.98% | false |
| `crisis_ladder` | 28.86% | 1.879 | -12.28% | 12.41% | 49.94% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
