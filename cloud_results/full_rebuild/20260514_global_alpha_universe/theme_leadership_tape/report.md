# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-13`
- Tickers scored: 737
- Liquid tickers: 737

## Top Themes

- `memory_semiconductors`: score 2.08, state `emerging_leader`, 5d 2.45%, 21d 44.07%, top `MU,SNDK,STX,WDC,PSA,EXR`
- `optical_networking_ai_infra`: score 1.79, state `emerging_leader`, 5d 9.12%, 21d 23.70%, top `COHR,LITE,CIEN`
- `ai_compute_semiconductors`: score 1.62, state `emerging_leader`, 5d 1.86%, 21d 21.67%, top `HIMX,STM,ON,QCOM,INTC,AMD,MTSI,MRVL`
- `rare_earths_battery_materials`: score 0.48, state `emerging_leader`, 5d 7.79%, 21d 13.50%, top `TECK`
- `software_ai_platforms`: score 0.35, state `neutral`, 5d -2.16%, 21d 3.59%, top `AKAM,PANW,FTNT,CRWD,GEN,ORCL,VRSN,FFIV`
- `software`: score 0.32, state `neutral`, 5d -1.02%, 21d 1.08%, top `FLEX,CSCO,GLW,HPE,GOOGL,AAPL,GOOG,AMZN`
- `energy`: score 0.07, state `neutral`, 5d -0.45%, 21d 1.50%, top `TRGP,FCX,MPC,LIN,FANG,NUE,XOM,STLD`
- `medtech`: score -0.09, state `neutral`, 5d -0.62%, 21d -4.70%, top `UNH,CVS,ELV,LLY,DVA,CI,VTR,WELL`
- `consumer`: score -0.17, state `neutral`, 5d -3.24%, 21d -4.19%, top `TSLA,SFM,HRB,PRMB,BWA,ARMK,PM,MUSA`
- `industrial`: score -0.24, state `neutral`, 5d -3.47%, 21d -1.54%, top `AAON,BE,VRT,FIX,MTZ,GWW,CMI,URI`

## Top Tickers

- `MU` MICRON TECHNOLOGY INC: theme `memory_semiconductors`, 1d 4.83%, 5d 20.56%, 21d 72.58%, score 4.18
- `AKAM` AKAMAI TECHNOLOGIES INC: theme `software_ai_platforms`, 1d 7.74%, 5d 32.09%, 21d 81.38%, score 3.76
- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d 5.61%, 5d 46.66%, 21d 71.91%, score 3.73
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 5.65%, 5d 24.01%, 21d 40.97%, score 3.31
- `HIMX` Himax Technologies: theme `ai_compute_semiconductors`, 1d 7.74%, 5d 66.99%, 21d 106.31%, score 3.26
- `STM` STMicroelectronics: theme `ai_compute_semiconductors`, 1d 9.43%, 5d 9.39%, 21d 54.99%, score 3.19
- `ON` ON SEMICONDUCTOR CORP: theme `ai_compute_semiconductors`, 1d 11.14%, 5d 9.40%, 21d 60.60%, score 3.19
- `QCOM` QUALCOMM INC: theme `ai_compute_semiconductors`, 1d 1.36%, 5d 10.70%, 21d 60.47%, score 3.12
- `FTNT` FORTINET INC: theme `software_ai_platforms`, 1d 3.35%, 5d 30.84%, 21d 49.54%, score 3.11
- `INTC` INTEL CORPORATION CORP: theme `ai_compute_semiconductors`, 1d -0.27%, 5d 6.44%, 21d 88.51%, score 3.03
- `AMD` ADVANCED MICRO DEVICES INC: theme `ai_compute_semiconductors`, 1d -0.62%, 5d 5.72%, 21d 74.66%, score 3.01
- `COHR` COHERENT CORP: theme `optical_networking_ai_infra`, 1d 7.94%, 5d 17.13%, 21d 28.81%, score 2.97
- `MTSI` MACOM TECHNOLOGY SOLUTIONS INC: theme `ai_compute_semiconductors`, 1d 5.18%, 5d 23.16%, 21d 44.57%, score 2.92
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 3.00%, 5d 20.19%, 21d 41.18%, score 2.90
- `SNDK` SANDISK CORP: theme `memory_semiconductors`, 1d -0.33%, 5d 2.64%, 21d 53.23%, score 2.86
- `MRVL` MARVELL TECHNOLOGY INC: theme `ai_compute_semiconductors`, 1d 8.18%, 5d 3.37%, 21d 32.97%, score 2.72
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d 1.06%, 5d 3.93%, 21d 53.22%, score 2.63
- `FLEX` FLEX LTD: theme `software`, 1d 2.94%, 5d 6.73%, 21d 79.44%, score 2.60
- `AAON` AAON INC: theme `industrial`, 1d 1.28%, 5d 37.71%, 21d 44.30%, score 2.52
- `TSLA` TESLA INC: theme `consumer`, 1d 2.73%, 5d 11.67%, 21d 22.26%, score 2.37

## ETF Attention

- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d 12.04%, 21d 53.33%, attention 1.59, holdings `MU,SNDK,WDC,STX`
- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d 4.23%, 21d 31.66%, attention 1.30, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d 6.08%, 21d 45.03%, attention 1.30, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d 4.13%, 21d 26.65%, attention 1.15, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d -1.92%, 21d 4.30%, attention -0.10, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d -1.33%, 21d 0.10%, attention -0.16, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d -0.64%, 21d 7.01%, attention -0.20, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d 1.02%, 21d -4.13%, attention -0.55, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d -8.50%, 21d 0.89%, attention -0.71, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d -8.61%, 21d -3.51%, attention -0.84, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`

## ETF Look-Through Watchlist

- `MU` via `DRAM`/memory_semiconductors: ETF attention 1.59, ticker score 4.18, 5d 20.56%, in universe `True`
- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 4.18, 5d 20.56%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.30, ticker score 4.18, 5d 20.56%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 1.15, ticker score 4.18, 5d 20.56%, in universe `True`
- `SNDK` via `DRAM`/memory_semiconductors: ETF attention 1.59, ticker score 2.86, 5d 2.64%, in universe `True`
- `STX` via `DRAM`/memory_semiconductors: ETF attention 1.59, ticker score 2.63, 5d 3.93%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 3.19, 5d 9.40%, in universe `True`
- `ON` via `XSD`/semiconductors_equal_weight: ETF attention 1.30, ticker score 3.19, 5d 9.40%, in universe `True`
- `QCOM` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 3.12, 5d 10.70%, in universe `True`
- `INTC` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 3.03, 5d 6.44%, in universe `True`
- `INTC` via `XSD`/semiconductors_equal_weight: ETF attention 1.30, ticker score 3.03, 5d 6.44%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 3.01, 5d 5.72%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.30, ticker score 3.01, 5d 5.72%, in universe `True`
- `QCOM` via `SMH`/semiconductors_broad: ETF attention 1.15, ticker score 3.12, 5d 10.70%, in universe `True`
- `WDC` via `DRAM`/memory_semiconductors: ETF attention 1.59, ticker score 2.16, 5d 2.26%, in universe `True`
- `INTC` via `SMH`/semiconductors_broad: ETF attention 1.15, ticker score 3.03, 5d 6.44%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 2.72, 5d 3.37%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.30, ticker score 2.72, 5d 3.37%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 1.15, ticker score 3.01, 5d 5.72%, in universe `True`
- `NVDA` via `SOXX`/semiconductors_broad: ETF attention 1.30, ticker score 2.20, 5d 8.66%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
