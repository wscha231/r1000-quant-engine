# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-08`
- Tickers scored: 734
- Liquid tickers: 734

## Top Themes

- `memory_semiconductors`: score 2.87, state `emerging_leader`, 5d 9.45%, 21d 49.17%, top `MU,SNDK,STX,WDC,PSA,EXR`
- `ai_compute_semiconductors`: score 2.20, state `emerging_leader`, 5d 4.76%, 21d 26.69%, top `AMD,QCOM,HIMX,MTSI,STM,MRVL,UMC,ARM`
- `rare_earths_battery_materials`: score 1.19, state `emerging_leader`, 5d 11.94%, 21d 18.68%, top `TECK`
- `software_ai_platforms`: score 1.02, state `neutral`, 5d 1.95%, 21d 10.17%, top `AKAM,FTNT,ORCL,CRWD,PANW,GEN,RBRK,CDNS`
- `optical_networking_ai_infra`: score 0.53, state `emerging_leader`, 5d 1.75%, 21d 12.46%, top `COHR,CIEN,LITE`
- `software`: score 0.34, state `neutral`, 5d 0.41%, 21d 0.15%, top `FLEX,GLW,HPE,HPQ,GOOGL,AMZN,AAPL,CSCO`
- `industrial`: score 0.08, state `neutral`, 5d -0.58%, 21d 1.25%, top `AAON,BE,VRT,ECG,FIX,ROK,CAT,MTZ`
- `consumer`: score 0.06, state `neutral`, 5d -0.40%, 21d -1.39%, top `TSLA,MNST,PRMB,HRB,TXRH,BWA,SFM,HST`
- `banking`: score -0.08, state `neutral`, 5d -0.82%, 21d 1.06%, top `CBOE,APO,ARES,BEN,MS,IVZ,JEF,BLK`
- `space_launch`: score -0.13, state `neutral`, 5d 2.37%, 21d -2.96%, top `RKLB,HWM,BA,FTAI,HEI,AXON,HXL,GE`

## Top Tickers

- `MU` MICRON TECHNOLOGY INC: theme `memory_semiconductors`, 1d 15.49%, 5d 37.73%, 21d 77.17%, score 4.65
- `SNDK` SANDISK CORP: theme `memory_semiconductors`, 1d 16.60%, 5d 31.62%, 21d 83.47%, score 4.48
- `AMD` ADVANCED MICRO DEVICES INC: theme `ai_compute_semiconductors`, 1d 11.44%, 5d 26.25%, 21d 92.36%, score 4.43
- `QCOM` QUALCOMM INC: theme `ai_compute_semiconductors`, 1d 8.17%, 5d 23.77%, 21d 71.50%, score 4.20
- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d 34.22%, 5d 33.83%, 21d 58.03%, score 3.85
- `FLEX` FLEX LTD: theme `software`, 1d 6.89%, 5d 55.04%, 21d 89.53%, score 3.65
- `AKAM` AKAMAI TECHNOLOGIES INC: theme `software_ai_platforms`, 1d 26.58%, 5d 42.21%, 21d 34.76%, score 3.52
- `HIMX` Himax Technologies: theme `ai_compute_semiconductors`, 1d 10.98%, 5d 44.52%, 21d 96.14%, score 3.43
- `AAON` AAON INC: theme `industrial`, 1d 8.05%, 5d 49.23%, 21d 53.86%, score 3.28
- `FTNT` FORTINET INC: theme `software_ai_platforms`, 1d 5.65%, 5d 32.19%, 21d 41.42%, score 3.20
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d 2.11%, 5d 7.66%, 21d 56.29%, score 2.92
- `MTSI` MACOM TECHNOLOGY SOLUTIONS INC: theme `ai_compute_semiconductors`, 1d 4.47%, 5d 26.64%, 21d 45.28%, score 2.88
- `ORCL` ORACLE CORP: theme `software_ai_platforms`, 1d 0.70%, 5d 14.04%, 21d 42.14%, score 2.81
- `WDC` WESTERN DIGITAL CORP: theme `memory_semiconductors`, 1d 3.47%, 5d 11.23%, 21d 42.06%, score 2.79
- `STM` STMicroelectronics: theme `ai_compute_semiconductors`, 1d 5.85%, 5d 6.13%, 21d 51.18%, score 2.76
- `MRVL` MARVELL TECHNOLOGY INC: theme `ai_compute_semiconductors`, 1d 6.32%, 5d 3.14%, 21d 41.93%, score 2.70
- `UMC` United Microelectronics: theme `ai_compute_semiconductors`, 1d 1.72%, 5d 18.16%, 21d 61.80%, score 2.69
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 4.36%, 5d 15.83%, 21d 33.72%, score 2.67
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 5.78%, 5d 14.80%, 21d 24.49%, score 2.53
- `DVA` DAVITA INC: theme `medtech`, 1d 1.22%, 5d 30.99%, 21d 31.84%, score 2.36

## ETF Attention

- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d 30.66%, 21d 63.06%, attention 2.05, holdings `MU,SNDK,WDC,STX`
- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d 11.71%, 21d 37.42%, attention 1.62, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d 11.18%, 21d 52.12%, attention 1.36, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d 11.13%, 21d 31.66%, attention 1.36, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d 3.29%, 21d 2.19%, attention 0.35, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d 2.86%, 21d 14.80%, attention 0.04, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d -1.18%, 21d 8.34%, attention -0.17, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d 2.02%, 21d 7.31%, attention -0.44, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d 3.34%, 21d -3.57%, attention -0.57, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d -2.17%, 21d 3.18%, attention -0.61, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`

## ETF Look-Through Watchlist

- `MU` via `DRAM`/memory_semiconductors: ETF attention 2.05, ticker score 4.65, 5d 37.73%, in universe `True`
- `SNDK` via `DRAM`/memory_semiconductors: ETF attention 2.05, ticker score 4.48, 5d 31.62%, in universe `True`
- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 4.65, 5d 37.73%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 4.43, 5d 26.25%, in universe `True`
- `QCOM` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 4.20, 5d 23.77%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.36, ticker score 4.65, 5d 37.73%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 1.36, ticker score 4.65, 5d 37.73%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.36, ticker score 4.43, 5d 26.25%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 1.36, ticker score 4.43, 5d 26.25%, in universe `True`
- `STX` via `DRAM`/memory_semiconductors: ETF attention 2.05, ticker score 2.92, 5d 7.66%, in universe `True`
- `QCOM` via `SMH`/semiconductors_broad: ETF attention 1.36, ticker score 4.20, 5d 23.77%, in universe `True`
- `WDC` via `DRAM`/memory_semiconductors: ETF attention 2.05, ticker score 2.79, 5d 11.23%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 2.70, 5d 3.14%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.36, ticker score 2.70, 5d 3.14%, in universe `True`
- `NVDA` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 2.11, 5d 8.44%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 2.10, 5d 0.16%, in universe `True`
- `AMAT` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 1.95, 5d 11.92%, in universe `True`
- `AVGO` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 1.90, 5d 2.07%, in universe `True`
- `LRCX` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 1.77, 5d 14.54%, in universe `True`
- `MCHP` via `SOXX`/semiconductors_broad: ETF attention 1.62, ticker score 1.72, 5d 5.47%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
