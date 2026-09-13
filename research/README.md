# Current S&P 500 expansion

The current v4 experiment targets every security in the dated current-constituent
snapshot [universe.json](universe.json). See [SP500-LEARNING.md](SP500-LEARNING.md)
for the generated run report and [sp500-summary.json](sp500-summary.json) for
coverage, same-row comparisons and sector results. The older pilot notes below
are historical documentation, not the current issuer limit.

Membership is refreshed from the same public constituent dataset used by the
stock dashboard. CompanyFacts is requested once per CIK, at most two requests
per second, and histories retrieved within 20 hours are reused. Progress is
checkpointed every 25 issuers and immediately on access denial. The dated input
checkpoint is published before model training. A denial stops further SEC
requests and preserves the 24-hour retry policy. Missing or unsupported standard
annual facts are reported; they are never replaced with invented data.

Both weekly and weekday research jobs refresh membership and SEC inputs. The
weekday job retains crypto results and their original model/date. Raw SEC and
price files are build caches. Additional companies can later be supported by
expanding the versioned universe loader, collection and evaluation together.

Price histories request up to 20 years. Each issuer contributes one representative
share class to fitting and evaluation, while all available classes get forecasts.
Weekly training origins, matured labels, nonoverlapping test windows and fixed
model settings are retained. Sector summaries and an availability-only control
use the same issuer/date pairs. Current membership has survivorship bias and
previously inspected dates are not an untouched test set. No production promotion
or paper-trading rule is changed by this expansion.

---

# Public environment model comparison

**Current earnings extension:** [Official quarterly earnings learning](EARNINGS-LEARNING.md)
describes the NVDA/MSFT dated-release collector, four quarterly features, daily
stock retraining and availability-only comparison. That extension supersedes the
older statements below that quarterly releases and numeric guidance are absent.

This is a separate, fixed challenger experiment for 16 representative current
stocks and the dashboard's available spot coins. It does not request trade
records or change the production model's forecast. Full historical inputs are
local build inputs (`research/history`, ignored by git); the published result
records their hashes and dates. Yahoo adjusted daily prices are requested up
to 20 years, with shorter histories for younger instruments. Failed requests
retain cached input dates. A 401/403/429 stops further provider requests.

Both fitted candidates use identical weekly origins, strictly matured labels,
parameters, and weighted absolute price-ratio loss (future-price MAPE). The
price-only candidate uses price trends and volatility. The environment candidate
adds prior-date SPY, QQQ, HYG, IEF, UUP and VIX features, and BTC context for coins.
HYG/IEF are price proxies: they are not measured credit spreads or policy rates.
Context closes strictly precede origin, including crypto weekends, and cannot
be more than five calendar days old. Stocks and crypto are fitted separately.
Prices can be revised; no vintage fundamental, news, supply, unlock or on-chain
history is included. Neither candidate is the production model, so its scores
must not be called a direct improvement over the production model.

The fixed third challenger is the equal-weight average of the two fitted
price ratios. All comparisons include no-change on identical rows. Up to 18
origins per horizon have disjoint realized outcome windows. An earlier block
selects environment or ensemble by date-balanced MAPE + 0.25 * pooled p90;
selection labels must mature before the later evaluation starts. The later
block reports results for all candidates. The research gate requires six later
dates, 5% mean error improvement over both simple comparators, no worse p90,
60% date win rate and no worse direction agreement. It does not auto-promote.
Per-symbol scores and regime groups are descriptive all-origin diagnostics,
not the selection holdout or additional independent evidence. Annual observations
remain limited for young coins. Same-date assets and market cycles are correlated.

Foundation models (Chronos-2, TimesFM-3) have not been run here. Their benchmark
results elsewhere are not evidence of profitable trading. Before including one,
check its pretraining data/cutoff for overlap with financial test periods and
use prospective testing when that cannot be established.

Run `python scripts/build_environment_research.py`, or `--offline` with cached
inputs. Then run `python -m unittest discover -s scripts -p test_environment_research.py`.
The workflow refreshes this research weekly; data dates remain visible.

## September 2026 upgrade: data, loss and uncertainty

The running version is now `environment-challenger-v6-medium-long`. The
earlier protocol above describes v1; the sections below supersede its selection
metric and its statement that no fundamental/supply inputs are present.

### Horizon-specific stock challenger

The 126- and 252-session stock targets train independent models rather than
sharing one estimator configuration. Both models can use price,
publication-lagged market context, and publication-dated SEC/company-release
features. The former 21-session price target is no longer treated as a useful
direction forecast; short-term entry timing is handled by separate transparent
technical rules. Each remaining horizon has fixed,
predeclared tree capacity and regularization, plus explicit prior-date bear and
high-volatility regime flags.

Each horizon also fits a separate three-class direction classifier for down,
flat and up outcomes at the existing ±2% boundary. Training class weights reduce
the previous all-up/all-flat collapse; its three outputs are labelled direction
scores, not calibrated real-world probabilities. The return regressor still
determines magnitude, subject only to the class boundary when a fixed score and
margin threshold is met. All thresholds are declared before later evaluation.
The later gate requires the model to beat the always-up direction baseline and
also requires at least 10% down recall when enough actual down observations
exist. Better down recall cannot compensate for failing the existing mean,
tail, consistency or direction checks, and no model is promoted automatically.

Research reviewed:

