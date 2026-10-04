# PR #19 forward entry study

This study tests an **unvalidated design hypothesis**. It does not promote a
strategy, replace an account, connect a broker, or authorize live trading.
`performanceValidated` and `autoPromotion` remain false regardless of results.

## Start and fixed inputs

The first production invocation of `scripts/build_simulation.cjs` after merge
creates `entry-context-v1-forward-v1/manifest.json`. No results or start date are
prepopulated in this PR. Genesis contains two independent $10,000 cash accounts,
zero positions/orders/trades, and a SPY comparison anchor. Existing stock state,
ledger, pending orders and frozen replay remain outside this directory.

The manifest freezes the first run's stock symbols and sectors (currently the
same 20-stock simulation universe; SPY is only the benchmark), settings, code
hashes, source timestamp and observation start time. It never adds a replacement
symbol after a constituent disappears. Warmup history calculates indicators;
it cannot create a signal, order, holding action or fill before study creation.
Later calls evaluate only the latest newly observed completed session. Missed
sessions may settle **already posted** orders and precommitted stops/targets;
they never receive retroactive entry or holding signals. Signals first observed
after a session opens cannot fill at that earlier opening price.

## Accounts and frozen rules

| Account | Entry/exit rules | Initial conditions |
| --- | --- | --- |
| `indicator` | Exact PR #19 55-bar breakout / confirmed pullback; separate observed-price holding response | $10,000 cash, no positions/orders |
| `control` | Existing 20-day-close breakout / EMA20 pullback stock engine, including original SPY, RSI, ATR, 2R target, EMA50 exit and 84-bar limit | Same start, universe and $10,000 cash |
| `comparison.existing` | Read-only observation of the already-running stock account | Its actual opening equity, AAPL/MSFT holdings and old pending orders; descriptive comparison only |

`scripts/entry-study-v1/technical-guide.cjs` is byte-for-byte PR #19's
`assets/technical-guide.js` (Git blob `41faedc2be71bc67b03b12d5680eb53d1e2b7395`,
merge `bbafecc23d691894a52a8152c26e689353daa7f3`). The original paper engine,
simulation detector and indicator dependency are also vendored, with only their
local require paths changed. The new adapter uses the EOD 253-observation history,
20/50/200-day simple means, 21/63-bar returns and 84 close-return sample standard
deviation (annualized; EOD inputs rounded to six decimals). It uses first-observed
Yahoo Close/OHLC in the same price basis, excluding dividends. It never uses AI
forecasts or backtests as entry inputs. Credit is the feed actually available at
observation, including its freshness gates, not an inferred historical regime.

All PR #19 thresholds, strategy selection and holding labels come from that
frozen source: 55 previous bars, no hybrid high/close breakout level, 20 true-range
average only with 21 valid high/low bars, explicit close-volatility fallback,
previous-bar moving-average pullback zone/support touch/rebound, structural stop,
credit-specific risk/reward/extension gates and optional volume confirmation.
See [ENTRY-INDICATOR.md](../../research/ENTRY-INDICATOR.md).

Each assessment and qualifying signal records `levelBasis` (`일별 고가·저가` or
`종가`), `levelBasisCode` (`ohlc-high-low` or `close-only-fallback`), `rangeBasis`,
both setup states, selected setup, levels, trend score, credit state and the
causal history hash. Entry orders and closed trades retain the signal basis.
Fallback observations are reported separately and never called ATR.

The UI holding recommendations are not themselves a complete execution system.
The following **additional, frozen execution hypotheses** make them testable:

- `reduce` schedules a full exit at the first opening after the observation.
- `protect` and `hold` may raise an existing stop to the preceding 20-bar low,
  only when the level is below close and above the old stop. It applies after
  observation, never to the bar that produced the new level. Stops never loosen.
- Breakouts have no fixed profit target or holding-time cap. Pullbacks use the
  signal's preceding 55-bar high as their immutable target. Both retain their
  initial structural stop unless tightened by a later recorded holding action.
- Market/AI failure alone cannot trigger an exit. Unavailable price data produces
  an unavailable holding response; it never fabricates a sell instruction.

These are strategy differences, not an isolated causal test of the 20 versus 55
lookback. Entry filters, target and holding controls differ as part of each full
rule. The simultaneous control avoids attributing different starting holdings,
start dates or costs to rule quality.

The original account's observed cost/risk configuration is retained at each
comparison observation. `comparison.existing.sameCostRiskAssumptions` reports
whether it matched the frozen study assumptions throughout the window; later
changes to the original account cannot silently become an equal-cost comparison.

## Equal cost and account risk assumptions

