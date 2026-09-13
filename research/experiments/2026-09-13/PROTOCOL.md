# Stock validation experiments — 2026-09-13

This protocol is fixed before fitting the new comparisons. The previously reviewed
v7 historical evaluation is development evidence, not an untouched holdout.
Production price models and their promotion conditions are unchanged.

## Inputs and scope

- Baseline: `8738ee7986676f34d2e154da7c810ba4442908d8`.
- `research/environment.json` SHA-256:
  `287f4280b23def1489ad7062fbe35994f56f20ca7bd756bedb9bad85a374b08a`.
- Use the archived stock universe, issuer representatives, origins and outcomes.
- E0 primary source is `independentReturn`, chosen from the preceding research
  report, before this experiment. `secDynamics` remains an archived comparison;
  no second set of calibration fits is selected from it.
- All training and calibration outcomes must have `targetDate < origin`.
- Selection uses the archived earlier selection dates whose outcomes matured
  before the later evaluation starts. Never change thresholds after seeing later results.

## E0: six calibration configurations

For each of 126 and 252 trading days, compare:

1. Unmodified down-class raw score.
2. A monotone binary sigmoid fitted to the last eight matured OOS origin dates.
3. The same sigmoid fitted to the last four matured OOS origin dates.

The archived multinomial calibration is a fixed control, not a new fit. The
sigmoid uses the logit of the down score, a positive slope bound of `1e-6`, an
unpenalized intercept and slope penalty `0.5 * 0.01 * slope**2`. Optimize the
date-weighted mean binary log loss; initialize at slope 1 and intercept 0.
Require at least three matured dates and 20 observations of each binary class.
Insufficient calibration is explicitly unavailable, not silently replaced by raw.

Use a date-weighted prior down frequency from the same eight available dates
as the probability baseline. Compare every method on the same complete rows.
Report binary Brier score, log loss, equal-date ROC AUC and average precision,
fixed-threshold (`p >= 0.5`) recall/precision and coverage, and top-20%-risk
precision as a capacity diagnostic. Top-20% is not an optimized threshold.
Report probability reliability by the fixed intervals [0,.2,.4,.6,.8,1].

Select among the two fitted sigmoids using earlier date-mean Brier score;
ties are broken by the fixed method name. An earlier candidate must improve
both Brier score and log loss over the prior and have date-mean AUC > 0.5.
If none qualify, select no calibrator. Report all later results regardless.
Later eligibility requires the same checks plus at least six dates. No risk or
price promotion follows from this reused historical evaluation.

## E1: four 12-month ranking configurations

Use two fixed models (Ridge with intercept; the existing horizon's HGB
regressor) and two targets (absolute log return; log return minus SPY log
return over the identical stock target dates). SPY future return is a label
component only, never an input. Keep all available issuer representatives.

The common feature set is the existing `w` field and its two regime flags.
For Ridge, use past-training medians, explicit missing indicators for every
column, training standardization, and fixed alpha 100. HGB retains the current
252-day capacity and absolute-error loss. Weight each training origin equally
in both models, with weights rescaled to a mean of one. Ridge uses squared error. The model comparison includes these
fixed model-specific losses; the target comparison holds each model fixed.

Use archived 252-day fold dates, selection boundary and samples. Publish all
four models. Select only on earlier equal-date Spearman IC, with deterministic
ties, and require positive mean IC and an improvement over the fixed 180-day
momentum score. Later outcomes cannot select a model or a feature set.
Record predicted-return MAPE and the original v7 controls as diagnostics;
relative scores are never converted into absolute price forecasts.

Primary ranking metrics: equal-date Spearman IC, fraction of positive dates,
and paired differences versus 180-day momentum. For economic diagnostics,
take the top 20% of available issuers, equal weight, enter at each stock's next
trading close after the forecast origin, and hold to the archived horizon end.
The holding period is consequently one close shorter than the prediction label.
Account for both purchases and
sales at predeclared 5/10/25 bps per side. Compare to the same investable
sample, momentum selection and SPY. Do not annualize these sparse portfolios
or claim a continuous tradable strategy. Report exposure and missing-price
coverage. A positive historical result alone does not authorize promotion.

## E2: two conditional data increments

Audit recovered SEC companyfacts before fitting. Reconstruct available-date
quarterly observations from standard tags, retaining filing/accession evidence.
Distinguish standalone quarters from cumulative cash flows. Use only data
available strictly before each prediction date. Require data coverage and
restatement/quarter/corporate-action checks before model comparisons.

Only if E1 has an earlier eligible model and compatible inputs are available:
add dated quarterly changes, then add dated valuation inputs, for two further
fixed configurations of the earlier-selected E1 model. If historical shares,
corporate-action alignment or filing vintage is unavailable, do not substitute
current valuation or pretend the missing comparison ran. Record the block.

## E3: verification and stop decisions

Use meaningful chronology and truncated-future-data invariance checks before
any expensive run. Verify restored price history against the archived price
hashes and every matched target return; fail rather than silently changing the
sample. Record code/input hashes, attempted configurations and errors.

Report paired date-level uncertainty; do not bootstrap stock rows as independent
market trials. The eight annual evaluation dates are too few for precise claims.
No existing historical period is relabeled as untouched. Truly prospective
verification needs predictions issued before outcomes occur and their maturity.
E0 failure does not block E1 because E1 does not consume the probability scores.
E1 failure blocks additional fitting in E2; the data quality audit still runs.

Budget: six E0 + four E1 + at most two E2 configurations. Fixed controls and
diagnostic summaries remain disclosed. New model/feature/threshold searches
require a new named protocol, not undisclosed retries until a gate turns green.

The same four E1 configurations are also fitted on matured labels at the latest
available origin and issued once with the actual UTC completion timestamp.
This is a research record, not production promotion or a fifth configuration.
Preserve the first issuance on reruns. A tradable evaluation must enter at the
first closing price strictly after issuance, not at the already observed anchor.
Future outcomes are pending; these records cannot validate the model today.
