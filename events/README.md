# Company event timeline

The stock home, advanced inspector and saved-company detail show company news
with preliminary impact labels first (see `news/README.md`). The selected
company's dated SEC event cards and earnings estimates remain in a collapsed
supplementary section. The stock, spot and futures trade calculator UI has
been removed. Saved watchlists, notes and valuation assumptions are unchanged.

## Sources and dates

`scripts/build_company_events.py` uses the current `research/universe.json` CIKs
without refreshing or modifying membership. Multiple share classes share one
SEC request and issuer event list. It publishes `events/latest.json` only; no
event is a model feature and no research input, filing-date rule, frozen history,
vintage, forecast or backtest is rewritten.

- SEC Submissions API: the latest 180 calendar days, up to 20 supported filings
  per issuer (8-K variants, 10-K/Q, 20-F/40-F, 6-K and DEF 14A). Cards use
  **filingDate**, never reportDate as an announcement date. Amendments remain
  separate accessions. Column alignment, CIK, accession, document path, source
  observation time and future acceptance/filing dates are checked.
- 8-K item labels are neutral translations of the official form headings.
  1.01 means a material agreement disclosure; 2.02 is results/financial condition.
  7.01 and 8.01 do not prove a guidance change, regulation, dividend or buyback.
  These cards summarize the **reported topics**, not an automatically read filing
  body. The exact transaction terms and statements remain in the original.
- Company original earnings releases: existing immutable `research/earnings.json`
  records for NVDA/MSFT. GAAP quarterly revenue and explicit management revenue
  guidance are displayed where available. Guidance presence is not a claim that
  guidance increased or decreased.
- Upcoming earnings: fresh (at most 8 days old), error-free Yahoo fundamentals
  calendar observations, today through 120 days ahead. Always labeled **예상**;
  no guessed fiscal dates or automatic promotion to a confirmed company date.

The XOM archive CIK exception uses the already reviewed predecessor in
`sec_fallbacks.PREDECESSORS`. Other accession prefixes are never treated as CIK
aliases because filing agents can submit for another issuer.

## Collection and reproduction

The workflow runs after US trading days and after earnings/fundamentals updates.
It requires the existing `SEC_USER_AGENT` secret (application name and real
contact email), sends it only to SEC, and uses one serial request per CIK with
a 0.3-second interval. It shares the stock research concurrency group. HTTP
401/403/429 stop the batch with a persisted 24-hour backoff; three consecutive
transport failures stop it for one hour. There are no identity rotations or
access-denial workarounds.

Per issuer, `sec.status`, `checkedAt`, `lastSuccessAt`, canonical `sourceHash` and
`rejectedRows` record what was checked. Global coverage and error codes distinguish
fresh, captured, failed and uncollected sources. Failed refreshes preserve
previously obtained events and their observation times. A new `generatedAt`
does not make an old source fresh. The UI distinguishes collection delay and
unknown coverage from an actually checked empty event list.

Normalized metadata and original-release hashes are public. Raw SEC submissions
and their observation timestamp/hash are cached in the already ignored
`research/source-cache/events`. `python scripts/build_company_events.py --offline`
replays them without network access or advancing their observation time. The
initial seed also reuses hash-verified Submissions captures from the existing
2026-10-01 SEC audit with their original manifest `acquiredAt`. It does not claim
fresh API collection for uncovered issuers.

Checks:

```sh
python -m unittest discover -s scripts -p test_company_events.py
node scripts/test_company_events.cjs
# With Playwright installed (BROWSER_BIN is optional):
node scripts/test_status_indicators_browser.cjs
```

Browser coverage includes 320/390/1280 px, date cards and open details, changing
companies and horizons, missing event feeds, existing gauges and saved records.

Primary references:
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- https://www.sec.gov/files/form8-k.pdf
