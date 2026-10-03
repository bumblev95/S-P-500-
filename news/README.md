# Korean company news and preliminary impact

The home, advanced and saved-company detail pages open with a short **Korean
news summary**, followed by its impact and a plain-language reason. The original
English headline, supplied excerpt, exact evidence and source link remain
available in expandable details. SEC filings and estimated dates are supplementary.

The collector requests Yahoo Finance RSS once per current S&P 500 issuer, shared
across share classes. It retains at most twelve company-related articles from the
last 30 days. This is the coverage of the supplied feed, not exhaustive reporting.
Names/tickers must match the headline; unrelated inheritance stories and known
foreign-ticker/sibling-vehicle collisions are excluded.

`company-impact-source-v2` uses issuer-anchored clauses from the English headline
and **complete sentences** in the supplied excerpt (capped at 300 characters).
It does not read article bodies or use translated text as classification evidence.

- 호재: favorable reported developments, including an earnings beat, raised
  guidance, shareholder returns, new products, contracts and business expansion.
- 악재: misses, lowered guidance, dividend reductions, litigation, product or
  security issues, strikes and other evidenced business burdens.
- 혼재: favorable and adverse company developments are both evidenced.
- 중립: an evidenced informational event without a direction in financial impact,
  such as a leadership change or a regular dividend.
- Unclear records remain unclear in data. The screen calls these 참고 뉴스 or
  추가 확인, explains the missing evidence and groups them under reference news.

Business developments appear first; analyst views are identified as 분석가 의견.
Within each group, publication order is retained. Price moves, buying comparisons
and records without sufficient company-impact evidence remain accessible in the
reference section. Earnings schedules and ADP macro statistics are supplementary
there, rather than filling the main company-news list. Counts describe articles
with a supported interpretation; they are not probabilities or an aggregate
company outlook. A positive price-target opinion is distinct from actual results.

Rival actions and a brokerage/ratings firm's actions on another issuer are not
attributed to the selected issuer. Shared subjects can share a stated event.
Rumors, conditional or negated events are not treated as completed business
changes. A factual complete lead can clarify a question in the headline. Product
upgrades are not stock-rating upgrades, and future earnings beats are unconfirmed.

## Korean summaries

`scripts/translate_company_news.py` selects one short complete event sentence or
the headline and translates it on the workflow runner, using the offline
[Meta NLLB-200 600M translation model](https://huggingface.co/facebook/nllb-200-distilled-600M)
(CC BY-NC 4.0; model use is restricted to noncommercial purposes), via CTranslate2. No translation API key or browser translation is
required. This is a translation of supplied short metadata, not a full-article
or generative analysis. Proper names can retain their original spelling.
The tokenizer sets English input and Korean output explicitly. A smoke check
verifies product-recall meaning, a financial term and numeric preservation.

Summaries checked against their provided source are stored in
`news/korean-reviewed.json`, bound to its exact headline/excerpt hash. Changed
source text cannot inherit a reviewed summary. Machine translations are cached
by exact passage and translator version. Output additionally stores its source
headline/excerpt, which the UI compares before display. Missing or failed Korean
translations get a Korean unavailable message and the English source remains
available in details. The site does not claim these translations are error-free.

## Collection and freshness

The existing GitHub Pages site refreshes on weekdays at 14:15 and 22:15 UTC.
Collection is followed by Korean translation before the snapshot is published.
At most three feed requests are in flight, with pauses. Access denial stops
unstarted requests and persists a 24-hour backoff; repeated transport failures
persist a one-hour backoff. Failed refreshes retain original source clocks.

Dates must precede observation and the current clock. Unsafe links, malformed
and future dates are hidden. News and SEC loads fail independently, retry on
a later refresh and share a one-minute cache. Older overlapping responses cannot
replace newer data or the selected stock. Translating/reclassifying a retained
snapshot does not change publication, collection or observation times. Neither
news data nor labels affect forecasts, stock assessments, models or trading data.

## Reproduction and validation

```sh
python scripts/build_company_news.py
python scripts/build_company_news.py --offline
python scripts/build_company_news.py --reclassify
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r scripts/requirements-news-translation.txt
python scripts/translate_company_news.py
python -m unittest discover -s scripts -p 'test_company_news*.py'
node scripts/test_company_news.cjs
node scripts/test_status_indicators_browser.cjs
```

Offline replay preserves capture times and does not claim a successful network
refresh. `--symbols NVDA,MSFT` only refreshes those issuers. Raw RSS captures,
translation models and translation caches are ignored under research/source-cache.
