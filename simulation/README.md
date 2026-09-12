# $10,000 public paper accounts

## Current default: 14-day momentum + 6 ATR profit target

By user request, the default crypto view now selects the separate
`momentum14-target6-forward-v1` account in `momentum-target6/`. It begins with
$10,000 when the updated automated runner first executes. No old balances,
positions, replay profits or backdated fills are transferred. The original
`momentum/` account continues unchanged as a comparison, including its open
positions, closed trades and hash-linked ledger. Different start dates mean
their lifetime returns are not a matched-period comparison.

Entries, 2.5 four-hour ATR initial/trailing stops, momentum reversal exits,
30-day maximum holding time, fees, funding and leverage/risk limits are unchanged.
The new target is signal price plus 6 signal ATR for longs or minus 6 for shorts.
It is frozen with the entry order, not recalculated or trailed after entry.
Same-bar stop/target hits remain stop-first. Forward orders and control changes
apply only after their actual observation time. This is prospective paper
evaluation authorized by the user, not validated profitability or real trading.
All earlier research reports remain unchanged historical records of their
original publication decisions. See [exit research](../exit-experiment.html).

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

## BTC 5x / ETH and SOL 3x experiment

The new default crypto view is a separate account under `leveraged/`, version
`isolated-5x3x-risk-v1`. Original 1x and stock accounts, balances and closed trades
are preserved. Both crypto accounts start with their own $10,000. New experiments
do not inherit replay profits. A fixed same-data 1x replay is also saved with the
new replay; leverage and risk controls both differ, so this is not a causal test
of leverage alone.

BTC uses 5x and ETH/SOL 3x entry leverage, with isolated collateral. Notional is
quantity times price; collateral is notional divided by leverage. Fees and
funding are based on notional, never collateral. Quantity is the minimum allowed
by all limits, not automatically multiplied by leverage:

* Planned stop risk, including modeled costs: 0.5% of current account equity.
* Sum of still-open entry risk budgets: at most 1.5% of current equity.
* Entry collateral per symbol: 20%; aggregate collateral: 40% of equity.
* Aggregate opening notional exposure: 2x account equity maximum.
* UTC day's equity loss >=2%: block new entries until the next UTC day.
* Three consecutive closed losing trades: six-hour entry cooldown.
* Equity >=10% below observed risk high-water mark: latch entry pause permanently
  for this experiment; no automatic capital or peak reset.
* No averaging down, widened stops or added collateral. Existing barriers/time
  exits continue during entry pauses. Target remains 2R, maximum hold two hours.

Daily and drawdown checks use observed opening/closing valuations, not continuous
ticks. They cancel new entries, do not promise a maximum account loss. Adverse
gaps may exceed the planned stop budget. An order also needs its stop to be at
least max(2 ATR, 1% of entry price) away from the modeled liquidation boundary.

**Stylized liquidation, not exchange-exact reconstruction:** fixed maintenance
rate 2.5% for all three symbols; trade OHLC substitutes for mark-price OHLC.
Historical margin tiers, insurance funds, order-book execution and partial
liquidations are unavailable. Liquidation price solves
`collateral + signed_quantity * (price - entry) = maintenance * quantity * price`.
Hourly funding changes isolated collateral and its boundary. Entry fees come
from available cash. If the opening price crosses the liquidation boundary,
liquidation takes precedence. For a continuous intrabar path crossing both stop
and liquidation, the nearer adverse boundary is used; stop also precedes target
when both are hit. Exact intrabar order of funding and prices is unknown.
Losses beyond isolated collateral are capped by a **simulation assumption**, with
the adjustment recorded per trade, aggregated and warned. This is not a claim
about actual liquidation guarantees. Original 1x execution has no such cap.

## Neural research and policy changes

`train_pattern_research.py` actually fits a small MLP with two hidden layers
(16 and 8 units), seed 42, L2 alpha 1, L-BFGS with a fixed 500-iteration limit.
This is an exploratory neural network, not ChatGPT retraining itself. Twenty
features describe completed-candle body/wicks, trend, volatility, volume, side,
pattern and symbol. The target is **whether the hypothetical candidate trade
has positive net P&L**, not the next candle's direction.

