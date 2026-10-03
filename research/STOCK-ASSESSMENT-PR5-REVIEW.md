# PR #5 stock assessment code review

Review date: 2026-10-03 UTC. Code fixes and local regression checks are complete; actual rendering of this follow-up remains a manual check.

## Reviewed state

- Requested PR: https://github.com/bumblev95/S-P-500-/pull/5
- Original base: `9828c124f23b62394a490205f5185da2b61a54bd`
- Original head: `1af53a4f10bb6b67f9328666ca230d8f94643785`
- Observed state: PR #5 was already squash-merged as `4a60dc35fe25a3bf79e7a75dd2fb0524ab7f4d51`. Its description reports PC production-browser checks and leaves physical-phone testing open.
- Initial review baseline: main `1c6dc0e00a0cb31f590930adc4448ae585057948`.
- Final follow-up baseline: main `f2082c5b9399d1e6aeb5f946fddad724afc7f787`. This intervening automatic scorecard/market update touched data only; the follow-up was rebased onto it and the regression suites rerun.
- The UI difference between the requested head and this main was already-completed clarification of two legacy scoring explanations. Those corrections are preserved.
- Follow-up branch: `codex/review-stock-assessment-pr5`. The original closed PR and its branch are not rewritten.

## Findings and corrections

### PR #6 synchronization with main (2026-10-03)

- Preserve original PR #6 head `041ac105549aa60ba3b6db5383f9cc2fbbcc0d85` and merge main `896b0cddc89c1967e20eb01387d4d3dc9b10f302`; no history rewrite or automatic PR merge.
- Resolve five actual content conflicts: `advanced-legacy.html`, `advanced.html`, `assets/advanced-page.js`, `index.html`, and `scripts/test_technical_guide.cjs`. `assets/stock-assessment.js` merges cleanly and is checked for calculation parity.
- Keep main's company news/filings panels, Korean summaries, decision-support integrations, indicator badges, stylesheet/script dependencies, and FRED recovery. Retain the PR's normalized aliases, render/export expiry checks, overall AI performance gate, supported 126/252-day controls, deterministic sorting, and CSV reference/gate columns.
- Combine the advanced market header's shared freshness/indicator gate with main's grey unknown-state badge. Resolve class-ticker entry badges through the canonical assessment and keep the matching selected company's news panel.
- Bump common assessment and advanced-page asset versions so caches cannot reuse either pre-merge implementation.
- Local validation: 16 JavaScript suites and 72 Python tests pass. The 1,010 current stock/horizon evaluations preserve the original PR's score, trend, color, reference date/price, decision, reason, and model status against the identical latest-main snapshot. The 697 protected data/backend/decision/news/visual files are byte-identical to main. JavaScript/inline-script syntax, asset paths, workflow YAML, and whitespace checks pass.
- Extend the existing DOM tests to cover class-ticker visual badges/news selection, the grey unknown market badge, and selected-company news in the missing-horizon fallback.
- Real-browser validation is run by `Validate visual status indicators` after the branch update. Local Chromium installation is unavailable in this environment; physical-phone touch behavior remains a manual check. Workflow conclusions are recorded in the PR description once available.

| Priority | Reproduction / impact | Correction |
| --- | --- | --- |
| P1 | Advanced CSV rows use dotted class tickers, while `StockAssessment.all` indexes assessments by normalized hyphenated tickers. `BRK.B` and `BF.B` therefore lost valid scores of 47 and 37. | Normalize assessment lookup and resolve both spellings in raw forecast records. Table, inspector, CSV, comparison and validation use the same identity. |
| P1 | Advanced scores were refreshed only on data load or a horizon change. An ordinary render or CSV export after expiry could still use the earlier score and decision. | Reassess at render/export time. Expired prices produce an empty CSV score and `판단 보류`. Redundant recalculations during loading/horizon changes are removed. |
| P1 | A synthetic, internally inconsistent file with a stock marked `eligible` and overall `validation[h].passed=false` could still permit entry. Missing overall validation could also qualify solely through the individual status. | Display eligibility requires the selected horizon's explicit overall pass, in addition to the existing individual, reference-date, price-alignment and causal-training checks. Research forecast numbers remain independently available. Missing validation and a failed validation have different messages. This is enforcement of the existing producer gate, not a new model or training rule. |
| P2 | Legacy mobile sorting treated a real zero and a missing score as the same value and had no ticker tie break. | Shared score comparator: numeric score first, normalized ticker for ties, missing last in either direction. It is also used by the advanced score sort and home ranking. |
| P2 | Legacy forecast controls defaulted to 84 days and offered 21/84 days although the current file contains only 126/252-day forecasts. Dotted saved-watchlist symbols also failed in the forecast bridge. | Use supported 126/252-day controls, fall back from obsolete saved periods, and resolve saved ticker aliases. Guard missing prediction/previous records. The displayed legacy forecast is explicitly separate from the common score and AI entry validation. |
| P2 | Advanced market status checked only a four-day collection timestamp, while the entry gate checks a three-day timestamp and required indicator freshness. A fresh file with missing indicators could look healthy. | Use the same `TechnicalGuide.marketState` for the market header. Market state does not enter the trend score. |
| P2 | `family-v24-archive.html` is reachable from research navigation and still shows its old combined scoring and trading labels without an in-page archive warning. | Add a visible historical-rules notice and a link to the current assessment. Preserve historical formulas and saved browser records. |

