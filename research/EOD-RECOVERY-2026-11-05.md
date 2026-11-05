# EOD / TOP3 recovery review — 2026-11-05

Status: proposed code only; owner approval required before merge, EOD publication or deployment. No production model, price, forecast, archive, or market snapshot is changed by this PR.

## Root causes

- Run 41937163111 attempted the 2026-11-04 EOD transaction four times. Each attempt downloaded 505 price rows and built 503 ready forecasts. The unchanged publication gate rejected KVUE's old session each time. There were no raw-data artifacts on that failed run, so the audit below is a fresh reproduction, not a claim to reconstruct the exact runner payload.
- Kimberly-Clark's November 2 announcement says KVUE trading ceased before that day's open. Its final session is October 30. S&P's October 30 announcement replaces KVUE with OKTA before the November 4 open. This is a constituent replacement, not a price-history alias to either OKTA or KMB.
- The saved public universe still contains KVUE. The external constituent CSV observed during this investigation now contains OKTA instead. The existing dated replacement mechanism is necessary for the saved-public-universe recovery mode and protects against delayed upstream lists.
- The watchlist configuration supplies Google's `pubhtml` HTML view. Converting that recognized Google URL to `pub?...&output=csv` returned `text/csv`, a `symbol` column, and zero data rows. The warning is separate from the stale KVUE constituent. Malformed CSV remains a warning; no rows are silently skipped.
- The homepage browser test seeded healthy synthetic cards with `home.json.rankings.asOf`, which was null during the outage. Healthy tests now use a fixed session, and the real outage is checked separately. Additional legacy/advanced assessment tests used the newer market clock against older prices; their healthy clocks now use the price snapshot, with explicit expiry tests retained.

## Source comparison and safe recovery choice

| Source / mechanism | Finding | Use |
| --- | --- | --- |
| Kimberly-Clark corporate announcement | KVUE ceased trading at the November 2 open | Authoritative last-session boundary |
| S&P Dow Jones Indices announcement | KVUE → OKTA effective November 4 | Dated, count-preserving universe replacement |
| Fresh Yahoo history | KVUE ends October 30 at 19.309999 (CSV precision) | Historical observation only |
| Stock Analysis historical table | October 30 close 19.31, inactive; no later trades | Independent corroboration only |
| Kenvue stock lookup / syndicated quote pages | A displayed lookup date or repeated quote is not proof of a trade after the halt | Never accepted as a November 4 EOD bar |
| Existing Nasdaq one-bar recovery | Requires a same-session incomplete Yahoo bar, matching OHLC and three preceding closes | Inapplicable to a security that stopped trading |
| Existing verified symbol transition | Requires the same reviewed security identity | Inapplicable to the KVUE acquisition |

Sources:
- https://kimberlyclark.gcs-web.com/news-releases/news-release-details/kimberly-clark-completes-acquisition-kenvue-creating-preeminent
- https://press.spglobal.com/2026-10-30-Okta-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600
- https://stockanalysis.com/stocks/kvue/history/
- https://investors.kenvue.com/stock-info/default.aspx

## Actual collection audit

Baseline: main commit `af1d73d6662bbd4632354a3f2f716bfe197897ad`; fresh download completed at 2026-11-05T09:11:15+00:00. All 505 symbols were audited for price date, collection timestamp, forecast/chart/history agreement, final OHLCV and November 2–4 bridge sessions.

- 504 rows: November 4; no other endpoint, timestamp, OHLCV or bridge-session anomalies found.
- KVUE: October 30, close 19.309999, no November 2–4 sessions. Original all-symbol validation failed as expected.
- Forecast readiness: KVUE stale; VYLR has 25 actual history rows and lacks 3- and 6-month return inputs. VYLR's latest price is valid; its missing predictions must remain missing. A ready-forecast count is not a count of valid downloaded closes.

Corrected full live collection completed at 2026-11-05T09:20:29+00:00; no network mocks or replayed prices were used. All 505 independently collected current-universe rows are dated November 4. The unchanged `eod_publication.validate` passed all 505 prices, histories and forecast/chart endpoints, with no missing November 2–4 bridge sessions.

- Forecasts: 504 ready; VYLR remains missing because of its short history. All 505 have history.
- Unchanged ranking model: 504 eligible, 3 buy-side and 3 sell-side cards; six distinct symbols, all November 4. Buy-side: ACGL, ACN, AJG; sell-side: CAT, CMI, FIS. These are technical priority lists, not newly validated investment recommendations. The buy-side cards retain `자료 확인` because the separate market-risk gate is unavailable; no positive buy signal was invented.
- OKTA uses its own Yahoo history and symbol. Yahoo close 191.050003 agrees with Nasdaq's $191.05 at cent precision; open/high/low also match at cents. Vendor volumes differ (Yahoo 3,679,200; Nasdaq 3,679,902); neither was relabeled or substituted. Nasdaq source: https://api.nasdaq.com/api/quote/OKTA/historical?assetclass=stocks&fromdate=2026-10-21&todate=2026-11-04&limit=20
- Validated CSV SHA-256: `b89b29c30e7cabf6113389a59803841a7b918f14bb5056dfc7d56d445919c218`.
- Validated forecast JSON SHA-256: `6a0196a1cffa639568c92bfb3aaedfcf6ccfd2dd34c675977156f4fbf72d2840`.
- These outputs remain isolated validation data; none were staged for live publication.


## Regression verification

- Python EOD suite: 65 tests passed, including existing 505-row atomic Git/research replay tests and five new KVUE/CSV regressions.
- Python homepage suite: 100 tests passed.
- Forecast model tests: 14 passed; price pipeline tests: 4 passed.
- Node homepage, entry, advanced, company search, canonical assessment, legacy assessment/forecast, technical, learned and decision-support suites passed.
- New boundary tests reject post-retirement KVUE, pre-effective replacement, a missing OKTA download and an unrelated stale symbol before Git staging; independent OKTA data passes the original atomic gate. New price-expiry assertions reject all scores after six days, even with newer market metadata.
- Browser checks cover the real empty snapshot, deterministic healthy/risk/empty/stale cases, 320–1440 px, themes, navigation, cache wrapper compatibility, periodic updates, failure retention and recovery. The successful GitHub run produced review screenshots. Mobile empty-state screenshot was inspected.

## Approval scope and operational limits

Approve merging PR #67 and then collecting the latest settled session through the existing atomic publisher, rebuilding TOP3, and publishing Pages. Merging the registry change triggers the existing EOD workflow; the home workflow follows a successful publication. A successful Pages build alone is insufficient: require the EOD gate, current matching price/forecast dates, and three valid cards on each side when enough symbols are eligible.

The model formulas, freshness windows, ranking policy, Nasdaq evidence checks, all-symbol publication gate and historical issued forecasts remain unchanged. Unknown missing/stale prices still stop publication. There is no invented price, backdated issuance, previous-session relabeling, history splice or fallback to KMB prices.

## Successful GitHub code checks

Code commit `e98c9f0c075f7461a2f47df342b6cd6b53b6942a`:
- Atomic EOD: https://github.com/bumblev95/S-P-500-/actions/runs/42000685719
- Homepage + browser: https://github.com/bumblev95/S-P-500-/actions/runs/42000685946
- Consistent assessment: https://github.com/bumblev95/S-P-500-/actions/runs/42000685909
- Advanced research: https://github.com/bumblev95/S-P-500-/actions/runs/42000686600
