# $10,000 public paper accounts

Two independent USD paper accounts, each initialized at $10,000. No keys,
wallet, user trade history, exchange order endpoint or payment is used. The
only Hyperliquid requests are public `/info` reads.

## Two different records

* **Forward paper account** (`state.json`): initialized when the automated
  runner first publishes this experiment. Only signals actually recorded by
  that runner can create orders. Subsequent completed candles can settle a
  pre-existing order, but missing historical signals are never invented during
  catch-up. Initial cash is $10,000 even if the historical replay made money.
* **Historical replay** (`replay.json`): exploratory application of the frozen
  version to the first available dataset. This is not live or out-of-sample
  performance. The initial replay is frozen, not replaced with a more favorable
  moving window every day. Its start/end, costs, losses and open positions are
  shown. Missing-data limitations remain visible.

Version: `paper-pattern-portfolio-v1`. Parameters were fixed before the first
replay. Changing the strategy version must create separate experiment accounts;
the runner refuses to silently reset this version's ongoing capital. Closed
trades are append-only. Each run that changes the signal/trade ledger writes a
separate timestamped file under `ledger/`, chained to the previous file hash.
Git history preserves account snapshots. This is an audit trail, not proof of
real exchange execution.

## Crypto rules

BTC, ETH, SOL perpetual OHLC from Hyperliquid, 15-minute signals with only
already-completed 1-hour context. Each symbol initially has up to 4,800 15-minute
bars (about 50 days); the API exposes only the latest 5,000 bars. New bars are
accumulated. No claim of multi-year intraday validation is made.

`assets/simulation-signals.js` is shared by the futures page's **paper-experiment
signal** and both account modes. It is separate from the existing futures page's
composite score, whose historical quotes/OI/order-book conditions are unavailable.

1. Breakout retest: recent close outside an earlier 20-bar box, revisit within
   0.2 ATR, directional close, relative volume >=0.8, matching 1-hour trend.
2. Candle at support/resistance: engulfing or pin bar near a previous 20-bar
   low/high (within 0.35 ATR), matching 1-hour trend, volume >=0.8.
3. False breakout: efficiency <0.35, sweep past the previous box then close
   inside, wick >40% of range, higher timeframe not opposing, volume >=0.8.

Stops are beyond the confirmation candles plus 0.2 ATR, at least 0.7 ATR and
at most 3 ATR away. Target is **a fixed 2R simulation exit**, not a forecast of
an observed resistance level. Exit after 8 bars (2 hours) if no barrier hits.
RSI >75 blocks longs; RSI <25 blocks shorts. Only one position per symbol,
3 positions maximum. Risk budget 0.5% of equity per entry; collateral capped
at one third of equity per symbol and available cash. Entry uses 1x collateral.
Exchange-specific liquidation and cross-margin mechanics are not simulated.

## Stock portfolio rules

Fixed research universe across sectors: AAPL, AMD, AMZN, BAC, CAT, COST, CVX,
GE, GOOGL, JNJ, JPM, LLY, META, MSFT, NEE, NVDA, PG, UNH, WMT, XOM. SPY is
the market filter and benchmark. This current-stock selection creates selection
and survivorship bias when replayed historically.

Daily Yahoo OHLC; dividends, taxes and currency conversion excluded. No current
fundamentals are inserted into past decisions. SPY must be above its 200-day
average. A stock must be above its own 200-day average and EMA50, with EMA20>
EMA50, positive 63-session return, RSI 45–72, and either a bullish EMA20 pullback
or 20-session closing-high breakout. Rank qualifying names by 63-session return
divided by ATR/price; ties resolve by ticker. Maximum 5 holdings, 20% entry
weight per stock, 2 stocks per sector. Integer shares only. Unallocated capital
stays in cash. Stop 2 ATR, target 4 ATR, risk budget 1% of current equity.
Exit on barriers, after 84 sessions, or next open after closing below EMA50.
This is a technical-rule research portfolio, not a validated AI stock forecast.

## Execution and accounting

Signals use completed bars only. A queued order may fill at the first available
bar **whose open is after the order was recorded**, including realistic delay
from the scheduled runner. A candle already in progress when a forward signal
was recorded cannot fill that order at its earlier open. Crypto signal expiry
is 2 bars; stock expiry is 5 calendar days. Entry gaps >0.5 ATR or net reward/
risk <1.3 cancel the order. Position and sector caps are checked at fill time.

Opening gap exits and previously scheduled trend exits are processed before
opening purchases. Later intrabar exits cannot fund earlier opening purchases.
If both stop and target are touched within a bar, stop wins. Adverse gap stops
fill at the opening price; favorable target gaps receive no price improvement.
Intrabar exact execution time is unknown and recorded at the bar end with
`timePrecision=bar`. Bar-close equity drawdown is shown; intrabar drawdown may
be larger. Risk budgets are not guaranteed maximum losses.

Fees per side: crypto taker 0.045%; stock research assumption 0.05%. Adverse
slippage per side: crypto 0.02%, stocks 0.05%. Slippage is embedded in execution
prices, not charged twice. Opening collateral is deducted from cash for both
long and short crypto positions. Closing returns collateral plus signed P&L
minus exit fee. Unrealized P&L marks open positions; paid costs already affect
equity. Comparison is SPY or BTC buy-and-hold from the same starting date and
capital, including identical entry fee/slippage, without hypothetical exit fees.

Actual historical funding rates are charged with candle prices as the notional
proxy, not historical oracle prices. Missing hours assume a conservative 0.01%
payment per hour and are counted visibly. Uncertain intrabar funding receipts
on exit bars are not credited. No estimated funding is presented as exact cost.

## Operation and sources

`Update public paper accounts` runs at minutes 7, 22, 37 and 52 UTC. GitHub
scheduling/deployment latency is displayed through data timestamps and may delay
updates. This is not a real-time execution service. Stock OHLC is fetched at
most once per UTC day; stock accounts can settle only when the next completed
session becomes available. Market-closed accounts remain in cash or hold their
positions. Material historical price revisions are flagged and suspend new
forward signals for affected symbols; prior bars/fills are not silently rewritten.

Reproduce: `python scripts/collect_simulation_data.py`, then
`node scripts/build_simulation.cjs`. Tests cover no future-bar use, next-bar
execution, both-hit bars, gap losses, short P&L, costs/funding, cash chronology,
idempotence and preservation of old candles.

* [Hyperliquid candle availability](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
* [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
* [Hyperliquid funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)
