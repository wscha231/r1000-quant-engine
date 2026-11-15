# Standalone daily multifactor research

`tools/a4_daily_multifactor.py` adds an independent experimental component.
The incumbent sparse release learner, seven released horizons, ten-axis risk
engine, Source Readers, scheduler and A3/A5 interfaces are unchanged. It has no
production release, model acceptance, portfolio weights or order interface.

## Priority and actual evidence

`registry()` is the versioned feature register. It identifies29 distinct macro
inputs,26 technical features and four funding spreads, yielding88 feature
columns. Levels/changes or several features from the same price path are not
independent sources or independent votes. A source's registration is not proof
that its originals, historical clocks or rights have been verified.

P0: price trend and realized volatility;2y/10y/real10y yields; HY/IG credit;
SOFR/TGCR/IORB/EFFR; Fed assets, reserve weekly average, TGA weekly average and
other-account RRP weekly average. P1: broad dollar; all/domestic/large/small
bank deposits, loans, C&I loans, cash; payroll, unemployment, CPI/core CPI,
claims, retail sales, real disposable income and core PCE. Existing Readers and
original captures are reused. VIX-family/native breadth, CCC/ICI/FINRA and
additional proprietary data are not silently substituted or declared present.

## Daily state and historical use

`macro_state` takes bounded observations and the completed NYSE calendar. It
respects each original `available_at`, observation date, unit, native frequency,
source identity, null and freshness limit. Today's revised history cannot
populate yesterday's decision. Same-clock conflicting vintages and mixed
publishers for one logical series refuse replay. Monthly values may remain
known across daily states; that does not create new independent releases.
`change` means four-week fractional change for balances, one-month native-unit
change for monthly observations, and five-observation native-unit change for
daily series. Missing reference periods remain missing. Funding differences
require matching observation dates and use100bp per percentage point.

The caller must obtain original-bound rows through the existing Readers and
retain their exact manifest, execution and policy evidence. This mathematical
component does not authenticate a supplied row merely because it has a hash.
`price_features` is a pure research transform; a Series alone cannot certify
historical price publication, adjustment basis or supplier permission.

## Predeclared combinations and comparison

`specification()` fixes12 arms in five cohorts before inspecting outcomes:

| Cohort | Arms |
| --- | --- |
| Technical |21 trend/relative-strength features;5 risk features; their26-feature combination |
| Dated economy |8 price features;6 economy level/change features; their combination |
| Liquidity/bank |8 price features; prices plus11 balance changes and four funding spreads |
| Rates/credit |8 price features; prices plus10 yield/credit levels and changes |
| Full |8 price features; all technical/economy/liquidity/bank/rates/credit plus dollar |

Within each cohort, the union of required columns determines exactly the same
train/test rows for every arm. A missing group blocks that cohort rather than
letting one arm choose easier dates. Different cohorts can have different
coverage and must not be ranked as if they had identical test populations.
Unavailable and negative arms remain in the declared multiple-testing family.

The research scope is SPY/QQQ and1/5/10/21/63/126/252/504 sessions, each with
return, maximum drawdown and realized volatility. Two targets produce576
declared cases.504 is separate exploratory research; it does not modify the
native request, release protocol or its seven horizons.
Both targets are mandatory for this specification. A missing target refuses
before fitting, rather than silently shrinking the declared testing family.

Expanding folds start at756 sessions with252-session test blocks. Training
requires504 complete rows, fixed ridge penalty10, train-only means/scales and
train-only constant-column removal. Hyperparameters and combinations are not
selected on test outcomes. Entry is next-session close; labels must mature
strictly before the first test position. This ordinal purge does not certify
unknown provider label-availability clocks. Pure past-only folds never train
on future-of-test rows; no extra post-test embargo is asserted or tested.

The component fits eligible overlapping daily observations even when there
are fewer than20 nonoverlap windows. It separately reports insufficient
independent evidence; the incumbent learner's20-window gate is unchanged.
Three-way return sign accuracy, RMSE, past-training-mean baseline, folds and
nonoverlap counts are retained. Drawdown/volatility sign accuracy is omitted.

Mean squared-loss improvements use exploratory Bartlett HAC uncertainty on
the original session grid, with horizon+entry-delay lag. This is not a
finite-sample correction guarantee for persistent predictors or long horizons.
BY adjustment includes every declared case, including unavailable ones as1.
Fewer than20 nonoverlap windows or three folds withhold a p-value and preserve
insufficient evidence. No statistical result grants source/PIT/admission,
independent review, a virgin holdout, probability calibration or promotion.

Before an actual private experiment, pin the complete specification, input
hashes, implementation and dependencies; run the do-not-repeat preflight and
retain all attempts in the existing research-history route. Prior inspected
outcomes are not blind. Identical input/specification reuses the recorded run.

Focused validation: `python tests/a4_daily_multifactor_smoke.py`. Shared runner
registration is a separate coordinated patch after the Source/Main publication
sequence; no shared runner or frozen historical fixture is modified here.
