# Crypto spot and short-term perpetual guides

Routes: `/` is the beginner stock guide; `advanced.html` retains the valuation dashboard; `crypto.html` is spot only; `futures.html` is short-term perpetuals. No wallet connection, order execution or leverage recommendation.

## Spot
CoinGecko aggregated spot prices, turnover, supply and FDV, plus UTC midnight daily price observations. The trailing live observation from market_chart is excluded. Midnight observations are labelled with the preceding completed date. Missing history remains missing; perpetual candles never substitute for spot data.

Daily history is cached until the next UTC day. Public CoinGecko requests are paced 12 seconds apart; 401/403/429 stop further requests to that provider for that run. Failures preserve original source timestamps. Refresh is scheduled hourly and may be delayed.

Fixed score: trend 40%, spot turnover 20%, float/FDV 20%, BTC spot trend 20%, normalized over available components. Entry requires current price inside an observed support zone and reward/risk >=1.5, fresh sources and acceptable US credit conditions. The close-only support buffer uses average absolute daily changes, not OHLC ATR. Targets use confirmed previous daily highs.

The 30/120/365-day scenario views are prefixes of one decaying trend path. Historical spot availability is at most one year, so a one-year backtest is unavailable; shorter price-only MAPE comparisons are not trade-strategy results. The fluctuating path is illustrative, not a turning-point forecast.

## Perpetuals
The browser calls the public Hyperliquid info endpoint for the selected coin: metaAndAssetCtxs, l2Book and 5m/15m/1h/1d candleSnapshot (242 bars each). Only completed, timestamp-aligned OHLCV bars are accepted. No API key or user account data is sent. Visible pages poll every 60 seconds; freshness is rechecked every 15 seconds. 401/403 halt automatic requests; 429 pauses requests; failures use bounded backoff. Errors never refresh old timestamps or produce fresh entry signals. Changing coins discards superseded results.

5m uses 15m confirmation; 15m uses 1h confirmation; 1d is independent. Rules use EMA20/50, Wilder RSI14/ATR14, MACD12/26/9, candle-volume-weighted typical price (UTC session for intraday; rolling 20 bars for daily), relative volume and 20-bar directional efficiency. Patterns include 20-bar range breaks, trend pullbacks and two-body engulfing patterns. Confirmed pivots require two completed bars on both sides.

Candidate gates require a confirmed pattern, aligned trend, no excessive RSI/ATR condition, a recent continuous series, quote/book age <=90 seconds, turnover >=$10M, OI >=$1M, spread <=0.1%, and mark/oracle deviation <=1%. Latest mark must remain within the signal close +/-0.15 ATR. Reward/risk >=1.5 includes 0.045% taker fees per side, assumed 0.02% slippage per side, and current paying-side hourly funding over six bars rounded up to whole hours. Funding receipts do not improve reward/risk. Actual fee tiers and costs differ.

Stops sit 0.25 ATR beyond support/resistance, with risk <=5 ATR. Targets are observed confirmed pivots; after a breakout with no observed target, a measured range projection is explicitly labelled as an assumption. Targets are never moved to manufacture a passing reward/risk. The chart has a separate horizon selector: 5m bars project 1/3/6 hours; 15m bars project 2/6/12 hours; daily bars project 3/7/14 days. Longer views truncate the same log-price trend with exponential drift decay and an uncalibrated ATR-based widening band. Display horizons never change entry gates, signal expiry or the six-bar cost assumption. The chart extension is an untrained trend assumption. Scores are not probabilities; long and short scores need not sum to 100.

Not connected: unlock schedules, concentration, exchange flows, active addresses, protocol revenue/TVL, liquidation maps, crypto news and trained crypto models. No claim of verified strategy profitability. US credit context applies to the spot page; it is not an intraday news signal.

Validation: Python crypto data guards; Node shared spot path checks; perpetual candidate/stale/gap/cost/closed-bar checks and mocked mobile-sized page interactions; existing stock guide regression check. Mocked DOM tests do not verify browser visual appearance.

## Visual summaries
Supply donuts use maximum supply when valid, otherwise current total supply. Slices separate circulating, issued-but-not-circulating and not-yet-issued tokens. They are not unlock schedules. Missing/inconsistent supply is not drawn as zero. Bars use common scales for component scores, market cap/FDV and signed 7/30-day returns. Long/short scores remain independent bars, not a percentage pie. RSI uses labelled 30/70 zones.
