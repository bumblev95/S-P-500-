# Search discovery — 2026-10-14

The hostname homepage is already indexed. Keep its existing canonical URL
`https://bumblev95.github.io/` and its project mirror; do not split the same
homepage into two competing search results. The project sitemap contains only
23 canonical URLs under `/S-P-500-/`. The root sitemap contains those URLs plus
the canonical homepage, including the previously missing selling guide.

Search Console inspection showed the project homepage unknown to Google but
the hostname homepage submitted and indexed (last crawl October 6). Therefore
the project homepage inspection is not evidence that the entire site is absent
from Google. The project property returned no page/query rows for September 14
through October 11. No settled-through boundary was available.

The submitted project sitemap was `sitemap.xml/`, pending. The correct URL is
`https://bumblev95.github.io/S-P-500-/sitemap.xml`, with no trailing slash. The
connected GSC Wizard account has read-only Google scope: it can inspect results,
but cannot submit sitemaps or request indexing. No indexing submission is claimed
by this code change.

All 24 public pages now have response-HTML metadata and schema. Editorial guides
have visible breadcrumbs, related links, a named author and matching update dates.
Dashboard pages use WebPage rather than claiming to be researched articles.
The homepage and stock screen link directly to the selling guide. Guide titles
describe questions already answered in the body: stop-loss, partial selling,
moving averages, RSI, breakouts, pullbacks and backtest limitations.

Run `node scripts/build_search_metadata.cjs` after changing titles, descriptions,
guide dates or the page list. It also synchronizes the root homepage copy and
both sitemaps. `node scripts/check_search_discovery.cjs` verifies those outputs.
Sitemap lastmod dates come from visible editorial update dates. Live dashboard
dates are omitted because the underlying market data changes independently.

The hostname repository must receive the synchronized homepage and root sitemap.
Its robots.txt must retain other projects' directives and advertise this project's
sitemap as well. Preserve unrelated application files in the hostname repository.

Reference: Google Search Central JavaScript SEO documentation:
https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics
Static response content, real anchor links, distinct titles/descriptions and
consistent canonical signals improve discoverability; they do not guarantee
indexing, ranking, traffic, or any search-result enhancement.
