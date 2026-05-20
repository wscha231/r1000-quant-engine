# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 29.19% / -17.46%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 30.88% | 1.934 | -13.54% | 8.40% | 51.96% | false |
| `bargain_reentry` | 29.72% | 1.937 | -12.77% | 11.35% | 50.84% | false |
| `crisis_ladder` | 29.46% | 1.934 | -12.34% | 12.41% | 49.86% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