Candidate outcomes use the same isolated execution engine with actual funding,
fees and gap checks, independently per signal. These overlapping training
observations are not independent portfolio trades. Three common time slices
across symbols use 60% training, 20% threshold selection, 20% final evaluation.
Samples whose outcomes approach the next boundary are purged with an additional
8-bar embargo. Scaling fits training data only. Thresholds 0.5, 0.6 and 0.7 are
ranked by validation candidate sum of net risk units, requiring 10 accepted
validation samples; the final evaluation does not choose model parameters.

Evaluation reports Brier error against logistic regression and a fixed training
base rate. A second pass evaluates neural-filtered and unfiltered eligible
signals as two actual paper portfolios, under identical risk and cost rules.
The displayed portfolio returns are not a sum of independently sized labels.
The first holdout is exploratory because the rules were studied on the broader
historical data before this experiment. It is not prospective performance.

All recorded reports, fitted weights and training sample snapshots are retained
under `research/`. A run is considered at most once per seven days; each later
evaluation must use signals after the prior evaluated-through timestamp. Older
outcomes may then be used in training/selection, but never counted again as a
new unseen evaluation period. Insufficient new data produces a waiting report.
Changing this research version is a new candidate, not erasure of old results.

Minimum candidate gates fixed before the first fit: 90 days of price history,
100 closed evaluation trades, positive net return, improvement over same-period
rule portfolio, no worse drawdown, Brier error below both simple baselines,
sufficient validation samples and no convergence warning. These gates are
screening criteria, not statistical proof of superiority. No learned model
automatically alters the operating account; a qualified candidate still needs
a separate prospective paper experiment. Failed and losing results remain visible.

