# Leader Drop Diagnostics

Research-only diagnostic. It does not change target weights.

- status: `completed`
- rows: 863
- missed leader candidates: 100

## Gate Counts

- `candidate_gate_rejected`: 484
- `rank_or_cap_not_selected`: 238
- `filtered_before_scoring`: 116
- `selected_target_no_order_needed_or_no_preview_delta`: 24
- `not_in_latest_universe_or_missing_data`: 1

## Drop Reasons

- `candidate_gate_rejected`: 484
- `rank_or_cap_not_selected`: 238
- `filtered_before_scoring:failed_mktcap`: 52
- `selected_target_no_order_needed_or_no_preview_delta`: 24
- `filtered_before_scoring:failed_dd_1y`: 22
- `filtered_before_scoring:failed_mktcap+failed_dd_1y`: 21
- `filtered_before_scoring:price_blacklisted`: 7
- `filtered_before_scoring:failed_dollar_vol+failed_mktcap+failed_dd_1y`: 4
- `filtered_before_scoring:failed_min_price+failed_mktcap`: 4
- `filtered_before_scoring:failed_min_price+failed_dd_1y`: 2
- `filtered_before_scoring:failed_min_price+failed_mktcap+failed_dd_1y`: 2
- `filtered_before_scoring:failed_dollar_vol+failed_mktcap`: 1
- `filtered_before_scoring:failed_min_price+failed_dollar_vol+failed_mktcap+failed_dd_1y`: 1
- `not_in_latest_universe_or_missing_data`: 1
