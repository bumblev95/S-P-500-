# Prediction → evidence → plan (September 2026)

The stock, spot-crypto and perpetual pages share `assets/decision-support.js`.
The calculator is local to the open page; it sends no trade records or inputs to a server.
All amounts are USD. Quantity is capped by both available cash/margin (including
entry costs and assumed funding payments) and planned stop loss including costs.
Funding receipts do not increase the risk budget. Perpetual liquidation clearance
uses an explicitly entered exchange liquidation price, not a guessed leverage-only
formula. Unknown funding requires an explicit assumption.

## Public risk sources

- GZ corporate credit spread and excess bond premium: monthly Federal Reserve staff
  research; https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html
- GZ and EBP use the permanent `ebp_csv.csv` dataset linked by that publication.
  They are not daily HY OAS. Source dates and monthly frequency are shown. Fetch
  failures remain missing. Historical vintages may be revised; these snapshots
  must not be treated as a point-in-time training dataset.
- DGS10 and DTWEXBGS: FRED / Federal Reserve Board, alongside existing NFCI,
  STLFSI4, lending and funding measures. Rates/dollar comparisons use 28-day lags.
- Market breadth uses same-date collected stocks. SPY volatility is realized
  20-session volatility, not VIX; drawdown uses the last 63 sessions.
- Funding and OI: existing Hyperliquid snapshots. Liquidation concentration remains
  explicitly unconnected. Never infer liquidation direction from OI alone.
- Official Fed headlines include source/time. BLS and FOMC calendars are linked;
  calendar ingestion is not implemented. Yahoo earnings dates are shown only
  when future/current and collected within eight days. Missing dates stay unknown.

Risk thresholds are operating heuristics. Related indicators share one family so
GZ/EBP or NFCI/STLFSI do not cast independent warning votes. This risk panel does
not silently retrain price forecasts or reinterpret news as a causal attribution.

## Prospective ledger and model promotion

`build_decision_support.py` captures publicly displayed stock/spot learned
forecasts and the environment model's balanced/enriched challengers. A file in
`ledger/` is never overwritten. The identity is asset class, symbol, original
price date, horizon and exact model version. This new ledger starts with this
release; older reconstructed predictions are not backdated into live performance.
Both eligible and withheld research forecasts are followed, not claimed as trades.

Stocks mature after the requested number of observed trading sessions; crypto
matures on the exact calendar target date. Scoring requires the target date after
recording and before the current UTC date. Missing origin/target or a changed
anchor produces unavailable/excluded status. Realized outcomes freeze in
`outcomes.json`; model selection uses only resolved outcomes. The price MAPE used
here is separate from the older stock return-error MAE (% points).

Each asset/horizon keeps a champion in `registry.json`. Challengers must match the
incumbent on symbol, price date, anchor and target. Selection uses non-overlapping
windows and equal weighting by origin date, at least 12 such dates and 30 pairs,
at least 5% lower error than incumbent and price-unchanged, wins on >=60% of dates,
no worse 90th-percentile error and better last-three-date error. No observations
means no promotion. This is a conservative operational gate, not a significance
test or guarantee of superiority. Promotion events retain their evidence.

Only a promoted, current, price-aligned record with a valid interval can replace
the default research chart. Individual trade eligibility stays withheld pending
its separate gate. No historical issued target is replaced. An enriched model
without its own interval remains in research until it supplies one.

The workflow runs after successful public price/crypto/research/fundamentals
updates and daily. It commits the ledger/outcomes/registry and refreshes Pages.
Intraday perpetual projections are not centrally archived by this release; their
existing replay panel remains separate from the stock/spot prospective scorecard.

## Verification

`python -m unittest discover -s scripts -p test_decision_support.py`

`node scripts/test_decision_support.cjs`

Tests cover immutable reruns, prospective timestamps, calendar vs trading-day
maturity, baseline error, missing data, paired/nonoverlapping promotion, numeric
input rejection, long/short funding signs and loss/cash caps.
