# R1000 미국주식 — 실제치 우선 가치평가 H1 감사·최소 Native 적용

- TASK_KEY: `R1000-US-ACTUAL-FIRST-PEG-ROIC-PROVENANCE-H1-20261012`
- Repo: `wscha231/r1000-quant-engine`, initially audited master `69acbb59afaba5bfd26b1cbaa2bc8811580a4c46`, tree `0b709650514d1864847eb0d168115ddd64005075`. **Rechecked live master** `b3cf8b83b756e382afda60c202475fba42ff0041` (merged PR #593); `r1000_features.py` and `tests/smoke_test.py` Git blob SHAs are unchanged, so the bounded addition-only patch context remains valid. This does NOT establish a clean Native worktree.
- Mode: `RESEARCH_ONLY / H1_READ_ONLY_CANDIDATE / NO_ECONOMIC_AUTHORITY`.
- Result: Local diagnostic implementation, archived source-row comparisons, normal/-O tests. **Not merged; no native CI/A6, no real SEC/price source admission, no economic A/B**.

## 1. Code census and serious semantics risks

| Current path | Observed behavior | Consequence | Disposition |
|---|---|---|---|
| `r1000_features.py` L1583–1591 | Finnhub `fh_peExclExtra_ttm` and `1/ep_ttm` may fill `forward_pe_final` | Trailing P/E masquerades as forward | Do not use as certified forward |
| `r1000_features.py` L1595–1650 | Vendor PEG or current `forward_pe_final` divided by mixed actual/derived growth | Fiscal period/basis not comparable | Current `peg_final` remains legacy diagnostic |
| `r1000_features.py` L1704–1717 & L3762 | `peg_final` contributes to `forward_value_score` and `valuation_blueprint_score` | Can affect research rankings; magnitude unmeasured | Build shadow first, no immediate score mutation |
| `r1000_features.py` L2526–2531 | Missing SBC estimated from dilution or set to 0 | Missing is not zero or actual SBC | Source class `UNVERIFIED_PROXY` |
| `r1000_features.py` L2533–2540 | Missing R&D estimated as gross−operating margin | Includes SGA, not actual R&D | Must not be labeled real R&D |
| `r1000_features.py` L2543–2551 | `roic_approx` uses 21% tax, current liabilities proxy 30%, cap/ffill | Accounting estimate, not actual ROIC | Isolate from actual ROIC |
| `r1000_features.py` L2553–2562 | Interest coverage may use liabilities×4% | Speculative cost of debt | Do not count as actual interest expense |
| `r1000_config.py` L785–925 | `peg_final`, `roic_approx` are in `DEFAULT_FEATURES` | They may be included in walk-forward ML | Retrain/quantify effects separately |
| `r1000_pipeline.py` L7786–7796 | Main calls `merge_live_fundamentals` then `compute_live_factor_columns` | Actual main fallback path | New diagnostics can attach as separate post-scoring report |
| `r1000_valuations.py` | Contains standalone recompute and risky 5–30% growth clamping | `compute_live_valuations` not called in main pipeline | Fixing that file alone won't fix Main |
| `tools/earnings_consensus_h1.py` | Strict `accounting_basis`, FY period, issuer/security/ADR, availability; `h2_eligible=false` | Vendor snapshot not yet H2-approved | Reuse native verifier in separate H1 PEG PR |

## 2. Real archived code-output census (not present-day broker holdings)

Input GitHub source files at exact master:

- Main: `cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_latest.csv`, blob SHA1 `21432762b0016b1c098fe671ebce444a17451df3`. 19 displayed rows including 1 `CASH`; 18 equity rows. PEG 14/18, forward PE 18/18, ROIC proxy 0/18. **No FY1/FY2 estimates in this reduced source format**, no forward P/E origin or full fundamental lineage columns. `fcf_ttm` not in this 149-field output; `fcfy_ttm` observations exist for 15/18 equity rows and are preserved separately as unverified yields. No claim FCF absent upstream.
- Concentrated: `cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_portfolio_latest.csv`, blob SHA1 `43871a003aa09645d059ea747fbb9c87e12c6f28`, `rebalance_date=2026-06-24`. Four securities (TKR, AMD, AMAT, WDC), PEG and forward PE 4/4, FY1/FY2 observations 0/4, `roic_approx` 0/4, FCF amount/yield fields 4/4. `forward_pe_source`: one `ep_ttm`, three `finnhub`; this repository's producer assigns `finnhub` to the TTM fallback, so all four are labeled trailing P/E masquerading as forward. Some high/low PEG figures should **not** be interpreted as cheap/expensive without source identity.

Derived subsets in `evidence/` and frozen smoke fixtures are **reduced-column extracts**, not original repository Git blobs. Their SHA-256 values cover those derived CSVs only; upstream original Git blob SHA1 is recorded separately. Source authenticity/PIT not proven by this script.

## 3. Implemented code and use

`tools/audit_valuation_provenance_shadow.py`: read-only command accepting scored/portfolio CSV, optionally pinned SHA256 and a date cutoff. Accepts no API keys, never calls a provider, and never writes original files. It emits observed legacy PEG, P/E, ROIC-approx/FCF presence and strict uncertainty labels. **Forward PEG V2 is deliberately null** because snapshot numeric values cannot prove `issuer/security/fiscal_period/accounting_basis/availability/ADR`. Actual forecast data must go through `tools/earnings_consensus_h1.py`, real source byte readback and H2 admission first.

```bash
python -B tools/audit_valuation_provenance_shadow.py \
  --input-csv cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_portfolio_latest.csv \
  --cutoff-date 2026-06-24 \
  > outputs/us_valuation_audit/concentrated.json
```

**Note:** The output redirect above is an explicit analyst-owned research report path, not a trusted collector or automatic publication. Execute only on a reviewed local repository. Do not use this CLI to approve an economic trade or time travel. A source hash may be added with `--expected-sha256`, whose value must be recomputed from actual input bytes.

Local test command:
```
python -B -m unittest discover -s tests -p valuation_provenance_shadow_smoke.py -v
python -B -O -m unittest discover -s tests -p valuation_provenance_shadow_smoke.py -v
```
Historical author-local coverage for the original draft was 43/43 normal and 43/43 optimized. Both runs tested reduced archived subsets + malformed/invalid/missing/future/corrupt checksum and CLI cases. **This is author-local testing, not independent A6.**

## 4. Native patch requirements

Native patch includes ONLY: `tools/audit_valuation_provenance_shadow.py`, `tests/valuation_provenance_shadow_smoke.py`, `tests/fixtures/valuation_provenance/{main,concentrated}_*.csv`, `docs/US_ACTUAL_FIRST_VALUATION_H1_KO.md`, and a narrow existing A3 `load_tests` hook in `tests/a3_candidate_packet_v1_smoke.py`. Do not modify `tools/run_pr_validation.py`, broker, protected workflow, source pointers or scoring features.

1. Recheck live master/Issue#448/Issue#590 A1 lane and PR#593 post-merge owner release, `AGENTS.md` and current Native worktree `git status/diff`; do NOT create additional worktree or remote content-API writes.
2. Apply after owner release, only to approved Native workspace. Verify any overlapping smoke hook/candidate research already merged and adapt context without removing existing tests.
3. Native normal/-O test, targeted registered Tier-1 smoke, current-head CI, independent A6 exact-head, final review and expected-head merge according to approved contract. Any future changed source blob needs re-review. Do not call a partial unit test `CI_PASS`.
4. Next H1 source family: actual FY1/FY2/GAAP-NONGAAP PEG research snapshots via existing `earnings_consensus_h1`; no mixed basis, no guessed publication time, no mandatory absent vendor fill. Real 8Q SEC from existing A1 and historical price generation are separate blocked dependencies.
5. Independent economic H2: pre-register Control unchanged vs H1 evidence-only vs validated native-PEG/actual-ROIC Challenger, required real R0 parity, G0 PIT eligibility, 21/63/126/252 NYSE sessions, missed-winner/false-positive/entry/upside-capture, net-cost CAGR/MDD. No old holdout retune.

**Stop conditions:** Missing exact input source, stale/missing 8Q publisher timing, conflicting GAAP vs NonGAAP, incompatible FY period, failed/unknown license or SHA, active competing writer, or a needed protected gate change.


## 5. Current-master H1 integration — 2026-10-14 KST

Base: `b5021d49bd6aa428b18a13fcf7d8044786c1f4b5`. The archived CSV classifier
always closes `current_valuation_comparison_allowed`; numeric observations alone
cannot authorize present valuation comparison. Ranking and ER authority stay closed.

Malformed CSV headers and data rows both reject through AuditInputError with
`CSV_PARSING_FAILURE`. The CLI emits a structured BLOCKED result and exit code 2
instead of an unhandled CSV parser traceback.

Reuse the already registered `structural.a3_candidate_packet_v1` route through its
existing unittest `load_tests` function, retaining all RegistryTests. No change to
`tests/smoke_test.py`, `tools/run_pr_validation.py`, workflows or protected pins.
The current `tests/smoke_test.py` accepts `--quick` and `--verbose`, not `--only`.

Proportionate local commands in an authorized Native checkout:

```bash
python -B tests/a3_candidate_packet_v1_smoke.py
python -B -O tests/a3_candidate_packet_v1_smoke.py
python -B tools/run_pr_validation.py --include a3_candidate_packet_v1_smoke --only a3_candidate_packet_v1_smoke --only agent_shared_lessons_contract_smoke --only run287_agent_github_operating_standard_smoke
git diff --check
```

The integrated A3 entrypoint contains 92 existing A3/Registry tests plus 60
valuation-audit tests. Counts represent unique cases, not reruns.
These local tests and scoped PR-runner checks do not replace required GitHub CI
or independently supplied exact-head A6 review. Shared tests and lessons use the
user-approved single Main lane. The separate source-review shadow draft is not
included in this H1 audit PR. No production score or investment-consumption path
is changed by the diagnostic tool.

Final-review input corrections normalize missing P/E source markers to unknown,
validate every supplied observation date independently of an optional cutoff,
and distinguish missing/nonpositive P/E from present forward-PEG inputs.
Observation-date errors use `BAD_OBSERVATION_DATE`; invalid cutoff arguments
retain `BAD_DECISION_CUTOFF_DATE`. Missing dates stay missing.

The CLI checks the opened file size before allocating its payload, then reads at
most 20,000,001 bytes to detect growth beyond the 20,000,000-byte budget.
Empty/oversize inputs return `INPUT_BYTE_BUDGET_OR_EMPTY`; OS read failures return
`INPUT_READ_FAILURE` without a private path or raw exception text. These remain
diagnostic refusals with all economic authority closed.

The 5,000-row budget covers all parsed data rows, including excluded CASH rows.
P/E source labels follow this repository's legacy producer: `finnhub` denotes
the known TTM fallback, not an unspecified provider basis. `fcf_ttm` amount and
`fcfy_ttm` yield retain separate numeric observations, statuses and presence
counts; yield presence does not manufacture a cash-flow amount or source proof.