- [Chronos-2 paper](https://arxiv.org/abs/2510.15821): numeric/categorical
  covariates, cross-series information and quantile forecasts. The synthetic-only
  variant is a possible future comparator when real financial pretraining overlap
  cannot be excluded. Text news is not a native input to this model. We have not
  executed its weights and do not claim its benchmark scores for this site.
- [TimesFM-3, Google Research](https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/):
  separates past-only covariates from information genuinely known in the future,
  and produces quantiles across its forecast horizon. This motivates timestamped
  data and range evaluation here, not an assertion that HGB implements TimesFM.
- [Forecasting: Principles and Practice, point accuracy](https://otexts.com/fpp3/accuracy.html)
  and [distribution accuracy](https://otexts.com/fpp3/distaccuracy.html): MAPE can
  reward a different point estimate from symmetric error objectives. Prediction
  intervals should be scored for width as well as missed outcomes.
- [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces):
  public companyfacts contains financial disclosures and filing dates. Fiscal
  period ends alone do not establish when an investor could know a number.
- [Hyperliquid perpetual info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals):
  public hourly funding history; this is one venue, not the entire crypto market.

### Implemented comparison

The additional `balanced` HGB uses the same environment inputs, model parameters,
origins and matured labels, but minimizes absolute **log-return** error without
inverse-price weights. Its exponentiated prediction is a conditional median,
not an arithmetic expected price, most likely price, or trading instruction.
MAPE, absolute log error, signed log bias, direction error and tail error are all
reported. Geometric price bias on the page is `exp(mean(log(pred/actual)))-1`.
A lower log error need not mean lower MAPE: crypto annual results demonstrate this
tradeoff. There is no artificial volatility multiplier or forced endpoint motion.

Earlier dates now choose environment, ensemble or balanced by date-mean absolute
log error plus 0.25 times the pooled 90th-percentile log error. Later gates require
six dates, 5% log-error improvement over price-only and no-change, no worse MAPE
or p90 MAPE, 60% date wins and no worse direction accuracy. These historical
periods have been inspected during earlier development. They are not a fresh,
untouched holdout for the design of v2, and there is no automatic promotion.

The balanced model's interval radius is the date-balanced 80th percentile of
absolute log residuals from at most eight previous **out-of-sample** origins whose
outcomes finished strictly before the new origin. At least three dates and 30
asset-date observations are required. Apply this radius symmetrically in log
price around the new median. Assets within each origin have equal total date
weight. All assets of the same class are pooled: individual assets/regimes can
be badly miscalibrated. This is empirical rolling calibration, not an iid
conformal coverage guarantee. The page reports actual later/own coverage and the
80% log interval score: width plus `2/0.2` times either tail miss. Wide crypto
annual ranges are shown with a prominent limited-use note, never silently clipped.
The interval concerns the terminal price, not simultaneous coverage of a path.

### Publication-aware features and missing data

`build_research_inputs.py` fetches SEC companyfacts for 15 operating companies
(SPY is an ETF and deliberately excluded). Only standard US-GAAP annual USD
facts are used. Revenue periods are 330–400 days, growth compares the same tag
and comparable annual periods, and income/cashflow margins match revenue start
and end dates. Balance ratios use the same end date. Each snapshot uses only
facts filed by that snapshot's date. Backtests admit a snapshot strictly after
its filing date; later restatements do not rewrite earlier inputs. A 550-day
maximum age applies to the fiscal period end. Evidence retains tags, filing
dates, period ends and accession numbers. This reconstruction is not a certified
point-in-time vendor feed; current API history/taxonomy can still be revised.
Custom tags, quarterly earnings, guidance and earnings surprises are absent.

The crypto collector pages up to 90 days of initial hourly Hyperliquid funding,
and requests up to three years for the BTC/ETH/SOL pilot (younger venue histories
remain shorter). Paging checkpoints preserve progress. Requests are spaced by
the documented response-weight budget, targeting under 1000 weight/minute. It
then resumes from its cache and retains published complete days. SEC denials
set a 24-hour backoff; no alternate identity or route is attempted. Only 24-hour
complete days enter 7/30-day funding sums. The first observed daily circulating
supply and base-coin OI snapshots are retained across the weekly build; this
history cannot predate this dashboard's observations. Seven-day OI and 30-day
supply changes require actual prior observations. No historical supply is
invented, no present OI is inserted into old tests, and missing funding is not
zero. News, unlock schedules, on-chain flows and multi-exchange positioning are
not available yet. Provider access/rate failures stop further requests to that
provider and keep the dated old series.

A separate `enriched` log-median HGB adds these four inputs to the balanced
model. It needs at least 300 matured training rows with some added data over at
least 40 origins. Missing features remain missing (HGB handles NaN internally).
No enriched forecast is shown for an origin lacking every added feature. Its
later comparison uses exactly the same rows for enriched and balanced, and
reports how many rows/dates actually qualified. It is not in the selection gate
or automatically substituted for the original model. Funding/supply collection
alone must not be advertised as a validated annual crypto model.

`research/inputs.json` preserves compact dated source features; raw source cache
is ignored and cached in Actions. `research/environment.json` includes source
coverage and input hashes. `research/issued.json` preserves the first prediction
for each version/class/symbol/origin/horizon, together with actual issuance time.
This archive is groundwork for future prospective evaluation; no prospective
success rate is claimed. Run input collection before the model build. Both
accept `--offline` for existing local inputs. The Actions workflow runs on relevant
code updates and weekly, and tests filing leakage, incomplete funding days,
future-value invariance, calibration chronology and interval scoring.

SEC connection setup and supported file import are documented in [SEC-DATA.md](SEC-DATA.md).
