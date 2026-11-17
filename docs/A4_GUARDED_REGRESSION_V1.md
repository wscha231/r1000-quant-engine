# Extrapolation-resistant A4 research comparison

The retained private 22-feature experiment lost to the past-training mean.
A read-only replay of its exact panels and unchanged predictions found extreme
input shifts: in the 2020 test fold, payroll three-month annualized growth
reached about178 training standard deviations. For21-session returns, 2020
accounted for approximately83% of SPY and90% of QQQ squared error. Rows with
any active feature beyond5 training standard deviations accounted for about
94% and96% of squared error respectively. This is descriptive association,
not causal attribution. The old predictions and negative results are retained.

`tools/a4_guarded_regression.py` implements one fixed new research challenger:

- Compute means, population standard deviations and constant columns on the
  training fold only. Clip standardized training and test values to[-3,3].
- Use ridge penalty equal to the number of training rows, without a search.
- Return the training target mean if any test feature exceeds5 standard
  deviations or a previously constant feature changes by more than1e-12.
- Otherwise constrain output to the training target minimum and maximum.
  Valid training outcomes therefore preserve their natural ranges.

This is a prospective method definition for a new development comparison,
not clipping an old result and claiming it improved. The module adds no
collector, scheduler, source admission, accepted model or A3/A5 connection.

Expanding folds retain the existing756-session initial split,252-session test
blocks and504-row training minimum. Next-close entry is unchanged. The training
label endpoint must be strictly before the first test session. There are no
future-of-test training rows and no claim of an additional post-test embargo.
Prediction generation does not inspect the availability or values of test
labels. Scoring separately uses mature outcomes on the fixed common cohort.

Before a real comparison, pin the complete caller/dependency/input identities,
obtain the separately scoped private research execution record, perform the
do-not-repeat preflight, and retain every attempt. Compare the single new arm
against both the training mean and unchanged retained22-feature predictions:
2 targets x8 horizons x3 outcomes x2 comparisons =96 new cases. Include the
prior960 cases in the1056-case BY family. Long-horizon evidence gates remain
unchanged;1-session realized volatility remains undefined. Already inspected
2016-era price outcomes are not a virgin holdout. Unknown price rights and
historical clocks remain unknown, regardless of mathematical leakage tests.

Official-source review remains separate from model improvement. Cboe provides
[daily VIX history](https://www.cboe.com/tradable_products/vix/vix_historical_data),
but [website terms](https://www.cboe.com/terms/) are not blanket permission for
cloud storage or machine learning. Chicago Fed
[NFCI histories](https://www.chicagofed.org/research/data/nfci/current-data) can
revise with incoming data and estimated weights; a current history cannot be
backdated as a vintage. OFR's
[stress index](https://www.financialresearch.gov/financial-stress-index/)
publishes two business days behind and documents historical corrections; its
credit contribution is not HY OAS. Nasdaq's free
[annual market files](https://nasdaqtrader.com/Trader.aspx?id=DailyMarketFiles)
list volume and selected index closes, not historical advance/decline counts.
No current-member reconstruction is labelled historical S&P500/NYSE breadth.
Use the existing Source writer and Readers for any separately reviewed addition.

Synthetic validation: `python tests/a4_guarded_regression_smoke.py` verifies
novel-scale/constant fallback, target support, test-batch invariance,
future-input/label and prefix invariance, maturity/cohort exclusion and invalid
inputs. The registered program and both local dependencies belong to the A6
proof inventory. These tests are not financial performance evidence.
