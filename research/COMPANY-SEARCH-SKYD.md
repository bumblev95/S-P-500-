# PSKY / SKYD company search compatibility

## Identity and reproduction

PR #56's Advanced research run [38473259151](https://github.com/bumblev95/S-P-500-/actions/runs/38473259151)
failed in `scripts/test_company_search.cjs`: `SKYD requires a display label`.
The unmodified main checkout `d9f41c114c75a56ee822ffcce4f84e5e5859c68f`
reproduces that assertion. Its fundamentals snapshot has 503 rows and records
`SKYD` with the older provider name `Paramount Skydance Corporation`.

The [issuer's October 2, 2026 8-K](https://ir.paramount.com/static-files/36b6ca19-67e4-4787-94ee-8c4c1373e0ac)
announces the same Class B common stock's Nasdaq/PSKY -> NYSE/SKYD listing
transfer and corporate name change to Skydance Corporation effective October 6.
The [issuer's warrant FAQ supplement](https://ir.paramount.com/node/73436/html)
also describes that transfer, and explicitly separates the SKYDW warrants.
That FAQ URL is an announcement/FAQ, not a completed-change 8-K.
The already-reviewed repository provider registry and captured provider evidence
in [EOD-PSKY-2026-10-06.md](EOD-PSKY-2026-10-06.md) identify CIK 2041610,
Class B common stock and Yahoo's `Skydance Corporation` metadata.

These layers serve different purposes:

| Layer | Key / behavior |
| --- | --- |
| Dated EOD registry | Retains logical `PSKY`; maps provider `yahooSymbol` / `nasdaqSymbol` to `SKYD` starting 2026-10-06. Unchanged. |
| Supplied snapshots | May already use `SKYD`, including current fundamentals and prices. Keep those keys and supplied English names unchanged. |
| Search catalog | Retains historical PSKY label and adds current SKYD label, with reciprocal ticker and former/current name search terms. |

No alias is inferred for PARA, WBD or SKYDW. A name prefix such as `PARA` can
still match `Paramount` under the existing partial-text search; that is not a
registered security alias. An exact available PARA ticker wins over that prefix.
WBD -> TWLO remains a constituent replacement, not a security rename.

## Changes and resolution policy

- Keep `PSKY`: 파라마운트 스카이댄스 / Paramount Skydance Corporation.
- Add `SKYD`: 스카이댄스 / Skydance Corporation.
- Both rows can be found by PSKY, SKYD and Korean/English former/current names.
  The catalog English name is searched even when the source still supplies an
  older name. Source names remain unchanged for display/export fallbacks.
- Search remains constrained to the supplied rows. A PSKY-only historical
  snapshot resolves SKYD to that PSKY row; a SKYD-only snapshot resolves PSKY
  to that SKYD row. Search never invents a second ticker or fetches provider data.
- If both rows exist, exact tickers select their respective rows. Shared names
  remain ambiguous until the user selects a row. Financial values, dates and
  archive keys are never merged or copied between the two rows.
- Duplicate rows of the same normalized ticker still produce one suggestion.
  Different share classes and unrelated issuers with shared names stay distinct.
- After SKYD was fixed, the same coverage gate exposed missing TWLO and VYLR
  labels. Add editorial Korean labels 트윌리오 and 바일러 for these already
  supplied constituents, with their original English names. This changes no
  membership, price collection or recommendation rule.

## Regression and validation

`scripts/test_company_search.cjs` covers current/former Korean and English names,
lowercase/full-width ticker aliases, combinations of names and actual row tickers,
partial search, repeated rows, shared-name ambiguity, exact-ticker precedence,
unavailable securities, unrelated merger/warrant identities, frozen catalogs,
browser UMD loading and combobox selection of the actual source key.
Synthetic historical PSKY and current SKYD financial rows verify separate prices,
EPS, dates, keys and original English names through screener filtering and CSV
export, without mutation. These synthetic values are test fixtures, not research
or investment evidence. The real supplied snapshot also exercises name searches.

The existing Advanced research command sequence is retained, including syntax,
company search, advanced UI, forecast and EOD pipeline checks. Additional checks
exercise the existing dated PSKY provider boundary and historical publication
replay. Remote CI results and PR #56 integration checks are recorded in the PR
description after the final code is validated.

## Scope and PR #56 compatibility

This patch changes only the company-name catalog, search terms, company-search
tests and this note. It shares no changed paths with PR #56's freshness patch.
Production prediction models, TOP3 recommendations, trading rules, publication
gates, provider routing, historical archives and operating snapshots are untouched.
The separate PR remains Draft; no production merge or publication is requested.