| Assumption | Both study accounts and current existing stock account |
| --- | --- |
| Initial study capital | $10,000 USD each |
| Fee / adverse slippage | 0.05% / 0.05%, each side |
| Stop-risk budget | 1% of opening equity, includes entry/stop slippage and both fees |
| Maximum position weight / count | 20% / 5 |
| Same-sector count | 2 |
| Shares / leverage | Whole shares / 1x, cash limited |
| Entry gap cap | 0.5 of the signal's range unit (original control uses its ATR) |
| Entry time | First eligible completed session's actual open, after observation |
| Signal lifetime | 5 calendar days from signal close |
| Same-bar stop and target | Stop first |
| Gap beyond stop / target | Adverse opening stop fill / target price, no favorable target windfall |
| Intraday exit proceeds | Cannot finance a purchase at the earlier open |
| Excluded | Dividends, tax, FX, automatic split adjustment |

The frozen engine's cost-adjusted 1.3 reward/risk execution gate remains on
pullbacks and the control. Targetless breakouts bypass that gate; they still use
the same cost-adjusted equity-risk sizing. This execution gate does not change
the exact PR #19 signal decision. Planned PR #19 8%/5% stop distances are stock
price distances, separate from the 1% account-equity budget.
The equity-risk budget sizes against the planned stop, not a guaranteed loss
ceiling; gaps can produce larger losses in either account.

A missing open/high/low never becomes synthetic execution OHLC. An entry at such
a session is canceled; a held position's affected execution/valuation is frozen
and `incompleteExecution` is set. Material revisions (>0.5%), provider errors,
missing symbols and malformed/duplicate sessions are recorded. First-observed
bars remain unchanged. SPY failure pauses both accounts. A data gap or frozen
valuation can understate risk; `executionComparable=false` excludes a clean
performance interpretation. There is no automatic repair or promotion.
Catch-up also records `missedObservationSessions` and makes this flag false:
the frozen control retains its legacy precommitted EMA50/time exits, whereas the
new account acts on holding assessments actually observed. Signal opportunities
lost between observations are not invented or counted as forward discoveries.

## Immutable evidence and comparison

Only `latest.json` is a replaceable derived view. The manifest and sequential
`ledger/00000000-<hash>.json` records use exclusive creation, never overwrite.
Each record includes the previous hash and manifest hash, observation time,
newly accepted bars, credit feed, complete assessment inputs/history hash,
signals, orders, fills, cancellations, holding/stop actions, trade/curve deltas
and checkpoint. It preserves all earlier events/trades. Bar history is stored
once and reconstructed for verification instead of copying warmup histories
into every daily record. The original stock ledger is never written by this
study builder. This is append-only application behavior with hash/CI tamper
detection, not a claim that a repository administrator cannot rewrite Git.

`latest.json` and the main simulation's `entryStudy` field expose:

- Qualifying stock-session signals (including signals while already holding),
  signals per 100 assessed stock sessions, posted orders, entries and cancellations.
- Fee/slippage-inclusive equity return, realized/unrealized P&L, closed-trade
  counts, win rate, maximum drawdown and current/mean/maximum session exposure.
- Breakout versus pullback counts/net results; actual high/low versus close-only
  fallback results for the indicator account.
- Same-start control results and read-only existing-account results rebased to
  the study start. Existing-account initial holdings remain explicitly visible.
- Observed-session count and data limitations. These metrics have no automatic
  pass threshold and never change the live site indicator or existing strategy.

Exposure is marked notional / equity at completed-session closes; mean exposure
uses the same completed-session sample grid, excluding genesis. Intraday peaks
and unobserved opportunities are not measured. With catch-up, the latest signal
is evaluated once, so frequency denominators count actual observation sessions,
not every downloaded historical date. The fixed present-day universe is not an
unbiased historical S&P 500 constituent sample.

## Validation and operational path

```sh
node scripts/test_entry_study.cjs
node scripts/test_paper_engine.cjs
node scripts/test_entry_indicator.cjs
node scripts/verify_entry_study.cjs --base origin/main
```

The new scenario suite covers source parity, both setups/bases, missing volume,
credit/AI independence, fixed universe, genesis, future data, late observation,
next-open execution, cost/risk sizing, missing OHLC, revision cancellation,
dual-hit/gap stops, holding timing, catch-up, same-start control, immutable
prefixes, altered manifest/records, truncation, cache reconstruction and repeat
idempotence. Synthetic test results are not forward P&L or profitability evidence.

The scheduled public-paper-account workflow runs this suite and the verifier,
then builds and commits the separate study together with the normal update.
Dedicated PR/push CI refuses modifications/deletions of prior study manifests or
ledger files. Frozen code changes pause this version; a reviewed change needs a
new named study version while retaining this one. An independent study-builder
failure is reported as `entryStudy.status=paused` and cannot change existing
account execution. Manual inspection remains necessary before drawing research
conclusions; this study never auto-promotes a strategy.
