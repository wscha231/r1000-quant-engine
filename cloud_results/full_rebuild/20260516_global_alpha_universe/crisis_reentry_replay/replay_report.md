# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 20.29% / -15.28%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 21.99% | 1.700 | -13.02% | 8.50% | 51.94% | false |
| `bargain_reentry` | 21.13% | 1.700 | -12.20% | 11.46% | 50.73% | false |
| `crisis_ladder` | 20.98% | 1.706 | -11.76% | 12.61% | 49.59% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
