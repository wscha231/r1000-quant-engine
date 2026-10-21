# Performance-oriented 13F research watch cohort — 2026-10-21

The existing Source owner can track the ten SEC manager identities below with
its existing 13F manager universe and quarterly workflow. This is a research
cohort selected from a public three-year stock-performance screen, not a claim
of the world's ten best hedge funds by actual fund NAV or net investor returns.

Selection basis: HedgeFollow manager-weighted top-20 stock holdings performance
over the past three years. The publisher snapshot is labelled beginning of Q3
2026 and was retrieved on 2026-10-21. Its population includes institutional
investors beyond hedge funds. This cohort favors manager research applicability;
vehicle-specific hedge-fund qualification, comparable fund net CAGR/Sharpe/MDD
and independent filing-delay/PIT replication remain unverified. Those fields are
blank or false in the companion CSV. No portfolio allocation or score rank is
inferred from the publisher's percentages.

Sources:
- https://hedgefollow.com/top-hedge-funds.php
- https://hedgefollow.com/how-we-rank-hedge-funds.php
- SEC submissions URLs and actual Q2 accession/raw hashes are in the CSV.
- https://www.sec.gov/rules-regulations/staff-guidance/frequently-asked-questions-about-form-13f

| Cohort | SEC manager | CIK | Publisher screen rank | Q2 stored rows |
| --- | --- | --- | --- | --- |
| 1 | FengHe Fund Management Pte. Ltd. | 0001660531 | 2 | 18 |
| 2 | SPRUCE HOUSE INVESTMENT MANAGEMENT LLC | 0001543170 | 3 | 11 |
| 3 | Caligan Partners LP | 0001727492 | 4 | 28 |
| 4 | CloudAlpha Capital Management Limited/Hong Kong | 0001745907 | 7 | 36 |
| 5 | CAS Investment Partners, LLC | 0001697591 | 8 | 6 |
| 6 | REDWOOD CAPITAL MANAGEMENT, LLC | 0001316622 | 9 | 25 |
| 7 | Slate Path Capital LP | 0001559706 | 10 | 40 |
| 8 | Whale Rock Capital Management LLC | 0001387322 | 11 | 35 |
| 9 | Fairmount Funds Management LLC | 0001802528 | 12 | 12 |
| 10 | Atreides Management, LP | 0001777813 | 14 | 49 |

The screen's earlier individual/family-office reporting identity Jeffrey Gendell,
public asset manager BIT Capital, adviser VARA and crossover/private portfolio
Greenoaks are not included pending comparable vehicle qualification. This is a
scope choice, not evidence that those managers are ineligible or lower quality.

Whale Rock and Atreides already exist in the universe and retain their original
collection priorities. Eight unique CIKs are added: 35 total/34 active becomes
43 total/42 active, below the existing workflow maximum of 50. Other rows and
priorities are preserved. The two existing cohort rows no longer put a three-year
proxy into the legacy two-year field. New three-year metrics live only in the
companion CSV; the builder still selects by existing verified identity rules.
The legacy aum_13f_usd field records reported 13F aggregate value, not fund NAV/AUM.

Actual Native source execution checked all ten SEC identities and indexed 430
filings. The latest due Q2 2026 period selected ten original accessions, producing
260 normalized rows. Mapped rows were 48/260 (18.46%), mapped value 24.78%. All
raw XML and parser receipts were retained. The existing combined-analysis
manager/mapping and Form4/ETF gates therefore remain blocked; source parsing
success does not make the cohort economically usable. Q3 2026 remains monitored
before its 2026-11-16 deadline rather than automatically classified as missing.

The companion CSV contains the ten actual accession, accepted_at, amendment type,
row counts and raw hashes. Independent Source DATA A6 verified the original
260-row generation, while a subsequent metadata-only Native derivation reused
those XMLs and explicitly records ORIGINAL on both rows and receipts. No provider
requests were made in that derivation; its second pass reused all ten checkpoints
without parsing. Local execution and evidence storage are not an accepted SEC
Lake generation or proof of scheduled production collection after merge.

Do not enable w_pda_13f, w_pda_form4 or live-score switches from this cohort.
Actual disclosure-to-A2/Registry/A3 consumption stays with the incumbent Main
owner and requires genuine downstream references. This data PR does not supply
economic-effect validation, automatic reselection, a new collector or scheduler.
