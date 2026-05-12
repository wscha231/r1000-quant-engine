# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 28.91% / -13.56%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 30.68% | 1.925 | -11.50% | 8.05% | 49.97% | false |
| `bargain_reentry` | 29.53% | 1.929 | -10.80% | 10.90% | 48.90% | false |
| `crisis_ladder` | 29.23% | 1.924 | -10.38% | 11.93% | 47.93% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
