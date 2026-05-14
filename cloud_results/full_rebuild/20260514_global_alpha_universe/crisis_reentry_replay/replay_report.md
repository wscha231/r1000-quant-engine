# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 29.79% / -16.65%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 31.31% | 1.887 | -14.15% | 8.40% | 53.24% | false |
| `bargain_reentry` | 30.17% | 1.890 | -13.29% | 11.35% | 52.09% | false |
| `crisis_ladder` | 29.85% | 1.888 | -12.80% | 12.41% | 51.10% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
