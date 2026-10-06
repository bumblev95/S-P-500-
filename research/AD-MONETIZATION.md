# AdSense connection

The homepage and stock page now have one manually placed horizontal display ad each. Ads are **disabled**: the owner's publisher ID (`ca-pub-9723666081819297`) and ownership meta tag were supplied on 2026-10-04, but site approval and ad-unit identifiers are still pending. Disabled or invalid configuration makes no advertising request and leaves no placeholder. The loader waits until the user approaches the bottom of the content, loads the provider once, and collapses unavailable or unfilled ads. It does not change stock rankings, forecasts, or trading signals.

## Finish the account connection

1. Create or open the owner's [Google AdSense account](https://adsense.google.com/start/). Register the public hostname without a path. For the current GitHub Pages deployment this is `bumblev95.github.io`, not `bumblev95.github.io/S-P-500-/`. AdSense accepts platform subdomains on the public suffix list; `github.io` is on that list. Approval and identity/payment steps belong to the account owner; adding code alone does not approve the account or guarantee revenue.
2. Resolve the hosting decision before enabling advertising. [GitHub Pages terms](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#pages) restrict use as free hosting for an online business. They permit some monetization such as donation buttons, but do not establish approval of this site's proposed advertising business. Seek GitHub's confirmation or use hosting that permits this use. Keeping the source on GitHub is separate from where the public site is served.
3. The owner's `google-adsense-account` meta tag is in `index.html`, `stocks.html`, and the published [hostname-root homepage](https://bumblev95.github.io/). The root repository [bumblev95/bumblev95.github.io](https://github.com/bumblev95/bumblev95.github.io) was created and published on 2026-10-04 from `main` / `/(root)`. [Pages deployment 37190174241](https://github.com/bumblev95/bumblev95.github.io/actions/runs/37190174241) succeeded for commit `7f2751fd7f704033daa164028f8c1bf5f2c7bdbc`; the live homepage rendered market data and the matching ownership tag without an advertising-provider script. In AdSense select **Meta tag**, confirm the code was inserted, and press **Verify**. The screenshot initially selected the script method. Resolve the hosting decision in step 2 before requesting site review. Successful hosting and a matching tag do not mean Google has verified or approved the site.
4. Create display ad units for the homepage and stock page. Copy the real `data-ad-client` (`ca-pub-` plus 16 digits) and the real `data-ad-slot` values from the account's ad-unit snippets.
5. Update `assets/site-ads-config.js`: the publisher ID is already filled; supply `slots.home` and `slots.stocks` from the real ad-unit code. Leave `enabled:false` during account/site review. Only change it to `true` after the site is approved, hosting permits the use, privacy disclosures are accurate, and the account's applicable **Privacy & messaging** settings/CMP are configured. Keep Auto ads, anchor/vignette formats, ad-size optimization, Fill empty in-page ads, and automatic refresh off for this small manual placement design. Create responsive display units: each page uses Google's approved expandable-width/fixed-height approach with in-page CSS (90px desktop, 100px mobile) and omits the automatic-format/full-width attributes.
6. Use a Google-certified CMP where required for European/UK/Swiss visitors; the account can configure Google's CMP. This loader is **not a CMP** and does not replace the account's consent setup. Review `privacy.html` against the actual hosting, advertising and data providers before activation; this operational disclosure does not certify legal compliance.
7. The 2026-10-05 readiness update prepares the standard Google seller line using the already supplied real publisher ID for the **public hostname's root**: `google.com, pub-9723666081819297, DIRECT, f08c47fec0942fa0`. It belongs in `ads.txt` at the top level of [bumblev95/bumblev95.github.io](https://github.com/bumblev95/bumblev95.github.io), served at `https://bumblev95.github.io/ads.txt`. A file under `/S-P-500-/ads.txt` is not the hostname root. Compare with the account's snippet if it reports an ads.txt issue. ads.txt is recommended, not mandatory, and publishing it does not mean approval or activation.

The [2026-10-05 public-site readiness review](ADSENSE-READINESS.md) adds original screen-specific explanations, methods/operator/contact pages, navigation, updated privacy choices, canonical URLs, sitemap and a synchronized root homepage. It records the limits of this review and does not claim Google approval.

The publisher and slot IDs are public advertising identifiers; no password, API key, banking detail, or tax information belongs in this repository. Media.net remains an alternative, but its account-issued tag would need to be supplied and reviewed rather than guessed. This change implements AdSense only.

## Verification

`node scripts/test_site_ads.cjs` checks disabled/missing/malformed/example IDs, page placements, footer links and source consistency. `node scripts/check_site_ads_browser.cjs` tests disabled zero-request behavior, one provider load across units, filled/unfilled ads, blocked provider scripts, repeated initialization, and responsive layout. Browser tests intercept all provider traffic and use synthetic ad identifiers; they never request a live advertisement.

## Official implementation references

- [Site address format](https://support.google.com/adsense/answer/2784438)
- [Accepted platform subdomains](https://support.google.com/adsense/answer/12170421)
- [Create a user-root GitHub Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)
- [Connect your site and verify with a meta tag](https://support.google.com/adsense/answer/7584263)
- [Where to place ad unit code](https://support.google.com/adsense/answer/9190028)
- [Responsive ad tag parameters](https://support.google.com/adsense/answer/9183460)
- [Approved expandable-width/fixed-height ad code](https://support.google.com/adsense/answer/9183363)
- [Hide only confirmed unfilled units](https://support.google.com/adsense/answer/10762946)
- [Google CMP requirements](https://support.google.com/adsense/answer/13554116)
- [How Google's CMP works](https://support.google.com/adsense/answer/16918505)
- [Publisher privacy disclosures and content policies](https://support.google.com/adsense/answer/10502938)

Market-data and news rights still need to allow the site's intended commercial use. Advertising account/site approval does not grant a license to redistribute a provider's market data or articles.
