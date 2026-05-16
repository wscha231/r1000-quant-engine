# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-15`
- Tickers scored: 746
- Liquid tickers: 746

## Top Themes

- `optical_networking_ai_infra`: score 2.24, state `neutral`, 5d 7.40%, 21d 11.97%, top `COHR,LITE,CIEN`
- `memory_semiconductors`: score 1.51, state `emerging_leader`, 5d -3.72%, 21d 41.42%, top `MU,SNDK,STX,WDC,PSA,EXR`
- `ai_compute_semiconductors`: score 1.50, state `emerging_leader`, 5d -1.93%, 21d 13.60%, top `ALAB,UMC,MRVL,AMD,QCOM,STM,ON,TXN`
- `software_ai_platforms`: score 0.53, state `neutral`, 5d -1.95%, 21d 0.87%, top `PANW,CRWD,FTNT,AKAM,APP,MSFT,TTWO,NOW`
- `energy`: score 0.43, state `neutral`, 5d -1.05%, 21d 0.87%, top `OXY,XOM,TRGP,DVN,CHRD,FANG,MPC,CF`
- `software`: score 0.33, state `neutral`, 5d -2.18%, 21d -2.06%, top `CSCO,FLEX,VRT,AAPL,EBAY,HPE,GOOGL,GOOG`
- `power_grid_gas_turbine`: score 0.13, state `neutral`, 5d -0.53%, 21d 0.91%, top `NXT,PWR,NVT,GEV,ETN,GTLS,AEP,VST`
- `medtech`: score 0.04, state `neutral`, 5d -0.77%, 21d -5.12%, top `UNH,CVS,DVA,ELV,LLY,ABBV,JNJ,SYK`
- `banking`: score -0.02, state `neutral`, 5d -1.53%, 21d -2.72%, top `CBOE,AIZ,APO,BEN,GS,SCHW,MS,PGR`
- `industrial`: score -0.14, state `neutral`, 5d -3.34%, 21d -1.87%, top `BE,AAON,FIX,JBHT,URI,KNX,UNP,GWW`

## Top Tickers

- `CSCO` CISCO SYSTEMS INC: theme `software`, 1d 2.32%, 5d 22.41%, 21d 39.89%, score 3.26
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 1.94%, 5d 16.81%, 21d 45.43%, score 3.07
- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d -5.87%, 5d 18.30%, 21d 50.45%, score 2.93
- `ALAB` Astera Labs: theme `ai_compute_semiconductors`, 1d 1.77%, 5d 16.46%, 21d 36.22%, score 2.79
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 2.44%, 5d 12.56%, 21d 42.06%, score 2.69
- `MU` Micron Technology: theme `memory_semiconductors`, 1d -6.62%, 5d -2.97%, 21d 58.49%, score 2.49
- `SNDK` SanDisk: theme `memory_semiconductors`, 1d 1.80%, 5d -9.90%, 21d 53.09%, score 2.48
- `UMC` United Microelectronics: theme `ai_compute_semiconductors`, 1d 0.41%, 5d 11.54%, 21d 61.96%, score 2.41
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d -1.15%, 5d 1.64%, 21d 49.58%, score 2.41
- `FTNT` FORTINET INC: theme `software_ai_platforms`, 1d 0.75%, 5d 7.64%, 21d 49.00%, score 2.38
- `MRVL` Marvell Technology: theme `ai_compute_semiconductors`, 1d -3.12%, 5d 3.97%, 21d 32.63%, score 2.24
- `AMD` Advanced Micro Devices: theme `ai_compute_semiconductors`, 1d -5.69%, 5d -6.83%, 21d 52.41%, score 2.22
- `QCOM` Qualcomm: theme `ai_compute_semiconductors`, 1d 0.70%, 5d -8.03%, 21d 49.84%, score 2.10
- `STM` STMicroelectronics: theme `ai_compute_semiconductors`, 1d -4.61%, 5d 3.79%, 21d 47.73%, score 2.08
- `ON` ON SEMICONDUCTOR CORP: theme `ai_compute_semiconductors`, 1d -4.44%, 5d 9.60%, 21d 41.51%, score 2.08
- `TXN` TEXAS INSTRUMENT INC: theme `ai_compute_semiconductors`, 1d -1.77%, 5d 5.19%, 21d 36.38%, score 1.99
- `INTC` Intel: theme `ai_compute_semiconductors`, 1d -6.18%, 5d -12.93%, 21d 58.79%, score 1.95
- `COHR` Coherent: theme `optical_networking_ai_infra`, 1d -5.55%, 5d 14.08%, 21d 16.60%, score 1.91
- `WDC` Western Digital: theme `memory_semiconductors`, 1d -1.46%, 5d 0.42%, 21d 33.27%, score 1.88
- `FLEX` FLEX LTD: theme `software`, 1d -4.00%, 5d -3.03%, 21d 72.50%, score 1.87

## ETF Attention

- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d -1.80%, 21d 22.33%, attention 1.34, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d -0.83%, 21d 36.02%, attention 1.32, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d -2.26%, 21d 25.27%, attention 1.31, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d -3.22%, 21d 45.83%, attention 1.10, holdings `MU,SNDK,WDC,STX`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d -2.98%, 21d -3.52%, attention 0.20, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d -5.33%, 21d -3.15%, attention 0.05, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d -4.43%, 21d -0.32%, attention -0.20, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d -2.78%, 21d -5.13%, attention -0.32, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d -7.95%, 21d -10.84%, attention -0.94, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d -9.51%, 21d -9.66%, attention -1.11, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`

## ETF Look-Through Watchlist

- `ALAB` via `XSD`/semiconductors_equal_weight: ETF attention 1.32, ticker score 2.79, 5d 16.46%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 1.34, ticker score 2.49, 5d -2.97%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.32, ticker score 2.49, 5d -2.97%, in universe `True`
- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.31, ticker score 2.49, 5d -2.97%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 1.34, ticker score 2.22, 5d -6.83%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.32, ticker score 2.24, 5d 3.97%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.31, ticker score 2.24, 5d 3.97%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.32, ticker score 2.22, 5d -6.83%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.31, ticker score 2.22, 5d -6.83%, in universe `True`
- `QCOM` via `SMH`/semiconductors_broad: ETF attention 1.34, ticker score 2.10, 5d -8.03%, in universe `True`
- `QCOM` via `SOXX`/semiconductors_broad: ETF attention 1.31, ticker score 2.10, 5d -8.03%, in universe `True`
- `ON` via `XSD`/semiconductors_equal_weight: ETF attention 1.32, ticker score 2.08, 5d 9.60%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.31, ticker score 2.08, 5d 9.60%, in universe `True`
- `MU` via `DRAM`/memory_semiconductors: ETF attention 1.10, ticker score 2.49, 5d -2.97%, in universe `True`
- `SNDK` via `DRAM`/memory_semiconductors: ETF attention 1.10, ticker score 2.48, 5d -9.90%, in universe `True`
- `INTC` via `SMH`/semiconductors_broad: ETF attention 1.34, ticker score 1.95, 5d -12.93%, in universe `True`
- `STX` via `DRAM`/memory_semiconductors: ETF attention 1.10, ticker score 2.41, 5d 1.64%, in universe `True`
- `INTC` via `XSD`/semiconductors_equal_weight: ETF attention 1.32, ticker score 1.95, 5d -12.93%, in universe `True`
- `INTC` via `SOXX`/semiconductors_broad: ETF attention 1.31, ticker score 1.95, 5d -12.93%, in universe `True`
- `NVDA` via `SMH`/semiconductors_broad: ETF attention 1.34, ticker score 1.87, 5d 4.70%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
