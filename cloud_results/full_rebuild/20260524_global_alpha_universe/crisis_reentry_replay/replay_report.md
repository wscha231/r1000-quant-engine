# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 28.45% / -18.05%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 30.32% | 1.926 | -16.08% | 8.74% | 52.79% | false |
| `bargain_reentry` | 29.25% | 1.930 | -15.26% | 11.73% | 51.50% | false |
| `crisis_ladder` | 28.97% | 1.930 | -14.67% | 12.77% | 50.40% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
