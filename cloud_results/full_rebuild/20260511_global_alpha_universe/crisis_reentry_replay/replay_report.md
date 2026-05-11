# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 27.32% / -17.87%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 29.40% | 1.857 | -14.04% | 7.93% | 50.19% | false |
| `bargain_reentry` | 28.30% | 1.857 | -13.54% | 10.70% | 48.96% | false |
| `crisis_ladder` | 27.95% | 1.848 | -13.45% | 11.64% | 48.06% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
