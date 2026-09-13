# Price forecast gate study — fixed before challenger results

Registered 2026-09-13 after inspecting the production model and earlier failed
stability, adaptive, SEC/ranking and methodology experiments. This is a new
finite experiment on previously explored history, **not an untouched holdout**.
The candidate family, calendar and gates below may not be changed after results.
Implementation corrections must be recorded, with all affected outputs rebuilt.

## Question and data

Can direct price loss, more recently matured training labels, and separate market
and company components improve 126/252-session terminal price forecasts while
also passing our unchanged production direction/recall/coverage requirements?
The user's 5–10% annual price-error ambition is reported separately from relative
improvement over a baseline. Neither is guaranteed by a historical gate.

Frozen input: the existing 509-file quote/volume archive from the methodology
audit, SHA-256 `5bf33128f82381c31ac97563aac099d22d1242febea44b0dee30e4ddda04662c`.
It contains approximately 20 years through 2026-09-11. Use Yahoo quote closes
(split adjusted, cash dividends excluded) and actual volumes. No synthetic
volume, revised SEC values, contemporary analyst estimates or future market
prices enter historical predictors. Current S&P 500 universe is frozen from
this repository; survivorship bias and historical quote revisions remain.
Use one share class per issuer, as selected by `research_universe.load_universe`.
SPY supplies the market series and is not scored as a stock.

The current production source and `ml/validation/{126,252}.json` are hashed.
Long-history control reruns the production point algorithm with the longer data;
it is explicitly distinct from the already published 10-year-data forecasts.
Also compare with those archived predictions on identical symbol/date/target
rows, checking every matched target numerically and reporting unmatched rows.

## Time split and selection

Use a 21-session SPY training grid anchored to the first session on/after
2014-01-01. Primary forecast origins are h sessions apart on this phase, starting
in 2011 for interval warmup. Targets use each stock's h-th observed session;
exclude targets beyond the next primary origin to prevent overlap. Primary
selection uses origins from 2014 with all targets strictly before 2019-01-01.
Later evaluation uses origins from 2019 with targets available by 2026-09-11.
Archive-date comparisons are secondary and never count as extra independent
primary dates. A 500-stock date remains one market observation.

Refit every origin. All challenger training targets, including the target of a
market residual, must end strictly before origin. Train-only imputation/scaling;
within-date ranks use no future rows. The main control retains its existing
extra training/calibration separation. No random split or early stopping.

Select once per horizon using earlier primary outcomes only: prefer candidates
whose earlier point errors beat no-change/trend and whose point directions beat
always-up with down recall >=10%. Among those minimize date-mean MAPE + .25*p90.
If none meet the screening conditions, use that objective over all challengers
and mark the choice provisional. Freeze before evaluating later results. Publish
all candidates, including unsuccessful and better-looking unselected candidates.
No second parameter search on the later table.

## Fixed candidate family (12 challengers, 3 controls, both horizons)

HGB parameters equal production: 60 iterations, 15 leaves, LR .05, minimum leaf
40, L2 10, random seed 17, early stopping false. Challenger weights balance each
training date to equal aggregate weight, normalized to mean one. Gross return
is future price / origin price; predictions must be finite and positive.

| ID | Fixed method |
|---|---|
| noChange | Gross return 1 |
| trend | Existing production decaying trend |
| mainLongHistory | Existing log-squared-error HGB, existing training cutoff, extended frozen history |
| freshLog | Log-squared-error HGB, all matured monthly labels |
| freshMedian | Gross-return absolute-error HGB, all matured monthly labels |
| freshMape | Same, inverse-gross-target weights for direct price MAPE |
| recentMedian | freshMedian with origins in preceding six calendar years |
| ownMedian | freshMedian excluding market21/market63/relative63 |
| ownMape | freshMape with the same three columns excluded |
| robustLinear | Huber log-return regression, epsilon 1.35, alpha 10, max_iter 500, train-only standard scaling |
| marketResidual | Log residual HGB on own features plus their within-date ranks; target log return minus shrunk trailing beta × realized market return; forecast market return with median of matured SPY monthly targets from prior ten years; 50% shrinkage of predicted company residual |
| marketState | Same residual; market forecast half historical median, half Ridge(alpha=100) on SPY's 16 own features, fitted on distinct market dates |
| linearResidual | Ridge(alpha=100) log company residual on same own/rank features; same historical market median and 50% residual shrinkage |
| equalBlend | Arithmetic mean of gross freshMedian, marketResidual, robustLinear |
| recentBlend | Arithmetic mean of gross freshMedian, recentMedian, marketState |

