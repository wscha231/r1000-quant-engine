# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 714
- latest scored date: 2026-05-07
- historical candidate rows: 46658
- historical months: 84
- historical candidate last date: 2026-03-31

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
- `historical_candidate_book.gross_profit_ttm` numeric=44.8%, nonzero=44.8%
- `historical_candidate_book.capex_ttm` numeric=46.9%, nonzero=46.8%
- `historical_candidate_book.ocf_ttm` numeric=56.5%, nonzero=56.5%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.7%, nonzero=57.7%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.969267287980819
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=72; sleeve=`core_compounder`; score=4.582744794744339
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=53; sleeve=`core_compounder`; score=3.757321465811227
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.518030737779704
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.157193156680457
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=4.279378810351513
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`future_winner`; score=4.358697267121587
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=21; sleeve=`unassigned`; score=5.0444841752681695
- `DELL`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=6.477690602028811
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=6.322004011265392
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.922779748037136
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`early_scout`; score=2.619949170037013
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=64; sleeve=``; score=None
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=4.695778016571429
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=5.6433585767762295
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.711274777014702
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`future_winner`; score=5.498113456473762
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=4.237888816627833
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=65; sleeve=`core_compounder`; score=5.054955248822722
- `OKLO`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=6.759325789757984
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=4.121517217655195
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=2; sleeve=`unassigned`; score=2.7491928466919178
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=4.709179149325199
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.8801916218281445
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=48; sleeve=`core_compounder`; score=6.07593554128502
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=38; sleeve=`future_winner`; score=5.271943832965327
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=23; sleeve=`core_compounder`; score=4.358676944820976

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
