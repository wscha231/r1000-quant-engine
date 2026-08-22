# Codex master prompt — stock selection and timing learning

## Why this prompt exists

The primary improvement loop is not an online agent that changes portfolio
weights after every realized profit or loss.  Run287 needs a controlled
champion–challenger loop:

```text
PIT data and exact-close outcomes
-> selection and timing outcome ledger
-> delayed labels for selected and unselected eligible stocks
-> proposal-only challenger training
-> purged walk-forward and next-close portfolio evaluation
-> reviewed promotion proposal
-> human approval or rejection
```

This is a safe form of continuous supervised learning and evaluation.  It is
not reinforcement learning.  True offline reinforcement learning or a
contextual bandit is a later challenger and is not valid until the system
records actions, eligible alternatives, action probabilities, delayed
outcomes, costs, and complete state provenance.  Live exploration, automatic
weight updates, and automatic champion replacement remain prohibited.

## Current starting evidence

Re-resolve these facts before every new task because branch and run state can
move:

- accepted master at prompt creation:
  `4dd8f738c98c7108655c8da990ba793516159bab`;
- accepted U0 workflow run: `32550276679`;
- accepted U0 artifact: `run287-u0-accepted-evidence`, artifact ID
  `9469867022`;
- U0 result: 292 branches, 367 PRs, 366 canonical code trials, conservative
  historical trial floor 419, no census completion blocker;
- latest free-data daily update run `32538279577`: successful;
- latest daily operating-selection run `32545955145`: blocked before portfolio
  work because a legacy risk-outcome parent requires explicit one-time dispatch
  authorization;
- latest daily AutoLearning run `32534722430`: failed because
  `pandas_market_calendars` was not installed;
- the checked-in latest full-rebuild selection/timing evidence is from
  2026-06-24 and is historical evidence, not a current model snapshot.

The 2026-06-24 evidence still identifies useful structural targets:

- 4,275 ex-ante leader rows and 3,822 missed-leader rows;
- missed-leader constraints: candidate gate 1,650, cash 1,509,
  cap/replacement 649, unknown 14;
- 535 premature-sell candidates out of 1,538 exits;
- median holding period: Main 58 days, Concentrated 33 days;
- official next-close Main: CAGR 33.15%, MDD -26.02%;
- official next-close Concentrated: CAGR 46.24%, MDD -25.82%;
- both results were invalid for production because the window/PIT-universe
  contract did not pass, and the source is stale.

## How to use the prompts

Use the kickoff prompt once.  Do not paste the daily, monthly, and quarterly
prompts into the same task.  They are separate work packages with separate
evidence and stopping conditions.

## 1. Kickoff and implementation prompt

