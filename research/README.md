# Public environment model comparison

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
