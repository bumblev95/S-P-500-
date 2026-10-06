# AdSense site-readiness review — 2026-10-05

This is a review of public content and implementation, not a Google approval
decision. No AdSense account review result, identity/payment status, account CMP
configuration or rejection reason was inspected. Google decides site approval.

## Findings and changes

| Observation before this change | Assessment | Concrete change |
| --- | --- | --- |
| The homepage initially consists mostly of JavaScript-populated prices, RSS translations and loading text; analytical value is difficult to understand without using the tools. | Inferred risk under original-content and inventory-value guidance, not a confirmed violation. | Four substantive static articles explain this site's TOP3, price rules, backtest limitations and news/sector calculations. A learning hub and methods page expose the actual rules and examples without JavaScript. The homepage links to these explanations. |
| A privacy page and named operator already exist, but site purpose, methods and corrections are not readily accessible from every main page. | Navigation and transparency improvement; an About/Contact page is not claimed to be a universal standalone approval requirement. | Static links on all 13 principal pages and the privacy page lead to the learning hub, methods, operator information, real GitHub Issues contact, privacy and use notices. No invented email, credentials or financial qualification. |
| Privacy disclosures describe advertising technologies, but do not explicitly explain prior-visit personalization or link to personalized-ad choices. | Specific gap against Google's required advertising-cookie disclosures. | Disclose prior-site/other-site visits, Google/third-party cookies and choices through Google Ads Settings and DAA. Keep analytics consent distinct from future advertising consent. |
| The hostname-root homepage retains old headings and asset versions. | The registered URL differs from the current project homepage. | Synchronize the current HTML into the root repository and the checked-in root wrapper, retaining the base URL and publisher ownership tag. Add canonical URLs. |
| No root robots/sitemap/ads.txt files are present. | Discoverability improvement. Google explicitly says ads.txt is recommended, not mandatory. It does not establish site approval. | Publish a crawlable root robots.txt, a sitemap of canonical pages and the standard Google seller line using the already supplied real publisher ID. The project sitemap remains available too. |
| Advertising loader is disabled and uses two separate manual placements when configured. | Existing behavior is appropriate for review preparation. | Preserve disabled ads and ownership meta tags; no ad slots, consent state, identity verification or account approval is fabricated. |

## Public pages

- `learn.html`: entry point and a map of what each screen means.
- `guide-top3.html`: relative ranks versus actual entry/holding states, a
  hypothetical score/rank example and close-date checks.
- `guide-indicators.html`: actual breakout/pullback rules, all nine states,
  hypothetical stop-risk/reward arithmetic and separation from AI research.
- `guide-backtesting.html`: costs, exposure, contribution concentration,
  directional baselines, downside recall, MAPE, survivorship/look-ahead bias and
  prospective versus retrospective records.
- `guide-news.html`: source and publication dates, automated translation and
  classification limits, hypothetical daily/week arithmetic and sector ETFs.
- `methodology.html`, `about.html`, `contact.html`, `terms.html`: implementation
  transparency, truthful operation information, a working public correction
  route and use limits.
- `privacy.html`: updated operational disclosures and existing analytics choice.

These explanations describe the current code; they are not copied articles or
claims that the trading strategy is profitable. There is no made-up approval
probability, mandatory post count or fabricated editor/expert credential.
Visible examples are explicitly hypothetical. Automated news summaries still
link to their original providers; attribution is not a license.

## Validation

`node scripts/check_site_information.cjs` checks internal destinations, static
navigation, canonical URLs, root-wrapper consistency and sitemap coverage.
`node scripts/check_site_information.cjs --browser` checks no-JavaScript reading,
navigation from the registered root URL, 320/375/768/1280px layouts and zero
external requests while reading explanatory pages. Existing ad and homepage
regressions remain in place. The advertising CI runs the new checks with
browser previews and never requests a real advertisement.

## Remaining review boundaries

Content quality, site/account approval and any account-specific errors remain
Google's judgment. There is no universal article-count or word-count threshold
established by the sources below. Additional original explanations should be
written when useful to actual readers, not padded for a presumed quota.

Before advertising activation, use the actual account's ad-unit IDs and
applicable Privacy & messaging/CMP settings. The existing analytics banner is
not an advertising CMP. The current changes do not enable advertising.

Commercial data/news reuse rights and hosting suitability are separate from
AdSense's decision. GitHub's current Pages terms limit using Pages to run an
online business while permitting some monetization; they do not state that
every ad-supported project is automatically prohibited. This review does not
claim hosting or third-party redistribution rights were granted. Resolve the
site's intended monetized use before activation, as described in the existing
[advertising guide](AD-MONETIZATION.md).

## Primary references checked

- [Site readiness and original content/navigation](https://support.google.com/adsense/answer/7299563?hl=en)
- [Publisher policies: inventory value, representation and privacy](https://support.google.com/adsense/answer/10502938?hl=en)
- [Required advertising-cookie disclosures and choices](https://support.google.com/adsense/answer/1348695?hl=en)
- [AdSense eligibility](https://support.google.com/adsense/answer/9724?hl=en)
- [ads.txt format, hostname-root placement and optional status](https://support.google.com/adsense/answer/12171612?hl=en)
- [Google CMP requirements](https://support.google.com/adsense/answer/13554116?hl=en)
- [GitHub Pages terms, effective August 27, 2026](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#pages)
