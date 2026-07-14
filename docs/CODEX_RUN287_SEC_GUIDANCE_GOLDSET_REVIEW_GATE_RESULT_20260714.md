# Run287 SEC guidance gold-set review gate result — 2026-07-14

## Decision

The bounded SEC management-guidance heuristic is closed at its preregistered
source precision gate.

- status: `CLOSED_SOURCE_PRECISION_OR_RECALL_GATE`;
- filing reviews completed: `80/80` by each of two independent reviewers;
- filing-level agreement: `77/80` (`96.25%`);
- adjudicated TP / FP / TN / FN: `13 / 3 / 61 / 1`;
- adjudicated precision: `81.25%`, below the fixed `90%` minimum;
- adjudicated recall: `92.86%`, above the fixed `80%` minimum;
- unreadable frozen packet rows: `2`;
- component adjudication: `NOT_RUN_EARLY_STOP`;
- deterministic parser and 45-name archive expansion: blocked.

No price, return, portfolio, or other outcome label was available to either
reviewer or the adjudicator. No A/B, fullrun, production, live trading, or
automatic order ran.

## Independent reviews

Reviewer A classified 12 true guidance, four false positives, 63 no-guidance,
and one unreadable filing. This produced 75% heuristic precision and 100%
recall.

Reviewer B classified 14 true guidance, three false positives, 61 no-guidance,
and two unreadable filings. This produced 81.25% heuristic precision and
92.86% recall.

Both reviewers validated all 80 manifest IDs independently. They did not read
one another's labels. Their frozen filing-label hashes are:

| Review | SHA-256 |
|---|---|
| Reviewer A | `915764b2ada70b3835133564af4e165c6afce2b43093c4743f368f8514d01b4f` |
| Reviewer B | `14d02d7fc471f1f3291ab275f0d5c653a25858ac1c6aa0a6199267dffd536762` |

## Filing adjudication

Three filing-level disagreements were resolved against the frozen source text:

1. NVS accession `0001114448-26-000007` is `TRUE_GUIDANCE/TP`. It explicitly
   reaffirms numeric 5–6% five-year sales CAGR guidance for 2025–2030; sales is
   the registered revenue metric.
2. NVS accession `0001114448-26-000008` is `UNREADABLE`. Its allowed annual-
   report attachment is a uuencoded PDF payload and cannot be judged from the
   frozen review text.
3. TPL accession `0001811074-26-000033` is `TRUE_GUIDANCE/FN`. The issuer
   presentation gives conditional FY2026–2035 potential renewal revenue above
   $250 million with explicit assumptions. It is an initial long-horizon
   revenue outlook, not comparable prior guidance.

The adjudication file hash is
`2d921b42230733552eb18de8f719c30a64e5e59378f07c82b05fd0b48574ceec`.

## False positives and false negative

The three adjudicated false positives are materially different from registered
numeric EPS/revenue guidance:

- one NVS qualitative low-single-digit statement whose nearby reported-period
  numbers do not form a registered numeric guidance value/range;
- RIO physical-volume/unit-cost material that is not EPS or revenue guidance;
- VZ estimated transaction-loss, expense-impact, and EBITDA-accretion text
  that is not eligible forward EPS or revenue guidance.

The TPL long-horizon conditional revenue outlook is the single false negative.
This is not permission to add a special-case keyword or threshold after seeing
the result.

## Early-stop rationale

Precision and recall are mandatory conjunctive gates. Precision failed before
component-level schema completeness could authorize downstream work. The
evaluation therefore deliberately did not reconcile the reviewers' component
rows and did not build or tune a deterministic parser.

Expanding the same heuristic to 45 active names, inspecting market outcomes,
or adding rules to rescue these known rows would violate the fixed endpoint
and no-retuning contract. A future lane would require genuinely different
signal semantics or materially improved source coverage and a new blind set.

## Frozen hashes

| Evidence | SHA-256 |
|---|---|
| Gold-set contract | `3e017f5a71cf3fd349909c4369db5f7555bf4d52643b80ac4c157a2790d5c3fb` |
| Review manifest | `8273d2116c27269ab57365557bc9b27ef36e5d2629944c6e52a87aa050717a7d` |
| Adjudicated filing labels | `8a922cafe4c2dc74684ab9f0199de22e08cb0c2dcdc15ca246cfa08d2c79c382` |
| Filing disagreements | `65128a43f94f3d63563409a6ee73ca6c35aff18cedf426a87d8fd0e8e195df0c` |

## Evidence files

- `docs/run287_sec_guidance_goldset_contract.json`
- `docs/run287_sec_guidance_goldset_adjudication.csv`
- `tools/evaluate_sec_guidance_goldset_reviews.py`
- `tests/sec_guidance_goldset_review_gate_smoke.py`
- `outputs/run287_sec_guidance_goldset_packet_20260714/`
- `outputs/run287_sec_guidance_goldset_review_gate_20260714/`