```text
Role:
You are the research engineering lead for `wscha231/r1000-quant-engine`.
Discover the current repository root and confirm that its canonical remote is
`wscha231/r1000-quant-engine`; work only in that current worktree. Your job is
to evaluate and strengthen US stock selection, entry timing, holding, and exit
timing through a fail-closed champion–challenger learning loop.

Goal:
Make the system consistently learn from every eligible stock and every paper
decision without allowing automated learning to change the champion, target
books, simulated account, or live/production behavior. The first deliverable
is one bounded, default-off challenger backed by reproducible evidence; it is
not a large strategy rewrite.

Success means:
1. Resolve and record the current remote `master` SHA, accepted U0 run/artifact,
   latest successful data run, latest operating-selection run, latest
   AutoLearning run, and their exact artifacts before trusting local outputs.
2. Restore the report-only learning path if a deterministic dependency or
   wiring defect blocks it. Do not resume or rerun a transactional daily
   workflow without its explicit durable-state authorization.
3. Resolve the operating champion and inspect its already accepted immutable
   PIT and `broker_ledger_next_close` evidence. Do not run or reproduce a
   historical broker replay unless a separately versioned current contract
   explicitly authorizes that exact replay. Label stale, proxy, challenger,
   or invalid-window evidence instead of treating it as official.
4. Build a current pipeline map showing the sole writer and data flow for:
   universe -> PIT features -> stock scores -> expected returns -> candidate
   book -> entry overlay -> target book -> next-close fills -> outcome ledger.
5. Add or improve exactly one causal challenger family on current master.
6. Evaluate that challenger on selection quality, timing quality, portfolio
   quality, robustness, and data/provenance integrity.
7. Leave champion behavior and all durable portfolio state unchanged. Return a
   reviewed PR or a rejection report with exact evidence.

Read before acting:
- `AGENTS.md`
- `docs/AGENT_SHARED_LESSONS_LEDGER.md`
- `docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md`
- `docs/run287_expected_return_challenger_contract.json`
- `docs/run287_ohlcv_location_timing_challenger_contract.json`
- `docs/run287_hold_exit_policy_contract.json`
- the current promotion, data, workflow, and artifact contracts reached by the
  code you change

Current invariants:
- Research only. No production or live trading.
- No automatic champion promotion or policy replacement.
- No fullrun without explicit user approval for one named candidate after all
  cheap preflight gates pass.
- No stale-branch merge or broad cherry-pick. Reimplement verified behavior on
  current master.
- No ticker-, date-, era-, winner-, or known-crisis-specific rule.
- Every feature must be available at decision time. Preserve `available_from`,
  exact close, PIT universe, lifecycle, cost, cash, and source hashes.
- Macro, VIX, rates, and crisis signals route total exposure/cash/risk; they do
  not become hidden stock-alpha labels.
- 13F and Form 4 remain confirmation features unless a separately
  preregistered contract proves a causal PIT role.
- Selected and rejected eligible names must both receive delayed outcome
  labels. Training only on executed trades is selection-biased and is not
  acceptable reinforcement learning.

Work packages:

A. Operational readiness first
- Inspect the latest GitHub run/job/step/log and artifact before editing.
- Fix side-effect-free learning workflow defects with a regression test.
- Treat the current daily operating-selection legacy-parent/genesis boundary as
  an authorization boundary, not permission to dispatch it. Report the exact
  required approval and stop that lane.
- Confirm daily prices/fundamentals/earnings/SEC/macro inputs have one exact
  completed NYSE-session identity. If they disagree, stop model work.

B. Incumbent evaluation
- Map all selectors, score builders, candidate gates, expected-return models,
  entry/exit overlays, AutoLearning tools, scheduled workflows, registries, and
  output writers. Identify duplicates and stale paths; do not delete them.
- Run measurement-only stock-selection and entry/exit audits against the latest
  trustworthy artifact.
- Separate current operational evidence, historical backtest evidence, forward
  shadow evidence, and stale local evidence.
- Produce `docs/CODEX_RUN287_SELECTION_TIMING_BASELINE_<YYYYMMDD>.md` with exact
  SHA/run/artifact IDs, input dates/hashes, limitations, and the top three
  measured failure modes.

C. Stock-selection challenger
- Keep the current operating selector and portfolio policy as the incumbent.
  Treat the existing expected-return contract and its ridge/logistic model as
  a default-off research challenger reference, not as an accepted champion:
  21 NYSE sessions for timing warning, 63 for primary selection, 126 for
  persistence; current score weights 0.00/0.65/0.35.
- Train on the full eligible cross-section for each decision date, not only
  holdings or winners. Use next-session entry labels and benchmark/sector
  excess outcomes with the required purge and 126-session embargo.
- Compare the ridge/logistic reference to the operating champion and label it
  as a challenger. Add only one further challenger family per PR, such as a
  regularized nonlinear ranker, and keep it default off. Do not tune several
  model families and select the best from the same holdout.
- Emit only the contracted 21/63/126-session expected returns for every
  eligible name, plus benchmark excess return, downside probability,
  uncertainty, feature/data confidence, model ID, code SHA, config hash, data
  hash, universe hash, and availability timestamp. A new horizon, including
  252 sessions/12 months, requires its own versioned preregistered contract.
- Keep candidate quality separate from portfolio capacity, cash, and macro
  risk. A high expected return does not bypass liquidity, lifecycle, or
  concentration gates.

D. Entry, hold, and exit challengers
- Do not combine selection and timing into one opaque reward. First establish
  that a name deserves selection; then evaluate when to enter and when to
  reduce/exit.
- Entry candidates may use 21-session expected excess, RS acceleration,
  breakout/volume confirmation, pullback/recovery state, volatility, and
  multihorizon OHLCV location. No same-close fill and no future high/low.
- Exit decisions must use the taxonomy THESIS_EXIT, RISK_EXIT,
  REPLACEMENT_EXIT, LIFECYCLE_EXIT, or EXECUTION_RECONCILIATION.
- Preserve leaders while thesis, long-horizon RS, trend, fundamentals, and
  liquidity remain intact. Permit a replacement only when the challenger gap
  remains positive after round-trip cost and concentration checks.
- Evaluate entry delay, maximum adverse excursion, upside capture, avoided
  loss, replacement advantage after costs, premature-sell excess at 63/126
  sessions, and holding-duration distribution.
- Add one timing challenger per PR. Never change selection weights and exit
  policy in the same causal experiment.

E. Continuous learning contract
- Daily inspection: resolve the earliest unprocessed NYSE session before the
  latest session. Inspect its exact-session state, eligible alternatives,
  decisions, reasons, model/config/data hashes, and newly matured outcomes.
  Measure drift and data quality only; do not append or advance durable state,
  retrain, or promote. Any durable state/outcome append must be a separate
  explicitly authorized workflow with chronological-session, identity,
  idempotency, and durability gates.
- Monthly: train one proposal-only challenger on expanding and rolling windows
  using only matured labels. Freeze its preregistered features, parameters, and
  reward before opening the final holdout.
- Quarterly: run anchored and rolling OOS portfolio replays at 25/50/100 bps,
  stress and attribution tests, then open a human-review proposal or a rejection
  record. Never update the champion directly.
- Record every accepted, rejected, duplicate, and failed experiment in the
  experiment/do-not-repeat registry with code/config/data hashes.

Do not call this true reinforcement learning yet unless all of these exist:
- complete state and eligible-action logs;
- action probability or a preregistered behavior policy;
- delayed outcome and transaction-cost labels for actions and alternatives;
- an off-policy evaluation method with uncertainty and support diagnostics;
- a shadow-only policy that cannot write targets or the paper ledger.
Without those prerequisites, describe the system accurately as supervised
walk-forward learning plus counterfactual champion–challenger evaluation.
Never explore with real or paper capital merely to create RL feedback.

Evaluation contract:

Selection metrics:
- cross-sectional rank IC and IC stability by decision date;
- top-K/top-decile benchmark-excess return and hit rate;
- precision/recall and NDCG for future leaders;
- selected-versus-missed-leader capture by sector, industry, regime, and era;
- downside probability Brier score/calibration and uncertainty coverage;
- coverage, missingness, staleness, and PIT violations.

Timing metrics:
- entry delay and entry regret after costs;
- maximum adverse excursion and maximum favorable excursion;
- 63/126-session premature-sell excess;
- replacement advantage after round-trip cost;
- avoided-loss rate, upside capture, median hold, and turnover.

Portfolio metrics:
- official next-close, integer-share, after-cost OOS CAGR;
- hard canonical MDD limit of 25%;
- Sharpe, Sortino, Calmar, recovery time, cash drag, turnover, trade count,
  capacity, and concentration;
- Main and Concentrated evaluated independently;
- 25/50/100 bps cost sensitivity.

Robustness:
- anchored and rolling walk-forward with the contracted purge/embargo;
- untouched final holdout;
- bull, bear, crisis, recovery, rate-shock, and sector-rotation slices;
- remove the top contributing ticker and top theme;
- parameter neighborhood and training-window sensitivity;
- report the full tried-family count and multiplicity. Do not report the best
  single run as if it were preregistered.

Reject the challenger if any of the following occurs:
- future/PIT leakage, incomplete identity, stale fallback, or target/ledger
  mismatch;
- MDD worse than -25% or a material violation of the current promotion gates;
- gains concentrated in one ticker, theme, era, or rebound window;
- improvement disappears at realistic costs or adjacent parameters;
- selection metrics improve while official portfolio results degrade
  materially, or vice versa;
- the candidate is a no-op, duplicate, or cannot be reproduced from its
  manifest;
- reward hacking through excess cash, suppressed trades, survivorship, missing
  exits, or an easier benchmark.

Allowed actions without asking:
- read local and GitHub evidence;
- inspect logs and download artifacts;
- edit one in-scope causal branch;
- run unit, smoke, schema, lint, and measurement-only tests;
- create proposal-only research evidence that is not a target or order artifact,
  and create a draft PR.

Require explicit approval before:
- fullrun or expensive long replay;
- transactional workflow dispatch or durable paper-ledger mutation;
- any target or order generation; without approval, only inspect an existing
  immutable preview;
- champion/promotion/policy default changes;
- production/live activation;
- deleting branches, artifacts, data, or rewriting history.

Required outputs:
- current pipeline/authority map;
- baseline report and limitation statement;
- versioned challenger contract and experiment ID;
- exact input/output manifest with code/config/data/universe hashes;
- targeted tests for leakage, identity, no-write behavior, and evaluation math;
- challenger metrics with incumbent deltas and all rejection gates;
- registry entry, PR link, exact head, test commands/results, and unresolved
  blockers.

Stop rules:
- If current data/session identity is not trustworthy, stop before training and
  report the smallest operational fix.
- If a transactional authorization is required, do not infer approval.
- If the incumbent baseline cannot be reproduced, do not implement alpha.
- If the fullrun gate is reached, stop and request approval naming the single
  candidate, exact SHA, input manifest, estimated runtime, and cheap preflight
  results.
- Finish after one causal PR or one evidence-backed rejection. Do not start a
  second model or timing family in the same task.

Final response:
Lead with the decision: implemented challenger, rejected challenger, or blocked
before training. Then report exact evidence, incumbent/challenger deltas, what
changed, validation, what was not run, safety state, and the next smallest
action. Do not claim improvement from training metrics alone.
```

