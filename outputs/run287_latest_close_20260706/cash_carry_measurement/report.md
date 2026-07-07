# Cash Carry Measurement

- Status: `completed`
- Rate source: `DGS3MO`
- Rate rows: 11208
- Price cache aligned: `True` (2026-07-06 vs required 2026-07-02)
- Rate cache aligned: `True` (2026-07-03)
- End date matches official: `True` (2026-07-06)
- Research only: `True`
- Production promotion allowed: `False`
- Production blocker: `research_only_cash_carry_measurement`

| Portfolio | Arm | Metric mode | CAGR | MDD | Sharpe | Equity end | Production allowed |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| main | baseline | broker_ledger_next_close | 0.33381163624338384 | -0.25652197608665717 | 1.250366472797416 | 2026-07-06 | False |
| main | cash_carry | broker_ledger_next_close_cash_carry | 0.34248490427249423 | -0.25361886246588794 | 1.2756315263222913 | 2026-07-06 | False |
| concentrated | baseline | broker_ledger_next_close | 0.4725678116430192 | -0.23221640827349677 | 1.4621225632708028 | 2026-07-06 | False |
| concentrated | cash_carry | broker_ledger_next_close_cash_carry | 0.4866155651099202 | -0.22955201825505345 | 1.4948238570140746 | 2026-07-06 | False |

| Portfolio | CAGR delta pp | MDD delta pp | IS CAGR delta pp | OOS CAGR delta pp | Cash interest | No-op guard |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| main | 0.8673268029110393 | 0.29031136207692265 | 0.6725946626443546 | 1.5138425918528542 | 13682.644425298755 | True |
| concentrated | 1.4047753466901014 | 0.2664390018443319 | 1.0920570341168556 | 2.5722655912367554 | 26580.445411408935 | True |
