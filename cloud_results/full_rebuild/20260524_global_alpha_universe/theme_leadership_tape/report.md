# Theme Leadership Tape

Report-only daily sidecar. It detects current market leadership concentration and does not alter production portfolios.

## Freshness

- Scored source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/scored_latest.csv`
- Latest price date: `2026-05-22`
- Tickers scored: 725
- Liquid tickers: 725

## Top Themes

- `ai_compute_semiconductors`: score 2.44, state `emerging_leader`, 5d 6.03%, 21d 12.77%, top `QCOM,ARM,ALAB,AMD,HIMX,MRVL,NXPI,STM`
- `memory_semiconductors`: score 2.14, state `emerging_leader`, 5d 4.00%, 21d 29.22%, top `MU,SNDK,STX,WDC,PSA,EXR`
- `software_ai_platforms`: score 1.41, state `neutral`, 5d 4.44%, 21d 6.86%, top `CRWD,NTAP,PANW,FTNT,FFIV,CDNS,NOW,AKAM`
- `software`: score 0.79, state `neutral`, 5d 2.83%, 21d 1.88%, top `HPE,HPQ,CSCO,IBM,FSLR,P,FLEX,AAPL`
- `optical_networking_ai_infra`: score 0.15, state `neutral`, 5d -1.28%, 21d 11.81%, top `CIEN,COHR,LITE`
- `medtech`: score 0.10, state `neutral`, 5d 3.06%, 21d -0.28%, top `MRK,LLY,UNH,DVA,EW,ELV,DOC,CVS`
- `consumer`: score 0.10, state `neutral`, 5d 2.98%, 21d -2.30%, top `ROST,TSLA,HRB,DECK,CROX,SFM,DKS,BWA`
- `space_launch`: score 0.03, state `neutral`, 5d 3.09%, 21d 1.20%, top `RKLB,GE,TDG,DRS,FTAI,GD,SARO,LMT`
- `general`: score -0.18, state `neutral`, 5d 3.95%, 21d -0.80%, top `D,EXC,VZ,XEL,EVRG,TMUS,SO,ETR`
- `energy`: score -0.19, state `neutral`, 5d 1.20%, 21d 0.70%, top `MPC,STLD,TRGP,DINO,NEU,TRP,ENB,PSX`

## Top Tickers

- `QCOM` QUALCOMM INC: theme `ai_compute_semiconductors`, 1d 11.60%, 5d 18.20%, 21d 77.80%, score 4.02
- `ARM` Arm Holdings: theme `ai_compute_semiconductors`, 1d 2.78%, 5d 46.54%, 21d 49.80%, score 3.87
- `ALAB` ASTERA LABS INC: theme `ai_compute_semiconductors`, 1d 3.04%, 5d 31.89%, 21d 55.35%, score 3.57
- `AMD` ADVANCED MICRO DEVICES INC: theme `ai_compute_semiconductors`, 1d 3.99%, 5d 10.24%, 21d 53.12%, score 3.43
- `RKLB` ROCKET LAB CORP: theme `space_launch`, 1d 8.22%, 5d 8.81%, 21d 60.47%, score 3.24
- `HPE` HEWLETT PACKARD ENTERPRISE: theme `software`, 1d 10.63%, 5d 13.53%, 21d 34.55%, score 3.17
- `HPQ` HP INC: theme `software`, 1d 15.25%, 5d 21.29%, 21d 25.32%, score 3.16
- `CRWD` CROWDSTRIKE HOLDINGS INC CLASS A: theme `software_ai_platforms`, 1d 2.35%, 5d 11.68%, 21d 48.96%, score 3.10
- `NTAP` NETAPP INC: theme `software_ai_platforms`, 1d 12.43%, 5d 16.20%, 21d 28.56%, score 2.85
- `PANW` PALO ALTO NETWORKS INC: theme `software_ai_platforms`, 1d 3.03%, 5d 7.31%, 21d 50.44%, score 2.84
- `FTNT` FORTINET INC: theme `software_ai_platforms`, 1d 3.45%, 5d 9.08%, 21d 61.83%, score 2.80
- `MU` MICRON TECHNOLOGY INC: theme `memory_semiconductors`, 1d -1.46%, 5d 3.63%, 21d 55.90%, score 2.63
- `HIMX` Himax Technologies: theme `ai_compute_semiconductors`, 1d 5.78%, 5d 10.39%, 21d 92.50%, score 2.57
- `SNDK` SANDISK CORP: theme `memory_semiconductors`, 1d -4.12%, 5d 5.05%, 21d 58.58%, score 2.45
- `MRVL` MARVELL TECHNOLOGY INC: theme `ai_compute_semiconductors`, 1d 2.96%, 5d 10.99%, 21d 18.59%, score 2.36
- `NXPI` NXP Semiconductors: theme `ai_compute_semiconductors`, 1d 5.71%, 5d 8.57%, 21d 31.23%, score 2.34
- `STM` STMicroelectronics: theme `ai_compute_semiconductors`, 1d 1.83%, 5d 8.87%, 21d 34.50%, score 2.23
- `STX` Seagate Technology: theme `memory_semiconductors`, 1d 0.28%, 5d 2.17%, 21d 38.31%, score 2.13
- `QRVO` QORVO INC: theme `ai_compute_semiconductors`, 1d 8.89%, 5d 15.37%, 21d 25.73%, score 2.12
- `CSCO` CISCO SYSTEMS INC: theme `software`, 1d 1.87%, 5d 1.86%, 21d 35.92%, score 2.08

## ETF Attention

- `XSD` SPDR S&P Semiconductor ETF: theme `semiconductors_equal_weight`, 5d 9.89%, 21d 33.91%, attention 1.82, holdings `AMD,INTC,MU,MRVL,ON,MCHP,LSCC,MPWR,TER,ALAB,CRUS,ONTO`
- `SOXX` iShares Semiconductor ETF: theme `semiconductors_broad`, 5d 5.67%, 21d 21.84%, attention 1.25, holdings `NVDA,AVGO,AMD,MU,INTC,QCOM,MRVL,LRCX,AMAT,KLAC,MCHP,ON,MPWR`
- `SMH` VanEck Semiconductor ETF: theme `semiconductors_broad`, 5d 3.59%, 21d 19.61%, attention 0.81, holdings `NVDA,TSM,AVGO,ASML,AMD,MU,INTC,QCOM,LRCX,AMAT,KLAC,ARM`
- `DRAM` Roundhill Memory ETF: theme `memory_semiconductors`, 5d 3.37%, 21d 45.27%, attention 0.66, holdings `MU,SNDK,WDC,STX`
- `ARKK` ARK Innovation ETF: theme `innovation_beta`, 5d 2.00%, 21d -0.13%, attention -0.24, holdings `TSLA,COIN,ROKU,HOOD,CRSP,PATH,PLTR`
- `ITA` iShares U.S. Aerospace & Defense ETF: theme `aerospace_defense`, 5d 3.73%, 21d 2.86%, attention -0.28, holdings `RTX,LMT,NOC,GD,RKLB,KTOS,HWM`
- `XBI` SPDR Biotech ETF: theme `biotech_small`, 5d 0.74%, 21d -2.10%, attention -0.33, holdings `EXEL,INSM,CRSP,BEAM,EDIT`
- `XME` SPDR Metals & Mining ETF: theme `metals_mining`, 5d 1.28%, 21d -0.48%, attention -0.42, holdings `MP,FCX,CLF,X,NUE,STLD,AA`
- `NLR` VanEck Uranium and Nuclear ETF: theme `nuclear_power`, 5d 0.90%, 21d -10.59%, attention -0.79, holdings `CEG,BWXT,CCJ,LEU,SMR,OKLO`
- `URA` Global X Uranium ETF: theme `nuclear_uranium`, 5d -1.94%, 21d -13.30%, attention -1.03, holdings `CCJ,UEC,UUUU,LEU,NXE,DNN`

## ETF Look-Through Watchlist

- `ALAB` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 3.57, 5d 31.89%, in universe `True`
- `AMD` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 3.43, 5d 10.24%, in universe `True`
- `QCOM` via `SOXX`/semiconductors_broad: ETF attention 1.25, ticker score 4.02, 5d 18.20%, in universe `True`
- `MU` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 2.63, 5d 3.63%, in universe `True`
- `MRVL` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 2.36, 5d 10.99%, in universe `True`
- `AMD` via `SOXX`/semiconductors_broad: ETF attention 1.25, ticker score 3.43, 5d 10.24%, in universe `True`
- `QCOM` via `SMH`/semiconductors_broad: ETF attention 0.81, ticker score 4.02, 5d 18.20%, in universe `True`
- `LSCC` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 1.86, 5d 19.24%, in universe `True`
- `ARM` via `SMH`/semiconductors_broad: ETF attention 0.81, ticker score 3.87, 5d 46.54%, in universe `True`
- `ON` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 1.76, 5d 2.73%, in universe `True`
- `MU` via `SOXX`/semiconductors_broad: ETF attention 1.25, ticker score 2.63, 5d 3.63%, in universe `True`
- `AMD` via `SMH`/semiconductors_broad: ETF attention 0.81, ticker score 3.43, 5d 10.24%, in universe `True`
- `MRVL` via `SOXX`/semiconductors_broad: ETF attention 1.25, ticker score 2.36, 5d 10.99%, in universe `True`
- `MCHP` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 0.65, 5d 0.05%, in universe `True`
- `ON` via `SOXX`/semiconductors_broad: ETF attention 1.25, ticker score 1.76, 5d 2.73%, in universe `True`
- `MU` via `SMH`/semiconductors_broad: ETF attention 0.81, ticker score 2.63, 5d 3.63%, in universe `True`
- `MPWR` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 0.56, 5d 2.57%, in universe `True`
- `CRUS` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 0.37, 5d 7.18%, in universe `True`
- `MU` via `DRAM`/memory_semiconductors: ETF attention 0.66, ticker score 2.63, 5d 3.63%, in universe `True`
- `TER` via `XSD`/semiconductors_equal_weight: ETF attention 1.82, ticker score 0.29, 5d 6.13%, in universe `True`

## Interpretation

- `climax_hot` means the theme is already moving violently; use it for tactical participation and tight exit rules, not blind long-term compounding.
- `emerging_leader` is the better early-entry state; the next step is to A/B test staged sizing into these themes.
- ETF attention is a proxy from ETF price/volume/dollar-volume behavior plus a curated look-through seed list; it is not a verified fund-flow feed.
- This report uses adjusted closes through the latest cached price date, so it can evaluate through the most recent close when cache data is fresh.
