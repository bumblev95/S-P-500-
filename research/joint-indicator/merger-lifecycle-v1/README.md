# Shareholder lifecycle after mergers and delisting

This separate outcome layer follows evidenced cash, replacement shares and
contingent rights while retaining the original frozen-origin security row.
It distinguishes **shareholder total return** from **the original issue's price
target**. It does not change the previous PIT/FJA bundles or any model result.

**Historical readiness remains 0/34. No real return has been calculated.** The
real bundle contains one unresolved WBA closing observation with its original
SEC payload, not a complete corporate-action/price/identity dataset. None of
the numeric test fixtures are historical observations or model backtests.

## Rules fixed before use

| Case | Accounting | Original price target |
|---|---|---|
| Completed cash acquisition | Verified cash per held unit; cash stays idle to horizon | Not applicable after original issue extinguished |
| Completed stock exchange | Verified new issue ID and exact per-unit replacement quantity; value at explicit target timestamp | Never substitute successor's price |
| Cash plus stock/rights | Track every delivered asset and cash leg | Not applicable after original issue extinguished |
| Multiple acquisitions | Follow A → B → C holdings under the original A evaluation row | Still not an A price series |
| Dividend/distribution | Add verified cash or separate issued asset; no reinvestment | Original issue's own split-adjusted price excludes these distributions |
| Split | Change units, require unadjusted quotes to avoid double counting | Compare on the initial-share basis |
| Unresolved contingent right | Preserve right and block full return, even if a maximum cash amount or purported quote exists | No fabricated value |
| Confirmed cancellation with no recovery/rights | Retain genuine zero wealth and the original row | MAPE unavailable for an extinguished issue |
| Index removal or ticker rename | No assumed sale; follow stable issue ID | No splice based on ticker spelling |
| Settlement after target | Preserve unvalued receivable; do not assign later cash to earlier horizon | Extinguished original issue remains not applicable |

The frozen policy is gross **USD**, with zero interest on paid cash, no fees,
taxes or dividend reinvestment. FX, investor elections/rounding and fractional
cash-in-lieu must not be guessed. The provider must document exact normalized
per-unit entitlements; unsupported circumstances stay blocked.

Start with one unit at the last completed, unadjusted USD close that was known
before the existing PIT origin cutoff. The accounting window starts at that
quote timestamp. The target is an **explicit exchange-session timestamp**;
the engine does not infer holiday schedules, market closes or a fixed horizon
from a date string. No terminal information selects the origin population.

## Files and commands

- `PROTOCOL.json`: registered accounting, clock, population and metric policy.
- `lifecycle-inputs.json`: source registry, normalized table contract, unresolved
  WBA observation; all actual asset/action/quote/coverage tables are empty.
- `sources/wba-20250828.html.gz`: unchanged original SEC payload and checksums
  copied from the frozen PIT source. No later settlement evidence is assumed.
- `manifest.json`: input/protocol SHA256 plus 71 preserved earlier-file hashes.
- `coverage-audit.json`: replayable 34-origin blocked report, no computed return.
- `INPUT-CONTRACT.md`: normalized provider fields and integration API.
- `FINDINGS.md`: Korean implementation and current evidence status.

From the repository root:

```sh
python -m unittest discover -s scripts -p test_merger_lifecycle.py -v
python scripts/build_merger_lifecycle.py --verify
python scripts/build_pit_sp500_inputs.py --verify
python scripts/audit_fja_sp500_quarantine.py --verify
```

The actual export gate, against the incomplete checked-in bundle:

```sh
python scripts/build_merger_lifecycle.py --export-outcomes \
  --origin 2009-11-13 --target-at 2010-11-15T21:00:00Z \
  --evaluated-at 2026-10-08T00:00:00Z \
  --output research/joint-indicator/merger-lifecycle-v1/origin-outcomes.json
```

This **must exit 2 without creating a file**. Both earlier cohort exports also
remain blocked. A different real normalized dataset requires a new frozen
bundle, complete origin inputs, evidence hashes and an explicitly registered
session/feature/evaluation protocol. Do not overwrite earlier results.

## Metrics and limits

`LifecycleInputs.ledger` verifies the unchanged complete cohort against the
original PIT object and returns one row for every original security. Each row
includes accounting trace, asset positions, cash, provenance and blockers.
Synthetic evaluation is explicitly marked `synthetic_fixture` and cannot
qualify as real research evidence. The normal file loader rejects synthetic
sources; only tests opt in.

`evaluate` requires explicit, separately named total-return-factor and
original-price-factor forecasts. It never treats existing price predictions
as total-return predictions. Return MAE in percentage points and direction
recall require **all** cohort returns, including genuine zero wealth. Full
population original-price MAPE is unavailable if any original security is
extinguished, missing, or has a zero denominator. No survivor-only subset is
silently scored; no model is trained or promoted.

Coverage must independently attest corporate actions, distributions, identities
and terminal status for every held security/right segment. Good quotes and a
merger press release are insufficient. Original PIT terminal blockers also
apply to successor holdings; a new evidenced PIT correction is needed to
resolve one. Corrections apply only after their original `knownAt`. Missing
target quotes are not forward-filled. Same-time dependent transformations need
evidenced sequencing. A later payment to an already extinguished issue must be
normalized as a residual right or a correction, never silently discarded.

Validation: **43 new + 96 preserved local tests = 139**. The unscheduled,
read-only CI runs 111 stdlib lifecycle/PIT/quarantine tests, all three audit
replays, 71 preserved hashes, and all three fail-closed export gates. The other
28 model-regression tests were run locally with the existing scientific stack;
no prior experiment was regenerated.
