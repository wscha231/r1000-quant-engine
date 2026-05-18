# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-14`
- Tickers scored: 745
- Liquid tickers: 745

## Top Themes

- `optical_networking_ai_infra`: score 2.81, state `climax_hot`, 5d 13.38%, 21d 22.89%, top `COHR,LITE,CIEN`
- `memory_semiconductors`: score 2.51, state `emerging_leader`, 5d 5.58%, 21d 46.21%, top `MU,SNDK,STX,WDC,PSA,EXR`
- `ai_compute_semiconductors`: score 2.33, state `emerging_leader`, 5d 4.88%, 21d 22.62%, top `AMD,MRVL,ON,STM,HIMX,UMC,INTC,NVDA`
- `rare_earths_battery_materials`: score 1.04, state `emerging_leader`, 5d 9.06%, 21d 13.70%, top `TECK`
- `software`: score 0.53, state `neutral`, 5d 0.65%, 21d -0.00%, top `CSCO,IONQ,QUBT,HPE,FLEX,GLW,AAPL,ARW`
- `energy`: score 0.34, state `neutral`, 5d 1.65%, 21d 2.40%, top `ENB,OXY,CNQ,NUE,FANG,OKE,MPC,WMB`
- `industrial`: score 0.07, state `neutral`, 5d -1.12%, 21d 0.16%, top `BE,AAON,VRT,URI,KNX,JBHT,FIX,MTZ`
- `software_ai_platforms`: score 0.02, state `neutral`, 5d -3.27%, 21d 1.31%, top `PANW,AKAM,CRWD,FTNT,ORCL,TTWO,NTAP,APP`
- `power_grid_gas_turbine`: score -0.04, state `neutral`, 5d 1.04%, 21d 1.58%, top `PWR,NXT,NVT,GEV,ETN,AEP,GTLS,TLN`
- `medtech`: score -0.21, state `neutral`, 5d -0.56%, 21d -3.62%, top `UNH,CVS,ELV,DVA,LLY,DOC,ABBV,VTR`

## Top Tickers

- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d 5.67%, 5d 66.95%, 21d 78.25%, score 3.81
- `CSCO` CISCO SYSTEMS INC: theme `software`, 1d 13.32%, 5d 25.26%, 21d 40.17%, score 3.72
- `MU` MICRON TECHNOLOGY INC: theme `memory_semiconductors`, 1d -1.19%, 5d 22.81%, 21d 74.06%, score 3.72
- `AMD` ADVANCED MICRO DEVICES INC: theme `ai_compute_semiconductors`, 1d 0.92%, 5d 10.07%, 21d 74.17%, score 3.13
- `MRVL` MARVELL TECHNOLOGY INC: theme `ai_compute_semiconductors`, 1d 3.74%, 5d 15.38%, 21d 37.16%, score 3.00
- `ON` ON SEMICONDUCTOR CORP: theme `ai_compute_semiconductors`, 1d 2.77%, 5d 18.20%, 21d 64.19%, score 2.99
- `BE` Bloom Energy: theme `industrial`, 1d 4.73%, 5d 17.33%, 21d 41.91%, score 2.99
- `IONQ` IonQ: theme `software`, 1d 4.04%, 5d 20.59%, 21d 32.94%, score 2.98
- `STM` STMicroelectronics: theme `ai_compute_semiconductors`, 1d 2.21%, 5d 15.90%, 21d 59.26%, score 2.95
- `HIMX` Himax Technologies: theme `ai_compute_semiconductors`, 1d 1.20%, 5d 29.99%, 21d 104.68%, score 2.86
- `UMC` United Microelectronics: theme `ai_compute_semiconductors`, 1d 8.67%, 5d 14.12%, 21d 73.87%, score 2.85
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 3.10%, 5d 19.50%, 21d 43.11%, score 2.85
- `QUBT` Quantum Computing Inc: theme `software`, 1d 11.24%, 5d 27.41%, 21d 30.53%, score 2.83
- `COHR` COHERENT CORP: theme `optical_networking_ai_infra`, 1d 0.62%, 5d 27.26%, 21d 31.80%, score 2.82
- `AKAM` AKAMAI TECHNOLOGIES INC: theme `software_ai_platforms`, 1d -2.81%, 5d 34.21%, 21d 73.29%, score 2.75
- `INTC` INTEL CORPORATION CORP: theme `ai_compute_semiconductors`, 1d -2.88%, 5d 6.57%, 21d 79.89%, score 2.68
- `SNDK` SANDISK CORP: theme `memory_semiconductors`, 1d -2.83%, 5d 4.95%, 21d 57.70%, score 2.65
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d -0.41%, 5d 6.21%, 21d 56.66%, score 2.52
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 3.17%, 5d 14.77%, 21d 41.17%, score 2.51
- `NVDA` NVIDIA CORP: theme `ai_compute_semiconductors`, 1d 4.38%, 5d 11.45%, 21d 18.53%, score 2.47

