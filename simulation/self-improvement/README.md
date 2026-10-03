# Shadow-only paper self-improvement

This layer proposes **new, immutable score-cutoff versions** of the pinned
momentum boosting study and measures them in independent shadow paper accounts.
It does not train or replace `momentum-boost/model.json`, rewrite any existing
ledger/account/replay, change `defaultCryptoProfile`, or place real orders.
`promotion_candidate` means **eligible for a separate human review only**.
There is no promotion command, operating-account writer, or exchange order client.

## Verified starting point

- [e9865cb](https://github.com/bumblev95/S-P-500-/commit/e9865cb77b5790ba7f2a12ef79930a715222b92c):
  `ml/adaptive-summary.json`, generated 2026-10-01, selects 126-day
  `regimeBlend` but has `passed=false`, `average=false`, `consistency=false`,
  `direction=false`, `improvementVsOriginal=-0.0019327440312792987`, and
  `liveForecastChanged=false`. The 252-day comparison is `insufficient` because
  independent post-correction validation dates are missing. These are forecast
  research diagnostics, not trading eligibility or paper returns.
- [6c537be](https://github.com/bumblev95/S-P-500-/commit/6c537be0d4615aefff7706f034b8410569c217dc):
  95 hash-linked decision records; the cited
  `1790835023912-55292d4a88c7.json` records BTC/ETH/SOL with
  `modelPassed=true`, `breakoutPassed=false`, and `side=null`.
  Only 2 closed trades exist in each one-position arm, and 5 in the three-position
  control. The current study cannot satisfy the gates below.
- Pinned model SHA256 remains
  `eb059abb6a4b5a6cbf05d1bb2db5f1e89cffae99e7b76579ac25edbd6254c025`;
  ID `momentum14-breakout3-boost-2026-frozen-v1`; incumbent cutoff 0.10 R.
  The existing `simulation/README.md` no-retraining/no-reset/no-live-promotion
  policy remains in force.

## Inputs and immutable storage

`scripts/shadow_evidence.cjs` reads all three pinned study ledger chains and
the decision chain. It checks the original insertion-order JSON SHA256,
`previousHash`, chronological filenames, model/profile identity, and head
agreement with the existing state/experiment files. A closed trade's authoritative
entry/exit prices, quantity and **net P&L** come from hashed ledger events.
The signal must have a causal, originally recorded decision, and the mutable
state's trade projection must agree with those events.

The old ledger does not separately hash every full trade's funding or final
trailing-stop field. The adapter therefore does **not** call mutable state fields
immutable training labels. It derives initial risk and fee/slippage diagnostics
from the hashed entry/exit events and the frozen execution policy; the residual
`fundingAndAdjustmentResidual` is explicitly not a claim of exact funding.
No outcome is invented for rejected, cancelled or unfilled historical signals.

Each registration anchors immutable source **file-byte hashes**, chain heads,
verified closed labels, adaptive context, the source git revision, policy and
execution-code hashes. Subsequent runs require every previously anchored source
file to remain present and unchanged, even if someone recomputes a valid chain.
New shadow records store only newly anchored file hashes plus a complete manifest
digest, and additionally hash full new closed trades, events, 15-minute curves
and continuation state. Account histories are reconstructed from these
append-only deltas; no mutable `state.json` or `latest.json` is maintained here.

```
simulation/self-improvement/versions/<new-version>/
  candidate.json                     # immutable parameters, policy and inputs
  observations/<time>-<hash>.json     # paired account deltas, hash linked
  assessments/<time>-<hash>.json      # immutable gate results
```

Candidate creation publishes its descriptor and paired $10,000 cash genesis
together. Missing/truncated observations, changed pinned models, candidate
tampering, or changed execution code stop that version; they never recreate or
migrate its balances. Files are created without overwriting existing paths.
After an execution-code change, explicitly register a new version and update its
ID. An all-versions update reports incompatible versions as blocked while still
processing compatible ones, and exits nonzero to expose every blocked version.

## Proposal and matched forward experiment

The implemented proposal family is deliberately narrow: raise the fixed model's
score cutoff above 0.10 R, initially 0.15 R. A different cutoff is a new version.
It does not search for an historical winning model or retune on the test sample.
Breakout confirmation, symbol ranking, one-position limit, stops, reversal exits,
30-day maximum hold, leverage, fees, funding and risk controls use the unchanged
paper engine. Arbitrary new model training/import is not implemented; that would
require another explicit versioned workflow and validation.

The new cutoff and fresh incumbent shadow account start from equal capital,
without importing old positions, balances, replay profits or backdated trades.
Their whole shared forward period is compared, including cash, losing trades,
skipped signals, pending orders and cancellations. Comparing only the intersection
of winning closed trades is prohibited. Waiting before the first actual run does
not count toward the minimum forward duration.

New entries and stop/reversal instructions require a fresh verified original
decision. Its score, price, breakout fields and feature readiness must reproduce
from the completed market bars. Missing/mismatched observations block new
instructions. Existing orders/positions settle through the original engine;
catch-up never invents unrecorded intermediate signals. All changes apply at the
shadow run's actual recording time. A passing model score cannot bypass breakout.

The independent `Shadow paper self-improvement` workflow runs **after a successful
public-paper update**. It updates already registered shadow versions and stages
only additions under this directory's `versions/`, plus the disposable website
status projection described below. No existing workflow, operating account
publisher or UI default is modified. New candidate registration requires
the workflow's explicit `register` action; no automatic retraining occurs.

## Read-only website status

Open `simulation.html#shadowImprovementApp`, or use its **자기개선 상태** link.
The panel is separate from the selected paper account and its forward/replay tab.
It shows every registered version, paired sample counts, actual shared forward
days, all eight gates, and same-period cost/risk metrics. Missing, blocked and
delayed data have explicit labels. Green **사람 검토 후보** appears only for a
verified, fresh all-gates pass. It is never an approval or trading action.

`scripts/build_shadow_status.cjs` verifies candidate/runtime identity, observation
chains and source-byte checkpoints. It checks assessment hashes and their exact
observation heads, then independently recomputes the reported gates. A missing
latest assessment, changed runtime, tampering or incomplete registry produces
blocked status instead of keeping an old successful result. Registration-only
versions remain **첫 수집 대기**, with zero forward duration; registration waiting
time is never counted as an experiment. The current initial 2-label pool remains
visible as a first-window training shortfall.

`simulation/self-improvement/status.json` is a **mutable, disposable display
projection**, unlike the immutable candidates, observations and assessments.
Neither the paper nor shadow engine reads it. Rebuilding it cannot register,
execute, assess, reset, promote or change an account. The website only fetches
this file and links to the underlying immutable records. Data older than 30 minutes
(either the display projection or observation assessment) is labelled delayed,
and cannot be presented as a current promotion candidate. Gate badges in a delayed
snapshot explicitly describe the last evaluation. The independent 126/252-day
forecast diagnostics have their own timestamp and never enter the trading score.
An open page expires the eligibility badge on time and refetches only the display
file every five minutes; version switching and refreshing never execute a trade.

The shadow workflow builds and publishes status even after a blocked collector
run, then leaves that workflow failed so the error remains visible. The staging
guard permits **new** version artifacts plus additions/modifications of this one
display file; edits/deletions of prior version artifacts remain forbidden. A
successful status commit requests a GitHub Pages rebuild. Collection and live
website publication start only after this feature is merged to `main`.

Reproduce without advancing any account:

```bash
node scripts/test_shadow_improvement.cjs
node scripts/test_shadow_status.cjs
node scripts/build_shadow_status.cjs
python -m http.server 8788
# Open http://localhost:8788/simulation.html#shadowImprovementApp
git diff -- simulation/self-improvement/status.json
```

Only the display file changes when running the builder. The regression suite uses
private copies to test corrupted/missing records, changed runtimes, stale/future
timestamps, all-pass/rejected/insufficient states, version switching, safe links,
request failures, forecast separation and unchanged operating/immutable files.

## Promotion screen v1

All conditions must be true simultaneously. Missing data or nonfinite economics
cannot pass. Results retain each failed gate and the underlying counts/metrics.

| Gate | Frozen requirement |
|---|---|
| Immutable evidence | Verified complete hash chains; old file-byte checkpoints unchanged; candidate and execution hashes fixed |
| Complete data | No decision mismatch, stale/missing/revised/gapped execution inputs, estimated funding or incomplete shadow execution anywhere in the version |
| Matched forward sample | Equal fresh capital/start, identical full curve timestamps, chronological paired observations, no pre-registration orders |
| Minimum sample | **100 closed trades in each arm**, **30 distinct entry dates in each arm**, and **90 days** since their actual first shared run |
| Purged walk-forward | At least **3 completed fixed 30-day windows**; every window passes. Expanding reference-label pool has at least **30 trades on 10 dates**, all published/exited more than **24 hours before** that test window. Simultaneous signal groups stay together. Boundary-crossing or not-yet-published test labels are purged. Each arm needs **20 completed test trades per window**; the candidate's base/stressed net P&L is positive and improves on the incumbent in every window |
| Cost-included improvement | Candidate's closed and marked returns positive and at least **0.5 percentage points** above incumbent; higher mean net R; doubled fee/slippage surcharge remains positive, improves return by 0.5 pp, and improves mean net R |
| Drawdown | Full 15-minute mark-to-market maximum drawdown no worse than incumbent and at most **10%** |
| Risk | No increase in maximum gross exposure/equity, initial open-risk/equity, entry risk/notional ratios, concurrent positions, observed leverage, daily volatility, worst daily loss or 5% daily tail loss; one-position cap; no isolated-loss adjustment, estimated funding, drawdown halt or incomplete execution |

Windows are anchored to the first shared run, not repartitioned after inspecting
results. There is no test-window refitting. The current 2-label starting pool will
fail the first window's training-size condition: collecting more later does not
rewrite that first result. A later proposal can be explicitly registered as a new
version with the now-larger immutable starting pool. This conservative rule
prevents erasing an insufficient or unsuccessful early experiment.

Net P&L already includes paid fees, funding and price-embedded slippage. Stress
subtracts only **additional** fees/slippage on recorded fills, keeping funding.
It is a conservative cost diagnostic, not a full counterfactual resimulation of
different sizing, fills or funding. Marked returns include open-position costs;
closed-trade improvements must also pass independently. Equity must reconcile
against initial capital, closed net and open-position net marks.

Entry risk/notional ratios include intrabar round trips and use preceding
bar-close equity because exact intrabar mark-price equity is unavailable.
Bar-close drawdown and approximate funding-mark prices inherit the original
engine's limits; intrabar risk can be larger. Current BTC/ETH/SOL selection and
multiple separately registered proposals create selection/multiple-testing risk.
Passing is a review candidate, not proof of future profitability or permission
to trade. Separate approval and additional research remain necessary for any
operating or real-trading change.

## Offline reproduction (Node 22+, git; no new package dependencies)

From a clean checkout containing this change:

```sh
node scripts/shadow_improvement.cjs audit
node scripts/test_shadow_improvement.cjs
node scripts/test_paper_engine.cjs
node scripts/test_momentum_boost.cjs
node scripts/test_boost_risk4.cjs
```

Tests use disposable synthetic git repositories/accounts, not real account
rewrites. They cover successful synthetic screening **without deployment**,
failures of all mandatory gates, fees, risk regressions, publication-time leakage,
embargo, grouped signals, fixed fold boundaries, hash tampering/truncation,
rehashed-source rewrites, immutable closes, model/runtime locks, missing-state
restoration, entry timing, decision reproduction and original-file preservation.
Synthetic successes are not recorded as user trading observations.

To explicitly register a fresh research version locally (writes only new shadow
files), then use the returned version ID:

```sh
node scripts/shadow_improvement.cjs register --threshold-r 0.15
node scripts/shadow_improvement.cjs update --version <returned-version>
node scripts/shadow_improvement.cjs assess --version <returned-version>
```

For recurring collection, dispatch the workflow's `register` action or retain the
initial checked-in version; successful future paper updates then collect paired
shadow observations. `assess` writes only a new content-addressed assessment and
never reruns or resets accounts. Same-time, identical-input updates are idempotent.
Altered inputs at the same observation time fail closed. There is intentionally
no `promote`, `reset`, `retrain`, `overwrite`, or lower-gates CLI option.

Implementation: `shadow_evidence.cjs`, `shadow_improvement.cjs`,
`shadow_gates.cjs`; tests: `test_shadow_improvement.cjs`.
