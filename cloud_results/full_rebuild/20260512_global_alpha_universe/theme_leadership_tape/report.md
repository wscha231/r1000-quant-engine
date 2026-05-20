# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-12`
- Tickers scored: 730
- Liquid tickers: 730

## Top Themes

- `memory_semiconductors`: score 2.67, state `emerging_leader`, 5d 3.74%, 21d 43.28%, top `MU,STX,SNDK,WDC,PSA,EXR`
- `optical_networking_ai_infra`: score 1.75, state `emerging_leader`, 5d 4.27%, 21d 18.36%, top `COHR,CIEN,LITE`
- `ai_compute_semiconductors`: score 1.68, state `emerging_leader`, 5d 0.62%, 21d 18.16%, top `AMD,UMC,QCOM,NVDA,HIMX,MTSI,TXN,STM`
- `rare_earths_battery_materials`: score 1.55, state `emerging_leader`, 5d 13.63%, 21d 14.43%, top `TECK`
- `software_ai_platforms`: score 0.60, state `neutral`, 5d -0.23%, 21d 5.95%, top `AKAM,FTNT,CRWD,PANW,SNPS,ORCL,APP,CDNS`
- `software`: score 0.28, state `neutral`, 5d -0.34%, 21d 0.90%, top `FLEX,GLW,NBIX,AAPL,CSCO,GOOGL,GOOG,AMZN`
- `space_launch`: score 0.15, state `neutral`, 5d 2.55%, 21d -3.50%, top `RKLB,HWM,BA,AXON,GE,GD,FTAI,RTX`
- `consumer`: score -0.03, state `neutral`, 5d -0.85%, 21d -2.48%, top `TSLA,SFM,HRB,PM,ARMK,PRMB,TXRH,BWA`
- `medtech`: score -0.03, state `neutral`, 5d -0.16%, 21d -3.61%, top `UNH,DVA,CVS,ELV,DOC,CI,LLY,WST`
- `industrial`: score -0.10, state `neutral`, 5d -0.87%, 21d -0.76%, top `AAON,VRT,BE,URI,FIX,GWW,CMI,CAT`

## Top Tickers

- `MU` MICRON TECHNOLOGY INC: theme `memory_semiconductors`, 1d -5.54%, 5d 17.34%, 21d 76.12%, score 3.62
- `AMD` ADVANCED MICRO DEVICES INC: theme `ai_compute_semiconductors`, 1d -4.13%, 5d 23.80%, 21d 78.19%, score 3.60
- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d 1.67%, 5d 51.48%, 21d 68.94%, score 3.34
- `FLEX` FLEX LTD: theme `software`, 1d -4.75%, 5d 43.26%, 21d 76.45%, score 2.89
- `AKAM` AKAMAI TECHNOLOGIES INC: theme `software_ai_platforms`, 1d -3.56%, 5d 25.11%, 21d 55.42%, score 2.89
- `FTNT` FORTINET INC: theme `software_ai_platforms`, 1d -1.91%, 5d 25.92%, 21d 43.80%, score 2.69
- `UMC` United Microelectronics: theme `ai_compute_semiconductors`, 1d 2.53%, 5d 14.10%, 21d 64.79%, score 2.65
- `QCOM` QUALCOMM INC: theme `ai_compute_semiconductors`, 1d -11.99%, 5d 12.06%, 21d 59.29%, score 2.61
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 0.82%, 5d 14.73%, 21d 35.92%, score 2.54
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 0.36%, 5d 16.55%, 21d 31.95%, score 2.49
- `UNH` UNITEDHEALTH GROUP INC: theme `medtech`, 1d 2.95%, 5d 8.77%, 21d 26.45%, score 2.43
- `DVA` DAVITA INC: theme `medtech`, 1d 1.01%, 5d 27.95%, 21d 32.57%, score 2.39
- `NVDA` NVIDIA CORP: theme `ai_compute_semiconductors`, 1d 0.84%, 5d 12.61%, 21d 16.89%, score 2.38
- `HIMX` Himax Technologies: theme `ai_compute_semiconductors`, 1d -8.84%, 5d 54.55%, 21d 103.28%, score 2.34
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d -4.02%, 5d 3.82%, 21d 55.96%, score 2.34
- `SNDK` SANDISK CORP: theme `memory_semiconductors`, 1d -8.15%, 5d 1.07%, 21d 49.23%, score 2.32
- `CVS` CVS HEALTH CORP: theme `medtech`, 1d 3.03%, 5d 17.75%, 21d 22.74%, score 2.31
- `AAON` AAON INC: theme `industrial`, 1d -6.16%, 5d 41.97%, 21d 42.15%, score 2.12
- `TSLA` TESLA INC: theme `consumer`, 1d -2.55%, 5d 11.37%, 21d 23.05%, score 2.10
- `VRT` VERTIV HOLDINGS CLASS A: theme `industrial`, 1d -0.06%, 5d 7.82%, 21d 22.58%, score 2.04

## ETF Attention

- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d 29.69%, 21d 69.84%, attention 2.68, holdings `MU,SNDK,WDC,STX`
- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d 15.95%, 21d 55.17%, attention 1.84, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d 15.30%, 21d 37.81%, attention 1.69, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d 7.38%, 21d 26.60%, attention 1.44, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d 2.30%, 21d 15.50%, attention -0.08, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d 0.94%, 21d 4.10%, attention -0.09, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d 4.49%, 21d 12.30%, attention -0.13, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d 6.48%, 21d 9.67%, attention -0.21, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d 1.53%, 21d 6.51%, attention -0.51, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d 5.44%, 21d -1.59%, attention -0.55, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`

## ETF Look-Through Watchlist

- `MU` via `DRAM`/memory_semiconductors: ETF attention 2.68, ticker score 3.62, 5d 17.34%, in universe `True`
- `STX` via `DRAM`/memory_semiconductors: ETF attention 2.68, ticker score 2.34, 5d 3.82%, in universe `True`
- `SNDK` via `DRAM`/memory_semiconductors: ETF attention 2.68, ticker score 2.32, 5d 1.07%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.84, ticker score 3.62, 5d 17.34%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.84, ticker score 3.60, 5d 23.80%, in universe `True`
- `WDC` via `DRAM`/memory_semiconductors: ETF attention 2.68, ticker score 1.85, 5d 3.36%, in universe `True`
- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 3.62, 5d 17.34%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 3.60, 5d 23.80%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 1.44, ticker score 3.62, 5d 17.34%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 1.44, ticker score 3.60, 5d 23.80%, in universe `True`
- `QCOM` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 2.61, 5d 12.06%, in universe `True`
- `NVDA` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 2.38, 5d 12.61%, in universe `True`
- `QCOM` via `SMH`/semiconductors_broad: ETF attention 1.44, ticker score 2.61, 5d 12.06%, in universe `True`
- `ON` via `XSD`/semiconductors_equal_weight: ETF attention 1.84, ticker score 1.62, 5d 0.65%, in universe `True`
- `NVDA` via `SMH`/semiconductors_broad: ETF attention 1.44, ticker score 2.38, 5d 12.61%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 1.62, 5d 0.65%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.84, ticker score 1.30, 5d -3.91%, in universe `True`
- `MCHP` via `XSD`/semiconductors_equal_weight: ETF attention 1.84, ticker score 1.07, 5d -1.70%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 1.30, 5d -3.91%, in universe `True`
- `MCHP` via `SOXX`/semiconductors_broad: ETF attention 1.69, ticker score 1.07, 5d -1.70%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
