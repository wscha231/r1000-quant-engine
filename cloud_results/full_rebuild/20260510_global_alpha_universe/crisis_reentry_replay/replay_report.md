# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 28.47% / -15.42%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 29.52% | 1.873 | -11.06% | 8.60% | 51.27% | false |
| `bargain_reentry` | 28.39% | 1.878 | -10.26% | 11.58% | 50.13% | false |
| `crisis_ladder` | 28.09% | 1.867 | -10.05% | 12.57% | 49.25% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
