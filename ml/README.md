# Learned forecast pilot

`pooled-hgb-price-v1` is an actual fitted histogram gradient boosting regressor,
not a language-model-generated price. It uses fixed parameters and pooled
price/volume features. SPY returns provide market context. The market warning
and Fed news panels remain separate; their current observations never enter
historical training examples.

## Reproduce

Use Python 3.11 and `scripts/requirements-ml.txt`. Run the public price updater,
`scripts/build_forecasts.py`, then `scripts/build_learned_forecasts.py`.
The updater downloads up to ten years of daily data, omits today's unfinished
session, preserves failed tickers' old snapshot dates, and stops new requests
when the provider returns 401, 403, or 429. It does not rotate endpoints.
Full input histories and model weights are local build inputs (gitignored).
Latest results contain their hashes, dependency version and fixed parameters.
The standard snapshot contains the last 126 actual daily closes for the UI.

## Chronological evaluation

Targets are log price returns after 21, 84, and 252 observed trading sessions.
Features at an origin use prices no later than that origin. Each horizon has
up to six test origins separated by max(horizon,126) SPY sessions, so their
outcome windows do not overlap. All stocks share the same time boundaries.
Training target end dates must precede the calibration start. Calibration
target end dates must precede the test origin. No random row cross-validation
or automatic early stopping is used. The final live fit follows the same split.
The calibration block deliberately sacrifices some training recency for an
honest held-out estimate of residual spread; this is a pilot tradeoff.

We report absolute return error (percentage points), direction agreement,
interval coverage, and distinct test dates. We compare on the identical
observations against both no-change and the existing fixed trend-decay model.
We do not call direction agreement an individual forecast's probability.

The promotion gate was fixed before inspecting results: at least four test
dates, return MAE at least 2% lower than both price baselines, direction
agreement no lower than always-up, and observed interval coverage at least 60%.
Both pooled and per-symbol results must pass, with aligned fresh current
prices. These are pilot eligibility checks, not statistical proof of skill.
No criteria are relaxed after a failed result. Forecasts that fail are stored
for research but not used as AI price lines or entry signals in the UI.

The 10th/90th percentiles of calibration residuals create a reference range.
They are not a guaranteed future 80% interval. The displayed line interpolates
the horizon endpoint; it is not a learned prediction for each intermediate day.

## Records and limits

`archive/YYYY-MM-DD.json` preserves first-issued records, including withheld
forecasts, for each origin. `validation/*.json` exposes the latest fold
predictions and cutoff dates. Future live outcomes need to accumulate; this
release does not claim live-trading performance or transaction-cost returns.

The dataset uses today's collected universe, so survivorship and selection
bias remain. Stocks at a shared date are correlated, not independent tests.
Per-symbol selection on backtests adds selection bias. Provider revisions and
split corrections can change reconstructed history. There is no point-in-time
fundamental or historical-news database in this model. The annual horizon has
particularly few independent observations, and abstention is expected.

Automatic updates run on weekdays after market close. A Pages build is
explicitly requested after publishing results so bot commits refresh the site.
Provider failure leaves the last successful forecast dates intact; the UI
rejects stale or misaligned results instead of treating them as current.

## Path illustration and additional comparison

The default wavy line is an explicitly labeled illustration. It resamples
five-session blocks of the last 126 observed closes' demeaned log returns,
with a deterministic symbol/date/horizon seed, then conditions the path to
end at the existing model endpoint. It changes neither the endpoint forecast
nor entry/exit levels. Excursions are not clipped to the reference band. It is
not a learned daily path or a forecast of when to buy a dip. The user can
switch back to the average direction; inadequate history disables sampling.

`build_forecast_comparison.py` compares no-change, trend-decay, and the fitted
model on stored out-of-sample records. A fourth research method chooses the
lowest-MAE candidate using only outcomes already matured before each test
origin, after at least two earlier test dates are available. All four methods
are compared on identical later dates. The table includes average and 90th
percentile absolute return errors, not portfolio losses or maximum drawdown.
This rule was devised retrospectively and needs prospective evaluation. It
does not replace the production forecast, alter promotion gates, or claim to
identify the best possible model. The comparison refreshes with daily builds.
