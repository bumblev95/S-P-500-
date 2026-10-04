# Prospective evidence for daily-top3-v1

This research-only study observes the **homepage display policy** introduced by
[PR #35](https://github.com/bumblev95/S-P-500-/pull/35). It does not select stocks,
change thresholds, create orders, estimate account CAGR, or promote a strategy.
It is separate from `entry-context-v1-forward-v1`, which uses a 20-stock universe
and different execution rules. The homepage's eligible universe is used as it
exists at each observation (505 stocks in the first snapshot).

## First operational evidence

Policy merge: `0974763563dd137ccc6dd22631296260edd48e5e`,
2026-10-04 19:53:08 UTC. The study starts with the exact ranking published in
`861c2f0ad86a4d076e9243e0bb02b22f02beccb5`, at **2026-10-04 20:07:32 UTC**.
Its source close date is **2026-10-02**, which is not its observation date.
`initializedAt` and ledger `recordedAt` disclose when the existing public evidence
was imported; `observedAt` uses that operational commit's publication time.

The source home/forecast Git blob IDs are retained. Bootstrap only imports that
one pinned commit; it cannot accept arbitrary historical snapshots or replace an
existing study. No rankings are reconstructed before the policy existed.

| Side | Rank | Symbol | code | holdingCode | selection | Score | Reference close |
| --- | ---: | --- | --- | --- | --- | ---: | ---: |
| buy | 1 | ILMN | breakout | hold | relative | 100 | 273.040009 |
| buy | 2 | RVTY | pullback | hold | relative | 100 | 151.529999 |
| buy | 3 | FTNT | breakout | hold | relative | 99 | 180.949997 |
| sell | 1 | AON | avoid | reduce | signal | 0 | 269.450012 |
| sell | 2 | APP | avoid | reduce | signal | 0 | 268.220001 |
| sell | 3 | CCI | avoid | reduce | signal | 0 | 66.440002 |

The `relative` buy priorities are not actual `buy` signals. Original names,
reasons, order, code, holdingCode, selection, scores, close date and reference
prices are retained without re-evaluating them under newer rules.

## Daily capture and immutability

`simulation/home-top3/daily-top3-v1-prospective-v1/manifest.json` freezes the
study contract and production rule hashes. `ledger/` contains hash-chained
observation and price events, created exclusively and never edited.
`latest.json` is a reproducible derived report, not the source of truth.
CI rejects edits/deletions of an existing manifest or ledger file and verifies
the chain, chronological separation, horizon dates and derived report.

After genesis, the first research capture of each **new source close date**
uses the actual runner timestamp as `observedAt`. Source generation timestamps
are provenance only; they never backdate a late capture. Repeated symbols on
different close dates remain daily cohorts. Multiple hourly refreshes, including
same-date changes and weekends/holidays, keep the first cohort unchanged and
never multiply it. Older source dates are rejected. Missing ranking dates are
reported rather than reconstructed; collection outages reduce the sample.

A separate `Observe prospective homepage TOP 3 research` workflow runs after
homepage workflow completion, hourly at minute 45, and on manual dispatch. It
reads **committed** `market/home.json` and `forecasts/latest.json` and only
stages `simulation/home-top3`. The existing homepage publication workflow and
all production ranking, signal, price and threshold code are unchanged.

Production selector/assessment/technical-rule hash changes stop collection for
this version. Review a new policy/study version rather than silently mixing
rules in the original sample. Study-contract changes also require a new version.

## Causal return windows

The baseline is the **close of the first XNYS session whose open is strictly
after actual observation**. This conservative close-to-close convention avoids
using an unavailable old closing price or a session that already opened.
The October 4 genesis therefore has an October 5 baseline; October 2 prices are
reference inputs only. It also excludes the October 5 open-to-close return.

Horizon targets are exactly baseline **+20** and **+63** XNYS trading sessions
(the baseline is day zero). Calendar `exchange_calendars==4.13.2` is pinned;
holidays, early closes and New York daylight saving time are respected. These
target dates do not slide when the price source misses a bar. Completed bars
require the exchange close plus 15 minutes and non-future source timestamps.

For each original card, on identical baseline and target dates:

```
return       = stock_target_close / stock_baseline_close - 1
spyReturn    = SPY_target_close   / SPY_baseline_close   - 1
excessReturn = return - spyReturn
```

Values are decimal returns (0.01 = 1%); excess return is a percentage-point
difference. Both sides use subsequent **long price returns**. Negative stock
returns or underperformance can support a sell priority; they are not simulated
short profits or realized savings. No trade timing, costs, dividends, taxes,
position sizing, capital allocation or account returns are claimed.

The EOD source supplies Yahoo Close (split-adjusted, dividends excluded). Future
closes for already recorded symbols and SPY are frozen on first ingestion in
price events. Revisions exceeding relative tolerance 1e-6 retain the old value
and quarantine affected windows, including SPY revisions. A split or other
provider restatement cannot silently rewrite prior evidence. This study does
not perform corporate-action reconstruction or total-return accounting.

Only fully completed horizon windows with exact stock endpoints and every
expected SPY session are scored. Unfinished/future horizons return null.
Missing stock endpoints, a missing SPY session or price revisions have separate
statuses. Removed/delisted symbols stay in the denominator; missing endpoints
are not replaced with zero returns or a later available price. A later source
recovery can supply a missing price without replacing the ranking observation.
The observer uses the existing EOD histories; it does not fetch substitute data
for a ticker that disappears from that source.

## Maturity and interpretation

Reports include every cohort, card and pending/missing status. Individual
20-session outcomes mature independently from 63-session outcomes.
Aggregate performance fields stay **null until at least 20 distinct, fully
mature six-card daily cohorts in that group**. This minimum is a fixed reporting
rule, not a statistical significance threshold. A cohort with any missing or
quarantined card is excluded as a whole from both-side aggregates; its rows and
exclusion counts remain visible, preventing partial-day survivor averages.

Within each group, cards are equally weighted per day and days are equally
weighted. The buy/sell summaries and their `selection`, `code`, `holdingCode`
subgroups have their own maturity counts and gates. Mean excess return and
above/below-SPY cohort rates distinguish relative review candidates from actual
signals. Sparse subgroups remain unscored even when the overall sample grows.

Daily cohorts overlap across their horizons and can repeatedly include the same
stock. Neither row counts nor cohort counts are independent sample sizes.
Complete-case aggregates can still have missing-data bias; report exclusions
alongside results. This is prospective descriptive evidence for a display
policy, not proof of a profitable trading strategy. `performanceValidated` and
`autoPromotion` remain false. Production never reads this study's results.

## Validation and operations

```
pip install -r scripts/requirements-home-top3-study.txt
python -m unittest discover -s scripts -p test_home_top3_study.py
python scripts/home_top3_study.py update
python scripts/home_top3_study.py verify --base HEAD
```

Bootstrap was performed once from the pinned first operational commit. It is
not an automatic initialization fallback. Do not reset/re-bootstrap a study to
repair a collection failure. Keep the manifest and ledger, investigate the
failure, and resume collection without reconstructing missed rankings.

Calendar source: [exchange_calendars documentation](https://github.com/gerrymanoim/exchange_calendars)
and [pinned release](https://github.com/gerrymanoim/exchange_calendars/releases/tag/v4.13.2).
