# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 30.91% / -16.38%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 32.69% | 1.911 | -12.35% | 8.60% | 52.31% | false |
| `bargain_reentry` | 31.35% | 1.918 | -11.56% | 11.58% | 51.21% | false |
| `crisis_ladder` | 31.00% | 1.909 | -11.35% | 12.57% | 50.28% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
