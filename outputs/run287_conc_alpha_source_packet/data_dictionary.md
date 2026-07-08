# Run287 Concentrated Alpha Source Packet Data Dictionary

- `miss_set_candidates.csv`: 51 replacement/cap miss-set rows extracted from the enriched Concentrated target book. `period_forward_return` is an audit label only.
- `source_inventory.csv`: compact availability summary for Form4, 13F, true earnings/guidance revision feed, and candidate proxy financial fields.
- `source_screen_signal_stats.csv`: full/IS/OOS quantile separation stats from `run_run287_w4_form4_13f_source_screen.py`.
- `summary.json`: machine-readable packet summary and next-action guardrails.
- `report.md`: human-readable Claude review packet.

Raw Form4/13F parquet files are not committed to GitHub. This packet exposes only compact statistics and candidate rows needed for review.
