# Research-only point-in-time S&P 500 input boundary

This is an additive input layer, not another forecast experiment. `relative-v1`
and all earlier results remain frozen. There is no production import, model
training, ranking, trading-policy, scheduled collection or promotion change.

**Historical completeness is still blocked.** The branch has no certified
security-level historical baseline, complete membership/sector/alias history,
delisted price vintages or final full-lifecycle returns. The 503-security current
snapshot is quarantined. A source with a historical date in its title does not,
by itself, establish its original availability or absence of later revisions.

The input contract and validation work are usable now. The checked-in bundle
contains four real official notices, their exact downloaded bytes/hashes, eight
membership changes, contemporaneous sector labels, a verified SQ→XYZ alias
continuity observation and the unresolved WBA terminal event. These are **seed
observations, not a complete historical S&P 500 universe**. Nine provisional local
security IDs are deliberately not claimed to be permanent provider identities.

## Files and commands

| File | Purpose |
|---|---|
| `PROTOCOL.json` | Frozen clocks, population policy, limitations and next required inputs |
| `inputs.json` | Normalized source registry and independent baseline/event/coverage/price/outcome tables |
| `sources/` | Original HTML/PDF bytes plus quarantined copy of the earlier current snapshot |
| `origins.json` | The same 34 origin requests from the earlier source, without importing its survivor symbols or numeric outcomes |
| `manifest.json` | Bundle hashes and SHA256 of all 31 preserved earlier research files/scripts |
| `coverage-audit.json` | Exact replayable **blocked** report for all 34 origins; no new model metrics |
| `INPUT-CONTRACT.md` | Export/import requirements for an actual historical provider |
| `FINDINGS.md` | Korean handoff and explicit remaining data blocker |

From the repository root:

```sh
python -m unittest discover -s scripts -p test_pit_sp500_inputs.py -v
python scripts/build_pit_sp500_inputs.py --verify
python scripts/build_pit_sp500_inputs.py --export-cohorts
```

The first two commands must pass. The third **must exit 2 without writing
`origin-cohorts.json`** for this incomplete bundle. `--audit` writes a report once;
it may verify identical bytes on a rerun but cannot overwrite different bytes.
An audit success verifies the boundary and documents the blocker; it never means
the historical dataset is ready. The workflow has read-only permissions, no
schedule, no downloads, no writes to the branch and no production jobs.

## Two clocks and two populations

An origin is an explicit session date. Its cutoff is 09:30 in
`America/New_York`, converted using that date's DST offset. This is a cutoff
convention, not an exchange calendar; origins are not generated here.

- A record must have original `knownAt < cutoff` and `effectiveAt <= cutoff`.
- A date-only US notice is usable only from the next New York midnight, not
  from an invented publication time. Effective pre-open changes enter at that
  session's open. Day-only trading-cessation observations conservatively enter
  at the end of the stated local day and retain their precision in provenance.
- Sector and identity events have their own clocks. No current-sector fallback,
  backward fill, future removal date, future alias or future settlement value is
  included in an origin row. Corrections need their own availability timestamp
  and an explicit same-security/kind/effective-date supersession chain.
- A complete dated baseline and a complete change-history attestation are both
  required. The absence of an event is not evidence that no company exited.
  Partial snapshots cannot replace complete earlier populations.
- A downloaded historical export can be used for replay only when its records
  have evidenced original availability. `retrievedAt` remains the real download
  clock. Later certification of coverage is administrative metadata, not a
  predictive feature or a claim of live availability.

The origin population is frozen by security ID, separately from issuer and share
class. Both share classes of one issuer may coexist; CIK and ticker are not
security IDs. `security_for_symbol` is a dated lookup and fails on ambiguity.
An alias rename stays on one security only with evidence of continuity; a
merger/spinoff does not automatically become the acquiring/new security.

The evaluation population is the full frozen origin population through the
target date. `evaluation_ledger` is a **left join**, independent of target-date
membership. Missing/pending/delisting outcomes remain explicit rows. Dropping,
duplicating or replacing a security fails the population validator. Missing
labels or unresolved terminal rights block aggregate metrics. A genuinely zero
terminal wealth factor remains zero; price/log-ratio metrics cannot quietly
floor it or delete it. Daily prices and outcome labels use independent tables;
future outcomes never select the origin cohort.

## What remains before a new experiment

The coverage audit requests baseline/history evidence spanning the legacy
origins **2009-11-13 through 2025-10-31**. The input layer will refuse a supplier's
current-only composition, sector map, ticker list or revised-price history as a
replacement. In particular, historical membership alone is insufficient if
sector availability, permanent identities or delisting return coverage remains
unknown. Full coverage must come from evidenced exports or fully documented
historical reconstruction; no paid account, subscription or export was assumed.

The next experiment also needs a separately registered feature/lookback/freshness
and outcome protocol. This input layer only checks existence and chronology of
past prices, not whether a particular model's 252-day lookback is complete.
No market/excess-return decomposition model is fitted here.
