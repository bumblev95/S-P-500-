# Official quarterly earnings learning

This free-source pilot collects original NVIDIA and Microsoft quarterly earnings
releases from fiscal 2014 onward. It does not require an API key or contact SEC.
It is not an earnings feed for all 500 stocks. Publication gaps and provider
errors remain visible in `earnings.json`; unsupported issuers have missing values.

The collector stores publication date, fiscal period, source URL, content hash,
GAAP revenue and diluted EPS with comparable prior-year figures, net income, and
explicit next-quarter NVIDIA revenue guidance. It validates issuer, fiscal quarter,
column order, and monetary units. EPS comparisons use values in the same original
release so stock-split bases match. Negative prior EPS uses its absolute value as
the growth denominator; this is a change ratio, not ordinary percentage growth.
Analyst-consensus surprises and narrative sentiment are not collected or inferred.

Imported releases are never overwritten. Backtests use them strictly after their
publication date and within 200 days of fiscal period end. Missing values remain
missing. These are historical corporate pages reconstructed today, not a certified
vendor vintage feed; an old page may have been corrected before our first retrieval.
Yahoo snapshots are separately accumulated with their original observation times
in `fundamental-observations.json`. They are not injected into historical training.

`environment-challenger-v3-official-earnings` fits the existing fixed HGB model
with four extra quarterly features alongside available SEC annual features. Its
parameters were not tuned on this experiment's results. Three models are compared
on identical held-out issuer/date rows: price and market context (`balanced`), the
same inputs plus only financial-data availability (`availabilityControl`), and
actual financial values (`enriched`). The availability control helps distinguish
financial information from an advantage due only to which companies have data.

Training targets must finish strictly before each prediction origin. Validation
windows do not overlap within each horizon. The fixed later block, previously
used in this research project, is not untouched prospective evidence. Scores
include price MAPE, logarithmic error, tail error, and three-way direction
accuracy (up >2%, flat within ±2%, down <-2%). Always-up direction accuracy uses
the exact same rows. The small issuer universe and correlated observations limit
generalization. These are forecast errors, not strategy returns or trading wins.

After US trading days, a separate workflow checks new company releases and
retrains stock research at 02:55 UTC Tuesday–Saturday (20:55 Saskatchewan
Monday–Friday). Newly published features become usable after their release date;
training on their subsequent price response waits until that horizon has actually
elapsed. Existing weekly SEC/crypto research retains its schedule and 24-hour SEC
backoff. The daily earnings workflow makes no SEC requests. A denied company-host
request stops that host and records a one-day local backoff. Current missing
quarters retry the next day; old unresolved pages retry after 30 days.

New results and first-issued predictions are saved and displayed on
`model-validation.html`. Research does not automatically replace the production
`pooled-hgb-pattern-v2` model or change paper-account trading rules. A stocks-only
run preserves the last crypto comparison, including its original model/date.

Reproduce with:

```sh
python scripts/build_earnings_inputs.py
python scripts/build_environment_research.py --stocks-only
python -m unittest discover -s scripts -p test_earnings_inputs.py
python -m unittest discover -s scripts -p test_environment_research.py
node scripts/test_environment_page.cjs
```

Use `--offline` for either builder to consume saved inputs without network access.
Normalized dated features are committed; source HTML and price histories are
Actions caches. Output records hashes of the training inputs for audit.

## Initial completed run — 2026-09-13 UTC

Actual training output: `environment-challenger-v3-official-earnings`, generated `2026-09-13T00:33:18.243074+00:00`.

105 original releases: NVDA 53 (2013-05-09–2026-08-26) and MSFT 52
(2013-10-24–2026-07-29). NVIDIA FY2016 Q4 remains missing; it was not
invented or filled with a current snapshot. All 105 retained feature rows were
checked again against their cached original HTML. Separately, 502 current Yahoo
observations were preserved for forward accumulation, not historical training.

| Horizon | Matched dates / rows | Context MAPE | Earnings MAPE | Context direction | Earnings direction | Always-up direction |
|---|---:|---:|---:|---:|---:|---:|
| 21 sessions | 9 / 18 | 6.29% | 6.33% | 22.22% | 38.89% | 38.89% |
| 84 sessions | 9 / 18 | 13.79% | 14.53% | 55.56% | 61.11% | 72.22% |
| 252 sessions | 8 / 16 | 33.07% | 32.47% | 68.75% | 68.75% | 68.75% |

These are matched NVDA/MSFT results from the fixed later block, not whole-site
production performance. Each date contains two companies; it is not two
independent market observations. Directions include a ±2% neutral band.

The earnings model produced **no downward predictions in this matched later
block**, including 16 upward annual predictions out of 16. The upward bias is
not resolved. The one-year MAPE improvement is modest; short-horizon MAPE worsens.
The availability-only control also matches or exceeds earnings direction accuracy
in all three horizons. This does not establish incremental financial predictive
power. The production model is therefore not replaced.

| Horizon | Latest training rows | Rows with dated financial inputs | Availability-control MAPE | Earnings p90 error |
|---|---:|---:|---:|---:|
| 21 sessions | 14397 | 1312 | 6.35% | 12.46% |
| 84 sessions | 14221 | 1290 | 14.39% | 30.58% |
| 252 sessions | 13677 | 1222 | 33.00% | 49.73% |

Financial training rows are weekly issuer/origin examples reusing quarterly
releases, not that many independent earnings announcements. Training and test
labels are strictly separated by time. Source dates, hashes, and row counts
are recorded in `environment.json`. New financial inputs affect prediction
after publication; fitting their realized response requires waiting for the
corresponding forecast outcome to mature.

Validation: eight collector tests, nine environment tests, five existing input
tests, four SEC-import tests, and the JavaScript page checks passed. The crypto
comparison and previous issued-record prefix were preserved. SEC was not contacted
by this implementation or the new daily workflow.
