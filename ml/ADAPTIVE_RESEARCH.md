# Completed-error adapter experiment

Version `completed-error-adapter-v1` is a correction layer on the existing
`pooled-hgb-pattern-v2` stock forecasts, not a newly trained foundation model.
It addresses repeated forecast bias and performance differences between stock
trend/volatility groups. It does not add unobserved news or fundamentals.

## Frozen protocol

Two candidates were specified before reading their later evaluation scores:

* `biasCorrected`: add half of the date-weighted median historical log residual
  to the original AI forecast.
* `regimeBlend`: combine original AI, unchanged price and trend in log space.
  Weights are half equal weights and half inverse historical return MAE plus a
  0.25 tail-error penalty, then add half the median blend residual. Use the
  stock's above/below 200-day average and above/below 40% annualized volatility
  group only with at least 4 completed origins and 60 observations; otherwise
  use the pooled correction.

Both fit only earlier **out-of-sample** forecasts with targets strictly before
the new forecast origin. A complete date block must mature before inclusion.
Use up to 12 disjoint return windows. Return windows are `(origin, target]`,
so adjacent windows may share a boundary close. Each origin has equal total
weight regardless of its stock count. No future result clipping or random
train/test split is used. Current trend features use the same formula as the
incumbent, from the date-aligned public input snapshot.

The first half of adapter evaluation origins selects one of the two candidates
using only results that matured before the later half began. Selection loss is
date-weighted return MAE + 0.25 * date-weighted 90th percentile error. All models
are compared on the identical later rows. The selector is not changed after
seeing later outcomes. Later fitting continues walk-forward using only results
available at each origin; it is an adaptive algorithm, not a fixed coefficient
model. Shared dates are not statistically independent trials across stocks.

Historical checks require 4 later origins, 2% lower MAE than all 3 baselines,
no worse tail error than all baselines, wins on at least 60% of later origins,
and direction accuracy at least both original AI and always-up. These checks
are research checks; they **never automatically replace the live chart**.
Existing historical periods have been explored in previous experiments, so
this split is not an untouched final holdout. No significance claim is made.

Each candidate gets its own interval only after 3 earlier completed adapter
evaluation origins and 60 rows. Residual 10/90 weighted quantiles are centered
on its current forecast, including the center. Coverage is measured only on
forecasts that had a band at issuance. Sparse histories leave bands missing.

## Publication and reproduction

Run `python scripts/build_adaptive_research.py` using `ml/latest.json`, matching
`ml/validation/{21,84,252}.json`, and `forecasts/latest.json`. No full price
redownload is needed. All source model train/calibration target dates are
checked to precede their forecast origins. A mismatched source snapshot fails
closed. Runtime dependency is NumPy (pinned in the workflow).

`ml/adaptive.json` contains current candidates; `ml/adaptive-summary.json` is the
small browser payload; `ml/adaptive/*.json` preserve reproducible historical
experiment rows. The main page's “모델 개선 실험” panel reports improvements and
failures together, including the unchanged default model status.

`build_decision_support.py` records every available candidate, including failed
and missing-interval candidates, with the actual recording timestamp in the
immutable public ledger. Past experiments are not inserted as live predictions.
Only the existing prospective promotion policy can replace a future research
forecast. Model identities include both adapter version and underlying model.

The experiment concerns stocks. Existing crypto models and their validation
remain separate. This experiment is not a trading strategy or realized P&L.

## First run, 2026-09-12

The earlier-period selector chose bias correction for 21 sessions and regime
blending for 84 sessions. On the identical 4 later origins, respectively:

| Horizon | Original return MAE | Selected adapter MAE | Change vs original |
| --- | ---: | ---: | ---: |
| 21 sessions | 7.05 percentage points | 7.29 percentage points | 3.4% worse |
| 84 sessions | 16.52 percentage points | 15.87 percentage points | 3.9% better |

The 84-session tail error fell from 35.02 to 33.10 percentage points, but
direction accuracy fell from 38.00% to 37.15%. It did not beat all simple
baselines by 2%. Neither candidate passed all checks. The 252-session source
has only 5 origins and no completed adapter test origins after the warm-up.
No default model was replaced. Subsequent automated runs may differ as more
outcomes become available; the immutable live ledger is separate.

## References

* [Time series cross-validation](https://otexts.com/fpp3/tscv.html)
* [Scikit-learn gradient boosting losses](https://scikit-learn.org/stable/modules/ensemble.html#gradient-boosting)
