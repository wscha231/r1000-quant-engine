# Crisis Ladder + Bargain Reentry Replay

Research-only replay. Production weights are unchanged.

- Status: `completed`
- Source cash: `reported_regime_by_month`
- Production CAGR / MaxDD: 28.12% / -15.92%

| Policy | CAGR | Sharpe | MaxDD | Avg Cash | Turnover | Production Allowed |
|---|---:|---:|---:|---:|---:|---:|
| `fast_reentry` | 29.04% | 1.866 | -12.64% | 8.60% | 51.94% | false |
| `bargain_reentry` | 27.91% | 1.873 | -11.79% | 11.58% | 50.81% | false |
| `crisis_ladder` | 27.65% | 1.866 | -11.59% | 12.57% | 49.92% | false |

## Limits

- Uses exported monthly holdings and macro policy rows, so it is directional until wired into the full production accounting path.
- It tests cash timing only; it does not discover new tickers.
- Policies that reduce cash can raise CAGR while worsening stress-window drawdowns; full-run validation is required.
