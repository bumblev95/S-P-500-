# Daily homepage TOP 3

The homepage contains buy TOP 3 and sell TOP 3 only. These are daily priorities
for reviewing a stock, using existing observed-price assessments. Inclusion in a
relative ranking does not change a stock's actual entry or holding signal.
The shared caption and each card's status make this distinction visible.

## Selection

Only fresh, positive prices with a finite 0–100 assessment score and valid plans
are eligible. Use the latest eligible close date for both lists; do not mix
older sessions. Normalize and deduplicate symbols before selection.

Buy priority: actual `buy`, then `breakout`/`pullback`, `riskwait`,
`overextended`, `confirm`, `watch`, market-only `unavailable`, and `avoid`.
Stocks with a holding `reduce` signal come last. Within a group, sort by existing
trend score descending and normalized symbol ascending for ties. This favours
existing entry setups over chasing a higher-scoring extended stock.

Sell priority: `reduce`, then `protect`, then `hold`; within each group use trend
score ascending and normalized symbol ascending. Exclude every selected buy.

At least six valid same-date stocks produce exactly three distinct stocks per
side, including days with no actual buy or reduce signals. Fewer valid stocks
produce fewer cards rather than synthetic entries or duplicate recommendations.
`selection: signal` denotes an actual buy/reduce signal; `selection: relative`
denotes a relative candidate. Original `code`, `holdingCode`, score and reason
remain in the snapshot. A market warning or missing market data never becomes
an actual buy: the card still shows the original condition, and delayed market
data is disclosed alongside the ranking date.

The selector is a display policy, not a newly validated trading strategy.
`StockAssessment`, `TechnicalGuide`, research/backtests, AI promotion and paper
accounts retain their existing rules.

## Refresh

The existing hourly workflow and successful price/market completion triggers
recalculate both lists. `--rankings-only` publishes the lists before external
news/translation work, preserving the recap, stories and cache byte-for-byte.
Polling/evaluation timestamps alone do not cause a commit. Source timestamps,
ranking dates, statuses and order still count as changes. No new close on a
weekend/holiday means the same latest trading-session ranking.

The browser re-fetches every five minutes while visible, and on return to a tab
after one minute. Failed refreshes retain already loaded data with an explicit
delay message; expired quotes are suppressed. Changed source files also trigger
the collector. CI checks selection completeness, signal labels, no overlap,
staleness, deterministic ties, no-op publication, refresh recovery, responsive
layout and existing stock links.
