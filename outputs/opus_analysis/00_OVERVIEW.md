# Opus Rule Discovery - Data Sample Overview

_Generated: 2026-04-25 16:24:58.629475_

## Source
- scored_oos_latest.parquet: 46650 rows, 2019-03-29 ~ 2026-02-27

## Bucket definitions
- **WINNER**: r_12m forward > +50%
- **LOSER**:  r_12m forward < -30%
- **AVERAGE**: r_12m forward in [-10%, +20%]

## Regime windows
- **2019_pre_covid**: 2019-03-31 ~ 2019-12-31
- **2020_covid**: 2020-02-28 ~ 2020-12-31
- **2022_bear**: 2022-01-31 ~ 2022-12-31
- **2024_ai_bull**: 2024-01-31 ~ 2024-12-31

## Files
- `<regime>_winner.md` - top winners + their features at signal time
- `<regime>_loser.md`  - big losers + their features
- `<regime>_average.md` - control group

## How to analyze
Read winner.md and loser.md for the SAME regime side-by-side.
Look for features where WINNERS systematically differ from LOSERS.
Validate any hypothesis via r1000_opus_hypothesis_tester.py.