Beta uses 252 past daily return pairs, minimum 200, shrunk halfway to 1 and
bounded [-.5,2.5] before observing targets. Market residual labels use SPY prices
at the exact stock origin/target dates, and those target dates must have matured.
No class balancing, sign forcing, threshold tuning or filtering on future error.
All candidates are scored on precisely the same rows.

## Intervals, metrics and gates

For challengers use matured prior primary out-of-sample log residuals divided by
known origin volatility84 × sqrt(h/252), floor .03. At least three prior primary
dates; at most 12. Equal aggregate weight per date; weighted .1/.9 quantiles,
including zero in the offset interval. This empirical interval has no formal
coverage guarantee. Archive comparisons may use only matured primary residuals.
Main control also uses this common interval procedure for the new experiment;
its point algorithm and training separation are unchanged. Published archive
forecasts retain their original intervals.

Return MAE = mean |predicted gross - actual gross| (origin-price percentage
points). Price MAPE = mean |predicted gross/actual gross - 1|. Report both,
date-mean MAPE, p90 MAPE, fraction within 10%, ±2% direction accuracy, always-up,
down recall/precision, range coverage, per-date and individual-stock counts.

1. **Production gate unchanged:** >=4 disjoint dates; return MAE < .98 times
   the better of noChange/trend; direction accuracy strictly > always-up;
   down recall >=.10 when >=20 actual down cases; interval coverage >=.60.
   This is tested by calling the existing `qualifies` function. Individual-stock
   gates and fresh/aligned input checks are still required for live eligibility.
2. **Additional price gate:** >=6 later disjoint dates; date-mean MAPE < .98
   times the best of noChange/trend/mainLongHistory; p90 no worse than all three;
   win on >=60% of dates against all three; down precision >=down prevalence;
   upper 95% paired-date bootstrap error difference <0 against each control.
   Fixed seed 17, 5,000 resamples. Descriptive intervals on reused, correlated
   market history are not fresh statistical discovery or future guarantees.
3. **Earlier environment research gate diagnostic:** retain its >=6 dates,
   >=5% date-mean log-MAE improvement vs mainLongHistory/noChange, no worse MAPE
   and p90, >=60% date wins, direction > always-up and both controls, recall>=10%.
4. **5–10% target:** disclose whether annual date-mean price MAPE <=.10 and <=.05.

No automatic production promotion, even if historical checks pass. Save one
first-issued research forecast snapshot with code/input/protocol hashes so new
outcomes can eventually be evaluated. Never overwrite an earlier issued record.

## Verification and stopping rule

Verify source archive and every raw file hash, exact archived target agreement,
all temporal cutoffs, nonoverlap and row parity. Recompute all summary metrics
from saved outcome rows. At a fixed 2023 primary origin remove all later raw
prices, rebuild features/labels and refit every challenger: predictions must
match the original historical fit (tolerance 1e-10). This is a reproduction and
leakage check, not evidence of predictive skill. Stop after this family; do not
add candidates in response to later scores. Report the actual limiting gates.

## Primary sources and hypotheses

- [Gneiting, Making and Evaluating Point Forecasts](https://arxiv.org/abs/0912.0902):
  choose the evaluation loss first; motivates direct median/MAPE training, not
  a stock-accuracy guarantee.
- [Gu, Kelly & Xiu, Empirical Asset Pricing via Machine Learning](https://www.aqr.com/Insights/Research/Journal-Article/Empirical-Asset-Pricing-via-Machine-Learning):
  nonlinear interactions and price/volatility signals motivate tree/linear
  comparisons; their risk-premium setting does not establish our price target.
- [Wang et al., Forecast combinations review](https://robjhyndman.com/publications/combinations/):
  motivates fixed mixtures to reduce dependence on one model; does not prove
  that these particular mixtures work.
- [Forecasting: Principles and Practice, accuracy](https://otexts.com/fpp3/accuracy.html):
  test future outcomes and naive baselines, and distinguish MAE from MAPE.
- [scikit-learn HGB documentation](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html):
  implementation semantics; runtime versions are recorded with results.

Foundation-model weights were not run: a pretraining overlap audit and an
appropriate multi-year stock validation would be needed before making claims.
