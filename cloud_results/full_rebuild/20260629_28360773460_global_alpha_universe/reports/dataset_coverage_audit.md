# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 742
- latest scored date: 2026-06-29
- historical candidate rows: 46772
- historical candidate tickers: 969
- historical months: 84
- historical candidate last date: 2026-04-30
- SEC-enriched candidate present: True
- SEC-enriched candidate rows: 46772

## Universe Source

- `current_constituents_proxy_static_seed`: 43970
- `adr_whitelist`: 1370
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1184
- `cycle_play_whitelist`: 248

## Evidence Utilization

- rows with SEC evidence: 5619
- rows with 13F evidence: 36401
- rows with ETF evidence: 0
- rows with smart-money evidence: 34258
- coverage ratio: 12.0%
- 13F coverage ratio: 77.8%

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.2%, nonzero=5.2%
- `historical_candidate_book.ocf_growth_yoy` numeric=5.9%, nonzero=5.9%
- `historical_candidate_book.roe_proxy` numeric=44.8%, nonzero=44.8%
- `historical_candidate_book.gross_profit_ttm` numeric=44.9%, nonzero=44.9%
- `historical_candidate_book.capex_ttm` numeric=46.9%, nonzero=46.8%
- `historical_candidate_book.ocf_ttm` numeric=56.4%, nonzero=56.4%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.6%, nonzero=57.6%

## Missing Audit Columns

- `historical_candidate_book.available_from`
- `historical_candidate_book.early_evidence_score`
- `historical_candidate_book.etf_holdings_score`
- `historical_candidate_book.etf_theme_leadership_score`
- `historical_candidate_book.evidence_fusion_score`
- `historical_candidate_book.institutional_evidence_score`
- `historical_candidate_book.latest_13f_available_from`
- `historical_candidate_book.latest_available_from`
- `historical_candidate_book.latest_etf_available_from`
- `historical_candidate_book.leader_onset_sec_v3_score`
- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `historical_candidate_book.sec_13f_score`
- `historical_candidate_book.sec_13f_smart_money_score`
- `historical_candidate_book.sec_combined_evidence_score`
- `historical_candidate_book.sec_form4_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=8.085989574903277
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=72; sleeve=`core_compounder`; score=6.704435265802394
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=54; sleeve=`core_compounder`; score=1.275349635833804
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.240725649880842
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.902817984118257
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=1.7971205436148954
- `CIEN`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=2.6650303696357684
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=22; sleeve=`unassigned`; score=4.635803457285423
- `DELL`: selection_gate_or_rank_rejected; latest=True; hist_months=7; sleeve=`unassigned`; score=5.717348446463392
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`core_compounder`; score=4.220733179995931
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=6.608349947945337
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=4.924820032594755
- `HPE`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=7.301394883008911
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=63; sleeve=``; score=None
- `KLAC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=81; sleeve=`early_scout`; score=6.795735164107887
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=4.699049807253192
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=7.719819453718485
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`future_winner`; score=5.61914033210043
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.149313298905694
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=66; sleeve=`core_compounder`; score=4.61493014491802
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selection_gate_or_rank_rejected; latest=True; hist_months=28; sleeve=`unassigned`; score=1.2356772414160209
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=2.3724486806823224
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=3; sleeve=`core_compounder`; score=4.563619656138558
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.815020872214255
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.424692670484618
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`core_compounder`; score=5.333346897005143
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=39; sleeve=`future_winner`; score=7.0486545111348855
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=24; sleeve=`core_compounder`; score=2.904779219764975

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