The CSV also carries `scorePrice`, `entryDecision`, `modelStatus` and `assessmentHorizon` alongside `trendScore` and `scoreAsOf`. Its price column can originate from a different CSV snapshot, so the score's own reference price is explicit.

## Entire-repository display-path check

| Path | Score / ordering status |
| --- | --- |
| `index.html` candidate rail and selected detail | Shared assessment; score descending with ticker ties; missing scores omitted from candidates. Entry decision and AI status are separate. |
| `advanced.html` / `assets/advanced-page.js` | Shared table/inspector score, matching default ranking and current filtered CSV. User-selected column sorts remain explicit through the column arrow. Both horizon controls leave the observed-price score unchanged. |
| `advanced-legacy.html` picks, signals, watchlist, extrema and mobile cards | The main stock score comes from the shared assessment. Mobile ordering and forecast selection aliases are corrected. Saved manual valuation, notes and risk assumptions remain separate. |
| Legacy sector heatmap | Median of the same common scores; already labeled as a sector median rather than a stock probability. |
| Legacy earnings / value-trap / debt cards | Intentionally order their named category by earnings date, weak-score order or debt severity. They do not replace the stock trend score. |
| Legacy manual factor grades and valuation/risk labels | Separate reference values inside the manual-assumption disclosure, including valuation, growth, quality and 1–5 risk inputs. They do not contribute to the common trend score or its ranking. |
| `assets/forecast.js` | A separate legacy price-scenario display with supported horizons; no separate stock score. |
| `family-v24-archive.html` | Historical combined score retained and clearly disclosed as obsolete. It is not a current assessment path. |
| `script.js` | Old independent scoring code remains in the repository, but no current HTML entry point imports it. It has no active display path. |
| `trendInfo`, `confidenceScore`, `scoreFromGap` in the legacy source | Residual helper code does not render an alternative current stock trend rating; `confidence` is not displayed. Removing unrelated dead code is outside this correction. |
| Research/model-validation and crypto/futures/simulation pages | Named research metrics, model diagnostics and separate asset/account rules. No current stock trend-score formula is substituted into the stock UI. Account calculations are untouched. |
| `beginner.html` and the old sector-dashboard URL | Redirect to the current home/advanced pages. |

## Validation completed

- Original PR-head implementation versus follow-up: all 1,010 actual stock/horizon records (505 stocks × two horizons) preserve `score`, `trend`, `color`, `asOf`, `price` and `decision` at the same snapshot time.
- Common-assessment regression: valid entry control, withheld/failed/missing AI gates, bearish eligible horizon, unknown/risk market, stale/future/missing/price-misaligned/short-history records, missing or mismatched ticker identity, forecast independence, valid-zero/missing/tied ordering and both ticker spellings. A map-key/record-symbol mismatch is withheld instead of displaying another stock's score.
- Home DOM harness: candidate/detail parity, actual 126/252-day button events, missing-horizon fallback and expiry.
- Advanced DOM harness: class-ticker table/detail/CSV consistency, common default ranking, four views, horizon metadata, expired export without reload, missing required market indicators and failed refresh.
- Legacy DOM harnesses: shared watchlist score, saved notes/assumptions preservation, alias bridge, zero/missing/mobile order, mobile-mode expiry, old forecast preferences, supported controls and missing prediction records.
- Nine JavaScript suites passed: `test_stock_assessment`, `test_advanced`, `test_legacy_assessment`, `test_legacy_forecast`, `test_learned_guide`, `test_technical_guide`, `test_decision_support`, `test_trade_journal`, `test_forecast_path`.
- Python forecast suite: 13 tests passed.
- Changed JavaScript, inline scripts, workflow YAML and `git diff --check` passed.
- Protected model, forecast, market, price, fundamental, decision and simulation files are unchanged. Training/research/account update workflows are not changed or invoked; the follow-up branch only matches read-only validation workflows.

## Remaining manual rendering checks

The DOM harnesses execute event and markup logic; they do not verify CSS layout, SVG placement, touch behavior or a real browser's download flow. A local Playwright browser launch was unavailable because its Chromium executable is not installed. The earlier PC-production check in PR #5 does not cover this new follow-up.

Before merging this follow-up, inspect desktop and phone rendering of:

1. Home and advanced `NVDA`, `KEYS`, `BRK.B` and `BF.B`: score, score date/price, separate decision and AI status; switch 126/252 days.
2. Advanced score sort in both directions, saved watchlist, class-ticker comparison/validation, CSV download and its reference/gate columns.
3. A stale-price fixture, missing forecast/AI validation and missing market indicators: no accidental entry approval or stale numeric score.
4. Legacy mobile zero/missing ordering, class-ticker selection, 6-month/1-year forecast buttons and stored notes/manual assumptions.
5. Common-panel wrapping and tap targets, legacy SVG/chart fit, and the historical archive notice.

No merge or production deployment is part of this review.
