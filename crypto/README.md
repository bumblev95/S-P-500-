# Crypto guide
Read-only Korean spot/perpetual dashboard at ../crypto.html. No order execution, wallet connection, leverage recommendation or trained crypto AI.

Sources: CoinGecko coins/markets for aggregated spot prices and supply; Hyperliquid info API for perpetual prices, completed UTC daily candles, hourly funding, open interest and order books. Symbols use explicit CoinGecko IDs, including SKR=seeker. Data collection is scheduled hourly and preserves original timestamps on failure.

The fixed score weights trend 40%, spot turnover 20%, float/FDV 20%, BTC trend 20%; missing components are null and remaining weights normalize. Coverage is shown. Scores are not probabilities. Long and short scores account for funding and mark/oracle differences; actual candidate gates also require fresh data, liquidity, observed support/resistance reward/risk and acceptable macro conditions. Macro context is the existing US credit dashboard, not crypto news.

Scenarios use a shared 365-day decaying price trend, with 30/120-day prefix views. The optional fluctuating path resamples historical daily returns and is an illustration, not a turning-point forecast. Bands are uncalibrated volatility references. Price-only backtests compare MAPE to unchanged prices at non-overlapping horizon endpoints; they do not validate spot/perpetual score profitability.

Not connected: future unlock dates, holder concentration, exchange flows, active addresses, protocol revenue/TVL, liquidation maps or crypto-specific news. Circulating/total is not an unlock schedule. Observed supply and OI changes need 24 hours of real history. OI changes use token quantities.

Validation:
- python -m unittest discover -s scripts -p 'test_crypto.py'
- python scripts/build_crypto.py
- node --check assets/crypto.js
- node scripts/test_crypto_page.cjs

The Node check validates chart prefixes and a mocked DOM render at mobile width, not browser visual appearance.
