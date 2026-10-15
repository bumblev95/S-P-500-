# Market observation and entry-state contract

## Incident reproduced

[Crypto run 38427020378](https://github.com/bumblev95/S-P-500-/actions/runs/38427020378)
checked out `ce4bfc5f2521acf6ad8fb91be91562a88c311bfa`. Collection, learning and
crypto page/perpetual checks succeeded; the stock-only `test_technical_guide.cjs`
then asserted that `marketState(snapshot, generatedAt) === credit.status`.
Publication and the Pages refresh were skipped.

The snapshot was generated at `2026-10-13T11:11:56.571358+00:00`. Its aligned
FUNDING observation was dated `2026-10-08`. The producer discarded the time of
day (`now.date()` and integer `.days`) and marked it ready at age 5. The entry
guard correctly measured 5.46662698 elapsed days, exceeding the existing 5-day
limit, and returned `unknown`. A reduced historical fixture is checked in at
`scripts/fixtures/market-freshness-2026-10-13.json`.

## Field meanings

| Field/result | Contract |
| --- | --- |
| `generatedAt` | Snapshot construction time; never the observation date. |
| `asOf` | Real observation date, interpreted at 00:00 UTC for age checks. |
| `maxAgeDays` | Inclusive elapsed-day limit (`seconds / 86400`), including weekends. No day rounding or extra holiday allowance. |
| `indicator.status` | `ready` only within the observation's limit; otherwise `stale` or `missing`. New builds apply the actual build clock to fetched and cached observations alike. |
| `fetchStatus`, `lastSuccessAt` | Transport/provenance. A successful fetch may contain an expired observation; it cannot renew `asOf`. A failed fetch may retain a still-fresh observation. |
| `credit.status` | Existing severity/coverage aggregate of available credit families. It is not entry permission. Its thresholds, family votes and minimum coverage are unchanged. |
| `TechnicalGuide.marketState()` | Entry context: snapshot age must be 0–3 days; NFCI, STLFSI4, DRTSCILM and FUNDING must each be ready and within their limits (16, 16, 150 and 5 days by default). Missing/expired required inputs turn stable/watch into `unknown`. A `risk` warning is retained only while the snapshot itself remains fresh. |

Even with corrected indicator freshness, `credit.status` can be stable while
`marketState()` is unknown: three available families can support the aggregate
without the mandatory FUNDING input. Tests must assert each contract rather
than equate them. In the replay, the corrected producer emits stale SOFR and
FUNDING, credit coverage 3/4 (missing short-term funding), and the consumer still
returns unknown. Existing stock prediction models and TOP3 selection/entry/
holding rules are unchanged.

The frontend independently rechecks ages so older published snapshots and
snapshots that expire after loading remain conservative. Source caches retain
their original dates and last-success timestamps. Boundary checks cover the
exact limit and one millisecond on either side.

## Validation ownership

- `update-crypto.yml` keeps the crypto data/model tests and runs mandatory
  `bash scripts/check_crypto.sh` after building snapshots and before publishing.
  This includes spot paths, withheld forecasts, perpetual stale/gap/cost guards,
  and the shared decision-support checks. No error suppression is used, and a
  missing crypto page test fails the gate.
- `validate-crypto.yml` runs those checks with read-only permissions on code
  changes and PRs. Its isolation regression runs without market/stock snapshots
  and injects failures into each safety check to prove they remain fatal.
- `validate-stock-assessment.yml` retains the full stock page/entry/model-display
  suite, including `test_technical_guide.cjs`. Its triggers also cover the market
  producer and the crypto workflow boundary change.
- `validate-market-context.yml` runs the offline Python→JavaScript contract
  replay and deterministic freshness cases, plus the existing live FRED check
  in a temporary directory. Neither validation workflow publishes snapshots.

Run the added regressions from the repository root:

```sh
python -m unittest discover -s scripts -p test_market_freshness_contract.py
node scripts/test_market_state.cjs
python -m unittest discover -s scripts -p test_crypto_validation_boundary.py
```

A passing PR check is not evidence of a successful production data publication.
Only a production run reaching the publish and dashboard steps establishes that.
