# Learned forecast pilot

`pooled-hgb-pattern-v2` is an actual fitted histogram gradient boosting regressor,
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
up to twelve test origins separated by max(horizon,63) SPY sessions, so their
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

`archive/YYYY-MM-DD[-model].json` preserves first-issued records, including withheld
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

## Prospective scorecard and private plans

`score_live_forecasts.py` evaluates immutable first-issued archives against the
close after 21/84/252 observed sessions. `live-results.json` separates eligible
predictions from withheld research records. Unfinished outcomes have null
metrics, not zero accuracy. Late publication, revised anchors (>0.5%), and
missing origin history are flagged instead of silently scored. Full downloaded
history is preferred; the public 126-close snapshot is a fallback and cannot
resolve long-horizon outcomes with missing full history. Daily overlapping
forecasts and correlated stocks are not independent observations. The scorecard
is forecast evaluation, not executable strategy returns or verified profit.

The beginner page has entry and holding modes. Holding mode suppresses current
new-entry advice and compares saved personal criteria with latest analysis.
Original criteria never move automatically. Historical checks use available
closes strictly after the save date; they do not detect intraday breaches.
Price revisions flag the position for review rather than report misleading P/L.

Personal plans are user-owned JSON documents downloaded/imported explicitly.
The editor working copy lasts only for the current page session; the downloaded
file is the durable record, required again on the next visit. No localStorage
or public repository contains holdings. No server receives form values.
There is no account synchronization, order execution, or background alerting.
P/L excludes fees, dividends and FX. Imported plans are validated atomically;
conflicting IDs are rejected instead of overwriting original records.

## Pattern model v2 and common horizon path

V2 adds causal exponentially smoothed RSI, price-normalized MACD/signal
residual, 50-day-average slope and relative-volume momentum. Features use only
observations through each forecast origin. These are numeric price patterns,
not named chart-pattern detection or historical news analysis. A fixed HGB
configuration is retrained for each of 21, 84 and 252 observed sessions.
The fold budget is 12 with disjoint outcomes; available annual history may
permit fewer. The original MAE, coverage and minimum-date gates remain.
Direction metrics now consistently use the UI's ±2% neutral category.

Validation includes per-date and historical regime diagnostics (200-day
average, volatility and RSI groups). These are descriptive subsets of the
same out-of-sample data, not separate independent proofs or tuned gates.
V2 archives include the model ID in filenames; V1 issue records remain intact.
The prospective scorecard includes the current model only, so a newly revised
model cannot inherit the older model's results.

The displayed common path connects the chosen 21/84/252 endpoints, with each
endpoint's AI eligibility shown. A failed horizon retains its explicitly
labeled trend fallback; no unvalidated AI endpoint is promoted for visual
consistency. The 21- and 84-session views are exact prefixes of the 252-session
view, including the reference band and deterministic five-session bootstrap
illustration. The bootstrap is pinned separately at each endpoint. Interior
values are interpolation/illustration, not learned daily forecasts, and an
annual endpoint alone does not validate any shorter horizon.

## Relative-price-error stability experiment

`build_stability_research.py` adds one fixed weighted absolute-error HGB
(target = future/current price, weight = current/future price). Its weighted
absolute training loss corresponds to actual-future-price-relative error.
A predeclared 50% blend with no-change is another candidate. Neither changes
the production model, forecast path, promotion gates, or issue archive.
All comparisons use identical production OOS stock/origin rows and input hashes.

Starting from the earlier half, a calendar-only boundary advances if needed
to retain two fully matured selection origins and at least two later origins.
This boundary never depends on observed candidate accuracy. Selection is among no-change, trend, existing
AI, relative-error AI and the 50% blend. The fixed selection objective is
equal-date mean MAPE + 0.25 * pooled p90 absolute percentage error. Selection
labels must mature strictly before the later evaluation begins. The chosen
method remains fixed across that evaluation; later training may use only data
available at each origin, as in the existing rolling forecasting protocol.
These historical periods have been inspected in prior research, so they are
held out from this selection, not genuinely unseen prospective evidence.

The research gate requires at least four later dates, 2% improvement in
date-mean MAPE over all three original candidates, p90 no worse than both
simple baselines, wins against both simple baselines on at least 60% of dates,
and direction agreement at least as high as always predicting an upward move
above 2%. All conditions are set before this experiment's results. Even a pass
is not an automatic promotion or proof of future skill. Pooled MAPE, p90 and
within-10% share are published alongside the checks; none is trading return.
Only five annual origins currently exist, limiting the later annual sample.
The experiment refreshes in the daily pipeline after the chronological audit.
