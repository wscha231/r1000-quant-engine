# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 27.86% / -16.84%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 29.83% | 1.882 | -12.46% | 9.61% | 51.48% | false |
| `bargain_reentry` | 28.64% | 1.878 | -11.99% | 12.59% | 50.11% | false |
| `crisis_ladder` | 28.26% | 1.865 | -11.89% | 13.53% | 49.12% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
