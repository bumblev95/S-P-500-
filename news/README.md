# Company news and preliminary impact

The home, advanced and saved-company detail pages show the selected company's
news first. SEC filings and estimated earnings dates remain in a collapsed
supplementary section. The same article labels and reasons appear on all pages.

`scripts/build_company_news.py` fetches Yahoo Finance's per-symbol RSS feed for
each current S&P 500 issuer. Share classes share one issuer and request. The
snapshot uses at most twelve relevant articles per issuer published in the last
30 days, in reverse publication order. It does not claim comprehensive coverage.
Company-name/ticker checks remove unrelated stories; short tickers require
explicit stock syntax. Personal inheritance/tax stories are excluded.

Impact labels are **headline-only preliminary interpretations**, with Korean
reasons and the exact matched headline phrases available in article details:

- 호재: concrete favorable developments such as an earnings beat, raised
  guidance, expanded shareholder returns, new products, contracts or approvals.
- 악재: earnings misses, lowered guidance, dividend cuts, litigation, product or
  security issues, financial/business risks or analyst downgrades.
- 혼재: both favorable and adverse developments in the same headline.
- 중립: a matched informational announcement such as a regular dividend or an
  upcoming earnings-call date, without an evidenced change in conditions.
- 판단 유보: insufficient evidence, questions, rumors, negation, opinions, or
  multiple named companies whose different impacts require reading the article.

Price movements alone are not evidence of a new favorable or adverse business
event. Analyst actions and product launches include reasons explaining their
limits. RSS excerpts are capped at 300 characters. Full articles are not read or
reproduced. Counts describe the displayed articles, not probabilities or a
company's overall outlook. Labels never affect stock scores, entry gates,
forecasts, model research, paper accounts or backtests.

Each issuer records its feed status, source hash, check time and last successful
observation. Failed refreshes retain articles with their original source clocks.
The UI distinguishes confirmed empty feeds, unknown coverage, read failures and
stale observations. Article timestamps must precede their observation and the
current clock; malformed/future dates and unsafe links are hidden. News and SEC
loads fail independently and refresh on the next visit/stock refresh after a
one-minute cache. Overlapping older responses cannot replace newer news.

The existing GitHub Pages deployment receives a refreshed snapshot on weekdays
at 14:15 and 22:15 UTC. The collector uses at most three concurrent requests,
pauses between requests, and stops unstarted requests after access/rate-limit
rejection or repeated transport failures. The persisted backoff lasts 24 hours
after access denial, one hour after repeated transport failures. A few already
in-flight requests can finish; no identity rotation or rejection workaround is
used. Raw feed captures are ignored under `research/source-cache/news`.

Reproduction and validation:

```sh
python scripts/build_company_news.py
python scripts/build_company_news.py --offline
python -m unittest discover -s scripts -p test_company_news.py
node scripts/test_company_news.cjs
node scripts/test_status_indicators_browser.cjs
```

Offline replay preserves capture times and does not claim a successful network
refresh. `--symbols NVDA,MSFT` refreshes only those issuers and retains all other
records. The collector writes only `news/latest.json` and request backoff state.
