# Run287 W4 External Feed Inventory

- Status: `completed`
- Decision label: `sec_w4_sources_available_but_guidance_feed_missing`
- This is read-only inventory. No signal, hook, fullrun, production promotion, or live trading path is enabled.

| Feed | Status | Rows | Tickers | Available From Max | Decision-time usable |
| --- | --- | ---: | ---: | --- | --- |
| sec_form4_transactions | `available` | 220674 | 1599 | 2026-05-19T10:03:54+00:00 | True |
| sec_13f_holdings | `available` | 1798508 | 3351 | 2026-05-18T06:10:10+00:00 | True |
| repo_earnings_revision_signals | `missing` | 0 | 0 |  | False |

## Interpretation

- SEC Form4 and 13F feeds can be local W4 evidence sources when present with PIT `available_from` timestamps.
- They are not true earnings/guidance feeds and do not unblock earnings revision/guidance confirmation.
- A usable inventory only permits source-screen work. It does not permit policy hooks or fullruns.
