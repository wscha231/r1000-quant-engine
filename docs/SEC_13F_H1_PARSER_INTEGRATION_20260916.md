# SEC 13F H1 Parser Integration — 2026-09-16

Status: `RESEARCH_ONLY` / parser-integrity fix only.

## Scope

Base master observed before this change: `bcb14c06613e34420ce7988e5bb1ac5547b22b57`.
Branch: `chatgpt/h1-13f-parser-integration-20260916`.
Parent research: #432. Implementation tracking: #434.

This slice connects strict raw-information-table integrity checks directly to the existing `tools/run_sec_13f_parser.py` path. It does not implement H2 manager ranking/replacement, manager-alpha backtests, universe promotion, portfolio targets, broker/paper mutations, or production activation.

## Before / after

Before:
- malformed or missing required numeric values could be coerced to `0.0`;
- a filing parse failure could be encoded as a pseudo holding with `issuer_name = PARSE_ERROR: ...`;
- numeric output normalization could fill missing values with zero.

After this slice:
- required quantities and values reject missing, malformed, non-finite, negative, badly grouped, precision-losing, overflow or underflow-like inputs instead of inventing zero;
- optional voting-authority fields may remain null while an explicit numeric zero stays zero;
- raw XML row count, security/reporting context, shares and reported value are checked before downstream lossy processing;
- cash/CALL/PUT, title of class, share type and repeated `otherManager` relationships are preserved in the transport key;
- a failed requested filing raises a batch error and blocks partial publication; no pseudo holding is emitted;
- empty parse results are blocked rather than replacing a prior successful snapshot;
- raw row id, raw shares/value strings, raw XML SHA and parse evidence id are retained;
- the historical date-based 13F dollar multiplier remains explicitly `UNVERIFIED_LEGACY_DATE_RULE`; this change does not certify the filing's economic value units.

## Validation evidence

The pre-integration #432 candidate package had 142 unique synthetic/offline tests passing in normal and Python `-O` modes; those are not counted twice.

The new parser-integration suite contains 47 cases. In the chat execution environment, 44 passed and 3 real Parquet round-trip/preservation cases could not run because neither `pyarrow` nor `fastparquet` was installed. Those three tests were not skipped, weakened, or replaced by a fake backend. The repository CI environment must run them with repository dependencies.

The existing `tests/sec_13f_parser_smoke.py` is already part of `tools/run_pr_validation.py`. It now invokes the new H1 integration suite, so the additional contract is exercised by the existing PR validation path rather than by an unregistered side test.

## Explicit non-claims / remaining work

This slice does **not** validate or complete:
- 13F cover totals, 13F-NT to 13F-HR reporting-scope/economic-manager relationships;
- definitive value-unit semantics or removal of the legacy date rule;
- stock splits, ADR ratios and other corporate-action-normalized quarter-to-quarter deltas;
- downstream signal keys that can still collapse equity/CALL/PUT/share-class rows if they deduplicate only by ticker;
- R1000 + ADR + validated Form 4/13F unified membership reasons;
- propagation of newly discovered securities through price/fundamental/estimate collection into the actual stock evaluator;
- historical post-disclosure clone accounts, H2 manager scores, manager replacement, CAGR/MDD or portfolio impact.

These must remain separate follow-up changes. Parsing integrity is necessary evidence hygiene, not an investment signal or portfolio decision.

## Safety

No fullrun, production, live trading, automatic portfolio/manager activation, accepted Drive ledger mutation, paper/broker order, target publication or champion promotion is part of this change.