## ETF Attention

- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d 12.04%, 21d 53.33%, attention 1.50, holdings `MU,SNDK,WDC,STX`
- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d 4.23%, 21d 31.66%, attention 1.27, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d 6.08%, 21d 45.03%, attention 1.25, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d 6.97%, 21d 27.54%, attention 1.16, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d -1.92%, 21d 4.30%, attention -0.08, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d -1.33%, 21d 0.10%, attention -0.14, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d -0.64%, 21d 7.01%, attention -0.19, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d 1.02%, 21d -4.13%, attention -0.55, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d -8.50%, 21d 0.89%, attention -0.64, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d -8.61%, 21d -3.51%, attention -0.76, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`

## ETF Look-Through Watchlist

- `MU` via `DRAM`/memory_semiconductors: ETF attention 1.50, ticker score 3.72, 5d 22.81%, in universe `True`
- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.27, ticker score 3.72, 5d 22.81%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.25, ticker score 3.72, 5d 22.81%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 1.16, ticker score 3.72, 5d 22.81%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.27, ticker score 3.13, 5d 10.07%, in universe `True`
- `SNDK` via `DRAM`/memory_semiconductors: ETF attention 1.50, ticker score 2.65, 5d 4.95%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.25, ticker score 3.13, 5d 10.07%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.27, ticker score 3.00, 5d 15.38%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.27, ticker score 2.99, 5d 18.20%, in universe `True`
- `STX` via `DRAM`/memory_semiconductors: ETF attention 1.50, ticker score 2.52, 5d 6.21%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.25, ticker score 3.00, 5d 15.38%, in universe `True`
- `ON` via `XSD`/semiconductors_equal_weight: ETF attention 1.25, ticker score 2.99, 5d 18.20%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 1.16, ticker score 3.13, 5d 10.07%, in universe `True`
- `INTC` via `SOXX`/semiconductors_broad: ETF attention 1.27, ticker score 2.68, 5d 6.57%, in universe `True`
- `INTC` via `XSD`/semiconductors_equal_weight: ETF attention 1.25, ticker score 2.68, 5d 6.57%, in universe `True`
- `NVDA` via `SOXX`/semiconductors_broad: ETF attention 1.27, ticker score 2.47, 5d 11.45%, in universe `True`
- `WDC` via `DRAM`/memory_semiconductors: ETF attention 1.50, ticker score 2.01, 5d 6.82%, in universe `True`
- `INTC` via `SMH`/semiconductors_broad: ETF attention 1.16, ticker score 2.68, 5d 6.57%, in universe `True`
- `NVDA` via `SMH`/semiconductors_broad: ETF attention 1.16, ticker score 2.47, 5d 11.45%, in universe `True`
- `ARM` via `SMH`/semiconductors_broad: ETF attention 1.16, ticker score 2.34, 5d 4.85%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