Sources: [Hyperliquid margin definitions](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining),
[scikit-learn supervised neural networks](https://scikit-learn.org/stable/modules/neural_networks_supervised.html).

## Wider stops and drawdown recovery experiment

`wide/` is another independent $10,000 account, version
`isolated-wide-recovery-v1`. Earlier accounts are preserved. Entry leverage is
still BTC 5x and ETH/SOL 3x. Account risk percentage is not price stop distance.
The initial comparison changes several parameters together, not a causal test
of any single parameter:

* Stop distance: maximum of the original structural distance and 2 ATR.
* Target: twice that initial distance; maximum hold: 32 fifteen-minute bars
  (8 hours), versus the original 8 bars (2 hours).
* Base planned account risk per trade: 1%; aggregate open entry risk: 3%.
* Daily entry pause: 3% UTC-day loss; three losses still trigger six-hour rest.
* At >=10% drawdown from the preserved observed risk high-water mark, multiply
  both risk budgets by 0.5; at >=20%, multiply by 0.25. Existing positions are
  not enlarged. When drawdown falls below those thresholds, budgets recover
  by the same stages. There is no permanent 10% stop in this new experiment.
* Collateral, exposure, liquidation and gap assumptions are otherwise retained.
  Funding risk reserve used for sizing now covers the eight-hour hold window.

These are hypotheses, not optimized or validated principles. Wider stops can
produce larger losses, fewer units or longer exposure. A 10% capital loss needs
11.11% subsequent profit to recover; recovery is not guaranteed. The observed
first old leverage replay had 35 stop exits, 49 time exits and 18 target exits,
so holding-time exits are also tested explicitly.

## Multi-year futures research

`collect_long_futures.py` reads the public Binance USD-M monthly archive listing,
downloads every available completed month for BTCUSDT/ETHUSDT/SOLUSDT 15-minute
klines and funding rates, and verifies official SHA-256 CHECKSUM files. At this
experiment's launch the available monthly candle history begins January 2020
for BTC/ETH and September 2020 for SOL. No pre-existence decades of crypto
futures are synthesized. Listing, actual dates, row counts, gaps and checksums
are published in each manifest. First-seen archives are cached and verified;
unavailable files cause the research to fail rather than silently use a shorter
history. Only complete groups of four 15-minute candles form a 1-hour candle.

The long archive is separate from the live Hyperliquid market. Funding follows
the archive's actual published settlement times and intervals. Intervening
hours count as no settlement only when consecutive published records confirm
the interval. Missing expected intervals retain explicit conservative charges;
an 8-hour settlement is not incorrectly charged every hour. Trading fees remain
the same fixed research assumption, not historical Binance account fee tiers.

`train_long_futures.py` fits an expanding-history MLP (16, 8), L2 alpha 1, seed
42, fixed 1000 L-BFGS iterations and training-only feature scaling. The target
is positive net candidate P&L under the wider-stop experiment. Evaluation in
2024 uses pre-2023 training and 2023 selection; 2025 uses pre-2024 training and
2024 selection; 2026 uses pre-2025 training and 2025 selection. Outcome windows
are purged with an additional 32-bar embargo. Threshold choices 0.5/0.6/0.7
require at least 30 selection samples and are chosen before the next-year
evaluation. Each year's model, warning, comparison and dates are preserved.

Reports compare Brier errors against logistic and training-base-rate models,
and use the actual paper engine to evaluate filtered and unfiltered candidates
in separate $10,000 accounts per evaluation segment. Segment returns must not
be added or presented as one continuous equity curve. Future monthly updates
preserve completed-year results and evaluate only dates after the last
evaluated-through time for incomplete years; earlier segments remain embedded.
Minimum screening includes 100 closed neural trades per segment, positive net
returns across segments, no worse drawdown, superiority to simple predictive
and trading controls, and no convergence warning. Data gaps are disclosed.
These are screening rules, not proof of future profitability. No automatic
promotion into an operating account occurs.

`Research long-history futures` runs after relevant source updates, on manual
dispatch, and monthly on the 8th after publication of the prior month's files.
It allows 90 minutes, caches reproducible raw inputs, and preserves reports,
manifests and model weights in git. Heavy research shares the account publisher
lock to avoid conflicting balance writes; scheduled paper updates may be
delayed during that run. The first result is retrospective research, not a
prospective trading record. Monthly archive age is visible in the data dates.

Source: [Binance public data specification and checksums](https://github.com/binance/binance-public-data).

Long-research correction: `long-futures-wide-mlp-v1` is superseded. Some archive
funding timestamps differ from their hour boundaries by one millisecond; exact
interval comparisons incorrectly charged conservative missing-hour funding.
`v2-funding-clock` verifies matching hour-aligned intervals with at most one
minute of timestamp jitter while retaining actual settlement times for charges.
True missing multi-interval gaps still trigger estimates. Candidate labels,
models and all year evaluations are regenerated under a new cache/version key.
Old reports remain as withdrawn research history, not valid performance.


## Fixed 4-hour trend comparison (v1)

Three new methods are kept separate from active paper accounts: prior 20-day Donchian breakout / 10-day opposite channel exit; EMA 60/180 on 4-hour bars (10/30 days); 14-day price momentum exceeding 2 four-hour ATR. Every method uses a 2.5 ATR initial and monotonically tightening trailing stop, no fixed profit target, and a 30-day maximum holding time. Completed 4-hour signals enter at the next available 15-minute open; stop revisions apply only to subsequent bars. The existing BTC 5x / ETH,SOL 3x risk and exposure limits remain in force. Eight hours of estimated funding is reserved at sizing; actual holding-period funding may exceed that reserve.

`research_trend_methods.cjs` evaluates every fixed method, without parameter search or selecting only winners, on separate $10,000 calendar accounts from 2024 to the latest archived month. Positions are closed at period end with exit costs. Each method is also rerun with doubled fees and slippage. Prior reports remain timestamped under `simulation/method-research/`. The three-method screen requires positive base and stressed returns in every period, maximum close-to-close drawdown <=10%, and at least 100 total closed trades; even passing this exploratory screen does not deploy a strategy. These years were already examined in earlier experiments, so this is explicitly retrospective comparison, not untouched out-of-sample proof. Fixed methods use only their rolling historical windows; this is not additional neural training. Current symbols entail selection/survivorship bias. Binance archive execution remains an approximation, separate from Hyperliquid forward accounts.

Motivation: [Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum). That paper studies different markets and longer horizons; its findings do not establish profitability for these crypto implementations.


## Public bot and trader ideas (2021 onward)

`public_bot_methods.cjs` independently implements four sourced strategy ideas plus the unchanged 14-day momentum control. These are **adaptations under common risk rules**, not replications of the original bots, their authors' account returns, or advertised profitability. All use complete 4-hour bars, next 15-minute open execution, 2.5 four-hour ATR initial/trailing stops, at most 30 days holding, and the existing 1% risk / BTC 5x / ETH,SOL 3x caps. Source details and differences are embedded in each report.

- Hummingbot MACD-BB: published BB(100,2) and MACD(21,42,9) joint conditions, moved from the original 3-minute APE setup to 4-hour BTC/ETH/SOL. Added mean reversion exit at the middle band. Original 20x leverage, 55-minute duration and standard-deviation barriers are not reproduced.
- Triple Supertrend: inspired by the Freqtrade example's three-way agreement, using fixed periods 7/10/14, multiplier 3, Wilder smoothing and symmetric short entries. The source's optimized parameters, ROI settings and 1-hour timeframe are not reproduced.
- Turtle 55-day: prior 330 four-hour bars and opposite 120-bar exit. No pyramiding; common risk rules replace original sizing/stops.
- Rayner 200-day: prior 1,200 four-hour bars and opposite 60-bar exit. Its author's reported 32.12% annual return / 41.51% max drawdown concerns another set of traditional futures and is not our bot's result.

The comparison publishes **all five methods**, annual and doubled-cost results from 2021, source links, timestamped manifests and closed trades in `simulation/public-bot-research/`. The 2020 input prepares indicators, with full warmup restarted after gaps. The existing 2024-onward momentum results must reconcile exactly against the preserved earlier comparison. No parameter optimization or automatic model promotion occurs. Current symbols and reused historical periods create selection bias; good historical ranking requires subsequent forward verification. NostalgiaForInfinity was reviewed but not reproduced or evaluated as that original bot.


## Momentum forward paper account (user-authorized experiment)

The separate `momentum14-forward-v1` account starts with $10,000 in `simulation/momentum/`. It uses the same fixed 14-day / 2 four-hour ATR entry idea and 2.5 ATR trailing stop as the research control, with BTC 5x / ETH,SOL 3x and the existing 1% base risk, 3% aggregate risk, drawdown scaling and daily entry limits. This is authorized forward **paper evaluation**, not a claim that the historical screening gates were passed. Old accounts and reports are retained.

The latest completed four-hour signal remains eligible until the next four-hour close, with at most one recorded signal per symbol/direction/bar. An order is filled only at a bar opening after its actual recording time, subject to the 0.5 ATR gap limit and capital checks. Unlike immediate historical replay, delayed forward jobs do not invent intermediate signals. Trailing-stop changes and momentum reversal exits observed by a delayed job are recorded at the observation time and apply only to bars starting after that time. Existing stops and predetermined maximum holding duration continue to settle against available completed bars. This means forward results may differ materially from replay when jobs are delayed.

The initial short replay is frozen on Hyperliquid data after sufficient 30-day indicator warmup. It is distinct from the Binance annual comparisons, and its balance is never imported into the new forward account. Hash-linked ledger records preserve entries, exits and recorded stop/exit instructions. Monthly long-research builds also preserve this account, and regular scheduled paper jobs collect prices and settle it.
# 추세 반전 감지 비교 실험

[14일 모멘텀 + 온라인 변화 감지 비교](../momentum-experiment.html)를 별도 공개했다. 통계적 BOCPD를 추가한 고정 규칙 실험이며, LSTM 전체 재현이나 진행 계좌 성적은 아니다. 2021–2026년 6개 구간 중 수익 개선 2개·낙폭 개선 1개였고, 최근 구간은 -3.53%에서 -4.11%로 악화됐다. 기존 모의계좌는 유지한다. [상세 결과와 재현 방법](cpd-research/README.md).
