# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-12`
- Tickers scored: 732
- Liquid tickers: 732

## Top Themes

- `memory_semiconductors`: score 2.62, state `emerging_leader`, 5d 4.54%, 21d 46.01%, top `MU,SNDK,STX,WDC,PSA,EXR`
- `optical_networking_ai_infra`: score 1.89, state `emerging_leader`, 5d 5.95%, 21d 20.26%, top `COHR,CIEN,LITE`
- `ai_compute_semiconductors`: score 1.72, state `emerging_leader`, 5d 1.02%, 21d 20.24%, top `AMD,UMC,QCOM,HIMX,MTSI,NVDA,TXN,ON`
- `rare_earths_battery_materials`: score 1.50, state `emerging_leader`, 5d 14.13%, 21d 14.93%, top `TECK`
- `software_ai_platforms`: score 0.67, state `neutral`, 5d 0.43%, 21d 5.94%, top `AKAM,FTNT,PANW,CRWD,APP,ORCL,SNPS,CDNS`
- `software`: score 0.27, state `neutral`, 5d -0.30%, 21d 0.73%, top `FLEX,GLW,NBIX,AAPL,CSCO,GOOGL,P,EBAY`
- `space_launch`: score 0.08, state `neutral`, 5d 2.90%, 21d -3.59%, top `RKLB,HWM,BA,AXON,GE,DRS,GD,RTX`
- `medtech`: score -0.07, state `neutral`, 5d -0.46%, 21d -3.38%, top `UNH,DVA,CVS,ELV,DOC,CI,LLY,SOLV`
- `consumer`: score -0.07, state `neutral`, 5d -1.17%, 21d -2.59%, top `TSLA,HRB,SFM,PM,ARMK,PRMB,TXRH,MNST`
- `industrial`: score -0.12, state `neutral`, 5d -0.99%, 21d -1.25%, top `AAON,VRT,BE,FIX,URI,GWW,CMI,CAT`

## Top Tickers

- `MU` MICRON TECHNOLOGY INC: theme `memory_semiconductors`, 1d -3.61%, 5d 19.74%, 21d 79.71%, score 3.89
- `AMD` ADVANCED MICRO DEVICES INC: theme `ai_compute_semiconductors`, 1d -2.29%, 5d 26.19%, 21d 81.62%, score 3.73
- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d 0.18%, 5d 49.26%, 21d 66.47%, score 3.25
- `AKAM` AKAMAI TECHNOLOGIES INC: theme `software_ai_platforms`, 1d -2.25%, 5d 26.81%, 21d 57.53%, score 3.02
- `FLEX` FLEX LTD: theme `software`, 1d -3.71%, 5d 44.83%, 21d 78.38%, score 3.00
- `FTNT` FORTINET INC: theme `software_ai_platforms`, 1d -1.36%, 5d 26.63%, 21d 44.62%, score 2.79
- `UMC` United Microelectronics: theme `ai_compute_semiconductors`, 1d 3.01%, 5d 14.63%, 21d 65.57%, score 2.75
- `QCOM` QUALCOMM INC: theme `ai_compute_semiconductors`, 1d -11.46%, 5d 12.74%, 21d 60.25%, score 2.66
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 0.91%, 5d 17.19%, 21d 32.67%, score 2.64
- `SNDK` SANDISK CORP: theme `memory_semiconductors`, 1d -6.17%, 5d 3.25%, 21d 52.44%, score 2.60
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 0.72%, 5d 14.62%, 21d 35.78%, score 2.57
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d -3.02%, 5d 4.90%, 21d 57.57%, score 2.48
- `UNH` UNITEDHEALTH GROUP INC: theme `medtech`, 1d 3.11%, 5d 8.94%, 21d 26.64%, score 2.48
- `DVA` DAVITA INC: theme `medtech`, 1d 0.81%, 5d 27.70%, 21d 32.32%, score 2.46
- `HIMX` Himax Technologies: theme `ai_compute_semiconductors`, 1d -7.46%, 5d 56.90%, 21d 106.37%, score 2.43
- `MTSI` MACOM TECHNOLOGY SOLUTIONS INC: theme `ai_compute_semiconductors`, 1d -0.85%, 5d 19.50%, 21d 37.60%, score 2.42
- `CVS` CVS HEALTH CORP: theme `medtech`, 1d 3.18%, 5d 17.92%, 21d 22.92%, score 2.41
- `NVDA` NVIDIA CORP: theme `ai_compute_semiconductors`, 1d 0.61%, 5d 12.36%, 21d 16.62%, score 2.38
- `AAON` AAON INC: theme `industrial`, 1d -5.67%, 5d 42.71%, 21d 42.89%, score 2.19
- `WDC` WESTERN DIGITAL CORP: theme `memory_semiconductors`, 1d -5.25%, 5d 5.05%, 21d 39.58%, score 2.15

## ETF Attention

- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d 6.89%, 21d 31.18%, attention 1.77, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d 10.82%, 21d 52.91%, attention 1.69, holdings `MU,SNDK,WDC,STX`
- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d 6.28%, 21d 44.68%, attention 1.63, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d 7.38%, 21d 26.60%, attention 1.62, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d 2.13%, 21d 8.69%, attention 0.04, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d 3.97%, 21d 7.53%, attention -0.16, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d 0.28%, 21d 4.16%, attention -0.25, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d -1.04%, 21d 0.63%, attention -0.40, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d 0.84%, 21d 2.17%, attention -0.41, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d 4.65%, 21d -3.19%, attention -0.51, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`

## ETF Look-Through Watchlist

- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 3.89, 5d 19.74%, in universe `True`
- `MU` via `DRAM`/memory_semiconductors: ETF attention 1.69, ticker score 3.89, 5d 19.74%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 3.73, 5d 26.19%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.63, ticker score 3.89, 5d 19.74%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 1.62, ticker score 3.89, 5d 19.74%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.63, ticker score 3.73, 5d 26.19%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 1.62, ticker score 3.73, 5d 26.19%, in universe `True`
- `QCOM` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 2.66, 5d 12.74%, in universe `True`
- `SNDK` via `DRAM`/memory_semiconductors: ETF attention 1.69, ticker score 2.60, 5d 3.25%, in universe `True`
- `NVDA` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 2.38, 5d 12.36%, in universe `True`
- `QCOM` via `SMH`/semiconductors_broad: ETF attention 1.62, ticker score 2.66, 5d 12.74%, in universe `True`
- `STX` via `DRAM`/memory_semiconductors: ETF attention 1.69, ticker score 2.48, 5d 4.90%, in universe `True`
- `NVDA` via `SMH`/semiconductors_broad: ETF attention 1.62, ticker score 2.38, 5d 12.36%, in universe `True`
- `WDC` via `DRAM`/memory_semiconductors: ETF attention 1.69, ticker score 2.15, 5d 5.05%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 1.79, 5d 1.40%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 1.55, 5d -2.52%, in universe `True`
- `ON` via `XSD`/semiconductors_equal_weight: ETF attention 1.63, ticker score 1.79, 5d 1.40%, in universe `True`
- `ARM` via `SMH`/semiconductors_broad: ETF attention 1.62, ticker score 1.74, 5d -0.44%, in universe `True`
- `MCHP` via `SOXX`/semiconductors_broad: ETF attention 1.77, ticker score 1.30, 5d -0.79%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.63, ticker score 1.55, 5d -2.52%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