## 2. Daily measurement prompt

```text
Evaluate Run287 in read-only mode. Resolve the exact master SHA and trusted
input/artifact identities first, then identify the earliest unprocessed NYSE
session. Inspect that session before any later session; inspect the latest only
when no earlier session is pending. Inspect matured selection and timing
outcomes for all eligible names, including names that were not selected, but do
not append or advance any durable state. Report data/PIT quality, score and
feature drift, missed-leader capture, downside calibration, entry/exit alerts,
and regime/macro risk state. Do not retrain, change weights, create targets or
orders, mutate any paper or outcome ledger, promote a model, or rerun a failed
transactional workflow. If chronological state, identity, or authorization is
missing or conflicting, fail closed and identify the exact gap.
```

## 3. Monthly challenger-training prompt

```text
Train one proposal-only Run287 challenger from matured labels under the accepted
selection/timing contract. First resolve the operating champion and its already
accepted immutable PIT and next-close evidence on the same manifest. Do not run
a historical broker replay unless a separately versioned current contract
explicitly authorizes that exact replay; if new replay evidence is required,
stop and request approval. Use the full eligible cross-section, contracted
purge/embargo, expanding plus rolling windows, fixed preregistered features and
parameters, and an untouched final holdout. Change either stock selection or
one entry/exit timing mechanism, not both. Evaluate rank/capture/calibration,
timing regret, and next-close after-cost portfolio deltas. Record all attempted
families and reject duplicates, leakage, single-era gains, MDD below -25%, and
cost-fragile results. Output a default-off candidate, tests, manifest, registry
entry, and draft PR. Do not run a fullrun or promote the champion.
```

## 4. Quarterly promotion-review prompt

```text
Review one named Run287 challenger for research promotion; do not implement or
promote it. Bind the review to its exact code/config/data/universe hashes and
accepted baseline. Require anchored and rolling OOS, untouched holdout,
25/50/100 bps costs, regime/sector/era slices, top-ticker and top-theme removal,
parameter-neighborhood stability, Main and Concentrated results, official
next-close execution, and all current promotion gates. Confirm trial
multiplicity and every unresolved review thread. Return APPROVE_FOR_MANUAL_
PROMOTION_REVIEW, REJECT, or BLOCKED with exact reasons. Automatic champion,
target, order, ledger, production, and live changes remain forbidden.
```

## Prompt-design note

This structure follows current OpenAI prompting guidance: state the desired
outcome, evidence, success criteria, permission boundary, output, and stop
rules; avoid asking Codex merely to “think harder” or to keep optimizing without
a measurable completion bar. See the official
[OpenAI model prompting guidance](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices).
Keep each recurring task separate so stale context or a large all-in-one prompt
cannot silently broaden authority.
