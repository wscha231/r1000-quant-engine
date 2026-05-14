# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 737
- latest scored date: 2026-05-14
- historical candidate rows: 46824
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
- `historical_candidate_book.roe_proxy` numeric=44.9%, nonzero=44.9%
- `historical_candidate_book.gross_profit_ttm` numeric=45.0%, nonzero=45.0%
- `historical_candidate_book.capex_ttm` numeric=47.1%, nonzero=47.0%
- `historical_candidate_book.ocf_ttm` numeric=56.5%, nonzero=56.5%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.7%, nonzero=57.7%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.927642959223958
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.385403809924164
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=53; sleeve=`core_compounder`; score=2.035206217703028
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.43853482180394
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.130007873526755
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=3.752923892146856
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`future_winner`; score=5.356085039925654
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=25; sleeve=`unassigned`; score=5.3464150025064585
- `DELL`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=6.836251287699587
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=5.708827839439032
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.7081076288634165
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`early_scout`; score=4.428079527631525
- `INTC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.002779330803119
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=5.147389099504571
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=6.235641762799949
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.590437669941604
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`future_winner`; score=7.016609111015272
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.070394243994032
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=77; sleeve=`core_compounder`; score=4.100296368361815
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=5.053546930221318
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=5.695001034644551
- `SMCI`: selection_gate_or_rank_rejected; latest=True; hist_months=22; sleeve=`unassigned`; score=-1.4822407664795572
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=2; sleeve=`unassigned`; score=3.8773343270107152
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=6.1293804662318525
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=3.694698119848381
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`core_compounder`; score=7.423873923978675
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=66; sleeve=`future_winner`; score=6.939597055072879
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=23; sleeve=`core_compounder`; score=4.620761959576609

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
