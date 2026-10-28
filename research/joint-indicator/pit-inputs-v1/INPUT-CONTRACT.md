# Normalized historical provider contract

Load an immutable bundle with `PITInputs.load(folder)`. The root `inputs.json`
must have `schemaVersion: 1`, `version: "sp500-pit-inputs-v1"` and the tables below.
The loader uses only the standard library. It does not scrape a current universe
or guess identifiers from a ticker. This is a provider-neutral normalized
boundary, not a claimed CRSP/Compustat/Norgate API adapter.

Create a new bundle/version for an actual provider export rather than replacing
the frozen official-notice seed. Include provider documentation, the exact
export request, original unmodified payloads, retrieval timestamps, checksums,
and a mapping from every normalized record to its original row/notice. Do not
equate a vendor's word "historical" with point-in-time availability.

## Source provenance

Every record references a `sourceId`. Each source has `uri`, relative `path`,
`sha256` of saved bytes, actual `retrievedAt`, `availabilityFloor`,
`availabilityEvidence` and `temporalQuality`. Compressed sources also specify
`compression: "gzip"` and `rawSha256`. Payloads must remain inside the bundle;
traversal, missing bytes and modified hashes fail. Real research data cannot
skip payload verification by loading an unverified in-memory object.

| Temporal quality | Additional evidence | Permitted use |
|---|---|---|
| `dated_notice` | `publicationPrecision` plus `publicationDate` or `publishedAt`; day precision uses next New York midnight | Observed individual facts and properly evidenced complete baseline snapshots, not complete change-history certification |
| `certified_point_in_time` | Named original `availabilityColumn`, its provider semantics and row-level original clock mapping | Historical records and documented completeness attestations |
| `current_only` | Availability cannot precede the actual retrieval | Quarantine/audit only; references from input tables or coverage are rejected |
| `synthetic` | Explicit fixture evidence; caller must opt in | Unit tests only; the checked-in loader never opts in |

Every baseline/event/price/outcome has explicit, timezone-aware `knownAt` and
`effectiveAt`. `knownAt` cannot precede the source's evidenced availability floor
or follow its frozen retrieval. It is not inferred from an effective date.
Original release/recorded-at evidence must be supplied by the exporter. A
researcher's download of a revised 2009 row in 2026 cannot give that revision a
2009 `knownAt` merely because its observation date is 2009.

## Tables

| Table | Required key/scope | Required content |
|---|---|---|
| `securities` | Unique immutable `securityId` | Provider permanent issue/security ID, including former/delisted lines; issuer and class are separate dated identity events |
| `baselines` | Unique `baselineId`, `indexId: "SP500"`, source and both clocks | Explicit security IDs, `completeness`, and for complete baselines `expectedSecurityCount == len(members)` plus `coverageEvidence` |
| `events` | Unique `eventId`, `securityId`, `kind`, source and both clocks | Membership, sector, symbol, identity or terminal observation; row/notice locator retained as `evidenceLocator` |
| `coverage` | Unique `coverageId`, `indexId: "SP500"`, source | Half-open `from` / `throughExclusive` timestamps, `domains`, `completeness`, `coverageEvidence` documenting the provider's coverage contract and gaps |
| `prices` | Security/date/original availability vintage | `sessionDate`, source and both clocks, finite nonnegative `close`, `basis` equal to `unadjusted` or `point_in_time_adjusted` |
| `outcomes` | Security/origin/target/original availability vintage | Separate future labels, explicit status and source; full-lifecycle resolved returns only |

Complete coverage is needed independently for `membership`, `sector`, `symbol`,
`identity`, `delisting` and `prices`. It cannot extend beyond the actual source
retrieval. A count of observed events, a current row count of 500/503, an old
universe plus incomplete deletes, or a successful ticker-price download is not
proof of completeness. Coverage attestations are administrative information;
the per-record original knowledge filter is still applied at each origin.

Event `value` is:

| Kind | Value and rules |
|---|---|
| `membership` | Boolean, and `indexId: "SP500"`; false records removal without deleting the security registry or prior cohorts |
| `sector` | `{name, taxonomy, taxonomyVersion}`; an origin cannot use a later change to GICS or company classification |
| `symbol` | `{symbol, venue}`; `symbol: null` explicitly retires an alias; symbol/venue conflicts fail rather than splice security histories |
| `identity` | `{issuerId, shareClass, verified: true}` with original availability evidence; CIK alone does not distinguish a security/share class |
| `delisting` | `{reason, settlementStatus}`; retain observed cash, exchange terms, distributions, and unresolved contingent rights in additional fields |

Corrections use `supersedes: priorEventId`, strictly later `knownAt`, the same
security/kind/effective timestamp and a new source locator. A correction cannot
rewrite cohorts formed before the correction was available. Simultaneous
conflicting facts are rejected; an exporter must resolve or explicitly mark
ambiguity, not choose a convenient ticker or current sector.

Do not create an `identity` event for a guessed merger successor. Validate
PERMNO/GVKEY+IID or equivalent security continuity against the provider's actual
corporate-action history. Keep issuer changes and share classes explicit. If a
symbol-only source cannot be mapped uniquely at the observation date, keep the
missing identity blocker. New aliases cannot rescue a historical unresolved row
by being assumed to have existed before their effective/known timestamps.

## Return lifecycle and missing labels

A ready outcome must have:

```json
{
  "securityId": "provider-permanent-security-id",
  "origin": "2020-01-02",
  "targetDate": "2020-12-31",
  "effectiveAt": "2020-12-31T21:00:00Z",
  "knownAt": "2021-01-01T00:00:00Z",
  "sourceId": "registered-export",
  "status": "ready",
  "totalReturnFactor": 1.1,
  "basis": "total_return_with_distributions_and_delisting",
  "lifecycleComplete": true
}
```

This example is a schema example, not a real observation. The importer must
document dividend/corporate-action adjustment, delisting return, merger
consideration, residual holdings/rights, and treatment of proceeds from
termination until the fixed horizon. **This layer does not calculate those
returns from last closes or cash headline amounts.** Resolve the entire
security's lifecycle under a preregistered outcome policy before marking it ready.

Statuses `missing` and `unresolved_delisting` require a null/absent numeric return.
The ledger also generates `pending_outcome` and `missing_outcome` where no usable
label exists. An unresolved terminal event takes precedence over an apparently
ready vendor ratio until a evidenced correction resolves settlement. A true
terminal factor of zero is valid and retained, with price/log-ratio metrics
explicitly unavailable. No clipping to positive values or survivor-only metrics.

Use `snapshot(origin)` to freeze an eligible full input cohort, and
`evaluation_ledger(cohort, targetDate, evaluatedAt)` to join labels. The latter
cannot run on an incomplete cohort or a modified cohort hash. Always validate
the complete output population using `assert_evaluation_population`; never
filter `status != ready` out before checking completeness.

## Integration boundary

`snapshot(require_complete=False)` is a diagnostic preview only. Its observed
rows are not a universe for fitting or scoring. CLI `--export-cohorts` requires
all requested origins to pass. Full input readiness would still not authorize a
new model: this frozen input-only protocol keeps `modelTrainingAllowed: false`
and `productionChangesAllowed: false`. Register a separate next experiment,
including exchange calendar, feature freshness/lookback, label definitions,
maturity, weighting and pairing rules, after the data blocker is actually closed.
